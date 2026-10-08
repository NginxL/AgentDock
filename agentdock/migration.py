"""Explicit, local-only import of billing metadata; never imports login credentials."""

import json
import plistlib
from datetime import datetime, timedelta, timezone
from pathlib import Path


def import_agentmeter(store, preferences, data_directory):
    preferences = Path(preferences)
    if not preferences.exists():
        return {"imported": 0, "skipped": 0}
    if preferences.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Preference file is too large")
    original = preferences.read_bytes()
    payload = plistlib.loads(original)
    raw = payload.get("subscriptions")
    rows = json.loads(raw) if isinstance(raw, (bytes, str)) else []
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Invalid subscription records")
    # Keep the complete preferences as a private local rollback copy, including fields
    # this workbench does not display. Do not publish this directory with application code.
    backup = Path(data_directory) / "backups" / "agentmeter-preferences.plist"
    backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not backup.exists():
        backup.write_bytes(original)
        backup.chmod(0o600)
    existing = {row["provider"] for row in store.state()["subscriptions"]}
    imported = skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        provider = row.get("provider")
        if provider not in ("codex", "claude") or provider in existing:
            skipped += 1
            continue
        renewal = None
        # Swift's default Codable Date is seconds since 2001-01-01, not Unix time.
        value = row.get("renewalDate")
        if (
            row.get("renewalKind", "renews") == "renews"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            try:
                renewal = (
                    (
                        datetime(2001, 1, 1, tzinfo=timezone.utc)
                        + timedelta(seconds=value)
                    )
                    .astimezone()
                    .date()
                    .isoformat()
                )
            except (OverflowError, ValueError):
                pass
        store.save_subscription(
            provider,
            row.get("plan", ""),
            renewal,
            row.get("monthlyCost"),
            row.get("currency", "USD"),
        )
        existing.add(provider)
        imported += 1
    return {"imported": imported, "skipped": skipped}
