import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agentdock.store import Conflict, Forbidden, Invalid, Store


class DispatchStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "state.sqlite3")
        self.project = self.store.add_project("One", str(self.root))
        self.a = self.store.add_agent(self.project["id"], "Planner", "codex", "Plan")
        self.b = self.store.add_agent(self.project["id"], "Builder", "claude", "Build")
        self.session = self.store.add_session(self.a["id"], "Task")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_queued_run_has_no_user_message_until_claim(self):
        run = self.store.enqueue_run(self.session["id"], "First")
        self.assertEqual(run["status"], "queued")
        self.assertFalse(
            any(
                e["kind"] == "user_message"
                for e in self.store.session_events(self.session["id"])
            )
        )
        self.assertEqual(self.store.claim_next_run()["id"], run["id"])
        self.assertEqual(
            len(
                [
                    e
                    for e in self.store.session_events(self.session["id"])
                    if e["kind"] == "user_message"
                ]
            ),
            1,
        )
        self.assertIsNone(self.store.claim_next_run())

    def test_concurrent_claim_has_single_winner(self):
        run = self.store.enqueue_run(self.session["id"], "One")
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.store.claim_next_run(), range(6)))
        self.assertEqual([x["id"] for x in results if x], [run["id"]])

    def test_workspace_queue_skips_blocked_without_losing_order(self):
        outer = self.store.begin_run(self.session["id"], "Active")
        sub = self.root / "sub"
        sub.mkdir()
        nested = self.store.add_project("Nested", str(sub))
        nested_agent = self.store.add_agent(nested["id"], "Nested", "claude")
        nested_session = self.store.add_session(nested_agent["id"], "Queued")
        blocked = self.store.enqueue_run(nested_session["id"], "Must wait")
        with tempfile.TemporaryDirectory() as elsewhere:
            separate = self.store.add_project("Separate", elsewhere)
            other = self.store.add_agent(separate["id"], "Parallel", "codex")
            other_session = self.store.add_session(other["id"], "Independent")
            independent = self.store.enqueue_run(other_session["id"], "Can run")
            self.assertEqual(self.store.claim_next_run()["id"], independent["id"])
            self.assertIsNone(self.store.claim_next_run())
            self.store.finish_run(outer["id"], "completed")
            self.assertEqual(self.store.claim_next_run()["id"], blocked["id"])

    def test_same_agent_sessions_serialize_and_cancelling_queue_keeps_active_status(
        self,
    ):
        active = self.store.begin_run(self.session["id"], "Active")
        queued = self.store.enqueue_run(self.session["id"], "Later")
        self.assertEqual(
            self.store.get_session(self.session["id"])["status"], "running"
        )
        self.store.cancel_queued_run(queued["id"])
        self.assertEqual(
            self.store.get_session(self.session["id"])["status"], "running"
        )
        self.assertIsNone(self.store.claim_next_run())
        self.store.finish_run(active["id"], "completed")
        self.assertEqual(
            self.store.get_session(self.session["id"])["status"], "completed"
        )
        with self.assertRaises(Conflict):
            self.store.cancel_queued_run(queued["id"])

    def test_session_binding_persists_but_cannot_be_replaced_or_shared(self):
        run = self.store.begin_run(self.session["id"], "First")
        self.store.bind_native_session(self.session["id"], "native-one", run["id"])
        self.store.bind_native_session(self.session["id"], "native-one", run["id"])
        with self.assertRaises(Conflict):
            self.store.bind_native_session(self.session["id"], "other", run["id"])
        other = self.store.add_session(self.a["id"], "Other")
        with self.assertRaises(Conflict):
            self.store.bind_native_session(other["id"], "native-one")
        with self.assertRaises(Forbidden):
            self.store.bind_native_session(other["id"], "native-two", run["id"])
        self.store.finish_run(run["id"], "completed")
        self.store.close()
        self.store = Store(self.root / "state.sqlite3")
        self.assertEqual(
            self.store.get_session(self.session["id"])["native_session_id"],
            "native-one",
        )

    def test_native_context_excludes_recorded_conversation_and_messages(self):
        self.store.put_memory(self.project["id"], "Rule", "APPROVED_RULE", 0)
        self.store.append_event(
            self.project["id"],
            self.session["id"],
            "assistant_message",
            {"text": "OLD_ASSISTANT_OUTPUT"},
        )
        self.store.send_message(
            self.project["id"], "human", self.a["id"], "UNCLAIMED_DELIVERY"
        )
        run = self.store.begin_run(self.session["id"], "CURRENT_PROMPT")
        context = self.store.context_for_run(run["id"])
        self.assertIn("APPROVED_RULE", context)
        for excluded in (
            "OLD_ASSISTANT_OUTPUT",
            "UNCLAIMED_DELIVERY",
            "CURRENT_PROMPT",
            "recent_conversation",
            '"inbox"',
        ):
            self.assertNotIn(excluded, context)

    def test_human_dispatch_resolves_latest_session_or_creates_one(self):
        newest = self.store.add_session(self.a["id"], "Recent")
        m = self.store.send_message(
            self.project["id"], "human", self.a["id"], "To recent"
        )
        self.assertEqual(m["recipient_session_id"], newest["id"])
        new = self.store.send_message(
            self.project["id"], "human", self.b["id"], "New agent"
        )
        self.assertEqual(
            self.store.get_session(new["recipient_session_id"])["agent_id"],
            self.b["id"],
        )
        self.assertIsNone(
            self.store.enqueue_reply(new["id"], "No automatic reply to a person")
        )

    def test_dispatch_ownership_and_self_delegation(self):
        run = self.store.begin_run(self.session["id"], "Start")
        bs = self.store.add_session(self.b["id"], "Builder")
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                self.a["id"],
                self.b["id"],
                "No",
                parent_run_id=run["id"],
                sender_session_id=bs["id"],
            )
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                self.a["id"],
                self.b["id"],
                "No",
                parent_run_id=run["id"],
                recipient_session_id=self.session["id"],
            )
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"], "human", self.b["id"], "No", parent_run_id=run["id"]
            )
        with self.assertRaises(Invalid):
            self.store.enqueue_message(
                self.project["id"],
                self.a["id"],
                self.a["id"],
                "No",
                parent_run_id=run["id"],
            )
        self.store.finish_run(run["id"], "completed")
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                self.a["id"],
                self.b["id"],
                "Too late",
                parent_run_id=run["id"],
            )

    def test_concurrent_dispatch_dedup_does_not_duplicate_runs(self):
        parent = self.store.begin_run(self.session["id"], "Start")

        def dispatch(_):
            return self.store.enqueue_message(
                self.project["id"],
                self.a["id"],
                self.b["id"],
                "Review",
                idempotency_key="same",
                parent_run_id=parent["id"],
            )

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(dispatch, range(5)))
        self.assertEqual(len({x["run_id"] for x in results}), 1)
        self.assertEqual(len(self.store.runs_for_root(parent["id"])), 2)

    def test_depth_limit_is_atomic_and_no_orphan_message_is_left(self):
        current = self.store.begin_run(self.session["id"], "Start")
        for depth in range(1, 4):
            recipient = self.b if current["agent_id"] == self.a["id"] else self.a
            message = self.store.enqueue_message(
                self.project["id"],
                current["agent_id"],
                recipient["id"],
                "Next",
                parent_run_id=current["id"],
            )
            self.store.finish_run(current["id"], "completed")
            current = self.store.claim_next_run()
            self.assertEqual(current["id"], message["run_id"])
            self.assertEqual(current["depth"], depth)
        recipient = self.b if current["agent_id"] == self.a["id"] else self.a
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                current["agent_id"],
                recipient["id"],
                "Too deep",
                parent_run_id=current["id"],
            )
        self.assertEqual(len(self.store.state()["messages"]), 3)
        self.assertEqual(len(self.store.runs_for_root(current["root_run_id"])), 4)

    def test_reply_returns_to_sender_depth_and_has_single_concurrent_winner(self):
        parent = self.store.begin_run(self.session["id"], "Start")
        message = self.store.enqueue_message(
            self.project["id"],
            self.a["id"],
            self.b["id"],
            "Review",
            parent_run_id=parent["id"],
        )
        self.store.finish_run(parent["id"], "completed")
        child = self.store.claim_next_run()
        self.store.finish_run(child["id"], "completed", result="RESULT")
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(
                pool.map(
                    lambda _: self.store.enqueue_reply(message["id"], "RESULT"),
                    range(4),
                )
            )
        self.assertEqual(len({x["id"] for x in replies}), 1)
        self.assertEqual(replies[0]["depth"], parent["depth"])
        self.assertEqual(replies[0]["root_run_id"], parent["id"])
        self.assertEqual(replies[0]["parent_run_id"], child["id"])
        self.assertEqual(self.store.get_message(message["id"])["result"], "RESULT")

    def test_chain_budget_prevents_infinite_reply_delegate_loops(self):
        current = self.store.begin_run(self.session["id"], "Start")
        root = current["id"]
        for index in range(7):
            recipient = self.b if current["agent_id"] == self.a["id"] else self.a
            message = self.store.enqueue_message(
                self.project["id"],
                current["agent_id"],
                recipient["id"],
                "Review",
                parent_run_id=current["id"],
            )
            self.store.finish_run(current["id"], "completed")
            child = self.store.claim_next_run()
            self.store.finish_run(child["id"], "completed")
            self.store.enqueue_reply(message["id"], "Done")
            current = self.store.claim_next_run()
        self.assertEqual(len(self.store.runs_for_root(root)), 15)
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                current["agent_id"],
                self.b["id"],
                "No unreturnable child",
                parent_run_id=current["id"],
            )
        self.assertEqual(len(self.store.runs_for_root(root)), 15)
        self.assertEqual(len(self.store.state()["messages"]), 7)

    def test_fanout_reserves_capacity_for_every_child_result(self):
        parent = self.store.begin_run(self.session["id"], "Coordinate reviews")
        deliveries = [
            self.store.enqueue_message(
                self.project["id"],
                self.a["id"],
                self.b["id"],
                "Review " + str(i),
                parent_run_id=parent["id"],
            )
            for i in range(7)
        ]
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                self.a["id"],
                self.b["id"],
                "Eighth child cannot reserve reply",
                parent_run_id=parent["id"],
            )
        self.store.finish_run(parent["id"], "completed")
        for delivery in deliveries:
            child = self.store.claim_next_run()
            self.assertEqual(child["id"], delivery["run_id"])
            self.store.finish_run(child["id"], "completed", result="Done")
            self.store.enqueue_reply(delivery["id"], "Child result")
        self.assertEqual(len(self.store.runs_for_root(parent["id"])), 15)
        self.assertTrue(
            all(self.store.get_message(d["id"])["reply_run_id"] for d in deliveries)
        )
        for _ in deliveries:
            reply = self.store.claim_next_run()
            self.assertEqual(reply["origin"], "reply")
            self.store.finish_run(reply["id"], "completed")
        self.assertIsNone(self.store.claim_next_run())

    def test_cancel_tree_cancels_queued_descendants_and_returns_active_ids(self):
        parent = self.store.begin_run(self.session["id"], "Start")
        message = self.store.enqueue_message(
            self.project["id"],
            self.a["id"],
            self.b["id"],
            "Review",
            parent_run_id=parent["id"],
        )
        self.assertEqual(self.store.cancel_run_tree(parent["id"]), [parent["id"]])
        self.assertEqual(self.store.get_run(message["run_id"])["status"], "cancelled")
        self.assertEqual(self.store.get_message(message["id"])["status"], "cancelled")
        self.store.finish_run(parent["id"], "cancelled")
        self.assertIsNone(self.store.claim_next_run())

    def test_reply_is_not_generated_for_failed_requester(self):
        parent = self.store.begin_run(self.session["id"], "Start")
        message = self.store.enqueue_message(
            self.project["id"],
            self.a["id"],
            self.b["id"],
            "Review",
            parent_run_id=parent["id"],
        )
        self.store.finish_run(parent["id"], "failed")
        self.assertIsNone(self.store.claim_next_run())
        self.assertEqual(self.store.get_run(message["run_id"])["status"], "cancelled")
        with self.assertRaises(Conflict):
            self.store.enqueue_reply(message["id"], "No replay")

    def test_cancel_waiting_task_returns_cancelled_result_without_stranding_parent(
        self,
    ):
        parent = self.store.begin_run(self.session["id"], "Start")
        delivery = self.store.enqueue_message(
            self.project["id"],
            self.a["id"],
            self.b["id"],
            "Build",
            parent_run_id=parent["id"],
        )
        self.store.finish_run(parent["id"], "completed")
        builder = self.store.claim_next_run()
        reviewer = self.store.add_agent(self.project["id"], "Reviewer", "codex")
        nested = self.store.enqueue_message(
            self.project["id"],
            self.b["id"],
            reviewer["id"],
            "Review",
            parent_run_id=builder["id"],
        )
        self.store.finish_run(builder["id"], "completed", result="Review requested")
        self.assertEqual(self.store.get_message(delivery["id"])["status"], "waiting")
        self.assertIsNone(self.store.settle_task(builder["id"]))
        self.assertEqual(self.store.cancel_run_tree(builder["id"]), [])
        settled = self.store.settle_task(builder["id"])
        self.assertEqual(settled["status"], "cancelled")
        self.assertEqual(self.store.get_run(nested["run_id"])["status"], "cancelled")
        reply = self.store.enqueue_reply(
            delivery["id"], "The builder task was cancelled."
        )
        self.assertEqual(reply["task_run_id"], parent["id"])
        self.assertEqual(self.store.claim_next_run()["id"], reply["id"])

    def test_session_cancellation_finds_waiting_tasks_and_not_delivered_history(self):
        parent = self.store.begin_run(self.session["id"], "Start")
        delivery = self.store.enqueue_message(
            self.project["id"],
            self.a["id"],
            self.b["id"],
            "Build",
            parent_run_id=parent["id"],
        )
        self.store.finish_run(parent["id"], "completed")
        self.assertEqual(self.store.pending_runs(self.session["id"]), [])
        self.assertEqual(
            [t["id"] for t in self.store.cancellable_tasks(self.session["id"])],
            [parent["id"]],
        )
        child = self.store.claim_next_run()
        self.store.finish_run(child["id"], "completed", result="Done")
        self.assertEqual(
            [t["id"] for t in self.store.cancellable_tasks(child["session_id"])],
            [child["id"]],
        )
        reply = self.store.enqueue_reply(delivery["id"], "Done")
        self.assertEqual(self.store.cancellable_tasks(child["session_id"]), [])
        self.assertEqual(
            [t["id"] for t in self.store.cancellable_tasks(self.session["id"])],
            [parent["id"]],
        )
        self.store.claim_next_run()
        self.store.finish_run(reply["id"], "completed")
        self.assertEqual(self.store.cancellable_tasks(self.session["id"]), [])
        self.assertEqual(self.store.cancel_run_tree(child["id"]), [])
        self.assertEqual(self.store.get_run(reply["id"])["status"], "completed")

    def test_cancelling_fully_completed_human_task_preserves_history(self):
        run = self.store.begin_run(self.session["id"], "Complete task")
        self.store.finish_run(run["id"], "completed", result="Preserved result")
        before = self.store.get_run(run["id"])
        events_before = self.store.session_events(self.session["id"])
        self.assertEqual(self.store.cancel_run_tree(run["id"]), [])
        self.assertEqual(self.store.get_run(run["id"]), before)
        self.assertEqual(self.store.session_events(self.session["id"]), events_before)
        self.assertEqual(
            self.store.get_session(self.session["id"])["status"], "completed"
        )

        delivery = self.store.send_message(
            self.project["id"], "human", self.b["id"], "Complete delivered task"
        )
        child = self.store.claim_next_run()
        self.store.finish_run(child["id"], "completed", result="Preserved delivery")
        delivery_before = self.store.get_message(delivery["id"])
        self.assertEqual(self.store.cancel_run_tree(child["id"]), [])
        self.assertEqual(self.store.get_run(child["id"])["status"], "completed")
        self.assertEqual(self.store.get_message(delivery["id"]), delivery_before)

    def test_session_cancel_scope_includes_independent_tasks_but_excludes_other_sessions(
        self,
    ):
        first = self.store.enqueue_run(self.session["id"], "First")
        second = self.store.enqueue_run(self.session["id"], "Second")
        other_session = self.store.add_session(self.a["id"], "Other conversation")
        other = self.store.enqueue_run(other_session["id"], "Other")
        self.assertEqual(
            [t["id"] for t in self.store.cancellable_tasks(self.session["id"])],
            [first["id"], second["id"]],
        )
        self.assertEqual(
            [t["id"] for t in self.store.cancellable_tasks(other_session["id"])],
            [other["id"]],
        )
        self.store.cancel_run_tree(first["id"])
        self.assertEqual(
            [t["id"] for t in self.store.cancellable_tasks(self.session["id"])],
            [second["id"]],
        )

    def test_restart_interrupts_queue_and_delivery_without_replay(self):
        parent = self.store.begin_run(self.session["id"], "Start")
        message = self.store.enqueue_message(
            self.project["id"],
            self.a["id"],
            self.b["id"],
            "Review",
            parent_run_id=parent["id"],
        )
        token = self.store.issue_capability(parent["id"])
        self.store.close()
        self.store = Store(self.root / "state.sqlite3")
        self.assertEqual(self.store.get_run(parent["id"])["status"], "interrupted")
        self.assertEqual(self.store.get_run(message["run_id"])["status"], "interrupted")
        self.assertEqual(self.store.get_message(message["id"])["status"], "interrupted")
        self.assertIsNone(self.store.claim_next_run())
        with self.assertRaises(Forbidden):
            self.store.capability_run(token)

    def test_old_mailbox_migrates_to_legacy_without_dispatch(self):
        old_path = self.root / "legacy.sqlite3"
        db = sqlite3.connect(old_path)
        db.executescript("""
        CREATE TABLE messages(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,sender_id TEXT NOT NULL,recipient_id TEXT NOT NULL,body TEXT NOT NULL,correlation_id TEXT,status TEXT NOT NULL,idempotency_key TEXT,created_at TEXT NOT NULL,acknowledged_at TEXT);
        INSERT INTO messages VALUES('old','project','human','agent','Do not run',NULL,'queued',NULL,'2026-01-01',NULL);
        """)
        db.close()
        migrated = Store(old_path)
        try:
            self.assertEqual(migrated.get_message("old")["status"], "legacy")
            self.assertIsNone(migrated.get_message("old")["run_id"])
            self.assertIsNone(migrated.claim_next_run())
            self.assertEqual(migrated.state()["runs"], [])
        finally:
            migrated.close()

    def test_state_runs_are_bounded_and_contain_delivery_metadata(self):
        for index in range(305):
            self.store.enqueue_run(self.session["id"], str(index))
        state = self.store.state()
        self.assertEqual(len(state["runs"]), 300)
        self.assertEqual(len(self.store.pending_runs()), 305)
        self.assertEqual(len(self.store.pending_runs(self.session["id"])), 305)
        self.assertEqual(state["runs"][-1]["prompt"], "304")
        self.assertIn("native_session_id", state["sessions"][0])
        self.assertIn("root_run_id", state["runs"][0])


if __name__ == "__main__":
    unittest.main()
