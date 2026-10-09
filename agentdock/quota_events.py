"""Public Claude quota observations; never query a provider or read a login."""

import math
from datetime import datetime, timezone

WINDOWS = {
    "five_hour": ("session", 300),
    "seven_day": ("weekly", 10080),
    "seven_day_sonnet": ("weekly_sonnet", 10080),
    "seven_day_opus": ("weekly_opus", 10080),
}


def unknown():
    return {
        "status": "unknown",
        "windows": [],
        "source": "cli_event",
        "fetched_at": None,
    }


def legacy(value):
    """Preserve public historical samples without inventing a CLI provenance."""
    if not value.get("windows"):
        return unknown()
    return {
        **value,
        "source": "legacy_snapshot",
        "status": "stale",
        "error_code": None,
    }


def observe(payload, previous, observed=None):
    if payload.get("status") not in ("allowed", "allowed_warning", "rejected"):
        return None
    observed = observed or datetime.now(timezone.utc)
    timestamp = observed.timestamp()
    kind = payload.get("rateLimitType")
    name, duration = (
        WINDOWS.get(kind, ("primary", None))
        if isinstance(kind, str)
        else ("primary", None)
    )
    window = {"name": name}
    if duration:
        window["duration_minutes"] = duration
    utilization = payload.get("utilization")
    if payload.get("status") == "rejected":
        utilization = 1
    if (
        isinstance(utilization, (int, float))
        and not isinstance(utilization, bool)
        and math.isfinite(utilization)
        and 0 <= utilization <= 1
    ):
        window["remaining_percent"] = 100 * (1 - utilization)
    reset = payload.get("resetsAt")
    if (
        isinstance(reset, (int, float))
        and not isinstance(reset, bool)
        and math.isfinite(reset)
        and timestamp - 86400 < reset <= timestamp + 8 * 86400
    ):
        window["reset_at"] = datetime.fromtimestamp(reset, timezone.utc).isoformat()
    # A direct-query legacy sample must never be relabeled as a CLI event.
    windows = (
        [w for w in previous.get("windows", []) if w.get("name") != name]
        if previous.get("source") == "cli_event"
        else []
    )
    windows = (windows + [window])[-10:]
    return {
        "windows": windows,
        "source": "cli_event",
        "status": "ok" if any("remaining_percent" in w for w in windows) else "unknown",
        "fetched_at": observed.isoformat(),
    }


def device_snapshot(quota):
    labels = {
        "session": "5 hours",
        "weekly": "Weekly window",
        "weekly_sonnet": "Sonnet 7-day limit",
        "weekly_opus": "Opus 7-day limit",
    }
    return {
        "provider": "claude",
        **quota,
        "windows": [
            {**w, "label": labels.get(w["name"], "Quota")} for w in quota["windows"]
        ],
    }
