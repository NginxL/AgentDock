import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.account_keychain import KeychainError
from agentdock.account_network import NetworkError
from agentdock.accounts import AccountError
from agentdock.errors import PublicError
from agentdock.runtime import Runtime
from agentdock.server import API
from agentdock.store import Store


class AccountPublicErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name).resolve() / "db.sqlite3")
        self.addCleanup(self.store.close)
        self.broker = patch("agentdock.credential_broker.available", return_value=False)
        self.broker.start()
        self.addCleanup(self.broker.stop)
        self.runtime = Runtime(self.store, {"execution_enabled": True, "commands": {}})
        self.addCleanup(self.runtime.close)
        self.api = API(self.store, self.runtime, None, "admin", 47831, True)
        self.addCleanup(self.api.close)
        self.headers = {
            "Host": "127.0.0.1:47831",
            "Authorization": "Bearer admin",
            "Content-Type": "application/json",
        }
        self.store.set_feature("native_switching", True, True)
        self.account = self.store.add_account("codex", "Work", "local", 0)
        self.route = f"/api/accounts/{self.account['id']}/native"

    def call(self):
        return self.api.dispatch(
            "POST",
            self.route,
            self.headers,
            json.dumps({"operation": "capture", "client": "codex"}).encode(),
        )

    def test_capture_without_desktop_returns_actionable_error_and_code(self):
        with (
            patch("agentdock.native_accounts.sys.platform", "darwin"),
            patch("subprocess.Popen") as process,
        ):
            self.assertEqual(
                self.call(),
                (
                    400,
                    {
                        "error": "Open AgentDock desktop to use protected native credentials.",
                        "code": "native_credentials_desktop_required",
                    },
                ),
            )
            process.assert_not_called()

    def test_public_account_errors_keep_valueerror_compatibility_and_codes(self):
        for error, code in (
            (
                AccountError(
                    "Cancel the active login before removing this account.",
                    code="account_login_active",
                ),
                "account_login_active",
            ),
            (AccountError("Account storage is invalid."), "account_error"),
            (KeychainError(), "keychain_unavailable"),
            (NetworkError("network_unavailable"), "network_unavailable"),
        ):
            with (
                self.subTest(code=code),
                patch.object(self.runtime.accounts, "native_action", side_effect=error),
            ):
                self.assertIsInstance(error, (ValueError, PublicError))
                self.assertIsInstance(error, ValueError)
                self.assertIsInstance(error, PublicError)
                self.assertEqual(
                    self.call(), (400, {"error": str(error), "code": code})
                )

    def test_unclassified_value_errors_do_not_expose_private_text(self):
        with patch.object(
            self.runtime.accounts,
            "native_action",
            side_effect=ValueError("private-token"),
        ):
            self.assertEqual(
                self.call(),
                (400, {"error": "Invalid request", "code": "invalid_request"}),
            )
