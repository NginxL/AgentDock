"""Bounded incremental text, independent of a turn's total output volume."""

from collections import deque

TEXT_LIMIT = 120_000
TRUNCATED = (
    "\n[Earlier output truncated; the native transcript retains the full response.]\n"
)


class TextBuffer:
    def __init__(self, limit: int = TEXT_LIMIT) -> None:
        if limit <= len(TRUNCATED.encode()):
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
        return (TRUNCATED if self.truncated else "") + b"".join(self.parts).decode(
            errors="ignore"
        )


def bounded_text(value: str) -> str:
    result = TextBuffer()
    result.append(value)
    return result.text()
