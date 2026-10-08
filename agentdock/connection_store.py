"""ConnectionStore domain operations; mutations share the owning Store transaction."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from .errors import Conflict, Invalid, now, text
from .registry import PROVIDERS


class ConnectionStore:
    @staticmethod
    def scope_key(provider, environment_id="local"):
        return (
            provider if environment_id == "local" else environment_id + ":" + provider
        )

    @staticmethod
    def metric_identity(environment_id, native_id):
        return (
            native_id if environment_id == "local" else environment_id + ":" + native_id
        )

    def set_quota(self, provider, quota, environment_id="local"):
        if provider not in PROVIDERS:
            raise Invalid("Unsupported provider")
        self.get_environment(environment_id)
        if environment_id != "local":
            quota = {**quota, "environment_id": environment_id}
        with self.transaction():
            self.db.execute(
                "INSERT OR REPLACE INTO quotas VALUES(?,?)",
                (self.scope_key(provider, environment_id), json.dumps(quota)),
            )

    def get_quota(self, provider, environment_id="local"):
        with self.lock:
            row = self.db.execute(
                "SELECT payload FROM quotas WHERE provider=?",
                (self.scope_key(provider, environment_id),),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_subscription(
        self,
        provider,
        plan="",
        renewal_date=None,
        monthly_cost=None,
        currency="USD",
        environment_id="local",
    ):
        import math

        if provider not in PROVIDERS:
            raise Invalid("Unsupported provider")
        self.get_environment(environment_id)
        plan = text(plan, "plan", 100, True)
        currency = text(currency, "currency", 3)
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise Invalid("Use a three-letter currency code")
        if renewal_date:
            try:
                datetime.strptime(renewal_date, "%Y-%m-%d")
            except (TypeError, ValueError):
                raise Invalid("Use YYYY-MM-DD for renewal_date")
        if monthly_cost is not None and (
            isinstance(monthly_cost, bool)
            or not isinstance(monthly_cost, (int, float))
            or not math.isfinite(monthly_cost)
            or monthly_cost < 0
        ):
            raise Invalid("Invalid monthly cost")
        item = dict(
            provider=provider,
            plan=plan,
            renewal_date=renewal_date or None,
            monthly_cost=monthly_cost,
            currency=currency.upper(),
        )
        with self.transaction():
            self.db.execute(
                "INSERT OR REPLACE INTO subscriptions VALUES(:provider,:plan,:renewal_date,:monthly_cost,:currency)",
                {**item, "provider": self.scope_key(provider, environment_id)},
            )
        if environment_id != "local":
            item["environment_id"] = environment_id
        return item

    def configured_providers(self, environment_id=None):
        with self.lock:
            return [
                r[0]
                for r in self.db.execute(
                    "SELECT DISTINCT provider FROM agents WHERE (? IS NULL OR environment_id=?) ORDER BY provider DESC",
                    (environment_id, environment_id),
                )
            ]

    def configured_connections(self):
        with self.lock:
            return [
                (r[0], r[1])
                for r in self.db.execute(
                    "SELECT DISTINCT provider,environment_id FROM agents ORDER BY environment_id,provider DESC"
                )
            ]

    def connection_agent_names(self, provider, environment_id):
        with self.lock:
            return [
                r[0]
                for r in self.db.execute(
                    "SELECT name FROM agents WHERE provider=? AND environment_id=? ORDER BY created_at,rowid",
                    (provider, environment_id),
                )
            ]

    def usage_bindings(self, local_only=False):
        with self.lock:
            return {
                (
                    r["provider"],
                    self.metric_identity(r["environment_id"], r["native_session_id"]),
                ): r["agent_id"]
                for r in self.db.execute(
                    "SELECT agents.provider,branch.native_session_id,sessions.agent_id,sessions.environment_id FROM session_account_branches AS branch JOIN sessions ON branch.session_id=sessions.id JOIN agents ON agents.id=sessions.agent_id WHERE branch.native_session_id IS NOT NULL AND (?=0 OR sessions.environment_id='local')",
                    (local_only,),
                )
            }

    def get_environment(self, identifier="local"):
        with self.lock:
            return self._one("environments", identifier or "local")

    def environments(self):
        with self.lock:
            return self._all("SELECT * FROM environments ORDER BY kind,name,id")

    def add_environment(self, name, ssh_host, python="python3"):
        host = text(ssh_host, "ssh_host", 255)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*", host):
            raise Invalid(
                "Use an SSH Host alias, without flags or shell commands",
                code="use_an_ssh_host_alias_without_flags_or_shell_commands",
            )
        python = text(python or "python3", "python", 512)
        if not re.fullmatch(
            r"(?:/[A-Za-z0-9_.+/-]+|[A-Za-z0-9][A-Za-z0-9_.+-]*)", python
        ):
            raise Invalid(
                "Invalid remote Python executable",
                code="invalid_remote_python_executable",
            )
        item = dict(
            id=str(uuid.uuid4()),
            name=text(name, "name", 100),
            kind="ssh",
            ssh_host=host,
            python=python,
            status="disconnected",
            payload="{}",
            updated_at=now(),
        )
        with self.transaction():
            self.db.execute(
                "INSERT INTO environments VALUES(:id,:name,:kind,:ssh_host,:python,:status,:payload,:updated_at)",
                item,
            )
            return self._one("environments", item["id"])

    def update_environment_status(self, identifier, status, payload=None):
        if status not in (
            "connected",
            "connecting",
            "reconnecting",
            "disconnected",
            "error",
        ):
            raise Invalid("Invalid connection state")
        with self.transaction():
            current = self._one("environments", identifier)
            self.db.execute(
                "UPDATE environments SET status=?,payload=?,updated_at=? WHERE id=?",
                (
                    status,
                    json.dumps(payload if payload is not None else current["payload"]),
                    now(),
                    identifier,
                ),
            )
            return self._one("environments", identifier)

    def remove_environment(self, identifier):
        with self.transaction():
            self._one("environments", identifier)
            if (
                identifier == "local"
                or self.db.execute(
                    "SELECT 1 FROM agents WHERE environment_id=? UNION SELECT 1 FROM projects WHERE environment_id=? UNION SELECT 1 FROM sessions WHERE environment_id=? UNION SELECT 1 FROM accounts WHERE environment_id=?",
                    (identifier, identifier, identifier, identifier),
                ).fetchone()
            ):
                raise Conflict(
                    "This environment is still in use",
                    code="this_environment_is_still_in_use",
                )
            self.db.execute("DELETE FROM environments WHERE id=?", (identifier,))
            return {"ok": True}
