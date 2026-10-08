"""Structured diagnostics: allowlisted metadata, never request/exception text."""

import base64
import io
import json
import logging
import os
import platform
import re
import traceback
import uuid
import zipfile
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__

_logger = logging.getLogger("agentdock.diagnostics")
_logger.propagate = False
_logger.addHandler(logging.NullHandler())


class PrivateHandler(RotatingFileHandler):
    def _open(self):
        descriptor = os.open(
            self.baseFilename,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "a", encoding="utf-8")


def configure(data_directory):
    root = Path(data_directory) / "logs"
    if root.is_symlink():
        raise ValueError("Invalid diagnostics directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    handler = PrivateHandler(
        root / "agentdock.jsonl", maxBytes=1024 * 1024, backupCount=3
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    for old in _logger.handlers[:]:
        _logger.removeHandler(old)
        old.close()
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    return root


def failure(error, component="api"):
    identifier = uuid.uuid4().hex[:16]
    # Exception messages, locals, source lines, URLs, command arguments and
    # arbitrary payloads are deliberately excluded, including chained exceptions.
    frames = []
    for frame in traceback.extract_tb(error.__traceback__):
        path = Path(frame.filename)
        if path.parent.name == "agentdock":
            frames.append(
                {"module": path.stem, "line": frame.lineno, "function": frame.name}
            )
    entry = {
        "error_id": identifier,
        "at": datetime.now(timezone.utc).isoformat(),
        "component": component
        if component in ("api", "runtime", "usage", "accounts", "startup")
        else "runtime",
        "category": type(error).__name__
        if re.fullmatch("[A-Za-z_]{1,80}", type(error).__name__)
        else "Exception",
        "frames": frames[-12:],
    }
    _logger.error(json.dumps(entry, separators=(",", ":")))
    return identifier


def export(store):
    manifest = {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.system(),
    }
    with store.lock:
        manifest["schema_version"] = store.db.execute("PRAGMA user_version").fetchone()[
            0
        ]
        manifest["counts"] = {
            table: store.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ("agents", "sessions", "runs", "events")
        }
    records = []
    root = store.workspaces.parent / "logs"
    if root.is_dir() and not root.is_symlink():
        for path in sorted(root.glob("agentdock.jsonl*")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
                continue
            for line in path.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    # Reconstruct the public schema: never blindly export a log
                    # file or arbitrary fields another component may have added.
                    if not re.fullmatch("[a-f0-9]{16}", entry.get("error_id", "")):
                        continue
                    item = {"error_id": entry["error_id"]}
                    for key in ("at", "category", "component"):
                        value = entry.get(key, "")
                        if isinstance(value, str) and re.fullmatch(
                            "[A-Za-z0-9_:T+. -]{1,80}", value
                        ):
                            item[key] = value
                    item["frames"] = [
                        {key: frame[key] for key in ("module", "function", "line")}
                        for frame in entry.get("frames", [])[:12]
                        if isinstance(frame.get("line"), int)
                        and all(
                            re.fullmatch("[A-Za-z_]{1,80}", frame.get(key, ""))
                            for key in ("module", "function")
                        )
                    ]
                    records.append(item)
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("system.json", json.dumps(manifest, indent=2))
        archive.writestr(
            "errors.jsonl", "\n".join(json.dumps(r) for r in records[-2000:])
        )
    return {
        "filename": "agentdock-diagnostics.zip",
        "content_type": "application/zip",
        "data": base64.b64encode(output.getvalue()).decode(),
    }
