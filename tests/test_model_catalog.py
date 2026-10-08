"""Metadata caching must avoid repeated SSH/CLI starts without mixing hosts."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from agentdock.providers import ProviderError
from agentdock.remote import RemoteManager
from agentdock.store import Conflict, Forbidden, Store


class RemoteCatalogTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.calls = []
        self.manager = RemoteManager(self.store, True, self.transport)
        self.first = self.store.add_environment("First", "host-one")["id"]
        self.second = self.store.add_environment("Second", "host-two")["id"]
        self.manager.connect(self.first)
        self.manager.connect(self.second)

    def tearDown(self):
        self.manager.close()
        self.store.close()

    def transport(self, environment, payload, stop=None):
        request = payload["request"]
        if request["op"] == "probe":
            return {
                "ok": True,
                "value": {
                    "providers": {p: {"available": True} for p in ("codex", "claude")}
                },
            }
        self.calls.append((environment["id"], request["provider"]))
        return {
            "ok": True,
            "value": {
                "provider": request["provider"],
                "models": [
                    {
                        "id": environment["name"] + "-" + request["provider"],
                        "name": "Fixture",
                        "efforts": ["high"],
                    }
                ],
            },
        }

    def test_repeated_reads_are_cached_per_host_and_provider(self):
        first = self.manager.models(self.first, "codex")
        self.assertEqual(self.manager.models(self.first, "codex"), first)
        self.assertNotEqual(self.manager.models(self.first, "claude"), first)
        self.assertNotEqual(self.manager.models(self.second, "codex"), first)
        self.assertEqual(len(self.calls), 3)

    def test_expiry_and_reconnect_refresh_metadata(self):
        with patch("agentdock.remote.time.monotonic", return_value=100) as clock:
            self.manager.models(self.first, "codex")
            clock.return_value = 399
            self.manager.models(self.first, "codex")
            self.assertEqual(len(self.calls), 1)
            clock.return_value = 401
            self.manager.models(self.first, "codex")
            self.assertEqual(len(self.calls), 2)
        self.manager.connect(self.first)
        self.manager.models(self.first, "codex")
        self.assertEqual(len(self.calls), 3)

    def test_concurrent_reads_share_one_remote_lookup(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            values = list(
                pool.map(lambda _: self.manager.models(self.first, "codex"), range(6))
            )
        self.assertTrue(all(value == values[0] for value in values))
        self.assertEqual(len(self.calls), 1)

    def test_failed_reads_are_not_cached_and_cached_reads_still_check_permissions(self):
        with patch.object(self.manager, "transport", return_value={"ok": False}):
            with self.assertRaises(ProviderError):
                self.manager.models(self.first, "codex")
        self.manager.models(self.first, "codex")
        self.assertEqual(len(self.calls), 1)
        self.manager.enabled = False
        with self.assertRaises(Forbidden):
            self.manager.models(self.first, "codex")
        self.manager.enabled = True
        self.store.update_environment_status(self.first, "connected", {"digest": "old"})
        with self.assertRaises(Conflict):
            self.manager.models(self.first, "codex")
        self.manager.close()
        with self.assertRaises(Forbidden):
            self.manager.models(self.second, "codex")

    def test_reconnect_does_not_cache_an_older_inflight_result(self):
        started, release = threading.Event(), threading.Event()
        original = self.manager.transport

        def slow(environment, payload, stop=None):
            if payload["request"]["op"] == "models":
                started.set()
                if not release.wait(2):
                    raise TimeoutError("test did not release lookup")
            return original(environment, payload, stop)

        self.manager.transport = slow
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.manager.models, self.first, "codex")
            try:
                self.assertTrue(started.wait(2))
                self.manager.connect(self.first)
            finally:
                release.set()
            future.result(timeout=2)
        self.manager.models(self.first, "codex")
        self.assertEqual(len(self.calls), 2)
