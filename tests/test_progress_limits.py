import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agentdock.runtime import Runtime, _Run
from agentdock.ssh_worker import atomic, read, work
from agentdock.store import Store


class ProgressLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.root / "state.sqlite3")
        self.addCleanup(self.store.close)
        self.runtime = Runtime(self.store, {"execution_enabled": True, "commands": {}})
        self.addCleanup(self.runtime.close)

    def new_run(self):
        agent = self.store.add_agent(None, "Fixture", "claude")
        session = self.store.add_session(agent["id"], "Fixture")
        return _Run(
            self.store.begin_run(session["id"], "Fixture"), "private-capability"
        )

    def test_one_oversized_event_does_not_suppress_later_local_progress(self):
        for length in (150_000, 9_000_000):
            with self.subTest(length=length):
                run = self.new_run()
                self.runtime._event(
                    run,
                    "tool_result",
                    {"provider": "claude", "item": {"content": "x" * length}},
                )
                self.runtime._event(run, "tool_call", {"item": {"name": "Edit"}})
                self.runtime._event(
                    run,
                    "agent_message_chunk",
                    {"content": {"text": "Now fixing the bug"}},
                )
                events = self.store.session_events(run.record["session_id"])[-3:]
                self.assertEqual(
                    [e["kind"] for e in events],
                    ["output_truncated", "tool_call", "agent_message_chunk"],
                )
                self.assertEqual(events[0]["payload"]["scope"], "event")
                self.assertFalse(run.output_truncated)
                self.assertEqual(run.event_count, 3)
                self.assertLess(run.output_bytes, 1000)

    def test_only_cumulative_limits_latch_and_final_messages_still_arrive(self):
        for counts in ({"event_count": 5000}, {"output_bytes": 8 * 1024 * 1024 - 1}):
            with self.subTest(counts=counts):
                run = self.new_run()
                for key, value in counts.items():
                    setattr(run, key, value)
                self.runtime._event(run, "tool_output", {"text": "last progress"})
                self.runtime._event(run, "tool_call", {"item": {"name": "Edit"}})
                self.runtime._event(
                    run, "assistant_message", {"text": "Final conclusion"}
                )
                events = self.store.session_events(run.record["session_id"])[-2:]
                self.assertEqual(
                    [e["kind"] for e in events],
                    ["output_truncated", "assistant_message"],
                )
                self.assertEqual(events[0]["payload"]["scope"], "run")
                self.assertTrue(run.output_truncated)

    def test_one_oversized_event_does_not_suppress_later_remote_progress(self):
        for length in (310_000, 9_000_000):
            with self.subTest(length=length):
                path = self.root / str(uuid.uuid4()) / str(uuid.uuid4())
                path.mkdir(parents=True)
                (path / "lease").touch()
                atomic(
                    path / "request.json",
                    {
                        "spec": {
                            "provider": "claude",
                            "cwd": str(self.root),
                            "prompt": "Fixture",
                        }
                    },
                )

                def execute(*args, **kwargs):
                    emit = args[7]
                    emit("tool_result", {"item": {"content": "x" * length}})
                    emit("tool_call", {"item": {"name": "Edit"}})
                    emit(
                        "agent_message_chunk",
                        {"content": {"text": "Now fixing the bug"}},
                    )
                    return "Final conclusion"

                with (
                    patch("agentdock.ssh_worker.execute", execute),
                    patch(
                        "agentdock.ssh_worker.commands",
                        return_value={"claude": ["fixture"]},
                    ),
                ):
                    work(path)
                events = [
                    json.loads(line)
                    for line in (path / "events.jsonl").read_text().splitlines()
                ]
                self.assertEqual(
                    [e["kind"] for e in events],
                    ["output_truncated", "tool_call", "agent_message_chunk"],
                )
                self.assertEqual(events[0]["payload"]["scope"], "event")
                self.assertEqual(read(path / "state.json")["status"], "completed")
