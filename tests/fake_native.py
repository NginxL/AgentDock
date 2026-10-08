"""A deterministic native-protocol peer. Never contacts a model or real CLI."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

provider, scenario = sys.argv[1:3]
args = sys.argv[3:]
Path("fake-pid").write_text(str(os.getpid()))


def send(value):
    print(json.dumps(value), flush=True)


def read():
    value = json.loads(sys.stdin.readline())
    with open("fake-contract.jsonl", "a") as output:
        output.write(json.dumps(value) + "\n")
    return value


def shared_tool():
    if scenario != 'mcp': return
    import urllib.request
    request = urllib.request.Request(os.environ['AGENTDOCK_URL']+'/mcp/tool',
        data=json.dumps({'name':'memory_search','arguments':{'query':'fixture'}}).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['AGENTDOCK_CAPABILITY']})
    with urllib.request.urlopen(request,timeout=10) as response:
        Path('fake-tool-result.json').write_bytes(response.read())


def hang():
    if scenario == "descendant":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        Path("fake-child-pid").write_text(str(child.pid))
    while True:
        time.sleep(1)


with open("fake-argv.json", "w") as output:
    json.dump(args, output)

if scenario in ("hang", "descendant"):
    hang()
if scenario == "invalid_json":
    print("not json -- private-token", flush=True)
    raise SystemExit(0)
if scenario == "huge_line":
    print("x" * 524289, flush=True)
    raise SystemExit(0)
if scenario == "huge_stderr":
    sys.stderr.write("x" * 8388609)
    sys.stderr.flush()
    hang()
if scenario == "early_exit":
    sys.stderr.write("private-token authentication failed")
    raise SystemExit(42)
if scenario == "partial":
    sys.stdout.write('{"private":"private-token"')
    sys.stdout.flush()
    raise SystemExit(1)

if provider == "codex":
    assert args[-2:] == ["--listen", "stdio://"]
    request = read()
    assert request["method"] == "initialize"
    assert request["params"]["capabilities"]["experimentalApi"] is False
    if scenario == "protocol_error":
        send({"id": request["id"], "error": {"code": -1, "message": "private-token"}})
        hang()
    send({"id": request["id"], "result": {"userAgent": "fake-codex"}})
    assert read()["method"] == "initialized"
    request = read()
    assert request["method"] in ("thread/start", "thread/resume")
    params = request["params"]
    assert params.get("excludeTurns") is True if request["method"] == "thread/resume" else "excludeTurns" not in params
    assert params["approvalPolicy"] == ("never" if scenario in ("full_access","read_only") else "untrusted")
    assert params["sandbox"] == ("danger-full-access" if scenario == "full_access" else "read-only" if scenario=='read_only' else "workspace-write")
    assert params["approvalsReviewer"] == "user"
    mcp = params["config"]["mcp_servers"]["agentdock"]
    assert "AGENTDOCK_CAPABILITY" in mcp["env_vars"]
    assert "private-token" not in json.dumps(request)
    native_id = params.get("threadId", "native-codex-1")
    if scenario == "resume_mismatch":
        native_id = "different-native-thread"
    send({"id": request["id"], "result": {"thread": {"id": native_id}, "cwd": "/different-workspace" if scenario == "wrong_cwd" else os.getcwd(),
        **({'model':'gateway/configured-model', 'modelProvider':'custom-relay', 'reasoningEffort':'xhigh'} if scenario == 'metadata' else {})}})
    request = read()
    assert request["method"] == "turn/start"
    assert request["params"]["threadId"] == native_id
    assert request["params"]["approvalPolicy"] == ("never" if scenario in ("full_access","read_only") else "untrusted")
    send({"id": request["id"], "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
    if scenario in ('steer','steer_reject','steer_mismatch'):
        adjustment=read()
        assert adjustment['method']=='turn/steer'
        assert adjustment['params']['expectedTurnId']=='turn-1'
        assert adjustment['params']['threadId']==native_id
        assert adjustment['params']['input']==[{'type':'text','text':'Use JSON'}]
        if scenario=='steer_reject': send({'id':adjustment['id'],'error':{'code':-1,'message':'turn unavailable'}})
        else: send({'id':adjustment['id'],'result':{'turnId':'other-turn' if scenario=='steer_mismatch' else 'turn-1'}})
    if scenario in ("permission", "permission_slow", "permissions", "duplicate_permission"):
        method = "item/permissions/requestApproval" if scenario == "permissions" else "item/commandExecution/requestApproval"
        params = {"threadId": native_id, "turnId": "turn-1", "itemId": "tool-1", "command": "touch reviewed-file", "cwd": os.getcwd()}
        if scenario == "permissions":
            params["permissions"] = {"network": {"enabled": True}}
        send({"id": "permission-1", "method": method, "params": params})
        response = read()
        assert response["id"] == "permission-1"
        if scenario == "duplicate_permission":
            send({"id": "permission-1", "method": method, "params": params})
            hang()
    shared_tool()
    if scenario == "usage":
        assert request["params"]["model"] == "fixture-model"
        assert request["params"]["effort"] == "high"
        usage = {"inputTokens": 10, "outputTokens": 5, "cachedInputTokens": 4}
        send({"method": "thread/tokenUsage/updated", "params": {"threadId": native_id, "turnId": "turn-1", "tokenUsage": {"total": usage, "last": usage}}})
    if scenario in ("progress", "unphased", "commentary_only"):
        assert request["params"]["summary"] == "auto"
        base = {"threadId":native_id,"turnId":"turn-1"}
        send({"method":"item/reasoning/summaryTextDelta","params":{**base,"itemId":"thought-1","summaryIndex":0,"delta":"Inspect "}})
        send({"method":"item/reasoning/summaryTextDelta","params":{**base,"itemId":"thought-1","summaryIndex":0,"delta":"private-token"}})
        send({"method":"item/completed","params":{**base,"item":{"type":"reasoning","id":"thought-1","summary":["Inspect private-token"],"content":["do not forward encrypted/raw reasoning"]}}})
        send({"method":"item/started","params":{**base,"item":{"type":"commandExecution","id":"tool-1","command":"pwd","status":"inProgress"}}})
        send({"method":"item/commandExecution/outputDelta","params":{**base,"itemId":"tool-1","delta":"/fixture/workspace"}})
        send({"method":"item/completed","params":{**base,"item":{"type":"commandExecution","id":"tool-1","command":"pwd","status":"completed","exitCode":0,"aggregatedOutput":"/fixture/workspace"}}})
        send({"method":"item/completed","params":{**base,"item":{"type":"agentMessage","id":"commentary-1","text":"Working on the task",
            **({} if scenario == "unphased" else {"phase":"commentary"})}}})
    params = {"threadId": "wrong-thread" if scenario == "wrong_session" else native_id,
              "turnId": "wrong-turn" if scenario == "wrong_turn" else "turn-1", "itemId": "answer-1", "delta": "hello "}
    phase = {} if scenario == "unphased" else {"phase": "commentary" if scenario == "commentary_only" else "final_answer"}
    send({"method": "item/started", "params": {"threadId": native_id, "turnId": "turn-1", "item": {
        "id": "answer-1", "type": "agentMessage", "text": "", **phase}}})
    send({"method": "item/agentMessage/delta", "params": params})
    params["delta"] = os.environ.get("AGENTDOCK_CAPABILITY", "missing") if scenario == "redact" else "world"
    send({"method": "item/agentMessage/delta", "params": params})
    send({"method": "item/completed", "params": {"threadId": native_id, "turnId": "turn-1", "item": {
        "id": "answer-1", "type": "agentMessage", "text": "hello " + params["delta"]}}})
    send({"method": "turn/completed", "params": {"threadId": native_id, "turn": {
        "id": "turn-1", "status": "failed" if scenario == "failed" else "completed",
        "error": {"message": "private-token"} if scenario == "failed" else None}}})
    hang()
else:
    assert os.environ.get("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS") == "1"
    assert "--dangerously-skip-permissions" not in args
    assert args[args.index("--permission-mode") + 1] == ("bypassPermissions" if scenario == "full_access" else "plan" if scenario=='read_only' else "manual")
    assert args[args.index("--permission-prompt-tool") + 1] == "stdio"
    assert "--strict-mcp-config" in args
    assert "private-token" not in " ".join(args)
    native_id = (next((a.split("=", 1)[1] for a in args if a.startswith("--resume=")), None)
                 or args[args.index("--session-id") + 1])
    request = read()
    assert request["type"] == "control_request" and request["request"]["subtype"] == "initialize"
    send({"type": "control_response", "response": {
        "subtype": "error" if scenario == "protocol_error" else "success",
        "request_id": request["request_id"], "response": {}, "error": "private-token"}})
    request = read()
    assert request["type"] == "user" and request["session_id"] == native_id
    if scenario == "wrong_session":
        native_id = "e0c5852b-f3ac-4115-8e03-5de5f76127f0"
    send({"type": "system", "subtype": "init", "session_id": native_id})
    shared_tool()
    if scenario in ("permission", "permission_slow", "duplicate_permission"):
        permission = {"type": "control_request", "request_id": "permission-1", "request": {
            "subtype": "can_use_tool", "tool_name": "Write", "input": {"file_path": "/tmp/reviewed-file", "content": "approved input"},
            "tool_use_id": "tool-1"}}
        send(permission)
        response = read()
        assert response["type"] == "control_response" and response["response"]["request_id"] == "permission-1"
        if response["response"]["response"]["behavior"] == "allow":
            assert response["response"]["response"]["updatedInput"] == permission["request"]["input"]
        if scenario == "duplicate_permission":
            send(permission)
            hang()
    if scenario == "unphased":
        send({"type": "assistant", "session_id": native_id, "message": {"id": "progress-1", "content": [
            {"type": "text", "text": "Working on the task"}]}})
    send({"type": "stream_event", "session_id": native_id, "event": {"type": "message_start", "message": {"id": "answer-1"}}})
    if scenario == "progress":
        send({"type":"stream_event","session_id":native_id,"event":{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"Inspect private-token"}}})
        send({"type":"stream_event","session_id":native_id,"event":{"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"do not forward signatures"}}})
        send({"type":"assistant","session_id":native_id,"message":{"content":[{"type":"thinking","thinking":"Inspect private-token","signature":"do not forward signatures"}]}})
        tool = {"type":"tool_use","id":"tool-1","name":"Read","input":{"file_path":"/fixture/file"}}
        send({"type":"stream_event","session_id":native_id,"event":{"type":"content_block_start","content_block":tool}})
        send({"type":"assistant","session_id":native_id,"message":{"content":[tool]}})
        send({"type":"user","session_id":native_id,"message":{"content":[{"type":"tool_result","tool_use_id":"tool-1","content":"fixture content"}]}})
    for text in ("hello ", os.environ.get("AGENTDOCK_CAPABILITY", "missing") if scenario == "redact" else "world"):
        send({"type": "stream_event", "session_id": native_id, "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}})
    result = "hello " + text
    if scenario == "unphased":
        send({"type": "stream_event", "session_id": native_id, "event": {
            "type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Second paragraph"}}})
    send({"type": "assistant", "session_id": native_id, "message": {"id": "answer-1", "content": [
        {"type": "text", "text": result}, *([{"type": "text", "text": "Second paragraph"}] if scenario == "unphased" else [])]}})
    send({"type": "result", "session_id": native_id, "subtype": "success", "is_error": scenario == "failed",
          **({} if scenario == "unphased" else {"result": "private-token" if scenario == "failed" else result})})
    hang()
