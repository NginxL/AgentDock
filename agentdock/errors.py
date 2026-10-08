"""Shared validation and public domain errors (no storage dependencies)."""

from __future__ import annotations

from datetime import datetime, timezone


class PublicError(Exception):
    code = "invalid_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class Invalid(PublicError, ValueError):
    code = "invalid_request"


class Missing(PublicError, KeyError):
    code = "not_found"


class Conflict(PublicError, ValueError):
    code = "state_conflict"


class Forbidden(PublicError, PermissionError):
    code = "forbidden"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text(value: object, field: str, limit: int = 16000, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or "\x00" in value
        or (not empty and not value.strip())
    ):
        raise Invalid("Invalid " + field)
    return value.strip()


def version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Invalid("expected_version must be a nonnegative integer")
    return value
