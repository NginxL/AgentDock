"""Bounded incremental text, independent of a turn's total output volume."""

import json
from collections import deque

TEXT_LIMIT = 120_000
TRUNCATED = (
    "\n[Earlier output truncated; the native transcript retains the full response.]\n"
)


def _json_content_size(value: str) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode()) - 2


def _bound_json_content(value: str, limit: int) -> str:
    """Bound escaped text too, leaving space for the event's fixed metadata.

    JSON quotes/backslashes and control characters can expand by 2x or 6x.
    Keep the tail with one marker; measure each retained character at most once.
    The raw byte buffer still bounds memory while streaming.
    """
    if _json_content_size(value) <= limit:
        return value
    body = value.removeprefix(TRUNCATED)
    budget = limit - _json_content_size(TRUNCATED)
    for index in range(len(body) - 1, -1, -1):
        char = body[index]
        if char in '"\\\b\f\n\r\t':
            width = 2
        elif ord(char) < 0x20:
            width = 6
        else:
            width = len(char.encode())
        if width > budget:
            return TRUNCATED + body[index + 1 :]
        budget -= width
    return TRUNCATED + body


class TextBuffer:
    def __init__(self, limit: int = TEXT_LIMIT) -> None:
        if limit <= _json_content_size(TRUNCATED):
            raise ValueError("Text limit must leave room for a truncation marker")
        self.limit = limit
        self.parts: deque[bytes] = deque()
        self.size = 0
        self.truncated = False

    def append(self, value: str) -> None:
        part = value.encode()
        self.parts.append(part)
        self.size += len(part)
        self.truncated = self.truncated or self.size > self.limit
        # Include the marker in the byte budget. Already bounded final text is
        # unchanged when it crosses another adapter/runtime boundary.
        budget = self.limit - (len(TRUNCATED.encode()) if self.truncated else 0)
        while self.size > budget:
            oldest = self.parts.popleft()
            excess = self.size - budget
            self.size -= len(oldest)
            if len(oldest) > excess:
                remainder = oldest[excess:]
                self.parts.appendleft(remainder)
                self.size += len(remainder)

    def text(self) -> str:
        value = (TRUNCATED if self.truncated else "") + b"".join(self.parts).decode(
            errors="ignore"
        )
        return _bound_json_content(value, self.limit)


def bounded_text(value: str) -> str:
    result = TextBuffer()
    result.append(value)
    return result.text()
