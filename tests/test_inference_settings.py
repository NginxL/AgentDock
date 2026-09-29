import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from agentdock.store import Store, Invalid
from agentdock.runtime import Runtime


class InferenceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'agentdock.sqlite3'
        self.store = Store(self.path)
        self.agent = self.store.add_agent(None, 'Agent', 'codex', model='model-a', effort='high')
        self.session = self.store.add_session(self.agent['id'], 'First')
        self.other = self.store.add_session(self.agent['id'], 'Second')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_conversation_override_persists_and_queued_runs_keep_their_choices(self):
        first = self.store.enqueue_run(self.session['id'], 'Before change')
        self.store.update_session_settings(self.session['id'], {'model':'model-b','effort':'low'})
        second = self.store.enqueue_run(self.session['id'], 'After change')
        sibling = self.store.enqueue_run(self.other['id'], 'Other session')
        self.assertEqual((first['model'], first['effort']), ('model-a','high'))
        self.assertEqual((second['model'], second['effort']), ('model-b','low'))
        self.assertEqual((sibling['model'], sibling['effort']), ('model-a','high'))
        self.assertEqual(self.store.get_agent(self.agent['id'])['model'], 'model-a')
        self.store.close(); self.store = Store(self.path)
        self.assertEqual(self.store.get_session(self.session['id'])['model'], 'model-b')
        self.store.update_session_settings(self.session['id'], {'inherit':True})
        again = self.store.enqueue_run(self.session['id'], 'Agent defaults')
        self.assertEqual((again['model'],again['effort']), ('model-a','high'))
        self.store.update_session_settings(self.session['id'], {'model':None,'effort':None})
        native = self.store.enqueue_run(self.session['id'], 'Client defaults')
        self.assertEqual((native['model'],native['effort']), (None,None))

    def test_invalid_settings_do_not_change_native_binding_or_ownership(self):
        native='managed-native-id'
        self.store.bind_native_session(self.session['id'],native)
        for change in ({}, {'model':'--bad','effort':None}, {'model':'a','effort':'unknown'},
                       {'inherit':1}, {'inherit':True,'model':'a'}, {'workspace':'/tmp'}, {'native_session_id':'other'}):
            with self.assertRaises(Invalid): self.store.update_session_settings(self.session['id'],change)
        self.assertEqual(self.store.get_session(self.session['id'])['native_session_id'],native)

    def test_local_and_remote_workers_use_submission_settings(self):
        for provider in ('codex','claude'):
            for remote in (False,True):
                with self.subTest(provider=provider,remote=remote):
                    env=self.store.add_environment('Fixture','test-host')['id'] if remote else 'local'
                    if remote: self.store.update_environment_status(env,'connected')
                    agent=self.store.add_agent(None,'A',provider,model='agent-model',effort='high',environment_id=env)
                    session=self.store.add_session(agent['id'],'S')
                    self.store.update_session_settings(session['id'],{'model':'session-model','effort':'low'})
                    entered=threading.Event(); release=threading.Event(); received=[]
                    def execute(*args,**kwargs):
                        received.append(kwargs); entered.set(); release.wait(3); return 'Done'
                    runtime=Runtime(self.store,{'execution_enabled':True,'commands':{provider:['fixture']},'python':'python3','package_root':self.temp.name,'base_url':'http://127.0.0.1:1'},executor=execute)
                    if remote:
                        runtime.remote.check=Mock()
                        def run_remote(environment,run_id,spec,*args):
                            received.append(spec); entered.set(); release.wait(3); return 'Done'
                        runtime.remote.run=run_remote
                    try:
                        run=runtime.start(session['id'],'Fixture only')
                        self.assertTrue(entered.wait(3))
                        self.store.update_session_settings(session['id'],{'model':'next-model','effort':'max'})
                        release.set()
                        deadline=time.monotonic()+3
                        while self.store.get_run(run['id'])['status'] in ('queued','running') and time.monotonic()<deadline:time.sleep(.01)
                        self.assertEqual(self.store.get_run(run['id'])['status'],'completed')
                        self.assertEqual((received[0]['model'],received[0]['effort']),('session-model','low'))
                    finally: release.set();runtime.close()
