"""Read-only directory navigation on the machine that owns the workspace."""

import os
from pathlib import Path


def list_directories(path="~"):
    if not isinstance(path, str) or len(path) > 4096 or any(ord(c) < 32 for c in path):
        raise ValueError("Invalid directory path")
    target = Path(path or "~").expanduser()
    if not target.is_absolute():
        raise ValueError("Use an absolute directory path")
    try:
        target = target.resolve(strict=True)
        entries = []
        truncated = False
        with os.scandir(target) as listing:
            for count, entry in enumerate(listing):
                if count >= 5000 or len(entries) >= 200:
                    truncated = True
                    break
                try:
                    if entry.is_dir() and not any(ord(c) < 32 for c in entry.name):
                        entries.append(
                            {"name": entry.name, "path": str(target / entry.name)}
                        )
                except OSError:
                    continue
    except (OSError, RuntimeError):
        raise ValueError("Unable to list this directory") from None
    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "directories": sorted(entries, key=lambda item: item["name"].casefold()),
        "truncated": truncated,
    }
