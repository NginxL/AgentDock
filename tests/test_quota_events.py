"""C1 acceptance uses real stores and synthetic CLI events, never real logins."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from agentdock.providers import _Callbacks, _Claude
from agentdock.quota import QuotaService
from agentdock.quota_events import observe
from agentdock.runtime import Runtime, _Run
from agentdock.store import Invalid, Store


class Pipe:
    def __init__(self, rows):
        self.rows = iter(rows)

    def next(self):
        return next(self.rows)

    def send(self, _):
        pass


class QuotaEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / "state.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.close())
        self.broker = patch("agentdock.credential_broker.available", return_value=False)
        self.broker.start()
        self.addCleanup(self.broker.stop)
        self.runtime = Runtime(self.store, {"execution_enabled": True, "commands": {}})
        self.addCleanup(
            lambda: self.runtime.close() if not self.runtime._closed else None
        )

    def new_run(self, *, managed=False, remote=False):
        env = (
            self.store.add_environment("fixture", "fixture-host")["id"]
            if remote
            else "local"
        )
        account = (
            self.store.complete_account_login(
                self.store.add_account("claude", "Work", env)["id"]
            )
            if managed
            else None
        )
        agent = self.store.add_agent(
            None,
            "worker",
            "claude",
            environment_id=env,
            account_id=account["id"] if account else None,
        )
        session = self.store.add_session(agent["id"], "quota")
        record = self.store.begin_run(session["id"], "fixture")
        return _Run(record, "fixture-capability"), account, env

    def test_stream_json_updates_quota_and_preserves_cli_timestamp_and_identity(self):
        run, account, _ = self.new_run(managed=True)
        now = datetime.now(timezone.utc).timestamp()
        pipe = Pipe(
            [
                {
                    "type": "control_response",
                    "response": {
                        "request_id": "agentdock_initialize",
                        "subtype": "success",
                        "response": {},
                    },
                },
                {
                    "type": "rate_limit_event",
                    "rate_limit_info": {
                        "status": "allowed_warning",
                        "rateLimitType": "five_hour",
                        "utilization": 0.8,
                        "resetsAt": now + 600,
                        "secret": "must-not-persist",
                    },
                },
                {
                    "type": "result",
                    "session_id": "native",
                    "subtype": "success",
                    "result": "done",
                },
            ]
        )
        adapter = _Claude(
            pipe,
            _Callbacks(
                pipe,
                lambda kind, payload: self.runtime._event(run, kind, payload),
                lambda *a: None,
                lambda *a: None,
                {},
            ),
            "native",
        )
        adapter.run("fixture")
        actual = self.store.get_account(account["id"])
        quota = actual["quota"]
        self.assertAlmostEqual(quota["windows"][0]["remaining_percent"], 20)
        self.assertEqual(quota["source"], "cli_event")
        self.assertEqual(
            datetime.fromisoformat(quota["windows"][0]["reset_at"]).timestamp(),
            now + 600,
        )
        self.assertEqual(quota["windows"][0]["duration_minutes"], 300)
        self.assertNotIn(
            "must-not-persist",
            json.dumps(self.store.session_events(run.record["session_id"])),
        )
        self.assertEqual(actual["identity"], account["identity"])
        self.assertIsNone(self.store.get_quota("claude"))

    def test_device_observations_are_scoped_by_ssh_environment(self):
        run, _, env = self.new_run(remote=True)
        self.runtime._event(
            run,
            "account_rate_limit",
            {"status": "allowed", "rateLimitType": "seven_day", "utilization": 0.3},
        )
        quota = self.store.get_quota("claude", env)
        self.assertEqual(quota["windows"][0]["remaining_percent"], 70)
        self.assertEqual(quota["windows"][0]["duration_minutes"], 10080)
        self.assertEqual(quota["windows"][0]["label"], "Weekly window")
        self.assertEqual(quota["source"], "cli_event")
        self.assertIsNone(self.store.get_quota("claude", "local"))

    def test_refresh_never_runs_cli_ssh_or_changes_observation_time(self):
        for remote in (False, True):
            run, account, _ = self.new_run(managed=True, remote=remote)
            with patch.object(
                self.runtime.accounts,
                "_call",
                side_effect=AssertionError("active probe"),
            ):
                self.assertEqual(
                    self.runtime.accounts.refresh(account["id"], force=True)["quota"][
                        "status"
                    ],
                    "unknown",
                )
                self.runtime._event(
                    run, "account_rate_limit", {"status": "allowed", "utilization": 0.4}
                )
                before = self.store.get_account(account["id"])["quota"]
                for _ in range(3):
                    self.assertEqual(
                        self.runtime.accounts.refresh(account["id"], force=True)[
                            "quota"
                        ],
                        before,
                    )

    def test_device_quota_refresh_only_reads_cache(self):
        run, _, env = self.new_run(remote=True)
        service = QuotaService(self.store, ["must-not-run"], True)
        self.addCleanup(service.close)
        service.remote = Mock(side_effect=AssertionError("remote query"))
        with patch.object(service, "_probe", side_effect=AssertionError("helper")):
            result = service.refresh("claude", environment_id=env)
            self.assertEqual(result["status"], "unknown")
            self.assertIsNone(result["fetched_at"])
            self.runtime._event(
                run, "account_rate_limit", {"status": "allowed", "utilization": 0.1}
            )
            self.assertEqual(
                service.refresh("claude", environment_id=env),
                self.store.get_quota("claude", env),
            )
        service.remote.assert_not_called()

    def test_reset_and_remaining_are_unknown_if_cli_did_not_supply_them(self):
        result = observe({"status": "allowed", "rateLimitType": "five_hour"}, {})
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("remaining_percent", result["windows"][0])
        self.assertNotIn("reset_at", result["windows"][0])
        for value in (True, float("nan"), float("inf"), -0.1, 1.01, "0.1"):
            result = observe(
                {"status": "allowed", "utilization": value, "resetsAt": value}, {}
            )
            self.assertNotIn("remaining_percent", result["windows"][0])
            self.assertNotIn("reset_at", result["windows"][0])
        self.assertIsNone(observe({"status": "unexpected"}, {}))

    def test_rejected_event_records_zero_but_local_cooldown_is_not_a_reset(self):
        run, account, _ = self.new_run(managed=True)
        self.runtime._event(
            run,
            "account_rate_limit",
            {"status": "rejected", "rateLimitType": "five_hour"},
        )
        value = self.store.get_account(account["id"])
        self.assertEqual(value["status"], "cooldown")
        self.assertEqual(value["quota"]["windows"][0]["remaining_percent"], 0)
        self.assertNotIn("reset_at", value["quota"]["windows"][0])
        self.assertIsNotNone(value["cooldown_until"])

    def test_old_generation_cannot_change_account_sample(self):
        account = self.store.complete_account_login(
            self.store.add_account("claude", "Work")["id"]
        )
        self.runtime._account_limit(
            account["id"],
            {"status": "allowed", "utilization": 0.2},
            account["generation"] - 1,
        )
        self.assertEqual(
            self.store.get_account(account["id"])["quota"]["status"], "unknown"
        )

    def test_claude_native_actions_stop_before_reading_snapshot_or_client(self):
        account = self.store.add_account("claude", "Work")
        native = self.runtime.accounts.native
        with patch.object(native, "platform") as platform:
            for client in ("claude_code", "claude_desktop"):
                for operation in (native.capture, native.switch, native.recover):
                    with self.assertRaisesRegex(ValueError, "official client"):
                        operation(account, client)
            self.assertEqual(platform.mock_calls, [])
        self.assertFalse(native.status(account)["available"])

    def test_migration_retains_legacy_sample_and_removes_only_quota_feature(self):
        self.runtime.close()
        account = self.store.add_account("claude", "Before upgrade")
        timestamp = "2026-01-01T00:00:00+00:00"
        legacy = {
            "windows": [{"name": "session", "remaining_percent": 25}],
            "fetched_at": timestamp,
            "status": "ok",
        }
        self.store.set_account_quota(account["id"], legacy)
        self.store.set_quota("claude", {"provider": "claude", **legacy})
        features = {"claude_quota": True, "native_switching": False, "acp_agents": True}
        self.store.db.execute(
            "INSERT OR REPLACE INTO metadata VALUES('experimental_features',?)",
            (json.dumps(features),),
        )
        self.store.db.execute("PRAGMA user_version=13")
        self.store.close()
        self.store = Store(self.path)
        value = self.store.get_account(account["id"])["quota"]
        self.assertEqual(value["windows"], legacy["windows"])
        self.assertEqual(value["fetched_at"], timestamp)
        self.assertEqual(value["source"], "legacy_snapshot")
        self.assertEqual(value["status"], "stale")
        self.assertEqual(self.store.get_quota("claude")["source"], "legacy_snapshot")
        saved = json.loads(
            self.store.db.execute(
                "SELECT value FROM metadata WHERE key='experimental_features'"
            ).fetchone()[0]
        )
        self.assertNotIn("claude_quota", saved)
        self.assertTrue(saved["acp_agents"])
        with self.assertRaises(Invalid):
            self.store.set_feature("claude_quota", True, True)
        # Reopening does not relabel newly observed data as legacy.
        fresh = observe({"status": "allowed", "utilization": 0.2}, value)
        self.store.set_account_quota(account["id"], fresh)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get_account(account["id"])["quota"], fresh)
