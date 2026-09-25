import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from agentdock.store import Store, Conflict, Forbidden, Invalid

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
    def test_codex_to_claude_mailbox_and_dedup(self):
        r,t=self.token(); args={'recipient_id':self.b['id'],'body':'Please review','idempotency_key':'one'}
        m=self.store.respond_tool(t,'message_send',args)
        self.assertEqual(self.store.respond_tool(t,'message_send',args)['id'],m['id'])
        self.assertEqual(m['sender_id'],self.a['id'])
        self.store.finish_run(r['id'],'completed')
        s=self.store.add_session(self.b['id'],'Review'); r=self.store.begin_run(s['id'],'Inbox'); t=self.store.issue_capability(r['id'])
        self.assertEqual(len(self.store.respond_tool(t,'inbox_read',{})),1)
        self.assertIn('Please review',self.store.context_for_run(r['id']))
        self.store.respond_tool(t,'inbox_ack',{'message_id':m['id']})
        self.assertEqual(self.store.respond_tool(t,'inbox_read',{}),[])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],2)
    def test_dedup_mismatch_rejected(self):
        self.store.send_message(self.p['id'],'human',self.a['id'],'First',idempotency_key='1')
        with self.assertRaises(Conflict): self.store.send_message(self.p['id'],'human',self.a['id'],'Other',idempotency_key='1')
    def test_project_and_inbox_isolation(self):
        _,t=self.token(); other=self.store.add_project('Other',str(self.root)); a=self.store.add_agent(other['id'],'Other','codex','')
        with self.assertRaises(Forbidden): self.store.respond_tool(t,'message_send',{'recipient_id':a['id'],'body':'No'})
        with self.assertRaises(Forbidden): self.store.send_message(self.p['id'],a['id'],self.a['id'],'No')
        m=self.store.send_message(self.p['id'],'human',self.b['id'],'Hi')
        with self.assertRaises(Forbidden): self.store.respond_tool(t,'inbox_ack',{'message_id':m['id']})
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
