import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from agentdock.store import Store, Conflict, Forbidden, Invalid, Missing

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state.sqlite3')
        self.p=self.store.add_project('Review',str(self.root))
        self.a=self.store.add_agent(self.p['id'],'Planner','codex','Plan carefully')
        self.b=self.store.add_agent(self.p['id'],'Reviewer','claude','Review changes')
        self.s=self.store.add_session(self.a['id'],'One task')
    def tearDown(self): self.store.close(); self.tmp.cleanup()
    def token(self):
        r=self.store.begin_run(self.s['id'],'Discuss interface')
        return r,self.store.issue_capability(r['id'])

    def test_existing_database_gets_cancellation_indexes(self):
        for name in ('runs_task', 'runs_session', 'messages_sender_run', 'events_run'):
            self.store.db.execute('DROP INDEX ' + name)
        self.store.db.execute('PRAGMA user_version=8')
        self.store.close()
        self.store = Store(self.root / 'state.sqlite3')
        indexes = {row[0] for row in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertTrue({'runs_task', 'runs_session', 'messages_sender_run', 'events_run'} <= indexes)
        self.assertEqual(self.store.get_session(self.s['id'])['title'], 'One task')
    def test_roles_are_optional_and_independent_of_provider(self):
        for provider in ('codex', 'claude'):
            empty = self.store.add_agent(self.p['id'], 'General helper', provider)
            custom = self.store.add_agent(self.p['id'], 'My researcher', provider, '  Research requirements, then propose a plan.  ')
            self.assertEqual(empty['role'], '')
            self.assertEqual(custom['role'], 'Research requirements, then propose a plan.')
            self.assertEqual(self.store.get_agent(custom['id'])['provider'], provider)

    def test_permission_defaults_updates_and_persistence(self):
        self.assertEqual(self.a['permission_mode'], 'ask')
        agent = self.store.add_agent(None, 'Autonomous', 'claude', permission_mode='full_access')
        self.assertEqual(agent['permission_mode'], 'full_access')
        self.store.update_agent(self.a['id'], {'permission_mode': 'full_access'})
        self.store.update_agent(self.a['id'], {'name': 'Renamed'})
        self.store.close(); self.store = Store(self.root/'state.sqlite3')
        self.assertEqual(self.store.get_agent(self.a['id'])['permission_mode'], 'full_access')
        self.assertEqual(self.store.get_agent(agent['id'])['permission_mode'], 'full_access')
        self.assertEqual(self.store.update_agent(self.a['id'], {'permission_mode': 'ask'})['permission_mode'], 'ask')

    def test_invalid_permission_modes_leave_agent_unchanged(self):
        for value in (None, '', 'full', 'FULL_ACCESS', True, {}, []):
            with self.subTest(value=value):
                with self.assertRaises(Invalid):
                    self.store.add_agent(None, 'Invalid', 'codex', permission_mode=value)
                with self.assertRaises(Invalid):
                    self.store.update_agent(self.a['id'], {'permission_mode': value})
                self.assertEqual(self.store.get_agent(self.a['id']), self.a)

    def test_cannot_change_permissions_for_queued_or_running_tasks(self):
        run = self.store.enqueue_run(self.s['id'], 'Queued task')
        for status in ('queued', 'running'):
            with self.subTest(status=status):
                if status == 'running': self.store.claim_next_run()
                with self.assertRaises(Conflict):
                    self.store.update_agent(self.a['id'], {'permission_mode': 'full_access'})
                self.assertEqual(self.store.get_agent(self.a['id'])['permission_mode'], 'ask')
        self.store.finish_run(run['id'], 'completed')
        self.assertEqual(self.store.update_agent(self.a['id'], {'permission_mode': 'full_access'})['permission_mode'], 'full_access')
    def test_agent_edits_persist_and_preserve_native_session_and_history(self):
        r,t = self.token()
        self.store.bind_native_session(self.s['id'], 'native-session-1', r['id'])
        session = self.store.get_session(self.s['id'])
        events = self.store.session_events(self.s['id'])
        edited = self.store.update_agent(self.a['id'], {'name': 'My designer', 'role': 'Design interfaces'})
        self.assertEqual(edited, {**self.a, 'name': 'My designer', 'role': 'Design interfaces'})
        self.assertEqual(self.store.get_session(self.s['id']), session)
        self.assertEqual(self.store.session_events(self.s['id']), events)
        roster = self.store.respond_tool(t, 'agent_list', {})
        self.assertEqual(next(a for a in roster if a['id'] == edited['id'])['role'], 'Design interfaces')
        self.store.finish_run(r['id'], 'completed')
        self.store.close(); self.store = Store(self.root/'state.sqlite3')
        self.assertEqual(self.store.get_agent(edited['id']), edited)
        self.assertEqual(self.store.get_session(self.s['id'])['native_session_id'], 'native-session-1')
        cleared = self.store.update_agent(edited['id'], {'role': ''})
        self.assertEqual(cleared['name'], 'My designer')
        self.assertEqual(cleared['role'], '')
    def test_invalid_agent_edits_leave_original_values_unchanged(self):
        for change in ({}, {'provider': 'claude'}, {'unknown_setting': 'x'}, {'id': 'other'},
                       {'name': ''}, {'name': 'x' * 101}, {'role': None}, {'role': 'x' * 4001},
                       {'name': 'Valid name', 'role': '\x00'}):
            with self.subTest(change=str(change)[:100]):
                with self.assertRaises(Invalid): self.store.update_agent(self.a['id'], change)
                self.assertEqual(self.store.get_agent(self.a['id']), self.a)
        with self.assertRaises(Missing): self.store.update_agent('missing', {'role': 'Research'})
    def test_codex_to_claude_dispatch_and_dedup(self):
        r,t=self.token()
        args=dict(project_id=self.p['id'],sender_id=self.a['id'],recipient_id=self.b['id'],body='Please review',idempotency_key='one',parent_run_id=r['id'])
        m=self.store.enqueue_message(**args)
        self.assertEqual(self.store.enqueue_message(**args)['id'],m['id'])
        self.assertEqual(m['sender_session_id'],self.s['id'])
        self.assertIsNone(self.store.claim_next_run())
        self.store.finish_run(r['id'],'completed')
        child=self.store.claim_next_run()
        self.assertEqual(child['id'],m['run_id'])
        self.assertEqual(self.store.get_message(m['id'])['status'],'running')
        self.assertNotIn('Please review',self.store.context_for_run(child['id']))
        self.store.finish_run(child['id'],'completed',result='Review passed')
        reply=self.store.enqueue_reply(m['id'],'Review passed')
        self.assertEqual(reply['session_id'],self.s['id'])
        self.assertEqual(self.store.enqueue_reply(m['id'],'Review passed')['id'],reply['id'])
        self.assertEqual(self.store.get_message(m['id'])['result'],'Review passed')
        self.assertEqual(self.store.claim_next_run()['id'],reply['id'])
        self.assertEqual(len(self.store.runs_for_root(r['id'])),3)
    def test_dedup_mismatch_rejected(self):
        self.store.send_message(self.p['id'],'human',self.a['id'],'First',idempotency_key='1')
        with self.assertRaises(Conflict): self.store.send_message(self.p['id'],'human',self.a['id'],'Other',idempotency_key='1')
    def test_project_dispatch_and_tool_isolation(self):
        r,t=self.token(); other=self.store.add_project('Other',str(self.root)); a=self.store.add_agent(other['id'],'Other','codex','')
        with self.assertRaises(Forbidden): self.store.enqueue_message(self.p['id'],self.a['id'],a['id'],'No',parent_run_id=r['id'])
        with self.assertRaises(Forbidden): self.store.send_message(self.p['id'],a['id'],self.a['id'],'No')
        self.store.send_message(self.p['id'],'human',self.b['id'],'Hi')
        for removed in ('inbox_read','inbox_ack','message_send'):
            with self.assertRaises(Invalid): self.store.respond_tool(t,removed,{})
        self.assertEqual(len(self.store.respond_tool(t,'agent_list',{})),2)
    def test_capability_expiry_and_revocation(self):
        r,t=self.token()
        self.store.db.execute("UPDATE capabilities SET expires_at='2000-01-01T00:00:00+00:00'")
        with self.assertRaises(Forbidden): self.store.respond_tool(t,'agent_list',{})
        t=self.store.issue_capability(r['id']); self.store.finish_run(r['id'],'cancelled')
        with self.assertRaises(Forbidden): self.store.respond_tool(t,'agent_list',{})
        self.assertNotIn(t,json.dumps(self.store.state()))
    def test_memory_CAS_single_winner(self):
        self.store.put_memory(self.p['id'],'Design','Original',0)
        def change(value):
            try: return self.store.put_memory(self.p['id'],'Design',value,1)['version']
            except Conflict: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(change,['A','B']))
        self.assertCountEqual(results,[2,'conflict'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM memory_versions').fetchone()[0],2)
    def test_proposals_need_human_review_and_version_match(self):
        self.store.put_memory(self.p['id'],'Fact','Initial',0); _,t=self.token()
        proposal=self.store.respond_tool(t,'memory_propose',{'key':'Fact','content':'Proposed','expected_version':1})
        self.assertEqual(self.store.respond_tool(t,'memory_search',{'query':'Fact'})[0]['content'],'Initial')
        self.store.put_memory(self.p['id'],'Fact','New fact',1)
        with self.assertRaises(Conflict): self.store.approve_proposal(proposal['id'],1)
        p=self.store.respond_tool(t,'memory_propose',{'key':'New','content':'Reviewed','expected_version':0})
        m=self.store.approve_proposal(p['id'],0)
        self.assertIn(self.a['id'],m['source'])
        with self.assertRaises(Conflict): self.store.approve_proposal(p['id'],0)
    def test_archived_and_cross_project_memories_excluded(self):
        m=self.store.put_memory(self.p['id'],'Old','OLD_VALUE',0); self.store.archive_memory(m['id'],1)
        other=self.store.add_project('Other',str(self.root)); self.store.put_memory(other['id'],'Other','OTHER_VALUE',0)
        r,t=self.token(); self.assertEqual(self.store.respond_tool(t,'memory_search',{'query':''}),[])
        c=self.store.context_for_run(r['id']); self.assertNotIn('OLD_VALUE',c); self.assertNotIn('OTHER_VALUE',c)
    def test_workspace_overlap_protection(self):
        self.token()
        sub=self.root/'sub'; sub.mkdir()
        for directory in (self.root,sub):
            p=self.store.add_project('Alias',str(directory)); a=self.store.add_agent(p['id'],'Other','codex',''); s=self.store.add_session(a['id'],'Other')
            with self.assertRaises(Conflict): self.store.begin_run(s['id'],'Overlapping')
    def test_file_lock_prevents_second_instance_from_corrupting_run(self):
        r,t=self.token()
        with self.assertRaises(Conflict): Store(self.root/'state.sqlite3')
        self.assertEqual(self.store.get_session(self.s['id'])['status'],'running')
        self.assertEqual(len(self.store.respond_tool(t,'agent_list',{})),2)
    def test_restart_marks_interrupted_and_never_replays(self):
        r,t=self.token(); self.store.close(); self.store=Store(self.root/'state.sqlite3')
        self.assertEqual(self.store.get_session(self.s['id'])['status'],'interrupted')
        with self.assertRaises(Forbidden): self.store.respond_tool(t,'agent_list',{})
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],1)
    def test_cancel_invalidates_approval(self):
        r,_=self.token(); a=self.store.create_approval(r['id'],{'toolCall':{'title':'Write'}},[{'optionId':'once','kind':'allow_once','name':'Allow once'}])
        with self.assertRaises(Invalid): self.store.resolve_approval(a['id'],'fake')
        self.store.finish_run(r['id'],'cancelled')
        with self.assertRaises(Conflict): self.store.resolve_approval(a['id'],'once')
        self.assertEqual(self.store.get_approval(a['id'])['status'],'cancelled')
    def test_version_and_manual_billing_validation(self):
        for invalid in (True,1.5,-1,None):
            with self.assertRaises(Invalid): self.store.put_memory(self.p['id'],'x','y',invalid)
        for cost in (float('nan'),float('inf'),True,-1):
            with self.assertRaises(Invalid): self.store.save_subscription('codex',monthly_cost=cost)
        self.assertIsNone(self.store.save_subscription('claude')['renewal_date'])

if __name__=='__main__': unittest.main()
