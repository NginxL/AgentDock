"""Slow external cleanup cannot block the workbench or admit new work."""

import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from agentdock.runtime import Runtime
from agentdock.store import Conflict, Forbidden, Missing, Store


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

    def test_default_dispatch_skips_failed_deletions_without_changing_activity(self):
        gone = self.store.add_session(self.agent["id"], "Failed cleanup")
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE sessions SET updated_at='2030-01-01T00:00:00+00:00' WHERE id=?",
                (gone["id"],),
            )
        before = self.store.get_session(gone["id"])["updated_at"]
        cleanup = Mock(side_effect=OSError("fixture SSH outage"))
        with self.assertRaises(OSError):
            self.store.delete_session(gone["id"], cleanup)
        self.assertEqual(self.store.get_session(gone["id"])["updated_at"], before)
        message = self.store.enqueue_message(
            self.project["id"], "human", self.agent["id"], "Healthy target"
        )
        self.assertEqual(message["recipient_session_id"], self.session["id"])
        self.assertTrue(self.store.get_session(gone["id"])["deleting"])

    def test_default_task_session_skips_deletions_and_creates_a_fresh_fallback(self):
        task = self.store.create_task(
            self.project["id"], "Task", "Goal", "Verified", self.agent["id"]
        )
        with self.store.transaction():
            healthy = self.store._task_session(task)
            gone = self.store._task_session(task, fresh=True)
            self.store.db.execute(
                "UPDATE sessions SET deleting=1 WHERE id=?", (gone["id"],)
            )
            self.assertEqual(self.store._task_session(task)["id"], healthy["id"])
            self.store.db.execute(
                "UPDATE sessions SET deleting=1 WHERE id=?", (healthy["id"],)
            )
            replacement = self.store._task_session(task)
            self.assertNotIn(replacement["id"], (gone["id"], healthy["id"]))
            self.assertFalse(replacement["deleting"])

    def test_remote_cleanup_refusal_does_not_mark_session_or_agent(self):
        device = self.store.add_environment("Fixture", "fixture")
        agent = self.store.add_agent(
            None, "Remote", "codex", environment_id=device["id"]
        )
        session = self.store.add_session(agent["id"], "Keep usable")
        run = self.store.enqueue_run(session["id"], "Prior work")
        self.store.finish_run(run["id"], "cancelled")
        before = self.store.get_session(session["id"])
        runtime = Runtime(self.store, {"execution_enabled": False, "commands": {}})
        try:
            with patch.object(runtime.remote, "rpc") as rpc:
                for delete in (
                    lambda: runtime.delete_session(session["id"]),
                    lambda: runtime.delete_agent(agent["id"]),
                ):
                    with self.assertRaises(Forbidden):
                        delete()
                    self.assertEqual(self.store.get_session(session["id"]), before)
                    self.assertFalse(self.store.get_agent(agent["id"])["deleting"])
                rpc.assert_not_called()
            self.store.enqueue_run(session["id"], "Still accepting work")
        finally:
            runtime.close()

    def test_agent_preflight_failure_rolls_back_every_tombstone(self):
        other = self.store.add_session(self.agent["id"], "Second")

        def preflight(session, _):
            if session["id"] == other["id"]:
                raise Forbidden("fixture refusal")

        cleanup = Mock()
        with self.assertRaises(Forbidden):
            self.store.delete_agent(self.agent["id"], cleanup, preflight=preflight)
        cleanup.assert_not_called()
        self.assertFalse(self.store.get_agent(self.agent["id"])["deleting"])
        for session in (self.session, other):
            self.assertFalse(self.store.get_session(session["id"])["deleting"])

    def test_external_cleanup_does_not_hold_the_runtime_dispatch_lock(self):
        runtime = Runtime(
            self.store,
            {
                "execution_enabled": True,
                "commands": {
                    "codex": [
                        sys.executable,
                        "-c",
                        "raise AssertionError('The queued fixture must not execute')",
                    ]
                },
            },
        )
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
