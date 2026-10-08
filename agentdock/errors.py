"""Shared validation and public domain errors (no storage dependencies)."""

from datetime import datetime, timezone


class Invalid(ValueError):
    pass


class Missing(KeyError):
    pass


class Conflict(ValueError):
    pass


class Forbidden(PermissionError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text(value, field, limit=16000, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or "\x00" in value
        or (not empty and not value.strip())
    ):
        raise Invalid("Invalid " + field)
    return value.strip()


def version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Invalid("expected_version must be a nonnegative integer")
    return value
