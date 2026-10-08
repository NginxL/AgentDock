"""Durable deletion lifecycle; external cleanup never holds the database lock."""
from contextlib import contextmanager
import threading

from .errors import Conflict, now


class DeletionStore:
    def _migrate_deletions(self):
        with self.transaction():
            for table in ('agents', 'sessions'):
                if 'deleting' not in {row[1] for row in self.db.execute('PRAGMA table_info(' + table + ')')}:
                    self.db.execute('ALTER TABLE ' + table + ' ADD COLUMN deleting INTEGER NOT NULL DEFAULT 0')
            self.db.execute('CREATE INDEX IF NOT EXISTS runs_root ON runs(root_run_id)')

    def _available(self, table, identifier):
        item = self._one(table, identifier)
        if item.get('deleting'):
            raise Conflict('Deletion is pending; retry deletion to finish cleanup')
        return item

    @contextmanager
    def _deletion_guard(self, agent_id):
        # One cleanup per Agent, independent of the database lock. A crash loses
        # this in-memory lock but retains the tombstones, so retry is possible.
        with self.lock:
            guard = self._deletion_locks.setdefault(agent_id, threading.Lock())
        if not guard.acquire(blocking=False):
            raise Conflict('Deletion is already in progress')
        try:
            yield
        finally:
            guard.release()

    def _cleanup_target(self, session):
        runs = [row['id'] for row in self.db.execute('SELECT id FROM runs WHERE session_id=?', (session['id'],))]
        self.db.execute("UPDATE sessions SET deleting=1,status='deleting',updated_at=? WHERE id=?", (now(), session['id']))
        return session, runs

    def delete_session(self, session_id, cleanup):
        agent_id = self.get_session(session_id)['agent_id']
        with self._deletion_guard(agent_id):
            with self.transaction():
                session = self._one('sessions', session_id)
                self._check_session_deletion(session_id)
                target = self._cleanup_target(session)
            cleanup(*target)  # Idempotent cleanup outside the database transaction.
            with self.transaction():
                self._delete_session_records(session)
        return {'ok': True}

    def _check_session_deletion(self, session_id):
        session=self._one('sessions',session_id)
        if session.get('work_task_id'):
            task=self._one('tasks',session['work_task_id'])
            if task['status'] not in ('completed','cancelled','archived'):
                raise Conflict('Finish or cancel the project task before deleting its conversation')
        if self.db.execute("SELECT 1 FROM runs WHERE session_id=? AND status IN ('queued','running')", (session_id,)).fetchone():
            raise Conflict('Stop active tasks before deleting a session')
        if self.cancellable_tasks(session_id) or self.db.execute("SELECT 1 FROM messages WHERE (sender_session_id=? OR recipient_session_id=?) AND status IN ('queued','running','waiting')", (session_id,session_id)).fetchone():
            raise Conflict('Wait for linked tasks before deleting a session')
        # Returned results remain ancestors of the requesting task's later turns.
        # Keep the whole collaboration chain until it has settled, including the
        # gap between a child finishing and its result being queued for return.
        roots = {row[0] for row in self.db.execute('SELECT DISTINCT root_run_id FROM runs WHERE session_id=?', (session_id,))}
        related = self.db.execute('''SELECT DISTINCT related.session_id FROM runs AS owned
            JOIN runs AS related ON related.root_run_id=owned.root_run_id
            WHERE owned.session_id=?''', (session_id,)).fetchall()
        if any(task['root_run_id'] in roots for row in related for task in self.cancellable_tasks(row[0])):
            raise Conflict('Wait for linked tasks before deleting a session')

    def _delete_session_records(self, session):
        session_id = session['id']
        # Task journals/deliveries outlive disposable native histories.
        self.db.execute('UPDATE tasks SET session_id=NULL WHERE session_id=?',(session_id,))
        natives = {row[0] for row in self.db.execute('SELECT native_session_id FROM session_account_branches WHERE session_id=? AND native_session_id IS NOT NULL',(session_id,))}
        if session.get('native_session_id'): natives.add(session['native_session_id'])
        provider = self._one('agents',session['agent_id'])['provider']
        for native in natives:
            identity = self.metric_identity(session['environment_id'], native)
            for table in ('token_records','token_spans'):
                self.db.execute('DELETE FROM '+table+' WHERE provider=? AND native_id=?',(provider,identity))
            self.db.execute('DELETE FROM token_activity_days WHERE native_id=?',(identity,))
        for table in ('capabilities','proposals'):
            self.db.execute('DELETE FROM '+table+' WHERE run_id IN (SELECT id FROM runs WHERE session_id=?)',(session_id,))
        self.db.execute('DELETE FROM approvals WHERE session_id=?',(session_id,))
        self.db.execute('DELETE FROM events WHERE session_id=?',(session_id,))
        self.db.execute('DELETE FROM messages WHERE sender_session_id=? OR recipient_session_id=?',(session_id,session_id))
        self.db.execute('DELETE FROM runs WHERE session_id=?',(session_id,))
        self.db.execute('DELETE FROM sessions WHERE id=?',(session_id,))

    def delete_agent(self, agent_id, cleanup):
        with self._deletion_guard(agent_id):
            targets = self._mark_agent_deletion(agent_id)
            for target in targets:
                cleanup(*target)
            with self.transaction():
                for session, _ in targets:
                    self._delete_session_records(session)
                self.db.execute('DELETE FROM messages WHERE sender_id=? OR recipient_id=?', (agent_id,agent_id))
                self.db.execute('DELETE FROM proposals WHERE agent_id=?', (agent_id,))
                self.db.execute('DELETE FROM agents WHERE id=?', (agent_id,))
        return {'ok': True}

    def _mark_agent_deletion(self, agent_id):
        with self.transaction():
            self._one('agents', agent_id)
            if self.db.execute("SELECT 1 FROM tasks WHERE owner_id=? AND status NOT IN ('completed','cancelled','archived')",(agent_id,)).fetchone():
                raise Conflict('Reassign or cancel this Agent\'s project tasks before deleting it')
            sessions = self._all('SELECT * FROM sessions WHERE agent_id=?', (agent_id,))
            if self.db.execute("SELECT 1 FROM runs WHERE agent_id=? AND status IN ('queued','running')", (agent_id,)).fetchone():
                raise Conflict('Stop active tasks before deleting an agent')
            if self.db.execute("SELECT 1 FROM messages WHERE (sender_id=? OR recipient_id=?) AND status IN ('queued','running','waiting')", (agent_id,agent_id)).fetchone():
                raise Conflict('Wait for linked tasks before deleting an agent')
            # Check every session before touching files; retain all records if
            # cleanup fails. File removal is idempotent so the user can retry.
            for session in sessions:
                self._check_session_deletion(session['id'])
            self.db.execute('UPDATE agents SET deleting=1 WHERE id=?', (agent_id,))
            return [self._cleanup_target(session) for session in sessions]
