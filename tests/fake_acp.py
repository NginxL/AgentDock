"""Offline protocol fixture. It never contacts a model, reads credentials or runs tools."""
import json
import sys
import time
import subprocess

scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"


def send(message):
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"id": message["id"], "result": {"protocolVersion": 9 if scenario == "version" else 1,
                                              "agentCapabilities": {}}})
    elif method == "session/new":
        assert message["params"]["mcpServers"][0]["args"] == ["-m", "agentdock.mcp"]
        assert {item["name"] for item in message["params"]["mcpServers"][0]["env"]} >= {
            "AGENTDOCK_URL", "AGENTDOCK_CAPABILITY"}
        send({"id": message["id"], "result": {"sessionId": "fixture-session"}})
    elif method == "session/prompt":
        prompt_id = message["id"]
        if scenario == "crash":
            print("private-debug-secret", file=sys.stderr)
            sys.exit(7)
        if scenario == "hang":
            time.sleep(60)
        if scenario == "child":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            send({"method": "session/update", "params": {
                "sessionId": "fixture-session", "update": {"sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "child-pid:" + str(child.pid)}}}})
            time.sleep(60)
        if scenario == "invalid":
            print("not-json", flush=True)
            time.sleep(60)
        if scenario == "flood":
            print("x" * 600000, flush=True)
            time.sleep(60)
        if scenario == "permission":
            send({"id": "permission-1", "method": "session/request_permission", "params": {
                "sessionId": "fixture-session", "toolCall": {"toolCallId": "fake-tool", "title": "Fake action"},
                "options": [{"optionId": "allow", "name": "Allow once", "kind": "allow_once"},
                            {"optionId": "deny", "name": "Reject once", "kind": "reject_once"}]}})
        else:
            send({"method": "session/update", "params": {
                "sessionId": "wrong-session" if scenario == "wrong-session" else "fixture-session",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {
                    "type": "text", "text": message["params"]["prompt"][0]["text"]}}}})
            send({"id": prompt_id, "result": {"stopReason": "end_turn"}})
    elif message.get("id") == "permission-1":
        send({"method": "session/update", "params": {
            "sessionId": "fixture-session", "update": {"sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": json.dumps(message["result"]["outcome"])}}}})
        send({"id": prompt_id, "result": {"stopReason": "end_turn"}})
