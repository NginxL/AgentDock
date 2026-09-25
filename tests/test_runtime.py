import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agentdock.runtime import Runtime, RuntimeFailure
from agentdock.store import Forbidden, Store


class RuntimeStore:
    def __init__(self, path):
        self.path = path
        self.runs = {}
        self.events = []
        self.approvals = {}
        self.capabilities = set()
        self.provider = "codex"
        self.lock = threading.RLock()

    def get_session(self, session_id):
        return {"id": session_id, "agent_id": "agent", "project_id": "project"}

    def get_agent(self, agent_id):
        return {"id": agent_id, "provider": self.provider}

    def get_project(self, project_id):
        return {"id": project_id, "path": self.path}

    def begin_run(self, session_id, prompt):
        with self.lock:
            if any(r["status"] == "running" for r in self.runs.values()):
                raise RuntimeFailure("Agent is already active")
            value = {"id": str(len(self.runs) + 1), "session_id": session_id,
                     "agent_id": "agent", "project_id": "project", "status": "running"}
            self.runs[value["id"]] = value
            return dict(value)

    def context_for_run(self, run_id):
        return "Approved shared fact and mailbox context"

    def issue_capability(self, run_id):
        self.capabilities.add(run_id)
        return "test-capability-never-persist"

    def revoke_capabilities(self, run_id):
        self.capabilities.discard(run_id)

    def append_event(self, project_id, session_id, kind, payload):
        self.events.append({"kind": kind, "payload": payload})

    def finish_run(self, run_id, status, error=None):
        for approval in self.approvals.values():
            if approval["status"] == "pending":
                approval["status"] = "cancelled"
        self.runs[run_id].update(status=status, error=error)

    def create_approval(self, run_id, request, options):
        value = {"id": "approval-1", "run_id": run_id, "status": "pending", "options": options}
        self.approvals[value["id"]] = value
        return value

    def resolve_approval(self, approval_id, option_id):
        approval = self.approvals[approval_id]
        if approval["status"] != "pending":
            raise RuntimeFailure("Approval is not pending")
        approval.update(status="resolved", option_id=option_id)
        return approval


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = RuntimeStore(self.directory.name)
        self.runtimes = []

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.close()
        self.directory.cleanup()

    def make_runtime(self, scenario="normal", **overrides):
        command = [sys.executable, str(Path(__file__).with_name("fake_acp.py")), scenario]
        config = {"execution_enabled": True, "commands": {"codex": command, "claude": command},
                  "base_url": "http://127.0.0.1:47831", "python": sys.executable,
                  "package_root": self.directory.name, "run_timeout": 4, "approval_timeout": 2}
        config.update(overrides)
        runtime = Runtime(self.store, config)
        self.runtimes.append(runtime)
        return runtime

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.01)
        self.fail("Fixture did not finish before its test deadline")

    def finished(self, run):
        self.wait_for(lambda: self.store.runs[run["id"]]["status"] != "running")
        self.assertFalse(self.store.capabilities)
        return self.store.runs[run["id"]]

    def test_default_disabled_never_spawns(self):
        runtime = self.make_runtime(execution_enabled=False)
        with patch("agentdock.runtime.subprocess.Popen") as spawn:
            with self.assertRaises(Forbidden):
                runtime.start("session", "task")
            spawn.assert_not_called()
        self.assertFalse(self.store.runs)

    def test_claude_requires_api_key_before_starting(self):
        self.store.provider = "claude"
        runtime = self.make_runtime()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeFailure, "ANTHROPIC_API_KEY"):
                runtime.start("session", "task")
        self.assertFalse(self.store.runs)

    def test_protocol_context_events_and_revocation(self):
        runtime = self.make_runtime()
        result = self.finished(runtime.start("session", "Review only"))
        self.assertEqual(result["status"], "completed")
        events = str(self.store.events)
        self.assertIn("Approved shared fact", events)
        self.assertIn("Review only", events)
        self.assertNotIn("test-capability-never-persist", events)

    def test_permissions_wait_for_explicit_valid_choice(self):
        runtime = self.make_runtime("permission")
        run = runtime.start("session", "task")
        self.wait_for(lambda: bool(self.store.approvals))
        self.assertEqual(self.store.runs[run["id"]]["status"], "running")
        with self.assertRaises(ValueError):
            runtime.approve("approval-1", "made-up-option")
        runtime.approve("approval-1", "deny")
        with self.assertRaises(RuntimeFailure):
            runtime.approve("approval-1", "allow")
        self.assertEqual(self.finished(run)["status"], "completed")
        self.assertIn('deny', str(self.store.events))

    def test_permission_timeout_fails_closed(self):
        runtime = self.make_runtime("permission", approval_timeout=0.1)
        result = self.finished(runtime.start("session", "task"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("expired", result["error"])
        self.assertEqual(self.store.approvals["approval-1"]["status"], "cancelled")
        with self.assertRaises(RuntimeFailure):
            runtime.approve("approval-1", "allow")

    def test_cancel_stops_process_and_revokes_capability(self):
        runtime = self.make_runtime("hang")
        run = runtime.start("session", "task")
        self.wait_for(lambda: bool(runtime._runs["session"].process))
        process = runtime._runs["session"].process
        runtime.cancel("session")
        self.assertEqual(self.finished(run)["status"], "cancelled")
        self.assertIsNotNone(process.poll())

    def test_one_active_run_per_agent(self):
        runtime = self.make_runtime("hang")
        run = runtime.start("session", "task")
        with self.assertRaises(RuntimeFailure):
            runtime.start("another-session", "task")
        runtime.cancel("session")
        self.finished(run)

    def test_timeout_stops_process(self):
        runtime = self.make_runtime("hang", run_timeout=0.15)
        result = self.finished(runtime.start("session", "task"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])

    def test_protocol_failures_are_bounded_and_private(self):
        for scenario in ("crash", "invalid", "flood", "version", "wrong-session"):
            with self.subTest(scenario=scenario):
                runtime = self.make_runtime(scenario)
                result = self.finished(runtime.start("session", "task"))
                self.assertEqual(result["status"], "failed")
                self.assertNotIn("private-debug-secret", str(result))
                runtime.close()

    def test_closed_runtime_rejects_work(self):
        runtime = self.make_runtime()
        runtime.close()
        with self.assertRaises(RuntimeFailure):
            runtime.start("session", "task")

    def test_cancel_also_stops_descendants(self):
        runtime = self.make_runtime("child")
        run = runtime.start("session", "task")
        self.wait_for(lambda: any("child-pid:" in str(event) for event in self.store.events))
        text = next(event["payload"]["content"]["text"] for event in self.store.events
                    if event["kind"] == "agent_message_chunk")
        child_pid = int(text.split(":")[1])
        runtime.cancel("session")
        self.assertEqual(self.finished(run)["status"], "cancelled")

        def gone():
            try:
                os.getpgid(child_pid)
                return False
            except ProcessLookupError:
                return True
        self.wait_for(gone)

    def test_real_store_retains_transcript_and_revokes_tool_access(self):
        store = Store(":memory:")
        self.store = store
        try:
            project = store.add_project("Fixture", self.directory.name)
            agent = store.add_agent(project["id"], "Fixture", "codex")
            session = store.add_session(agent["id"], "Fixture")
            runtime = self.make_runtime()
            run = runtime.start(session["id"], "Remember the reviewed result")
            self.wait_for(lambda: store.get_session(session["id"])["status"] != "running")
            self.assertEqual(store.get_session(session["id"])["status"], "completed")
            self.assertIn("agent_message_chunk", store.context_for_run(run["id"]))
            row = store.db.execute("SELECT COUNT(*) FROM capabilities WHERE revoked=0").fetchone()
            self.assertEqual(row[0], 0)
            runtime.close()
        finally:
            for runtime in self.runtimes:
                runtime.close()
            self.runtimes.clear()
            store.close()


if __name__ == "__main__":
    unittest.main()
