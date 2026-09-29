import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from agentdock.runtime import Runtime
from agentdock.store import Store, Conflict, Invalid, Missing


class AgentRelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'agentdock.sqlite3'
        self.store = Store(self.path)
        self.remote = self.store.add_environment('Fixture', 'fixture-host')['id']

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_move_preserves_old_session_defaults_history_and_queued_runs(self):
        agent = self.store.add_agent(None, 'Helper', 'codex', model='local-model', effort='high', permission_mode='full_access')
        old = self.store.add_session(agent['id'], 'Original')
        override = self.store.add_session(agent['id'], 'Custom')
        self.store.update_session_settings(override['id'], {'model': 'custom-model', 'effort': 'low'})
        self.store.bind_native_session(old['id'], 'native-original')
        running = self.store.begin_run(old['id'], 'Running')
        queued = self.store.enqueue_run(old['id'], 'Queued')
        before = self.store.get_session(old['id'])
        events = self.store.session_events(old['id'])
        moved = self.store.update_agent(agent['id'], {'environment_id': self.remote, 'model': 'remote-model', 'effort': 'max', 'permission_mode': 'ask'})
        self.assertEqual(moved['id'], agent['id'])
        self.assertTrue(moved['workspace'].startswith('~/.local/share/agentdock/'))
        after = self.store.get_session(old['id'])
        self.assertEqual({k: v for k, v in after.items() if k != 'agent_defaults'}, {k: v for k, v in before.items() if k != 'agent_defaults'})
        self.assertEqual(after['agent_defaults'], {'model': 'local-model', 'effort': 'high', 'permission_mode': 'full_access'})
        self.assertEqual(events, self.store.session_events(old['id']))
        self.assertEqual(self.store.get_run(running['id']), running)
        self.assertEqual(self.store.get_run(queued['id']), queued)
        new = self.store.add_session(agent['id'], 'Remote')
        next_run = self.store.enqueue_run(new['id'], 'New location')
        self.assertEqual(new['environment_id'], self.remote)
        self.assertEqual((next_run['model'], next_run['effort'], next_run['permission_mode']), ('remote-model', 'max', 'ask'))
        self.assertIsNone(self.store.claim_next_run())  # Same agent stays serialized across hosts.
        continued = self.store.enqueue_run(old['id'], 'Continue original')
        self.assertEqual((continued['model'], continued['effort'], continued['permission_mode']), ('local-model', 'high', 'full_access'))
        self.assertEqual(self.store.enqueue_run(override['id'], 'Custom')['model'], 'custom-model')
        self.store.update_session_settings(override['id'], {'inherit': True})
        self.assertEqual(self.store.enqueue_run(override['id'], 'Reset')['model'], 'local-model')
        # Moving back must not thaw either generation of existing conversations.
        self.store.update_agent(agent['id'], {'environment_id': 'local', 'model': 'third-model'})
        self.assertEqual(self.store.session_agent(old['id'])['model'], 'local-model')
        self.assertEqual(self.store.session_agent(new['id'])['model'], 'remote-model')
        with self.assertRaises(Conflict): self.store.remove_environment(self.remote)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.session_agent(old['id'])['environment_id'], 'local')
        self.assertEqual(self.store.session_agent(new['id'])['environment_id'], self.remote)
        self.assertEqual(self.store.session_agent(new['id'])['model'], 'remote-model')

    def test_defaults_reset_on_new_host_and_invalid_edits_are_atomic(self):
        agent = self.store.add_agent(None, 'A', 'claude', model='only-local', effort='high')
        session = self.store.add_session(agent['id'], 'Original')
        before = self.store.get_session(session['id'])
        for changes, error in (({'environment_id': 'missing'}, Missing),
                               ({'environment_id': []}, Invalid),
                               ({'environment_id': None}, Invalid),
                               ({'environment_id': self.remote, 'workspace': 'relative'}, Invalid),
                               ({'environment_id': self.remote, 'name': ''}, Invalid),
                               ({'environment_id': self.remote, 'provider': 'codex'}, Invalid)):
            with self.assertRaises(error): self.store.update_agent(agent['id'], changes)
            self.assertEqual(self.store.get_agent(agent['id']), agent)
            self.assertEqual(self.store.get_session(session['id']), before)
        changed = self.store.update_agent(agent['id'], {'environment_id': self.remote})
        self.assertIsNone(changed['model'])
        self.assertIsNone(changed['effort'])
        self.assertEqual(self.store.session_agent(session['id'])['model'], 'only-local')

    def test_workers_resume_original_host_and_new_sessions_use_new_host(self):
        for provider in ('codex', 'claude'):
            for source, target in (('local', self.remote), (self.remote, 'local')):
                with self.subTest(provider=provider, source=source):
                    agent = self.store.add_agent(None, 'A', provider, environment_id=source, model='original-model')
                    old = self.store.add_session(agent['id'], 'Original')
                    self.store.bind_native_session(old['id'], 'native-' + old['id'])
                    entered = threading.Event()
                    release = threading.Event()
                    received = []
                    def execute(*args, **kwargs):
                        received.append(('local', args[2], args[4], kwargs.get('model'), kwargs['permission_mode']))
                        entered.set(); release.wait(4)
                        return 'Local result'
                    def remote_execute(environment, run_id, spec, *args):
                        received.append((environment, spec['cwd'], spec['native_session_id'], spec['model'], spec['permission_mode']))
                        entered.set(); release.wait(4)
                        return 'Remote result'
                    runtime = Runtime(self.store, {'execution_enabled': True, 'commands': {provider: ['fixture']}, 'python': 'python3', 'package_root': self.temp.name, 'base_url': 'http://127.0.0.1:1'}, executor=execute)
                    runtime.remote.check = Mock()
                    runtime.remote.run = remote_execute
                    try:
                        first = runtime.start(old['id'], 'First')
                        self.assertTrue(entered.wait(3))
                        queued = runtime.start(old['id'], 'Already queued')
                        self.store.update_agent(agent['id'], {'environment_id': target, 'model': 'target-model', 'permission_mode': 'full_access'})
                        resumed = runtime.start(old['id'], 'Original history')
                        new = self.store.add_session(agent['id'], 'New')
                        latest = runtime.start(new['id'], 'New history')
                        release.set()
                        deadline = time.monotonic() + 5
                        while self.store.get_run(latest['id'])['status'] in ('queued', 'running') and time.monotonic() < deadline:
                            time.sleep(.01)
                        for run in (first, queued, resumed, latest):
                            self.assertEqual(self.store.get_run(run['id'])['status'], 'completed')
                        self.assertEqual([item[0] for item in received], [source, source, source, target])
                        for item in received[:3]:
                            self.assertEqual(item[1:], (old['workspace'], 'native-' + old['id'], 'original-model', 'ask'))
                        self.assertEqual(received[3][1:], (new['workspace'], None, 'target-model', 'full_access'))
                        self.assertEqual(self.store.get_session(old['id'])['native_session_id'], 'native-' + old['id'])
                    finally:
                        release.set(); runtime.close()

    def test_dispatch_uses_new_location_unless_old_conversation_is_explicit(self):
        project = self.store.add_project('Project', self.temp.name)
        agent = self.store.add_agent(project['id'], 'Recipient', 'claude')
        old = self.store.add_session(agent['id'], 'Old')
        self.store.update_agent(agent['id'], {'environment_id': self.remote})
        runtime = Runtime(self.store, {'execution_enabled': True, 'commands': {'claude': ['fixture']}})
        runtime._notify = Mock()
        runtime.remote.check = Mock()
        try:
            implicit = runtime.send_message(project['id'], agent['id'], 'Current location')
            self.assertEqual(self.store.get_session(implicit['recipient_session_id'])['environment_id'], self.remote)
            self.assertNotEqual(implicit['recipient_session_id'], old['id'])
            runtime.remote.check.reset_mock()
            explicit = runtime.send_message(project['id'], agent['id'], 'Old location', recipient_session_id=old['id'])
            self.assertEqual(explicit['recipient_session_id'], old['id'])
            runtime.remote.check.assert_not_called()
            same = runtime.send_message(project['id'], agent['id'], 'Resume current')
            self.assertEqual(same['recipient_session_id'], implicit['recipient_session_id'])
        finally: runtime.close()

    def test_delete_agent_cleans_both_locations_without_deleting_shared_directory(self):
        shared = Path(self.temp.name) / 'project'
        shared.mkdir()
        (shared / 'source.txt').write_text('keep')
        agent = self.store.add_agent(None, 'A', 'claude', workspace=str(shared))
        old = self.store.add_session(agent['id'], 'Local')
        directory = self.store.session_directory(old['id'])
        directory.mkdir(parents=True)
        (directory / 'private-history').write_text('history')
        self.store.update_agent(agent['id'], {'environment_id': self.remote})
        remote = self.store.add_session(agent['id'], 'Remote')
        run = self.store.begin_run(remote['id'], 'Previous remote turn')
        self.store.finish_run(run['id'], 'completed')
        self.store.update_agent(agent['id'], {'environment_id': 'local'})
        with self.assertRaises(Conflict): self.store.remove_environment(self.remote)
        runtime = Runtime(self.store, {'execution_enabled': True})
        runtime.remote.rpc = Mock(return_value={'ok': True})
        try:
            runtime.delete_agent(agent['id'])
            request = runtime.remote.rpc.call_args
            self.assertEqual(request.args[0], self.remote)
            self.assertEqual(request.args[1]['session_id'], remote['id'])
            self.assertFalse(directory.exists())
            self.assertEqual((shared / 'source.txt').read_text(), 'keep')
            self.store.remove_environment(self.remote)
            with self.assertRaises(Missing): self.store.get_agent(agent['id'])
        finally: runtime.close()
