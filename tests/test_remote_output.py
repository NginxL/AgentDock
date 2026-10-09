"""Real SSH worker event storage with a fake provider; no CLI or SSH is started."""

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agentdock.event_policy import essential
from agentdock.ssh_worker import atomic, read, work


class RemoteOutputTests(unittest.TestCase):
    def test_accounting_control_and_final_events_survive_both_progress_limits(self):
        critical = [
            (
                "token_usage",
                {
                    "native_id": "fixture",
                    "record_id": "total",
                    "usage": {"input_tokens": 50, "output_tokens": 20},
                },
            ),
            ("account_rate_limit", {"status": "rejected", "resetsAt": 2_000_000_000}),
            ("input_receipt", {"input_id": "input", "status": "applied"}),
            ("input_control", {"turn_id": "turn", "steer": True}),
            ("model_info", {"model": "fixture-model"}),
            ("remote_bind", {"native_id": "fixture"}),
            ("remote_tool", {"name": "task_status"}),
            ("remote_approval", {"request_id": "approval"}),
            ("agent_message", {"phase": "final_answer", "text": "CONCLUSION"}),
        ]
        for count, text in ((5001, "x"), (90, "x" * 100_000)):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                path = root / str(uuid.uuid4()) / str(uuid.uuid4())
                path.mkdir(parents=True)
                (path / "lease").touch()
                atomic(
                    path / "request.json",
                    {
                        "spec": {
                            "provider": "codex",
                            "cwd": str(root),
                            "prompt": "fixture",
                        }
                    },
                )

                def execute(*args, **kwargs):
                    emit = args[7]
                    for _ in range(count):
                        emit("tool_output", {"text": text})
                    for kind, payload in critical:
                        emit(kind, payload)
                    emit("tool_output", {"text": "must be dropped"})
                    return "CONCLUSION"

                with (
                    patch(
                        "agentdock.ssh_worker.commands",
                        return_value={"codex": ["fake"]},
                    ),
                    patch("agentdock.ssh_worker.execute", execute),
                ):
                    work(path)
                events = [
                    json.loads(line)
                    for line in (path / "events.jsonl").read_text().splitlines()
                ]
                self.assertEqual(
                    [(e["kind"], e["payload"]) for e in events[-len(critical) :]],
                    critical,
                )
                self.assertEqual(
                    sum(e["kind"] == "output_truncated" for e in events), 1
                )
                self.assertEqual(read(path / "state.json")["status"], "completed")
                self.assertEqual(read(path / "state.json")["result"], "CONCLUSION")

    def test_progress_and_unrecognized_remote_events_are_not_essential(self):
        for kind, payload in (
            ("tool_output", {}),
            ("agent_message", {"phase": "commentary"}),
            ("usage", {}),
            ("remote_arbitrary", {}),
        ):
            self.assertFalse(essential(kind, payload))
