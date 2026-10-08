"""Task controls use isolated fake native calls, never a model or production host."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from agentdock.runtime import Runtime
from agentdock.providers import ProviderCancelled
from agentdock.store import Store, Conflict
from agentdock.execution_lease import lease


class TaskRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state.db')
        self.project=self.store.add_project('P',str(self.root))
        self.agent=self.store.add_agent(self.project['id'],'Owner','codex')
        self.task=self.store.create_task(self.project['id'],'T','Goal','Check',self.agent['id'])
        self.calls=[]; self.gate=threading.Event(); self.started=threading.Event()
        self.runtime=Runtime(self.store,dict(execution_enabled=True,commands={'codex':['fixture']},python=sys.executable,
            package_root=str(self.root),base_url='http://127.0.0.1:47831',run_timeout=5),executor=self.execute)

    def tearDown(self):
        self.gate.set(); self.runtime.close(); self.store.close(); self.tmp.cleanup()

    def wait(self,predicate):
        end=time.monotonic()+4
        while time.monotonic()<end:
            if predicate(): return
            time.sleep(.01)
        self.fail('Task runtime did not settle: '+str(self.store.state()['runs']))

    def execute(self,provider,command,cwd,prompt,native_id,mcp,stop,emit,bind,approve,**settings):
        run=self.store.capability_run(mcp['env']['AGENTDOCK_CAPABILITY'])
        self.calls.append((run,settings)); self.started.set()
        bind('native-'+run['session_id'])
        control=settings['control']; emit('input_control',{'turn_id':'fixture-turn'})
        if run['prompt']=='blocked':
            while not self.gate.wait(.01):
                if stop.is_set(): raise ProviderCancelled()
                for item in control.take(): emit('input_receipt',{'input_id':item['id'],'status':'accepted'})
        return 'Finished fixture turn'

    def test_notes_queue_steer_and_pause_have_distinct_effects(self):
        item=self.runtime.submit_task(self.task['id'],'blocked','develop','first')
        self.wait(lambda:self.runtime._runs.get(item['run_id']) and self.runtime._runs[item['run_id']].control.available)
        self.runtime.submit_task(self.task['id'],'Only a note','record','note')
        steer=self.runtime.submit_task(self.task['id'],'Use JSON','develop','live','steer',item['run_id'])
        self.wait(lambda:self.store.task_detail(self.task['id'])['inputs'][-1]['status']=='accepted')
        self.runtime.submit_task(self.task['id'],'Next turn','develop','later')
        self.assertEqual(len(self.calls),1)
        self.runtime.stop_task(self.task['id'])
        self.wait(lambda:not self.runtime._runs)
        self.assertFalse(self.store.pending_runs())
        self.assertEqual(self.store.get_task(self.task['id'])['status'],'paused')
        self.assertFalse(any(i['status'] in ('queued','pending') for i in self.store.task_detail(self.task['id'])['inputs']))

    def test_recovery_checks_owned_native_lease_before_starting_new_history(self):
        item=self.runtime.submit_task(self.task['id'],'blocked','develop','first')
        self.wait(lambda:bool(self.calls))
        self.runtime.stop_task(self.task['id']); self.wait(lambda:not self.runtime._runs)
        old=self.store.get_run(item['run_id'])['session_id']
        with lease(self.store.session_directory(old)):
            with self.assertRaises(Conflict): self.runtime.recover_task(self.task['id'])
        self.runtime.recover_task(self.task['id'])
        self.wait(lambda:len(self.calls)==2 and not self.runtime._runs)
        self.assertNotEqual(old,self.calls[-1][0]['session_id'])
        self.assertEqual(self.store.get_task(self.task['id'])['status'],'review')

    def test_discussion_uses_read_only_and_cannot_approve_writes(self):
        item=self.runtime.submit_task(self.task['id'],'blocked','discuss','first')
        self.wait(lambda:bool(self.calls))
        self.assertEqual(self.calls[0][1]['permission_mode'],'read_only')
        active=self.runtime._runs[item['run_id']]
        choices=[dict(optionId='yes',kind='allow_once'),dict(optionId='no',kind='reject_once')]
        self.assertEqual(self.runtime._request_approval(active,{'tool_name':'Write'},choices),'no')
        self.assertEqual(self.runtime._request_approval(active,{'tool_name':'mcp__agentdock__task_ask'},choices),'yes')
        self.gate.set(); self.wait(lambda:not self.runtime._runs)
        self.assertEqual(self.store.get_task(self.task['id'])['status'],'draft')

    def test_preparation_failure_does_not_leave_task_active(self):
        with self.runtime._lock:
            self.store.submit_task_input(self.task['id'],'go','develop','first')
            self.runtime._agent_command=Mock(side_effect=ValueError('missing CLI'))
            self.runtime._notify()
        self.wait(lambda:self.store.get_task(self.task['id'])['status']=='interrupted')
        self.assertEqual(len(self.calls),0)

    def test_remote_uncertainty_blocks_recovery(self):
        env=self.store.add_environment('Remote','fixture-host')
        project=self.store.add_project('R','/fixture/project',env['id'])
        agent=self.store.add_agent(project['id'],'Remote','codex',environment_id=env['id'])
        task=self.store.create_task(project['id'],'T','Goal','Check',agent['id'])
        with self.runtime._lock:
            item=self.store.submit_task_input(task['id'],'go','develop','first')
            self.store.cancel_queued_run(item['run_id'])
            self.store.task_transition(task['id'],'pause')
        with patch.object(self.runtime.remote,'rpc',return_value={'idle':False}) as rpc:
            with self.assertRaisesRegex(Conflict,'Remote execution'): self.runtime.recover_task(task['id'])
            self.assertEqual(rpc.call_args.args[1]['op'],'recovery_status')
        self.assertEqual(self.store.get_task(task['id'])['status'],'paused')
