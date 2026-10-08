import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agentdock.runtime import Runtime
from agentdock.store import Conflict, Missing, Store


class AgentDeletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.store = Store(self.root / "data" / "agentdock.sqlite3")
        self.runtime = Runtime(self.store, {"execution_enabled": True})

    def tearDown(self):
        self.runtime.close()
        self.store.close()
        self.tmp.cleanup()

    def test_delete_cleans_sessions_but_preserves_shared_project_and_other_agent(self):
        project = self.store.add_project("Shared", str(self.root))
        agent = self.store.add_agent(project["id"], "Delete me", "codex")
        other = self.store.add_agent(project["id"], "Keep me", "claude")
        sibling = self.store.add_session(other["id"], "Preserved")
        sessions = [self.store.add_session(agent["id"], str(i)) for i in range(2)]
        shared = self.root / "shared.txt"
        shared.write_text("keep")
        for session in sessions:
            directory = self.store.session_directory(session["id"])
            directory.mkdir(parents=True)
            (directory / "project-link").symlink_to(self.root, target_is_directory=True)
            (directory / "history.jsonl").write_text("private")
            run = self.store.begin_run(session["id"], "Fixture")
            self.store.issue_capability(run["id"])
            self.store.finish_run(run["id"], "completed")
        memory = self.store.put_memory(project["id"], "Shared fact", "Keep this", 0)
        self.assertEqual(self.runtime.delete_agent(agent["id"]), {"ok": True})
        with self.assertRaises(Missing):
            self.store.get_agent(agent["id"])
        for session in sessions:
            self.assertFalse(self.store.session_directory(session["id"]).exists())
        self.assertEqual(self.store.get_session(sibling["id"])["agent_id"], other["id"])
        self.assertEqual(shared.read_text(), "keep")
        self.assertEqual(self.store.get_project(project["id"])["id"], project["id"])
        self.assertEqual(self.store.state()["memories"][0]["id"], memory["id"])
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM events WHERE session_id IS NOT NULL"
            ).fetchone()[0],
            0,
        )
        for table in ("runs", "capabilities", "approvals"):
            self.assertEqual(
                self.store.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0
            )
        self.assertEqual(
            self.store.db.execute("PRAGMA foreign_key_check").fetchall(), []
        )

    def test_all_sessions_are_checked_before_any_cleanup(self):
        agent = self.store.add_agent(None, "A", "codex")
        self.store.add_session(agent["id"], "Empty")
        active = self.store.add_session(agent["id"], "Pending")
        self.store.enqueue_run(active["id"], "Queued")
        cleanup = Mock()
        with self.assertRaisesRegex(Conflict, "Stop active tasks"):
            self.store.delete_agent(agent["id"], cleanup)
        cleanup.assert_not_called()
        self.assertEqual(len(self.store.state()["sessions"]), 2)

    def test_completed_delivery_without_return_still_blocks_deletion(self):
        project = self.store.add_project("P", str(self.root))
        sender = self.store.add_agent(project["id"], "Sender", "codex")
        receiver = self.store.add_agent(project["id"], "Receiver", "claude")
        session = self.store.add_session(sender["id"], "Parent")
        parent = self.store.begin_run(session["id"], "Delegate")
        message = self.store.enqueue_message(
            project["id"],
            sender["id"],
            receiver["id"],
            "Task",
            sender_session_id=session["id"],
            parent_run_id=parent["id"],
        )
        self.store.finish_run(parent["id"], "completed")
        child = self.store.claim_next_run()
        self.store.finish_run(child["id"], "completed")
        self.store.db.execute(
            "UPDATE messages SET status='completed' WHERE id=?", (message["id"],)
        )
        cleanup = Mock()
        for agent in (sender, receiver):
            with self.assertRaisesRegex(Conflict, "linked tasks"):
                self.store.delete_agent(agent["id"], cleanup)
        cleanup.assert_not_called()

    def test_remote_failure_keeps_all_records_and_retry_removes_only_owned_sessions(
        self,
    ):
        env = self.store.add_environment("Remote", "fixture-host")
        agent = self.store.add_agent(None, "A", "codex", environment_id=env["id"])
        sessions = [self.store.add_session(agent["id"], str(i)) for i in range(2)]
        for session in sessions:
            run = self.store.begin_run(session["id"], "Previous turn")
            self.store.finish_run(run["id"], "completed")
        self.runtime.remote.rpc = Mock(side_effect=[{"ok": True}, OSError("offline")])
        with self.assertRaisesRegex(Conflict, "Check the SSH connection and retry"):
            self.runtime.delete_agent(agent["id"])
        self.assertEqual(len(self.store.state()["sessions"]), 2)
        self.assertEqual(self.store.get_agent(agent["id"])["id"], agent["id"])
        self.runtime.remote.rpc = Mock(return_value={"ok": True})
        self.runtime.delete_agent(agent["id"])
        self.assertEqual(
            [
                call.args[1]["session_id"]
                for call in self.runtime.remote.rpc.call_args_list
            ],
            [s["id"] for s in sessions],
        )
        self.assertTrue(
            all(
                call.args[1]["op"] == "delete_session"
                for call in self.runtime.remote.rpc.call_args_list
            )
        )
        self.assertEqual(self.store.get_environment(env["id"])["id"], env["id"])

    def _returned_delivery(self):
        project = self.store.add_project("P", str(self.root))
        sender = self.store.add_agent(project["id"], "Sender", "codex")
        receiver = self.store.add_agent(project["id"], "Receiver", "claude")
        session = self.store.add_session(sender["id"], "Parent")
        parent = self.store.begin_run(session["id"], "Delegate")
        message = self.store.enqueue_message(
            project["id"],
            sender["id"],
            receiver["id"],
            "Task",
            parent_run_id=parent["id"],
        )
        self.store.finish_run(parent["id"], "completed")
        child = self.store.claim_next_run()
        self.store.finish_run(child["id"], "completed", result="Done")
        reply = self.store.enqueue_reply(message["id"], "Consume result")
        return parent, child, reply

    def _assert_history_protected(self, child):
        cleanup = Mock()
        with self.assertRaisesRegex(Conflict, "linked tasks"):
            self.store.delete_session(child["session_id"], cleanup)
        with self.assertRaisesRegex(Conflict, "linked tasks"):
            self.store.delete_agent(child["agent_id"], cleanup)
        cleanup.assert_not_called()

    def test_returned_child_remains_protected_until_requester_stops(self):
        for running in (False, True):
            with self.subTest(running=running):
                parent, child, reply = self._returned_delivery()
                if running:
                    self.assertEqual(self.store.claim_next_run()["id"], reply["id"])
                self._assert_history_protected(child)
                self.assertEqual(
                    self.store.cancel_run_tree(parent["id"]),
                    [reply["id"]] if running else [],
                )
                if running:
                    self.store.finish_run(reply["id"], "cancelled")
                self.assertEqual(self.store.get_run(reply["id"])["status"], "cancelled")
                self.store.delete_agent(child["agent_id"], Mock())

    def test_old_child_remains_protected_across_later_delegation_and_return_gap(self):
        parent, child, reply = self._returned_delivery()
        self.store.claim_next_run()
        third = self.store.add_agent(parent["project_id"], "Third", "codex")
        delivery = self.store.enqueue_message(
            parent["project_id"],
            parent["agent_id"],
            third["id"],
            "Follow up",
            parent_run_id=reply["id"],
        )
        self.store.finish_run(reply["id"], "completed")
        self._assert_history_protected(child)
        later = self.store.claim_next_run()
        self.store.finish_run(later["id"], "completed", result="Final result")
        self._assert_history_protected(child)
        final = self.store.enqueue_reply(delivery["id"], "Final result")
        self.store.claim_next_run()
        self.store.finish_run(final["id"], "completed")
        self.store.delete_session(child["session_id"], Mock())
        self.assertEqual(self.store.get_run(final["id"])["status"], "completed")

    def test_empty_agent_can_be_deleted_without_any_cli_or_ssh_call(self):
        env = self.store.add_environment("Remote", "fixture-host")
        agent = self.store.add_agent(None, "A", "claude", environment_id=env["id"])
        self.runtime.remote.rpc = Mock()
        self.runtime.delete_agent(agent["id"])
        self.runtime.remote.rpc.assert_not_called()
