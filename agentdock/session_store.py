"""SessionStore domain operations; mutations share the owning Store transaction."""
from __future__ import annotations
from .registry import PROVIDERS, ACP_PROVIDERS
import json
import re
import shutil
import uuid
import posixpath
from pathlib import Path



from .errors import Invalid, Conflict, Forbidden, now, text


class SessionStore:
    def add_project(self, name, path, environment_id='local'):
        environment_id=environment_id or 'local'
        self.get_environment(environment_id)
        path=text(path,'path',4096)
        if environment_id=='local':
            path=Path(path).expanduser()
            if not path.is_absolute() or not path.is_dir(): raise Invalid("Choose an existing absolute workspace directory")
            path=str(path.resolve())
        elif not path.startswith('/') or any(ord(c)<32 for c in path): raise Invalid('Use an absolute directory on the remote host')
        else: path=posixpath.normpath(path)
        item = dict(id=str(uuid.uuid4()), name=text(name,"name",100), path=path, created_at=now(),environment_id=environment_id,confirm_dispatch=0)
        with self.transaction():
            self.db.execute("INSERT INTO projects(id,name,path,created_at,environment_id,confirm_dispatch) VALUES(:id,:name,:path,:created_at,:environment_id,:confirm_dispatch)",item)
        return item


    def add_agent(self, project_id, name, provider, role="", workspace=None, model=None, effort=None, environment_id='local', permission_mode='ask', account_id=None, account_policy='manual', account_ids=None, run_timeout=None):
        if provider not in PROVIDERS: raise Invalid("Unsupported provider")
        model, effort = self._settings(model, effort, provider)
        permission_mode = self._permission_mode(permission_mode)
        environment_id=environment_id or 'local'
        self.get_environment(environment_id)
        item = dict(id=str(uuid.uuid4()),project_id=project_id or None,name=text(name,"name",100),provider=provider,role=text(role,"role",4000,True),created_at=now(),model=model,effort=effort,environment_id=environment_id,permission_mode=permission_mode,source_agent_id=None,deleting=0,run_timeout=self._run_timeout(run_timeout))
        with self.transaction():
            item.update(self._account_settings(provider, environment_id, account_id, account_policy, account_ids))
            item["workspace"] = self._workspace(project_id, workspace, item["id"],environment_id)
            self.db.execute("INSERT INTO agents(id,project_id,name,provider,role,created_at,workspace,model,effort,environment_id,permission_mode) VALUES(:id,:project_id,:name,:provider,:role,:created_at,:workspace,:model,:effort,:environment_id,:permission_mode)",item)
            self.db.execute("UPDATE agents SET account_id=?,account_policy=?,account_ids=? WHERE id=?", (item["account_id"],item["account_policy"],json.dumps(item["account_ids"]),item["id"]))
            self.db.execute("UPDATE agents SET run_timeout=? WHERE id=?", (item["run_timeout"], item["id"]))
        return item


    def update_agent(self, agent_id, changes):
        if not isinstance(changes, dict) or not changes or set(changes) - {"name", "role", "model", "effort", "workspace", "project_id", "permission_mode", "environment_id", "account_id", "account_policy", "account_ids", "run_timeout"}:
            raise Invalid("Only agent settings can be updated")
        with self.transaction():
            agent = self._available("agents", agent_id)
            environment_id = text(changes.get('environment_id', agent['environment_id']), 'environment_id', 160)
            self._one('environments', environment_id)
            relocated = environment_id != agent['environment_id']
            account_settings = self._account_settings(agent['provider'], environment_id, changes.get('account_id', None if relocated else agent['account_id']), changes.get('account_policy', 'manual' if relocated else agent['account_policy']), changes.get('account_ids', [] if relocated else agent['account_ids']))
            model, effort = self._settings(changes.get("model", None if relocated else agent["model"]), changes.get("effort", None if relocated else agent["effort"]), agent['provider'])
            permission_mode = self._permission_mode(changes.get("permission_mode", agent["permission_mode"]))
            run_timeout = self._run_timeout(changes.get("run_timeout", agent["run_timeout"]))
            project_id = changes.get("project_id", agent["project_id"]) or None
            if agent['source_agent_id'] and project_id != agent['project_id']:
                raise Conflict('Add this agent to the other project separately')
            workspace = changes.get("workspace", None if relocated else agent["workspace"])
            moved = project_id != agent["project_id"] or workspace != agent["workspace"]
            if (project_id != agent['project_id'] or (moved and not relocated)) and self.db.execute("SELECT 1 FROM sessions WHERE agent_id=?", (agent_id,)).fetchone():
                raise Conflict("Create a new agent to change the workspace or project after a conversation exists")
            if not relocated and (moved or (model, effort, permission_mode, run_timeout) != (agent['model'], agent['effort'], agent['permission_mode'], agent['run_timeout'])) and self.db.execute("SELECT 1 FROM runs WHERE agent_id=? AND status IN ('queued','running')", (agent_id,)).fetchone():
                raise Conflict("Wait for active tasks before changing agent settings")
            workspace = self._workspace(project_id, workspace, agent_id,environment_id) if moved or relocated else workspace
            if relocated:
                # Freeze inherited defaults once; repeated moves must not rebind old conversations.
                defaults = {key: agent[key] for key in ('model', 'effort', 'permission_mode', 'run_timeout')}
                self.db.execute('UPDATE sessions SET agent_defaults=? WHERE agent_id=? AND agent_defaults IS NULL',
                                (json.dumps(defaults), agent_id))
            self.db.execute("UPDATE agents SET name=?,role=?,model=?,effort=?,project_id=?,workspace=?,permission_mode=?,environment_id=? WHERE id=?", (text(changes.get("name", agent["name"]), "name", 100), text(changes.get("role", agent["role"]), "role", 4000, True), model, effort, project_id, workspace, permission_mode, environment_id, agent_id))
            self.db.execute("UPDATE agents SET account_id=?,account_policy=?,account_ids=? WHERE id=?", (account_settings["account_id"],account_settings["account_policy"],json.dumps(account_settings["account_ids"]),agent_id))
            self.db.execute("UPDATE agents SET run_timeout=? WHERE id=?", (run_timeout, agent_id))
            return self._one("agents", agent_id)


    def _add_session(self, agent_id, title, account_settings=None):
        agent = self._available("agents",agent_id)
        if account_settings is not None:
            if not isinstance(account_settings, dict) or set(account_settings) - {'account_id','account_policy','account_ids'}:
                raise Invalid('Invalid session account settings')
            agent = {**agent, **self._account_settings(agent['provider'], agent['environment_id'],
                account_settings.get('account_id', agent['account_id']), account_settings.get('account_policy', agent['account_policy']),
                account_settings.get('account_ids', agent['account_ids']))}
        item = dict(id=str(uuid.uuid4()),project_id=agent["project_id"],agent_id=agent_id,title=text(title,"title",160),status="idle",native_session_id=None,workspace=agent["workspace"],created_at=now(),updated_at=now(),environment_id=agent['environment_id'])
        if self._automatic_workspace(agent['workspace'], agent['id'], agent['environment_id']):
            item['workspace'] = self._session_workspace(item['id'], agent['environment_id'])
        self.db.execute("INSERT INTO sessions(id,project_id,agent_id,title,status,native_session_id,created_at,updated_at,workspace,environment_id) VALUES(:id,:project_id,:agent_id,:title,:status,:native_session_id,:created_at,:updated_at,:workspace,:environment_id)",item)
        generation = self._one('accounts', agent['account_id'])['generation'] if agent['account_id'] else 0
        self.db.execute('UPDATE sessions SET account_id=?,account_policy=?,account_ids=?,account_generation=? WHERE id=?',
                        (agent['account_id'], agent['account_policy'], json.dumps(agent['account_ids']), generation, item['id']))
        self.db.execute('INSERT INTO session_account_branches VALUES(?,0,?,?,NULL,?)', (item['id'],agent['account_id'],generation,now()))
        return self._one('sessions', item['id'])


    def add_session(self, agent_id, title, account_settings=None):
        with self.transaction(): return self._add_session(agent_id, title, account_settings)


    def session_directory(self, session_id):
        from .session_storage import session_directory
        return session_directory(self.workspaces.parent / 'sessions', session_id)


    def _automatic_workspace(self, workspace, agent_id, environment_id):
        return workspace == (str(self.workspaces / agent_id) if environment_id == 'local'
                             else '~/.local/share/agentdock/workspaces/' + agent_id)


    def _session_workspace(self, session_id, environment_id):
        if environment_id != 'local':
            return '~/.local/share/agentdock/ssh/controllers/' + self.controller_id + '/sessions/' + session_id + '/workspace'
        from .codex_home import _private
        return str(_private(self.session_directory(session_id) / 'workspace'))


    def _migrate_session_workspaces(self):
        # Only AgentDock's old automatic directories are migrated. Explicit project
        # directories stay shared, and are never included in session deletion.
        with self.transaction():
            for row in self.db.execute('SELECT * FROM sessions').fetchall():
                if not self._automatic_workspace(row['workspace'], row['agent_id'], row['environment_id']): continue
                old = row['workspace']
                destination = self._session_workspace(row['id'], row['environment_id'])
                if row['environment_id'] == 'local' and Path(old).is_dir():
                    shutil.copytree(old, destination, dirs_exist_ok=True, symlinks=True)
                self.db.execute('UPDATE sessions SET workspace=?,legacy_workspace=? WHERE id=?', (destination,old,row['id']))


    def bind_native_session(self, session_id, native_session_id, run_id=None):
        """Called only by the trusted adapter after a provider creates a session."""
        native_session_id = text(native_session_id, "native_session_id", 512)
        with self.transaction():
            session = self._one("sessions", session_id)
            if run_id is not None:
                run = self._one("runs", run_id)
                if run["session_id"] != session_id or run["status"] != "running":
                    raise Forbidden("Native session binding requires this session's active run")
            if session["native_session_id"] not in (None, native_session_id):
                raise Conflict("Native session is already bound")
            provider = self._one("agents", session["agent_id"])["provider"]
            existing = self.db.execute("SELECT sessions.id FROM session_account_branches AS branch JOIN sessions ON branch.session_id=sessions.id JOIN agents ON sessions.agent_id=agents.id WHERE branch.native_session_id=? AND agents.provider=? AND sessions.environment_id=? AND (sessions.id<>? OR branch.branch<>?)", (native_session_id, provider, session['environment_id'],session_id,session['account_branch'])).fetchone()
            if existing: raise Conflict("Native session is already owned by another AgentDock session")
            if run_id is not None and run['account_branch'] != session['account_branch']:
                raise Conflict('Native session binding belongs to a different account branch')
            self.db.execute("UPDATE sessions SET native_session_id=?,updated_at=? WHERE id=?", (native_session_id, now(), session_id))
            self.db.execute('UPDATE session_account_branches SET native_session_id=? WHERE session_id=? AND branch=?', (native_session_id,session_id,session['account_branch']))
            return self._one("sessions", session_id)


    def update_session_settings(self, session_id, changes):
        if isinstance(changes, dict) and set(changes) == {'inherit'} and changes['inherit'] is True:
            model, effort, override = None, None, 0
        elif isinstance(changes, dict) and set(changes) == {'model', 'effort'}:
            provider = self.get_agent(self.get_session(session_id)['agent_id'])['provider']
            model, effort = self._settings(changes['model'], changes['effort'], provider)
            override = 1
        else:
            raise Invalid('Invalid session model settings')
        with self.transaction():
            self._available('sessions', session_id)
            self.db.execute('UPDATE sessions SET model=?,effort=?,model_override=?,updated_at=? WHERE id=?',
                            (model, effort, override, now(), session_id))
            return self._one('sessions', session_id)


    @staticmethod
    def _settings(model, effort, provider=None):
        model = text(model, "model", 160, True) if model is not None else None
        effort = text(effort, "effort", 32, True) if effort is not None else None
        if provider in ACP_PROVIDERS:
            # ACP options are opaque IDs sent as JSON and checked against the
            # CLI's offered choices before prompting, never shell arguments.
            if any(ord(c) < 32 or ord(c) == 127 for c in (model or '') + (effort or '')):
                raise Invalid('Invalid model or reasoning option')
        else:
            if model and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/()\[\]-]{0,159}", model): raise Invalid("Invalid model identifier")
            if effort and effort not in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "ultracode"): raise Invalid("Invalid reasoning effort")
        return model or None, effort or None


