"""Opt-in, bounded usage helper. Provider credentials never enter the HTTP service."""
from __future__ import annotations

import json
import math
import selectors
import subprocess
import threading
import time
from datetime import datetime, timezone

from .processes import stop_group as _kill_group
from .store import Forbidden

ERRORS = {
    "authorization_required": "Connect Claude to approve access to its existing Keychain credential.",
    "not_installed": "The provider CLI is not installed or cannot be found.",
    "not_signed_in": "Sign in to a subscription account in the official client first.",
    "expired": "The provider login has expired. Sign in again in its official client.",
    "rate_limited": "The provider is rate limiting usage requests. Try again later.",
    "timeout": "The usage request timed out. Try again later.",
    "unavailable": "Usage is unavailable. Check the provider login, plan and network.",
}


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
    AUTO_REFRESH_INTERVAL = 600

    def __init__(self, store, command: list[str] | None, execution_enabled: bool, source="AgentDock"):
        self.store, self.command = store, list(command) if command else None
        self.source = source
        self.execution_enabled = execution_enabled
        self._last_attempt = {}
        self._lock = threading.Lock()
        self._lifecycle = threading.Condition(threading.RLock())
        self._closed = False
        self._inflight = 0
        self._processes = set()
        self._auto_stop = threading.Event()
        self._auto_thread = None

    def start_auto_refresh(self) -> None:
        """One service-owned timer, independent of visible windows or browser tabs."""
        with self._lifecycle:
            self._ensure_open()
            if not self.execution_enabled or not self.command or self._auto_thread is not None:
                return
            self._auto_thread = threading.Thread(target=self._auto_refresh, name="quota-refresh", daemon=True)
            self._auto_thread.start()

    def _auto_refresh(self):
        deadline = time.monotonic() + self.AUTO_REFRESH_INTERVAL
        while not self._auto_stop.wait(max(0, deadline - time.monotonic())):
            for provider in ("codex", "claude"):
                if self._auto_stop.is_set():
                    return
                try:
                    self.refresh(provider)  # Non-interactive; never request Keychain authorization.
                except Forbidden:
                    return
                except Exception:
                    # Isolate provider failures; retry at the next tick without logging credentials.
                    continue
            now = time.monotonic()
            deadline += self.AUTO_REFRESH_INTERVAL
            if deadline <= now:
                deadline = now + self.AUTO_REFRESH_INTERVAL  # No catch-up burst after suspension.

    def refresh(self, provider: str, authorize=False) -> dict:
        if provider not in ("codex", "claude"):
            raise ValueError("Only codex and claude quota providers are supported.")
        if authorize and (provider != "claude" or self.source != "AgentDock"):
            raise ValueError("Interactive authorization requires the built-in Claude helper.")
        with self._lifecycle:
            self._ensure_open()
            self._inflight += 1
        try:
            return self._refresh(provider, authorize)
        finally:
            with self._lifecycle:
                self._inflight -= 1
                self._lifecycle.notify_all()

    def close(self) -> None:
        """Stop owned probes and drain refresh callers before their Store is closed."""
        with self._lifecycle:
            self._closed = True
            self._auto_stop.set()
            processes = list(self._processes)
        for process in processes:
            _kill_group(process)
        with self._lifecycle:
            while self._inflight:
                self._lifecycle.wait(timeout=0.1)
        if self._auto_thread is not None:
            self._auto_thread.join()

    def _ensure_open(self):
        if self._closed:
            raise Forbidden("Quota service is closed.")

    def _save(self, provider, quota):
        with self._lifecycle:
            self._ensure_open()
            self.store.set_quota(provider, quota)

    def _refresh(self, provider: str, authorize=False) -> dict:
        with self._lock:
            with self._lifecycle:
                self._ensure_open()
            if not self.execution_enabled:
                return self._failure(provider, "Quota reads are disabled until execution is enabled.", "disabled", code="disabled")
            if not self.command:
                return self._failure(provider, "Configure the local usage helper first.", code="helper_unconfigured")
            if (not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in self.command)):
                return self._failure(provider, "Usage helper command configuration is invalid.", code="helper_config_invalid")
            now = time.monotonic()
            if not authorize and provider in self._last_attempt and now - self._last_attempt[provider] < 60:
                cached = self.cached(provider)
                if cached:
                    return self._expire(cached)
                return self._failure(provider, "Please wait before refreshing again.", code="refresh_throttled")
            self._last_attempt[provider] = now
            try:
                raw = self._probe(provider, authorize=True) if authorize else self._probe(provider)
                if isinstance(raw, dict) and raw.get("provider") == provider and raw.get("error_code") in ERRORS:
                    return self._failure(provider, ERRORS[raw["error_code"]], code=raw["error_code"])
                quota = self._normalize(provider, raw)
            except Forbidden:
                raise
            except TimeoutError:
                return self._failure(provider, "Usage helper timed out; its process was stopped.", code="timeout")
            except (ValueError, UnicodeError, TypeError):
                return self._failure(provider, "Usage helper returned an invalid quota snapshot.", code="invalid_snapshot")
            except (OSError, RuntimeError):
                return self._failure(provider, "Usage helper could not read this provider. Check its local login and permissions.", code="read_failed")
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

    def _probe(self, provider, authorize=False):
        # Spawning and registration share the close lock: shutdown cannot miss a
        # process between its creation and insertion into the active set.
        selector = selectors.DefaultSelector()
        try:
            with self._lifecycle:
                self._ensure_open()
                process = subprocess.Popen(self.command + ["--authorize" if authorize else "--probe", provider], stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=True, bufsize=0)
                self._processes.add(process)
        except BaseException:
            selector.close()
            raise
        output, total = bytearray(), 0
        deadline = time.monotonic() + (180 if authorize else self.TIMEOUT)
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
                             "source": self.source})

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
            outdated = "Cached quota is outdated. Refresh to read current limits."
            if not quota.get("error") or quota.get("error") == outdated:
                quota.update(error=outdated, error_code="outdated_cache")
        return quota

    def _failure(self, provider, error, status="unavailable", code=None):
        with self._lifecycle:
            self._ensure_open()
            previous = self.store.get_quota(provider)
            if previous and previous.get("fetched_at") and status != "disabled":
                quota = self._expire(previous)
                quota.update(status="stale", error=error)
            else:
                quota = {"provider": provider, "plan": None, "windows": [], "fetched_at": None,
                         "status": status, "error": error, "source": self.source}
            quota.pop("error_code", None)
            if code: quota["error_code"] = code
            self._save(provider, quota)
            return quota
