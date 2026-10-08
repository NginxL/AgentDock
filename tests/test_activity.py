import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agentdock.metrics import LocalUsage, daily_activity, normalize, record
from agentdock.store import Store


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "state.sqlite3")
        self.today = (
            datetime.now()
            .astimezone()
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def event(self, day, inp, out):
        return {
            "type": "event_msg",
            "timestamp": (self.today + timedelta(days=day, hours=1)).isoformat(),
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {"input_tokens": inp, "output_tokens": out}
                },
            },
        }

    def log(self, events):
        if not self.store.usage_bindings():
            a = self.store.add_agent(None, "A", "codex")
            session = self.store.add_session(a["id"], "S")
            self.store.bind_native_session(session["id"], "native")
        path = self.root / ".codex/sessions/log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                json.dumps(e)
                for e in [{"type": "session_meta", "payload": {"id": "native"}}]
                + events
            )
            + "\n"
        )
        return path

    def days(self):
        return {
            r["date"]: r["tokens"]
            for r in daily_activity(self.store, self.today.timestamp())["days"]
        }

    def date(self, day):
        return (self.today + timedelta(days=day)).date().isoformat()

    def test_codex_daily_deltas_do_not_recount_cumulative_usage_or_archived_copies(
        self,
    ):
        path = self.log(
            [self.event(-3, 100, 10), self.event(-3, 200, 20), self.event(-2, 250, 30)]
        )
        scan = LocalUsage(self.store, self.root)
        scan.scan()
        self.assertEqual(self.days(), {self.date(-3): 220, self.date(-2): 60})
        archive = self.root / ".codex/archived_sessions/copy.jsonl"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(path.read_bytes())
        with path.open("a") as stream:
            stream.write(json.dumps(self.event(-1, 300, 35)) + "\n")
        scan.scan()
        scan.scan()
        self.assertEqual(
            self.days(), {self.date(-3): 220, self.date(-2): 60, self.date(-1): 55}
        )

    def test_backfill_is_resumable_and_keeps_the_baseline_before_the_visible_year(self):
        self.log(
            [
                self.event(-370, 500, 50),
                self.event(-2, 600, 65),
                self.event(-1, 620, 75),
            ]
        )
        scan = LocalUsage(self.store, self.root)
        scan.ACTIVITY_CHUNK = scan.ACTIVITY_BUDGET = 150
        scan.scan()
        self.assertTrue(scan.activity_pending)
        self.store.close()
        self.store = Store(self.root / "state.sqlite3")
        scan = LocalUsage(self.store, self.root)
        scan.scan()
        self.assertFalse(scan.activity_pending)
        self.assertEqual(self.days(), {self.date(-2): 115, self.date(-1): 30})

    def test_partial_tail_recovers_and_rotation_does_not_duplicate_days(self):
        path = self.log([self.event(-2, 10, 2)])
        next_line = json.dumps(self.event(-1, 30, 4)) + "\n"
        with path.open("a") as stream:
            stream.write(next_line[:40])
        scan = LocalUsage(self.store, self.root)
        scan.scan()
        self.assertEqual(self.days(), {self.date(-2): 12})
        with path.open("a") as stream:
            stream.write(next_line[40:])
        scan.scan()
        expected = {self.date(-2): 12, self.date(-1): 22}
        self.assertEqual(self.days(), expected)
        content = path.read_text()
        path.unlink()
        path.write_text(content)
        scan.scan()
        self.assertEqual(self.days(), expected)

    def test_claude_message_dedup_and_cache_counts_use_the_local_calendar(self):
        a = self.store.add_agent(None, "A", "claude")
        session = self.store.add_session(a["id"], "S")
        self.store.bind_native_session(session["id"], "c")
        usage = normalize(
            "claude",
            {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 20,
                "cache_creation_input_tokens": 30,
            },
        )
        stamp = (self.today - timedelta(days=1) + timedelta(seconds=1)).timestamp()
        for source in ("managed", "local", "local"):
            record(self.store, "claude", "c", "message", usage, stamp, source)
        record(
            self.store,
            "claude",
            "c",
            "second",
            normalize("claude", {"input_tokens": 1, "output_tokens": 2}),
            stamp - 2,
            "local",
        )
        self.assertEqual(self.days(), {self.date(-2): 3, self.date(-1): 65})

    def test_empty_history_has_no_invented_activity(self):
        self.assertEqual(
            daily_activity(self.store, self.today.timestamp()),
            {"today": self.date(0), "days": [], "updated_at": None},
        )
