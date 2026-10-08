"""Durable project work; native conversations are replaceable execution records.

Internal helpers run under Store.transaction/lock. Public mutations own exactly
one transaction, so inputs, run admission and task revisions commit together.
"""
import json
import uuid


class TaskStore:
    def _migrate_tasks(self):
        with self.transaction():
            self.db.execute('''CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
                title TEXT NOT NULL,goal TEXT NOT NULL,criteria TEXT NOT NULL,
                owner_id TEXT NOT NULL,session_id TEXT,status TEXT NOT NULL DEFAULT 'draft',
                intent TEXT NOT NULL DEFAULT 'record',acceptance_policy TEXT NOT NULL DEFAULT 'owner',
                review_required INTEGER NOT NULL DEFAULT 0,workspace_mode TEXT NOT NULL DEFAULT 'shared',
                revision INTEGER NOT NULL DEFAULT 0,delivery_id TEXT,source_session_id TEXT,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS task_inputs(
                id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),request_id TEXT NOT NULL,
                body TEXT NOT NULL,intent TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,
                run_id TEXT,created_at TEXT NOT NULL,UNIQUE(task_id,request_id))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS task_questions(
                id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),run_id TEXT NOT NULL,
                question TEXT NOT NULL,options TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',
                answer TEXT,created_at TEXT NOT NULL,answered_at TEXT)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS task_deliveries(
                id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),run_id TEXT NOT NULL,
                revision INTEGER NOT NULL,summary TEXT NOT NULL,checks TEXT NOT NULL,artifacts TEXT NOT NULL,
                risks TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'candidate',created_at TEXT NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS task_journal(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL REFERENCES tasks(id),
                kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS task_workspaces(
                task_id TEXT NOT NULL REFERENCES tasks(id),agent_id TEXT NOT NULL,
                environment_id TEXT NOT NULL,path TEXT NOT NULL,base_commit TEXT NOT NULL,
                PRIMARY KEY(task_id,agent_id,environment_id))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS task_reviews(
                id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),run_id TEXT NOT NULL,
                revision INTEGER NOT NULL,verdict TEXT NOT NULL,summary TEXT NOT NULL,created_at TEXT NOT NULL)''')
            for table in ('sessions', 'runs'):
                columns = {row[1] for row in self.db.execute('PRAGMA table_info('+table+')')}
                for name, definition in {'work_task_id': 'TEXT REFERENCES tasks(id)',
                                         'task_role': 'TEXT', 'task_intent': 'TEXT'}.items():
                    if name not in columns: self.db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
            self.db.execute('CREATE INDEX IF NOT EXISTS task_runs ON runs(work_task_id,status)')
            if 'task_revision' not in {r[1] for r in self.db.execute('PRAGMA table_info(runs)')}:
                self.db.execute('ALTER TABLE runs ADD COLUMN task_revision INTEGER')
            self.db.execute('CREATE INDEX IF NOT EXISTS task_inputs_order ON task_inputs(task_id,created_at)')
            self.db.execute('CREATE INDEX IF NOT EXISTS task_journal_order ON task_journal(task_id,seq)')

    def _task_event(self, task_id, kind, payload):
        from .store import now
        self.db.execute('INSERT INTO task_journal(task_id,kind,payload,created_at) VALUES(?,?,?,?)',
                        (task_id,kind,json.dumps(payload,ensure_ascii=False),now()))
        self.db.execute('UPDATE tasks SET updated_at=? WHERE id=?', (now(),task_id))

    def get_task(self, task_id):
        with self.lock: return self._one('tasks',task_id)

    def task_detail(self, task_id):
        with self.lock:
            task = self._one('tasks',task_id)
            result = dict(task)
            for key, table in (('inputs','task_inputs'),('questions','task_questions'),('deliveries','task_deliveries'),('reviews','task_reviews')):
                result[key] = self._all('SELECT * FROM '+table+' WHERE task_id=? ORDER BY rowid', (task_id,))
            result['journal'] = self._all('SELECT * FROM task_journal WHERE task_id=? ORDER BY seq', (task_id,))
            result['runs'] = self._all('SELECT * FROM runs WHERE work_task_id=? ORDER BY created_at,rowid',(task_id,))
            result['sessions'] = self._all('SELECT * FROM sessions WHERE work_task_id=? ORDER BY created_at,rowid',(task_id,))
            result['workspaces'] = self._all('SELECT * FROM task_workspaces WHERE task_id=?',(task_id,))
            return result

    def _task_owner(self, task, agent_id):
        from .store import Forbidden
        agent = self._available('agents',agent_id)
        if agent['project_id'] != task['project_id']: raise Forbidden('Choose an Agent in this project')
        project = self._one('projects',task['project_id'])
        if agent['environment_id'] != project['environment_id']:
            raise Forbidden('Task Agents must use the project device')
        return agent

    def create_task(self, project_id, title, goal, criteria, owner_id, *, acceptance_policy='owner',
                    review_required=False, workspace_mode='shared', source_session_id=None):
        from .store import Invalid, Forbidden, text, now
        if acceptance_policy not in ('owner','human'): raise Invalid('Invalid acceptance policy')
        if type(review_required) is not bool: raise Invalid('Invalid review requirement')
        if workspace_mode not in ('shared','worktree'): raise Invalid('Invalid workspace mode')
        # Criteria are line-oriented so the delivery can cover each exact item.
        criteria = text(criteria,'criteria',8000)
        criteria = '\n'.join(dict.fromkeys(x.strip() for x in criteria.splitlines() if x.strip()))
        if len(criteria.splitlines()) > 30: raise Invalid('Use at most 30 acceptance criteria')
        item = dict(id=str(uuid.uuid4()),project_id=project_id,title=text(title,'title',160),
                    goal=text(goal,'goal',16000),criteria=criteria,owner_id=owner_id,
                    acceptance_policy=acceptance_policy,review_required=int(review_required),
                    workspace_mode=workspace_mode,source_session_id=source_session_id,created_at=now(),updated_at=now())
        with self.transaction():
            self._one('projects',project_id)
            self._task_owner(item,owner_id)
            source = None
            if source_session_id:
                source = self._one('sessions',source_session_id)
                if source['project_id'] not in (None,project_id): raise Forbidden('Cannot import a conversation from another project')
            self.db.execute('''INSERT INTO tasks(id,project_id,title,goal,criteria,owner_id,acceptance_policy,
                review_required,workspace_mode,source_session_id,created_at,updated_at)
                VALUES(:id,:project_id,:title,:goal,:criteria,:owner_id,:acceptance_policy,:review_required,
                :workspace_mode,:source_session_id,:created_at,:updated_at)''',item)
            self._task_event(item['id'],'created',item)
            if source:
                # Copy bounded source facts, never adopt or rewrite its native history.
                history = self._all('SELECT id,prompt,result,status FROM runs WHERE session_id=? ORDER BY rowid DESC LIMIT 20',(source_session_id,))
                self._task_event(item['id'],'conversation_imported',{'session_id':source_session_id,
                    'history':[dict(id=r['id'],prompt=r['prompt'][:3000],result=(r['result'] or '')[:6000],status=r['status']) for r in reversed(history)]})
            return self._one('tasks',item['id'])

    def _task_live(self, task_id):
        return self.db.execute("SELECT 1 FROM runs WHERE work_task_id=? AND status IN ('queued','running')",(task_id,)).fetchone() is not None

    def update_task(self, task_id, title, goal, criteria, acceptance_policy, review_required):
        from .store import Conflict, Invalid, text
        title,goal=text(title,'title',160),text(goal,'goal',16000)
        criteria='\n'.join(dict.fromkeys(x.strip() for x in text(criteria,'criteria',8000).splitlines() if x.strip()))
        if len(criteria.splitlines())>30: raise Invalid('Use at most 30 acceptance criteria')
        if acceptance_policy not in ('owner','human') or type(review_required) is not bool: raise Invalid('Invalid acceptance settings')
        with self.transaction():
            task=self._one('tasks',task_id)
            if self._task_live(task_id): raise Conflict('Pause execution before changing task requirements')
            if task['status'] in ('completed','cancelled','archived'): raise Conflict('Reopen this task before changing requirements')
            values=dict(title=title,goal=goal,criteria=criteria,acceptance_policy=acceptance_policy,review_required=int(review_required))
            if all(task[key]==value for key,value in values.items()): return task
            status=task['status'] if task['status'] in ('paused','interrupted','waiting_input') else 'draft'
            self.db.execute('''UPDATE tasks SET title=:title,goal=:goal,criteria=:criteria,acceptance_policy=:acceptance_policy,
                review_required=:review_required,revision=revision+1,delivery_id=NULL,status=:status WHERE id=:id''',
                {**values,'status':status,'id':task_id})
            self._task_event(task_id,'requirements_changed',values)
            return self._one('tasks',task_id)

    def _task_session(self, task, agent_id=None, role='owner', intent=None, fresh=False):
        agent_id, intent = agent_id or task['owner_id'], intent or task['intent']
        self._task_owner(task,agent_id)
        row = None if fresh else self.db.execute('''SELECT id FROM sessions WHERE work_task_id=? AND agent_id=?
            AND task_role=? AND task_intent=? ORDER BY rowid DESC LIMIT 1''',(task['id'],agent_id,role,intent)).fetchone()
        if row: return self._one('sessions',row['id'])
        session = self._add_session(agent_id,task['title'])
        project = self._one('projects',task['project_id'])
        workspace = project['path']
        if task['workspace_mode'] == 'worktree':
            # Review the owner's integrated files, in a separate native history.
            workspace_agent = task['owner_id'] if role=='reviewer' else agent_id
            owned = self.db.execute('SELECT path FROM task_workspaces WHERE task_id=? AND agent_id=? AND environment_id=?',
                                    (task['id'],workspace_agent,project['environment_id'])).fetchone()
            if owned: workspace=owned['path']
            elif project['environment_id']=='local': workspace=str(self.workspaces.parent/'tasks'/task['id']/workspace_agent/'workspace')
            else: workspace='~/.local/share/agentdock/ssh/controllers/'+self.controller_id+'/tasks/'+task['id']+'/'+workspace_agent+'/workspace'
        self.db.execute('UPDATE sessions SET work_task_id=?,task_role=?,task_intent=?,workspace=? WHERE id=?',
                        (task['id'],role,intent,workspace,session['id']))
        if role == 'owner': self.db.execute('UPDATE tasks SET session_id=? WHERE id=?',(session['id'],task['id']))
        return self._one('sessions',session['id'])

    def submit_task_input(self, task_id, body, intent, request_id, *, action='queue', expected_run_id=None):
        from .store import text, Invalid, Conflict, now
        body, request_id = text(body,'body',24000), text(request_id,'request_id',128)
        if intent not in ('record','discuss','develop'): raise Invalid('Invalid task intent')
        if action not in ('queue','steer'): raise Invalid('Invalid input action')
        with self.transaction():
            task = self._one('tasks',task_id)
            existing = self.db.execute('SELECT * FROM task_inputs WHERE task_id=? AND request_id=?',(task_id,request_id)).fetchone()
            if existing:
                if (existing['body'],existing['intent'],existing['action']) != (body,intent,action):
                    raise Conflict('Request identity already belongs to another input')
                return dict(existing)
            if task['status'] in ('archived','cancelled','paused','interrupted'):
                raise Conflict('Resume this task before submitting more work')
            if task['status'] == 'completed': raise Conflict('Reopen this task before adding requirements')
            if self._task_live(task_id) and intent not in ('record',task['intent']):
                raise Conflict('Wait for the current work before changing discussion or execution mode')
            if action == 'steer':
                if intent=='record': raise Invalid('Notes are recorded without interrupting execution')
                run = self._one('runs',expected_run_id)
                if (run['work_task_id'] != task_id or run['status'] != 'running' or run['task_role'] != 'owner'
                        or intent != task['intent']): raise Conflict('The active task run changed')
                run_id, status = run['id'], 'pending'
            else:
                run_id, status = None, 'recorded'
                if intent != 'record':
                    session = self._task_session(task,intent=intent)
                    self.db.execute("UPDATE tasks SET intent=?,status='active' WHERE id=?",(intent,task_id))
                    run_id = self._enqueue_run(session['id'],body)['id']
                    status = 'queued'
                    if self.db.execute("SELECT 1 FROM task_questions WHERE task_id=? AND status='open'",(task_id,)).fetchone():
                        self.db.execute("UPDATE tasks SET status='waiting_input' WHERE id=?",(task_id,))
            identifier = str(uuid.uuid4())
            self.db.execute('INSERT INTO task_inputs VALUES(?,?,?,?,?,?,?,?,?)',
                (identifier,task_id,request_id,body,intent,action,status,run_id,now()))
            if intent!='record': self.db.execute('UPDATE tasks SET revision=revision+1,delivery_id=NULL WHERE id=?',(task_id,))
            self._task_event(task_id,'input',{'input_id':identifier,'intent':intent,'action':action})
            return self._one('task_inputs',identifier)

    def task_input_receipt(self, input_id, status):
        from .store import Invalid
        if status not in ('accepted','rejected','unknown'): raise Invalid('Invalid receipt')
        with self.transaction():
            item=self._one('task_inputs',input_id)
            if item['status'] != 'pending': return item
            self.db.execute('UPDATE task_inputs SET status=? WHERE id=?',(status,input_id))
            if status=='accepted':
                self.db.execute('UPDATE runs SET task_revision=(SELECT revision FROM tasks WHERE id=?) WHERE id=?',(item['task_id'],item['run_id']))
            self._task_event(item['task_id'],'input_receipt',{'input_id':input_id,'status':status})
            return self._one('task_inputs',input_id)

    def task_question(self, run, question, options=None):
        from .store import text, Invalid, now
        question=text(question,'question',4000)
        options=[] if options is None else options
        if not isinstance(options,list) or len(options)>8: raise Invalid('Use at most 8 answer choices')
        options=[text(x,'option',500) for x in options]
        with self.transaction():
            task=self._task_run_authority(run)
            identifier=str(uuid.uuid4())
            self.db.execute('INSERT INTO task_questions(id,task_id,run_id,question,options,created_at) VALUES(?,?,?,?,?,?)',
                (identifier,task['id'],run['id'],question,json.dumps(options,ensure_ascii=False),now()))
            self.db.execute("UPDATE tasks SET status='waiting_input',revision=revision+1,delivery_id=NULL WHERE id=?",(task['id'],))
            self._task_event(task['id'],'question',{'question_id':identifier})
            return self._one('task_questions',identifier)

    def answer_task_question(self, task_id, question_id, answer):
        from .store import text, Conflict, Forbidden, now
        answer=text(answer,'answer',8000)
        with self.transaction():
            question=self._one('task_questions',question_id)
            if question['task_id'] != task_id: raise Forbidden('Question belongs to another task')
            if question['status']=='answered':
                if question['answer']!=answer: raise Conflict('Question was already answered')
                return question
            task=self._one('tasks',task_id)
            if task['status'] in ('archived','completed','cancelled'): raise Conflict('Task is closed')
            self.db.execute("UPDATE task_questions SET status='answered',answer=?,answered_at=? WHERE id=?",(answer,now(),question_id))
            self.db.execute('UPDATE tasks SET revision=revision+1,delivery_id=NULL WHERE id=?',(task_id,))
            self._task_event(task_id,'decision',{'question_id':question_id,'question':question['question'],'answer':answer})
            # A paused/interrupted task retains the answer until explicit recovery.
            if task['status'] not in ('paused','interrupted') and not self.db.execute("SELECT 1 FROM task_questions WHERE task_id=? AND status='open'",(task_id,)).fetchone():
                session=self._task_session(task)
                self.db.execute("UPDATE tasks SET status='active' WHERE id=?",(task_id,))
                self._enqueue_run(session['id'],'A task question has been answered. Read task_context for the saved decision and continue the existing goal.')
            return self._one('task_questions',question_id)

    def _task_run_authority(self, run, owner=False):
        from .store import Forbidden
        current=self._one('runs',run['id'])
        if not current.get('work_task_id') or current['status'] != 'running': raise Forbidden('An active project task is required')
        task=self._one('tasks',current['work_task_id'])
        if task['status'] in ('paused','interrupted','completed','cancelled','archived'): raise Forbidden('Task is not accepting agent changes')
        if owner and (current['agent_id'] != task['owner_id'] or current['session_id'] != task['session_id'] or current['task_role'] != 'owner'):
            raise Forbidden('Only the current task owner may deliver or coordinate work')
        return task

    def task_delivery(self, run, summary, checks, artifacts=None, risks=''):
        from .store import text, Invalid, Conflict, now
        summary,risks=text(summary,'summary',24000),text(risks,'risks',8000,True)
        if not isinstance(checks,list) or not 1<=len(checks)<=30: raise Invalid('Provide acceptance checks')
        cleaned=[]
        for check in checks:
            if not isinstance(check,dict) or set(check)!={'criterion','status','evidence'}: raise Invalid('Invalid acceptance check')
            if check['status'] not in ('passed','failed','unverified'): raise Invalid('Invalid check status')
            cleaned.append(dict(criterion=text(check['criterion'],'criterion',8000),status=check['status'],evidence=text(check['evidence'],'evidence',4000)))
        artifacts=[] if artifacts is None else artifacts
        if not isinstance(artifacts,list) or len(artifacts)>30: raise Invalid('Use at most 30 artifact references')
        artifacts=[text(x,'artifact',2000) for x in artifacts]
        with self.transaction():
            task=self._task_run_authority(run,owner=True)
            if run['task_intent'] != 'develop': raise Conflict('Discussion cannot deliver implementation')
            if run['task_revision'] != task['revision']: raise Conflict('Requirements changed during this run; process the queued input before delivering')
            if sorted(c['criterion'] for c in cleaned)!=sorted(task['criteria'].splitlines()):
                raise Invalid('Delivery must cover every acceptance criterion exactly once')
            identifier=str(uuid.uuid4())
            self.db.execute('INSERT INTO task_deliveries(id,task_id,run_id,revision,summary,checks,artifacts,risks,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (identifier,task['id'],run['id'],task['revision'],summary,json.dumps(cleaned,ensure_ascii=False),json.dumps(artifacts,ensure_ascii=False),risks,now()))
            self.db.execute('UPDATE tasks SET delivery_id=? WHERE id=?',(identifier,task['id']))
            self._task_event(task['id'],'delivery',{'delivery_id':identifier,'run_id':run['id']})
            return self._one('task_deliveries',identifier)

    def task_review(self, run, verdict, summary):
        from .store import Forbidden, Invalid, Conflict, text, now
        if verdict not in ('approved','changes_requested','unverified'): raise Invalid('Invalid review verdict')
        summary=text(summary,'summary',16000)
        with self.transaction():
            task=self._task_run_authority(run)
            if run['task_role']!='reviewer' or run['agent_id']==task['owner_id']:
                raise Forbidden('An independent reviewer must submit this report')
            if run['task_revision']!=task['revision']: raise Conflict('Review no longer covers the latest requirements')
            identifier=str(uuid.uuid4())
            self.db.execute('INSERT INTO task_reviews VALUES(?,?,?,?,?,?,?)',
                (identifier,task['id'],run['id'],task['revision'],verdict,summary,now()))
            self._task_event(task['id'],'review',{'review_id':identifier,'verdict':verdict})
            return self._one('task_reviews',identifier)

    def _task_can_accept(self, task):
        from .store import Conflict
        if self._task_live(task['id']): raise Conflict('Wait for task execution and delegated results')
        if self.db.execute("SELECT 1 FROM task_questions WHERE task_id=? AND status='open'",(task['id'],)).fetchone():
            raise Conflict('Answer the pending task questions first')
        if not task['delivery_id']: raise Conflict('The task owner has not submitted a delivery')
        delivery=self._one('task_deliveries',task['delivery_id'])
        if delivery['revision']!=task['revision']: raise Conflict('Delivery does not cover the latest requirements')
        run=self._one('runs',delivery['run_id'])
        if run['status']!='completed': raise Conflict('Delivery execution did not finish successfully')
        if any(c['status']!='passed' for c in delivery['checks']): raise Conflict('All acceptance checks need passing evidence')
        if task['review_required']:
            review=self.db.execute('''SELECT v.verdict,r.rowid AS run_order FROM task_reviews v JOIN runs r ON r.id=v.run_id
                WHERE v.task_id=? AND v.revision=? AND r.status='completed'
                AND r.rowid < (SELECT rowid FROM runs WHERE id=?) ORDER BY v.rowid DESC LIMIT 1''',
                (task['id'],task['revision'],run['id'])).fetchone()
            if not review or review['verdict']!='approved': raise Conflict('An approved independent review is required before final delivery')
            if self.db.execute("SELECT 1 FROM runs WHERE work_task_id=? AND task_role='worker' AND rowid>?",(task['id'],review['run_order'])).fetchone():
                raise Conflict('Request a new review after the latest delegated changes')
        if self.db.execute("SELECT 1 FROM messages WHERE sender_run_id IN (SELECT id FROM runs WHERE work_task_id=?) AND status IN ('queued','running','waiting')",(task['id'],)).fetchone():
            raise Conflict('Wait for delegated results')
        return delivery

    def accept_task(self, task_id):
        with self.transaction():
            task=self._one('tasks',task_id)
            from .store import Conflict
            if task['status']=='completed': return task
            if task['status']!='review': raise Conflict('Task is not ready for acceptance')
            delivery=self._task_can_accept(task)
            self.db.execute("UPDATE task_deliveries SET status='accepted' WHERE id=?",(delivery['id'],))
            self.db.execute("UPDATE tasks SET status='completed' WHERE id=?",(task_id,))
            self._task_event(task_id,'accepted',{'delivery_id':delivery['id'],'by':'human'})
            return self._one('tasks',task_id)

    def _refresh_work_task(self, run):
        """Called after delivery return scheduling, never before child replies exist."""
        from .store import Conflict, Missing
        task_id=run.get('work_task_id')
        if not task_id: return
        task=self._one('tasks',task_id)
        self.db.execute("UPDATE task_inputs SET status=CASE WHEN status='pending' THEN 'unknown' ELSE ? END WHERE run_id=? AND status IN ('queued','accepted','pending')",('processed' if run['status']=='completed' else 'interrupted',run['id']))
        self._task_event(task_id,'run_finished',{'run_id':run['id'],'status':run['status'],'result':run.get('result'),
                                               'error':run.get('error'),'agent_id':run['agent_id'],'role':run['task_role']})
        if task['status'] in ('paused','cancelled','archived','completed'): return
        if self._task_live(task_id): return
        if self.db.execute("SELECT 1 FROM task_questions WHERE task_id=? AND status='open'",(task_id,)).fetchone(): status='waiting_input'
        elif run['status'] in ('failed','cancelled','interrupted'): status='interrupted'
        elif task['intent']=='discuss': status='draft'
        else: status='review'
        self.db.execute('UPDATE tasks SET status=? WHERE id=?',(status,task_id))
        if status=='review' and task['acceptance_policy']=='owner':
            try: delivery=self._task_can_accept(task)
            except (Conflict,Missing): return
            self.db.execute("UPDATE task_deliveries SET status='accepted' WHERE id=?",(delivery['id'],))
            self.db.execute("UPDATE tasks SET status='completed' WHERE id=?",(task_id,))
            self._task_event(task_id,'accepted',{'delivery_id':delivery['id'],'by':'owner'})

    def refresh_work_task(self, run_id):
        with self.transaction(): self._refresh_work_task(self._one('runs',run_id))

    def task_transition(self, task_id, action):
        from .store import Conflict, Invalid
        with self.transaction():
            task=self._one('tasks',task_id)
            if action in ('pause','cancel'):
                if task['status'] in ('completed','archived','cancelled'): raise Conflict('Task is closed')
                status='paused' if action=='pause' else 'cancelled'
                self.db.execute('UPDATE tasks SET status=? WHERE id=?',(status,task_id))
                self.db.execute("UPDATE task_inputs SET status=CASE WHEN status='pending' THEN 'unknown' ELSE 'interrupted' END WHERE task_id=? AND status IN ('queued','accepted','pending')",(task_id,))
            elif action=='archive':
                if task['status'] not in ('completed','cancelled') or self._task_live(task_id): raise Conflict('Finish or cancel this task before archiving')
                self.db.execute("UPDATE tasks SET status='archived' WHERE id=?",(task_id,))
            elif action=='reopen':
                if task['status'] not in ('completed','cancelled'): raise Conflict('Only a completed or cancelled task can reopen')
                if self._task_live(task_id): raise Conflict('Wait for task processes to stop')
                self.db.execute("UPDATE tasks SET status='draft',revision=revision+1,delivery_id=NULL WHERE id=?",(task_id,))
            else: raise Invalid('Invalid task transition')
            self._task_event(task_id,action,{})
            return self._one('tasks',task_id)

    def task_recovery(self, task_id, owner_id, intent, request_id):
        from .store import Conflict, text
        if request_id is None: return None
        request_id=text(request_id,'request_id',128)
        with self.lock:
            task=self._one('tasks',task_id)
            records=self._all("SELECT payload FROM task_journal WHERE task_id=? AND kind='resumed' AND json_extract(payload,'$.request_id')=? LIMIT 1",(task_id,request_id))
            if not records: return None
            prior=records[0]['payload']
            if (prior.get('requested_owner'),prior.get('intent'))!=(owner_id,intent):
                raise Conflict('Request identity already belongs to another recovery')
            return task

    def resume_task(self, task_id, owner_id=None, intent='develop', request_id=None):
        from .store import Conflict, Invalid
        if intent not in ('discuss','develop'): raise Invalid('Choose discussion or execution')
        with self.transaction():
            previous=self.task_recovery(task_id,owner_id,intent,request_id)
            if previous: return previous
            requested_owner=owner_id
            task=self._one('tasks',task_id)
            if task['status'] in ('archived','cancelled','completed'): raise Conflict('Reopen this task before continuing')
            if self._task_live(task_id): raise Conflict('Wait for old task execution to stop before continuing')
            owner_id=owner_id or task['owner_id']
            self._task_owner(task,owner_id)
            if owner_id!=task['owner_id']:
                self.db.execute('UPDATE tasks SET owner_id=?,session_id=NULL WHERE id=?',(owner_id,task_id))
                self._task_event(task_id,'owner_changed',{'previous':task['owner_id'],'owner_id':owner_id})
            task=self._one('tasks',task_id)
            session=self._task_session(task,intent=intent,fresh=True)
            self.db.execute("UPDATE tasks SET status='active',intent=?,revision=revision+1,delivery_id=NULL WHERE id=?",(intent,task_id))
            run=self._enqueue_run(session['id'],'Continue this task from its saved goal, decisions and results. Inspect the current workspace and unresolved attempts before acting. Do not replay completed work or effects whose outcome is unknown.')
            self._task_event(task_id,'resumed',{'run_id':run['id'],'owner_id':owner_id,'requested_owner':requested_owner,'intent':intent,'request_id':request_id})
            return self._one('tasks',task_id)

    def task_context(self, run):
        with self.lock:
            task=self._task_run_authority(run)
            # Load bounded summaries instead of the full transcript on each turn.
            records=self._all('SELECT seq,kind,payload FROM task_journal WHERE task_id=? ORDER BY seq DESC LIMIT 16',(task['id'],))
            history=[dict(seq=r['seq'],kind=r['kind'],preview=json.dumps(r['payload'],ensure_ascii=False)[:1600]) for r in reversed(records)]
            inputs=self._all('SELECT id,body,intent,status FROM task_inputs WHERE task_id=? ORDER BY rowid DESC LIMIT 12',(task['id'],))
            questions=self._all("SELECT id,question,answer,status FROM task_questions WHERE task_id=? ORDER BY status='open' DESC,rowid DESC LIMIT 12",(task['id'],))
            work=self._all('SELECT id,agent_id,task_role,status,result,error FROM runs WHERE work_task_id=? ORDER BY rowid DESC LIMIT 12',(task['id'],))
            return {**task,'your_role':run['task_role'],
                'inputs':[{**i,'body':i['body'][:2000],'truncated':len(i['body'])>2000} for i in reversed(inputs)],
                'questions':[{**q,'question':q['question'][:1000],'answer':(q['answer'] or '')[:1500]} for q in questions],
                'workspaces':self._all('SELECT * FROM task_workspaces WHERE task_id=? LIMIT 30',(task['id'],)),
                'recent_work':[{**r,'result':(r['result'] or '')[:1200]} for r in reversed(work)],
                'history':history,'history_note':'Summaries may be truncated. Read task_history from after=0 to retrieve every durable record; task_result reads full run reports.'}

    def task_history(self, run, after=0, offset=0, limit=1):
        from .errors import Invalid
        if type(after) is not int or after < 0 or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise Invalid('Invalid history cursor')
        with self.lock:
            task = self._task_run_authority(run)
            rows = self._all('SELECT * FROM task_journal WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?', (task['id'], after, limit))
            if not rows: return dict(record=None, records=[], next_after=None, next_offset=None)
            records, budget = [], 16000
            refs = {'input': ('task_inputs', 'input_id'), 'question': ('task_questions', 'question_id'),
                    'delivery': ('task_deliveries', 'delivery_id'), 'review': ('task_reviews', 'review_id')}
            next_after, next_offset = after, offset
            for row in rows:
                payload = row['payload']
                if row['kind'] in refs:
                    table, key = refs[row['kind']]
                    payload = self._one(table, payload[key])
                raw = json.dumps(payload, ensure_ascii=False)
                piece = raw[next_offset:next_offset + budget]
                more = len(raw) > next_offset + len(piece)
                records.append(dict(seq=row['seq'], kind=row['kind'], text=piece))
                budget -= len(piece)
                next_after, next_offset = (next_after, next_offset + len(piece)) if more else (row['seq'], 0)
                if more or budget == 0: break
            result = dict(records=records, next_after=next_after, next_offset=next_offset)
            if limit == 1: result.update(records[0])
            return result

    def task_result(self, run, result_run_id, offset=0):
        from .store import Forbidden, Invalid, Missing
        with self.lock:
            task=self._task_run_authority(run)
            try: other=self._one('runs',result_run_id)
            except Missing:
                records=self._all("SELECT payload FROM task_journal WHERE task_id=? AND kind='run_finished' AND json_extract(payload,'$.run_id')=? ORDER BY seq DESC LIMIT 1",(task['id'],result_run_id))
                if not records: raise
                other={**records[0]['payload'],'id':result_run_id,'work_task_id':task['id']}
            if other['work_task_id']!=task['id']: raise Forbidden('Result belongs to another task')
            if type(offset) is not int or offset<0: raise Invalid('Invalid result offset')
            result=other['result'] or ''
            return dict(run_id=other['id'],status=other['status'],error=other['error'],text=result[offset:offset+16000],
                        next_offset=offset+16000 if len(result)>offset+16000 else None)
