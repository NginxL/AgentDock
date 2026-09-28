import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agentdock.providers import execute, ProviderCancelled, ProviderError


FAKE = str(Path(__file__).with_name("fake_native.py"))
CLAUDE_SESSION = "f11f67f0-04ba-49ac-aac5-cdc1a9c5a38d"


class NativeProvidersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)
        self.events, self.bound, self.approvals = [], [], []
        self.stop = threading.Event()

    def tearDown(self):
        self.tmp.cleanup()

    def run_provider(self, provider, scenario="success", native_id=None, approve=None, timeout=3, permission_mode='ask'):
        def permission(request, options):
            self.approvals.append((request, options))
            return options[0]["optionId"]
        return execute(provider, [sys.executable, FAKE, provider, scenario], str(self.cwd),
            "A bounded test prompt", native_id,
            {"command": sys.executable, "args": ["-m", "agentdock.mcp"],
             "env": {"AGENTDOCK_CAPABILITY": "private-token", "AGENTDOCK_URL": "http://127.0.0.1:1"}},
            self.stop, lambda kind, payload: self.events.append((kind, payload)), self.bound.append,
            approve or permission, timeout=timeout, permission_mode=permission_mode)

    def test_full_access_is_explicit_and_can_be_revoked_on_native_resume(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                self.assertEqual(self.run_provider(provider, 'full_access', permission_mode='full_access'), 'hello world')
                native_id = self.bound[-1]
                self.assertEqual(self.run_provider(provider, 'full_access', native_id, permission_mode='full_access'), 'hello world')
                self.assertEqual(self.bound[-1], native_id)
                self.assertEqual(self.run_provider(provider, 'permission', native_id, permission_mode='ask'), 'hello world')
                self.assertEqual(self.bound[-1], native_id)
                self.assertTrue(self.approvals)
                self.approvals.clear()

    def test_invalid_permissions_never_start_a_native_process(self):
        for provider in ('codex', 'claude'):
            for value in (None, '', 'full', 'FULL_ACCESS', True, {}):
                with self.subTest(provider=provider, value=value):
                    with patch('agentdock.providers._Pipe') as pipe:
                        with self.assertRaisesRegex(ProviderError, 'Invalid agent permission mode'):
                            self.run_provider(provider, permission_mode=value)
                        pipe.assert_not_called()

    def test_live_progress_precedes_final_reply_and_excludes_private_fields(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                self.events = []
                self.assertEqual(self.run_provider(provider, 'progress'), 'hello world')
                kinds = [k for k, p in self.events]
                self.assertIn('reasoning_chunk', kinds)
                self.assertIn('tool_call', kinds)
                self.assertIn('tool_result', kinds)
                self.assertLess(kinds.index('reasoning_chunk'), kinds.index('agent_message_chunk'))
                if provider == 'codex': self.assertIn('tool_output', kinds)
                self.assertNotIn('private-token', json.dumps(self.events))
                self.assertNotIn('do not forward', json.dumps(self.events))
                if provider == 'claude': self.assertNotIn('reasoning_message', kinds)

    def test_model_effort_and_real_usage_event_are_forwarded(self):
        execute("codex", [sys.executable, FAKE, "codex", "usage"], str(self.cwd), "hello", None,
            {"command": sys.executable, "args": [], "env": {"AGENTDOCK_CAPABILITY":"private-token"}},
            self.stop, lambda k,p:self.events.append((k,p)), self.bound.append, lambda *a:None,
            model="fixture-model", effort="high")
        usage = next(p for k,p in self.events if k == "token_usage")
        self.assertEqual(usage["usage"]["total_tokens"], 15)
        self.assertEqual(usage["output_delta"], 5)
        self.assertEqual(usage["native_id"], self.bound[0])
        self.assertNotIn("private-token", json.dumps(usage))

    def contract(self):
        return [json.loads(line) for line in (self.cwd / "fake-contract.jsonl").read_text().splitlines()]

    def assert_process_stopped(self):
        pid = int((self.cwd / "fake-pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_codex_start_and_resume_preserve_native_thread(self):
        self.assertEqual(self.run_provider("codex"), "hello world")
        self.assertEqual(self.bound, ["native-codex-1"])
        self.assertEqual([m["method"] for m in self.contract()[:4]], ["initialize", "initialized", "thread/start", "turn/start"])
        self.assertNotIn("excludeTurns", self.contract()[2]["params"])
        self.assertEqual("".join(e[1]["content"]["text"] for e in self.events), "hello world")
        self.assert_process_stopped()
        (self.cwd / "fake-contract.jsonl").unlink()
        self.run_provider("codex", native_id=self.bound[0])
        self.assertEqual(self.contract()[2]["method"], "thread/resume")
        self.assertEqual(self.contract()[2]["params"]["threadId"], "native-codex-1")
        self.assertIs(self.contract()[2]["params"]["excludeTurns"], True)
        self.assertEqual(self.bound, ["native-codex-1", "native-codex-1"])

    def test_claude_start_and_resume_native_cli_auth_and_stream(self):
        self.assertEqual(self.run_provider("claude"), "hello world")
        self.assertEqual(len(self.bound), 1)
        first_id = self.bound[0]
        self.assertEqual("".join(e[1]["content"]["text"] for e in self.events), "hello world")
        self.assert_process_stopped()
        self.run_provider("claude", native_id=first_id)
        self.assertEqual(self.bound, [first_id, first_id])
        argv = json.loads((self.cwd / "fake-argv.json").read_text())
        self.assertIn("--resume=" + first_id, argv)
        self.assertNotIn("--session-id", argv)

    def test_approval_and_denial_protocol_contracts(self):
        for provider in ("codex", "claude"):
            for allow in (True, False):
                with self.subTest(provider=provider, allow=allow):
                    def approve(request, options):
                        self.assertEqual(request["provider"], provider)
                        return options[0 if allow else 1]["optionId"]
                    self.run_provider(provider, "permission", approve=approve)
                    response = self.contract()[-1]
                    if provider == "codex":
                        self.assertEqual(response["result"]["decision"], "accept" if allow else "decline")
                    else:
                        data = response["response"]["response"]
                        self.assertEqual(data["behavior"], "allow" if allow else "deny")
                        if allow:
                            self.assertEqual(data["updatedInput"], {"file_path": "/tmp/reviewed-file", "content": "approved input"})
                        else:
                            self.assertNotIn("updatedInput", data)

    def test_claude_foreground_policy_is_scoped_to_child_environment(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "0"}):
            self.assertEqual(self.run_provider("claude"), "hello world")
            self.assertEqual(os.environ["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"], "0")

    def test_codex_permission_grants_are_turn_scoped(self):
        self.run_provider("codex", "permissions")
        self.assertEqual(self.contract()[-1]["result"], {"permissions": {"network": {"enabled": True}}, "scope": "turn"})

    def test_errors_never_expose_private_output(self):
        for provider in ("codex", "claude"):
            for scenario in ("protocol_error", "invalid_json", "early_exit", "partial", "failed", "wrong_session", "duplicate_permission"):
                with self.subTest(provider=provider, scenario=scenario):
                    with self.assertRaises(ProviderError) as error:
                        self.run_provider(provider, scenario)
                    self.assertNotIn("private-token", str(error.exception))
                    self.assert_process_stopped()

    def test_codex_refuses_a_different_resumed_thread_or_turn(self):
        with self.assertRaisesRegex(ProviderError, "different native session"):
            self.run_provider("codex", "resume_mismatch", "owned-thread")
        with self.assertRaisesRegex(ProviderError, "different turn"):
            self.run_provider("codex", "wrong_turn")

    def test_secrets_stay_out_of_argv_events_results_and_handshake(self):
        for provider in ("codex", "claude"):
            with self.subTest(provider=provider):
                self.assertEqual(self.run_provider(provider, "redact"), "hello [redacted]")
                self.assertNotIn("private-token", (self.cwd / "fake-argv.json").read_text())
                self.assertNotIn("private-token", (self.cwd / "fake-contract.jsonl").read_text())
                self.assertNotIn("private-token", json.dumps(self.events))

    def test_output_limits_stop_process(self):
        for scenario in ("huge_line", "huge_stderr"):
            with self.subTest(scenario=scenario):
                with self.assertRaisesRegex(ProviderError, "limit"):
                    self.run_provider("codex", scenario)
                self.assert_process_stopped()

    def test_deadline_interrupts_a_blocked_permission_callback(self):
        release = threading.Event()
        entered = threading.Event()
        def blocked(request, options):
            entered.set()
            release.wait(2)
            return options[0]["optionId"]
        before = time.monotonic()
        try:
            with self.assertRaisesRegex(ProviderError, "timed out"):
                self.run_provider("claude", "permission_slow", approve=blocked, timeout=0.35)
            self.assertTrue(entered.is_set())
            self.assertLess(time.monotonic() - before, 1.5)
            self.assert_process_stopped()
        finally:
            release.set()

    def test_cancel_stops_a_hung_native_process(self):
        timer = threading.Timer(0.2, self.stop.set)
        timer.start()
        try:
            with self.assertRaises(ProviderCancelled):
                self.run_provider("codex", "hang")
            self.assert_process_stopped()
        finally:
            timer.cancel()

    def test_deadline_stops_descendants(self):
        with self.assertRaisesRegex(ProviderError, "timed out"):
            self.run_provider("codex", "descendant", timeout=0.3)
        self.assert_process_stopped()
        child = int((self.cwd / "fake-child-pid").read_text())
        # A reparented zombie can briefly remain until PID 1 reaps it; no child
        # that can still execute may survive the process-group stop.
        import subprocess
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), state)

    def test_invalid_session_does_not_spawn_a_cli(self):
        for provider, identifier in (("codex", "--dangerous"), ("claude", "not-a-uuid")):
            with self.subTest(provider=provider):
                with self.assertRaises(ProviderError):
                    self.run_provider(provider, native_id=identifier)
                self.assertFalse((self.cwd / "fake-pid").exists())


class RuntimeNativeContractTest(unittest.TestCase):
    """Exercise the actual dispatcher and native transports together, offline."""
    def test_native_sessions_and_permission_decisions_are_persisted(self):
        from agentdock.runtime import Runtime
        from agentdock.store import Store
        with tempfile.TemporaryDirectory() as directory:
            store = Store(":memory:")
            project = store.add_project("Native fixtures", directory)
            sessions = {}
            for provider in ("codex", "claude"):
                agent = store.add_agent(project["id"], provider, provider)
                sessions[provider] = store.add_session(agent["id"], "Retained native session")
            runtime = Runtime(store, {"execution_enabled": True, "python": sys.executable,
                "package_root": str(Path(__file__).resolve().parents[1]), "base_url": "http://127.0.0.1:1",
                "run_timeout": 3, "approval_timeout": 2,
                "commands": {provider: [sys.executable, FAKE, provider, "permission"] for provider in sessions}})
            try:
                for provider, session in sessions.items():
                    for turn in range(2):
                        run = runtime.start(session["id"], "Fixture turn " + str(turn))
                        deadline = time.monotonic() + 4
                        while time.monotonic() < deadline:
                            for approval in store.state()["approvals"]:
                                if approval["status"] == "pending":
                                    runtime.approve(approval["id"], approval["options"][1]["optionId"])
                            current = store.get_run(run["id"])
                            if current["status"] not in ("queued", "running"):
                                break
                            time.sleep(0.01)
                        self.assertEqual(current["status"], "completed", current.get("error"))
                        self.assertEqual(current["result"], "hello world")
                        bound = store.get_session(session["id"])["native_session_id"]
                        self.assertTrue(bound)
                        if turn:
                            self.assertEqual(bound, previous)
                        previous = bound
                        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM capabilities WHERE revoked=0").fetchone()[0], 0)
            finally:
                runtime.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
