"""Versioned state snapshots and scoped change notifications."""

import copy
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

DOMAINS = {
    "projects",
    "agents",
    "sessions",
    "messages",
    "memories",
    "proposals",
    "runs",
    "approvals",
    "quotas",
    "subscriptions",
    "accounts",
    "environments",
    "tasks",
    "task_questions",
}
ALIASES = {
    "metadata": "features",
    "run_attempts": "account_attempts",
    "session_account_branches": "sessions",
}
WRITE = re.compile(
    r'^\s*(?:INSERT(?: OR \w+)? INTO|REPLACE INTO|UPDATE(?: OR \w+)?|DELETE FROM)\s+["`\[]?(\w+)',
    re.I,
)


class StateSync:
    def _initialize_sync(self, path):
        self._database_path = str(path)
        self._is_reader = False
        self._epoch = uuid.uuid4().hex
        self._revision = 0
        self._domain_versions = {}
        self._changed_tables = set()
        self._changed_sessions = set()
        self._session_conditions = {}
        self._activity_cache = {}
        self._activity_lock = threading.Lock()
        self.db.set_trace_callback(self._track_write)

    def _track_write(self, statement):
        # SQL contains bound values: extract only its table name and discard it.
        # Never log the statement or hold it in the change feed.
        match = WRITE.match(statement)
        if match:
            self._changed_tables.add(match[1].lower())

    def _publish_changes(self):
        domains = {
            ALIASES.get(table, table)
            for table in self._changed_tables
            if table in DOMAINS or table in ALIASES
        }
        if domains:
            self._revision += 1
            for domain in domains:
                self._domain_versions[domain] = self._revision
            self.changed.notify_all()
        for session_id in self._changed_sessions:
            condition = self._session_conditions.get(session_id)
            if condition:
                condition.notify_all()
        self._changed_tables.clear()
        self._changed_sessions.clear()

    def state_version(self):
        with self.lock:
            return self._epoch + ":" + str(self._revision)

    def changed_domains(self, since):
        if not isinstance(since, str) or not since.startswith(self._epoch + ":"):
            return None
        try:
            revision = int(since.split(":")[1])
        except ValueError:
            return None
        if revision < 0 or revision > self._revision:
            return None
        return {key for key, value in self._domain_versions.items() if value > revision}

    def wait_state_version(self, previous, stop, timeout=10):
        with self.changed:
            self.changed.wait_for(
                lambda: (
                    self.closed or stop.is_set() or self.state_version() != previous
                ),
                timeout,
            )
            return self.state_version()

    @contextmanager
    def reader(self):
        """A WAL snapshot gets its own read-only connection and lock.

        Pin the snapshot and copy revision metadata under the writer lock, then
        release it before fetching/serializing rows. In-memory test databases
        retain their existing connection instead of silently opening another DB.
        """
        if self._is_reader or self._database_path == ":memory:":
            with self.lock:
                yield self
            return
        connection = sqlite3.connect(
            Path(self._database_path).absolute().as_uri() + "?mode=ro",
            uri=True,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            with self.lock:
                connection.execute("BEGIN")
                connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
                reader = copy.copy(self)
                reader.db = connection
                reader.lock = threading.RLock()
                reader._is_reader = True
                reader._domain_versions = dict(self._domain_versions)
            yield reader
        finally:
            connection.close()
