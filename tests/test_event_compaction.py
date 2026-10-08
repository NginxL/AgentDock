import tempfile
import unittest
from pathlib import Path

from agentdock.store import Store


class CompactionTests(unittest.TestCase):
    def test_compaction_keeps_final_response_tool_result_and_partial_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'state.sqlite3')
            try:
                agent = store.add_agent(None, 'Fixture', 'codex')
                session = store.add_session(agent['id'], 'Fixture')
                run = store.begin_run(session['id'], 'Fixture')
                def event(kind, **payload):
                    return store.append_event(None, session['id'], kind, {'run_id': run['id'], 'provider': 'codex', **payload})
                event('agent_message_chunk', item_id='answer', content={'text': 'Final '})
                middle = event('agent_message_chunk', item_id='answer', content={'text': 'answer'})
                final = event('agent_message', item_id='answer', content={'text': 'Final answer'})
                event('tool_output', item_id='tool', text='Output')
                tool = event('tool_result', item={'id': 'tool', 'aggregatedOutput': 'Output', 'exitCode': 0})
                partial = event('reasoning_chunk', item_id='unfinished', text='Partial summary')
                self.assertEqual(store.compact_run_events(run['id']), 0)
                store.finish_run(run['id'], 'completed', result='Final answer')
                self.assertEqual(store.compact_run_events(run['id']), 3)
                replay = store.session_events(session['id'], middle['seq'])
                self.assertTrue({final['id'], tool['id'], partial['id']}.issubset({r['id'] for r in replay}))
                self.assertEqual(store.get_run(run['id'])['result'], 'Final answer')
                self.assertEqual(store.compact_run_events(run['id']), 0)
            finally:
                store.close()
