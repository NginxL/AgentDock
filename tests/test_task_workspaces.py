"""Exercise workspace ownership and native-process leases without user repositories."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from agentdock.execution_lease import assert_idle, lease
from agentdock.store import Conflict
from agentdock.task_workspace import prepare


class TaskWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.test")
        self.git("config", "user.name", "Fixture")
        (self.repo / "code.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Initial")
        self.task = str(uuid.uuid4())
        self.a = str(uuid.uuid4())
        self.b = str(uuid.uuid4())

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True
        ).strip()

    def test_worktrees_are_owned_idempotent_and_pin_a_common_base(self):
        first = prepare(self.root / "tasks", self.task, self.a, self.repo)
        (Path(first["path"]) / "code.txt").write_text("owner changes\n")
        self.assertEqual(
            first, prepare(self.root / "tasks", self.task, self.a, self.repo)
        )
        (self.repo / "code.txt").write_text("new upstream\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Later upstream")
        second = prepare(self.root / "tasks", self.task, self.b, self.repo)
        self.assertEqual(first["base_commit"], second["base_commit"])
        self.assertEqual((Path(second["path"]) / "code.txt").read_text(), "base\n")
        self.assertEqual((self.repo / "code.txt").read_text(), "new upstream\n")
        self.assertEqual(
            (Path(first["path"]) / "code.txt").read_text(), "owner changes\n"
        )

    def test_dirty_source_and_unowned_paths_fail_without_cleaning(self):
        (self.repo / "uncommitted.txt").write_text("keep")
        with self.assertRaisesRegex(ValueError, "Commit or save"):
            prepare(self.root / "tasks", self.task, self.a, self.repo)
        (self.repo / "uncommitted.txt").unlink()
        target = self.root / "tasks" / self.task / self.a / "workspace"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            prepare(self.root / "tasks", self.task, self.a, self.repo)
        self.assertEqual((target / "keep.txt").read_text(), "keep")
        target.rename(target.with_name("saved"))
        target.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare(self.root / "tasks", self.task, self.a, self.repo)
        self.assertTrue((self.repo / "code.txt").exists())

    def test_native_child_holds_lease_after_controller_descriptor_closes(self):
        home = self.root / "session"
        child = None
        try:
            with lease(home) as descriptor:
                child = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    pass_fds=(descriptor,),
                )
            with self.assertRaises(Conflict):
                assert_idle(home)
            with self.assertRaises(Conflict):
                with lease(home):
                    pass
            child.terminate()
            child.wait(timeout=3)
            assert_idle(home)
            with lease(home / "branches" / "account"):
                with self.assertRaises(Conflict):
                    assert_idle(home)
        finally:
            if child and child.poll() is None:
                child.kill()
                child.wait()
