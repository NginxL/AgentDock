"""Deterministic ACP peer: exercises real pipes, no provider or network access."""

import json
import os
import sys
import time
from pathlib import Path

scenario = sys.argv[1]
session = "fixture-session"
config = [
    {
        "id": "model",
        "category": "model",
        "type": "select",
        "currentValue": "fixture-model",
        "options": [
            {
                "group": "models",
                "name": "Models",
                "options": [{"value": "fixture-model", "name": "Fixture model"}],
            }
        ],
    },
    {
        "id": "effort",
        "category": "thought_level",
        "type": "select",
        "currentValue": "high",
        "options": [{"value": "high", "name": "High"}],
    },
]


def send(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)


def update(kind, **values):
    send(
        {
            "method": "session/update",
            "params": {
                "sessionId": session,
                "update": {"sessionUpdate": kind, **values},
            },
        }
    )


def read():
    return json.loads(sys.stdin.readline())


for line in sys.stdin:
    request = json.loads(line)
    method, params = request.get("method"), request.get("params", {})
    result = {}
    if method == "initialize":
        assert request["params"]["clientCapabilities"]["terminal"] is False
        result = {
            "protocolVersion": 1,
            "agentCapabilities": {"loadSession": scenario != "no_resume"},
        }
        if scenario == "version":
            result["protocolVersion"] = 999
    elif method in ("session/new", "session/load", "session/resume"):
        assert os.path.isabs(params["cwd"])
        if method != "session/new":
            assert params["sessionId"] == session
            update(
                "agent_message_chunk",
                content={"type": "text", "text": "Replayed OLD answer"},
            )
            send(
                {
                    "id": 999,
                    "method": "session/request_permission",
                    "params": {
                        "sessionId": session,
                        "toolCall": {"title": "old permission"},
                        "options": [
                            {"optionId": "allow", "name": "Allow", "kind": "allow_once"}
                        ],
                    },
                }
            )
            assert read()["result"]["outcome"]["outcome"] == "cancelled"
        result = {"sessionId": session, "configOptions": config}
        if scenario == "read_only":
            result["modes"] = {"availableModes": [{"id": "plan", "name": "Plan"}]}
        (Path.home() / "private-session.json").write_text(session)
    elif method == "session/set_mode":
        assert scenario == "read_only" and params["modeId"] == "plan"
        (Path.home() / "plan-mode").write_text("enabled")
    elif method == "session/set_config_option":
        assert params["value"] in ("fixture-model", "high")
        result = {"configOptions": config}
    elif method == "session/prompt":
        if scenario == "read_only":
            assert (Path.home() / "plan-mode").exists()
        if scenario == "hang":
            time.sleep(30)
        if scenario == "foreign":
            send(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": "other-session",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "wrong"},
                        },
                    },
                }
            )
        if scenario == "error":
            send(
                {
                    "id": request["id"],
                    "error": {"code": -32010, "message": "private-token"},
                }
            )
            continue
        update(
            "agent_thought_chunk", content={"type": "text", "text": "Checking the file"}
        )
        update(
            "agent_message_chunk",
            content={"type": "text", "text": "Let me inspect it."},
        )
        update("tool_call", toolCallId="tool-1", title="Read file", status="pending")
        if scenario in ("permission", "full_access", "unknown_option"):
            send(
                {
                    "id": 100,
                    "method": "session/request_permission",
                    "params": {
                        "sessionId": session,
                        "toolCall": {"title": "Read file"},
                        "options": [
                            {"optionId": "one", "name": "Allow", "kind": "allow_once"},
                            {"optionId": "deny", "name": "Deny", "kind": "reject_once"},
                        ],
                    },
                }
            )
            assert read()["result"]["outcome"]["optionId"] in ("one", "deny")
        if scenario == "unsupported":
            send(
                {
                    "id": 101,
                    "method": "fs/write_text_file",
                    "params": {"path": "/must-not-write", "content": "unsafe"},
                }
            )
            assert read()["error"]["code"] == -32601
        update(
            "tool_call_update",
            toolCallId="tool-1",
            status="completed",
            content=[
                {"type": "content", "content": {"type": "text", "text": "Tool output"}}
            ],
        )
        update("usage_update", used=50000, size=200000)
        update("agent_message_chunk", content={"type": "text", "text": "Final "})
        answer = "answer"
        if scenario == "quoted_final":
            answer = (
                '{"id": "a1", "name": "item", "tags": ["x", "y"]}\n' * 2400
                + "CONCLUSION"
            )
        elif scenario == "control_final":
            answer = "\x01" * 60000 + "CONCLUSION"
        update("agent_message_chunk", content={"type": "text", "text": answer})
        result = {
            "stopReason": "max_tokens" if scenario == "incomplete" else "end_turn"
        }
    elif method == "session/cancel":
        break
    else:
        raise AssertionError(method)
    send({"id": request["id"], "result": result})
