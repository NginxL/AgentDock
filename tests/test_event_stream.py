import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

from agentdock.server import API, handler_for
from agentdock.store import Store


class EventStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(':memory:')
        agent = self.store.add_agent(None, 'Fixture', 'codex')
        self.session = self.store.add_session(agent['id'], 'Fixture')['id']
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *a:None)
        self.api = API(self.store, Mock(), Mock(), 'fixture', self.server.server_port)
        self.server.RequestHandlerClass = handler_for(self.api, self.tmp.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.connections = []

    def tearDown(self):
        for connection in self.connections: connection.close()
        self.api.close(); self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.store.close(); self.tmp.cleanup()

    def stream(self, after=0, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        self.connections.append(connection)
        connection.request('GET', f'/api/sessions/{self.session}/events/stream?after={after}',
                           headers={'Authorization':'Bearer fixture', **headers})
        return connection.getresponse()

    def event(self, response):
        while True:
            line = response.fp.readline()
            if not line: self.fail('Stream ended before event')
            if line.startswith(b'data: '): return json.loads(line[6:])['events']

    def test_live_events_replay_and_resume_without_duplicates(self):
        first = self.store.append_event(None, self.session, 'user_message', {'text':'你好'})
        response = self.stream()
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader('Content-Type').startswith('text/event-stream'))
        self.assertEqual(self.event(response)[0]['id'], first['id'])
        before = time.monotonic()
        second = self.store.append_event(None, self.session, 'agent_message_chunk', {'text':'Hello'})
        self.assertEqual(self.event(response)[0]['id'], second['id'])
        self.assertLess(time.monotonic() - before, .5)
        resumed = self.stream(first['seq'])
        self.assertEqual([e['id'] for e in self.event(resumed)], [second['id']])

    def test_stream_requires_same_token_origin_and_host_as_history(self):
        for headers, status in [({'Authorization':'Bearer bad'}, 401), ({'Origin':'https://evil.example'}, 403),
                                ({'Host':'evil.example'},403), ({'Sec-Fetch-Site':'cross-site'},403)]:
            response = self.stream(**headers)
            self.assertEqual(response.status, status)
            response.read()
        self.assertEqual(self.stream(-1).status, 200)

    def test_commit_notification_does_not_lose_race_or_publish_rollback(self):
        stop = threading.Event()
        first = self.store.append_event(None, self.session, 'tool_result', {})
        self.assertEqual(self.store.wait_session_events(self.session, 0, stop, .1)[0]['id'], first['id'])
        with self.assertRaises(ValueError):
            with self.store.transaction():
                self.store._event(None, self.session, 'private', {})
                raise ValueError('rollback')
        self.assertEqual(self.store.wait_session_events(self.session, first['seq'], stop, .01), [])

    def test_large_history_is_split_into_bounded_replayable_frames(self):
        expected = [self.store.append_event(None, self.session, 'tool_output', {'text':'x'*100000})['id'] for _ in range(15)]
        response = self.stream()
        first = self.event(response); second = self.event(response)
        self.assertLess(len(json.dumps(first)), 1100000)
        self.assertEqual([e['id'] for e in first + second], expected)


if __name__ == '__main__': unittest.main()
