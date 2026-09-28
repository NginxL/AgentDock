from datetime import datetime, timedelta, timezone
import json
import sys
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from agentdock.quota import QuotaService
from agentdock.store import Forbidden


class QuotaStore:
    def __init__(self):
        self.quotas = {}

    def get_quota(self, provider):
        return self.quotas.get(provider)

    def set_quota(self, provider, quota):
        self.quotas[provider] = quota


class QuotaTests(unittest.TestCase):
    def test_helper_failures_are_whitelisted_and_authorization_is_explicit(self):
        service = QuotaService(QuotaStore(), ['helper'], True)
        with patch.object(service, '_probe', return_value={'provider':'claude','error_code':'authorization_required','error':'private token'}) as probe:
            result = service.refresh('claude')
            self.assertEqual(result['error_code'], 'authorization_required')
            self.assertNotIn('private token', str(result))
            probe.assert_called_once_with('claude')
        with patch.object(service, '_probe', return_value={**self.snapshot(), 'provider':'claude'}) as probe:
            result = service.refresh('claude', authorize=True)
            self.assertEqual(result['status'], 'available')
            self.assertNotIn('error_code', result)
            probe.assert_called_once_with('claude', authorize=True)
        with self.assertRaises(ValueError): service.refresh('codex', authorize=True)
        legacy = QuotaService(QuotaStore(), ['AgentMeter'], True, source='AgentMeter')
        with self.assertRaises(ValueError): legacy.refresh('claude', authorize=True)

    def test_authorization_never_starts_in_review_mode(self):
        service = QuotaService(QuotaStore(), ['helper'], False)
        with patch.object(service, '_probe') as probe:
            self.assertEqual(service.refresh('claude', authorize=True)['status'], 'disabled')
            probe.assert_not_called()

    def setUp(self):
        self.store = QuotaStore()

    def snapshot(self, **extra):
        return {"provider": "codex", "plan": "Pro", "accountID": "private-account",
                "source": "local credential data", "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "windows": [{"title": "Five hours", "usedPercent": 23}], **extra}

    def command(self, snapshot):
        return [sys.executable, "-c", "import sys; sys.stdout.write(" + repr(json.dumps(snapshot)) + ")"]

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
        raw = self.snapshot(fetchedAt=old, windows=[{"title": "Five hours", "usedPercent": 23, "resetsAt": old}])
        quota = QuotaService(self.store, self.command(raw), True).refresh("codex")
        self.assertEqual(quota["status"], "stale")
        self.assertIsNone(quota["windows"][0]["remaining_percent"])

    def test_invalid_values_fail_closed(self):
        for raw in (self.snapshot(provider="claude"), self.snapshot(fetchedAt="invalid"),
                    self.snapshot(windows=[{"usedPercent": 101}]), self.snapshot(windows=[{"usedPercent": True}])):
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
        commands = [[sys.executable, "-c", "import time; time.sleep(60)"],
                    [sys.executable, "-c", "print('x' * 1100000)"]]
        for command in commands:
            service = QuotaService(QuotaStore(), command, True)
            service.TIMEOUT = 0.15
            quota = service.refresh("codex")
            self.assertEqual(quota["status"], "unavailable")
            self.assertLess(len(json.dumps(quota)), 500)

    def test_stderr_never_exposed(self):
        command = [sys.executable, "-c", "import sys; print('private-debug-secret', file=sys.stderr); sys.exit(2)"]
        quota = QuotaService(self.store, command, True).refresh("codex")
        self.assertNotIn("private-debug-secret", str(quota))
        self.assertEqual(quota["status"], "unavailable")

    def test_cached_read_ages_without_process_or_store_mutation(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        original = {"provider": "codex", "plan": "Pro", "windows": [],
                    "fetched_at": old, "status": "available", "source": "AgentMeter"}
        self.store.set_quota("codex", original)
        service = QuotaService(self.store, ["AgentMeter"], False)
        with patch("agentdock.quota.subprocess.Popen") as spawn:
            self.assertEqual(service.cached("codex")["status"], "stale")
            spawn.assert_not_called()
        self.assertEqual(original["status"], "available")

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
        with patch("agentdock.quota.subprocess.Popen") as spawn, \
                patch.object(self.store, "set_quota") as save:
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
