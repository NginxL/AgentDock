"""Real dispatcher with deterministic native adapters; no login, network or credentials."""

import sys
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from agentdock.providers import ProviderCancelled, ProviderError, account_error
from agentdock.runtime import Runtime
from agentdock.store import Invalid, Missing, Store


class AccountRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = Store(self.path)
        self.store.set_feature("automatic_failover", True, acknowledged=True)
        self.runtimes = []
        self.calls = []
        self.leases = []
        self.gates = []

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        for runtime in self.runtimes:
            runtime.close()
        self.store.close()
        self.temp.cleanup()

    def account(self, label="Account", provider="codex", environment="local"):
        return self.store.complete_account_login(
            self.store.add_account(provider, label, environment)["id"]
        )

    def test_disabled_or_replaced_account_is_not_revived_by_running_attempt(self):
        account = self.account()
        runtime = self.runtime()
        self.store.update_account(account["id"], {"enabled": False})
        runtime._account_failure(
            account["id"],
            ProviderError("Limited", code="rate_limited"),
            account["generation"],
        )
        runtime._account_limit(
            account["id"],
            {"status": "rejected", "resetsAt": time.time() + 30},
            account["generation"],
        )
        self.assertEqual(self.store.get_account(account["id"])["status"], "disabled")
        self.store.update_account(account["id"], {"enabled": True})
        refreshed = self.store.complete_account_login(account["id"])
        runtime._account_failure(
            account["id"],
            ProviderError("Expired", code="auth_expired"),
            account["generation"],
        )
        self.assertEqual(self.store.get_account(account["id"])["status"], "ready")
        self.assertGreater(refreshed["generation"], account["generation"])

    def test_managed_session_cleanup_never_touches_default_cli_history(self):
        for provider, target in [
            ("codex", "agentdock.codex_home.retire_legacy"),
            ("claude", "agentdock.session_storage.retire_legacy_claude"),
        ]:
            account = self.account(provider=provider)
            session = self.session(account, provider=provider)
            runtime = self.runtime()
            run = runtime.start(session["id"], "Fixture")
            self.wait(lambda: self.store.get_run(run["id"])["status"] == "completed")
            with patch(target) as retire:
                runtime.delete_session(session["id"])
                retire.assert_not_called()

    def test_claude_limit_without_reset_expires_after_bounded_cooldown_and_refresh(
        self,
    ):
        account = self.account(provider="claude")
        session = self.session(account, provider="claude")
        runtime = self.runtime()
        observed = datetime.now(timezone.utc)
        runtime._account_limit(
            account["id"],
            {"status": "rejected", "rateLimitType": "five_hour"},
            account["generation"],
        )
        runtime._account_failure(
            account["id"],
            ProviderError("Fixture", code="quota_exhausted", rejected=True),
            account["generation"],
        )
        limited = self.store.get_account(account["id"])
        reset = datetime.fromisoformat(limited["quota"]["windows"][0]["reset_at"])
        self.assertGreater(reset, observed)
        self.assertLess(reset, observed + timedelta(seconds=65))
        self.assertFalse(self.store._account_available(limited))
        runtime.accounts.manager.refresh = Mock(
            return_value={
                "logged_in": True,
                "windows": [],
                "error_code": "quota_unavailable",
            }
        )
        runtime.accounts.refresh(account["id"])
        with patch("agentdock.account_store.datetime", wraps=datetime) as clock:
            clock.now.return_value = observed + timedelta(seconds=70)
            self.assertTrue(
                self.store._account_available(self.store.get_account(account["id"]))
            )
            self.assertEqual(
                self.store.enqueue_run(session["id"], "Try after recovery")["status"],
                "queued",
            )

    def test_legacy_claude_limit_without_reset_can_recover_without_new_login(self):
        account = self.account(provider="claude")
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        self.store.set_account_quota(
            account["id"],
            {
                "status": "stale",
                "fetched_at": old,
                "windows": [{"name": "session", "remaining_percent": 0}],
            },
        )
        self.store.set_account_status(account["id"], "cooldown", cooldown_until=old)
        runtime = self.runtime()
        runtime.accounts.manager.refresh = Mock(
            return_value={
                "logged_in": True,
                "windows": [],
                "error_code": "quota_unavailable",
            }
        )
        runtime.accounts.refresh(account["id"])
        restored = self.store.get_account(account["id"])
        self.assertEqual(restored["generation"], account["generation"])
        self.assertTrue(self.store._account_available(restored))

    def test_legacy_unknown_limit_schedules_a_bounded_retry(self):
        account = self.account(provider="claude")
        observed = datetime.now(timezone.utc)
        self.store.set_account_quota(
            account["id"],
            {
                "fetched_at": observed.isoformat(),
                "windows": [{"name": "session", "remaining_percent": 0}],
            },
        )
        session = self.session(policy="auto", provider="claude")
        run = self.store.begin_run(session["id"], "Wait for recovery")
        retry = self.store.next_account_retry(run["id"])
        self.assertEqual(
            datetime.fromisoformat(retry), observed + timedelta(seconds=60)
        )

    def test_native_future_quota_reset_is_not_shortened_to_unknown_limit_cooldown(self):
        account = self.account(provider="claude")
        runtime = self.runtime()
        reset = time.time() + 3600
        runtime._account_limit(
            account["id"],
            {"status": "rejected", "resetsAt": reset},
            account["generation"],
        )
        limited = self.store.get_account(account["id"])
        self.assertAlmostEqual(
            datetime.fromisoformat(
                limited["quota"]["windows"][0]["reset_at"]
            ).timestamp(),
            reset,
            places=5,
        )
        with patch("agentdock.account_store.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime.now(timezone.utc) + timedelta(seconds=120)
            self.assertFalse(self.store._account_available(limited))

    def session(
        self,
        account=None,
        policy="manual",
        pool=None,
        provider="codex",
        environment="local",
    ):
        agent = self.store.add_agent(
            None,
            "Worker",
            provider,
            environment_id=environment,
            account_id=account["id"] if account else None,
            account_policy=policy,
            account_ids=pool,
        )
        return self.store.add_session(agent["id"], "Conversation")

    @contextmanager
    def credentials(self, account, session_home, **kwargs):
        self.leases.append((account["id"], account["generation"], session_home))
        yield {
            "AGENTDOCK_TEST_ACCOUNT": account["id"],
            "AGENTDOCK_TEST_GENERATION": str(account["generation"]),
        }

    def runtime(self, behavior=None):
        def execute(
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
            **options,
        ):
            call = dict(
                provider=provider,
                command=command,
                cwd=cwd,
                prompt=prompt,
                native_id=native_id,
                stop=stop,
                emit=emit,
                bind=bind,
                approve=approve,
                options=options,
                account_id=options.get("base_environment", {}).get(
                    "AGENTDOCK_TEST_ACCOUNT"
                ),
            )
            self.calls.append(call)
            if behavior:
                return behavior(call)
            bind(native_id or str(uuid.uuid4()))
            return "Completed safely"

        config = dict(
            execution_enabled=True,
            commands={"codex": ["fixture-codex"], "claude": ["fixture-claude"]},
            python=sys.executable,
            package_root=self.temp.name,
            base_url="http://127.0.0.1:1",
            run_timeout=5,
            approval_timeout=2,
        )
        with patch("agentdock.account_service.AccountService.watch"):
            runtime = Runtime(self.store, config, executor=execute)
        runtime.accounts.manager.credential_session = self.credentials
        self.runtimes.append(runtime)
        return runtime

    def wait(self, predicate, seconds=4):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Dispatcher did not reach the expected fixture state")

    def finished(self, run):
        self.wait(
            lambda: self.store.get_run(run["id"])["status"] not in ("queued", "running")
        )
        return self.store.get_run(run["id"])

    def cooldown(self, account, seconds=120):
        until = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        return self.store.set_account_status(
            account["id"], "cooldown", "rate_limited", until
        )

    def test_selected_account_environment_and_native_resume_remain_private(self):
        for provider in ("codex", "claude"):
            account = self.account(provider=provider)
            session = self.session(account, provider=provider)
            runtime = self.runtime()
            first = self.finished(runtime.start(session["id"], "First"))
            second = self.finished(runtime.start(session["id"], "Second"))
            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "completed")
            calls = self.calls[-2:]
            self.assertEqual(
                [call["account_id"] for call in calls], [account["id"]] * 2
            )
            self.assertTrue(all(call["options"]["managed_account"] for call in calls))
            self.assertIsNone(calls[0]["native_id"])
            self.assertEqual(
                calls[1]["native_id"],
                self.store.get_session(session["id"])["native_session_id"],
            )
            self.assertEqual(
                calls[0]["options"]["session_home"], calls[1]["options"]["session_home"]
            )
            self.assertNotIn(".codex", calls[0]["options"]["session_home"])
            self.assertEqual(
                [a["status"] for a in self.store.account_attempts(first["id"])],
                ["completed"],
            )

    def test_auto_skips_exhausted_accounts_before_first_turn(self):
        exhausted, healthy = self.account("Exhausted"), self.account("Healthy")
        self.cooldown(exhausted)
        runtime = self.runtime()
        session = self.session(policy="auto")
        result = self.finished(runtime.start(session["id"], "Pick an account"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call["account_id"] for call in self.calls], [healthy["id"]])

    def test_structured_prework_rejection_fails_over_but_plain_model_text_does_not(
        self,
    ):
        first, second = self.account("One"), self.account("Two")

        def behavior(call):
            if call["account_id"] == first["id"]:
                raise account_error(
                    {"error": {"code": "rate_limit_error", "retry_after": 10}}, "Failed"
                )
            call["bind"](str(uuid.uuid4()))
            return "The text quota_exceeded is ordinary answer content."

        runtime = self.runtime(behavior)
        session = self.session(first, "failover", [first["id"], second["id"]])
        result = self.finished(runtime.start(session["id"], "Run once"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            [call["account_id"] for call in self.calls], [first["id"], second["id"]]
        )
        attempts = self.store.account_attempts(result["id"])
        self.assertEqual(
            [attempt["status"] for attempt in attempts], ["rejected", "completed"]
        )
        self.assertEqual(self.store.get_account(first["id"])["status"], "cooldown")
        self.assertEqual(
            len(
                [
                    e
                    for e in self.store.session_events(session["id"])
                    if e["kind"] == "user_message"
                ]
            ),
            1,
        )
        self.assertEqual(
            self.store.get_session(session["id"])["account_id"], second["id"]
        )

    def test_unstructured_auth_looking_error_does_not_switch(self):
        first, second = self.account("One"), self.account("Two")

        def behavior(_):
            raise ProviderError("rate_limit_error unauthorized quota_exceeded")

        runtime = self.runtime(behavior)
        session = self.session(first, "failover")
        result = self.finished(runtime.start(session["id"], "No heuristic replay"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            self.store.account_attempts(result["id"])[0]["status"], "failed"
        )
        self.assertEqual(self.store.get_account(first["id"])["status"], "ready")

    def test_output_reasoning_and_tool_progress_each_prevent_automatic_replay(self):
        for kind, payload in [
            ("assistant_delta", {"text": "Started"}),
            ("reasoning_chunk", {"text": "Examining"}),
            ("tool_call", {"name": "write_file"}),
            ("tool_output", {"text": "written"}),
        ]:
            with self.subTest(kind=kind):
                first, second = self.account(kind + " one"), self.account(kind + " two")
                before = len(self.calls)

                def behavior(call):
                    call["emit"](kind, payload)
                    raise ProviderError(
                        "Quota exhausted", code="quota_exhausted", rejected=True
                    )

                runtime = self.runtime(behavior)
                session = self.session(first, "failover", [first["id"], second["id"]])
                result = self.finished(
                    runtime.start(session["id"], "Do not repeat side effects")
                )
                self.assertEqual(result["status"], "failed")
                self.assertEqual(len(self.calls) - before, 1)
                attempt = self.store.account_attempts(result["id"])[0]
                self.assertEqual(attempt["status"], "failed")
                self.assertTrue(attempt["progress"])

    def test_approval_request_prevents_replay_even_when_approved(self):
        first, second = self.account("One"), self.account("Two")

        def behavior(call):
            call["approve"](
                {"command": "fixture"},
                [{"optionId": "allow", "name": "Allow", "kind": "allow_once"}],
            )
            raise ProviderError(
                "Authentication expired", code="auth_expired", rejected=True
            )

        runtime = self.runtime(behavior)
        session = self.session(first, "failover")
        run = runtime.start(session["id"], "Permission")
        self.wait(lambda: bool(self.store.state()["approvals"]))
        runtime.approve(self.store.state()["approvals"][0]["id"], "allow")
        result = self.finished(run)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.store.account_attempts(run["id"])[0]["progress"])
        self.assertEqual(self.store.get_account(first["id"])["status"], "expired")

    def test_idle_manual_switch_starts_new_native_branch_with_final_reply_context(self):
        first, second = self.account("One"), self.account("Two")
        runtime = self.runtime()
        session = self.session(first)
        original = self.finished(runtime.start(session["id"], "Original question"))
        self.store.switch_session_account(session["id"], second["id"])
        continuation = self.finished(runtime.start(session["id"], "Continue here"))
        self.assertEqual(continuation["status"], "completed")
        self.assertEqual(self.calls[-1]["account_id"], second["id"])
        self.assertIsNone(self.calls[-1]["native_id"])
        self.assertIn("<conversation-handover>", self.calls[-1]["prompt"])
        self.assertIn("Original question", self.calls[-1]["prompt"])
        self.assertIn(original["result"], self.calls[-1]["prompt"])
        self.assertNotEqual(
            self.calls[0]["options"]["session_home"],
            self.calls[-1]["options"]["session_home"],
        )
        self.assertEqual(self.store.get_run(original["id"])["account_id"], first["id"])

    def test_maximum_three_distinct_accounts_and_no_silent_device_fallback(self):
        accounts = [self.account(str(index)) for index in range(4)]

        def behavior(_):
            raise ProviderError(
                "Rate limited", code="rate_limited", retry_after=120, rejected=True
            )

        runtime = self.runtime(behavior)
        session = self.session(accounts[0], "failover", [a["id"] for a in accounts])
        result = self.finished(runtime.start(session["id"], "Bounded attempts"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [call["account_id"] for call in self.calls], [a["id"] for a in accounts[:3]]
        )
        self.assertEqual(len(self.store.account_attempts(result["id"])), 3)
        self.assertEqual(self.store.get_account(accounts[3]["id"])["status"], "ready")

    def test_handover_reads_last_actions_of_failed_run_beyond_first_500_events(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first)
        old = self.store.begin_run(session["id"], "Earlier task")
        for index in range(510):
            self.store.append_event(
                None,
                session["id"],
                "tool_output",
                {"run_id": old["id"], "text": "Old action " + str(index)},
            )
        self.store.finish_run(old["id"], "completed", result="Earlier result")
        failed = self.store.begin_run(session["id"], "Failed task")
        for index in range(20):
            self.store.append_event(
                None,
                session["id"],
                "tool_output",
                {"run_id": failed["id"], "text": "Recent action " + str(index)},
            )
        self.store.finish_run(failed["id"], "failed")
        self.store.switch_session_account(session["id"], second["id"])
        continuation = self.store.enqueue_run(session["id"], "Continue")
        handover = self.runtime()._handover(
            self.store.get_session(session["id"]), continuation
        )
        self.assertIn("Recent action 19", handover)
        self.assertIn("Recent action 8", handover)
        self.assertNotIn("Recent action 7", handover)
        self.assertNotIn("Old action", handover)
        self.assertEqual(len(self.store.run_activity(failed["id"])), 12)

    def test_progress_cap_does_not_fail_the_turn_or_discard_final_reply(self):
        def noisy(call):
            for _ in range(5010):
                call["emit"]("tool_output", {"text": "fixture"})
            return "The final reply is intact."

        runtime = self.runtime(noisy)
        session = self.session()
        run = runtime.start(session["id"], "A long task")
        self.wait(
            lambda: self.store.get_run(run["id"])["status"] == "completed", seconds=10
        )
        self.assertEqual(
            self.store.get_run(run["id"])["result"], "The final reply is intact."
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='output_truncated'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='assistant_message'"
            ).fetchone()[0],
            1,
        )

    def test_agent_execution_timeout_is_inherited_by_the_session(self):
        runtime = self.runtime()
        session = self.session()
        self.store.update_agent(session["agent_id"], {"run_timeout": 3600})
        self.finished(runtime.start(session["id"], "Use the configured duration"))
        self.assertGreater(self.calls[-1]["options"]["timeout"], 3590)
        for invalid in (True, -1, 0, 90000, "3600"):
            with self.assertRaises(Invalid):
                self.store.update_agent(session["agent_id"], {"run_timeout": invalid})

    def test_all_cooling_wait_can_be_cancelled_without_native_execution(self):
        account = self.account()
        self.cooldown(account)
        runtime = self.runtime()
        session = self.session(policy="failover")
        run = runtime.start(session["id"], "Wait")
        self.wait(lambda: bool(self.store.get_run(run["id"])["next_attempt_at"]))
        runtime.cancel_run(run["id"])
        self.assertEqual(self.finished(run)["status"], "cancelled")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.leases, [])
        self.assertEqual(self.store.account_attempts(run["id"]), [])

    def test_all_cooling_wakes_after_reset_without_duplicate_question(self):
        account = self.account()
        self.cooldown(account)
        runtime = self.runtime()
        session = self.session(policy="failover")
        run = runtime.start(session["id"], "Wait then work")
        self.wait(lambda: bool(self.store.get_run(run["id"])["next_attempt_at"]))
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.store.set_account_status(account["id"], "cooldown", "rate_limited", past)
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE runs SET next_attempt_at=? WHERE id=?", (past, run["id"])
            )
        runtime._wake.set()
        self.assertEqual(self.finished(run)["status"], "completed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            len(
                [
                    e
                    for e in self.store.session_events(session["id"])
                    if e["kind"] == "user_message"
                ]
            ),
            1,
        )

    def test_two_agents_sharing_account_queue_instead_of_holding_a_credential_lease(
        self,
    ):
        account, other_account = self.account("Shared"), self.account("Independent")
        gate, entered = threading.Event(), threading.Event()
        self.gates.append(gate)

        def behavior(call):
            if "block-first" in call["prompt"]:
                entered.set()
                while not gate.wait(0.01):
                    if call["stop"].is_set():
                        raise ProviderCancelled()
            return "Done"

        runtime = self.runtime(behavior)
        first, second, independent = (
            self.session(account),
            self.session(account),
            self.session(other_account),
        )
        running = runtime.start(first["id"], "block-first")
        self.assertTrue(entered.wait(2))
        queued = runtime.start(second["id"], "queued-second")
        other = runtime.start(independent["id"], "independent")
        self.assertEqual(self.finished(other)["status"], "completed")
        self.assertEqual(self.store.get_run(queued["id"])["status"], "queued")
        self.assertEqual(self.store.account_attempts(queued["id"]), [])
        self.assertEqual(
            [value[0] for value in self.leases], [account["id"], other_account["id"]]
        )
        gate.set()
        self.assertEqual(self.finished(running)["status"], "completed")
        self.assertEqual(self.finished(queued)["status"], "completed")

    def test_pending_pool_recovery_does_not_start_two_leases_for_one_account(self):
        account = self.account()
        self.cooldown(account)
        gate, entered = threading.Event(), threading.Event()
        self.gates.append(gate)

        def behavior(call):
            if "first-waiter" in call["prompt"]:
                entered.set()
                while not gate.wait(0.01):
                    if call["stop"].is_set():
                        raise ProviderCancelled()
            return "Done"

        runtime = self.runtime(behavior)
        first, second = self.session(policy="auto"), self.session(policy="auto")
        run_one = runtime.start(first["id"], "first-waiter")
        run_two = runtime.start(second["id"], "second-waiter")
        self.wait(
            lambda: all(
                self.store.get_run(run["id"])["next_attempt_at"]
                for run in (run_one, run_two)
            )
        )
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.store.set_account_status(account["id"], "cooldown", "rate_limited", past)
        with self.store.transaction():
            self.store.db.execute("UPDATE runs SET next_attempt_at=?", (past,))
        runtime._wake.set()
        self.assertTrue(entered.wait(2))
        self.wait(lambda: self.store.get_run(run_two["id"])["status"] == "queued")
        self.assertEqual(len(self.leases), 1)
        self.assertEqual(self.store.account_attempts(run_two["id"]), [])
        gate.set()
        self.assertEqual(self.finished(run_one)["status"], "completed")
        self.assertEqual(self.finished(run_two)["status"], "completed")

    def test_failover_waits_for_busy_backup_without_burning_an_attempt(self):
        first, backup = self.account("Primary"), self.account("Backup")
        gate, entered = threading.Event(), threading.Event()
        self.gates.append(gate)

        def behavior(call):
            if "hold-backup" in call["prompt"]:
                entered.set()
                while not gate.wait(0.01):
                    if call["stop"].is_set():
                        raise ProviderCancelled()
            elif call["account_id"] == first["id"]:
                raise ProviderError("Limited", code="rate_limited", rejected=True)
            return "Done"

        runtime = self.runtime(behavior)
        occupied = self.session(backup)
        holding = runtime.start(occupied["id"], "hold-backup")
        self.assertTrue(entered.wait(2))
        session = self.session(first, "failover", [first["id"], backup["id"]])
        run = runtime.start(session["id"], "Fail over")
        self.wait(lambda: bool(self.store.get_run(run["id"])["next_attempt_at"]))
        self.assertEqual(
            [a["status"] for a in self.store.account_attempts(run["id"])], ["rejected"]
        )
        self.assertEqual(len(self.leases), 2)
        gate.set()
        self.assertEqual(self.finished(holding)["status"], "completed")
        self.assertEqual(self.finished(run)["status"], "completed")
        self.assertEqual(
            [a["account_id"] for a in self.store.account_attempts(run["id"])],
            [first["id"], backup["id"]],
        )

    def test_queued_account_became_unavailable_is_rejected_without_a_native_call(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first, "failover", [first["id"], second["id"]])
        run = self.store.enqueue_run(session["id"], "Preflight failure")
        self.cooldown(first)
        runtime = self.runtime()
        runtime._notify()
        self.assertEqual(self.finished(run)["status"], "completed")
        self.assertEqual([call["account_id"] for call in self.calls], [second["id"]])
        self.assertEqual(
            self.store.account_attempts(run["id"])[0]["error_code"],
            "account_unavailable",
        )

    def test_session_account_override_is_atomic_and_does_not_edit_agent(self):
        first, second = self.account("One"), self.account("Two")
        original = self.session(first)
        before = len(self.store.state()["sessions"])
        with self.assertRaises(Missing):
            self.store.add_session(
                original["agent_id"], "Invalid", {"account_id": str(uuid.uuid4())}
            )
        self.assertEqual(len(self.store.state()["sessions"]), before)
        created = self.store.add_session(
            original["agent_id"], "Selected", {"account_id": second["id"]}
        )
        self.assertEqual(created["account_id"], second["id"])
        self.assertEqual(
            self.store.get_agent(original["agent_id"])["account_id"], first["id"]
        )
        runtime = self.runtime()
        self.assertEqual(
            self.finished(runtime.start(created["id"], "Use selection"))["status"],
            "completed",
        )
        self.assertEqual(self.calls[-1]["account_id"], second["id"])

    def test_account_identity_accepts_only_bounded_display_metadata(self):
        account = self.account()
        updated = self.store.set_account_identity(
            account["id"],
            {"email": "fixture@example.com", "plan": "Pro", "access_token": "private"},
        )
        self.assertEqual(
            updated["identity"], {"email": "fixture@example.com", "plan": "Pro"}
        )
        with self.assertRaises(Invalid):
            self.store.set_account_identity(account["id"], {"email": "private\nsecret"})
        self.assertNotIn(
            "private",
            self.store.db.execute(
                "SELECT identity FROM accounts WHERE id=?", (account["id"],)
            ).fetchone()[0],
        )

    def test_remote_fallback_uses_distinct_attempt_ids_and_account_metadata_only(self):
        environment = self.store.add_environment("Fixture remote", "fixture.invalid")
        first, second = (
            self.account("One", environment=environment["id"]),
            self.account("Two", environment=environment["id"]),
        )
        session = self.session(
            first,
            "failover",
            [first["id"], second["id"]],
            environment=environment["id"],
        )
        runtime = self.runtime()
        runtime.remote.check = lambda *_: None
        remote_calls = []

        def remote_run(
            environment_id, attempt_id, spec, stop, emit, bind, approve, tool
        ):
            remote_calls.append((environment_id, attempt_id, spec))
            if spec["account"]["id"] == first["id"]:
                raise ProviderError(
                    "Retry another account", code="quota_exhausted", rejected=True
                )
            bind(str(uuid.uuid4()))
            return "Remote answer"

        runtime.remote.run = remote_run
        result = self.finished(runtime.start(session["id"], "Remote"))
        self.assertEqual(result["status"], "completed")
        attempts = self.store.account_attempts(result["id"])
        self.assertEqual(
            [call[1] for call in remote_calls], [attempt["id"] for attempt in attempts]
        )
        self.assertEqual(len(set(call[1] for call in remote_calls)), 2)
        self.assertTrue(all(call[1] != result["id"] for call in remote_calls))
        self.assertTrue(
            all(
                set(call[2]["account"]) == {"id", "provider", "generation"}
                for call in remote_calls
            )
        )
        self.assertEqual(self.leases, [])

    def test_restart_marks_orphaned_run_interrupted_without_replay(self):
        account = self.account()
        session = self.session(account)
        run = self.store.begin_run(session["id"], "Interrupted work")
        attempt = self.store.reserve_run_account(run["id"])
        self.store.close()
        self.store = Store(self.path)
        runtime = self.runtime()
        runtime._notify()
        self.assertEqual(self.store.get_run(run["id"])["status"], "interrupted")
        self.assertEqual(self.store.account_attempts(run["id"])[0]["id"], attempt["id"])
        self.assertEqual(
            self.store.account_attempts(run["id"])[0]["status"], "interrupted"
        )
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
