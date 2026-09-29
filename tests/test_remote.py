"""Exercise the actual SSH bootstrap/worker with an isolated home and fake CLIs."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from agentdock.remote import BOOTSTRAP, RemoteManager, TransportError
from agentdock.providers import ProviderCancelled, ProviderError
from agentdock.store import Store, Conflict, Invalid
from agentdock.runtime import Runtime
from agentdock.metrics import record, snapshot

FAKE = str(Path(__file__).with_name('fake_native.py').resolve())


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.store = Store(':memory:')
        self.environment = self.store.add_environment('Fixture Devbox', 'fixture-host')
        self.manager = RemoteManager(self.store, True, self.transport)
        self.processes = []
        self.requests = []
        self.scenario = 'progress'
        self.drop_start = self.drop_poll = False
        self.runtime = None
        binaries = self.home / '.local/bin'; binaries.mkdir(parents=True)
        for provider in ('codex', 'claude'):
            script = binaries/provider
            script.write_text('#!' + sys.executable + '\nimport os,sys\n'
                'if "--version" in sys.argv:\n print("fixture 1.0"); sys.exit(0)\n'
                'args=sys.argv[1:]\n'
                'if args[:1]==["app-server"]: args=args[1:]\n'
                f'os.execv({sys.executable!r}, [{sys.executable!r}, {FAKE!r}, {provider!r}, os.environ.get("FIXTURE_SCENARIO","progress")]+args)\n')
            script.chmod(0o700)
        self.manager.connect(self.environment['id'])

    def transport(self, environment, payload, stop=None):
        self.requests.append(payload['request'])
        result = subprocess.run([sys.executable, '-c', BOOTSTRAP], input=json.dumps(payload),
            env={**os.environ, 'HOME': str(self.home), 'PATH':str(self.home/'.local/bin')+os.pathsep+os.environ['PATH'],
                 'FIXTURE_SCENARIO': self.scenario}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.home, text=True, timeout=15, check=True)
        value=json.loads(result.stdout.split('AGENTDOCK_RESPONSE ')[-1])
        operation=payload['request']['op']
        if operation == 'start' and self.drop_start:
            self.drop_start=False
            raise TransportError('Simulated lost acceptance')
        if operation == 'poll' and self.drop_poll:
            self.drop_poll=False
            raise TransportError('Simulated interrupted event read')
        return value

    def tearDown(self):
        if self.runtime: self.runtime.close()
        self.manager.close()
        self.store.close()
        self.tmp.cleanup()

    def make_agent(self, provider='codex'):
        agent=self.store.add_agent(None,'Remote '+provider,provider,environment_id=self.environment['id'])
        session=self.store.add_session(agent['id'],'Remote fixture')
        return agent,session

    def test_directory_picker_reads_remote_home_without_starting_a_cli_task(self):
        (self.home/'remote-project').mkdir()
        self.requests.clear()
        result=self.manager.rpc(self.environment['id'], {'op':'directories','path':'~'})
        self.assertEqual(Path(result['path']), self.home.resolve())
        self.assertIn('remote-project', [entry['name'] for entry in result['directories']])
        self.assertEqual([item['op'] for item in self.requests], ['directories'])

    def run_turn(self, session, **changes):
        events, bound = [], []
        spec={'provider':self.store.get_agent(session['agent_id'])['provider'], 'cwd':session['workspace'], 'session_id':session['id'],
              'prompt':'Protocol fixture only', 'native_session_id':session.get('native_session_id'), 'timeout':8, **changes}
        result=self.manager.run(self.environment['id'],str(uuid.uuid4()),spec,threading.Event(),
            lambda k,p:events.append((k,p)),bound.append,lambda request,options:options[-1]['optionId'],lambda *a:[])
        return result,events,bound

    def test_detached_progress_final_result_and_native_resume_for_both_providers(self):
        for provider in ('codex','claude'):
            agent, session=self.make_agent(provider)
            result,events,bound=self.run_turn(session)
            self.assertEqual(result,'hello world')
            self.assertTrue((self.home/'.local/share/agentdock/ssh/controllers'/self.store.controller_id/'sessions'/session['id']/'workspace').is_dir())
            self.assertFalse(self.store.session_directory(session['id']).exists())
            self.assertFalse((self.store.workspaces/agent['id']).exists())
            self.assertIn('reasoning_chunk',[k for k,p in events])
            self.assertIn('tool_result',[k for k,p in events])
            self.assertEqual(len(bound),1)
            session['native_session_id']=bound[0]
            self.assertEqual(self.run_turn(session)[2],bound)
            if provider == 'codex':
                contract=Path(session['workspace'].replace('~',str(self.home),1))/'fake-contract.jsonl'
                starts=[json.loads(line) for line in contract.read_text().splitlines() if json.loads(line).get('method') in ('thread/start','thread/resume')]
                self.assertTrue(starts)
                self.assertTrue(all(message['params']['cwd'] == str(contract.parent) for message in starts))
        self.assertNotIn('AGENTDOCK_CAPABILITY', json.dumps(self.requests))

    def test_acp_discovery_dialogue_and_resume_use_only_remote_private_state(self):
        fixture = str(Path(__file__).with_name('fake_acp.py').resolve())
        binary = self.home/'.local/bin/gemini'
        binary.write_text('#!' + sys.executable + '\nimport os\n'
                          f'os.execv({sys.executable!r}, [{sys.executable!r}, {fixture!r}, "normal"])\n')
        binary.chmod(0o700)
        info = self.manager.connect(self.environment['id'])
        self.assertTrue(info['payload']['providers']['gemini']['available'])
        models = self.manager.rpc(self.environment['id'], {'op':'models', 'provider':'gemini'})
        self.assertEqual(models['models'][0]['id'], 'fixture-model')
        _, session = self.make_agent('gemini')
        result, events, bound = self.run_turn(session)
        self.assertEqual(result, 'Final answer')
        session['native_session_id'] = bound[0]
        self.assertEqual(self.run_turn(session)[2], bound)
        self.assertFalse(self.store.session_directory(session['id']).exists())
        remote = self.home/'.local/share/agentdock/ssh/controllers'/self.store.controller_id/'sessions'/session['id']
        self.assertTrue((remote/'gemini/private-session.json').is_file())
        self.assertFalse((self.home/'.gemini').exists())
        self.assertIn('reasoning_chunk', [kind for kind, _ in events])

    def test_runtime_forwards_explicit_permissions_and_resets_them_on_resume(self):
        self.runtime = Runtime(self.store, {'execution_enabled':True, 'commands':{},
            'python':sys.executable, 'package_root':str(self.home), 'base_url':'http://127.0.0.1:1', 'run_timeout':8})
        self.runtime.remote = self.manager
        for provider in ('codex', 'claude'):
            agent, session = self.make_agent(provider)
            native_id = None
            for mode, scenario in (('full_access', 'full_access'), ('ask', 'progress')):
                self.scenario = scenario
                self.store.update_agent(agent['id'], {'permission_mode':mode})
                run = self.runtime.start(session['id'], 'Offline permission fixture')
                deadline = time.monotonic() + 8
                while self.store.get_run(run['id'])['status'] in ('queued', 'running') and time.monotonic() < deadline:
                    time.sleep(.03)
                self.assertEqual(self.store.get_run(run['id'])['status'], 'completed')
                requests = [r for r in self.requests if r['op'] == 'start' and r['run_id'] == run['id']]
                self.assertEqual(requests[0]['spec']['permission_mode'], mode)
                bound = self.store.get_session(session['id'])['native_session_id']
                if native_id: self.assertEqual(bound, native_id)
                native_id = bound
            if provider == 'codex':
                contract = Path(session['workspace'].replace('~', str(self.home), 1))/'fake-contract.jsonl'
                starts = [json.loads(line) for line in contract.read_text().splitlines() if json.loads(line).get('method') in ('thread/start', 'thread/resume')]
                self.assertEqual(len(starts), 2)
                self.assertTrue(all(m['params']['cwd'] == str(contract.parent) for m in starts))

    def test_wrong_remote_directory_rejected_before_user_prompt(self):
        self.scenario='wrong_cwd'
        _, session=self.make_agent()
        with self.assertRaisesRegex(ProviderError, 'different working directory'):
            self.run_turn(session)
        contract=Path(session['workspace'].replace('~',str(self.home),1))/'fake-contract.jsonl'
        self.assertFalse(any(json.loads(line).get('method')=='turn/start' for line in contract.read_text().splitlines()))

    def test_start_and_poll_retries_do_not_execute_a_turn_twice(self):
        _,session=self.make_agent()
        self.drop_start=self.drop_poll=True
        result, events, _ = self.run_turn(session)
        self.assertEqual(result,'hello world')
        self.assertEqual(sum(k=='reasoning_chunk' for k,p in events),2)
        contract=Path(session['workspace'].replace('~',str(self.home),1))/'fake-contract.jsonl'
        self.assertEqual(sum(json.loads(line).get('method')=='turn/start' for line in contract.read_text().splitlines()),1)
        self.assertIn(('transport_status',{'status':'reconnecting'}), events)
        self.assertIn(('transport_status',{'status':'connected'}), events)

    def test_permission_response_returns_to_the_correct_native_cli(self):
        self.scenario='permission'
        for provider in ('codex','claude'):
            _,session=self.make_agent(provider)
            self.assertEqual(self.run_turn(session)[0], 'hello world')
        responses=[r for r in self.requests if r['op']=='respond']
        self.assertIn('decline',[r['response'].get('value') for r in responses])
        self.assertIn('deny',[r['response'].get('value') for r in responses])

    def test_remote_shared_memory_bridge_returns_results_without_exporting_local_credentials(self):
        self.scenario='mcp'
        _,session=self.make_agent()
        calls=[]
        def tool(name,args):
            calls.append((name,args)); return [{'key':'fixture','content':'Reviewed shared memory'}]
        result=self.manager.run(self.environment['id'],str(uuid.uuid4()),
            {'provider':'codex','cwd':session['workspace'],'session_id':session['id'],'prompt':'fixture','timeout':8},threading.Event(),
            lambda *a:None,lambda *a:None,lambda *a:None,tool)
        self.assertEqual(result,'hello world')
        self.assertEqual(calls,[('memory_search',{'query':'fixture'})])
        response=Path(session['workspace'].replace('~',str(self.home),1))/'fake-tool-result.json'
        self.assertEqual(json.loads(response.read_text())[0]['content'],'Reviewed shared memory')

    def test_cancel_stops_remote_child_process(self):
        self.scenario='hang'
        _,session=self.make_agent()
        stop=threading.Event(); errors=[]
        def run():
            try: self.manager.run(self.environment['id'],str(uuid.uuid4()), {'provider':'codex','cwd':session['workspace'],'session_id':session['id'],'prompt':'fixture','timeout':8}, stop, lambda *a:None, lambda *a:None, lambda *a:None, lambda *a:None)
            except Exception as error: errors.append(error)
        thread=threading.Thread(target=run); thread.start()
        pidfile=Path(session['workspace'].replace('~',str(self.home),1))/'fake-pid'
        deadline=time.monotonic()+5
        while not pidfile.exists() and time.monotonic()<deadline: time.sleep(.02)
        self.assertTrue(pidfile.exists())
        pid=int(pidfile.read_text()); stop.set(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertIsInstance(errors[0],ProviderCancelled)
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            try: os.kill(pid,0)
            except ProcessLookupError: break
            time.sleep(.05)
        else: self.fail('Remote child survived cancellation')

    def test_expired_lease_stops_abandoned_process(self):
        self.scenario='hang'
        _,session=self.make_agent(); run_id=str(uuid.uuid4())
        identity={'controller':self.store.controller_id,'run_id':run_id}
        self.manager.rpc(self.environment['id'], {**identity,'op':'start','spec':{'provider':'codex','cwd':session['workspace'],'session_id':session['id'],'prompt':'fixture','timeout':15}})
        path=self.home/'.local/share/agentdock/ssh/controllers'/identity['controller']/run_id
        deadline=time.monotonic()+5
        pidfile=Path(session['workspace'].replace('~',str(self.home),1))/'fake-pid'
        while not pidfile.exists() and time.monotonic()<deadline: time.sleep(.02)
        self.assertTrue(pidfile.exists())
        os.utime(path/'lease',(time.time()-100,time.time()-100))
        while time.monotonic()<deadline:
            if json.loads((path/'state.json').read_text())['status']=='cancelled': break
            time.sleep(.05)
        else: self.fail('Expired lease did not cancel the task')

    def test_runtime_persists_only_final_reply_after_remote_completion(self):
        agent, session=self.make_agent()
        self.runtime=Runtime(self.store,{'execution_enabled':True,'commands':{},'python':sys.executable,'package_root':str(self.home),'base_url':'http://127.0.0.1:1','run_timeout':8})
        self.runtime.remote=self.manager
        run=self.runtime.start(session['id'],'Remote fixture')
        deadline=time.monotonic()+8
        while self.store.get_run(run['id'])['status'] in ('queued','running') and time.monotonic()<deadline: time.sleep(.03)
        run=self.store.get_run(run['id'])
        self.assertEqual(run['status'],'completed',run)
        self.assertEqual(run['result'],'hello world')
        self.assertEqual([e['kind'] for e in self.store.session_events(session['id'])][-2:],['assistant_message','run_finished'])

    def test_deleting_a_session_cleans_its_remote_workspace_and_run_files_only(self):
        agent, first=self.make_agent()
        second=self.store.add_session(agent['id'],'Keep this session')
        self.runtime=Runtime(self.store,{'execution_enabled':True,'commands':{},'python':sys.executable,'package_root':str(self.home),'base_url':'http://127.0.0.1:1','run_timeout':8})
        self.runtime.remote=self.manager
        run=self.runtime.start(first['id'],'Fixture')
        deadline=time.monotonic()+8
        while self.store.get_run(run['id'])['status'] in ('queued','running') and time.monotonic()<deadline: time.sleep(.03)
        self.assertEqual(self.store.get_run(run['id'])['status'],'completed')
        controller=self.home/'.local/share/agentdock/ssh/controllers'/self.store.controller_id
        self.assertTrue((controller/'sessions'/first['id']).is_dir())
        self.assertTrue((controller/run['id']).is_dir())
        self.runtime.delete_session(first['id'])
        self.assertFalse((controller/'sessions'/first['id']).exists())
        self.assertFalse((controller/run['id']).exists())
        self.assertEqual(self.store.get_session(second['id'])['title'],'Keep this session')


class EnvironmentTests(unittest.TestCase):
    def setUp(self): self.store=Store(':memory:')
    def tearDown(self): self.store.close()

    def test_namespaces_isolate_colliding_native_ids_quotas_and_workspaces(self):
        remote=self.store.add_environment('Remote','user@devbox')
        a=self.store.add_agent(None,'Local','codex',workspace='/tmp')
        b=self.store.add_agent(None,'Remote','codex',workspace='/tmp',environment_id=remote['id'])
        sessions=[self.store.add_session(agent['id'],'Session') for agent in (a,b)]
        for session in sessions: self.store.bind_native_session(session['id'],'same-native-id')
        for index,session in enumerate(sessions):
            usage={'input_tokens':10+index,'output_tokens':5,'cache_read_tokens':0,'cache_write_tokens':0,'total_tokens':15+index}
            record(self.store,'codex',self.store.metric_identity(session['environment_id'],'same-native-id'),'total',usage,time.time(),'managed')
        metrics=snapshot(self.store)
        self.assertEqual(metrics['agents'][a['id']]['total_tokens'],15)
        self.assertEqual(metrics['agents'][b['id']]['total_tokens'],16)
        self.assertEqual(len(self.store.usage_bindings(local_only=True)),1)
        self.store.set_quota('codex',{'provider':'codex','plan':'local'})
        self.store.set_quota('codex',{'provider':'codex','plan':'remote'},remote['id'])
        self.assertEqual(self.store.get_quota('codex')['plan'],'local')
        self.assertEqual(self.store.get_quota('codex',remote['id'])['plan'],'remote')
        for session in sessions: self.store.enqueue_run(session['id'],'Hello')
        self.assertIsNotNone(self.store.claim_next_run()); self.assertIsNotNone(self.store.claim_next_run())
        with self.assertRaises(Conflict): self.store.remove_environment(remote['id'])
        self.store.update_agent(b['id'],{'environment_id':'local'})
        self.assertEqual(self.store.get_session(sessions[1]['id'])['environment_id'], remote['id'])
        with self.assertRaises(Conflict): self.store.remove_environment(remote['id'])

    def test_reject_shell_ssh_option_and_path_injection(self):
        for host in ('-oProxyCommand=evil','host;echo secret','host\nother','$(whoami)'):
            with self.assertRaises(Invalid): self.store.add_environment('Bad',host)
        env=self.store.add_environment('Remote','devbox')
        with self.assertRaises(Invalid): self.store.add_agent(None,'Bad','claude',workspace='relative/path',environment_id=env['id'])


if __name__=='__main__': unittest.main()
