"""Slow external cleanup cannot block the workbench or admit new work."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from agentdock.store import Conflict, Missing, Store
from agentdock.runtime import Runtime


class DeletionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = Store(self.path)
        self.project = self.store.add_project("Fixture", self.temp.name)
        self.agent = self.store.add_agent(self.project["id"], "Delete", "codex")
        self.session = self.store.add_session(self.agent["id"], "Delete")
        other = self.store.add_agent(None, "Keep running", "codex")
        self.other = self.store.add_session(other["id"], "Unrelated")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_cleanup_releases_database_lock_and_rejects_new_work(self):
        entered, release = threading.Event(), threading.Event()

        def cleanup(*_):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test cleanup was not released")

        with ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(self.store.delete_agent, self.agent["id"], cleanup)
            try:
                self.assertTrue(entered.wait(1))
                # Both reads and writes on unrelated sessions must finish while
                # the simulated SSH cleanup is still blocked.
                state = pool.submit(self.store.state).result(timeout=1)
                self.assertEqual(
                    next(s for s in state["sessions"] if s["id"] == self.session["id"])[
                        "status"
                    ],
                    "deleting",
                )
                pool.submit(
                    self.store.enqueue_run, self.other["id"], "Unrelated work"
                ).result(timeout=1)
                for submit in (
                    lambda: self.store.add_session(self.agent["id"], "New"),
                    lambda: self.store.enqueue_run(self.session["id"], "New"),
                    lambda: self.store.enqueue_message(
                        self.project["id"], "human", self.agent["id"], "Dispatch"
                    ),
                    lambda: self.store.update_agent(
                        self.agent["id"], {"name": "Changed"}
                    ),
                ):
                    with self.assertRaisesRegex(Conflict, "Deletion is pending"):
                        pool.submit(submit).result(timeout=1)
                with self.assertRaisesRegex(Conflict, "already in progress"):
                    self.store.delete_session(self.session["id"], lambda *_: None)
            finally:
                release.set()
            self.assertEqual(deleting.result(timeout=1), {"ok": True})

    def test_failed_cleanup_survives_restart_and_can_be_retried(self):
        def fail(*_):
            raise OSError("Fixture SSH outage")

        with self.assertRaises(OSError):
            self.store.delete_session(self.session["id"], fail)
        self.store.close()
        self.store = Store(self.path)
        self.assertTrue(self.store.get_session(self.session["id"])["deleting"])
        with self.assertRaises(Conflict):
            self.store.enqueue_run(
                self.session["id"], "No admission while cleanup is incomplete"
            )
        self.store.delete_session(self.session["id"], lambda *_: None)
        with self.assertRaises(Missing):
            self.store.get_session(self.session["id"])
        self.assertEqual(self.store.get_session(self.other["id"])["title"], "Unrelated")

    def test_external_cleanup_does_not_hold_the_runtime_dispatch_lock(self):
        runtime = Runtime(self.store, {"execution_enabled": True})
        entered, release = threading.Event(), threading.Event()

        def cleanup(*_):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Cleanup fixture was not released")

        try:
            with (
                patch.object(runtime, "_cleanup_session", cleanup),
                patch.object(runtime, "_notify"),
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    deleting = pool.submit(runtime.delete_session, self.session["id"])
                    try:
                        self.assertTrue(entered.wait(1))
                        run = pool.submit(
                            runtime.start, self.other["id"], "Unrelated task"
                        ).result(timeout=1)
                        self.assertEqual(run["status"], "queued")
                    finally:
                        release.set()
                    self.assertEqual(deleting.result(timeout=1), {"ok": True})
        finally:
            runtime.close()
