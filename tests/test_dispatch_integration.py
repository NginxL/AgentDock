"""Full local dispatch path using fake native processes and the real MCP HTTP bridge."""

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from agentdock.loopback_server import LoopbackServer
from pathlib import Path

from agentdock.runtime import Runtime, RuntimeFailure
from agentdock.server import API, handler_for
from agentdock.store import Store

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).with_name("fake_dispatch_native.py")


class NoQuota:
    def cached(self, provider):
        raise AssertionError("Native dispatch tests must never probe quotas")

    def refresh(self, provider):
        raise AssertionError("Native dispatch tests must never probe quotas")


class DispatchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.store = Store(self.directory / "state.sqlite3")
        self.project = self.store.add_project("Fixture project", str(self.directory))
        self.a = self.store.add_agent(self.project["id"], "Planner", "codex")
        self.b = self.store.add_agent(self.project["id"], "Builder", "claude")
        self.sa = self.store.add_session(self.a["id"], "Original planner conversation")
        self.sb = self.store.add_session(self.b["id"], "Builder conversation")
        self.runtime = None
        self.server = LoopbackServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.server.daemon_threads = True
        self.server_thread = None

    def tearDown(self):
        if self.runtime:
            self.runtime.close()
        if self.server_thread:
            self.server.shutdown()
            self.server_thread.join(timeout=2)
        self.server.server_close()
        self.store.close()
        self.tmp.cleanup()

    def start_runtime(self, mode="delegate"):
        port = self.server.server_address[1]
        self.runtime = Runtime(
            self.store,
            {
                "execution_enabled": True,
                "commands": {
                    provider: [sys.executable, str(FIXTURE), provider, mode]
                    for provider in ("codex", "claude")
                },
                "python": sys.executable,
                "package_root": str(ROOT),
                "base_url": "http://127.0.0.1:" + str(port),
                "run_timeout": 8,
                "approval_timeout": 2,
            },
        )
        api = API(
            self.store, self.runtime, NoQuota(), "fixture-admin-token", port, True
        )
        self.server.RequestHandlerClass = handler_for(api, self.directory)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        self.server_thread.start()
        return self.runtime

    def wait_for(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(
            "Fake native integration timed out: "
            + json.dumps(self.store.state()["runs"])
        )

    def transcript(self):
        path = self.directory / "native-transcript.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def test_project_goal_question_review_and_delivery_over_native_mcp(self):
        runtime = self.start_runtime("project_task")
        task = self.store.create_task(
            self.project["id"],
            "Feature",
            "Implement JSON output",
            "Outputs JSON",
            self.a["id"],
            review_required=True,
        )
        runtime.submit_task(task["id"], "Please start", "develop", "start-task")
        self.wait_for(
            lambda: (
                self.store.get_task(task["id"])["status"] == "waiting_input"
                and not self.store.pending_runs()
            )
        )
        detail = self.store.task_detail(task["id"])
        self.assertIsNone(detail["delivery_id"])
        question = detail["questions"][0]
        runtime.answer_task(task["id"], question["id"], "JSON")
        self.wait_for(lambda: self.store.get_task(task["id"])["status"] == "completed")
        detail = self.store.task_detail(task["id"])
        self.assertEqual(
            [r["task_role"] for r in detail["runs"]],
            ["owner", "owner", "reviewer", "owner"],
        )
        self.assertEqual(detail["reviews"][0]["verdict"], "approved")
        self.assertEqual(detail["deliveries"][0]["status"], "accepted")
        self.assertEqual(detail["questions"][0]["answer"], "JSON")
        self.assertIsNone(self.store.get_session(self.sa["id"])["native_session_id"])
        self.assertIsNone(self.store.get_session(self.sb["id"])["native_session_id"])
        self.assertEqual(
            len({r["session_id"] for r in detail["runs"] if r["task_role"] == "owner"}),
            1,
        )

    def test_codex_to_claude_to_same_codex_session_over_real_bridge(self):
        self.store.put_memory(
            self.project["id"], "Project rule", "Use the reviewed contract.", 0
        )
        other = self.store.add_project("Foreign project", str(self.directory))
        foreign = self.store.add_agent(other["id"], "Foreign builder", "claude")
        (self.directory / "fixture-control.json").write_text(
            json.dumps({"foreign_agent": foreign["id"]})
        )
        runtime = self.start_runtime()
        root = runtime.start(self.sa["id"], "<fixture-delegate> Build the feature.")
        self.wait_for(
            lambda: (
                len(self.store.runs_for_root(root["id"])) == 3
                and all(
                    r["status"] == "completed"
                    for r in self.store.runs_for_root(root["id"])
                )
            )
        )
        chain = self.store.runs_for_root(root["id"])
        self.assertEqual([r["origin"] for r in chain], ["human", "delegate", "reply"])
        self.assertEqual(
            [r["agent_id"] for r in chain], [self.a["id"], self.b["id"], self.a["id"]]
        )
        messages = self.store.state()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["reply_run_id"], chain[2]["id"])
        self.assertIn("Use the reviewed contract.", messages[0]["result"])
        self.assertEqual(messages[0]["status"], "completed")
        log = self.transcript()
        starts = [e for e in log if e["method"] in ("thread/start", "thread/resume")]
        self.assertEqual(
            [e["method"] for e in starts], ["thread/start", "thread/resume"]
        )
        self.assertEqual(starts[0]["native_id"], starts[1]["native_id"])
        self.assertEqual(
            self.store.get_session(self.sa["id"])["native_session_id"],
            starts[0]["native_id"],
        )
        prompts = [e["prompt"] for e in log if e["method"] == "turn/start"]
        self.assertIn("Claude implemented the plan.", prompts[1])
        self.assertNotIn("<fixture-delegate>", prompts[1])
        self.assertTrue(any(e["method"] == "cross_project_rejected" for e in log))
        self.assertEqual(len(self.store.state()["proposals"]), 1)
        self.assertEqual(self.store.state()["proposals"][0]["status"], "pending")
        self.assertEqual(len(self.store.state()["memories"]), 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM capabilities WHERE revoked=0"
            ).fetchone()[0],
            0,
        )

        # Claude's next human turn must also keep its own provider session.
        followup = runtime.start(self.sb["id"], "Continue the implementation review.")
        self.wait_for(
            lambda: self.store.get_run(followup["id"])["status"] == "completed"
        )
        claude_starts = [
            e
            for e in self.transcript()
            if e["method"] in ("claude/start", "claude/resume")
        ]
        self.assertEqual(
            [e["method"] for e in claude_starts], ["claude/start", "claude/resume"]
        )
        self.assertEqual(claude_starts[0]["native_id"], claude_starts[1]["native_id"])

    def test_nested_delegation_returns_final_composed_result_to_original_sender(self):
        reviewer = self.store.add_agent(self.project["id"], "Reviewer", "codex")
        self.store.add_session(reviewer["id"], "Review session")
        runtime = self.start_runtime("nested")
        root = runtime.start(self.sa["id"], "<fixture-delegate> Build and review.")
        self.wait_for(
            lambda: (
                len(self.store.runs_for_root(root["id"])) >= 5
                and not self.store.pending_runs()
            )
        )
        builder_delivery = next(
            m
            for m in self.store.state()["messages"]
            if m["recipient_id"] == self.b["id"]
        )
        self.assertIn(
            "Builder completed implementation after review.", builder_delivery["result"]
        )
        planner_native = self.store.get_session(self.sa["id"])["native_session_id"]
        planner_prompts = [
            e["prompt"]
            for e in self.transcript()
            if e["method"] == "turn/start" and e["native_id"] == planner_native
        ]
        self.assertIn(
            "Builder completed implementation after review.", planner_prompts[-1]
        )
        self.assertNotIn("Builder delegated review.", planner_prompts[-1])

    def test_multiple_children_are_consumed_before_returning_one_final_result(self):
        for name in ("Reviewer one", "Reviewer two"):
            reviewer = self.store.add_agent(self.project["id"], name, "codex")
            self.store.add_session(reviewer["id"], name)
        runtime = self.start_runtime("fanout")
        root = runtime.start(
            self.sa["id"], "<fixture-delegate> Build with two reviewers."
        )
        self.wait_for(
            lambda: (
                len(self.store.runs_for_root(root["id"])) >= 7
                and not self.store.pending_runs()
            )
        )
        chain = self.store.runs_for_root(root["id"])
        self.assertEqual(len(chain), 7)
        builder_delivery = next(
            m
            for m in self.store.state()["messages"]
            if m["recipient_id"] == self.b["id"]
        )
        self.assertEqual(
            builder_delivery["result"],
            "Builder completed implementation after all reviews.",
        )
        planner_native = self.store.get_session(self.sa["id"])["native_session_id"]
        planner_prompts = [
            e["prompt"]
            for e in self.transcript()
            if e["method"] == "turn/start" and e["native_id"] == planner_native
        ]
        self.assertEqual(len(planner_prompts), 2)
        self.assertIn(
            "Builder completed implementation after all reviews.", planner_prompts[-1]
        )
        self.assertEqual(
            len([e for e in self.transcript() if e["method"] == "claude/prompt"]), 3
        )
        self.assertTrue(
            all(
                m["status"] == "completed" and m["reply_run_id"]
                for m in self.store.state()["messages"]
            )
        )

    def test_failed_continuation_cancels_queued_sibling_reply_and_returns_error(self):
        for name in ("Reviewer one", "Reviewer two"):
            reviewer = self.store.add_agent(self.project["id"], name, "codex")
            self.store.add_session(reviewer["id"], name)
        runtime = self.start_runtime("fanoutfail")
        root = runtime.start(self.sa["id"], "<fixture-delegate> Build with reviewers.")
        self.wait_for(
            lambda: (
                len(self.store.runs_for_root(root["id"])) >= 7
                and not self.store.pending_runs()
            )
        )
        builder_delivery = next(
            m
            for m in self.store.state()["messages"]
            if m["recipient_id"] == self.b["id"]
        )
        self.assertEqual(builder_delivery["status"], "failed")
        self.assertIsNone(builder_delivery["result"])
        builder_turns = [
            r
            for r in self.store.runs_for_root(root["id"])
            if r["agent_id"] == self.b["id"]
        ]
        self.assertEqual(
            [r["status"] for r in builder_turns], ["completed", "failed", "cancelled"]
        )
        self.assertEqual(
            self.store.get_run(builder_delivery["reply_run_id"])["status"], "completed"
        )
        planner_native = self.store.get_session(self.sa["id"])["native_session_id"]
        prompts = [
            e["prompt"]
            for e in self.transcript()
            if e["method"] == "turn/start" and e["native_id"] == planner_native
        ]
        self.assertIn("Status: failed", prompts[-1])

    def test_cancelling_waiting_builder_stops_child_and_returns_cancellation_to_planner(
        self,
    ):
        reviewer = self.store.add_agent(self.project["id"], "Reviewer", "codex")
        self.store.add_session(reviewer["id"], "Review session")
        runtime = self.start_runtime("nestedcancel")
        root = runtime.start(self.sa["id"], "<fixture-delegate> Build then review.")
        self.wait_for(lambda: bool(self.store.state()["approvals"]))
        delivery = next(
            m
            for m in self.store.state()["messages"]
            if m["recipient_id"] == self.b["id"]
        )
        self.assertEqual(delivery["status"], "waiting")
        runtime.cancel_run(delivery["run_id"])
        self.wait_for(
            lambda: (
                not self.store.pending_runs()
                and bool(self.store.get_message(delivery["id"])["reply_run_id"])
            )
        )
        settled = self.store.get_message(delivery["id"])
        self.assertEqual(settled["status"], "cancelled")
        self.assertEqual(
            self.store.get_run(settled["reply_run_id"])["status"], "completed"
        )
        child = next(
            m
            for m in self.store.state()["messages"]
            if m["recipient_id"] == reviewer["id"]
        )
        self.assertEqual(child["status"], "cancelled")
        self.assertIsNone(child["reply_run_id"])
        self.assertEqual(
            len([e for e in self.transcript() if e["method"] == "claude/prompt"]), 1
        )
        planner_native = self.store.get_session(self.sa["id"])["native_session_id"]
        planner_prompts = [
            e["prompt"]
            for e in self.transcript()
            if e["method"] == "turn/start" and e["native_id"] == planner_native
        ]
        self.assertIn("Status: cancelled", planner_prompts[-1])
        self.assertEqual(self.store.state()["approvals"], [])
        self.assertEqual(len(self.store.runs_for_root(root["id"])), 4)

    def test_session_cancel_stops_waiting_task_and_does_not_resume_it(self):
        reviewer = self.store.add_agent(self.project["id"], "Reviewer", "codex")
        self.store.add_session(reviewer["id"], "Review session")
        runtime = self.start_runtime("nestedcancel")
        root = runtime.start(self.sa["id"], "<fixture-delegate> Build then review.")
        self.wait_for(lambda: bool(self.store.state()["approvals"]))
        self.assertEqual(self.store.pending_runs(self.sa["id"]), [])
        self.assertEqual(
            [t["id"] for t in self.store.cancellable_tasks(self.sa["id"])], [root["id"]]
        )
        runtime.cancel(self.sa["id"])
        self.wait_for(lambda: not self.store.pending_runs())
        self.assertEqual(self.store.get_run(root["id"])["status"], "cancelled")
        self.assertTrue(
            all(
                m["status"] == "cancelled" and not m["reply_run_id"]
                for m in self.store.state()["messages"]
            )
        )
        self.assertEqual(len(self.store.runs_for_root(root["id"])), 3)
        self.assertEqual(self.store.cancellable_tasks(self.sa["id"]), [])
        self.assertEqual(self.store.state()["approvals"], [])

    def test_native_control_characters_do_not_strand_workspace(self):
        runtime = self.start_runtime("nul")
        run = runtime.start(
            self.sa["id"], "Return a valid JSON string with a NUL character."
        )
        self.wait_for(
            lambda: self.store.get_run(run["id"])["status"] not in ("queued", "running")
        )
        self.assertEqual(self.store.get_run(run["id"])["status"], "completed")
        self.assertEqual(self.store.get_run(run["id"])["result"], "beforeafter")
        second = runtime.start(self.sa["id"], "Continue after malformed text.")
        self.wait_for(lambda: self.store.get_run(second["id"])["status"] == "completed")
        self.assertEqual(self.store.pending_runs(), [])

    def test_native_permission_denial_round_trip_and_cancel_race(self):
        runtime = self.start_runtime("permission")
        run = runtime.start(self.sa["id"], "Request a fixture permission.")
        self.wait_for(lambda: bool(self.store.state()["approvals"]))
        approval = self.store.state()["approvals"][0]
        runtime.approve(approval["id"], "decline")
        self.wait_for(lambda: self.store.get_run(run["id"])["status"] == "completed")
        self.assertTrue(any(e.get("decision") == "decline" for e in self.transcript()))
        self.assertEqual(
            self.store.get_approval(approval["id"])["picked_option_id"], "decline"
        )
        queued = runtime.start(self.sa["id"], "Second fixture permission.")
        self.wait_for(lambda: bool(self.store.state()["approvals"]))
        pending = self.store.state()["approvals"][0]
        runtime.cancel_run(queued["id"])
        with self.assertRaises(RuntimeFailure):
            runtime.approve(pending["id"], "accept")
        self.wait_for(lambda: self.store.get_run(queued["id"])["status"] == "cancelled")
        self.assertEqual(self.store.get_approval(pending["id"])["status"], "cancelled")
        self.assertEqual(self.store.pending_runs(), [])


if __name__ == "__main__":
    unittest.main()
