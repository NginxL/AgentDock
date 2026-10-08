"""A reusable CLI configuration never reuses another project's conversation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agentdock.store import Conflict, Forbidden, Invalid, Missing, Store


class ProjectAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.sqlite3")
        self.projects = []
        for name in ("A", "B"):
            path = self.root / name
            path.mkdir()
            self.projects.append(self.store.add_project(name, str(path)))
        self.base = self.store.add_agent(
            None,
            "My Codex",
            "codex",
            "General assistant",
            model="model-a",
            effort="high",
        )
        self.daily = self.store.add_session(self.base["id"], "Everyday question")
        self.store.bind_native_session(self.daily["id"], "daily-native")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def members(self):
        return [
            self.store.add_project_agent(
                p["id"],
                {"source_agent_id": self.base["id"], "name": name, "role": role},
            )
            for p, name, role in zip(
                self.projects, ("cr", "coding"), ("Review only", "Implement changes")
            )
        ]

    def test_reuse_preserves_daily_history_and_separates_workspaces_native_ids_and_settings(
        self,
    ):
        original = self.store.get_session(self.daily["id"])
        a, b = self.members()
        self.assertEqual([a["name"], b["name"]], ["cr", "coding"])
        self.assertEqual(
            [a["workspace"], b["workspace"]], [p["path"] for p in self.projects]
        )
        self.assertEqual(a["source_agent_id"], b["source_agent_id"])
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(len(self.store.state()["sessions"]), 1)
        sessions = [self.store.add_session(m["id"], "Project chat") for m in (a, b)]
        self.assertTrue(all(s["native_session_id"] is None for s in sessions))
        self.assertEqual(
            len(
                {self.store.session_directory(s["id"]) for s in [self.daily, *sessions]}
            ),
            3,
        )
        for s in sessions:
            with self.assertRaises(Conflict):
                self.store.bind_native_session(s["id"], "daily-native")
        self.store.bind_native_session(sessions[0]["id"], "a-native")
        self.store.bind_native_session(sessions[1]["id"], "b-native")
        self.store.update_agent(
            a["id"],
            {
                "name": "review",
                "role": "A rules",
                "model": "model-b",
                "effort": "low",
                "permission_mode": "full_access",
            },
        )
        self.assertEqual(self.store.get_agent(b["id"]), b)
        self.assertEqual(self.store.get_agent(self.base["id"]), self.base)
        self.assertEqual(self.store.get_session(self.daily["id"]), original)
        self.store.update_session_settings(
            sessions[0]["id"], {"model": "session-model", "effort": "medium"}
        )
        self.assertFalse(self.store.get_session(sessions[1]["id"])["model_override"])
        self.store.update_agent(
            self.base["id"], {"role": "New base role", "model": "model-c"}
        )
        self.assertEqual(self.store.get_agent(b["id"]), b)

    def test_project_and_daily_capabilities_memory_dispatch_and_cancellation_stay_separate(
        self,
    ):
        a, b = self.members()
        sessions = [self.store.add_session(m["id"], "Chat") for m in (a, b)]
        for p, content in zip(self.projects, ("Only project A", "Only project B")):
            self.store.put_memory(p["id"], "rules", content, 0)
        runs = [
            self.store.begin_run(s["id"], "Question") for s in [*sessions, self.daily]
        ]
        tokens = [self.store.issue_capability(r["id"]) for r in runs]
        for i in (0, 1):
            context = self.store.context_for_run(runs[i]["id"])
            self.assertIn(("Only project A", "Only project B")[i], context)
            self.assertNotIn(("Only project B", "Only project A")[i], context)
            self.assertEqual(
                [m["id"] for m in self.store.respond_tool(tokens[i], "agent_list", {})],
                [(a, b)[i]["id"]],
            )
            self.assertEqual(
                len(self.store.respond_tool(tokens[i], "memory_search", {})), 1
            )
        self.assertNotIn("Only project", self.store.context_for_run(runs[2]["id"]))
        self.assertEqual(self.store.respond_tool(tokens[2], "memory_search", {}), [])
        self.assertEqual(self.store.respond_tool(tokens[2], "agent_list", {}), [])
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                a["project_id"],
                a["id"],
                b["id"],
                "Cross-project",
                parent_run_id=runs[0]["id"],
            )
        with self.assertRaises(Forbidden):
            self.store.enqueue_message(
                a["project_id"],
                "human",
                a["id"],
                "Wrong conversation",
                recipient_session_id=self.daily["id"],
            )
        self.assertEqual(self.store.cancel_run_tree(runs[0]["id"]), [runs[0]["id"]])
        self.store.finish_run(runs[0]["id"], "cancelled")
        self.assertEqual(self.store.get_run(runs[1]["id"])["status"], "running")
        self.assertEqual(self.store.get_run(runs[2]["id"])["status"], "running")

    def test_same_cli_can_run_different_project_directories_concurrently(self):
        a, b = self.members()
        for m in (a, b):
            self.store.enqueue_run(
                self.store.add_session(m["id"], "Chat")["id"], "Work"
            )
        self.assertEqual(
            {
                self.store.claim_next_run()["agent_id"],
                self.store.claim_next_run()["agent_id"],
            },
            {a["id"], b["id"]},
        )

    def test_overlapping_project_directories_still_serialize(self):
        a, _ = self.members()
        p = self.store.add_project("Same files", a["workspace"])
        c = self.store.add_project_agent(
            p["id"], {"source_agent_id": self.base["id"], "name": "Other role"}
        )
        for m in (a, c):
            self.store.enqueue_run(
                self.store.add_session(m["id"], "Chat")["id"], "Work"
            )
        self.assertIsNotNone(self.store.claim_next_run())
        self.assertIsNone(self.store.claim_next_run())

    def test_deleting_a_member_or_source_never_deletes_other_members_or_daily_files(
        self,
    ):
        a, b = self.members()
        sa, sb = [self.store.add_session(m["id"], "Chat") for m in (a, b)]
        cleanup = Mock()
        self.store.delete_agent(a["id"], cleanup)
        self.assertEqual(cleanup.call_args[0][0]["id"], sa["id"])
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual(self.store.get_agent(b["id"]), b)
        self.assertEqual(
            self.store.get_session(self.daily["id"])["native_session_id"],
            "daily-native",
        )
        self.store.delete_agent(self.base["id"], cleanup)
        self.assertEqual(self.store.get_agent(b["id"]), {**b, "source_agent_id": None})
        self.assertEqual(self.store.get_session(sb["id"])["agent_id"], b["id"])
        self.assertTrue(Path(b["workspace"]).exists())

    def test_remote_member_uses_target_remote_project_or_explicit_device_directory(
        self,
    ):
        env = self.store.add_environment("Fixture", "fixture-host")
        remote = self.store.add_agent(
            None, "Remote", "claude", environment_id=env["id"]
        )
        before = set(self.store.workspaces.iterdir())
        p = self.store.add_project("Remote project", "/srv/project", env["id"])
        member = self.store.add_project_agent(
            p["id"], {"source_agent_id": remote["id"]}
        )
        session = self.store.add_session(member["id"], "Remote conversation")
        self.assertEqual(
            (session["environment_id"], session["workspace"]),
            (env["id"], "/srv/project"),
        )
        self.assertEqual(set(self.store.workspaces.iterdir()), before)
        with self.assertRaises(Invalid):
            self.store.add_project_agent(
                self.projects[0]["id"], {"source_agent_id": remote["id"]}
            )
        mapped = self.store.add_project_agent(
            self.projects[0]["id"],
            {"source_agent_id": remote["id"], "workspace": "/srv/checkout-a"},
        )
        self.assertEqual(mapped["workspace"], "/srv/checkout-a")
        self.assertEqual(set(self.store.workspaces.iterdir()), before)

    def test_bad_membership_requests_do_not_move_or_mutate_source(self):
        for changes in (
            {},
            {"source_agent_id": self.base["id"], "name": ""},
            {"source_agent_id": self.base["id"], "provider": "claude"},
        ):
            with self.assertRaises(Invalid):
                self.store.add_project_agent(self.projects[0]["id"], changes)
        with self.assertRaises(Missing):
            self.store.add_project_agent(
                "missing", {"source_agent_id": self.base["id"]}
            )
        a, _ = self.members()
        with self.assertRaises(Conflict):
            self.store.update_agent(a["id"], {"project_id": self.projects[1]["id"]})
        self.assertEqual(self.store.get_agent(self.base["id"]), self.base)

    def test_additive_upgrade_preserves_original_records_and_links_survive_restart(
        self,
    ):
        original = self.store.get_session(self.daily["id"])
        # Simulate the immediately preceding schema without the new nullable column.
        self.store.db.execute("ALTER TABLE agents DROP COLUMN source_agent_id")
        self.store.db.execute("PRAGMA user_version=5")
        self.store.close()
        self.store = Store(self.root / "state.sqlite3")
        self.assertEqual(self.store.get_agent(self.base["id"]), self.base)
        self.assertEqual(self.store.get_session(self.daily["id"]), original)
        a, b = self.members()
        self.store.close()
        self.store = Store(self.root / "state.sqlite3")
        self.assertEqual(self.store.get_agent(a["id"]), a)
        self.assertEqual(self.store.get_agent(b["id"]), b)
        self.assertEqual(
            self.store.db.execute("PRAGMA foreign_key_check").fetchall(), []
        )
