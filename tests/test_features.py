import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agentdock.account_service import AccountService
from agentdock.store import Forbidden, Invalid, Store


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_defaults_acknowledgment_and_persisted_failover_gate(self):
        self.assertFalse(any(self.store.features().values()))
        with self.assertRaises(Invalid):
            self.store.set_feature("automatic_failover", True)
        self.store.set_feature("automatic_failover", True, acknowledged=True)
        account = self.store.complete_account_login(
            self.store.add_account("codex", "Fixture")["id"]
        )
        agent = self.store.add_agent(
            None,
            "Fixture",
            "codex",
            account_id=account["id"],
            account_policy="failover",
        )
        session = self.store.add_session(agent["id"], "Fixture")
        self.store.set_feature("automatic_failover", False)
        with self.assertRaises(Forbidden):
            self.store.enqueue_run(session["id"], "Must not change accounts")
        self.store.close()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.assertFalse(self.store.features()["automatic_failover"])

    def test_disabled_native_switch_never_calls_client_or_credential_manager(self):
        runtime = Mock(enabled=True, config={})
        service = AccountService(self.store, runtime)
        service.native = Mock()
        try:
            account = self.store.add_account("codex", "Fixture")
            with self.assertRaises(Forbidden):
                service.native_action(account["id"], "switch", "codex")
            service.native.switch.assert_not_called()
        finally:
            service.close()

    def test_claude_quota_has_no_active_query_or_experimental_switch(self):
        runtime = Mock(enabled=True, config={})
        service = AccountService(self.store, runtime)
        service.manager = Mock()
        try:
            account = self.store.complete_account_login(
                self.store.add_account("claude", "Fixture")["id"]
            )
            value = service.refresh(account["id"], force=True)
            service.manager.refresh.assert_not_called()
            self.assertEqual(value["quota"], account["quota"])
            self.assertEqual(value["quota"]["status"], "unknown")
            self.assertNotIn("claude_quota", self.store.features())
            with self.assertRaises(Invalid):
                self.store.set_feature("claude_quota", True, acknowledged=True)
        finally:
            service.close()
