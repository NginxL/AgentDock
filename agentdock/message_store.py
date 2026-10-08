"""MessageStore domain operations; mutations share the owning Store transaction."""

from __future__ import annotations

import uuid

from .errors import Conflict, Forbidden, Invalid, now, text


class MessageStore:
    def enqueue_message(
        self,
        project_id,
        sender_id,
        recipient_id,
        body,
        correlation_id=None,
        idempotency_key=None,
        *,
        sender_session_id=None,
        recipient_session_id=None,
        parent_run_id=None,
        task_role="worker",
    ):
        body = text(body, "body", 12000)
        if correlation_id is not None:
            correlation_id = text(correlation_id, "correlation_id", 128)
        if idempotency_key is not None:
            idempotency_key = text(idempotency_key, "idempotency_key", 128)
        with self.transaction():
            self._one("projects", project_id)
            recipient = self._available("agents", recipient_id)
            if recipient["project_id"] != project_id:
                raise Forbidden("Recipient belongs to another project")
            if sender_id == "human":
                if sender_session_id or parent_run_id:
                    raise Forbidden("Human dispatch cannot claim an agent session")
            else:
                sender = self._available("agents", sender_id)
                if sender["project_id"] != project_id:
                    raise Forbidden("Sender belongs to another project")
                if not parent_run_id:
                    raise Invalid("Agent dispatch requires an active parent run")
                parent = self._one("runs", parent_run_id)
                if (
                    parent["agent_id"] != sender_id
                    or parent["project_id"] != project_id
                    or parent["status"] != "running"
                ):
                    raise Forbidden("Sender run is not active or owned by this agent")
                if (
                    sender_session_id is not None
                    and sender_session_id != parent["session_id"]
                ):
                    raise Forbidden("Sender session does not own this run")
                sender_session_id = parent["session_id"]
                if sender_id == recipient_id:
                    raise Invalid("Choose a different agent for delegation")
                if parent.get("work_task_id"):
                    task = self._task_run_authority(parent, owner=True)
                    if parent.get("task_intent") != "develop":
                        raise Forbidden(
                            "Discussion cannot dispatch implementation work"
                        )
                    if task_role not in ("worker", "reviewer"):
                        raise Invalid("Invalid task role")
                    if recipient_session_id is not None:
                        target = self._one("sessions", recipient_session_id)
                        if (
                            target.get("work_task_id") != task["id"]
                            or target.get("task_role") != task_role
                        ):
                            raise Forbidden(
                                "Select a conversation assigned to this task and role"
                            )
            if recipient_session_id is not None:
                recipient_session = self._one("sessions", recipient_session_id)
                if (
                    recipient_session["project_id"] != project_id
                    or recipient_session["agent_id"] != recipient_id
                ):
                    raise Forbidden(
                        "Recipient session does not belong to the target agent"
                    )
                if sender_id == "human" and recipient_session.get("work_task_id"):
                    raise Forbidden(
                        "Use the project task input to continue this conversation",
                        code="use_the_project_task_input_to_continue_this_conversation",
                    )
            if idempotency_key:
                row = self.db.execute(
                    "SELECT * FROM messages WHERE project_id=? AND sender_id=? AND idempotency_key=?",
                    (project_id, sender_id, idempotency_key),
                ).fetchone()
                if row:
                    mismatched = (
                        row["body"] != body
                        or row["recipient_id"] != recipient_id
                        or row["correlation_id"] != correlation_id
                        or row["sender_session_id"] != sender_session_id
                        or row["sender_run_id"] != parent_run_id
                    )
                    if (
                        recipient_session_id is not None
                        and row["recipient_session_id"] != recipient_session_id
                    ):
                        mismatched = True
                    if (
                        sender_id != "human"
                        and parent.get("work_task_id")
                        and self._one("sessions", row["recipient_session_id"]).get(
                            "task_role"
                        )
                        != task_role
                    ):
                        mismatched = True
                    if mismatched:
                        raise Conflict(
                            "Idempotency key already used for another message"
                        )
                    return dict(row)
            if recipient_session_id is None:
                if sender_id != "human" and parent.get("work_task_id"):
                    recipient_session_id = self._task_session(
                        task, recipient_id, task_role, "develop"
                    )["id"]
                else:
                    latest = self.db.execute(
                        "SELECT id FROM sessions WHERE agent_id=? AND environment_id=? AND work_task_id IS NULL ORDER BY updated_at DESC,rowid DESC LIMIT 1",
                        (recipient_id, recipient["environment_id"]),
                    ).fetchone()
                    recipient_session_id = (
                        latest["id"]
                        if latest
                        else self._add_session(
                            recipient_id,
                            "Delegated task" if sender_id != "human" else "New task",
                        )["id"]
                    )
            identifier = str(uuid.uuid4())
            run = self._enqueue_run(
                recipient_session_id,
                body,
                "human" if sender_id == "human" else "delegate",
                parent_run_id=parent_run_id,
                delivery_id=identifier,
            )
            item = dict(
                id=identifier,
                project_id=project_id,
                sender_id=sender_id,
                recipient_id=recipient_id,
                body=body,
                correlation_id=correlation_id,
                status="queued",
                idempotency_key=idempotency_key,
                created_at=now(),
                acknowledged_at=None,
                sender_session_id=sender_session_id,
                recipient_session_id=recipient_session_id,
                sender_run_id=parent_run_id,
                run_id=run["id"],
                reply_run_id=None,
                error=None,
                updated_at=now(),
                result=None,
            )
            self.db.execute(
                "INSERT INTO messages(id,project_id,sender_id,recipient_id,body,correlation_id,status,idempotency_key,created_at,acknowledged_at,sender_session_id,recipient_session_id,sender_run_id,run_id,reply_run_id,error,updated_at) VALUES(:id,:project_id,:sender_id,:recipient_id,:body,:correlation_id,:status,:idempotency_key,:created_at,:acknowledged_at,:sender_session_id,:recipient_session_id,:sender_run_id,:run_id,:reply_run_id,:error,:updated_at)",
                item,
            )
            if sender_id != "human":
                self._dispatch_approval(item, parent)
            self._event(
                project_id,
                sender_session_id,
                "message_queued",
                {
                    "message_id": identifier,
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "run_id": run["id"],
                },
            )
            return item

    def send_message(
        self,
        project_id,
        sender_id,
        recipient_id,
        body,
        correlation_id=None,
        idempotency_key=None,
        **kwargs,
    ):
        return self.enqueue_message(
            project_id,
            sender_id,
            recipient_id,
            body,
            correlation_id,
            idempotency_key,
            **kwargs,
        )

    def enqueue_reply(self, delivery_id, prompt):
        with self.transaction():
            message = self._one("messages", delivery_id)
            if message["reply_run_id"]:
                return self._one("runs", message["reply_run_id"])
            if message["sender_id"] == "human" or not message["sender_session_id"]:
                return None
            child = self._one("runs", message["run_id"])
            if message["status"] not in ("completed", "failed", "cancelled"):
                raise Conflict("Only a settled delivery can return a result")
            sender = self._one("runs", message["sender_run_id"])
            if self._task_stopped(sender["task_run_id"]):
                raise Conflict("The requesting task has been stopped")
            run = self._enqueue_run(
                message["sender_session_id"],
                prompt,
                "reply",
                parent_run_id=child["id"],
                delivery_id=delivery_id,
            )
            self.db.execute(
                "UPDATE messages SET reply_run_id=?,updated_at=? WHERE id=?",
                (run["id"], now(), delivery_id),
            )
            self._event(
                message["project_id"],
                message["sender_session_id"],
                "reply_queued",
                {
                    "message_id": delivery_id,
                    "run_id": run["id"],
                    "child_run_id": child["id"],
                },
            )
            return run
