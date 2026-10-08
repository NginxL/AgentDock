"""Crash-recovery cleanup uses only temporary credentials and fake SSH RPCs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agentdock import ssh_worker
from agentdock.accounts import AccountError, AccountManager, _write
from agentdock.runtime import Runtime
from agentdock.store import Missing, Store


class AccountCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / "local" / "state.sqlite3")
        with patch("agentdock.account_service.AccountService.watch"):
            self.runtime = Runtime(
                self.store, {"execution_enabled": True, "commands": {}}
            )

    def tearDown(self):
        self.runtime.close()
        self.store.close()
        self.temp.cleanup()

    def session(self, remote=False):
        environment = (
            self.store.add_environment("Fixture", "fixture-host")["id"]
            if remote
            else "local"
        )
        accounts = [
            self.store.complete_account_login(
                self.store.add_account("codex", name, environment)["id"]
            )
            for name in ("Old account", "Current account")
        ]
        agent = self.store.add_agent(
            None,
            "Fixture",
            "codex",
            account_id=accounts[0]["id"],
            environment_id=environment,
        )
        session = self.store.add_session(agent["id"], "Fixture")
        self.store.switch_session_account(session["id"], accounts[1]["id"])
        return accounts, self.store.get_session(session["id"])

    def pending(self, manager, account, session):
        source = Path(manager.environment(account, {})["CODEX_HOME"])
        _write(source / "auth.json", {"tokens": {"refresh_token": "old-fixture"}})
        target = manager.root.parent / "sessions" / session["id"] / "codex"
        _write(target / "auth.json", {"tokens": {"refresh_token": "refreshed-fixture"}})
        _write(
            source.parent / ".pending-session.json",
            {
                "provider": "codex",
                "phase": "copying",
                "target": str(target.relative_to(manager.root.parent)),
                "source_hashes": {
                    "auth.json": manager._fingerprint(source / "auth.json")
                },
            },
        )
        return source, target.parent

    def assert_recovered(self, source, session_home):
        self.assertEqual(
            json.loads((source / "auth.json").read_text())["tokens"]["refresh_token"],
            "refreshed-fixture",
        )
        self.assertFalse((source.parent / ".pending-session.json").exists())
        self.assertFalse(session_home.exists())

    def test_delete_session_recovers_retired_account_branch_without_creating_unused_profiles(
        self,
    ):
        accounts, session = self.session()
        manager = self.runtime.accounts.manager
        source, home = self.pending(manager, accounts[0], session)
        self.runtime.delete_session(session["id"])
        self.assert_recovered(source, home)
        self.assertFalse((manager.root / accounts[1]["id"]).exists())
        with self.assertRaises(Missing):
            self.store.get_session(session["id"])

    def test_delete_agent_recovers_pending_credentials_before_removing_its_sessions(
        self,
    ):
        accounts, session = self.session()
        source, home = self.pending(self.runtime.accounts.manager, accounts[0], session)
        self.runtime.delete_agent(session["agent_id"])
        self.assert_recovered(source, home)
        with self.assertRaises(Missing):
            self.store.get_agent(session["agent_id"])

    def test_surviving_native_lease_blocks_local_cleanup_and_preserves_record(self):
        accounts, session = self.session()
        manager = self.runtime.accounts.manager
        source, home = self.pending(manager, accounts[0], session)
        program = """import json,sys
from agentdock.accounts import AccountManager
manager=AccountManager(sys.argv[1])
with manager.lease(json.loads(sys.argv[2]), recover=False):
    print('locked', flush=True)
    sys.stdin.readline()
"""
        child = subprocess.Popen(
            [sys.executable, "-c", program, str(manager.root), json.dumps(accounts[0])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaisesRegex(AccountError, "busy"):
                self.runtime.delete_session(session["id"])
            self.assertTrue(home.exists())
            self.assertTrue((source.parent / ".pending-session.json").exists())
            self.assertEqual(self.store.get_session(session["id"])["id"], session["id"])
        finally:
            child.communicate("\n", timeout=5)
        self.runtime.delete_session(session["id"])
        self.assert_recovered(source, home)

    def remote_fixture(self, session):
        # A persisted prior run makes Runtime request remote cleanup after restart.
        run = self.store.begin_run(session["id"], "Finished fixture")
        self.store.finish_run(run["id"], "interrupted")
        self.runtime.remote.rpc = Mock(
            side_effect=lambda _, request, **kwargs: ssh_worker.rpc(request)
        )
        return AccountManager(
            self.root / "remote" / "controllers" / self.store.controller_id / "accounts"
        )

    def test_remote_cleanup_recovers_all_account_branches(self):
        accounts, session = self.session(remote=True)
        manager = self.remote_fixture(session)
        source, home = self.pending(manager, accounts[0], session)
        with patch.object(ssh_worker, "ROOT", self.root / "remote"):
            self.runtime.delete_session(session["id"])
        self.assert_recovered(source, home)
        request = self.runtime.remote.rpc.call_args.args[1]
        self.assertEqual(
            {a["id"] for a in request["accounts"]}, {a["id"] for a in accounts}
        )
        self.assertTrue(all(set(a) == {"id", "provider"} for a in request["accounts"]))

    def test_remote_cleanup_keeps_files_until_old_account_lease_is_released(self):
        accounts, session = self.session(remote=True)
        manager = self.remote_fixture(session)
        source, home = self.pending(manager, accounts[0], session)
        with patch.object(ssh_worker, "ROOT", self.root / "remote"):
            with manager.lease(accounts[0], recover=False):
                with self.assertRaisesRegex(AccountError, "busy"):
                    self.runtime.delete_agent(session["agent_id"])
            self.assertTrue(home.exists())
            self.assertEqual(self.store.get_session(session["id"])["id"], session["id"])
            self.runtime.delete_agent(session["agent_id"])
        self.assert_recovered(source, home)


if __name__ == "__main__":
    unittest.main()
