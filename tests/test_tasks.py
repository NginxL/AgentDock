"""Task lifecycle and authority regressions; no native login/model or production host."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agentdock.server import API
from agentdock.store import Conflict, Forbidden, Invalid, Store


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.store = Store(self.path)
        self.project = self.store.add_project("Project", self.tmp.name)
        self.owner = self.store.add_agent(self.project["id"], "Owner", "codex")
        self.worker = self.store.add_agent(self.project["id"], "Worker", "claude")
        self.task = self.create()

    def test_history_returns_multiple_records_without_losing_large_record_chunks(self):
        current = self.start()
        with self.store.transaction():
            for index in range(30):
                self.store.db.execute(
                    "INSERT INTO task_journal(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
                    (
                        self.task["id"],
                        "fixture",
                        json.dumps(
                            {
                                "index": index,
                                "text": "x" * (17000 if index == 5 else 20),
                            }
                        ),
                        "2026-10-08",
                    ),
                )
        after = offset = 0
        chunks, complete, batch_sizes = {}, [], []
        while True:
            page = self.store.task_history(current, after, offset, 20)
            if not page["records"]:
                break
            batch_sizes.append(len(page["records"]))
            self.assertLessEqual(sum(len(r["text"]) for r in page["records"]), 16000)
            for record in page["records"]:
                chunks[record["seq"]] = chunks.get(record["seq"], "") + record["text"]
            after, offset = page["next_after"], page["next_offset"]
        complete = [json.loads(value) for value in chunks.values()]
        self.assertEqual(
            [r["index"] for r in complete if "index" in r], list(range(30))
        )
        self.assertGreater(max(batch_sizes), 1)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def create(self, **settings):
        return self.store.create_task(
            self.project["id"],
            "Feature",
            "Build feature",
            "Happy path\nFailure path",
            self.owner["id"],
            **settings,
        )

    def start(self, task=None, intent="develop", key="first"):
        task = task or self.task
        item = self.store.submit_task_input(task["id"], "Please proceed", intent, key)
        run = self.store.claim_next_run()
        self.assertEqual(run["id"], item["run_id"])
        return run

    def deliver(self, run, status="passed"):
        return self.store.task_delivery(
            run,
            "Implemented",
            [
                dict(criterion=c, status=status, evidence="Fixture validation")
                for c in self.task["criteria"].splitlines()
            ],
            ["src/feature.py"],
        )

    def finish(self, run, status="completed"):
        self.store.finish_run(
            run["id"], status, result="Raw report" if status == "completed" else None
        )
        self.store.refresh_work_task(run["id"])

    def test_draft_does_not_create_session_or_run(self):
        self.store.submit_task_input(self.task["id"], "Remember this", "record", "note")
        self.assertFalse(self.store.state()["runs"])
        self.assertFalse(self.store.state()["sessions"])
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "draft")

    def test_delivery_is_distinct_from_turn_completion(self):
        run = self.start()
        self.finish(run)
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "review")
        with self.assertRaises(Conflict):
            self.store.accept_task(self.task["id"])
        self.assertEqual(
            self.store.task_detail(self.task["id"])["journal"][-1]["payload"]["result"],
            "Raw report",
        )

    def test_verified_owner_delivery_accepts_only_after_execution_stops(self):
        run = self.start()
        delivery = self.deliver(run)
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "active")
        with self.assertRaises(Conflict):
            self.store.accept_task(self.task["id"])
        self.finish(run)
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "completed")
        self.assertEqual(
            self.store.task_detail(self.task["id"])["deliveries"][0]["status"],
            "accepted",
        )

    def test_human_policy_requires_human_acceptance_and_failed_checks_block(self):
        task = self.create(acceptance_policy="human")
        run = self.start(task)
        self.deliver(run)
        self.finish(run)
        self.assertEqual(self.store.get_task(task["id"])["status"], "review")
        self.assertEqual(self.store.accept_task(task["id"])["status"], "completed")
        run = self.start()
        self.deliver(run, "unverified")
        self.finish(run)
        with self.assertRaises(Conflict):
            self.store.accept_task(self.task["id"])

    def test_requires_exact_criteria_and_rejects_stale_delivery(self):
        run = self.start()
        with self.assertRaises(Invalid):
            self.store.task_delivery(
                run, "Done", [dict(criterion="Other", status="passed", evidence="test")]
            )
        self.store.submit_task_input(
            self.task["id"], "Changed requirement", "develop", "second"
        )
        with self.assertRaises(Conflict):
            self.deliver(run)
        self.finish(run)
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "active")

    def test_input_retries_are_idempotent_and_mutation_is_rejected(self):
        first = self.store.submit_task_input(self.task["id"], "Go", "develop", "same")
        self.assertEqual(
            first,
            self.store.submit_task_input(self.task["id"], "Go", "develop", "same"),
        )
        with self.assertRaises(Conflict):
            self.store.submit_task_input(self.task["id"], "Other", "develop", "same")
        self.assertEqual(len(self.store.state()["runs"]), 1)

    def test_questions_survive_finish_and_answers_resume_once(self):
        run = self.start()
        question = self.store.task_question(run, "Which format?", ["JSON", "CSV"])
        self.finish(run)
        self.assertEqual(
            self.store.get_task(self.task["id"])["status"], "waiting_input"
        )
        first = self.store.answer_task_question(self.task["id"], question["id"], "JSON")
        self.assertEqual(
            first,
            self.store.answer_task_question(self.task["id"], question["id"], "JSON"),
        )
        self.assertEqual(len(self.store.pending_runs()), 1)
        with self.assertRaises(Conflict):
            self.store.answer_task_question(self.task["id"], question["id"], "CSV")
        next_run = self.store.claim_next_run()
        self.assertIn("JSON", json.dumps(self.store.task_context(next_run)))

    def test_cross_project_owners_conversions_and_results_are_forbidden(self):
        other = self.store.add_project("Other", self.tmp.name)
        outsider = self.store.add_agent(other["id"], "Other owner", "codex")
        session = self.store.add_session(outsider["id"], "Other history")
        with self.assertRaises(Forbidden):
            self.store.create_task(self.project["id"], "T", "G", "C", outsider["id"])
        with self.assertRaises(Forbidden):
            self.create(source_session_id=session["id"])
        run = self.start()
        unrelated = self.store.add_session(self.owner["id"], "Private project chat")
        other_run = self.store.enqueue_run(unrelated["id"], "Other")
        with self.assertRaises(Forbidden):
            self.store.task_result(run, other_run["id"])

    def test_conversion_preserves_daily_chat_and_copies_context(self):
        agent = self.store.add_agent(None, "Daily", "codex")
        session = self.store.add_session(agent["id"], "Everyday")
        run = self.store.begin_run(session["id"], "Original question")
        self.store.finish_run(run["id"], "completed", result="Original reply")
        before = self.store.get_session(session["id"])
        task = self.create(source_session_id=session["id"])
        task_run = self.start(task)
        self.assertEqual(before, self.store.get_session(session["id"]))
        self.assertNotEqual(task_run["session_id"], session["id"])
        self.assertIn("Original reply", json.dumps(self.store.task_context(task_run)))

    def test_delegation_never_adopts_unrelated_history_and_worker_cannot_coordinate(
        self,
    ):
        unrelated = self.store.add_session(self.worker["id"], "Unrelated")
        run = self.start()
        message = self.store.enqueue_message(
            self.project["id"],
            self.owner["id"],
            self.worker["id"],
            "Implement part",
            parent_run_id=run["id"],
        )
        self.assertNotEqual(unrelated["id"], message["recipient_session_id"])
        self.assertEqual(
            self.store.get_session(message["recipient_session_id"])["work_task_id"],
            self.task["id"],
        )
        self.finish(run)
        child = self.store.claim_next_run()
        with self.assertRaises(Forbidden):
            self.deliver(child)
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                self.worker["id"],
                self.owner["id"],
                "Loop",
                parent_run_id=child["id"],
            )
        self.store.finish_run(child["id"], "completed", result="Child report")
        reply = self.store.enqueue_reply(message["id"], "Read child report")
        self.store.refresh_work_task(child["id"])
        followup = self.store.claim_next_run()
        self.assertEqual(reply["id"], followup["id"])
        self.assertEqual(followup["task_role"], "owner")
        self.assertEqual(
            self.store.task_result(followup, child["id"])["text"], "Child report"
        )
        self.deliver(followup)
        self.finish(followup)
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "completed")

    def test_review_is_required_and_new_inputs_invalidate_old_review(self):
        task = self.create(review_required=True)
        run = self.start(task)
        self.deliver(run)
        self.finish(run)
        self.assertEqual(self.store.get_task(task["id"])["status"], "review")
        with self.assertRaises(Conflict):
            self.store.accept_task(task["id"])
        run = self.start(task, key="review-request")
        message = self.store.enqueue_message(
            self.project["id"],
            self.owner["id"],
            self.worker["id"],
            "Review",
            parent_run_id=run["id"],
            task_role="reviewer",
        )
        self.finish(run)
        review = self.store.claim_next_run()
        self.store.task_review(review, "approved", "All criteria independently checked")
        self.store.finish_run(review["id"], "completed", result="Reviewed changes")
        self.store.enqueue_reply(message["id"], "Review report")
        followup = self.store.claim_next_run()
        self.deliver(followup)
        self.finish(followup)
        self.assertEqual(self.store.get_task(task["id"])["status"], "completed")

    def test_discussion_cannot_deliver_delegate_or_write_memory(self):
        run = self.start(intent="discuss")
        with self.assertRaises(Conflict):
            self.deliver(run)
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                self.owner["id"],
                self.worker["id"],
                "Implement",
                parent_run_id=run["id"],
            )
        token = self.store.issue_capability(run["id"])
        with self.assertRaises(Forbidden):
            self.store.respond_tool(
                token, "memory_propose", dict(key="k", content="c", expected_version=0)
            )
        self.finish(run)
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "draft")
        execution = self.start(key="execution")
        self.assertNotEqual(run["session_id"], execution["session_id"])

    def test_restart_requires_explicit_recovery_preserves_decisions_and_reassigns(self):
        run = self.start()
        question = self.store.task_question(run, "Where?")
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get_run(run["id"])["status"], "interrupted")
        self.store.answer_task_question(self.task["id"], question["id"], "Here")
        pending = self.store.pending_runs()
        self.assertFalse(
            pending
        )  # A restart never silently resumes an unknown old process.
        self.store.task_transition(self.task["id"], "pause")
        task = self.store.resume_task(self.task["id"], self.worker["id"])
        self.assertEqual(task["owner_id"], self.worker["id"])
        next_run = self.store.claim_next_run()
        self.assertNotEqual(run["session_id"], next_run["session_id"])
        self.assertIn("Here", json.dumps(self.store.task_context(next_run)))

    def test_task_records_survive_disposable_session_deletion(self):
        run = self.start()
        self.deliver(run)
        self.finish(run)
        self.store.delete_session(run["session_id"], lambda *_: None)
        detail = self.store.task_detail(self.task["id"])
        self.assertEqual(detail["deliveries"][0]["summary"], "Implemented")
        self.assertTrue(any(e["kind"] == "run_finished" for e in detail["journal"]))
        self.assertFalse(detail["sessions"])

    def test_active_task_blocks_deleting_owner_and_task_session(self):
        run = self.start()
        self.finish(run)
        with self.assertRaises(Conflict):
            self.store.delete_agent(self.owner["id"], lambda *_: None)
        with self.assertRaises(Conflict):
            self.store.delete_session(run["session_id"], lambda *_: None)

    def test_api_task_boundaries_and_review_mode(self):
        runtime = Mock(config={})
        runtime._runs = {}
        api = API(self.store, runtime, Mock(), "admin")
        h = {
            "Host": "127.0.0.1:47831",
            "Authorization": "Bearer admin",
            "Content-Type": "application/json",
        }
        path = "/api/tasks/" + self.task["id"]
        try:
            self.assertEqual(api.dispatch("GET", path, h)[0], 200)
            self.assertEqual(
                api.dispatch("GET", path, {**h, "Authorization": "Bearer wrong"})[0],
                401,
            )
            self.assertEqual(api.dispatch("POST", path + "/resume", h, b"{}")[0], 403)
            self.assertEqual(
                api.dispatch(
                    "POST",
                    path + "/inputs",
                    h,
                    json.dumps(
                        {"body": "go", "intent": "develop", "request_id": "id"}
                    ).encode(),
                )[0],
                403,
            )
            runtime.recover_task.assert_not_called()
        finally:
            api.close()

    def test_editing_requirements_invalidates_delivery_but_not_history(self):
        task = self.create(acceptance_policy="human")
        run = self.start(task)
        with self.assertRaises(Conflict):
            self.store.update_task(task["id"], "T", "G", "New check", "human", False)
        self.deliver(run)
        self.finish(run)
        updated = self.store.update_task(
            task["id"], "T", "G", "New check", "human", False
        )
        self.assertIsNone(updated["delivery_id"])
        self.assertEqual(updated["status"], "draft")
        self.assertEqual(len(self.store.task_detail(task["id"])["deliveries"]), 1)
        with self.assertRaises(Conflict):
            self.store.accept_task(task["id"])

    def test_negative_review_blocks_acceptance(self):
        task = self.create(review_required=True)
        owner = self.start(task)
        with self.assertRaises(Forbidden):
            self.store.task_review(owner, "approved", "Self review")
        message = self.store.enqueue_message(
            self.project["id"],
            self.owner["id"],
            self.worker["id"],
            "Review",
            parent_run_id=owner["id"],
            task_role="reviewer",
        )
        self.finish(owner)
        reviewer = self.store.claim_next_run()
        self.store.task_review(reviewer, "changes_requested", "Missing error case")
        self.store.finish_run(reviewer["id"], "completed", result="Fix error handling")
        self.store.enqueue_reply(message["id"], "Read the review")
        owner = self.store.claim_next_run()
        self.deliver(owner)
        self.finish(owner)
        with self.assertRaisesRegex(Conflict, "approved independent review"):
            self.store.accept_task(task["id"])

    def test_history_pages_preserve_full_inputs_and_deleted_run_reports(self):
        body = "数据" * 11000
        self.store.submit_task_input(self.task["id"], body, "record", "large")
        run = self.start()
        self.deliver(run)
        self.finish(run)
        self.store.delete_session(run["session_id"], lambda *_: None)
        self.store.task_transition(self.task["id"], "reopen")
        current = self.start(key="continue")
        self.assertEqual(
            self.store.task_result(current, run["id"])["text"], "Raw report"
        )
        after = offset = 0
        records = []
        pieces = []
        while True:
            page = self.store.task_history(current, after, offset)
            if page.get("record", "not-end") is None:
                break
            self.assertLessEqual(len(page["text"]), 16000)
            pieces.append(page["text"])
            if page["next_offset"] == 0:
                records.append(json.loads("".join(pieces)))
                pieces = []
            after, offset = page["next_after"], page["next_offset"]
        self.assertTrue(any(r.get("body") == body for r in records))
        self.assertLess(len(self.store.context_for_run(current["id"]).encode()), 400000)

    def test_manual_dispatch_cannot_bypass_task_input_and_role_retry_is_rejected(self):
        owner = self.start()
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                self.project["id"],
                "human",
                self.owner["id"],
                "Bypass",
                recipient_session_id=owner["session_id"],
            )
        self.store.enqueue_message(
            self.project["id"],
            self.owner["id"],
            self.worker["id"],
            "Part",
            parent_run_id=owner["id"],
            idempotency_key="same",
        )
        with self.assertRaises(Conflict):
            self.store.enqueue_message(
                self.project["id"],
                self.owner["id"],
                self.worker["id"],
                "Part",
                parent_run_id=owner["id"],
                idempotency_key="same",
                task_role="reviewer",
            )

    def test_worktree_reviewer_targets_owner_files_without_adopting_history(self):
        task = self.create(workspace_mode="worktree")
        owner = self.start(task)
        message = self.store.enqueue_message(
            self.project["id"],
            self.owner["id"],
            self.worker["id"],
            "Review",
            parent_run_id=owner["id"],
            task_role="reviewer",
        )
        reviewer = self.store.get_session(message["recipient_session_id"])
        self.assertEqual(
            reviewer["workspace"],
            self.store.get_session(owner["session_id"])["workspace"],
        )
        self.assertNotEqual(reviewer["id"], owner["session_id"])

    def test_recovery_idempotency_prevents_second_execution_after_lost_response(self):
        self.store.task_transition(self.task["id"], "pause")
        self.store.resume_task(
            self.task["id"], self.owner["id"], "develop", "resume-once"
        )
        run = self.store.claim_next_run()
        self.finish(run)
        before = len(self.store.task_detail(self.task["id"])["runs"])
        self.store.resume_task(
            self.task["id"], self.owner["id"], "develop", "resume-once"
        )
        self.assertEqual(len(self.store.task_detail(self.task["id"])["runs"]), before)
        with self.assertRaises(Conflict):
            self.store.resume_task(
                self.task["id"], self.worker["id"], "develop", "resume-once"
            )

    def test_open_questions_block_new_queued_work_until_answered(self):
        run = self.start()
        q = self.store.task_question(run, "Choose")
        self.store.submit_task_input(
            self.task["id"], "Additional requirement", "develop", "next"
        )
        self.finish(run)
        self.assertIsNone(self.store.claim_next_run())
        self.store.answer_task_question(self.task["id"], q["id"], "Confirmed")
        self.assertIsNotNone(self.store.claim_next_run())


if __name__ == "__main__":
    unittest.main()
