import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from agentdock.account_keychain import KeychainError, claude_credentials, claude_service
from agentdock.account_network import (
    NetworkError,
    _NoRedirect,
    claude_get,
    claude_network,
)
from agentdock.accounts import AccountManager


class AccountNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.wrapper = self.root / "claude"
        self.native = self.root / "native"
        self.native.write_bytes(b"fixture executable")

    def tearDown(self):
        self.temp.cleanup()

    def test_literal_launcher_proxy_is_shared_and_never_written_back(self):
        self.wrapper.write_text(
            '#!/bin/sh\nexport HTTPS_PROXY="http://127.0.0.1:7897"\nexport https_proxy="http://127.0.0.1:7897"\nexec "'
            + str(self.native)
            + '" "$@"\n'
        )
        source = {
            "HTTPS_PROXY": "http://different:9999",
            "CLAUDE_CONFIG_DIR": str(self.root),
            "CLAUDE_CODE_CLIENT_CERT": "/cert",
            "ANTHROPIC_AUTH_TOKEN": "private",
        }
        before = dict(source)
        contents = self.wrapper.read_bytes()
        network = claude_network(source, [str(self.wrapper)], strict=True)
        self.assertEqual(network["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(network["CLAUDE_CODE_CLIENT_CERT"], "/cert")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", network)
        self.assertEqual(source, before)
        self.assertEqual(self.wrapper.read_bytes(), contents)

    def test_dynamic_wrapper_is_not_executed_or_replaced_with_direct_access(self):
        for script in (
            "export HTTPS_PROXY=$(read-secret)",
            "source ~/.custom-proxy",
            'if true; then export HTTPS_PROXY="http://proxy"; fi',
        ):
            self.wrapper.write_text("#!/bin/sh\n" + script + "\n")
            with self.assertRaises(NetworkError):
                claude_network(
                    {"CLAUDE_CONFIG_DIR": str(self.root)},
                    [str(self.wrapper)],
                    strict=True,
                )

    def test_client_tls_dns_flags_survive_isolated_account_environment(self):
        import uuid

        env = {
            "CLAUDE_CONFIG_DIR": str(self.root),
            "CLAUDE_CODE_CLIENT_CERT": "/cert",
            "CLAUDE_CODE_CLIENT_KEY": "/key",
            "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE": "private",
            "CLAUDE_CODE_PROXY_RESOLVES_HOSTS": "1",
            "CLAUDE_CODE_OAUTH_TOKEN": "not-inherit",
        }
        manager = AccountManager(self.root / "accounts", {"claude": [str(self.native)]})
        result = manager.environment(
            {"id": str(uuid.uuid4()), "provider": "claude"}, env
        )
        for key in (
            "CLAUDE_CODE_CLIENT_CERT",
            "CLAUDE_CODE_CLIENT_KEY",
            "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
            "CLAUDE_CODE_PROXY_RESOLVES_HOSTS",
        ):
            self.assertEqual(result[key], env[key])
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", result)

    def test_proxy_failure_never_retries_direct_and_does_not_leak_tokens(self):
        opener = Mock()
        opener.open.side_effect = URLError("private-proxy-password")
        with patch(
            "agentdock.account_network.build_opener", return_value=opener
        ) as builder:
            with self.assertRaises(NetworkError) as error:
                claude_get(
                    "usage", "private-token", {"https_proxy": "http://127.0.0.1:7897"}
                )
        self.assertEqual(str(error.exception), "network_unavailable")
        opener.open.assert_called_once()
        self.assertEqual(
            builder.call_args.args[0].proxies["https"], "http://127.0.0.1:7897"
        )
        self.assertNotIn("private-token", str(error.exception))

    def test_proxy_handler_ignores_unrelated_service_no_proxy(self):
        response = Mock()
        response.read.return_value = b"{}"
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch(
            "agentdock.account_network.build_opener", return_value=opener
        ) as builder:
            claude_get("usage", "fixture", {"HTTPS_PROXY": "http://127.0.0.1:7897"})
            handler = builder.call_args.args[0]
            with patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}):
                request = Request("https://api.anthropic.com/api/oauth/usage")
                handler.proxy_open(request, "http://127.0.0.1:7897", "https")
                self.assertEqual(request.host, "127.0.0.1:7897")
                self.assertEqual(request._tunnel_host, "api.anthropic.com")
            claude_get(
                "usage",
                "fixture",
                {
                    "HTTPS_PROXY": "http://127.0.0.1:7897",
                    "NO_PROXY": "api.anthropic.com",
                },
            )
            self.assertEqual(builder.call_args.args[0].proxies, {})

    def test_rate_limit_respects_retry_header_and_redirect_refuses_auth_forwarding(
        self,
    ):
        opener = Mock()
        opener.open.side_effect = HTTPError(
            "unused", 429, "private", {"Retry-After": "120"}, None
        )
        with patch("agentdock.account_network.build_opener", return_value=opener):
            with self.assertRaises(NetworkError) as error:
                claude_get("usage", "private", {})
        self.assertEqual(
            (error.exception.code, error.exception.retry_after), ("rate_limited", 120)
        )
        with self.assertRaises(NetworkError):
            _NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere")

    def test_keychain_namespace_matches_cli_and_denial_does_not_read_stale_file(self):
        self.assertEqual(
            claude_service(
                {
                    "CLAUDE_SECURESTORAGE_CONFIG_DIR": "",
                    "CLAUDE_CONFIG_DIR": "/else",
                    "USER": "test",
                }
            ),
            ("Claude Code-credentials", "test"),
        )
        one = claude_service({"CLAUDE_CONFIG_DIR": "/test", "USER": "test"})
        two = claude_service({"CLAUDE_CONFIG_DIR": "/test/", "USER": "test"})
        self.assertNotEqual(one, two)
        (self.root / ".credentials.json").write_text('{"stale":true}')
        with (
            patch("agentdock.account_keychain.sys.platform", "darwin"),
            patch("agentdock.account_keychain.Keychain") as keychain,
        ):
            keychain.return_value.read.side_effect = KeychainError()
            with self.assertRaises(KeychainError):
                claude_credentials({"CLAUDE_CONFIG_DIR": str(self.root)})


if __name__ == "__main__":
    unittest.main()
