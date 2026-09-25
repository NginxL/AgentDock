"""Opt-in, read-only AgentMeter bridge. No provider credentials are read here."""
from __future__ import annotations

import json
import math
import selectors
import subprocess
import threading
import time
from datetime import datetime, timezone

from .runtime import _kill_group
from .store import Forbidden


def _date(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value, length):
    return value[:length] if isinstance(value, str) else None


class QuotaService:
    TIMEOUT = 35
    MAX_OUTPUT = 1048576
    MAX_AGE = 900

    def __init__(self, store, command: list[str] | None, execution_enabled: bool):
        self.store, self.command = store, list(command) if command else None
        self.execution_enabled = execution_enabled
        self._last_attempt = {}
        self._lock = threading.Lock()
        self._lifecycle = threading.Condition(threading.RLock())
        self._closed = False
        self._inflight = 0
        self._processes = set()

    def refresh(self, provider: str) -> dict:
        if provider not in ("codex", "claude"):
            raise ValueError("Only codex and claude quota providers are supported.")
        with self._lifecycle:
            self._ensure_open()
            self._inflight += 1
        try:
            return self._refresh(provider)
        finally:
            with self._lifecycle:
                self._inflight -= 1
                self._lifecycle.notify_all()

    def close(self) -> None:
        """Stop owned probes and drain refresh callers before their Store is closed."""
        with self._lifecycle:
            self._closed = True
            processes = list(self._processes)
        for process in processes:
            _kill_group(process)
        with self._lifecycle:
            while self._inflight:
                self._lifecycle.wait(timeout=0.1)

    def _ensure_open(self):
        if self._closed:
            raise Forbidden("Quota service is closed.")

    def _save(self, provider, quota):
        with self._lifecycle:
            self._ensure_open()
            self.store.set_quota(provider, quota)

    def _refresh(self, provider: str) -> dict:
        with self._lock:
            with self._lifecycle:
                self._ensure_open()
            if not self.execution_enabled:
                return self._failure(provider, "Quota reads are disabled until execution is enabled.", "disabled")
            if not self.command:
                return self._failure(provider, "Configure the local AgentMeter executable first.")
            if (not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in self.command)):
                return self._failure(provider, "AgentMeter command configuration is invalid.")
            now = time.monotonic()
            if provider in self._last_attempt and now - self._last_attempt[provider] < 60:
                cached = self.cached(provider)
                if cached:
                    return self._expire(cached)
                return self._failure(provider, "Please wait before refreshing again.")
            self._last_attempt[provider] = now
            try:
                raw = self._probe(provider)
                quota = self._normalize(provider, raw)
            except Forbidden:
                raise
            except TimeoutError:
                return self._failure(provider, "AgentMeter timed out; its process was stopped.")
            except (ValueError, UnicodeError, TypeError):
                return self._failure(provider, "AgentMeter returned an invalid quota snapshot.")
            except (OSError, RuntimeError):
                return self._failure(provider, "AgentMeter could not read this provider. Check its local login and permissions.")
            self._save(provider, quota)
            return quota

    def cached(self, provider: str):
        """Age a saved snapshot for display without starting a process or reading credentials."""
        if provider not in ("codex", "claude"):
            raise ValueError("Unsupported quota provider.")
        with self._lifecycle:
            self._ensure_open()
            snapshot = self.store.get_quota(provider)
        return self._expire(snapshot) if snapshot else None

    def _probe(self, provider):
        # Spawning and registration share the close lock: shutdown cannot miss a
        # process between its creation and insertion into the active set.
        selector = selectors.DefaultSelector()
        try:
            with self._lifecycle:
                self._ensure_open()
                process = subprocess.Popen(self.command + ["--probe", provider], stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=True, bufsize=0)
                self._processes.add(process)
        except BaseException:
            selector.close()
            raise
        output, total = bytearray(), 0
        deadline = time.monotonic() + self.TIMEOUT
        try:
            for stream, kind in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                selector.register(stream, selectors.EVENT_READ, kind)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                for key, _ in selector.select(timeout=0.1):
                    data = key.fileobj.read(65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(data)
                    if total > self.MAX_OUTPUT:
                        raise ValueError("Output limit exceeded")
                    if key.data == "stdout":
                        output.extend(data)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise TimeoutError()
            if code != 0:
                raise RuntimeError("Probe failed")
            return json.loads(output)
        finally:
            selector.close()
            try:
                _kill_group(process)
            finally:
                process.stdout.close()
                process.stderr.close()
                with self._lifecycle:
                    self._processes.discard(process)

    def _normalize(self, provider, raw):
        if not isinstance(raw, dict) or raw.get("provider") != provider:
            raise ValueError("Provider mismatch")
        fetched = _date(raw.get("fetchedAt"))
        if fetched is None or (fetched - _now()).total_seconds() > 60:
            raise ValueError("Invalid fetchedAt")
        raw_windows = raw.get("windows")
        if not isinstance(raw_windows, list) or len(raw_windows) > 20:
            raise ValueError("Invalid windows")
        windows = []
        for entry in raw_windows:
            if not isinstance(entry, dict):
                raise ValueError("Invalid window")
            used = entry.get("usedPercent")
            if used is not None and (isinstance(used, bool) or not isinstance(used, (int, float))
                                     or not math.isfinite(used) or not 0 <= used <= 100):
                raise ValueError("Invalid percentage")
            reset = _date(entry.get("resetsAt"))
            if entry.get("resetsAt") is not None and reset is None:
                raise ValueError("Invalid reset date")
            windows.append({
                "label": _text(entry.get("title", entry.get("label")), 120) or "Quota",
                "remaining_percent": None if used is None else round(100 - used, 4),
                "reset_at": _iso(reset) if reset else None,
            })
        return self._expire({"provider": provider, "plan": _text(raw.get("plan"), 120),
                             "windows": windows, "fetched_at": _iso(fetched),
                             "status": "available" if any(w["remaining_percent"] is not None for w in windows) else "unknown",
                             "source": "AgentMeter"})

    def _expire(self, snapshot):
        # Return a copy so cache aging never mutates Store-owned values in memory.
        quota = json.loads(json.dumps(snapshot))
        now = _now()
        fetched = _date(quota.get("fetched_at"))
        old = fetched is not None and (now - fetched).total_seconds() > self.MAX_AGE
        for window in quota.get("windows", []):
            reset = _date(window.get("reset_at"))
            if reset is not None and reset <= now:
                window["remaining_percent"] = None
                old = True
        if old and quota.get("status") in ("available", "unknown", "stale"):
            quota["status"] = "stale"
            quota.setdefault("error", "Cached quota is outdated. Refresh to read current limits.")
        return quota

    def _failure(self, provider, error, status="unavailable"):
        with self._lifecycle:
            self._ensure_open()
            previous = self.store.get_quota(provider)
            if previous and previous.get("fetched_at") and status != "disabled":
                quota = self._expire(previous)
                quota.update(status="stale", error=error)
            else:
                quota = {"provider": provider, "plan": None, "windows": [], "fetched_at": None,
                         "status": status, "error": error, "source": "AgentMeter"}
            self._save(provider, quota)
            return quota
