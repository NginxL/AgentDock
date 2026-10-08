"""claude protocol; no process is started at import."""

from __future__ import annotations

import math
import time

from .metrics import normalize
from .provider_common import _MAX_APPROVALS, ProviderError, _identifier, account_error
from .text_buffer import bounded_text


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
        self.text_bytes = 0
        self.part_bytes = {}
        self.usage_messages = {}
        self.usage_id = None
        self.turn_started = time.time()

    def usage(self, message):
        identifier = message.get("id")
        raw = message.get("usage")
        if not _identifier(identifier) or not isinstance(raw, dict):
            return
        at = time.time()
        previous = self.usage_messages.get(
            identifier, {"raw": {}, "at": self.turn_started, "out": 0}
        )
        raw = {**previous["raw"], **raw}
        usage = normalize("claude", raw)
        if usage:
            self.cb.emit(
                "token_usage",
                {
                    "native_id": self.native_id,
                    "record_id": identifier,
                    "usage": usage,
                    "at": at,
                    "started_at": previous["at"],
                    "output_delta": max(0, usage["output_tokens"] - previous["out"]),
                },
            )
        self.usage_messages[identifier] = {
            "raw": raw,
            "at": at,
            "out": usage["output_tokens"] if usage else previous["out"],
        }

    def handle_permission(self, message):
        identifier, request = message.get("request_id"), message.get("request")
        if (
            not _identifier(identifier)
            or identifier in self.permission_ids
            or not isinstance(request, dict)
        ):
            raise ProviderError("Claude returned an invalid control request.")
        self.permission_ids.add(identifier)
        if len(self.permission_ids) > _MAX_APPROVALS:
            raise ProviderError("Claude exceeded the control request limit.")
        if request.get("subtype") != "can_use_tool":
            self.pipe.send(
                {
                    "type": "control_response",
                    "response": {
                        "subtype": "error",
                        "request_id": identifier,
                        "error": "This client does not support that control request.",
                    },
                }
            )
            return
        name, tool_input = request.get("tool_name"), request.get("input")
        if not isinstance(name, str) or not name or not isinstance(tool_input, dict):
            raise ProviderError("Claude requested invalid tool permissions.")
        decision = self.cb.approve({"provider": "claude", **request}, "allow", "deny")
        response = (
            {"behavior": "allow", "updatedInput": tool_input}
            if decision == "allow"
            else {
                "behavior": "deny",
                "message": "The user did not approve this action.",
            }
        )
        self.pipe.send(
            {
                "type": "control_response",
                "response": {
                    "subtype": "success",
                    "request_id": identifier,
                    "response": response,
                },
            }
        )

    def validate_session(self, message):
        native_id = message.get("session_id")
        if native_id is not None and native_id != self.native_id:
            raise ProviderError(
                "Claude emitted an event for a different native session."
            )
        if native_id and not self.bound:
            self.cb.bind_session(native_id)
            self.bound = True

    def run(self, prompt):
        self.pipe.send(
            {
                "type": "control_request",
                "request_id": "agentdock_initialize",
                "request": {"subtype": "initialize", "hooks": None},
            }
        )
        while True:
            message = self.pipe.next()
            self.validate_session(message)
            if message.get("type") == "control_response":
                response = message.get("response")
                if (
                    not isinstance(response, dict)
                    or response.get("request_id") != "agentdock_initialize"
                    or response.get("subtype") != "success"
                    or not isinstance(response.get("response"), dict)
                ):
                    raise ProviderError(
                        "Claude rejected the control handshake. Check CLI compatibility."
                    )
                break
            if message.get("type") == "control_request":
                self.handle_permission(message)
        self.pipe.send(
            {
                "type": "user",
                "session_id": self.native_id,
                "parent_tool_use_id": None,
                "message": {"role": "user", "content": prompt},
            }
        )
        while True:
            message = self.pipe.next()
            self.validate_session(message)
            kind = message.get("type")
            if kind == "assistant" and message.get("error"):
                raise account_error(message, "Claude could not complete this request.")
            if kind == "rate_limit_event":
                info = message.get("rate_limit_info", {})
                if isinstance(info, dict):
                    self.cb.emit(
                        "account_rate_limit",
                        {
                            key: info[key]
                            for key in (
                                "status",
                                "resetsAt",
                                "rateLimitType",
                                "utilization",
                            )
                            if key in info
                            and isinstance(info[key], (str, int, float))
                            and not isinstance(info[key], bool)
                            and (
                                not isinstance(info[key], (int, float))
                                or math.isfinite(info[key])
                            )
                        },
                    )
                    if info.get("status") == "rejected":
                        reset = info.get("resetsAt")
                        delay = (
                            max(1, reset - time.time())
                            if isinstance(reset, (int, float)) and math.isfinite(reset)
                            else None
                        )
                        raise ProviderError(
                            "This account has reached its usage limit.",
                            code="quota_exhausted",
                            retry_after=delay,
                            rejected=True,
                        )
            if kind == "control_request":
                self.handle_permission(message)
            elif kind == "system" and message.get("subtype") == "init":
                actual_model = message.get("model")
                if (
                    isinstance(actual_model, str)
                    and actual_model
                    and len(actual_model) <= 160
                ):
                    self.cb.emit(
                        "model_info",
                        {"native_id": self.native_id, "model": actual_model},
                    )
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
                    self.message_id = (
                        self.usage_id
                        if _identifier(self.usage_id)
                        else f"message-{self.message_number}"
                    )
                    if _identifier(self.usage_id):
                        self.usage_messages[self.usage_id] = {
                            "raw": {},
                            "at": time.time(),
                            "out": 0,
                        }
                        self.usage(body)
                if event.get("type") == "message_delta":
                    self.usage({"id": self.usage_id, "usage": event.get("usage")})
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        index = event.get("index", 0)
                        if (
                            not isinstance(index, int)
                            or isinstance(index, bool)
                            or index < 0
                        ):
                            raise ProviderError(
                                "Claude returned an invalid text block index."
                            )
                        self.saw_delta = True
                        self.cb.text(
                            delta.get("text"),
                            item_id=self.message_id,
                            provider="claude",
                            part=index,
                        )
                    elif (
                        isinstance(delta, dict)
                        and delta.get("type") == "thinking_delta"
                    ):
                        text, index = delta.get("thinking"), event.get("index", 0)
                        if (
                            not isinstance(text, str)
                            or not isinstance(index, int)
                            or isinstance(index, bool)
                            or index < 0
                        ):
                            raise ProviderError(
                                "Claude returned an invalid thinking event."
                            )
                        self.thinking_blocks.add(index)
                        self.cb.emit(
                            "reasoning_chunk",
                            {
                                "provider": "claude",
                                "item_id": self.usage_id or str(self.message_number),
                                "part": index,
                                "text": text,
                            },
                        )
                if event.get("type") == "content_block_start":
                    block = event.get("content_block", {})
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        self.cb.emit("tool_call", {"provider": "claude", "item": block})
            elif kind in ("assistant", "user"):
                body = message.get("message", {})
                if (
                    kind == "assistant"
                    and not message.get("parent_tool_use_id")
                    and isinstance(body, dict)
                ):
                    self.usage(body)
                content = body.get("content", []) if isinstance(body, dict) else []
                if not isinstance(content, list):
                    raise ProviderError("Claude returned invalid message content.")
                identifier = (
                    body.get("id")
                    if isinstance(body, dict) and _identifier(body.get("id"))
                    else self.message_id
                )
                if kind == "assistant" and identifier is None:
                    self.message_number += 1
                    identifier = f"message-{self.message_number}"
                for index, block in enumerate(content):
                    if not isinstance(block, dict):
                        raise ProviderError("Claude returned an invalid content block.")
                    if (
                        block.get("type") == "text"
                        and kind == "assistant"
                        and not message.get("parent_tool_use_id")
                    ):
                        text = block.get("text")
                        if not isinstance(text, str):
                            raise ProviderError(
                                "Claude returned an invalid assistant message."
                            )
                        parts = self.messages.setdefault(identifier, {})
                        parts[index] = bounded_text(text)
                        while len(self.messages) > 8:
                            self.messages.pop(next(iter(self.messages)))
                        metadata = {
                            "item_id": identifier,
                            "provider": "claude",
                            "part": index,
                        }
                        if not self.saw_delta:
                            self.cb.text(text, **metadata)
                        self.cb.text(text, complete=True, **metadata)
                    elif (
                        block.get("type") == "thinking"
                        and kind == "assistant"
                        and not message.get("parent_tool_use_id")
                    ):
                        text = block.get("thinking")
                        if not isinstance(text, str):
                            raise ProviderError(
                                "Claude returned an invalid thinking block."
                            )
                        if index not in self.thinking_blocks:
                            self.cb.emit(
                                "reasoning_message",
                                {
                                    "provider": "claude",
                                    "item_id": body.get("id")
                                    or str(self.message_number),
                                    "part": index,
                                    "text": text,
                                },
                            )
                    elif block.get("type") in ("tool_use", "tool_result"):
                        self.cb.emit(
                            "tool_call"
                            if block["type"] == "tool_use"
                            else "tool_result",
                            {"provider": "claude", "item": block},
                        )
            elif kind == "result":
                if message.get("is_error") or message.get("subtype") != "success":
                    raise account_error(
                        message,
                        "Claude stopped before completing the turn. Check CLI login and limits.",
                    )
                if not self.bound:
                    raise ProviderError("Claude did not confirm the native session.")
                last_message = next(reversed(self.messages.values()), {})
                result = message.get(
                    "result",
                    "\n".join(last_message[index] for index in sorted(last_message)),
                )
                if not isinstance(result, str):
                    raise ProviderError("Claude returned an invalid final result.")
                if not self.messages and not self.saw_delta:
                    self.cb.text(result)
                return self.cb.clean(bounded_text(result))

    def cancel(self):
        self.pipe.cancel_notice(
            {
                "type": "control_request",
                "request_id": "agentdock_interrupt",
                "request": {"subtype": "interrupt"},
            }
        )
