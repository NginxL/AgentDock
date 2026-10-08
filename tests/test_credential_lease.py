import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.credential_lease import catalog_home, credentials
from agentdock.errors import Conflict


class CredentialLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.native = self.root / "native"
        self.target = self.root / "session"
        self.auth = self.native / ".gemini/oauth_creds.json"
        self.auth.parent.mkdir(parents=True)
        self.auth.write_text('{"refresh_token":"fixture-original"}')
        self.settings = self.auth.with_name("settings.json")
        self.settings.write_text('{"proxy":"fixture-fixed-proxy"}')
        self.env = {"HOME": str(self.native), "HTTPS_PROXY": "http://127.0.0.1:1234"}

    def tearDown(self):
        self.temp.cleanup()

    def lease(self):
        return credentials("gemini", self.target, self.env, threading.Event())

    def test_refresh_copied_back_settings_unchanged_and_idle_seeds_removed(self):
        with self.lease() as environment:
            self.assertEqual(environment["HTTPS_PROXY"], self.env["HTTPS_PROXY"])
            (self.target / ".gemini/oauth_creds.json").write_text(
                '{"refresh_token":"fixture-refreshed"}'
            )
            (self.target / ".gemini/settings.json").write_text("must not propagate")
        self.assertIn("fixture-refreshed", self.auth.read_text())
        self.assertIn("fixture-fixed-proxy", self.settings.read_text())
        self.assertFalse((self.target / ".gemini/oauth_creds.json").exists())
        self.assertFalse((self.target / ".gemini/settings.json").exists())
        self.assertEqual(list(self.native.rglob("pending.json")), [])

    def test_copy_failure_is_recoverable_without_losing_refreshed_credentials(self):
        with (
            self.assertRaises(OSError),
            patch("agentdock.credential_lease.replace", side_effect=OSError("fixture")),
        ):
            with self.lease():
                (self.target / ".gemini/oauth_creds.json").write_text("refreshed")
        self.assertTrue(list(self.native.rglob("pending.json")))
        with self.lease():
            self.assertEqual(
                (self.target / ".gemini/oauth_creds.json").read_text(), "refreshed"
            )
        self.assertEqual(self.auth.read_text(), "refreshed")
        self.assertFalse((self.target / ".gemini/oauth_creds.json").exists())

    def test_external_login_is_not_overwritten(self):
        with self.assertRaises(Conflict):
            with self.lease():
                self.auth.write_text("external login")
                (self.target / ".gemini/oauth_creds.json").write_text("run refresh")
        self.assertEqual(self.auth.read_text(), "external login")
        self.assertTrue(list(self.native.rglob("pending.json")))
        with self.assertRaises(Conflict):
            with self.lease():
                self.fail("A conflicting refresh must remain blocked")

    def test_credentials_removed_after_cli_error(self):
        with self.assertRaises(RuntimeError):
            with self.lease():
                raise RuntimeError("fixture CLI failure")
        self.assertFalse((self.target / ".gemini/oauth_creds.json").exists())

    def test_legacy_divergent_copy_is_preserved_without_overwriting_native_login(self):
        cached = self.target / ".gemini/oauth_creds.json"
        cached.parent.mkdir(parents=True)
        cached.write_text("legacy refreshed token")
        with self.assertRaises(Conflict), self.lease():
            self.fail("Unknown legacy refresh must require reconciliation")
        self.assertEqual(cached.read_text(), "legacy refreshed token")
        self.assertIn("fixture-original", self.auth.read_text())

    def test_catalog_refresh_recovery_outlives_disposable_workspace(self):
        self.target = catalog_home("gemini", self.env)
        with tempfile.TemporaryDirectory() as workspace:
            with (
                self.assertRaises(OSError),
                patch(
                    "agentdock.credential_lease.replace", side_effect=OSError("fixture")
                ),
            ):
                with self.lease():
                    (self.target / ".gemini/oauth_creds.json").write_text(
                        "discovery refreshed"
                    )
        self.assertFalse(Path(workspace).exists())
        with self.lease():
            self.assertEqual(
                (self.target / ".gemini/oauth_creds.json").read_text(),
                "discovery refreshed",
            )
        self.assertEqual(self.auth.read_text(), "discovery refreshed")
