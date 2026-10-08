import json
import plistlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agentdock.migration import import_agentmeter
from agentdock.store import Store


class MigrationTests(unittest.TestCase):
    def test_import_preserves_existing_records_dates_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefs = root / "source.plist"
            date = (
                datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
                - datetime(2001, 1, 1, tzinfo=timezone.utc)
            ).total_seconds()
            original = plistlib.dumps(
                {
                    "subscriptions": json.dumps(
                        [
                            {"provider": "codex", "plan": "Old", "monthlyCost": 100},
                            {
                                "provider": "claude",
                                "plan": "Pro",
                                "currency": "USD",
                                "monthlyCost": 20,
                                "renewalDate": date,
                            },
                            {"provider": "manual", "name": "Other"},
                        ]
                    ).encode(),
                    "snapshots": b"private old cache",
                }
            )
            prefs.write_bytes(original)
            store = Store(":memory:")
            try:
                store.save_subscription("codex", "Keep me", monthly_cost=7)
                result = import_agentmeter(store, prefs, root)
                self.assertEqual(result, {"imported": 1, "skipped": 2})
                records = {r["provider"]: r for r in store.state()["subscriptions"]}
                self.assertEqual(records["codex"]["plan"], "Keep me")
                self.assertEqual(records["claude"]["renewal_date"], "2026-10-05")
                self.assertEqual(records["claude"]["monthly_cost"], 20)
                self.assertEqual(store.state()["quotas"], [])
                backup = root / "backups/agentmeter-preferences.plist"
                self.assertEqual(backup.read_bytes(), original)
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                self.assertEqual(import_agentmeter(store, prefs, root)["imported"], 0)
                self.assertEqual(prefs.read_bytes(), original)
            finally:
                store.close()

    def test_expiry_date_is_not_imported_as_renewal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefs = root / "source.plist"
            prefs.write_bytes(
                plistlib.dumps(
                    {
                        "subscriptions": json.dumps(
                            [
                                {
                                    "provider": "claude",
                                    "renewalKind": "expires",
                                    "renewalDate": 810000000,
                                }
                            ]
                        ).encode()
                    }
                )
            )
            store = Store(":memory:")
            try:
                import_agentmeter(store, prefs, root)
                self.assertIsNone(store.state()["subscriptions"][0]["renewal_date"])
            finally:
                store.close()
