"""Dispatcher integration tests with a deterministic, non-network native executor."""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agentdock.providers import ProviderCancelled
from agentdock.runtime import Runtime, RuntimeFailure
from agentdock.store import Forbidden, Invalid, Store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.project = self.store.add_project("Fixture", self.tmp.name)
        self.a = self.store.add_agent(self.project["id"], "Planner", "codex")
        self.b = self.store.add_agent(self.project["id"], "Builder", "claude")
        self.sa = self.store.add_session(self.a["id"], "Original conversation")
        self.sb = self.store.add_session(self.b["id"], "Implementation")
        self.calls = []
        self.runtimes = []
        self.gate = threading.Event()

    def tearDown(self):
        self.gate.set()
        for runtime in self.runtimes:
            runtime.close()
        self.store.close()
        self.tmp.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Local fixture did not reach its expected state")

    def executor(
        self,
        provider,
        command,
        cwd,
        prompt,
        native_id,
        mcp,
        stop,
        emit,
        bind,
        approve,
        timeout=900,
        permission_mode="ask",
        session_home=None,
    ):
        token = mcp["env"]["AGENTDOCK_CAPABILITY"]
        run = self.store.capability_run(token)
        self.calls.append(
            dict(
                provider=provider,
                native_id=native_id,
                prompt=prompt,
                run=run,
                token=token,
                permission_mode=permission_mode,
            )
        )
        bind(native_id or "native-" + run["session_id"])
        if "<block>" in run["prompt"]:
            while not self.gate.wait(0.01):
                if stop.is_set():
                    raise ProviderCancelled()
        if "<permission>" in run["prompt"]:
            picked = approve(
                {"command": "fixture command"},
                [
                    {"optionId": "allow", "name": "Allow once", "kind": "allow_once"},
                    {"optionId": "deny", "name": "Reject", "kind": "reject_once"},
                ],
            )
            emit("tool_result", {"decision": picked})
        if "<delegate>" in run["prompt"]:
            self.runtime.respond_tool(
                token,
                "message_send",
                {
                    "recipient_id": self.b["id"],
                    "recipient_session_id": self.sb["id"],
                    "body": "Implement the reviewed plan",
                    "idempotency_key": "one-handoff",
                },
            )
        if "<failure>" in run["prompt"]:
            raise RuntimeFailure("Fixture failed")
        result = (
            "Implemented and verified" if provider == "claude" else "Reviewed result"
        )
        emit("agent_message_chunk", {"content": {"type": "text", "text": result}})
        return result

    def make_runtime(self, executor=None, **config):
        options = {
            "execution_enabled": True,
            "commands": {"codex": ["test-codex"], "claude": ["test-claude"]},
            "python": sys.executable,
            "package_root": self.tmp.name,
            "base_url": "http://127.0.0.1:47831",
            "approval_timeout": 1,
            "run_timeout": 2,
        }
        options.update(config)
        runtime = Runtime(self.store, options, executor=executor or self.executor)
        self.runtime = runtime
        self.runtimes.append(runtime)
        return runtime

    def finished(self, run):
        self.wait_for(
            lambda: self.store.get_run(run["id"])["status"] not in ("queued", "running")
        )
        return self.store.get_run(run["id"])

    def test_same_device_acp_login_queues_without_blocking_other_providers(self):
        self.store.set_feature("acp_agents", True, acknowledged=True)
        sessions = []
        for name, provider in (
            ("First", "trae"),
            ("Second", "trae"),
            ("Other", "gemini"),
        ):
            agent = self.store.add_agent(None, name, provider)
            sessions.append(self.store.add_session(agent["id"], name))
        first, second, independent = sessions
        runtime = self.make_runtime(
            commands={"trae": ["test-trae"], "gemini": ["test-gemini"]}
        )
        running = runtime.start(first["id"], "<block>")
        self.wait_for(lambda: len(self.calls) == 1)
        queued = runtime.start(second["id"], "Wait for the same native login")
        other = runtime.start(independent["id"], "Independent login")
        self.assertEqual(self.finished(other)["status"], "completed")
        self.assertEqual(self.store.get_run(queued["id"])["status"], "queued")
        self.assertFalse(any(c["run"]["id"] == queued["id"] for c in self.calls))
        self.gate.set()
        self.assertEqual(self.finished(running)["status"], "completed")
        self.assertEqual(self.finished(queued)["status"], "completed")

    def test_queued_acp_work_can_be_cancelled_without_acquiring_credentials(self):
        self.store.set_feature("acp_agents", True, acknowledged=True)
        first = self.store.add_agent(None, "Holding", "trae")
        second = self.store.add_agent(None, "Queued", "trae")
        a = self.store.add_session(first["id"], "Holding")
        b = self.store.add_session(second["id"], "Queued")
        runtime = self.make_runtime(commands={"trae": ["test-trae"]})
        running = runtime.start(a["id"], "<block>")
        self.wait_for(lambda: len(self.calls) == 1)
        queued = runtime.start(b["id"], "Cancel while waiting")
        runtime.cancel_run(queued["id"])
        self.assertEqual(self.store.get_run(queued["id"])["status"], "cancelled")
        self.assertEqual(len(self.calls), 1)
        self.gate.set()
        self.assertEqual(self.finished(running)["status"], "completed")

    def test_progress_is_persisted_while_running_and_result_only_completes_after_exit(
        self,
    ):
        entered = threading.Event()

        def stream(
            provider,
            command,
            cwd,
            prompt,
            native_id,
            mcp,
            stop,
            emit,
            bind,
            approve,
            timeout=900,
            permission_mode="ask",
            session_home=None,
        ):
            bind("progress-session")
            emit(
                "reasoning_chunk",
                {"item_id": "thought", "part": 0, "text": "Checking the workspace"},
            )
            emit(
                "tool_call",
                {"item": {"type": "commandExecution", "id": "cmd", "command": "pwd"}},
            )
            emit("tool_output", {"item_id": "cmd", "text": "/workspace"})
            entered.set()
            self.gate.wait(2)
            emit(
                "tool_result",
                {
                    "item": {
                        "id": "cmd",
                        "status": "completed",
                        "aggregatedOutput": "/workspace",
                    }
                },
            )
            return "Verified workspace"

        runtime = self.make_runtime(executor=stream)
        run = runtime.start(self.sa["id"], "Check workspace")
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.store.get_run(run["id"])["status"], "running")
        events = self.store.session_events(self.sa["id"])
        progress = [
            e
            for e in events
            if e["kind"] in ("reasoning_chunk", "tool_call", "tool_output")
        ]
        self.assertEqual(len(progress), 3)
        self.assertTrue(all(e["payload"]["run_id"] == run["id"] for e in progress))
        self.assertFalse(any(e["kind"] == "run_finished" for e in events))
        self.gate.set()
        self.wait_for(lambda: self.store.get_run(run["id"])["status"] == "completed")
        self.assertEqual(self.store.get_run(run["id"])["result"], "Verified workspace")
        events = self.store.session_events(self.sa["id"])
        self.assertEqual(
            [e["kind"] for e in events][-2:], ["assistant_message", "run_finished"]
        )

    def test_review_mode_does_not_dispatch_or_persist_pending_tasks(self):
        runtime = self.make_runtime(execution_enabled=False)
        with self.assertRaises(Forbidden):
            runtime.start(self.sa["id"], "Task")
        with self.assertRaises(Forbidden):
            runtime.send_message(self.project["id"], self.b["id"], "Task")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.state()["runs"], [])
        self.assertIsNone(runtime._scheduler)

    def test_two_turns_resume_native_session_without_history_replay(self):
        runtime = self.make_runtime()
        first = self.finished(runtime.start(self.sa["id"], "First task unique marker"))
        second = self.finished(runtime.start(self.sa["id"], "Second task"))
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        self.assertIsNone(self.calls[0]["native_id"])
        self.assertEqual(self.calls[1]["native_id"], "native-" + self.sa["id"])
        self.assertNotIn("First task unique marker", self.calls[1]["prompt"])
        self.assertNotIn("inbox", self.calls[1]["prompt"])
        for call in self.calls:
            with self.assertRaises(Forbidden):
                self.store.capability_run(call["token"])

    def test_role_changes_reach_future_turns_without_rewriting_active_prompts(self):
        runtime = self.make_runtime()
        for agent, session in ((self.a, self.sa), (self.b, self.sb)):
            with self.subTest(provider=agent["provider"]):
                self.gate.clear()
                start = len(self.calls)
                self.store.update_agent(agent["id"], {"role": "ROLE_BEFORE_EDIT"})
                first = runtime.start(session["id"], "<block> Work on this task")
                self.wait_for(lambda: len(self.calls) == start + 1)
                self.store.update_agent(
                    agent["id"],
                    {"name": "User-defined helper", "role": "ROLE_AFTER_EDIT"},
                )
                second = runtime.start(session["id"], "Next task")
                self.assertEqual(self.store.get_run(second["id"])["status"], "queued")
                self.assertIn("ROLE_BEFORE_EDIT", self.calls[start]["prompt"])
                self.assertNotIn("ROLE_AFTER_EDIT", self.calls[start]["prompt"])
                self.gate.set()
                self.assertEqual(self.finished(first)["status"], "completed")
                self.assertEqual(self.finished(second)["status"], "completed")
                self.assertIn("ROLE_AFTER_EDIT", self.calls[start + 1]["prompt"])
                self.assertNotIn("ROLE_BEFORE_EDIT", self.calls[start + 1]["prompt"])
                self.assertEqual(
                    self.calls[start + 1]["native_id"], "native-" + session["id"]
                )
                self.assertEqual(self.calls[start + 1]["provider"], agent["provider"])
                self.store.update_agent(agent["id"], {"role": ""})
                self.assertEqual(
                    self.finished(
                        runtime.start(session["id"], "Task without a preset role")
                    )["status"],
                    "completed",
                )
                self.assertIn('"role": ""', self.calls[start + 2]["prompt"])
                self.assertNotIn("ROLE_AFTER_EDIT", self.calls[start + 2]["prompt"])

    def test_delegate_executes_and_result_resumes_exact_sender_session(self):
        runtime = self.make_runtime()
        first = runtime.start(self.sa["id"], "<delegate> Ask Builder to implement")
        self.wait_for(
            lambda: (
                len(self.calls) == 3
                and all(r["status"] == "completed" for r in self.store.state()["runs"])
            )
        )
        self.assertEqual(
            [c["provider"] for c in self.calls], ["codex", "claude", "codex"]
        )
        self.assertEqual(
            [c["run"]["origin"] for c in self.calls], ["human", "delegate", "reply"]
        )
        self.assertEqual(self.calls[2]["run"]["session_id"], self.sa["id"])
        self.assertEqual(
            self.calls[2]["native_id"],
            self.calls[0]["run"]["session_id"].join(["native-", ""]),
        )
        self.assertIn("Implemented and verified", self.calls[2]["prompt"])
        delivery = self.store.state()["messages"][0]
        self.assertEqual(delivery["status"], "completed")
        self.assertEqual(delivery["result"], "Implemented and verified")
        self.assertEqual(delivery["sender_run_id"], first["id"])
        self.assertTrue(delivery["reply_run_id"])

    def test_busy_workspace_queues_and_drains_automatically(self):
        runtime = self.make_runtime()
        first = runtime.start(self.sa["id"], "<block> Task")
        self.wait_for(lambda: len(self.calls) == 1)
        second = runtime.start(self.sb["id"], "Task B")
        self.assertEqual(self.store.get_run(second["id"])["status"], "queued")
        self.assertEqual(len(self.calls), 1)
        self.gate.set()
        self.assertEqual(self.finished(first)["status"], "completed")
        self.assertEqual(self.finished(second)["status"], "completed")
        self.assertEqual(len(self.calls), 2)

    def test_independent_workspaces_run_while_another_is_busy(self):
        runtime = self.make_runtime()
        first = runtime.start(self.sa["id"], "<block>")
        self.wait_for(lambda: len(self.calls) == 1)
        with tempfile.TemporaryDirectory() as other:
            project = self.store.add_project("Independent", other)
            agent = self.store.add_agent(project["id"], "Second", "codex")
            session = self.store.add_session(agent["id"], "Task")
            run = runtime.start(session["id"], "Independent work")
            self.assertEqual(self.finished(run)["status"], "completed")
            self.assertEqual(self.store.get_run(first["id"])["status"], "running")
        runtime.cancel_run(first["id"])
        self.assertEqual(self.finished(first)["status"], "cancelled")

    def test_cancel_queued_task_never_invokes_executor(self):
        runtime = self.make_runtime()
        first = runtime.start(self.sa["id"], "<block>")
        self.wait_for(lambda: len(self.calls) == 1)
        queued = runtime.start(self.sb["id"], "Must not execute")
        runtime.cancel_run(queued["id"])
        self.gate.set()
        self.finished(first)
        self.assertEqual(self.store.get_run(queued["id"])["status"], "cancelled")
        self.assertEqual(len(self.calls), 1)

    def test_human_dispatch_routes_and_deduplicates(self):
        runtime = self.make_runtime()
        one = runtime.send_message(
            self.project["id"],
            self.b["id"],
            "Build",
            idempotency_key="retry",
            recipient_session_id=self.sb["id"],
        )
        two = runtime.send_message(
            self.project["id"],
            self.b["id"],
            "Build",
            idempotency_key="retry",
            recipient_session_id=self.sb["id"],
        )
        self.assertEqual(one["run_id"], two["run_id"])
        self.assertEqual(self.finished({"id": one["run_id"]})["status"], "completed")
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(self.store.get_message(one["id"])["reply_run_id"])

    def test_permission_decision_is_explicit_and_single_use(self):
        runtime = self.make_runtime()
        run = runtime.start(self.sa["id"], "<permission>")
        self.wait_for(lambda: bool(self.store.state()["approvals"]))
        approval = self.store.state()["approvals"][0]
        with self.assertRaises(Invalid):
            runtime.approve(approval["id"], "anything")
        runtime.approve(approval["id"], "deny")
        with self.assertRaises(RuntimeFailure):
            runtime.approve(approval["id"], "allow")
        self.assertEqual(self.finished(run)["status"], "completed")
        self.assertEqual(
            self.store.get_approval(approval["id"])["picked_option_id"], "deny"
        )

    def test_permission_timeout_and_cancel_fail_closed(self):
        runtime = self.make_runtime(approval_timeout=0.08)
        run = runtime.start(self.sa["id"], "<permission>")
        result = self.finished(run)
        self.assertEqual(result["status"], "failed")
        self.assertIn("expired", result["error"])
        self.assertEqual(self.store.state()["approvals"], [])
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM capabilities WHERE revoked=0"
            ).fetchone()[0],
            0,
        )

    def test_failure_result_returns_to_sender(self):
        def executor(*args, **kwargs):
            if args[0] == "claude":
                raise RuntimeFailure("Fixture provider unavailable")
            return self.executor(*args, **kwargs)

        runtime = self.make_runtime(executor)
        runtime.start(self.sa["id"], "<delegate>")
        self.wait_for(lambda: any(c["run"]["origin"] == "reply" for c in self.calls))
        reply = next(c for c in self.calls if c["run"]["origin"] == "reply")
        self.assertIn("Fixture provider unavailable", reply["prompt"])
        self.assertEqual(self.store.state()["messages"][0]["status"], "failed")

    def test_permission_changes_apply_to_the_next_turn_of_each_agent(self):
        runtime = self.make_runtime()
        for agent, session in ((self.a, self.sa), (self.b, self.sb)):
            self.store.update_agent(agent["id"], {"permission_mode": "full_access"})
            self.assertEqual(
                self.finished(runtime.start(session["id"], "First"))["status"],
                "completed",
            )
            self.assertEqual(self.calls[-1]["permission_mode"], "full_access")
            native_id = self.store.get_session(session["id"])["native_session_id"]
            self.store.update_agent(agent["id"], {"permission_mode": "ask"})
            self.assertEqual(
                self.finished(runtime.start(session["id"], "Second"))["status"],
                "completed",
            )
            self.assertEqual(self.calls[-1]["permission_mode"], "ask")
            self.assertEqual(self.calls[-1]["native_id"], native_id)

    def test_capability_redacted_from_stream_and_final_result(self):
        def executor(
            provider,
            command,
            cwd,
            prompt,
            native_id,
            mcp,
            stop,
            emit,
            bind,
            approve,
            timeout,
            permission_mode,
            session_home=None,
        ):
            token = mcp["env"]["AGENTDOCK_CAPABILITY"]
            self.token = token
            bind("fake-session")
            emit("tool_result", {"text": token})
            return token

        runtime = self.make_runtime(executor)
        self.finished(runtime.start(self.sa["id"], "Task"))
        self.assertNotIn(self.token, json.dumps(self.store.state()))
        self.assertIn("[redacted]", json.dumps(self.store.state()))

    def test_stop_parent_cancels_waiting_delegation(self):
        def executor(
            provider,
            command,
            cwd,
            prompt,
            native_id,
            mcp,
            stop,
            emit,
            bind,
            approve,
            timeout,
            permission_mode,
            session_home=None,
        ):
            token = mcp["env"]["AGENTDOCK_CAPABILITY"]
            self.runtime.respond_tool(
                token, "message_send", {"recipient_id": self.b["id"], "body": "Child"}
            )
            self.gate.set()
            while not stop.wait(0.01):
                pass
            raise ProviderCancelled()

        runtime = self.make_runtime(executor)
        run = runtime.start(self.sa["id"], "Delegate then wait")
        self.wait_for(self.gate.is_set)
        runtime.cancel_run(run["id"])
        self.assertEqual(self.finished(run)["status"], "cancelled")
        self.assertTrue(
            all(r["status"] == "cancelled" for r in self.store.state()["runs"])
        )
        self.assertIsNone(self.store.state()["messages"][0]["reply_run_id"])

    def test_close_stops_active_and_queued_work(self):
        runtime = self.make_runtime()
        first = runtime.start(self.sa["id"], "<block>")
        self.wait_for(lambda: bool(self.calls))
        second = runtime.start(self.sb["id"], "Queued")
        runtime.close()
        self.assertEqual(self.store.get_run(first["id"])["status"], "cancelled")
        self.assertEqual(self.store.get_run(second["id"])["status"], "cancelled")
        with self.assertRaises(RuntimeFailure):
            runtime.start(self.sa["id"], "No")
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
