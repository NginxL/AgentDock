"""Real framed pipes, detached fake native workers, and durable replay; no network/model."""
import json
import os
import shutil
from pathlib import Path
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from agentdock.remote import BOOTSTRAP, RemoteManager
from agentdock.ssh_transport import Channel
from agentdock.providers import ProviderCancelled
from agentdock.ssh_bridge import EventReader
import test_remote as fixtures


class StreamTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RemoteTests()
        self.fixture.setUp()
        self.fixture.manager.close()
        self.channels = []
        def factory(argv, payload):
            f = self.fixture
            channel = Channel([sys.executable, '-u', '-c', BOOTSTRAP], payload,
                env={**os.environ, 'HOME': str(f.home), 'PATH': str(f.home/'.local/bin') + os.pathsep + os.environ['PATH'],
                     'FIXTURE_SCENARIO': f.scenario}, cwd=f.home)
            self.channels.append(channel)
            return channel
        self.fixture.manager = RemoteManager(self.fixture.store, True, channel_factory=factory)
        self.manager = self.fixture.manager
        self.environment = self.fixture.environment['id']

    def tearDown(self):
        self.fixture.tearDown()
        for channel in self.channels:
            self.assertFalse(channel.thread.is_alive())
            self.assertIsNotNone(channel.process.poll())

    def connect(self, scenario='progress'):
        self.fixture.scenario = scenario
        self.manager.connect(self.environment)

    def test_concurrent_turns_and_directory_reads_share_one_channel(self):
        self.connect()
        sessions = [self.fixture.make_agent(p)[1] for p in ('codex', 'claude')]
        with ThreadPoolExecutor(max_workers=3) as pool:
            turns = [pool.submit(self.fixture.run_turn, s) for s in sessions]
            directory = pool.submit(self.manager.rpc, self.environment, {'op':'directories', 'path':'~'})
            self.assertEqual(directory.result(timeout=5)['path'], str(self.fixture.home.resolve()))
            self.assertEqual([turn.result(timeout=8)[0] for turn in turns], ['hello world', 'hello world'])
        self.assertEqual(len(self.channels), 1)

    def test_cleanup_after_upgrade_bootstraps_a_fresh_channel(self):
        # Mirror an app restart: no live channel and only an older remote bundle.
        shutil.rmtree(self.fixture.home/'.local/share/agentdock/ssh/runtimes'/self.manager.digest)
        controller=self.fixture.store.controller_id
        session=str(uuid.uuid4())
        path=self.fixture.home/'.local/share/agentdock/ssh/controllers'/controller/'sessions'/session
        path.mkdir(parents=True)
        (path/'history').write_text('owned fixture')
        self.assertEqual(self.manager.rpc(self.environment, {'op':'delete_session',
            'controller':controller, 'session_id':session, 'run_ids':[]}, install=True), {'ok':True})
        self.assertFalse(path.exists())
        self.assertEqual(len(self.channels), 1)

    def test_disconnect_replays_events_without_restarting_native_turn(self):
        self.connect()
        _, session = self.fixture.make_agent()
        events, dropped = [], False
        def emit(kind, payload):
            nonlocal dropped
            events.append((kind, payload))
            if kind == 'reasoning_chunk' and not dropped:
                dropped = True
                self.channels[0].close()
        result = self.manager.run(self.environment, str(uuid.uuid4()),
            {'provider':'codex', 'cwd':session['workspace'], 'session_id':session['id'], 'prompt':'fixture', 'timeout':12},
            threading.Event(), emit, lambda *a:None, lambda *a:None, lambda *a:None)
        self.assertEqual(result, 'hello world')
        self.assertTrue(dropped)
        self.assertEqual(sum(kind == 'reasoning_chunk' for kind, _ in events), 2)
        contract = Path(session['workspace'].replace('~', str(self.fixture.home), 1))/'fake-contract.jsonl'
        self.assertEqual(sum(json.loads(line).get('method') == 'turn/start' for line in contract.read_text().splitlines()), 1)
        self.assertIn(('transport_status', {'status':'connected'}), events)
        self.assertEqual(self.fixture.store.get_environment(self.environment)['status'], 'connected')

    def test_permissions_can_return_while_other_requests_are_active(self):
        self.connect('permission')
        sessions = [self.fixture.make_agent(p)[1] for p in ('codex', 'claude')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.fixture.run_turn, sessions))
        self.assertEqual([result[0] for result in results], ['hello world', 'hello world'])
        self.assertEqual(len(self.channels), 1)

    def test_cancel_is_not_blocked_by_slow_models_and_does_not_close_other_subscription(self):
        self.connect('hang')
        identities = []
        for _ in range(2):
            _, session = self.fixture.make_agent()
            identity = {'controller':self.fixture.store.controller_id, 'run_id':str(uuid.uuid4())}
            self.manager.rpc(self.environment, {**identity, 'op':'start', 'spec':{
                'provider':'codex','cwd':session['workspace'],'session_id':session['id'],'prompt':'fixture','timeout':8}})
            identities.append(identity)
        watch = self.manager._watch(self.environment, {**identities[1], 'after':0}, threading.Event())
        with ThreadPoolExecutor(max_workers=1) as pool:
            cancelled = threading.Event()
            model = pool.submit(self.manager.rpc, self.environment, {'op':'models','provider':'codex'}, stop=cancelled)
            try:
                time.sleep(.1)
                start = time.monotonic()
                self.manager.rpc(self.environment, {**identities[0], 'op':'cancel'})
                self.assertLess(time.monotonic() - start, .8)
                self.assertFalse(self.channels[0].closed.is_set())
                value = watch.next(timeout=1)
                self.assertIn(value['state']['status'], ('starting','running'))
            finally:
                cancelled.set()
                with self.assertRaises(ProviderCancelled): model.result(timeout=2)
                watch.close()
                for identity in identities: self.manager.rpc(self.environment, {**identity, 'op':'cancel'})
                time.sleep(.8)
        pid = int((self.fixture.home/'fake-pid').read_text())
        self.manager.close()
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_incremental_reader_waits_for_complete_records_and_honors_resume_cursor(self):
        path = self.fixture.home/'records'; path.mkdir()
        (path/'state.json').write_text(json.dumps({'status':'running', 'updated_at':time.time()}))
        log = path/'events.jsonl'
        log.write_text('{"seq":1}\n{"seq":2')
        reader = EventReader(path, 1)
        self.assertEqual(reader.poll()['events'], [])
        self.assertEqual(reader.offset, len(b'{"seq":1}\n'))
        with log.open('a') as out: out.write('}\n{"seq":3}\n')
        self.assertEqual([e['seq'] for e in reader.poll()['events']], [2,3])
        self.assertEqual(reader.poll()['events'], [])


if __name__ == '__main__': unittest.main()
