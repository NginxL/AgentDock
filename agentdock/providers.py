"""Bounded native CLI transports. Importing this module does not start a process.

Codex uses app-server's public JSON-RPC protocol. Claude uses its native CLI's
stream-json control protocol; no agent SDK, credential export, or API client is
used. Callers must only pass session IDs previously bound by this application.
"""
from __future__ import annotations

from collections import deque
import json
import math
import os
import re
import selectors
import subprocess
import threading
import time
import uuid

from .metrics import normalize
from .processes import stop_group as _stop_group
from .registry import PROVIDERS, ACP_PROVIDERS


class ProviderError(Exception):
    """A safe, stable diagnostic; never contains raw provider stderr or errors."""


class ProviderCancelled(Exception):
    pass


_MAX_LINE = 524288
_MAX_OUTPUT = 8388608
_MAX_EVENTS = 10000
_MAX_RESULT = 262144
_MAX_APPROVALS = 64


def _identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value))


def _validate_mcp(config):
    if (not isinstance(config, dict) or not isinstance(config.get("command"), str)
            or not config["command"] or "\x00" in config["command"]):
        raise ProviderError("The configured AgentDock MCP command is invalid.")
    args, env = config.get("args", []), config.get("env", {})
    if (not isinstance(args, list) or any(not isinstance(v, str) or "\x00" in v for v in args)
            or not isinstance(env, dict) or any(not isinstance(k, str) or not k
                or "=" in k or "\x00" in k or not isinstance(v, str) or "\x00" in v
                for k, v in env.items())):
        raise ProviderError("The configured AgentDock MCP arguments are invalid.")
    return {"command": config["command"], "args": list(args)}, dict(env)


