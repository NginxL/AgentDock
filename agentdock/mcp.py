"""Scoped MCP stdio bridge; credentials stay in process environment, never tool args."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")


def tool(name, description, properties, required=()):
    return dict(
        name=name,
        description=description,
        inputSchema=dict(
            type="object",
            properties=properties,
            required=list(required),
            additionalProperties=False,
        ),
    )


S = {"type": "string"}
TOOLS = [
    tool(
        "agent_list", "List teammates in this run's project. Does not start them.", {}
    ),
    tool(
        "message_send",
        "Dispatch bounded work to a teammate. In a project task only the owner can dispatch, into task-scoped conversations. Choose worker or reviewer. Finish this turn; results return automatically. Use idempotency_key for retries.",
        {
            "recipient_id": S,
            "recipient_session_id": S,
            "body": S,
            "correlation_id": S,
            "idempotency_key": S,
            "task_role": {"type": "string", "enum": ["worker", "reviewer"]},
        },
        ("recipient_id", "body"),
    ),
    tool(
        "task_status",
        "Inspect the execution state and result of a task you sent or received. This does not wait for completion.",
        {"message_id": S},
        ("message_id",),
    ),
    tool(
        "memory_search",
        "Search approved, non-archived project memory using literal keywords.",
        {"query": S},
    ),
    tool(
        "memory_propose",
        "Propose a memory update for human review. Cannot overwrite approved memory. expected_version is zero for a new key.",
        {"key": S, "content": S, "expected_version": {"type": "integer", "minimum": 0}},
        ("key", "content", "expected_version"),
    ),
    tool(
        "task_context",
        "Read this project task: goal, exact acceptance criteria, saved inputs/decisions, workspaces and previous results. No access to other tasks.",
        {},
    ),
    tool(
        "task_history",
        "Read durable task records in order, including full requirements, inputs, decisions and prior reports. Start after=0,offset=0; Read up to 20 records per page; continue with next_after and next_offset until records is empty. The final record may contain partial JSON text.",
        {
            "after": {"type": "integer", "minimum": 0},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
    ),
    tool(
        "task_result",
        "Read a full raw result in this task in pages. Check next_offset; never rely only on truncated handoff text.",
        {"run_id": S, "offset": {"type": "integer", "minimum": 0}},
        ("run_id",),
    ),
    tool(
        "task_ask",
        "Save a question that needs a human decision. Finish your turn after asking. Answers persist and resume the task owner automatically.",
        {"question": S, "options": {"type": "array", "items": S, "maxItems": 8}},
        ("question",),
    ),
    tool(
        "task_deliver",
        "Task owner submits a delivery. Cover every exact acceptance criterion once, with honest validation evidence. Finishing a native turn alone does not accept the task.",
        {
            "summary": S,
            "checks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion": S,
                        "status": {
                            "type": "string",
                            "enum": ["passed", "failed", "unverified"],
                        },
                        "evidence": S,
                    },
                    "required": ["criterion", "status", "evidence"],
                    "additionalProperties": False,
                },
            },
            "artifacts": {"type": "array", "items": S, "maxItems": 30},
            "risks": S,
        },
        ("summary", "checks"),
    ),
    tool(
        "task_review",
        "Independent reviewer records its verdict on the owner workspace and current requirements. Report findings honestly; unverified or changes_requested blocks required review acceptance.",
        {
            "verdict": {
                "type": "string",
                "enum": ["approved", "changes_requested", "unverified"],
            },
            "summary": S,
        },
        ("verdict", "summary"),
    ),
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Bridge:
    def __init__(self, call):
        self.call = call
        self.initialized = False

    def handle(self, message):
        if not isinstance(message, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid request"},
            }
        identifier = message.get("id")
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return {
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32600, "message": "Invalid request"},
            }
        if "id" not in message:
            return None
        try:
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("Invalid parameters")
            if method == "initialize":
                requested = params.get("protocolVersion")
                self.initialized = True
                result = {
                    "protocolVersion": requested
                    if requested in PROTOCOLS
                    else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "agentdock", "version": "0.3.0"},
                }
            elif not self.initialized:
                raise ValueError("Initialize first")
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments", {})
                definition = next((t for t in TOOLS if t["name"] == name), None)
                if definition is None:
                    raise ValueError("Unknown tool")
                schema = definition["inputSchema"]
                if (
                    not isinstance(args, dict)
                    or set(args) - set(schema["properties"])
                    or any(x not in args for x in schema["required"])
                ):
                    raise ValueError("Invalid tool arguments")
                try:
                    value = self.call(name, args)
                    result = {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(value, ensure_ascii=False),
                            }
                        ],
                        "isError": False,
                    }
                except Exception:
                    result = {
                        "content": [
                            {
                                "type": "text",
                                "text": "Tool request rejected or unavailable. Check the workbench; no action should be assumed successful.",
                            }
                        ],
                        "isError": True,
                    }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            return {"jsonrpc": "2.0", "id": identifier, "result": result}
        except (ValueError, TypeError):
            return {
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32602, "message": "Invalid parameters or lifecycle"},
            }


def main():
    address = os.environ.get("AGENTDOCK_URL", "")
    parsed = urllib.parse.urlsplit(address)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        print("AgentDock MCP requires an explicit loopback address", file=sys.stderr)
        return 2
    token = os.environ.get("AGENTDOCK_CAPABILITY", "")
    if not token:
        print("AgentDock MCP requires a run capability", file=sys.stderr)
        return 2
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def invoke(name, args):
        req = urllib.request.Request(
            address.rstrip("/") + "/mcp/tool",
            data=json.dumps({"name": name, "arguments": args}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
            method="POST",
        )
        with opener.open(req, timeout=15) as response:
            data = response.read(1048577)
            if len(data) > 1048576:
                raise ValueError("Response too large")
            return json.loads(data)

    bridge = Bridge(invoke)
    while True:
        raw = sys.stdin.buffer.readline(262145)
        if not raw:
            break
        if len(raw) > 262144:
            print("MCP input exceeds limit", file=sys.stderr)
            return 2
        try:
            message = json.loads(raw)
        except (ValueError, UnicodeError):
            result = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            result = bridge.handle(message)
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
