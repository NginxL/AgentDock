"""EventStore domain operations; mutations share the owning Store transaction."""

from __future__ import annotations

import json
import threading
import uuid

from .errors import Invalid, now


class EventStore:
    def _event(self, project_id, session_id, kind, payload):
        data = json.dumps(payload, ensure_ascii=False)
        if len(data) > 131072:
            raise Invalid("Event too large")
        event = dict(
            id=str(uuid.uuid4()),
            project_id=project_id,
            session_id=session_id,
            kind=kind,
            payload=data,
            created_at=now(),
        )
        c = self.db.execute(
            "INSERT INTO events(id,project_id,session_id,kind,payload,created_at) VALUES(:id,:project_id,:session_id,:kind,:payload,:created_at)",
            event,
        )
        event["seq"] = c.lastrowid
        event["payload"] = payload
        if session_id and hasattr(self, "_changed_sessions"):
            self._changed_sessions.add(session_id)
        return event

    def append_event(self, project_id, session_id, kind, payload):
        with self.transaction():
            return self._event(project_id, session_id, kind, payload)

    def session_events(self, session_id, after=0):
        with self.lock:
            self._one("sessions", session_id)
            return self._all(
                "SELECT * FROM events WHERE session_id=? AND seq>? ORDER BY seq LIMIT 500",
                (session_id, max(0, int(after))),
            )

    def run_activity(self, run_id, limit=12):
        """Most recent observed actions for one attempt, in chronological order."""
        with self.lock:
            self._one("runs", run_id)
            rows = self._all(
                """SELECT * FROM events
                WHERE json_extract(payload, '$.run_id')=?
                AND kind IN ('tool_call','tool_result','tool_output','agent_message')
                ORDER BY seq DESC LIMIT ?""",
                (run_id, max(1, min(int(limit), 100))),
            )
            return list(reversed(rows))

    def wait_session_events(self, session_id, after, stop, timeout=10):
        # Subscribe and inspect the durable cursor under the same lock. A commit
        # between a history read and the wait cannot be missed.
        with self.lock:
            condition = self._session_conditions.setdefault(
                session_id, threading.Condition(self.lock)
            )
            result = []

            def available():
                nonlocal result
                if self.closed or stop.is_set():
                    return True
                result = self.session_events(session_id, after)
                return bool(result)

            condition.wait_for(available, timeout)
            return result
