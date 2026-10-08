"""Durable project-scoped state. Provider output is data, never authorization."""

from __future__ import annotations

import fcntl
import json
import posixpath
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .account_store import AccountStore
from .connection_store import ConnectionStore
from .deletions import DeletionStore
from .errors import Conflict, Invalid, Missing, now, text
from .errors import Forbidden as Forbidden
from .event_compaction import EventCompaction
from .event_store import EventStore
from .features import FeatureStore
from .memory_search import MemorySearch
from .memory_store import MemoryStore
from .message_store import MessageStore
from .permission_store import PermissionStore
from .project_policy import ProjectPolicy
from .run_store import RunStore
from .session_store import SessionStore
from .state_sync import StateSync
from .task_store import TaskStore


class Store(
    ConnectionStore,
    PermissionStore,
    MemoryStore,
    MessageStore,
    EventStore,
    RunStore,
    SessionStore,
    EventCompaction,
    ProjectPolicy,
    MemorySearch,
    FeatureStore,
    AccountStore,
    TaskStore,
    DeletionStore,
    StateSync,
):
    def __init__(self, path):
        self._existing_db = str(path) != ":memory:" and Path(path).expanduser().exists()
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.closed = False
        self._deletion_locks = {}
        self._file_lock = None
        self.workspaces = (
            Path(path).expanduser().resolve().parent
            if str(path) != ":memory:"
            else Path(tempfile.gettempdir()) / "agentdock-tests"
        ) / "workspaces"
        if str(path) != ":memory:":
            path = Path(path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._file_lock = open(str(path) + ".lock", "a")
            Path(str(path) + ".lock").chmod(0o600)
            try:
                fcntl.flock(self._file_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self._file_lock.close()
                self._file_lock = None
                raise Conflict("Another AgentDock instance owns this data directory")
        self.db = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),name TEXT NOT NULL,provider TEXT NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),agent_id TEXT NOT NULL REFERENCES agents(id),title TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),project_id TEXT NOT NULL,agent_id TEXT NOT NULL,prompt TEXT NOT NULL,status TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS active_agent_run ON runs(agent_id) WHERE status='running';
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,session_id TEXT,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS session_event ON events(session_id,seq);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,sender_id TEXT NOT NULL,recipient_id TEXT NOT NULL REFERENCES agents(id),body TEXT NOT NULL,correlation_id TEXT,status TEXT NOT NULL,idempotency_key TEXT,created_at TEXT NOT NULL,acknowledged_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS message_dedup ON messages(project_id,sender_id,idempotency_key) WHERE idempotency_key IS NOT NULL;
        CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,key TEXT NOT NULL,content TEXT NOT NULL,version INTEGER NOT NULL,author TEXT NOT NULL,source TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,key));
        CREATE TABLE IF NOT EXISTS memory_versions(id INTEGER PRIMARY KEY AUTOINCREMENT,memory_id TEXT NOT NULL,version INTEGER NOT NULL,content TEXT NOT NULL,author TEXT NOT NULL,source TEXT NOT NULL,archived INTEGER NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,agent_id TEXT NOT NULL,run_id TEXT NOT NULL,key TEXT NOT NULL,content TEXT NOT NULL,expected_version INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,session_id TEXT NOT NULL,project_id TEXT NOT NULL,request TEXT NOT NULL,options TEXT NOT NULL,status TEXT NOT NULL,picked_option_id TEXT,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS capabilities(hash TEXT PRIMARY KEY,run_id TEXT NOT NULL,expires_at TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS quotas(provider TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS subscriptions(provider TEXT PRIMARY KEY,plan TEXT NOT NULL,renewal_date TEXT,monthly_cost REAL,currency TEXT NOT NULL);
        """)
        migrations = (
            self._migrate_dispatch,
            self._migrate_independent_agents,
            self._migrate_environments,
            self._migrate_session_workspaces,
            self._migrate_inference_settings,
            self._migrate_project_agents,
            self._migrate_accounts,
            self._migrate_tasks,
            self._migrate_read_indexes,
            self._migrate_deletions,
            self._migrate_run_limits,
            self._migrate_project_policy,
            self._migrate_memory_search,
        )
        applied = self.db.execute("PRAGMA user_version").fetchone()[0]
        if applied > len(migrations):
            raise Conflict("This database requires a newer AgentDock version")
        for number, migrate in enumerate(migrations, 1):
            if number > applied:
                migrate()
                self.db.execute("PRAGMA user_version=" + str(number))
        from .metrics import initialize

        initialize(self.db)
        if str(path) != ":memory:":
            Path(path).chmod(0o600)
        with self.transaction():
            self.db.execute(
                "UPDATE run_attempts SET status='interrupted',finished_at=? WHERE status='running'",
                (now(),),
            )
            self.db.execute(
                "UPDATE tasks SET status='interrupted' WHERE status IN ('active','waiting_input','review') AND id IN (SELECT work_task_id FROM runs WHERE status IN ('running','queued'))"
            )
            self.db.execute(
                "UPDATE runs SET status='interrupted',error='Workbench restarted; explicit rerun required',updated_at=? WHERE status IN ('running','queued')",
                (now(),),
            )
            self.db.execute(
                "UPDATE sessions SET status='interrupted',updated_at=? WHERE status IN ('running','queued')",
                (now(),),
            )
            self.db.execute(
                "UPDATE messages SET status='interrupted',error='Workbench restarted; explicit rerun required',updated_at=? WHERE status IN ('running','queued','waiting')",
                (now(),),
            )
            self.db.execute(
                "UPDATE approvals SET status='cancelled' WHERE status='pending'"
            )
            self.db.execute("UPDATE capabilities SET revoked=1")
            self.db.execute(
                "UPDATE task_inputs SET status='unknown' WHERE status='pending'"
            )
            self.db.execute(
                "UPDATE task_inputs SET status='interrupted' WHERE status IN ('queued','accepted')"
            )
        self._initialize_sync(path)

    def _migrate_run_limits(self):
        with self.transaction():
            if "run_timeout" not in {
                row[1] for row in self.db.execute("PRAGMA table_info(agents)")
            }:
                self.db.execute("ALTER TABLE agents ADD COLUMN run_timeout INTEGER")

    @staticmethod
    def _run_timeout(value):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 30 <= value <= 86400
        ):
            raise Invalid("Agent execution time must be between 30 and 86400 seconds")
        return value

    def _migrate_read_indexes(self):
        # Run on existing databases too. Correlated cancellation queries otherwise
        # scan the entire run/message history once for every logical task.
        with self.transaction():
            self.db.execute("CREATE INDEX IF NOT EXISTS runs_task ON runs(task_run_id)")
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id)"
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS messages_sender_run ON messages(sender_run_id)"
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS events_run ON events(json_extract(payload, '$.run_id'), seq)"
            )

    def _migrate_dispatch(self):
        # Additive migration keeps earlier workspaces, history and memory intact.
        columns = {
            "sessions": {"native_session_id": "TEXT"},
            "runs": {
                "origin": "TEXT NOT NULL DEFAULT 'human'",
                "parent_run_id": "TEXT",
                "root_run_id": "TEXT",
                "depth": "INTEGER NOT NULL DEFAULT 0",
                "delivery_id": "TEXT",
                "result": "TEXT",
                "task_run_id": "TEXT",
            },
            "messages": {
                "sender_session_id": "TEXT",
                "recipient_session_id": "TEXT",
                "sender_run_id": "TEXT",
                "run_id": "TEXT",
                "reply_run_id": "TEXT",
                "error": "TEXT",
                "updated_at": "TEXT",
                "result": "TEXT",
            },
        }
        with self.transaction():
            for table, additions in columns.items():
                existing = {
                    row[1]
                    for row in self.db.execute("PRAGMA table_info(" + table + ")")
                }
                for name, definition in additions.items():
                    if name not in existing:
                        self.db.execute(
                            "ALTER TABLE "
                            + table
                            + " ADD COLUMN "
                            + name
                            + " "
                            + definition
                        )
            self.db.execute("UPDATE runs SET root_run_id=id WHERE root_run_id IS NULL")
            self.db.execute(
                "UPDATE runs SET task_run_id=id WHERE task_run_id IS NULL AND origin<>'reply'"
            )
            for _ in range(16):
                self.db.execute(
                    "UPDATE runs SET task_run_id=(SELECT sender.task_run_id FROM messages JOIN runs AS sender ON messages.sender_run_id=sender.id WHERE messages.id=runs.delivery_id) WHERE task_run_id IS NULL AND origin='reply'"
                )
            self.db.execute("UPDATE runs SET task_run_id=id WHERE task_run_id IS NULL")
            # Old mailbox rows are historical records, never executable deliveries.
            self.db.execute(
                "UPDATE messages SET status='legacy',updated_at=COALESCE(updated_at,created_at) WHERE run_id IS NULL"
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS pending_runs ON runs(status,created_at)"
            )
            self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS delivery_run ON messages(run_id) WHERE run_id IS NOT NULL"
            )
            self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS delivery_reply ON messages(reply_run_id) WHERE reply_run_id IS NOT NULL"
            )

    def _migrate_independent_agents(self):
        # SQLite cannot drop NOT NULL in place. Rebuild without renaming the old
        # table so foreign-key targets stay unchanged; preserve indexes and rows.
        legacy = self.db.execute(
            "SELECT sql FROM sqlite_master WHERE name='agents'"
        ).fetchone()[0]
        if self._existing_db and "project_id TEXT NOT NULL" in legacy:
            backup_dir = self.workspaces.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup_path = backup_dir / ("pre-0.3-" + uuid.uuid4().hex + ".sqlite3")
            backup = sqlite3.connect(str(backup_path))
            try:
                self.db.backup(backup)
            finally:
                backup.close()
            backup_path.chmod(0o600)
        self.db.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.transaction():
                for table in ("agents", "sessions", "runs", "events", "approvals"):
                    sql = self.db.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()[0]
                    if "project_id TEXT NOT NULL" not in sql:
                        continue
                    indexes = [
                        r[0]
                        for r in self.db.execute(
                            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                            (table,),
                        )
                    ]
                    new_sql = sql.replace(
                        "CREATE TABLE " + table, "CREATE TABLE " + table + "_new", 1
                    ).replace("project_id TEXT NOT NULL", "project_id TEXT")
                    self.db.execute(new_sql)
                    self.db.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
                    self.db.execute(f"DROP TABLE {table}")
                    self.db.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
                    for index in indexes:
                        self.db.execute(index)
                for table, fields in {
                    "agents": {
                        "workspace": "TEXT",
                        "model": "TEXT",
                        "effort": "TEXT",
                        "permission_mode": "TEXT NOT NULL DEFAULT 'ask' CHECK(permission_mode IN ('ask','full_access'))",
                    },
                    "sessions": {"workspace": "TEXT", "legacy_workspace": "TEXT"},
                }.items():
                    existing = {
                        r[1]
                        for r in self.db.execute("PRAGMA table_info(" + table + ")")
                    }
                    for name, definition in fields.items():
                        if name not in existing:
                            self.db.execute(
                                f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                            )
                self.db.execute(
                    "UPDATE agents SET workspace=(SELECT path FROM projects WHERE projects.id=agents.project_id) WHERE workspace IS NULL"
                )
                self.db.execute(
                    "UPDATE sessions SET workspace=(SELECT workspace FROM agents WHERE agents.id=sessions.agent_id) WHERE workspace IS NULL"
                )
                if self.db.execute("PRAGMA foreign_key_check").fetchone():
                    raise Conflict("Database migration failed integrity validation")
        finally:
            self.db.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _permission_mode(value):
        if value not in ("ask", "full_access"):
            raise Invalid("Invalid agent permission mode")
        return value

    def _migrate_project_agents(self):
        # A project member has its own execution identity. The source link is
        # provenance only: updates/deletion must never cascade into other projects.
        with self.transaction():
            if "source_agent_id" not in {
                r[1] for r in self.db.execute("PRAGMA table_info(agents)")
            }:
                self.db.execute(
                    "ALTER TABLE agents ADD COLUMN source_agent_id TEXT REFERENCES agents(id) ON DELETE SET NULL"
                )

    def add_project_agent(self, project_id, changes):
        if not isinstance(changes, dict) or set(changes) - {
            "source_agent_id",
            "name",
            "role",
            "workspace",
        }:
            raise Invalid("Invalid project agent settings")
        with self.transaction():
            project = self._one("projects", project_id)
            source = self._available(
                "agents", text(changes.get("source_agent_id"), "source_agent_id", 160)
            )
            workspace = changes.get("workspace")
            if project["environment_id"] != source["environment_id"] and not workspace:
                raise Invalid(
                    "Choose this project's working directory on the agent device"
                )
            item = {
                **source,
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "source_agent_id": source["id"],
                "created_at": now(),
                "name": text(changes.get("name", source["name"]), "name", 100),
                "role": text(changes.get("role", source["role"]), "role", 4000, True),
            }
            # Never copy the source's workspace or any native history. Same-device
            # members use the target project directory; cross-device paths are explicit.
            item["workspace"] = self._workspace(
                project_id, workspace, item["id"], item["environment_id"]
            )
            self.db.execute(
                """INSERT INTO agents(id,project_id,name,provider,role,created_at,workspace,model,effort,environment_id,permission_mode,source_agent_id)
                VALUES(:id,:project_id,:name,:provider,:role,:created_at,:workspace,:model,:effort,:environment_id,:permission_mode,:source_agent_id)""",
                item,
            )
            self.db.execute(
                "UPDATE agents SET account_id=?,account_policy=?,account_ids=? WHERE id=?",
                (
                    source["account_id"],
                    source["account_policy"],
                    json.dumps(source["account_ids"]),
                    item["id"],
                ),
            )
            self.db.execute(
                "UPDATE agents SET run_timeout=? WHERE id=?",
                (source["run_timeout"], item["id"]),
            )
            return item

    def _migrate_inference_settings(self):
        with self.transaction():
            for table, fields in {
                "sessions": {
                    "model": "TEXT",
                    "effort": "TEXT",
                    "model_override": "INTEGER NOT NULL DEFAULT 0",
                    "agent_defaults": "TEXT",
                },
                "runs": {"model": "TEXT", "effort": "TEXT", "permission_mode": "TEXT"},
            }.items():
                existing = {
                    r[1] for r in self.db.execute("PRAGMA table_info(" + table + ")")
                }
                for name, definition in fields.items():
                    if name not in existing:
                        self.db.execute(
                            "ALTER TABLE "
                            + table
                            + " ADD COLUMN "
                            + name
                            + " "
                            + definition
                        )

    def _migrate_environments(self):
        if self._existing_db and "environment_id" not in {
            r[1] for r in self.db.execute("PRAGMA table_info(agents)")
        }:
            directory = self.workspaces.parent / "backups"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination = directory / ("pre-ssh-" + uuid.uuid4().hex + ".sqlite3")
            backup = sqlite3.connect(str(destination))
            try:
                self.db.backup(backup)
            finally:
                backup.close()
            destination.chmod(0o600)
        with self.transaction():
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS environments(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,ssh_host TEXT,python TEXT NOT NULL DEFAULT 'python3',status TEXT NOT NULL DEFAULT 'disconnected',payload TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL)"
            )
            self.db.execute(
                "INSERT OR IGNORE INTO environments(id,name,kind,status,updated_at) VALUES('local','This Mac','local','connected',?)",
                (now(),),
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
            )
            self.db.execute(
                "INSERT OR IGNORE INTO metadata VALUES('controller_id',?)",
                (str(uuid.uuid4()),),
            )
            for table in ("projects", "agents", "sessions"):
                if "environment_id" not in {
                    r[1] for r in self.db.execute("PRAGMA table_info(" + table + ")")
                }:
                    self.db.execute(
                        "ALTER TABLE "
                        + table
                        + " ADD COLUMN environment_id TEXT NOT NULL DEFAULT 'local'"
                    )

    @property
    def controller_id(self):
        with self.lock:
            return self.db.execute(
                "SELECT value FROM metadata WHERE key='controller_id'"
            ).fetchone()[0]

    def _workspace(self, project_id, workspace, identifier, environment_id="local"):
        environment = self._one("environments", environment_id)
        if project_id and not workspace:
            project = self._one("projects", project_id)
            if project["environment_id"] == environment_id:
                workspace = project["path"]
        if environment["kind"] == "ssh":
            if not workspace:
                return "~/.local/share/agentdock/workspaces/" + identifier
            path = text(workspace, "workspace", 4096)
            if not path.startswith("/") or any(ord(c) < 32 for c in path):
                raise Invalid("Use an absolute directory on the remote host")
            return posixpath.normpath(path)
        if workspace:
            path = Path(text(workspace, "workspace", 4096)).expanduser()
            if not path.is_absolute() or not path.is_dir():
                raise Invalid("Choose an existing absolute workspace directory")
            return str(path.resolve())
        path = self.workspaces / identifier
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return str(path)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
                if hasattr(self, "_changed_tables"):
                    self._publish_changes()
                else:
                    self.changed.notify_all()
            except BaseException:
                self.db.execute("ROLLBACK")
                if hasattr(self, "_changed_tables"):
                    self._changed_tables.clear()
                    self._changed_sessions.clear()
                raise

    def close(self):
        with self.lock:
            self.closed = True
            self.changed.notify_all()
            for condition in getattr(self, "_session_conditions", {}).values():
                condition.notify_all()
            self.db.close()
            if self._file_lock:
                fcntl.flock(self._file_lock.fileno(), fcntl.LOCK_UN)
                self._file_lock.close()
                self._file_lock = None

    def _one(self, table, identifier):
        row = self.db.execute(
            "SELECT * FROM " + table + " WHERE id=?", (identifier,)
        ).fetchone()
        if not row:
            raise Missing(table + " not found")
        return self._decode(dict(row))

    @staticmethod
    def _decode(row):
        for key in (
            "payload",
            "options",
            "request",
            "quota",
            "account_ids",
            "identity",
            "checks",
            "artifacts",
        ):
            if key in row:
                row[key] = json.loads(row[key])
        if row.get("agent_defaults") is not None:
            row["agent_defaults"] = json.loads(row["agent_defaults"])
        return row

    def _all(self, query, args=()):
        return [self._decode(dict(x)) for x in self.db.execute(query, args).fetchall()]

    def get_project(self, identifier):
        with self.lock:
            return self._one("projects", identifier)

    def get_agent(self, identifier):
        with self.lock:
            return self._one("agents", identifier)

    def session_agent(self, session_id):
        """Execution settings belong to the conversation, even after its agent moves."""
        with self.lock:
            session = self._one("sessions", session_id)
            agent = self._one("agents", session["agent_id"])
            return {
                **agent,
                **(session["agent_defaults"] or {}),
                **{
                    key: session[key]
                    for key in (
                        "environment_id",
                        "workspace",
                        "project_id",
                        "account_id",
                        "account_policy",
                        "account_ids",
                    )
                },
            }

    def get_session(self, identifier):
        with self.lock:
            return self._one("sessions", identifier)

    def get_run(self, identifier):
        with self.lock:
            return self._one("runs", identifier)

    def get_message(self, identifier):
        with self.lock:
            return self._one("messages", identifier)

    def get_approval(self, identifier):
        with self.lock:
            return self._one("approvals", identifier)

    def state(self, since=None):
        if not self._is_reader:
            with self.reader() as reader:
                return reader._state_snapshot(since)
        return self._state_snapshot(since)

    def _state_snapshot(self, since=None):
        with self.lock:
            domains = self.changed_domains(since)
            if domains == set():
                return {"version": self.state_version(), "partial": True}
            result = {
                name: self._all("SELECT * FROM " + name + " ORDER BY created_at")
                for name in (
                    "projects",
                    "agents",
                    "sessions",
                    "messages",
                    "memories",
                    "proposals",
                )
                if domains is None or name in domains
            }
            for agent in result.get("agents", []):
                agent["workspace_is_default"] = self._automatic_workspace(
                    agent["workspace"], agent["id"], agent["environment_id"]
                )
            if domains is None or "runs" in domains:
                result["runs"] = self._all(
                    "SELECT * FROM runs WHERE id IN (SELECT id FROM runs ORDER BY created_at DESC,rowid DESC LIMIT 300) ORDER BY created_at,rowid"
                )
            if domains is None or "events" in domains:
                result["events"] = self._all(
                    "SELECT * FROM (SELECT * FROM events ORDER BY seq DESC LIMIT 300) ORDER BY seq"
                )
            if domains is None or "approvals" in domains:
                result["approvals"] = self._all(
                    "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at"
                )
            if domains is None or "quotas" in domains:
                result["quotas"] = [
                    json.loads(row[0])
                    for row in self.db.execute("SELECT payload FROM quotas")
                ]
            if domains is None or "subscriptions" in domains:
                result["subscriptions"] = self._all("SELECT * FROM subscriptions")
            for item in result.get("subscriptions", []):
                if ":" in item["provider"]:
                    item["environment_id"], item["provider"] = item["provider"].split(
                        ":", 1
                    )
            if domains is None or "accounts" in domains:
                result["accounts"] = self.accounts(include_removed=True)
            if domains is None or "account_attempts" in domains:
                result["account_attempts"] = self._all(
                    "SELECT * FROM run_attempts ORDER BY created_at DESC LIMIT 300"
                )
            if domains is None or "environments" in domains:
                result["environments"] = self.environments()
            if domains is None or "tasks" in domains:
                result["tasks"] = self._all(
                    "SELECT * FROM tasks ORDER BY updated_at DESC,rowid DESC"
                )
            if domains is None or "task_questions" in domains:
                result["task_questions"] = self._all(
                    "SELECT * FROM task_questions WHERE status='open' ORDER BY created_at"
                )
            result.update(version=self.state_version(), partial=domains is not None)
            return result
