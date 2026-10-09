import tempfile
import unittest
import uuid
from pathlib import Path

from agentdock.account_network import claude_network
from agentdock.accounts import AccountManager


class AccountNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.wrapper = self.root / "claude"
        self.native = self.root / "native"
        self.native.write_bytes(b"fixture executable")

    def test_literal_launcher_proxy_is_shared_and_never_written_back(self):
        self.wrapper.write_text(
            '#!/bin/sh\nexport HTTPS_PROXY="http://127.0.0.1:7897"\n'
            'export https_proxy="http://127.0.0.1:7897"\nexec "'
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
        network = claude_network(source, [str(self.wrapper)])
        self.assertEqual(network["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(network["CLAUDE_CODE_CLIENT_CERT"], "/cert")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", network)
        self.assertEqual(source, before)
        self.assertEqual(self.wrapper.read_bytes(), contents)

    def test_dynamic_wrapper_is_left_to_cli_and_never_executed(self):
        marker = self.root / "must-not-exist"
        self.wrapper.write_text(f'#!/bin/sh\nexport HTTPS_PROXY=$(touch "{marker}")\n')
        environment = {
            "CLAUDE_CONFIG_DIR": str(self.root),
            "HTTPS_PROXY": "http://inherited",
        }
        self.assertEqual(
            claude_network(environment, [str(self.wrapper)]),
            {"HTTPS_PROXY": "http://inherited"},
        )
        self.assertFalse(marker.exists())

    def test_settings_copy_only_network_values_with_existing_precedence(self):
        settings = self.root / "settings.json"
        contents = '{"env":{"HTTPS_PROXY":"http://configured","NODE_EXTRA_CA_CERTS":"/cert","ANTHROPIC_AUTH_TOKEN":"private"}}'
        settings.write_text(contents)
        values = claude_network(
            {"CLAUDE_CONFIG_DIR": str(self.root), "HTTPS_PROXY": "http://parent"}
        )
        self.assertEqual(
            values, {"HTTPS_PROXY": "http://parent", "NODE_EXTRA_CA_CERTS": "/cert"}
        )
        self.assertEqual(settings.read_text(), contents)

    def test_client_tls_dns_flags_survive_isolated_account_environment(self):
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
