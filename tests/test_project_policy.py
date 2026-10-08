import tempfile
import unittest
from pathlib import Path

from agentdock.store import Conflict, Store


class ProjectPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.sqlite3")
        self.project = self.store.add_project("Fixture", str(self.root))
        self.sender = self.store.add_agent(
            self.project["id"], "Owner", "codex", permission_mode="full_access"
        )
        worker = self.root / "worker"
        worker.mkdir()
        self.recipient = self.store.add_agent(
            self.project["id"], "Worker", "claude", workspace=str(worker)
        )
        self.store.update_project_policy(self.project["id"], True)
        session = self.store.add_session(self.sender["id"], "Fixture")
        self.run = self.store.begin_run(session["id"], "Fixture")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def send(self):
        return self.store.enqueue_message(
            self.project["id"],
            self.sender["id"],
            self.recipient["id"],
            "Bounded work",
            parent_run_id=self.run["id"],
            idempotency_key="fixture",
        )

    def test_full_access_dispatch_waits_for_human_after_sender_finishes(self):
        message = self.send()
        self.assertEqual(self.send()["id"], message["id"])
        self.assertIsNone(self.store.claim_next_run())
        self.assertEqual(len(self.store.state()["approvals"]), 1)
        approval = self.store.state()["approvals"][0]
        self.store.finish_run(
            self.run["id"], "completed", result="Waiting for delegated result"
        )
        self.assertIsNone(self.store.claim_next_run())
        self.assertEqual(self.store.get_approval(approval["id"])["status"], "pending")
        self.store.resolve_dispatch(approval["id"], "accept")
        self.assertEqual(self.store.claim_next_run()["id"], message["run_id"])
        with self.assertRaises(Conflict):
            self.store.resolve_dispatch(approval["id"], "accept")

    def test_rejection_or_cancellation_cannot_dispatch(self):
        self.send()
        approval = self.store.state()["approvals"][0]
        self.store.resolve_dispatch(approval["id"], "reject")
        self.assertIsNone(self.store.claim_next_run())
        self.store.finish_run(self.run["id"], "cancelled")
        self.assertIsNone(self.store.claim_next_run())

    def test_fts_preserves_project_scope_literal_text_and_archive_filter(self):
        other = self.store.add_project("Other", str(self.root))
        self.store.put_memory(other["id"], "Other", "工作目录和索引", 0)
        memory = self.store.put_memory(
            self.project["id"], "Fixture", "工作目录和索引", 0
        )
        self.assertEqual(
            [m["id"] for m in self.store.search_memory(self.project["id"], "工作目录")],
            [memory["id"]],
        )
        self.assertEqual(
            [m["id"] for m in self.store.search_memory(self.project["id"], "索引")],
            [memory["id"]],
        )
        self.assertEqual(self.store.search_memory(self.project["id"], '" OR *'), [])
        self.store.archive_memory(memory["id"], 1)
        self.assertEqual(self.store.search_memory(self.project["id"], "工作目录"), [])

    def test_fts_migration_backfills_existing_memory(self):
        self.store.put_memory(
            self.project["id"], "Fixture", "Existing searchable text", 0
        )
        for name in ("insert", "delete", "update"):
            self.store.db.execute("DROP TRIGGER memory_fts_" + name)
        self.store.db.execute("DROP TABLE memory_fts")
        self.store.db.execute("PRAGMA user_version=12")
        self.store.close()
        self.store = Store(self.root / "state.sqlite3")
        self.assertEqual(
            len(self.store.search_memory(self.project["id"], "searchable")), 1
        )
