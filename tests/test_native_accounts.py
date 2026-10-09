"""Native switching tests use temporary files and an in-memory fake client only."""

import base64
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from agentdock.accounts import AccountError, AccountManager
from agentdock.native_accounts import (
    MacClients,
    NativeAccounts,
    _codex_identity,
    _desktop_token,
    _encode,
)


class Client:
    def __init__(self, identity):
        self.current = {"identity": identity, "auth": "private-native-token"}
        self.history = []
        self.fail_write = 0

    def stop(self, client):
        self.history.append("stop")
        return True

    def start(self, client):
        self.history.append("start")

    def ensure_idle(self, client):
        self.history.append("idle")

    def read(self, client):
        return copy.deepcopy(self.current)

    def identity(self, client, value, online=False):
        return value["identity"]

    def write(self, client, value):
        self.history.append("write")
        self.current = copy.deepcopy(value)
        if self.fail_write:
            self.fail_write -= 1
            raise OSError("private-native-token must not reach the API")


class FixtureVault:
    """In-memory fixture; real authenticated encryption is checked in Swift."""

    def __init__(self):
        self.values = {}

    def available(self):
        return True

    def seal(self, data, context):
        handle = uuid.uuid4().hex
        self.values[(handle, context)] = data
        return handle

    def unseal(self, data, context):
        return self.values[(data, context)]


class NativeSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.mac = patch("agentdock.native_accounts.sys.platform", "darwin")
        self.mac.start()
        self.account = {
            "id": str(uuid.uuid4()),
            "provider": "codex",
            "environment_id": "local",
            "identity": {"email": "one@example.test"},
        }
        self.identity = {"email": "one@example.test", "account_id": "native-one"}
        self.client = Client(self.identity)
        self.manager = AccountManager(self.root / "accounts")
        self.native = NativeAccounts(self.manager, self.client, FixtureVault())

    def tearDown(self):
        self.mac.stop()
        self.temp.cleanup()

    def capture(self):
        self.native.capture(self.account, "codex")

    def test_capture_is_explicit_and_does_not_export_managed_credentials(self):
        self.native.status(self.account)
        self.assertEqual(self.client.history, [])
        self.capture()
        self.assertEqual(self.client.history, ["stop", "start"])
        public = self.native.status(self.account)
        self.assertTrue(public["clients"][0]["saved"])
        self.assertNotIn("private-native-token", json.dumps(public))
        self.assertEqual(
            self.native._path(self.account["id"], "codex").stat().st_mode & 0o777, 0o600
        )
        self.assertFalse((self.manager.root / self.account["id"] / "codex").exists())
        self.assertNotIn(
            "private-native-token",
            self.native._path(self.account["id"], "codex").read_text(),
        )

    def test_old_plaintext_snapshots_and_recovery_journals_are_migrated(self):
        for path in (
            self.native._path(self.account["id"], "codex"),
            self.native.root / "previous.json",
            self.native.root / "pending.json",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            value = {
                "identity": self.identity,
                "snapshot": self.client.read("codex"),
                "client": "codex",
            }
            path.write_text(json.dumps(value))
        self.native.protect_legacy()
        for path in self.native.root.rglob("*.json"):
            self.assertNotIn("private-native-token", path.read_text())
            self.assertEqual(json.loads(path.read_text())["schema"], 2)
            self.assertEqual(self.native._load(path)["snapshot"], self.client.current)

    def test_status_reads_public_metadata_while_a_switch_owns_the_lock(self):
        self.capture()
        with (
            self.native._lock(),
            patch.object(
                self.native,
                "protect_legacy",
                side_effect=AssertionError("migration in status"),
            ),
            patch.object(
                self.native.vault,
                "unseal",
                side_effect=AssertionError("decrypt in status"),
            ),
            patch.object(
                self.native.vault, "seal", side_effect=AssertionError("write in status")
            ),
        ):
            status = self.native.status(self.account)
            self.assertTrue(status["clients"][0]["saved"])
            self.assertEqual(status["clients"][0]["identity"], self.identity)

    def test_startup_skips_corrupt_snapshots_and_migrates_healthy_ones(self):
        bad = self.native._path(self.account["id"], "codex")
        bad.parent.mkdir(parents=True)
        bad.write_text("private-token invalid json")
        pending = self.native.root / "pending.json"
        pending.write_text("[]")
        healthy = self.native.root / "previous.json"
        healthy.write_text(
            json.dumps(
                {
                    "identity": self.identity,
                    "snapshot": self.client.current,
                    "client": "codex",
                }
            )
        )
        with patch("agentdock.native_accounts.failure") as log:
            native = NativeAccounts(self.manager, self.client, self.native.vault)
            status = native.status(self.account)
            self.assertFalse(status["clients"][0]["saved"])
            self.assertTrue(status["recovery_needed"])
            self.assertEqual(status["recovery_client"], "codex")
            self.assertGreaterEqual(log.call_count, 2)
            self.assertTrue(
                all(call.args[1] == "accounts" for call in log.call_args_list)
            )
        self.assertEqual(bad.read_text(), "private-token invalid json")
        self.assertEqual(pending.read_text(), "[]")
        self.assertEqual(json.loads(healthy.read_text())["schema"], 2)
        with self.assertRaises(ValueError):
            native._load(bad)
        self.assertEqual(self.client.history, [])

    def test_startup_can_defer_migration_while_another_process_owns_the_lock(self):
        with self.native._lock(), patch("agentdock.native_accounts.failure") as log:
            native = NativeAccounts(self.manager, self.client, self.native.vault)
            self.assertTrue(native.status(self.account)["available"])
            log.assert_called_once()
        self.assertEqual(self.client.history, [])

    def test_cannot_switch_before_capture_or_use_wrong_provider_device_identity(self):
        with self.assertRaises(AccountError):
            self.native.switch(self.account, "codex")
        self.assertEqual(self.client.history, [])
        for changes, client in (
            ({"environment_id": "remote"}, "codex"),
            ({}, "../escape"),
            ({}, "claude_code"),
            ({"identity": {"email": "wrong@example.test"}}, "codex"),
        ):
            with self.assertRaises(AccountError):
                self.native.capture({**self.account, **changes}, client)
        self.assertNotIn("write", self.client.history)

    def test_switch_verifies_storage_and_can_restore_previous_login(self):
        self.capture()
        self.client.current = {
            "identity": {"email": "two@example.test", "account_id": "native-two"},
            "auth": "old",
        }
        previous = self.client.read("codex")
        result = self.native.switch(self.account, "codex")
        self.assertEqual(self.client.current["identity"], self.identity)
        self.assertEqual(result["login_confirmation"], "client_required")
        self.assertEqual(result["recovery_client"], "codex")
        self.native.recover(self.account, "codex")
        self.assertEqual(self.client.current, previous)

    def test_latest_rotated_native_token_is_saved_before_leaving(self):
        self.capture()
        self.client.current["auth"] = "rotated"
        self.native.switch(self.account, "codex")
        self.assertEqual(self.client.current["auth"], "rotated")

    def test_partial_write_rolls_back_and_failed_rollback_keeps_recovery(self):
        self.capture()
        self.client.current = {"identity": self.identity, "auth": "rotated"}
        previous = copy.deepcopy(self.client.current)
        self.client.fail_write = 1
        with self.assertRaises(OSError):
            self.native.switch(self.account, "codex")
        self.assertEqual(self.client.current, previous)
        self.assertFalse(self.native.status(self.account)["recovery_needed"])
        self.client.fail_write = 2
        with self.assertRaisesRegex(AccountError, "Recover"):
            self.native.switch(self.account, "codex")
        self.assertTrue(self.native.status(self.account)["recovery_needed"])
        with self.assertRaises(AccountError):
            self.native.switch(self.account, "codex")
        self.client.fail_write = 1
        self.client.history.clear()
        with self.assertRaises(OSError):
            self.native.recover(self.account, "codex")
        self.assertNotIn("start", self.client.history)
        self.assertTrue(self.native.status(self.account)["recovery_needed"])
        self.native.recover(self.account, "codex")
        self.assertFalse(self.native.status(self.account)["recovery_needed"])

    def test_busy_native_cli_never_gets_killed_or_written(self):
        self.capture()
        self.client.stop = Mock(side_effect=AccountError("busy"))
        with self.assertRaises(AccountError):
            self.native.switch(self.account, "codex")
        self.assertNotIn("write", self.client.history)

    def test_external_login_change_before_write_is_never_rolled_back(self):
        self.capture()

        def changed(_):
            self.client.current["auth"] = "new-external-login"

        self.client.ensure_idle = changed
        with self.assertRaisesRegex(AccountError, "login changed"):
            self.native.switch(self.account, "codex")
        self.assertEqual(self.client.current["auth"], "new-external-login")
        self.assertNotIn("write", self.client.history)
        self.assertFalse(self.native.status(self.account)["recovery_needed"])

    def test_symlink_native_snapshot_rejected(self):
        self.capture()
        path = self.native._path(self.account["id"], "codex")
        path.unlink()
        path.symlink_to(self.root / "other")
        with self.assertRaises(AccountError):
            self.native.status(self.account)

    def test_removal_keeps_active_client_and_managed_history_untouched(self):
        self.capture()
        before = copy.deepcopy(self.client.current)
        self.native.remove(self.account)
        self.assertEqual(self.client.current, before)
        self.assertFalse(self.native.status(self.account)["clients"][0]["saved"])


class NativeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.clients = MacClients(home=self.home, environment={})
        self.keychain = patch("agentdock.native_accounts.Keychain")
        self.key = self.keychain.start().return_value
        self.key.read.return_value = None

    def tearDown(self):
        self.keychain.stop()
        self.temp.cleanup()

    def test_desktop_only_auth_fields_and_both_cookie_layouts_change(self):
        home = self.home / "Library/Application Support/Claude"
        home.mkdir(parents=True)
        config = {
            "oauth:tokenCacheV2": "encrypted-one",
            "lastKnownAccountUuid": "one",
            "workspace": {"egressProxyUrl": "http://localhost:7897"},
            "other": "retained",
        }
        (home / "config.json").write_text(json.dumps(config))
        (home / "Cookies").write_bytes(b"cookie-one")
        (home / "Network").mkdir()
        (home / "Network/Cookies").write_bytes(b"cookie-two")
        history = home / "claude-code-sessions"
        history.mkdir()
        (history / "history").write_text("keep")
        first = self.clients.read("claude_desktop")
        second = copy.deepcopy(first)
        second["config"]["lastKnownAccountUuid"] = "two"
        second["config"]["oauth:tokenCacheV2"] = "encrypted-two"
        second["cookies"]["Cookies"] = _encode(b"other")
        self.clients.write("claude_desktop", second)
        result = json.loads((home / "config.json").read_text())
        self.assertEqual(result["workspace"], config["workspace"])
        self.assertEqual(result["other"], "retained")
        self.assertEqual((history / "history").read_text(), "keep")
        self.assertEqual(self.clients.read("claude_desktop"), second)
        self.clients.write("claude_desktop", first)
        self.assertEqual(self.clients.read("claude_desktop"), first)

    def test_codex_config_and_history_are_not_replaced(self):
        home = self.home / ".codex"
        home.mkdir()
        config = b'cli_auth_credentials_store = "file"\nmodel = "unchanged"\n'
        (home / "config.toml").write_bytes(config)
        (home / "auth.json").write_text('{"old":true}')
        (home / "history.jsonl").write_text("keep")
        value = self.clients.read("codex")
        value["auth"] = _encode(b'{"new":true}')
        self.clients.write("codex", value)
        self.assertEqual((home / "config.toml").read_bytes(), config)
        self.assertEqual((home / "history.jsonl").read_text(), "keep")
        self.key.read.assert_not_called()

    def test_toml_quoted_keys_and_tables_cannot_hide_native_store_policy(self):
        home = self.home / ".codex"
        home.mkdir()
        path = home / "config.toml"
        path.write_text(
            '\x22cli_auth_credentials_store\x22 = "file"\n[other]\nmodel_provider = "relay"\n'
        )
        self.assertEqual(self.clients._codex_store()[0], "file")
        for contents in (
            'model_provider = "relay"\n',
            "cli_auth_credentials_store = true\n",
            "[invalid",
        ):
            path.write_text(contents)
            with self.assertRaises(AccountError):
                self.clients._codex_store()

    def test_claude_code_proxy_and_unrelated_metadata_remain(self):
        home = self.home / ".claude"
        home.mkdir()
        settings = b'{"env":{"HTTPS_PROXY":"http://localhost:7897"}}'
        (home / "settings.json").write_bytes(settings)
        (self.home / ".claude.json").write_text(
            '{"oauthAccount":{"accountUuid":"old"},"theme":"dark"}'
        )
        value = self.clients.read("claude_code")
        value["oauthAccount"] = {"accountUuid": "new"}
        value["keychain"] = _encode(b'{"claudeAiOauth":{"accessToken":"fixture"}}')
        self.clients.write("claude_code", value)
        self.assertEqual((home / "settings.json").read_bytes(), settings)
        self.assertEqual(
            json.loads((self.home / ".claude.json").read_text())["theme"], "dark"
        )
        self.key.write.assert_called_once()

    def test_relay_and_keychain_denial_cannot_fall_back_to_stale_credentials(self):
        self.clients.environment["ANTHROPIC_AUTH_TOKEN"] = "fixture"
        with self.assertRaisesRegex(AccountError, "Relay"):
            self.clients.read("claude_code")
        self.clients.environment.clear()
        self.key.read.side_effect = ValueError("denied")
        with self.assertRaises(ValueError):
            self.clients.read("claude_code")

    def test_codex_identity_includes_account_id_and_rejects_api_key(self):
        claims = (
            base64.urlsafe_b64encode(
                json.dumps({"email": "person@example.test"}).encode()
            )
            .decode()
            .rstrip("=")
        )
        value = {
            "tokens": {"id_token": "header." + claims + ".sig", "account_id": "org-one"}
        }
        self.assertEqual(_codex_identity(value)["account_id"], "org-one")
        with self.assertRaises(AccountError):
            _codex_identity({**value, "OPENAI_API_KEY": "fixture"})
        encoded = _encode(json.dumps(value).encode())
        with self.assertRaises(AccountError):
            self.clients.identity(
                "codex", {"mode": "keyring", "keychain": None, "auth": encoded}
            )
        self.assertEqual(
            self.clients.identity(
                "codex", {"mode": "auto", "keychain": None, "auth": encoded}
            )["account_id"],
            "org-one",
        )

    @unittest.skipUnless(
        sys.platform == "darwin" and shutil.which("openssl"), "macOS crypto fixture"
    )
    def test_desktop_safestorage_fixture_decrypts_without_real_keychain(self):
        password = b"fictional-fixture-password"
        self.key.read.return_value = password
        key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
        payload = {
            "acct:one|client:org:audience:user:profile": {
                "token": "fictional-access-token",
                "expiresAt": 4000000000000,
            },
            "acct:other|client:org:audience:user:profile": {
                "token": "other-token",
                "expiresAt": 5000000000000,
            },
        }
        encrypted = subprocess.run(
            ["openssl", "enc", "-aes-128-cbc", "-K", key.hex(), "-iv", "20" * 16],
            input=json.dumps(payload).encode(),
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(
            _desktop_token(_encode(b"v10" + encrypted), "one"), "fictional-access-token"
        )
        self.key.read.assert_called_once_with("Claude Safe Storage", "Claude")


if __name__ == "__main__":
    unittest.main()
