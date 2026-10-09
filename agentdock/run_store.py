"""RunStore domain operations; mutations share the owning Store transaction."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .errors import Conflict, Forbidden, Invalid, now, text
from .registry import ACP_PROVIDERS


class RunStore:
    def _enqueue_run(
        self,
        session_id,
        prompt,
        origin="human",
        parent_run_id=None,
        root_run_id=None,
        depth=None,
        delivery_id=None,
    ):
        prompt = text(prompt, "prompt", 24000)
        if origin not in ("human", "delegate", "reply"):
            raise Invalid("Invalid run origin")
        session = self._available("sessions", session_id)
        self._available("agents", session["agent_id"])
        parent = self._one("runs", parent_run_id) if parent_run_id else None
        work_task_id = session.get("work_task_id")
        if work_task_id:
            task = self._one("tasks", work_task_id)
            if task["status"] in (
                "paused",
                "cancelled",
                "archived",
                "completed",
                "interrupted",
            ):
                raise Conflict("Task is not accepting execution")
        if parent and parent.get("work_task_id") != work_task_id:
            raise Forbidden("Delegation cannot mix task and independent conversations")
        if parent and parent["project_id"] != session["project_id"]:
            raise Forbidden("Parent run belongs to another project")
        if origin in ("delegate", "reply") and not parent:
            raise Invalid("Delegated runs require a parent run")
        if origin == "human" and parent:
            raise Invalid("Human runs cannot inherit an agent delegation")
        expected_root = parent["root_run_id"] if parent else None
        if root_run_id is not None and root_run_id != expected_root:
            raise Invalid("Invalid root run")
        if origin == "delegate" and (
            parent["status"] != "running" or self._task_stopped(parent["task_run_id"])
        ):
            raise Forbidden("Delegation requires an active parent task")
        expected_depth = parent["depth"] + 1 if parent else 0
        if origin == "reply":
            if not parent["delivery_id"] or parent["status"] not in (
                "completed",
                "failed",
                "cancelled",
            ):
                raise Forbidden("Reply requires a finished delivery")
            delivery = self._one("messages", parent["delivery_id"])
            sender = self._one("runs", delivery["sender_run_id"])
            if delivery["run_id"] != parent["id"] or session_id != sender["session_id"]:
                raise Forbidden("Reply must return to the requesting session")
            if self._task_stopped(sender["task_run_id"]):
                raise Forbidden("The requesting task has stopped")
            expected_depth = sender["depth"]
        if expected_depth > 3:
            raise Forbidden("Delegation depth limit reached (3)")
        if expected_root:
            actual = self.db.execute(
                "SELECT COUNT(*) FROM runs WHERE root_run_id=?", (expected_root,)
            ).fetchone()[0]
            # A new child reserves its return turn before it is allowed to execute.
            reserved = self.db.execute(
                "SELECT COUNT(*) FROM messages JOIN runs AS sender ON messages.sender_run_id=sender.id WHERE sender.root_run_id=? AND messages.reply_run_id IS NULL AND messages.status NOT IN ('legacy','interrupted') AND NOT EXISTS (SELECT 1 FROM runs AS stopped WHERE stopped.task_run_id=sender.task_run_id AND stopped.status IN ('failed','cancelled','interrupted'))",
                (expected_root,),
            ).fetchone()[0]
            if actual >= 16 or (origin == "delegate" and actual + reserved + 2 > 16):
                raise Forbidden(
                    "Collaboration run limit reached (16, including reserved replies)"
                )
        if depth is not None and (isinstance(depth, bool) or depth != expected_depth):
            raise Invalid("Invalid dispatch depth")
        identifier = str(uuid.uuid4())
        task_run_id = sender["task_run_id"] if origin == "reply" else identifier
        run = dict(
            id=identifier,
            task_run_id=task_run_id,
            session_id=session_id,
            project_id=session["project_id"],
            agent_id=session["agent_id"],
            prompt=prompt,
            status="queued",
            error=None,
            created_at=now(),
            updated_at=now(),
            origin=origin,
            parent_run_id=parent_run_id,
            root_run_id=expected_root or identifier,
            depth=expected_depth,
            delivery_id=delivery_id,
            result=None,
        )
        session_agent = self.session_agent(session_id)
        settings = (
            sender
            if origin == "reply"
            else (session if session["model_override"] else session_agent)
        )
        run.update(model=settings["model"], effort=settings["effort"])
        run["permission_mode"] = (
            sender["permission_mode"]
            if origin == "reply"
            else session_agent["permission_mode"]
        )
        self.db.execute(
            "INSERT INTO runs(id,session_id,project_id,agent_id,prompt,status,error,created_at,updated_at,origin,parent_run_id,root_run_id,depth,delivery_id,task_run_id,model,effort,permission_mode) VALUES(:id,:session_id,:project_id,:agent_id,:prompt,:status,:error,:created_at,:updated_at,:origin,:parent_run_id,:root_run_id,:depth,:delivery_id,:task_run_id,:model,:effort,:permission_mode)",
            run,
        )
        self.db.execute(
            "UPDATE runs SET work_task_id=?,task_role=?,task_intent=? WHERE id=?",
            (
                work_task_id,
                session.get("task_role"),
                session.get("task_intent"),
                run["id"],
            ),
        )
        self._freeze_run_account(session, run)
        self.db.execute(
            "UPDATE runs SET account_id=?,account_policy=?,account_ids=?,account_generation=?,account_branch=?,account_selection_pending=? WHERE id=?",
            (
                run["account_id"],
                run["account_policy"],
                json.dumps(run["account_ids"]),
                run["account_generation"],
                run["account_branch"],
                run.get("account_selection_pending", 0),
                run["id"],
            ),
        )
        self._refresh_session(session_id, "queued")
        self._event(
            run["project_id"],
            session_id,
            "run_queued",
            {
                "run_id": identifier,
                "origin": origin,
                "parent_run_id": parent_run_id,
                "delivery_id": delivery_id,
            },
        )
        return self._one("runs", run["id"])

    def enqueue_run(
        self,
        session_id,
        prompt,
        *,
        origin="human",
        parent_run_id=None,
        root_run_id=None,
        depth=None,
        delivery_id=None,
    ):
        with self.transaction():
            return self._enqueue_run(
                session_id,
                prompt,
                origin,
                parent_run_id,
                root_run_id,
                depth,
                delivery_id,
            )

    def _can_claim(self, run):
        blocked = self.db.execute(
            "SELECT 1 FROM approvals WHERE json_extract(request,'$.dispatch_run_id')=? AND (status!='resolved' OR picked_option_id!='accept') LIMIT 1",
            (run["id"],),
        ).fetchone()
        if blocked:
            return False
        if run["status"] != "queued":
            return False
        if run.get("work_task_id"):
            task = self._one("tasks", run["work_task_id"])
            if task["status"] in (
                "paused",
                "cancelled",
                "archived",
                "completed",
                "interrupted",
            ):
                return False
            if self.db.execute(
                "SELECT 1 FROM task_questions WHERE task_id=? AND status='open'",
                (task["id"],),
            ).fetchone():
                return False
        if run.get("next_attempt_at") and datetime.fromisoformat(
            run["next_attempt_at"]
        ) > datetime.now(timezone.utc):
            return False
        if self.db.execute(
            "SELECT 1 FROM runs WHERE agent_id=? AND status='running'",
            (run["agent_id"],),
        ).fetchone():
            return False
        # Managed credential refresh is serialized per account. Queue here instead
        # of occupying a worker while waiting for a native credential lease.
        if (
            run.get("account_id")
            and self.db.execute(
                "SELECT 1 FROM runs WHERE account_id=? AND status='running'",
                (run["account_id"],),
            ).fetchone()
        ):
            return False
        session = self._one("sessions", run["session_id"])
        provider = self._one("agents", run["agent_id"])["provider"]
        chosen = Path(session["workspace"])
        active = self.db.execute(
            "SELECT runs.agent_id,agents.provider,sessions.workspace AS path FROM runs JOIN sessions ON runs.session_id=sessions.id JOIN agents ON agents.id=runs.agent_id WHERE runs.status='running' AND sessions.environment_id=?",
            (session["environment_id"],),
        ).fetchall()
        return not any(
            row["agent_id"] == run["agent_id"]
            # ACP agents on one device inherit the same provider login. Reserve
            # that resource before starting a worker or consuming its deadline.
            or (provider in ACP_PROVIDERS and row["provider"] == provider)
            or chosen == Path(row["path"])
            or chosen in Path(row["path"]).parents
            or Path(row["path"]) in chosen.parents
            for row in active
        )

    def _claim(self, run):
        self.db.execute(
            "UPDATE runs SET status='running',updated_at=? WHERE id=? AND status='queued'",
            (now(), run["id"]),
        )
        if run.get("work_task_id"):
            self.db.execute(
                "UPDATE runs SET task_revision=(SELECT revision FROM tasks WHERE id=?) WHERE id=?",
                (run["work_task_id"], run["id"]),
            )
            self.db.execute(
                "UPDATE task_inputs SET status='accepted' WHERE run_id=? AND status='queued'",
                (run["id"],),
            )
        self._refresh_session(run["session_id"], "running")
        if run["delivery_id"] and run["origin"] != "reply":
            self.db.execute(
                "UPDATE messages SET status='running',acknowledged_at=?,updated_at=? WHERE id=?",
                (now(), now(), run["delivery_id"]),
            )
        already_shown = any(
            json.loads(row[0]).get("run_id") == run["id"]
            for row in self.db.execute(
                "SELECT payload FROM events WHERE session_id=? AND kind='user_message'",
                (run["session_id"],),
            )
        )
        if not already_shown:
            self._event(
                run["project_id"],
                run["session_id"],
                "user_message",
                {
                    "text": run["prompt"],
                    "run_id": run["id"],
                    "origin": run["origin"],
                    "delivery_id": run["delivery_id"],
                },
            )
        self._event(
            run["project_id"], run["session_id"], "run_started", {"run_id": run["id"]}
        )
        return self._one("runs", run["id"])

    def claim_next_run(self):
        with self.transaction():
            for run in self._all(
                "SELECT * FROM runs WHERE status='queued' ORDER BY created_at,rowid"
            ):
                if self._can_claim(run):
                    return self._claim(run)
            return None

    def begin_run(self, session_id, prompt):
        """Compatibility helper for callers that require immediate admission."""
        with self.transaction():
            run = self._enqueue_run(session_id, prompt)
            if not self._can_claim(run):
                raise Conflict("Agent or overlapping workspace has an active run")
            return self._claim(run)

    def _refresh_session(self, session_id, fallback):
        statuses = {
            row[0]
            for row in self.db.execute(
                "SELECT status FROM runs WHERE session_id=? AND status IN ('running','queued')",
                (session_id,),
            )
        }
        status = (
            "running"
            if "running" in statuses
            else "queued"
            if "queued" in statuses
            else fallback
        )
        self.db.execute(
            "UPDATE sessions SET status=?,updated_at=? WHERE id=?",
            (status, now(), session_id),
        )

    def finish_run(self, run_id, status, error=None, result=None):
        if status not in ("completed", "failed", "cancelled", "interrupted"):
            raise Invalid("Invalid run status")
        if error is not None:
            error = text(error, "error", 8000, True)
        if result is not None:
            result = text(result, "result", 120000, True)
        with self.transaction():
            run = self._one("runs", run_id)
            if run["status"] not in ("running", "queued"):
                return run
            if run["status"] == "queued" and status == "completed":
                raise Conflict("A queued run cannot complete before execution")
            self.db.execute(
                "UPDATE runs SET status=?,error=?,result=?,updated_at=? WHERE id=?",
                (status, error, result, now(), run_id),
            )
            self._refresh_session(run["session_id"], status)
            self.db.execute(
                "UPDATE capabilities SET revoked=1 WHERE run_id=?", (run_id,)
            )
            self.db.execute(
                "UPDATE approvals SET status='cancelled' WHERE run_id=? AND status='pending' AND (? != 'completed' OR COALESCE(json_extract(request,'$.kind'),'') != 'dispatch')",
                (run_id, status),
            )
            if run["delivery_id"] and run["origin"] != "reply":
                self.db.execute(
                    "UPDATE messages SET status=?,error=?,result=?,updated_at=? WHERE id=?",
                    (
                        "waiting" if status == "completed" else status,
                        error,
                        result,
                        now(),
                        run["delivery_id"],
                    ),
                )
            self.db.execute(
                "UPDATE approvals SET status='cancelled' WHERE json_extract(request,'$.dispatch_run_id')=? AND status='pending'",
                (run_id,),
            )
            self._event(
                run["project_id"],
                run["session_id"],
                "run_finished",
                {
                    "run_id": run_id,
                    "status": status,
                    "error": error,
                    "delivery_id": run["delivery_id"],
                },
            )
            if status in ("failed", "cancelled", "interrupted"):
                self._cancel_queued_descendants(run["task_run_id"])
            self._settle_task(run_id)
            return self._one("runs", run_id)

    def _task_stopped(self, task_run_id):
        return (
            self.db.execute(
                "SELECT 1 FROM runs WHERE task_run_id=? AND status IN ('failed','cancelled','interrupted') LIMIT 1",
                (task_run_id,),
            ).fetchone()
            is not None
        )

    def _settle_task(self, run_id):
        run = self._one("runs", run_id)
        task = self._one("runs", run["task_run_id"])
        if not task["delivery_id"]:
            return None
        delivery = self._one("messages", task["delivery_id"])
        if delivery["reply_run_id"]:
            return None
        turns = self._all(
            "SELECT * FROM runs WHERE task_run_id=? ORDER BY created_at,rowid",
            (task["id"],),
        )
        # Cancelling queued sibling continuations is cleanup, not the failure cause.
        failed = next(
            (turn for turn in reversed(turns) if turn["status"] == "failed"), None
        )
        if failed is None:
            failed = next(
                (
                    turn
                    for turn in reversed(turns)
                    if turn["status"] in ("cancelled", "interrupted")
                ),
                None,
            )
        if failed:
            status, error, result = failed["status"], failed["error"], None
        else:
            if any(turn["status"] in ("queued", "running") for turn in turns):
                return None
            children = self._all(
                "SELECT messages.* FROM messages JOIN runs AS sender ON messages.sender_run_id=sender.id WHERE sender.task_run_id=?",
                (task["id"],),
            )
            for child in children:
                if child["status"] in ("queued", "running", "waiting"):
                    return None
                if child["status"] in ("completed", "failed", "cancelled"):
                    if not child["reply_run_id"]:
                        return None
                    reply = self._one("runs", child["reply_run_id"])
                    if reply["status"] in ("queued", "running"):
                        return None
            final = turns[-1]
            status, error, result = final["status"], final["error"], final["result"]
        if (delivery["status"], delivery["error"], delivery["result"]) != (
            status,
            error,
            result,
        ):
            self.db.execute(
                "UPDATE messages SET status=?,error=?,result=?,updated_at=? WHERE id=?",
                (status, error, result, now(), delivery["id"]),
            )
            self._event(
                task["project_id"],
                task["session_id"],
                "task_settled",
                {
                    "task_run_id": task["id"],
                    "message_id": delivery["id"],
                    "status": status,
                },
            )
        return self._one("messages", delivery["id"])

    def settle_task(self, run_id):
        """Return a completed logical delivery, after all child results were consumed."""
        with self.transaction():
            return self._settle_task(run_id)

    def _cancel_queued_descendants(self, run_id):
        descendants = self._all(
            "WITH RECURSIVE descendants(id) AS (SELECT id FROM runs WHERE parent_run_id=? UNION ALL SELECT runs.id FROM runs JOIN descendants ON runs.parent_run_id=descendants.id) SELECT runs.* FROM runs JOIN descendants ON runs.id=descendants.id",
            (run_id,),
        )
        for child in descendants:
            if child["origin"] != "reply" and child["delivery_id"]:
                delivery = self._one("messages", child["delivery_id"])
                if delivery["status"] == "waiting":
                    self.db.execute(
                        "UPDATE messages SET status='cancelled',error=?,updated_at=? WHERE id=?",
                        ("Requesting task stopped", now(), delivery["id"]),
                    )
                    self.db.execute(
                        "UPDATE runs SET status='cancelled',error=?,updated_at=? WHERE id=? AND status='completed'",
                        ("Requesting task stopped", now(), child["id"]),
                    )
                    self._refresh_session(child["session_id"], "cancelled")
            if child["status"] != "queued":
                continue
            error = "Requesting task stopped before this run started"
            self.db.execute(
                "UPDATE runs SET status='cancelled',error=?,updated_at=? WHERE id=?",
                (error, now(), child["id"]),
            )
            self._refresh_session(child["session_id"], "cancelled")
            if child["delivery_id"] and child["origin"] != "reply":
                self.db.execute(
                    "UPDATE messages SET status='cancelled',error=?,updated_at=? WHERE id=?",
                    (error, now(), child["delivery_id"]),
                )
            self.db.execute(
                "UPDATE approvals SET status='cancelled' WHERE json_extract(request,'$.dispatch_run_id')=? AND status='pending'",
                (child["id"],),
            )
            self._event(
                child["project_id"],
                child["session_id"],
                "run_finished",
                {
                    "run_id": child["id"],
                    "status": "cancelled",
                    "error": error,
                    "delivery_id": child["delivery_id"],
                },
            )

    def cancel_queued_run(self, run_id):
        with self.lock:
            run = self._one("runs", run_id)
            if run["status"] != "queued":
                raise Conflict("Run is not queued")
            return self.finish_run(run_id, "cancelled")

    def cancel_run_tree(self, run_id):
        """Cancel one logical task and descendants; return process IDs to stop."""
        with self.lock:
            target = self._one("runs", run_id)
            task = self._one("runs", target["task_run_id"])
            if task["id"] not in {
                item["id"] for item in self.cancellable_tasks(task["session_id"])
            }:
                return []
            if (
                task["delivery_id"]
                and self._one("messages", task["delivery_id"])["reply_run_id"]
            ):
                # Its completed result already belongs to the requesting task now.
                return []
            with self.transaction():
                # A completed turn can still own a task waiting for child results.
                if task["status"] == "completed":
                    self.db.execute(
                        "UPDATE runs SET status='cancelled',error=?,updated_at=? WHERE id=?",
                        ("Task cancelled by the user", now(), task["id"]),
                    )
                    self._refresh_session(task["session_id"], "cancelled")
                self._cancel_queued_descendants(task["id"])
            descendants = self._all(
                "WITH RECURSIVE descendants(id) AS (SELECT id FROM runs WHERE id=? UNION ALL SELECT runs.id FROM runs JOIN descendants ON runs.parent_run_id=descendants.id) SELECT runs.* FROM runs JOIN descendants ON runs.id=descendants.id",
                (task["id"],),
            )
            running = []
            for run in descendants:
                if run["status"] == "queued":
                    self.finish_run(run["id"], "cancelled")
                elif run["status"] == "running":
                    running.append(run["id"])
            self.settle_task(task["id"])
            return running

    def runs_for_root(self, root_run_id):
        with self.lock:
            self._one("runs", root_run_id)
            return self._all(
                "SELECT * FROM runs WHERE root_run_id=? ORDER BY created_at,rowid",
                (root_run_id,),
            )

    def pending_runs(self, session_id=None):
        with self.lock:
            if session_id is not None:
                self._one("sessions", session_id)
                return self._all(
                    "SELECT * FROM runs WHERE session_id=? AND status IN ('queued','running') ORDER BY created_at,rowid",
                    (session_id,),
                )
            return self._all(
                "SELECT * FROM runs WHERE status IN ('queued','running') ORDER BY created_at,rowid"
            )

    def cancellable_tasks(self, session_id):
        """Logical tasks owned by a session, including turns waiting on teammates."""
        with self.lock:
            self._one("sessions", session_id)
            return self._all(
                """
                SELECT task.* FROM runs AS task
                WHERE task.session_id=? AND task.task_run_id=task.id AND (
                    EXISTS (SELECT 1 FROM runs AS turn WHERE turn.task_run_id=task.id
                            AND turn.status IN ('queued','running'))
                    OR (NOT EXISTS (SELECT 1 FROM runs AS stopped WHERE stopped.task_run_id=task.id
                                    AND stopped.status IN ('failed','cancelled','interrupted')) AND (
                        EXISTS (SELECT 1 FROM messages AS child
                                JOIN runs AS sender ON child.sender_run_id=sender.id
                                LEFT JOIN runs AS reply ON child.reply_run_id=reply.id
                                WHERE sender.task_run_id=task.id AND (
                                    child.status IN ('queued','running','waiting') OR
                                    (child.status IN ('completed','failed','cancelled') AND
                                     (child.reply_run_id IS NULL OR reply.status IN ('queued','running')))))
                        OR EXISTS (SELECT 1 FROM messages AS delivery WHERE delivery.id=task.delivery_id
                                   AND (delivery.status='waiting' OR
                                        (delivery.status='completed' AND delivery.sender_id<>'human'
                                         AND delivery.reply_run_id IS NULL)))
                    ))
                ) ORDER BY task.created_at,task.rowid
            """,
                (session_id,),
            )
