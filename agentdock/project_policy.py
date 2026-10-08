"""Human control of delegated work, separate from native tool permissions."""
import json
import uuid

from .errors import Conflict, Invalid, now


class ProjectPolicy:
    def _migrate_project_policy(self):
        with self.transaction():
            if 'confirm_dispatch' not in {row[1] for row in self.db.execute('PRAGMA table_info(projects)')}:
                self.db.execute('ALTER TABLE projects ADD COLUMN confirm_dispatch INTEGER NOT NULL DEFAULT 0')
            self.db.execute("CREATE INDEX IF NOT EXISTS dispatch_approval ON approvals(json_extract(request,'$.dispatch_run_id'),status)")

    def update_project_policy(self, project_id, confirm_dispatch):
        if type(confirm_dispatch) is not bool:
            raise Invalid('Project dispatch confirmation must be true or false')
        with self.transaction():
            self._one('projects', project_id)
            self.db.execute('UPDATE projects SET confirm_dispatch=? WHERE id=?', (confirm_dispatch, project_id))
            return self._one('projects', project_id)

    def _dispatch_approval(self, message, parent):
        project = self._one('projects', message['project_id'])
        if not project['confirm_dispatch']:
            return
        request = {'kind': 'dispatch', 'recipient_id': message['recipient_id'],
                   'body': message['body'], 'message_id': message['id'], 'dispatch_run_id': message['run_id']}
        options = [{'optionId': 'accept', 'name': 'Approve delegation', 'kind': 'allow_once'},
                   {'optionId': 'reject', 'name': 'Reject delegation', 'kind': 'reject_once'}]
        identifier = str(uuid.uuid4())
        self.db.execute('INSERT INTO approvals(id,run_id,session_id,project_id,request,options,status,picked_option_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                        (identifier, parent['id'], parent['session_id'], parent['project_id'],
                         json.dumps(request), json.dumps(options), 'pending', None, now()))
        self._event(parent['project_id'], parent['session_id'], 'approval_required',
                    {'approval_id': identifier, 'run_id': parent['id'], 'kind': 'dispatch'})

    def resolve_dispatch(self, identifier, option):
        with self.transaction():
            approval = self._one('approvals', identifier)
            request = approval['request']
            if request.get('kind') != 'dispatch' or option not in ('accept', 'reject'):
                raise Invalid('Invalid dispatch decision')
            child = self._one('runs', request['dispatch_run_id'])
            parent = self._one('runs', approval['run_id'])
            if approval['status'] != 'pending' or child['status'] != 'queued' or self._task_stopped(parent['task_run_id']):
                raise Conflict('This delegation is no longer awaiting approval')
            self.db.execute("UPDATE approvals SET status='resolved',picked_option_id=? WHERE id=?", (option, identifier))
            self._event(approval['project_id'], approval['session_id'], 'approval_resolved',
                        {'approval_id': identifier, 'option_id': option, 'run_id': parent['id']})
            return child
