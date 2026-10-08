"""Task orchestration reuses the native dispatcher and its project fences."""
class TaskRuntime:
    def submit_task(self, task_id, body, intent, request_id, action='queue', expected_run_id=None):
        from .store import Conflict
        with self._lock:
            task=self.store.get_task(task_id)
            if intent!='record':
                self._check_enabled()
                self._agent_command(self.store.get_agent(task['owner_id']))
            if action=='steer':
                live=self._runs.get(expected_run_id)
                if not live or live.stop.is_set() or not live.control.available:
                    raise Conflict('This run does not support live adjustment; queue the input or stop it first')
            item=self.store.submit_task_input(task_id,body,intent,request_id,action=action,expected_run_id=expected_run_id)
            if action=='steer' and item['status']=='pending':
                live.control.submit(item['id'],body)
            if intent!='record': self._notify()
            return item

    def answer_task(self, task_id, question_id, answer):
        with self._lock:
            self._check_enabled()
            task=self.store.get_task(task_id)
            self._agent_command(self.store.get_agent(task['owner_id']))
            result=self.store.answer_task_question(task_id,question_id,answer)
            self._notify()
            return result

    def stop_task(self, task_id, action='pause'):
        with self._lock:
            self._check_enabled()
            result=self.store.task_transition(task_id,action)
            for record in self.store.task_detail(task_id)['runs']:
                if record['status'] in ('queued','running'):
                    self.cancel_run(record['id'])
            return result

    def recover_task(self, task_id, owner_id=None, intent='develop', request_id=None):
        from .store import Conflict
        from .execution_lease import assert_idle
        with self._lock:
            self._check_enabled()
            task=self.store.get_task(task_id)
            previous=self.store.task_recovery(task_id,owner_id,intent,request_id)
            if previous: return previous
            if any(r.record.get('work_task_id')==task_id for r in self._runs.values()):
                raise Conflict('The previous task processes are still stopping')
            detail=self.store.task_detail(task_id)
            # No new model call occurs during preflight. Old remote runs must
            # acknowledge quiescence; network uncertainty never means stopped.
            for session in detail['sessions']:
                if session['environment_id']=='local':
                    assert_idle(self.store.session_directory(session['id']))
                else:
                    runs=[r for r in detail['runs'] if r['session_id']==session['id']]
                    ids=[]
                    for run in runs:
                        attempts=self.store.account_attempts(run['id'])
                        ids.extend(a['id'] for a in attempts if a.get('account_id'))
                        ids.append(run['id'])
                    if ids:
                        value=self.remote.rpc(session['environment_id'],{'op':'recovery_status',
                            'controller':self.store.controller_id,'session_id':session['id'],'run_ids':ids},install=True)
                        if value.get('idle') is not True: raise Conflict('Remote execution is still stopping; retry after it settles')
            self._agent_command(self.store.get_agent(owner_id or task['owner_id']))
            result=self.store.resume_task(task_id,owner_id,intent,request_id)
            self._notify()
            return result

    def _prepare_task_workspace(self, record, session, agent):
        task_id=record.get('work_task_id')
        if not task_id: return session['workspace']
        task=self.store.get_task(task_id)
        if task['workspace_mode']!='worktree': return session['workspace']
        project=self.store.get_project(task['project_id'])
        workspace_agent=task['owner_id'] if record.get('task_role')=='reviewer' else agent['id']
        if agent['environment_id']=='local':
            from .task_workspace import prepare
            value=prepare(self.store.workspaces.parent/'tasks',task_id,workspace_agent,project['path'])
        else:
            value=self.remote.rpc(agent['environment_id'],{'op':'task_workspace','controller':self.store.controller_id,
                'task_id':task_id,'agent_id':workspace_agent,'source':project['path']})
        with self.store.transaction():
            self.store.db.execute('INSERT OR REPLACE INTO task_workspaces VALUES(?,?,?,?,?)',
                (task_id,workspace_agent,agent['environment_id'],value['path'],value['base_commit']))
            self.store.db.execute('UPDATE sessions SET workspace=? WHERE id=?',(value['path'],session['id']))
        return value['path']

    def _task_tool(self, caller, name, arguments):
        from .store import Invalid
        if name=='task_context': return self.store.task_context(caller)
        if name=='task_history': return self.store.task_history(caller,arguments.get('after',0),arguments.get('offset',0))
        if name=='task_result': return self.store.task_result(caller,arguments.get('run_id'),arguments.get('offset',0))
        if name=='task_ask': return self.store.task_question(caller,arguments.get('question'),arguments.get('options'))
        if name=='task_review': return self.store.task_review(caller,arguments.get('verdict'),arguments.get('summary'))
        if name=='task_deliver':
            return self.store.task_delivery(caller,arguments.get('summary'),arguments.get('checks'),arguments.get('artifacts'),arguments.get('risks',''))
        raise Invalid('Unknown task tool')
