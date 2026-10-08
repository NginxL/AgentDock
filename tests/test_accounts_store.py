import json
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentdock.store import Conflict, Invalid, Missing, Store


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = Store(self.path)
        self.store.set_feature("automatic_failover", True, acknowledged=True)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def account(
        self, label="One", provider="codex", environment_id="local", priority=0
    ):
        account = self.store.add_account(provider, label, environment_id, priority)
        return self.store.complete_account_login(account["id"])

    def session(self, account=None, policy="manual", pool=None):
        agent = self.store.add_agent(
            None,
            "Worker",
            "codex",
            account_id=account["id"] if account else None,
            account_policy=policy,
            account_ids=pool,
        )
        return self.store.add_session(agent["id"], "Conversation")

    def future(self, seconds=100):
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()

    def test_metadata_validation_and_no_native_secrets_in_quota(self):
        account = self.store.add_account("claude", "Personal")
        self.assertEqual(account["status"], "pending")
        self.assertEqual(account["generation"], 0)
        for changes in (
            {"token": "secret"},
            {"priority": True},
            {"status": "expired"},
            {"enabled": "yes"},
        ):
            with self.assertRaises(Invalid):
                self.store.update_account(account["id"], changes)
        with self.assertRaises(Invalid):
            self.store.add_account("other", "No")
        with self.assertRaises(Invalid):
            self.store.set_account_status(
                account["id"], "expired", error="Bearer private-token"
            )
        self.store.set_account_quota(
            account["id"],
            {
                "access_token": "private-token",
                "windows": [
                    {
                        "name": "session",
                        "used_percent": 50,
                        "raw_response": "private-token",
                    }
                ],
            },
        )
        raw = self.store.db.execute(
            "SELECT quota FROM accounts WHERE id=?", (account["id"],)
        ).fetchone()[0]
        self.assertNotIn("private-token", raw)
        self.assertEqual(
            json.loads(raw)["windows"], [{"name": "session", "used_percent": 50}]
        )

    def test_existing_device_login_default_and_session_identity(self):
        session = self.session()
        run = self.store.begin_run(session["id"], "Hello")
        self.assertIsNone(run["account_id"])
        self.assertEqual(run["account_policy"], "manual")
        self.assertEqual(run["account_branch"], 0)
        attempt = self.store.reserve_run_account(run["id"])
        self.assertIsNone(attempt["account_id"])
        self.assertEqual(self.store.get_session(session["id"])["account_branch"], 0)

    def test_provider_device_and_pool_boundaries(self):
        local = self.account()
        claude = self.account(provider="claude")
        env = self.store.add_environment("Other", "test-host")
        remote = self.account(environment_id=env["id"])
        for account in (claude, remote):
            with self.assertRaises(Invalid):
                self.session(account)
        with self.assertRaises(Invalid):
            self.session(local, "failover", [remote["id"]])
        with self.assertRaises(Invalid):
            self.session(None, "auto", [local["id"], local["id"]])
        with self.assertRaises(Conflict):
            self.store.remove_environment(env["id"])

    def test_session_defaults_frozen_across_agent_edits_and_project_reuse(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first, "failover", [first["id"], second["id"]])
        self.store.update_agent(
            session["agent_id"],
            {"account_id": second["id"], "account_policy": "manual", "account_ids": []},
        )
        original = self.store.get_session(session["id"])
        newer = self.store.add_session(session["agent_id"], "New")
        self.assertEqual(original["account_id"], first["id"])
        self.assertEqual(original["account_policy"], "failover")
        self.assertEqual(newer["account_id"], second["id"])
        project = self.store.add_project("Project", self.temp.name)
        member = self.store.add_project_agent(
            project["id"], {"source_agent_id": session["agent_id"], "name": "Reviewer"}
        )
        self.assertEqual(member["account_id"], second["id"])
        self.store.update_agent(member["id"], {"account_id": first["id"]})
        self.assertEqual(
            self.store.get_agent(session["agent_id"])["account_id"], second["id"]
        )

    def test_selection_uses_priority_quota_and_least_recent_use(self):
        first, second = self.account("One"), self.account("Two")
        one, two = self.session(policy="auto"), self.session(policy="auto")
        run_one = self.store.enqueue_run(one["id"], "One")
        run_two = self.store.enqueue_run(two["id"], "Two")
        self.assertNotEqual(run_one["account_id"], run_two["account_id"])
        self.store.set_account_quota(first["id"], {"windows": [{"used_percent": 90}]})
        self.store.set_account_quota(second["id"], {"windows": [{"used_percent": 50}]})
        third = self.session(policy="auto")
        self.assertEqual(
            self.store.enqueue_run(third["id"], "Three")["account_id"], second["id"]
        )
        self.store.update_account(first["id"], {"priority": 10})
        fourth = self.session(policy="auto")
        self.assertEqual(
            self.store.enqueue_run(fourth["id"], "Four")["account_id"], first["id"]
        )

    def test_ordered_pool_excludes_other_ready_accounts(self):
        first, second, outside = (
            self.account("One"),
            self.account("Two"),
            self.account("Outside", priority=100),
        )
        session = self.session(policy="auto", pool=[second["id"], first["id"]])
        run = self.store.enqueue_run(session["id"], "Select")
        self.assertEqual(run["account_id"], second["id"])
        self.assertNotEqual(run["account_id"], outside["id"])

    def test_unknown_and_stale_quota_are_not_ranked_as_full(self):
        unknown, known = self.account("Unknown"), self.account("Known")
        self.store.set_account_quota(
            known["id"], {"status": "ok", "windows": [{"remaining_percent": 5}]}
        )
        self.assertIsNone(self.store._account_remaining(unknown))
        selected = self.store._choose_account(
            "codex",
            "local",
            {"account_policy": "auto", "account_id": None, "account_ids": []},
        )
        self.assertEqual(selected["id"], known["id"])
        stale = self.store.set_account_quota(
            unknown["id"], {"status": "stale", "windows": [{"remaining_percent": 99}]}
        )
        self.assertIsNone(self.store._account_remaining(stale))
        self.assertTrue(self.store._account_available(stale))
        exhausted = self.store.set_account_quota(
            unknown["id"],
            {
                "status": "stale",
                "windows": [{"remaining_percent": 0, "reset_at": self.future()}],
            },
        )
        self.assertFalse(self.store._account_available(exhausted))

    def test_concurrent_reservation_is_idempotent_and_generation_fixed(self):
        account = self.account()
        session = self.session(account)
        run = self.store.begin_run(session["id"], "Once")
        with ThreadPoolExecutor(max_workers=8) as executor:
            attempts = list(
                executor.map(
                    lambda _: self.store.reserve_run_account(run["id"]), range(16)
                )
            )
        self.assertEqual(len({a["id"] for a in attempts}), 1)
        self.assertEqual(len(self.store.account_attempts(run["id"])), 1)
        self.assertEqual(attempts[0]["generation"], account["generation"])
        with self.assertRaises(Conflict):
            self.store.complete_account_login(account["id"])
        with self.assertRaises(Conflict):
            self.store.update_account(account["id"], {"enabled": False})
        with self.assertRaises(Conflict):
            self.store.switch_session_account(session["id"], None)

    def test_failover_distinct_accounts_maximum_three(self):
        accounts = [self.account(str(index)) for index in range(4)]
        session = self.session(accounts[0], "failover", [a["id"] for a in accounts])
        run = self.store.begin_run(session["id"], "Run")
        attempt = self.store.reserve_run_account(run["id"])
        for index in range(3):
            self.assertEqual(attempt["account_id"], accounts[index]["id"])
            self.store.finish_account_attempt(attempt["id"], "rejected", "rate_limited")
            if index < 2:
                attempt = self.store.reserve_run_account(run["id"], fallback=True)
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"], fallback=True)
        self.assertEqual(len(self.store.account_attempts(run["id"])), 3)
        self.assertIsNone(self.store.next_account_retry(run["id"]))

    def test_progress_prevents_replay_and_finished_attempt_cannot_be_reopened(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first, "failover")
        run = self.store.begin_run(session["id"], "Write a file")
        attempt = self.store.reserve_run_account(run["id"])
        self.store.mark_account_attempt_progress(attempt["id"])
        with self.assertRaises(Conflict):
            self.store.finish_account_attempt(attempt["id"], "rejected", "rate_limited")
        self.store.finish_account_attempt(attempt["id"], "failed", "rate_limited")
        for fallback in (False, True):
            with self.assertRaises(Conflict):
                self.store.reserve_run_account(run["id"], fallback=fallback)

    def test_manual_and_auto_policies_never_failover_after_attempt(self):
        first, second = self.account("One"), self.account("Two")
        for policy in ("manual", "auto"):
            session = self.session(first, policy)
            run = self.store.begin_run(session["id"], "Run")
            attempt = self.store.reserve_run_account(run["id"])
            self.store.finish_account_attempt(attempt["id"], "rejected", "rate_limited")
            with self.assertRaises(Conflict):
                self.store.reserve_run_account(run["id"], fallback=True)
            self.store.finish_run(run["id"], "failed")

    def test_auto_sticks_to_selected_account_instead_of_silently_switching(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first, "auto")
        deadline = self.future()
        self.store.set_account_status(first["id"], "cooldown", "rate_limited", deadline)
        run = self.store.begin_run(session["id"], "Keep the account")
        self.assertEqual(run["account_id"], first["id"])
        self.assertEqual(run["account_selection_pending"], 1)
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"])
        self.assertEqual(self.store.next_account_retry(run["id"]), deadline)
        self.assertNotEqual(run["account_id"], second["id"])

    def test_unavailable_queued_identity_can_fail_over_only_after_preflight_rejection(
        self,
    ):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first, "failover")
        run = self.store.enqueue_run(session["id"], "Queued")
        self.store.set_account_status(
            first["id"], "cooldown", "rate_limited", self.future()
        )
        self.store.claim_next_run()
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"])
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"], fallback=True)
        rejected = self.store.reject_unavailable_run_account(run["id"])
        self.assertEqual(rejected["status"], "rejected")
        self.assertFalse(rejected["progress"])
        self.assertEqual(
            self.store.reject_unavailable_run_account(run["id"])["id"], rejected["id"]
        )
        next_attempt = self.store.reserve_run_account(run["id"], fallback=True)
        self.assertEqual(next_attempt["account_id"], second["id"])

    def test_deleted_account_never_uses_device_login_and_cleanup_failure_is_retryable(
        self,
    ):
        account = self.account()
        session = self.session(account)

        def fail_cleanup(_):
            raise OSError("offline")

        with self.assertRaises(OSError):
            self.store.remove_account(account["id"], fail_cleanup)
        self.assertEqual(self.store.get_account(account["id"])["status"], "ready")
        self.store.remove_account(account["id"])
        with self.assertRaises(Conflict):
            self.store.enqueue_run(session["id"], "No fallback")
        self.assertEqual(
            self.store.get_session(session["id"])["account_id"], account["id"]
        )

    def test_active_account_cannot_be_removed_or_preflight_rejected(self):
        account = self.account()
        session = self.session(account)
        run = self.store.begin_run(session["id"], "Working")
        with self.assertRaises(Conflict):
            self.store.remove_account(account["id"])
        with self.assertRaises(Conflict):
            self.store.reject_unavailable_run_account(run["id"])

    def test_other_session_cannot_reuse_a_historical_branch_native_identity(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first)
        self.store.bind_native_session(session["id"], "native-history")
        self.store.switch_session_account(session["id"], second["id"])
        other = self.session(first)
        with self.assertRaises(Conflict):
            self.store.bind_native_session(other["id"], "native-history")

    def test_switch_creates_branch_and_preserves_history_usage_and_cleanup(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first)
        run = self.store.begin_run(session["id"], "Old")
        attempt = self.store.reserve_run_account(run["id"])
        self.store.bind_native_session(session["id"], "native-one", run["id"])
        self.store.finish_account_attempt(attempt["id"], "completed")
        self.store.finish_run(run["id"], "completed", result="Old final answer")
        switched = self.store.switch_session_account(session["id"], second["id"])
        self.assertIsNone(switched["native_session_id"])
        self.assertEqual(switched["account_branch"], 1)
        self.assertEqual(self.store.get_run(run["id"])["result"], "Old final answer")
        self.assertEqual(
            self.store.usage_bindings()[("codex", "native-one")], session["agent_id"]
        )
        self.assertEqual(
            self.store.account_usage_bindings()[("codex", "native-one")], first["id"]
        )
        self.store.remove_account(first["id"])
        self.assertEqual(self.store.get_account(first["id"])["status"], "removed")
        self.store.delete_session(session["id"], lambda *_: None)
        self.assertFalse(self.store.db.execute("SELECT 1 FROM run_attempts").fetchone())
        self.assertFalse(
            self.store.db.execute("SELECT 1 FROM session_account_branches").fetchone()
        )

    def test_queued_turn_keeps_original_account_after_earlier_failover(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first, "failover")
        run = self.store.begin_run(session["id"], "First")
        queued = self.store.enqueue_run(session["id"], "Second")
        attempt = self.store.reserve_run_account(run["id"])
        self.store.finish_account_attempt(attempt["id"], "rejected", "rate_limited")
        backup = self.store.reserve_run_account(run["id"], fallback=True)
        self.store.bind_native_session(
            session["id"], "second-account-native", run["id"]
        )
        self.store.finish_account_attempt(backup["id"], "completed")
        self.store.finish_run(run["id"], "completed")
        self.assertEqual(
            self.store.get_session(session["id"])["account_id"], second["id"]
        )
        self.assertEqual(self.store.claim_next_run()["id"], queued["id"])
        recovered = self.store.reserve_run_account(queued["id"])
        self.assertEqual(recovered["account_id"], first["id"])
        self.assertEqual(self.store.get_session(session["id"])["account_branch"], 0)
        self.assertIsNone(self.store.get_session(session["id"])["native_session_id"])

    def test_enqueue_different_choice_does_not_mutate_active_session(self):
        first, second = self.account("One"), self.account("Two")
        session = self.session(first, "failover")
        running = self.store.begin_run(session["id"], "First")
        self.store.reserve_run_account(running["id"])
        self.store.bind_native_session(session["id"], "first-native", running["id"])
        before = self.store.get_session(session["id"])
        self.store.set_account_quota(
            first["id"],
            {"windows": [{"used_percent": 100, "resets_at": self.future()}]},
        )
        queued = self.store.enqueue_run(session["id"], "Second")
        self.assertEqual(queued["account_id"], second["id"])
        after = self.store.get_session(session["id"])
        for field in ("account_id", "account_branch", "native_session_id"):
            self.assertEqual(after[field], before[field])

    def test_all_accounts_cooling_wait_and_resume_without_duplicate_prompt(self):
        account = self.account()
        deadline = self.future()
        self.store.set_account_status(
            account["id"], "cooldown", "rate_limited", deadline
        )
        session = self.session(policy="failover")
        run = self.store.begin_run(session["id"], "Only once")
        self.assertEqual(run["account_selection_pending"], 1)
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"])
        self.assertEqual(self.store.next_account_retry(run["id"]), deadline)
        self.store.requeue_account_run(run["id"], deadline)
        self.assertIsNone(self.store.claim_next_run())
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.store.set_account_status(account["id"], "cooldown", "rate_limited", past)
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE runs SET next_attempt_at=? WHERE id=?", (past, run["id"])
            )
        claimed = self.store.claim_next_run()
        self.assertEqual(claimed["id"], run["id"])
        attempt = self.store.reserve_run_account(run["id"])
        self.assertEqual(attempt["account_id"], account["id"])
        recovered = self.store.get_account(account["id"])
        self.assertEqual(recovered["status"], "ready")
        self.assertIsNone(recovered["cooldown_until"])
        self.assertIsNone(recovered["error"])
        prompts = [
            event
            for event in self.store.session_events(session["id"])
            if event["kind"] == "user_message"
        ]
        self.assertEqual(len(prompts), 1)

    def test_expired_cooldown_does_not_clear_another_exhausted_quota_window(self):
        account = self.account()
        session = self.session(account)
        run = self.store.begin_run(session["id"], "Blocked at admission")
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.store.set_account_status(
            account["id"],
            "cooldown",
            "quota_exhausted",
            past,
            {"windows": [{"remaining_percent": 0}]},
        )
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"])
        blocked = self.store.get_account(account["id"])
        self.assertEqual(blocked["status"], "cooldown")
        self.assertEqual(blocked["error"], "quota_exhausted")
        self.assertEqual(self.store.account_attempts(run["id"]), [])

    def test_relogin_rotates_generation_and_creates_fresh_native_branch(self):
        account = self.account()
        session = self.session(account)
        run = self.store.begin_run(session["id"], "Before")
        attempt = self.store.reserve_run_account(run["id"])
        self.store.bind_native_session(session["id"], "old-native", run["id"])
        self.store.finish_account_attempt(attempt["id"], "completed")
        self.store.finish_run(run["id"], "completed")
        logged_in = self.store.complete_account_login(account["id"])
        self.assertEqual(logged_in["generation"], 2)
        after = self.store.begin_run(session["id"], "After")
        selected = self.store.reserve_run_account(after["id"])
        self.assertEqual(selected["generation"], 2)
        self.assertEqual(selected["account_branch"], 1)
        self.assertIsNone(self.store.get_session(session["id"])["native_session_id"])

    def test_disabled_and_expired_accounts_require_validated_login(self):
        account = self.account()
        self.store.update_account(account["id"], {"enabled": False})
        self.assertEqual(
            self.store.update_account(account["id"], {"enabled": True})["status"],
            "pending",
        )
        session = self.session(account)
        with self.assertRaises(Conflict):
            self.store.enqueue_run(session["id"], "No login")
        self.store.complete_account_login(account["id"])
        self.store.set_account_status(account["id"], "expired", "login_expired")
        auto = self.session(policy="auto")
        run = self.store.begin_run(auto["id"], "Wait")
        self.assertIsNone(self.store.next_account_retry(run["id"]))
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"])

    def test_remove_unreferenced_account_and_preserve_referenced_history(self):
        account = self.account()
        self.assertEqual(self.store.remove_account(account["id"]), {"ok": True})
        self.assertEqual(self.store.get_account(account["id"])["status"], "removed")
        self.assertEqual(self.store.accounts(), [])
        self.assertEqual(len(self.store.accounts(include_removed=True)), 1)
        kept = self.account()
        self.session(kept)
        calls = []
        self.store.remove_account(
            kept["id"], lambda account: calls.append(account["id"])
        )
        self.store.remove_account(kept["id"], lambda account: calls.append("duplicate"))
        self.assertEqual(calls, [kept["id"]])
        for operation in (
            lambda: self.store.complete_account_login(kept["id"]),
            lambda: self.store.set_account_status(kept["id"], "ready"),
            lambda: self.store.update_account(kept["id"], {"enabled": True}),
        ):
            with self.assertRaises(Conflict):
                operation()

    def test_restart_keeps_attempt_history_and_marks_inflight_interrupted(self):
        account = self.account()
        session = self.session(account)
        run = self.store.begin_run(session["id"], "Active")
        attempt = self.store.reserve_run_account(run["id"])
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get_run(run["id"])["status"], "interrupted")
        self.assertEqual(
            self.store.account_attempts(run["id"])[0]["status"], "interrupted"
        )
        self.assertEqual(self.store.account_attempts(run["id"])[0]["id"], attempt["id"])
        with self.assertRaises(Conflict):
            self.store.reserve_run_account(run["id"])

    def test_legacy_database_migration_keeps_native_history_without_accounts(self):
        self.store.close()
        legacy = Path(self.temp.name) / "legacy.sqlite3"
        agent_id, session_id = str(uuid.uuid4()), str(uuid.uuid4())
        db = sqlite3.connect(legacy)
        db.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE agents(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),name TEXT NOT NULL,provider TEXT NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE sessions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),agent_id TEXT NOT NULL REFERENCES agents(id),title TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,native_session_id TEXT);""")
        db.execute(
            "INSERT INTO projects VALUES(?,?,?,?)",
            ("project", "Project", self.temp.name, self.future()),
        )
        db.execute(
            "INSERT INTO agents VALUES(?,?,?,?,?,?)",
            (agent_id, "project", "Agent", "codex", "", self.future()),
        )
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)",
            (
                session_id,
                "project",
                agent_id,
                "History",
                "completed",
                self.future(),
                self.future(),
                "legacy-native",
            ),
        )
        db.commit()
        db.close()
        self.store = Store(legacy)
        session = self.store.get_session(session_id)
        self.assertEqual(session["native_session_id"], "legacy-native")
        self.assertIsNone(session["account_id"])
        self.assertEqual(session["account_policy"], "manual")
        self.assertEqual(
            self.store.usage_bindings()[("codex", "legacy-native")], agent_id
        )
        self.assertEqual(self.store.accounts(), [])
        self.assertIsNone(self.store.db.execute("PRAGMA foreign_key_check").fetchone())


if __name__ == "__main__":
    unittest.main()
