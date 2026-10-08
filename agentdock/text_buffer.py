"""Bounded incremental text, independent of a turn's total output volume."""

from collections import deque

TEXT_LIMIT = 120_000
TRUNCATED = (
    "\n[Earlier output truncated; the native transcript retains the full response.]\n"
)


class TextBuffer:
    def __init__(self, limit: int = TEXT_LIMIT) -> None:
        self.limit = limit
        self.parts: deque[bytes] = deque()
        self.size = 0
        self.truncated = False

    def append(self, value: str) -> None:
        part = value.encode()
        self.parts.append(part)
        self.size += len(part)
        while self.size > self.limit:
            oldest = self.parts.popleft()
            excess = self.size - self.limit
            self.size -= len(oldest)
            if len(oldest) > excess:
                remainder = oldest[excess:]
                self.parts.appendleft(remainder)
                self.size += len(remainder)
            self.truncated = True

    def text(self) -> str:
        return (TRUNCATED if self.truncated else "") + b"".join(self.parts).decode(
            errors="ignore"
        )


def bounded_text(value: str) -> str:
    result = TextBuffer()
    result.append(value)
    return result.text()