class _Pipe:
    """One worker owns pipe IO. Stderr is bounded and drained, never recorded."""
    def __init__(self, command, cwd, env, stop, timeout):
        self.stop = stop
        self.deadline = time.monotonic() + timeout
        self.process = None
        self.selector = selectors.DefaultSelector()
        self.buffer, self.writes = bytearray(), bytearray()
        self.messages = deque()
        self.total = self.count = 0
        self.stdout_open = True
        self.check()
        try:
            self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            start_new_session=True, bufsize=0)
            for stream, name in ((self.process.stdout, "stdout"), (self.process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                self.selector.register(stream, selectors.EVENT_READ, name)
            os.set_blocking(self.process.stdin.fileno(), False)
        except Exception:
            self.close()
            raise ProviderError("Could not start the configured native CLI. Check its installation and configuration.") from None

    def check(self):
        if self.stop.is_set():
            raise ProviderCancelled()
        if time.monotonic() >= self.deadline:
            raise ProviderError("Agent run timed out and its processes were stopped.")

    def send(self, message):
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > _MAX_LINE or len(self.writes) + len(encoded) > _MAX_LINE * 2:
            raise ProviderError("Native CLI request exceeded the size limit.")
        self.writes.extend(encoded)
        try:
            self.selector.get_key(self.process.stdin)
        except KeyError:
            self.selector.register(self.process.stdin, selectors.EVENT_WRITE, "stdin")

    def next(self):
        while True:
            self.check()
            if self.messages:
                return self.messages.popleft()
            if not self.stdout_open:
                raise ProviderError("Native CLI exited before the turn completed. Check CLI login and compatibility.")
            for key, _ in self.selector.select(timeout=0.05):
                if key.data == "stdin":
                    try:
                        count = os.write(key.fd, self.writes)
                    except BlockingIOError:
                        continue
                    except (BrokenPipeError, OSError):
                        raise ProviderError("Native CLI closed its input unexpectedly.") from None
                    del self.writes[:count]
                    if not self.writes:
                        self.selector.unregister(key.fileobj)
                    continue
                try:
                    data = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not data:
                    self.selector.unregister(key.fileobj)
                    if key.data == "stdout":
                        self.stdout_open = False
                        if self.buffer:
                            raise ProviderError("Native CLI ended with an incomplete protocol message.")
                    continue
                self.total += len(data)
                if self.total > _MAX_OUTPUT:
                    raise ProviderError("Native CLI exceeded the bounded output limit.")
                if key.data == "stderr":
                    continue
                self.buffer.extend(data)
                while b"\n" in self.buffer:
                    line, _, tail = self.buffer.partition(b"\n")
                    self.buffer = bytearray(tail)
                    if len(line) > _MAX_LINE:
                        raise ProviderError("Native CLI message exceeded the line limit.")
                    try:
                        message = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise ProviderError("Native CLI emitted invalid JSON.") from None
                    if not isinstance(message, dict):
                        raise ProviderError("Native CLI emitted an invalid protocol message.")
                    self.count += 1
                    if self.count > _MAX_EVENTS:
                        raise ProviderError("Native CLI exceeded the event limit.")
                    self.messages.append(message)
                if len(self.buffer) > _MAX_LINE:
                    raise ProviderError("Native CLI message exceeded the line limit.")

    def cancel_notice(self, message):
        """Best effort only; process-group termination is always authoritative."""
        try:
            self.writes.clear()
            data = json.dumps(message, separators=(",", ":")).encode() + b"\n"
            os.write(self.process.stdin.fileno(), data)
        except (OSError, ValueError):
            pass

    def close(self):
        self.selector.close()
        if self.process:
            _stop_group(self.process)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream:
                    stream.close()


class _Callbacks:
    def __init__(self, pipe, emit, bind_session, approve, secrets):
        self.pipe, self.emit_callback = pipe, emit
        self.bind_session, self.approve_callback = bind_session, approve
        self.secrets = [v for k, v in secrets.items() if v and re.search(r"TOKEN|KEY|SECRET|CAPABILITY", k, re.I)]
        self.approvals = 0

    def clean(self, value):
        encoded = json.dumps(value, ensure_ascii=False)
        for secret in self.secrets:
            # JSON quoting handles secrets with quotes/newlines correctly.
            encoded = encoded.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[redacted]")
        if len(encoded.encode()) > _MAX_RESULT:
            raise ProviderError("Native CLI event exceeded the size limit.")
        return json.loads(encoded)

    def emit(self, kind, payload):
        self.emit_callback(kind, self.clean(payload))

    def text(self, text, *, item_id=None, provider=None, part=0, phase=None, complete=False):
        if not isinstance(text, str):
            raise ProviderError("Native CLI returned an invalid text event.")
        if text or complete:
            payload = {"content": {"type": "text", "text": text}}
            if item_id is not None:
                payload.update(item_id=item_id, provider=provider, part=part)
            if phase in ("commentary", "final_answer"):
                payload["phase"] = phase
            self.emit("agent_message" if complete else "agent_message_chunk", payload)

    def approve(self, request, allow="accept", deny="decline"):
        return self.approve_options(request, [
            {"optionId": allow, "name": "Allow once", "kind": "allow_once"},
            {"optionId": deny, "name": "Deny", "kind": "reject_once"}])

    def approve_options(self, request, options):
        self.approvals += 1
        if self.approvals > _MAX_APPROVALS:
            raise ProviderError("Native CLI exceeded the permission request limit.")
        request = self.clean(request)
        done, answer = threading.Event(), []
        options = self.clean(options)

        def decide():
            try:
                answer.append(self.approve_callback(request, options))
            except Exception:
                answer.append(None)
            finally:
                done.set()

        # A slow UI callback must not bypass the run deadline or cancellation.
        threading.Thread(target=decide, daemon=True, name="agentdock-permission").start()
        while not done.wait(0.05):
            self.pipe.check()
        self.pipe.check()
        if not answer or answer[0] not in [option['optionId'] for option in options]:
            raise ProviderError("Permission request was not resolved; the agent run was stopped.")
        return answer[0]


class _Codex:
    def __init__(self, pipe, callbacks):
        self.pipe, self.cb = pipe, callbacks
        self.thread_id = self.turn_id = None
        self.request_id = 0
        self.permission_ids = set()
        self.finished = None
        self.final_messages = {}
        self.message_phases = {}
        self.message_order = {}
        self.deltas = {}
        self.usage_output = None
        self.usage_at = None

    def request(self, method, params):
        self.request_id += 1
        request_id = self.request_id
        self.pipe.send({"id": request_id, "method": method, "params": params})
        while True:
            message = self.pipe.next()
            if "method" not in message:
                if message.get("id") != request_id:
                    raise ProviderError("Codex returned an unexpected response.")
                if "error" in message:
                    raise ProviderError("Codex rejected a protocol request. Check CLI login and compatibility.")
                if not isinstance(message.get("result"), dict):
                    raise ProviderError("Codex returned an invalid response.")
                return message["result"]
            self.handle(message)

    def handle(self, message):
        method, params = message.get("method"), message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            raise ProviderError("Codex emitted invalid method parameters.")
        if self.thread_id and params.get("threadId", self.thread_id) != self.thread_id:
            raise ProviderError("Codex emitted an event for a different session.")
        if self.turn_id and params.get("turnId", self.turn_id) != self.turn_id:
            raise ProviderError("Codex emitted an event for a different turn.")
        if "id" in message:
            identifier = message["id"]
            if (not isinstance(identifier, (str, int)) or isinstance(identifier, bool)
                    or identifier in self.permission_ids):
                raise ProviderError("Codex reused an invalid permission request ID.")
            self.permission_ids.add(identifier)
            if len(self.permission_ids) > _MAX_APPROVALS:
                raise ProviderError("Codex exceeded the server request limit.")
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                decision = self.cb.approve({"provider": "codex", "method": method, **params})
                self.pipe.send({"id": identifier, "result": {"decision": decision}})
            elif method == "item/permissions/requestApproval":
                permissions = params.get("permissions")
                if not isinstance(permissions, dict):
                    raise ProviderError("Codex requested invalid permissions.")
                decision = self.cb.approve({"provider": "codex", "method": method, **params})
                self.pipe.send({"id": identifier, "result": {
                    "permissions": permissions if decision == "accept" else {}, "scope": "turn"}})
            elif method == "mcpServer/elicitation/request":
                # Arbitrary schemas and URL flows need a dedicated form UI.
                self.pipe.send({"id": identifier, "result": {"action": "decline", "content": None}})
                self.cb.emit("agent_update", {"type": "unsupported_input", "provider": "codex"})
            else:
                self.pipe.send({"id": identifier, "error": {
                    "code": -32601, "message": "This client does not support that request."}})
            return
        if method == "item/agentMessage/delta":
            item = params.get("itemId")
            if not _identifier(item) or not isinstance(params.get("delta"), str):
                raise ProviderError("Codex returned an invalid message delta.")
            self.deltas[item] = self.deltas.get(item, "") + params["delta"]
            self.message_order[item] = None
            if sum(len(v.encode()) for v in self.deltas.values()) > _MAX_RESULT:
                raise ProviderError("Codex response exceeded the text limit.")
            self.cb.text(params["delta"], item_id=item, provider="codex", phase=self.message_phases.get(item))
        elif method in ("item/reasoning/summaryTextDelta", "item/commandExecution/outputDelta", "item/fileChange/outputDelta"):
            item, delta = params.get("itemId"), params.get("delta")
            if not _identifier(item) or not isinstance(delta, str):
                raise ProviderError("Codex returned an invalid progress event.")
            reasoning = method == "item/reasoning/summaryTextDelta"
            part = params.get("summaryIndex", 0)
            if reasoning and (not isinstance(part, int) or isinstance(part, bool) or part < 0):
                raise ProviderError("Codex returned an invalid reasoning summary index.")
            self.cb.emit("reasoning_chunk" if reasoning else "tool_output", {
                "provider": "codex", "item_id": item, "part": part, "text": delta})
        elif method in ("item/started", "item/completed"):
            item = params.get("item")
            if not isinstance(item, dict):
                raise ProviderError("Codex returned an invalid item event.")
            if item.get("type") == "agentMessage":
                identifier, text = item.get("id"), item.get("text")
                if not _identifier(identifier):
                    raise ProviderError("Codex returned an invalid assistant message.")
                self.message_order[identifier] = None
                if item.get("phase") in ("commentary", "final_answer"):
                    self.message_phases[identifier] = item["phase"]
                if method == "item/completed":
                    if not isinstance(text, str):
                        raise ProviderError("Codex returned an invalid assistant message.")
                    self.final_messages[identifier] = text
                    metadata = {"item_id": identifier, "provider": "codex", "phase": self.message_phases.get(identifier)}
                    if identifier not in self.deltas:
                        self.cb.text(text, **metadata)
                    self.cb.text(text, complete=True, **metadata)
            elif item.get("type") == "reasoning":
                if method == "item/completed":
                    summary = item.get("summary", [])
                    if not isinstance(summary, list) or any(not isinstance(s, str) for s in summary):
                        raise ProviderError("Codex returned an invalid reasoning summary.")
                    for index, text in enumerate(summary):
                        self.cb.emit("reasoning_message", {"provider": "codex", "item_id": item.get("id"), "part": index, "text": text})
            elif item.get("type") not in ("agentMessage", "reasoning", "userMessage"):
                self.cb.emit("tool_call" if method == "item/started" else "tool_result", {"provider": "codex", "item": item})
        elif method == "thread/tokenUsage/updated":
            info = params.get("tokenUsage", {})
            usage = normalize("codex", info.get("total")) if isinstance(info, dict) else None
            if usage and self.thread_id:
                at = time.time()
                delta = usage["output_tokens"] - self.usage_output if self.usage_output is not None else (normalize("codex", info.get("last")) or {}).get("output_tokens")
                self.cb.emit("token_usage", {"native_id": self.thread_id, "record_id": "total", "usage": usage,
                    "at": at, "started_at": self.usage_at, "output_delta": delta})
                self.usage_output, self.usage_at = usage["output_tokens"], at
        elif method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict) or not _identifier(turn.get("id")):
                raise ProviderError("Codex returned an invalid turn completion.")
            if self.turn_id and turn["id"] != self.turn_id:
                raise ProviderError("Codex completed a different turn.")
            self.finished = turn
        elif method == "error" and not params.get("willRetry", False):
            raise ProviderError("Codex reported a run failure; private error details were omitted.")

    def run(self, cwd, prompt, native_session_id, mcp, env, model=None, effort=None, inherit_process_cwd=False, permission_mode='ask', session_ready=None):
        self.request("initialize", {"clientInfo": {"name": "agentdock", "title": "AgentDock", "version": "0.3.0"},
                                    "capabilities": {"experimentalApi": False}})
        self.pipe.send({"method": "initialized", "params": {}})
        approval_policy = "never" if permission_mode == "full_access" else "untrusted"
        sandbox = "danger-full-access" if permission_mode == "full_access" else "workspace-write"
        params = {"cwd": cwd, "approvalPolicy": approval_policy, "sandbox": sandbox,
                  "approvalsReviewer": "user", "config": {
                      "mcp_servers": {"agentdock": {**mcp, "env_vars": list(env), "required": True}}}}
        if inherit_process_cwd:
            # An explicit thread/start cwd can persist project trust in Codex.
            # The owned process already starts in this directory; inherit it and
            # verify the resolved directory before submitting any user prompt.
            params.pop("cwd")
        if model: params["model"] = model
        if native_session_id:
            params["threadId"] = native_session_id
            # Restore state without returning potentially unbounded turn history.
            params["excludeTurns"] = True
        response = self.request("thread/resume" if native_session_id else "thread/start", params)
        if (not isinstance(response.get("cwd"), str)
                or os.path.realpath(response["cwd"]) != os.path.realpath(cwd)):
            raise ProviderError("Codex selected a different working directory; no prompt was sent.")
        thread = response.get("thread")
        if not isinstance(thread, dict) or not _identifier(thread.get("id")):
            raise ProviderError("Codex did not return a valid native session.")
        self.thread_id = thread["id"]
        if native_session_id and self.thread_id != native_session_id:
            raise ProviderError("Codex resumed a different native session.")
        self.cb.bind_session(self.thread_id)
        if session_ready: session_ready()
        actual_model = response.get('model')
        if isinstance(actual_model, str) and actual_model and len(actual_model) <= 160:
            metadata = {'native_id': self.thread_id, 'model': actual_model}
            for key, value in (('model_provider', response.get('modelProvider')),
                               ('effort', effort or response.get('reasoningEffort'))):
                if isinstance(value, str) and len(value) <= 160: metadata[key] = value
            self.cb.emit('model_info', metadata)
        self.usage_at = time.time()
        response = self.request("turn/start", {"threadId": self.thread_id,
            "input": [{"type": "text", "text": prompt}], "approvalPolicy": approval_policy,
            "approvalsReviewer": "user", "model": model, "effort": effort, "summary": "auto"})
        turn = response.get("turn")
        if not isinstance(turn, dict) or not _identifier(turn.get("id")):
            raise ProviderError("Codex did not return a valid turn.")
        self.turn_id = turn["id"]
        while self.finished is None:
            self.handle(self.pipe.next())
        if self.finished["id"] != self.turn_id:
            raise ProviderError("Codex completed a different turn.")
        status = self.finished.get("status")
        if status == "interrupted":
            raise ProviderCancelled()
        if status != "completed":
            raise ProviderError("Codex stopped before completing the turn.")
        # Some gateways omit phase. The last assistant item is the reply;
        # concatenating all items would also include earlier progress updates.
        candidates = [item for item in self.message_order
                      if item in self.final_messages or item in self.deltas]
        finals = [item for item in candidates if self.message_phases.get(item) == "final_answer"]
        candidates = finals or [item for item in candidates if self.message_phases.get(item) != "commentary"]
        identifier = candidates[-1] if candidates else None
        result = self.final_messages.get(identifier, self.deltas.get(identifier, ""))
        if len(result.encode()) > _MAX_RESULT:
            raise ProviderError("Codex response exceeded the text limit.")
        return self.cb.clean(result)

    def cancel(self):
        if self.thread_id and self.turn_id:
            self.pipe.cancel_notice({"id": self.request_id + 1, "method": "turn/interrupt",
                                     "params": {"threadId": self.thread_id, "turnId": self.turn_id}})


class _Claude:
    def __init__(self, pipe, callbacks, native_id):
        self.pipe, self.cb, self.native_id = pipe, callbacks, native_id
        self.permission_ids = set()
        self.bound = False
        self.saw_delta = False
        self.thinking_blocks = set()
        self.message_number = 0
        self.message_id = None
        self.messages = {}
        self.usage_messages = {}
        self.usage_id = None
        self.turn_started = time.time()

    def usage(self, message):
        identifier = message.get("id")
        raw = message.get("usage")
        if not _identifier(identifier) or not isinstance(raw, dict): return
        at = time.time()
        previous = self.usage_messages.get(identifier, {"raw": {}, "at": self.turn_started, "out": 0})
        raw = {**previous["raw"], **raw}
        usage = normalize("claude", raw)
        if usage:
            self.cb.emit("token_usage", {"native_id": self.native_id, "record_id": identifier, "usage": usage,
                "at": at, "started_at": previous["at"], "output_delta": max(0, usage["output_tokens"]-previous["out"])})
        self.usage_messages[identifier] = {"raw": raw, "at": at, "out": usage["output_tokens"] if usage else previous["out"]}

    def handle_permission(self, message):
        identifier, request = message.get("request_id"), message.get("request")
        if not _identifier(identifier) or identifier in self.permission_ids or not isinstance(request, dict):
            raise ProviderError("Claude returned an invalid control request.")
        self.permission_ids.add(identifier)
        if len(self.permission_ids) > _MAX_APPROVALS:
            raise ProviderError("Claude exceeded the control request limit.")
        if request.get("subtype") != "can_use_tool":
            self.pipe.send({"type": "control_response", "response": {"subtype": "error",
                "request_id": identifier, "error": "This client does not support that control request."}})
            return
        name, tool_input = request.get("tool_name"), request.get("input")
        if not isinstance(name, str) or not name or not isinstance(tool_input, dict):
            raise ProviderError("Claude requested invalid tool permissions.")
        decision = self.cb.approve({"provider": "claude", **request}, "allow", "deny")
        response = ({"behavior": "allow", "updatedInput": tool_input} if decision == "allow" else
                    {"behavior": "deny", "message": "The user did not approve this action."})
        self.pipe.send({"type": "control_response", "response": {
            "subtype": "success", "request_id": identifier, "response": response}})

    def validate_session(self, message):
        native_id = message.get("session_id")
        if native_id is not None and native_id != self.native_id:
            raise ProviderError("Claude emitted an event for a different native session.")
        if native_id and not self.bound:
            self.cb.bind_session(native_id)
            self.bound = True

    def run(self, prompt):
        self.pipe.send({"type": "control_request", "request_id": "agentdock_initialize",
                        "request": {"subtype": "initialize", "hooks": None}})
        while True:
            message = self.pipe.next()
            self.validate_session(message)
            if message.get("type") == "control_response":
                response = message.get("response")
                if (not isinstance(response, dict) or response.get("request_id") != "agentdock_initialize"
                        or response.get("subtype") != "success" or not isinstance(response.get("response"), dict)):
                    raise ProviderError("Claude rejected the control handshake. Check CLI compatibility.")
                break
            if message.get("type") == "control_request":
                self.handle_permission(message)
        self.pipe.send({"type": "user", "session_id": self.native_id, "parent_tool_use_id": None,
                        "message": {"role": "user", "content": prompt}})
        while True:
            message = self.pipe.next()
            self.validate_session(message)
            kind = message.get("type")
            if kind == "control_request":
                self.handle_permission(message)
            elif kind == 'system' and message.get('subtype') == 'init':
                actual_model = message.get('model')
                if isinstance(actual_model, str) and actual_model and len(actual_model) <= 160:
                    self.cb.emit('model_info', {'native_id': self.native_id, 'model': actual_model})
            elif kind == "stream_event" and not message.get("parent_tool_use_id"):
                event = message.get("event", {})
                if not isinstance(event, dict):
                    raise ProviderError("Claude returned an invalid stream event.")
                if event.get("type") == "message_start":
                    self.saw_delta = False
                    self.message_number += 1
                    self.thinking_blocks = set()
                    body = event.get("message", {})
                    self.usage_id = body.get("id")
                    self.message_id = self.usage_id if _identifier(self.usage_id) else f"message-{self.message_number}"
                    if _identifier(self.usage_id):
                        self.usage_messages[self.usage_id] = {"raw": {}, "at": time.time(), "out": 0}
                        self.usage(body)
                if event.get("type") == "message_delta":
                    self.usage({"id": self.usage_id, "usage": event.get("usage")})
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        index = event.get("index", 0)
                        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                            raise ProviderError("Claude returned an invalid text block index.")
                        self.saw_delta = True
                        self.cb.text(delta.get("text"), item_id=self.message_id, provider="claude", part=index)
                    elif isinstance(delta, dict) and delta.get("type") == "thinking_delta":
                        text, index = delta.get("thinking"), event.get("index", 0)
                        if not isinstance(text, str) or not isinstance(index, int) or isinstance(index, bool) or index < 0:
                            raise ProviderError("Claude returned an invalid thinking event.")
                        self.thinking_blocks.add(index)
                        self.cb.emit("reasoning_chunk", {"provider": "claude", "item_id": self.usage_id or str(self.message_number), "part": index, "text": text})
                if event.get("type") == "content_block_start":
                    block = event.get("content_block", {})
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        self.cb.emit("tool_call", {"provider": "claude", "item": block})
            elif kind in ("assistant", "user"):
                if kind == "assistant" and message.get("error"):
                    raise ProviderError("Claude reported a provider error; private error details were omitted.")
                body = message.get("message", {})
                if kind == "assistant" and not message.get("parent_tool_use_id") and isinstance(body, dict): self.usage(body)
                content = body.get("content", []) if isinstance(body, dict) else []
                if not isinstance(content, list):
                    raise ProviderError("Claude returned invalid message content.")
                identifier = body.get("id") if isinstance(body, dict) and _identifier(body.get("id")) else self.message_id
                if kind == "assistant" and identifier is None:
                    self.message_number += 1
                    identifier = f"message-{self.message_number}"
                for index, block in enumerate(content):
                    if not isinstance(block, dict):
                        raise ProviderError("Claude returned an invalid content block.")
                    if block.get("type") == "text" and kind == "assistant" and not message.get("parent_tool_use_id"):
                        text = block.get("text")
                        if not isinstance(text, str):
                            raise ProviderError("Claude returned an invalid assistant message.")
                        parts = self.messages.setdefault(identifier, {})
                        parts[index] = text
                        if sum(len(v.encode()) for values in self.messages.values() for v in values.values()) > _MAX_RESULT:
                            raise ProviderError("Claude response exceeded the text limit.")
                        metadata = {"item_id": identifier, "provider": "claude", "part": index}
                        if not self.saw_delta:
                            self.cb.text(text, **metadata)
                        self.cb.text(text, complete=True, **metadata)
                    elif block.get("type") == "thinking" and kind == "assistant" and not message.get("parent_tool_use_id"):
                        text = block.get("thinking")
                        if not isinstance(text, str): raise ProviderError("Claude returned an invalid thinking block.")
                        if index not in self.thinking_blocks:
                            self.cb.emit("reasoning_message", {"provider": "claude", "item_id": body.get("id") or str(self.message_number), "part": index, "text": text})
                    elif block.get("type") in ("tool_use", "tool_result"):
                        self.cb.emit("tool_call" if block["type"] == "tool_use" else "tool_result",
                                     {"provider": "claude", "item": block})
            elif kind == "result":
                if message.get("is_error") or message.get("subtype") != "success":
                    raise ProviderError("Claude stopped before completing the turn. Check CLI login and limits.")
                if not self.bound:
                    raise ProviderError("Claude did not confirm the native session.")
                last_message = next(reversed(self.messages.values()), {})
                result = message.get("result", "\n".join(last_message[index] for index in sorted(last_message)))
                if not isinstance(result, str) or len(result.encode()) > _MAX_RESULT:
                    raise ProviderError("Claude returned an invalid final result.")
                if not self.messages and not self.saw_delta:
                    self.cb.text(result)
                return self.cb.clean(result)

    def cancel(self):
        self.pipe.cancel_notice({"type": "control_request", "request_id": "agentdock_interrupt",
                                 "request": {"subtype": "interrupt"}})


def execute(provider, command, cwd, prompt, native_session_id, mcp_config, stop,
            emit, bind_session, approve, timeout=900, model=None, effort=None, inherit_process_cwd=False, permission_mode='ask', session_home=None):
    """Run one turn and return final text, retaining native session identity.

    ``command`` is a trusted server-side argv prefix (``codex app-server`` or
    ``claude``), never user/model supplied. ``mcp_config`` is the sole AgentDock
    stdio server descriptor: ``{command, args, env}``. The caller owns session
    authorization and callbacks; ``approve`` returns an offered optionId.
    Cancellation and deadlines stop the whole child process group.
    """
    if provider not in PROVIDERS:
        raise ProviderError("Unsupported native agent provider.")
    if permission_mode not in ("ask", "full_access"):
        raise ProviderError("Invalid agent permission mode")
    if (not isinstance(command, list) or not command or any(not isinstance(v, str) or not v
            or "\x00" in v for v in command)):
        raise ProviderError("Configure a native CLI command for this provider.")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 400000:
        raise ProviderError("Agent prompt exceeds the supported size.")
    from .acp import ACP, identifier as acp_identifier
    valid_identifier = acp_identifier if provider in ACP_PROVIDERS else _identifier
    if native_session_id is not None and not valid_identifier(native_session_id):
        raise ProviderError("The saved native session identifier is invalid.")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise ProviderError("The agent run timeout is invalid.")
    mcp, additions = _validate_mcp(mcp_config)
    env = dict(os.environ)
    for key in ('CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE'):
        env.pop(key, None)
    env.update(additions)
    argv = list(command)
    native_id = native_session_id
    session_ready = None
    if provider == "codex":
        if session_home is not None:
            from .codex_home import prepare
            original_env = dict(env)
            try:
                env, flags, legacy = prepare(os.path.join(session_home, 'codex'), env, native_id, cwd)
            except (OSError, ValueError):
                raise ProviderError('Could not prepare isolated Codex session storage; no prompt was sent.') from None
            argv += flags
            if legacy:
                def session_ready():
                    # The private transcript has resumed successfully; remove the
                    # old duplicate without touching any other desktop conversation.
                    from .codex_home import retire_legacy
                    retire_legacy(command, original_env, native_id)
        argv += ["--listen", "stdio://"]
    elif provider == 'claude':
        original_env = dict(env)
        if session_home is not None:
            from .session_storage import prepare_claude
            env = prepare_claude(os.path.join(session_home, 'claude'), env, native_id)
        # Each worker owns one foreground turn; background work cannot outlive it.
        env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
        if native_id:
            try:
                uuid.UUID(native_id)
            except ValueError:
                raise ProviderError("The saved Claude session identifier is invalid.") from None
        else:
            native_id = str(uuid.uuid4())
        argv += ["--print", "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
                 "--include-partial-messages", "--permission-prompt-tool", "stdio",
                 "--permission-mode", "bypassPermissions" if permission_mode == "full_access" else "manual", "--strict-mcp-config",
                 "--mcp-config", json.dumps({"mcpServers": {"agentdock": {"type": "stdio", **mcp}}})]
        if model: argv += ["--model", model]
        if effort: argv += ["--effort", effort]
        argv += ["--resume=" + native_id] if native_session_id else ["--session-id", native_id]
    else:
        if session_home is None:
            raise ProviderError('ACP agents require an isolated AgentDock session directory.')
        if provider == 'pi' and permission_mode != 'full_access':
            raise ProviderError('Pi does not gate its tools through ACP. Select full access explicitly to use Pi.')
        from .acp_home import prepare
        try:
            env = prepare(provider, os.path.join(session_home, provider), env)
        except (OSError, ValueError):
            raise ProviderError('Could not prepare isolated CLI storage; no prompt was sent.') from None
        from .registry import acp_command
        argv = acp_command(provider, argv, cwd, env, stop)
        if provider == 'opencode':
            env['OPENCODE_PERMISSION'] = '{"*":"ask"}'
    pipe = adapter = None
    try:
        pipe = _Pipe(argv, cwd, env, stop, timeout)
        callbacks = _Callbacks(pipe, emit, bind_session, approve, additions)
        if provider == "codex":
            adapter = _Codex(pipe, callbacks)
            return adapter.run(cwd, prompt, native_session_id, mcp, additions, model, effort, inherit_process_cwd, permission_mode, session_ready)
        if provider in ACP_PROVIDERS:
            adapter = ACP(pipe, callbacks, provider, permission_mode)
            return adapter.run(os.path.realpath(cwd), prompt, native_session_id, mcp, additions, model, effort)
        adapter = _Claude(pipe, callbacks, native_id)
        result = adapter.run(prompt)
        if session_home is not None and native_session_id:
            from .session_storage import retire_legacy_claude
            retire_legacy_claude(original_env, native_session_id)
        return result
    except (ProviderCancelled, ProviderError):
        if adapter:
            adapter.cancel()
        raise
    except Exception:
        raise ProviderError("Native agent run failed; private process details were omitted.") from None
    finally:
        if pipe:
            pipe.close()
