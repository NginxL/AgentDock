"""codex protocol; no process is started at import."""

from __future__ import annotations

import os
import time

from . import __version__
from .metrics import normalize
from .provider_common import (
    _MAX_APPROVALS,
    ProviderCancelled,
    ProviderError,
    _identifier,
    account_error,
)
from .text_buffer import TextBuffer, bounded_text


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
        self.text_bytes = 0
        self.usage_output = None
        self.usage_at = None

    def trim_messages(self):
        while len(self.message_order) > 16:
            identifier = next(iter(self.message_order))
            self.message_order.pop(identifier)
            self.deltas.pop(identifier, None)
            self.final_messages.pop(identifier, None)
            self.message_phases.pop(identifier, None)

    def initialize(self):
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "agentdock",
                    "title": "AgentDock",
                    "version": __version__,
                },
                "capabilities": {"experimentalApi": False},
            },
        )
        self.pipe.send({"method": "initialized", "params": {}})

    def request(self, method, params, allow_rejection=False):
        self.request_id += 1
        request_id = self.request_id
        self.pipe.send({"id": request_id, "method": method, "params": params})
        while True:
            message = self.pipe.next()
            if "method" not in message:
                if message.get("id") != request_id:
                    raise ProviderError("Codex returned an unexpected response.")
                if "error" in message:
                    if allow_rejection:
                        return {"rejected": True}
                    raise account_error(
                        message["error"],
                        "Codex rejected a protocol request. Check CLI login and compatibility.",
                    )
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
            if (
                not isinstance(identifier, (str, int))
                or isinstance(identifier, bool)
                or identifier in self.permission_ids
            ):
                raise ProviderError("Codex reused an invalid permission request ID.")
            self.permission_ids.add(identifier)
            if len(self.permission_ids) > _MAX_APPROVALS:
                raise ProviderError("Codex exceeded the server request limit.")
            if method in (
                "item/commandExecution/requestApproval",
                "item/fileChange/requestApproval",
            ):
                decision = self.cb.approve(
                    {"provider": "codex", "method": method, **params}
                )
                self.pipe.send({"id": identifier, "result": {"decision": decision}})
            elif method == "item/permissions/requestApproval":
                permissions = params.get("permissions")
                if not isinstance(permissions, dict):
                    raise ProviderError("Codex requested invalid permissions.")
                decision = self.cb.approve(
                    {"provider": "codex", "method": method, **params}
                )
                self.pipe.send(
                    {
                        "id": identifier,
                        "result": {
                            "permissions": permissions if decision == "accept" else {},
                            "scope": "turn",
                        },
                    }
                )
            elif method == "mcpServer/elicitation/request":
                # Arbitrary schemas and URL flows need a dedicated form UI.
                self.pipe.send(
                    {"id": identifier, "result": {"action": "decline", "content": None}}
                )
                self.cb.emit(
                    "agent_update", {"type": "unsupported_input", "provider": "codex"}
                )
            else:
                self.pipe.send(
                    {
                        "id": identifier,
                        "error": {
                            "code": -32601,
                            "message": "This client does not support that request.",
                        },
                    }
                )
            return
        if method == "item/agentMessage/delta":
            item = params.get("itemId")
            if not _identifier(item) or not isinstance(params.get("delta"), str):
                raise ProviderError("Codex returned an invalid message delta.")
            self.deltas.setdefault(item, TextBuffer()).append(params["delta"])
            self.message_order[item] = None
            self.trim_messages()
            self.cb.text(
                params["delta"],
                item_id=item,
                provider="codex",
                phase=self.message_phases.get(item),
            )
        elif method in (
            "item/reasoning/summaryTextDelta",
            "item/commandExecution/outputDelta",
            "item/fileChange/outputDelta",
        ):
            item, delta = params.get("itemId"), params.get("delta")
            if not _identifier(item) or not isinstance(delta, str):
                raise ProviderError("Codex returned an invalid progress event.")
            reasoning = method == "item/reasoning/summaryTextDelta"
            part = params.get("summaryIndex", 0)
            if reasoning and (
                not isinstance(part, int) or isinstance(part, bool) or part < 0
            ):
                raise ProviderError(
                    "Codex returned an invalid reasoning summary index."
                )
            self.cb.emit(
                "reasoning_chunk" if reasoning else "tool_output",
                {"provider": "codex", "item_id": item, "part": part, "text": delta},
            )
        elif method in ("item/started", "item/completed"):
            item = params.get("item")
            if not isinstance(item, dict):
                raise ProviderError("Codex returned an invalid item event.")
            if item.get("type") == "agentMessage":
                identifier, text = item.get("id"), item.get("text")
                if not _identifier(identifier):
                    raise ProviderError("Codex returned an invalid assistant message.")
                self.message_order[identifier] = None
                self.trim_messages()
                if item.get("phase") in ("commentary", "final_answer"):
                    self.message_phases[identifier] = item["phase"]
                if method == "item/completed":
                    if not isinstance(text, str):
                        raise ProviderError(
                            "Codex returned an invalid assistant message."
                        )
                    self.final_messages[identifier] = bounded_text(text)
                    metadata = {
                        "item_id": identifier,
                        "provider": "codex",
                        "phase": self.message_phases.get(identifier),
                    }
                    if identifier not in self.deltas:
                        self.cb.text(text, **metadata)
                    self.cb.text(text, complete=True, **metadata)
            elif item.get("type") == "reasoning":
                if method == "item/completed":
                    summary = item.get("summary", [])
                    if not isinstance(summary, list) or any(
                        not isinstance(s, str) for s in summary
                    ):
                        raise ProviderError(
                            "Codex returned an invalid reasoning summary."
                        )
                    for index, text in enumerate(summary):
                        self.cb.emit(
                            "reasoning_message",
                            {
                                "provider": "codex",
                                "item_id": item.get("id"),
                                "part": index,
                                "text": text,
                            },
                        )
            elif item.get("type") not in ("agentMessage", "reasoning", "userMessage"):
                self.cb.emit(
                    "tool_call" if method == "item/started" else "tool_result",
                    {"provider": "codex", "item": item},
                )
        elif method == "thread/tokenUsage/updated":
            info = params.get("tokenUsage", {})
            usage = (
                normalize("codex", info.get("total"))
                if isinstance(info, dict)
                else None
            )
            if usage and self.thread_id:
                at = time.time()
                delta = (
                    usage["output_tokens"] - self.usage_output
                    if self.usage_output is not None
                    else (normalize("codex", info.get("last")) or {}).get(
                        "output_tokens"
                    )
                )
                self.cb.emit(
                    "token_usage",
                    {
                        "native_id": self.thread_id,
                        "record_id": "total",
                        "usage": usage,
                        "at": at,
                        "started_at": self.usage_at,
                        "output_delta": delta,
                    },
                )
                self.usage_output, self.usage_at = usage["output_tokens"], at
        elif method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict) or not _identifier(turn.get("id")):
                raise ProviderError("Codex returned an invalid turn completion.")
            if self.turn_id and turn["id"] != self.turn_id:
                raise ProviderError("Codex completed a different turn.")
            self.finished = turn
        elif method == "error" and not params.get("willRetry", False):
            raise account_error(
                params,
                "Codex reported a run failure; private error details were omitted.",
            )

    def run(
        self,
        cwd,
        prompt,
        native_session_id,
        mcp,
        env,
        model=None,
        effort=None,
        inherit_process_cwd=False,
        permission_mode="ask",
        session_ready=None,
        control=None,
    ):
        self.initialize()
        approval_policy = "untrusted" if permission_mode == "ask" else "never"
        sandbox = {
            "full_access": "danger-full-access",
            "read_only": "read-only",
            "ask": "workspace-write",
        }[permission_mode]
        params = {
            "cwd": cwd,
            "approvalPolicy": approval_policy,
            "sandbox": sandbox,
            "approvalsReviewer": "user",
            "config": {
                "mcp_servers": {
                    "agentdock": {**mcp, "env_vars": list(env), "required": True}
                }
            },
        }
        if inherit_process_cwd:
            # An explicit thread/start cwd can persist project trust in Codex.
            # The owned process already starts in this directory; inherit it and
            # verify the resolved directory before submitting any user prompt.
            params.pop("cwd")
        if model:
            params["model"] = model
        if native_session_id:
            params["threadId"] = native_session_id
            # Restore state without returning potentially unbounded turn history.
            params["excludeTurns"] = True
        response = self.request(
            "thread/resume" if native_session_id else "thread/start", params
        )
        if not isinstance(response.get("cwd"), str) or os.path.realpath(
            response["cwd"]
        ) != os.path.realpath(cwd):
            raise ProviderError(
                "Codex selected a different working directory; no prompt was sent."
            )
        thread = response.get("thread")
        if not isinstance(thread, dict) or not _identifier(thread.get("id")):
            raise ProviderError("Codex did not return a valid native session.")
        self.thread_id = thread["id"]
        if native_session_id and self.thread_id != native_session_id:
            raise ProviderError("Codex resumed a different native session.")
        self.cb.bind_session(self.thread_id)
        if session_ready:
            session_ready()
        actual_model = response.get("model")
        if isinstance(actual_model, str) and actual_model and len(actual_model) <= 160:
            metadata = {"native_id": self.thread_id, "model": actual_model}
            for key, value in (
                ("model_provider", response.get("modelProvider")),
                ("effort", effort or response.get("reasoningEffort")),
            ):
                if isinstance(value, str) and len(value) <= 160:
                    metadata[key] = value
            self.cb.emit("model_info", metadata)
        self.usage_at = time.time()
        response = self.request(
            "turn/start",
            {
                "threadId": self.thread_id,
                "input": [{"type": "text", "text": prompt}],
                "approvalPolicy": approval_policy,
                "approvalsReviewer": "user",
                "model": model,
                "effort": effort,
                "summary": "auto",
            },
        )
        turn = response.get("turn")
        if not isinstance(turn, dict) or not _identifier(turn.get("id")):
            raise ProviderError("Codex did not return a valid turn.")
        self.turn_id = turn["id"]
        if control:
            control.attach(self.turn_id)
            self.cb.emit("input_control", {"turn_id": self.turn_id, "steer": True})
        while self.finished is None:
            if control:
                for item in control.take():
                    status = "rejected"
                    if item["turn_id"] == self.turn_id and self.finished is None:
                        response = self.request(
                            "turn/steer",
                            {
                                "threadId": self.thread_id,
                                "expectedTurnId": self.turn_id,
                                "input": [{"type": "text", "text": item["body"]}],
                            },
                            allow_rejection=True,
                        )
                        status = (
                            "rejected"
                            if response.get("rejected")
                            else (
                                "accepted"
                                if response.get("turnId") == self.turn_id
                                else "unknown"
                            )
                        )
                    self.cb.emit(
                        "input_receipt", {"input_id": item["id"], "status": status}
                    )
                if self.finished is not None:
                    break
            message = self.pipe.next(timeout=0.05) if control else self.pipe.next()
            if message is not None:
                self.handle(message)
        if self.finished["id"] != self.turn_id:
            raise ProviderError("Codex completed a different turn.")
        status = self.finished.get("status")
        if status == "interrupted":
            raise ProviderCancelled()
        if status != "completed":
            raise account_error(
                self.finished, "Codex stopped before completing the turn."
            )
        # Some gateways omit phase. The last assistant item is the reply;
        # concatenating all items would also include earlier progress updates.
        candidates = [
            item
            for item in self.message_order
            if item in self.final_messages or item in self.deltas
        ]
        finals = [
            item
            for item in candidates
            if self.message_phases.get(item) == "final_answer"
        ]
        candidates = finals or [
            item for item in candidates if self.message_phases.get(item) != "commentary"
        ]
        identifier = candidates[-1] if candidates else None
        result = self.final_messages.get(
            identifier, self.deltas.get(identifier, TextBuffer()).text()
        )
        return self.cb.clean(result)

    def cancel(self):
        if self.thread_id and self.turn_id:
            self.pipe.cancel_notice(
                {
                    "id": self.request_id + 1,
                    "method": "turn/interrupt",
                    "params": {"threadId": self.thread_id, "turnId": self.turn_id},
                }
            )
