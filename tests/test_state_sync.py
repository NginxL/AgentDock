import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agentdock.metrics import LocalUsage, cached_activity
from agentdock.store import Store


class StateSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_delta_contains_only_committed_domains_and_restart_resets_cursor(self):
        initial = self.store.state()
        agent = self.store.add_agent(None, "Fixture", "codex")
        changed = self.store.state(initial["version"])
        self.assertTrue(changed["partial"])
        self.assertEqual([a["id"] for a in changed["agents"]], [agent["id"]])
        self.assertNotIn("memories", changed)
        self.assertEqual(
            self.store.state(changed["version"]),
            {"version": changed["version"], "partial": True},
        )
        with self.assertRaises(ValueError):
            with self.store.transaction():
                self.store.db.execute("UPDATE agents SET name='Rolled back'")
                raise ValueError("rollback")
        self.assertEqual(self.store.state_version(), changed["version"])
        self.store.close()
        self.store = Store(self.root / "state.sqlite3")
        restored = self.store.state(changed["version"])
        self.assertFalse(restored["partial"])
        self.assertEqual(restored["agents"][0]["name"], "Fixture")

    def test_slow_snapshot_does_not_block_writer_and_is_consistent_read_only(self):
        agent = self.store.add_agent(None, "Before", "codex")
        ready, done = threading.Event(), threading.Event()

        def write():
            ready.wait()
            self.store.update_agent(agent["id"], {"name": "After"})
            done.set()

        writer = threading.Thread(target=write)
        writer.start()
        with self.store.reader() as reader:
            ready.set()
            self.assertTrue(done.wait(1), "A read snapshot blocked a writer")
            self.assertEqual(reader.get_agent(agent["id"])["name"], "Before")
            with self.assertRaises(sqlite3.OperationalError):
                reader.db.execute("DELETE FROM agents")
        writer.join(1)
        self.assertEqual(self.store.get_agent(agent["id"])["name"], "After")

    def test_event_wakes_only_its_session_and_not_global_feed(self):
        agent = self.store.add_agent(None, "Fixture", "codex")
        first = self.store.add_session(agent["id"], "One")
        second = self.store.add_session(agent["id"], "Two")
        one, two = Mock(), Mock()
        self.store._session_conditions.update({first["id"]: one, second["id"]: two})
        version = self.store.state_version()
        self.store.append_event(None, first["id"], "tool_output", {"text": "fixture"})
        one.notify_all.assert_called_once()
        two.notify_all.assert_not_called()
        self.assertEqual(self.store.state_version(), version)

    def test_heatmap_cached_for_minute_across_read_connections(self):
        with patch(
            "agentdock.metrics.daily_activity", return_value={"days": []}
        ) as calculate:
            for stamp in (120, 121, 179):
                with self.store.reader() as reader:
                    cached_activity(reader, stamp)
            self.assertEqual(calculate.call_count, 1)
            with self.store.reader() as reader:
                cached_activity(reader, 180)
            self.assertEqual(calculate.call_count, 2)
            self.store.add_agent(None, "Changed binding", "codex")
            with self.store.reader() as reader:
                cached_activity(reader, 181)
            self.assertEqual(calculate.call_count, 3)

    def test_scanner_skips_unrelated_codex_names_without_opening_files(self):
        agent = self.store.add_agent(None, "Fixture", "codex")
        session = self.store.add_session(agent["id"], "One")
        self.store.bind_native_session(
            session["id"], "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
        )
        folder = self.root / ".codex/sessions"
        folder.mkdir(parents=True)
        (
            folder / "rollout-2026-10-01-cccccccc-1111-2222-3333-dddddddddddd.jsonl"
        ).write_text("unrelated")
        with patch.object(
            Path, "open", side_effect=AssertionError("Unrelated transcript was opened")
        ):
            LocalUsage(self.store, self.root).scan()
