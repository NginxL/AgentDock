import json
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, call, patch

from agentdock.quota import QuotaService
from agentdock.store import Forbidden


class QuotaStore:
    def __init__(self):
        self.quotas = {}
        self.providers = ["codex", "claude"]

    def configured_connections(self):
        return [(p, "local") for p in self.configured_providers()]

    def configured_providers(self, environment_id=None):
        return self.providers

    def get_quota(self, provider, environment_id="local"):
        return self.quotas.get(provider)

    def set_quota(self, provider, quota):
        self.quotas[provider] = quota


class QuotaTests(unittest.TestCase):
    def test_refresh_and_timer_follow_configured_agents(self):
        store = QuotaStore()
        store.providers = []
        service = QuotaService(store, ["helper"], True)
        service.AUTO_REFRESH_INTERVAL = 0.01
        with patch.object(service, "_probe") as probe:
            with self.assertRaises(ValueError):
                service.refresh("codex")
            service.start_auto_refresh()
            time.sleep(0.04)
            probe.assert_not_called()
            called = threading.Event()

            def result(provider):
                self.assertEqual(provider, "codex")
                called.set()
                return {"provider": provider, "windows": []}

            probe.side_effect = result
            store.providers = ["codex"]
            self.assertTrue(called.wait(1))
            service.close()
            self.assertEqual({c.args[0] for c in probe.call_args_list}, {"codex"})

    def test_helper_failures_are_whitelisted_and_authorization_is_explicit(self):
        service = QuotaService(QuotaStore(), ["helper"], True)
        with patch.object(
            service,
            "_probe",
            return_value={
                "provider": "codex",
                "error_code": "authorization_required",
                "error": "private token",
            },
        ) as probe:
            result = service.refresh("codex")
            self.assertEqual(result["error_code"], "authorization_required")
            self.assertNotIn("private token", str(result))
            probe.assert_called_once_with("codex")
        with patch.object(service, "_probe") as probe:
            with self.assertRaises(ValueError):
                service.refresh("codex", authorize=True)
            probe.assert_not_called()
        with self.assertRaises(ValueError):
            service.refresh("codex", authorize=True)
        legacy = QuotaService(QuotaStore(), ["AgentMeter"], True, source="AgentMeter")
        with self.assertRaises(ValueError):
            legacy.refresh("codex", authorize=True)

    def test_authorization_never_starts_in_review_mode(self):
        service = QuotaService(QuotaStore(), ["helper"], False)
        with patch.object(service, "_probe") as probe:
            with self.assertRaises(ValueError):
                service.refresh("claude", authorize=True)
            probe.assert_not_called()

    def setUp(self):
        self.store = QuotaStore()

    def snapshot(self, **extra):
        return {
            "provider": "codex",
            "plan": "Pro",
            "accountID": "private-account",
            "source": "local credential data",
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "windows": [{"title": "Five hours", "usedPercent": 23}],
            **extra,
        }

    def command(self, snapshot):
        return [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write(" + repr(json.dumps(snapshot)) + ")",
        ]

    def test_disabled_does_not_launch(self):
        service = QuotaService(self.store, ["AgentMeter"], False)
        with patch("agentdock.quota.subprocess.Popen") as spawn:
            self.assertEqual(service.refresh("codex")["status"], "disabled")
            spawn.assert_not_called()

    def test_provider_allowlist(self):
        service = QuotaService(self.store, ["AgentMeter"], True)
        with self.assertRaises(ValueError):
            service.refresh("--anything")

    def test_real_probe_shape_and_private_fields(self):
        service = QuotaService(self.store, self.command(self.snapshot()), True)
        quota = service.refresh("codex")
        self.assertEqual(quota["status"], "available")
        self.assertEqual(quota["windows"][0]["remaining_percent"], 77)
        self.assertEqual(quota["windows"][0]["label"], "Five hours")
        self.assertEqual(quota["source"], "AgentDock")
        self.assertNotIn("accountID", quota)
        self.assertNotIn("private-account", json.dumps(quota))

    def test_unknown_percentage_is_not_zero(self):
        raw = self.snapshot(windows=[{"title": "Weekly", "usedPercent": None}])
        quota = QuotaService(self.store, self.command(raw), True).refresh("codex")
        self.assertIsNone(quota["windows"][0]["remaining_percent"])
        self.assertEqual(quota["status"], "unknown")

    def test_throttle_does_not_probe_twice(self):
        service = QuotaService(self.store, ["fixture"], True)
        with patch.object(service, "_probe", return_value=self.snapshot()) as probe:
            first = service.refresh("codex")
            self.assertEqual(service.refresh("codex"), first)
            self.assertEqual(probe.call_count, 1)

    def test_stale_snapshot_and_elapsed_reset(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        raw = self.snapshot(
            fetchedAt=old,
            windows=[{"title": "Five hours", "usedPercent": 23, "resetsAt": old}],
        )
        quota = QuotaService(self.store, self.command(raw), True).refresh("codex")
        self.assertEqual(quota["status"], "stale")
        self.assertEqual(quota["error_code"], "outdated_cache")
        self.assertIsNone(quota["windows"][0]["remaining_percent"])

    def test_invalid_values_fail_closed(self):
        for raw in (
            self.snapshot(provider="claude"),
            self.snapshot(fetchedAt="invalid"),
            self.snapshot(windows=[{"usedPercent": 101}]),
            self.snapshot(windows=[{"usedPercent": True}]),
        ):
            with self.subTest(raw=raw):
                service = QuotaService(QuotaStore(), ["fixture"], True)
                with patch.object(service, "_probe", return_value=raw):
                    self.assertEqual(service.refresh("codex")["status"], "unavailable")

    def test_error_keeps_old_value_marked_stale(self):
        service = QuotaService(self.store, ["fixture"], True)
        with patch.object(service, "_probe", return_value=self.snapshot()):
            service.refresh("codex")
        service._last_attempt.clear()
        with patch.object(service, "_probe", side_effect=RuntimeError("private-token")):
            quota = service.refresh("codex")
        self.assertEqual(quota["status"], "stale")
        self.assertEqual(quota["windows"][0]["remaining_percent"], 77)
        self.assertNotIn("private-token", json.dumps(quota))

    def test_timeout_and_output_limit(self):
        commands = [
            [sys.executable, "-c", "import time; time.sleep(60)"],
            [sys.executable, "-c", "print('x' * 1100000)"],
        ]
        for command in commands:
            service = QuotaService(QuotaStore(), command, True)
            service.TIMEOUT = 0.15
            quota = service.refresh("codex")
            self.assertEqual(quota["status"], "unavailable")
            self.assertLess(len(json.dumps(quota)), 500)

    def test_stderr_never_exposed(self):
        command = [
            sys.executable,
            "-c",
            "import sys; print('private-debug-secret', file=sys.stderr); sys.exit(2)",
        ]
        quota = QuotaService(self.store, command, True).refresh("codex")
        self.assertNotIn("private-debug-secret", str(quota))
        self.assertEqual(quota["status"], "unavailable")

    def test_cached_read_ages_without_process_or_store_mutation(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        original = {
            "provider": "codex",
            "plan": "Pro",
            "windows": [],
            "fetched_at": old,
            "status": "available",
            "source": "AgentMeter",
        }
        self.store.set_quota("codex", original)
        service = QuotaService(self.store, ["AgentMeter"], False)
        with patch("agentdock.quota.subprocess.Popen") as spawn:
            self.assertEqual(service.cached("codex")["status"], "stale")
            spawn.assert_not_called()
        self.assertEqual(original["status"], "available")

    def test_auto_refresh_waits_ten_minutes_and_is_single_instance(self):
        service = QuotaService(self.store, ["fixture"], True)
        with patch.object(service, "_probe") as probe:
            service.start_auto_refresh()
            worker = service._auto_thread
            service.start_auto_refresh()
            self.assertIs(service._auto_thread, worker)
            self.assertEqual(service.AUTO_REFRESH_INTERVAL, 600)
            self.assertTrue(worker.is_alive())
            probe.assert_not_called()
            service.close()
            self.assertFalse(worker.is_alive())
            probe.assert_not_called()
        with self.assertRaises(Forbidden):
            service.start_auto_refresh()

    def test_auto_refresh_disabled_without_execution_or_helper(self):
        for enabled, command in ((False, ["fixture"]), (True, None)):
            service = QuotaService(self.store, command, enabled)
            service.start_auto_refresh()
            self.assertIsNone(service._auto_thread)
            service.close()

    def test_timer_is_noninteractive_and_continues_after_provider_failure(self):
        service = QuotaService(self.store, ["fixture"], True)
        service._auto_stop = Mock()
        service._auto_stop.wait.side_effect = [False, False, True]
        service._auto_stop.is_set.return_value = False
        with (
            patch(
                "agentdock.quota.time.monotonic",
                side_effect=[100, 100, 700, 700, 1300, 1300],
            ),
            patch.object(
                service, "refresh", side_effect=[RuntimeError("offline"), {}, {}, {}]
            ) as refresh,
        ):
            service._auto_refresh()
        self.assertEqual(service._auto_stop.wait.call_args_list, [call(600)] * 3)
        self.assertEqual(refresh.call_args_list, [call("codex")] * 2)

    def test_timer_skips_missed_intervals_after_suspension(self):
        service = QuotaService(self.store, ["fixture"], True)
        service._auto_stop = Mock()
        service._auto_stop.wait.side_effect = [False, True]
        service._auto_stop.is_set.return_value = False
        with (
            patch("agentdock.quota.time.monotonic", side_effect=[0, 2000, 2010, 2010]),
            patch.object(service, "refresh") as refresh,
        ):
            service._auto_refresh()
        self.assertEqual(service._auto_stop.wait.call_args_list, [call(0), call(600)])
        self.assertEqual(refresh.call_count, 1)

    def test_close_stops_automatic_probe_and_joins_timer(self):
        service = QuotaService(
            self.store, [sys.executable, "-c", "import time; time.sleep(60)"], True
        )
        service.AUTO_REFRESH_INTERVAL = 0.01
        service.start_auto_refresh()
        try:
            self.wait_for(lambda: bool(service._processes))
            process = next(iter(service._processes))
            service.close()
            self.assertFalse(service._auto_thread.is_alive())
            self.assertIsNotNone(process.poll())
            self.assertEqual(service._inflight, 0)
            self.assertFalse(self.store.quotas)
        finally:
            service.close()

    def start_refresh(self, service):
        errors = []

        def refresh():
            try:
                service.refresh("codex")
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=refresh, daemon=True)
        worker.start()
        return worker, errors

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Offline quota fixture did not reach the expected state")

    def test_close_stops_probe_and_drains_refresh_without_writing(self):
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        service = QuotaService(self.store, command, True)
        worker, errors = self.start_refresh(service)
        try:
            self.wait_for(lambda: bool(service._processes))
            process = next(iter(service._processes))
            service.close()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            self.assertIsNotNone(process.poll())
            self.assertFalse(service._processes)
            self.assertEqual(service._inflight, 0)
            self.assertFalse(self.store.quotas)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], Forbidden)
        finally:
            service.close()
            worker.join(timeout=2)

    def test_closed_refresh_rejected_before_process_or_store_access(self):
        service = QuotaService(self.store, ["AgentMeter"], True)
        service.close()
        with (
            patch("agentdock.quota.subprocess.Popen") as spawn,
            patch.object(self.store, "set_quota") as save,
        ):
            with self.assertRaisesRegex(Forbidden, "closed"):
                service.refresh("codex")
            spawn.assert_not_called()
            save.assert_not_called()
        service.close()  # Closing twice is safe.

    def test_close_racing_process_creation_cannot_miss_probe(self):
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        service = QuotaService(self.store, command, True)
        entered, release = threading.Event(), threading.Event()
        real_popen = subprocess.Popen
        created = []

        def delayed_spawn(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=3):
                raise RuntimeError("Fixture release timed out")
            process = real_popen(*args, **kwargs)
            created.append(process)
            return process

        with patch("agentdock.quota.subprocess.Popen", side_effect=delayed_spawn):
            worker, errors = self.start_refresh(service)
            closer = threading.Thread(target=service.close, daemon=True)
            try:
                self.assertTrue(entered.wait(timeout=2))
                closer.start()
                release.set()
                closer.join(timeout=3)
                worker.join(timeout=1)
                self.assertFalse(closer.is_alive())
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(created), 1)
                self.assertIsNotNone(created[0].poll())
                self.assertFalse(service._processes)
                self.assertFalse(self.store.quotas)
                self.assertIsInstance(errors[0], Forbidden)
            finally:
                release.set()
                service.close()
                worker.join(timeout=2)
                if closer.ident:
                    closer.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
