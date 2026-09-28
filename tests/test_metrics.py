import json
from pathlib import Path
import tempfile
import time
import unittest
from datetime import datetime, timezone
from agentdock.store import Store, Forbidden, Conflict, Invalid
from agentdock.metrics import normalize, record, snapshot, LocalUsage


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state.sqlite3')
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def bind(self, provider, native):
        a = self.store.add_agent(None, provider, provider)
        session = self.store.add_session(a['id'], 'Chat')
        self.store.bind_native_session(session['id'], native)
        return a

    def test_only_registered_agent_sessions_contribute_to_every_metric(self):
        at = time.time()
        u = normalize('claude', {'input_tokens': 10, 'output_tokens': 20})
        record(self.store, 'claude', 'unrelated', 'm', u, at, 'local', (at-2,20))
        empty = snapshot(self.store, at)
        self.assertEqual(empty['total']['total_tokens'], 0)
        self.assertEqual(empty['total']['current_tps'], 0)
        self.assertEqual(empty['providers'], {})
        self.assertEqual(empty['activity']['days'], [])
        a = self.bind('claude', 'managed')
        record(self.store, 'claude', 'managed', 'm', u, at, 'managed', (at-2,20))
        result = snapshot(self.store, at)
        self.assertEqual(set(result['providers']), {'claude'})
        self.assertEqual(result['total']['total_tokens'], 30)
        self.assertEqual(result['total']['sessions'], 1)
        self.assertEqual(result['agents'][a['id']]['total_tokens'], 30)
        self.assertEqual(sum(day['tokens'] for day in result['activity']['days']), 30)
        self.assertAlmostEqual(result['total']['average_tps'], round(20/180, 2))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM token_records').fetchone()[0], 2)

    def test_scanner_ignores_unbound_files_and_starts_after_binding(self):
        path = self.root / '.claude/projects/p/unrelated.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'type':'assistant', 'sessionId':'unrelated', 'message':{'id':'m','usage':{'input_tokens':1,'output_tokens':2}}}) + '\n')
        scan = LocalUsage(self.store, self.root)
        scan.scan()
        self.assertEqual(scan.scanned, 0)
        self.bind('claude', 'managed')
        scan.scan()
        self.assertEqual(scan.scanned, 0)
        self.bind('claude', 'unrelated')
        scan.scan()
        self.assertEqual(snapshot(self.store)['total']['total_tokens'], 3)

    def test_independent_agent_runs_without_project_and_stays_isolated(self):
        a=self.store.add_agent(None,'Personal','codex',model='test-model',effort='high')
        self.assertEqual(self.store.state()['projects'],[])
        self.assertTrue(Path(a['workspace']).is_dir())
        s=self.store.add_session(a['id'],'Chat');r=self.store.begin_run(s['id'],'hello')
        cap=self.store.issue_capability(r['id'])
        self.assertEqual(self.store.respond_tool(cap,'agent_list',{}),[])
        self.assertEqual(self.store.respond_tool(cap,'memory_search',{'query':''}),[])
        with self.assertRaises(Forbidden):self.store.respond_tool(cap,'memory_propose',{'key':'k','content':'secret','expected_version':0})
        self.assertNotIn('approved_project_memory',self.store.context_for_run(r['id']))
        with self.assertRaises(Conflict):self.store.update_agent(a['id'],{'model':'new'})
        approval=self.store.create_approval(r['id'],{'tool':'test'},[{'optionId':'deny','name':'Deny','kind':'reject_once'}])
        self.assertIsNone(approval['project_id'])
        self.assertEqual(self.store.resolve_approval(approval['id'],'deny')['status'],'resolved')
        self.store.finish_run(r['id'],'completed');self.store.update_agent(a['id'],{'model':'new','effort':'low'})
        with self.assertRaises(Conflict):self.store.update_agent(a['id'],{'workspace':str(self.root)})
    def test_overlap_lock_works_for_projectless_and_project_agents(self):
        p=self.store.add_project('P',str(self.root));a=self.store.add_agent(p['id'],'A','codex');b=self.store.add_agent(None,'B','claude',workspace=str(self.root))
        sa=self.store.add_session(a['id'],'a');sb=self.store.add_session(b['id'],'b')
        self.store.begin_run(sa['id'],'work');self.store.enqueue_run(sb['id'],'wait');self.assertIsNone(self.store.claim_next_run())
    def test_invalid_model_is_not_a_cli_option(self):
        for model in ['--help','bad\nmodel','$(secret)']:
            with self.assertRaises(Invalid):self.store.add_agent(None,'X','codex',model=model)
    def test_input_cache_normalization_and_unknown(self):
        u=normalize('claude',{'input_tokens':10,'output_tokens':5,'cache_read_input_tokens':20,'cache_creation_input_tokens':30})
        self.assertEqual((u['input_tokens'],u['total_tokens']),(60,65))
        for raw in [{},{'input_tokens':True,'output_tokens':1},{'input_tokens':1,'output_tokens':-1}]:self.assertIsNone(normalize('claude',raw))
    def test_usage_dedup_across_live_local_and_restart(self):
        at=time.time();a=self.store.add_agent(None,'A','claude');s=self.store.add_session(a['id'],'S');self.store.bind_native_session(s['id'],'native')
        u=normalize('claude',{'input_tokens':10,'output_tokens':8})
        for source in ['managed','local','local']:record(self.store,'claude','native','message',u,at,source,(at-2,8))
        m=snapshot(self.store,at)
        self.assertEqual(m['total']['total_tokens'],18);self.assertEqual(m['agents'][a['id']]['output_tokens'],8)
        self.assertAlmostEqual(m['total']['average_tps'],round(8/180,2),2)
        self.store.close();self.store=Store(self.root/'state.sqlite3')
        self.assertEqual(snapshot(self.store)['total']['total_tokens'],18)
        record(self.store,'claude','native','message',normalize('claude',{'input_tokens':10,'output_tokens':12}),at+1,'local')
        self.assertEqual(snapshot(self.store)['total']['total_tokens'],22)
    def test_codex_cumulative_and_partial_log_tail(self):
        self.bind("codex", "x")
        path=self.root/'.codex/sessions/log.jsonl';path.parent.mkdir(parents=True)
        def event(n):return {'timestamp':datetime.now(timezone.utc).isoformat(),'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':100,'output_tokens':n}}}}
        lines=[{'type':'session_meta','payload':{'id':'x'}},event(5),event(15)]
        path.write_text('\n'.join(map(json.dumps,lines))+'\n{"partial":')
        scan=LocalUsage(self.store,self.root);scan.scan();scan.scan()
        self.assertEqual(snapshot(self.store)['total']['total_tokens'],115)
        with path.open('a') as f:f.write('true}\n'+json.dumps(event(30))+'\n')
        scan.scan();self.assertEqual(snapshot(self.store)['total']['total_tokens'],130)
        archive=self.root/'.codex/archived_sessions';archive.mkdir();(archive/'copy.jsonl').write_bytes(path.read_bytes())
        scan.scan();self.assertEqual(snapshot(self.store)['total']['total_tokens'],130)
    def test_differently_batched_live_and_log_spans_do_not_double_count(self):
        at=time.time()
        for counters in ((5,10,7,10),(10,5,10)):
            identity='native-'+str(counters[0])
            for n in counters:
                u=normalize('claude',{'input_tokens':1,'output_tokens':n})
                record(self.store,'claude',identity,'m',u,at,'local',(at-2,n))
            observed=self.store.db.execute('SELECT SUM(tokens) FROM token_spans WHERE native_id=?',(identity,)).fetchone()[0]
            self.assertEqual(observed,10)
    def test_claude_repeated_content_blocks_incremental_and_rotation(self):
        self.bind("claude", "c")
        path=self.root/'.claude/projects/p/c.jsonl';path.parent.mkdir(parents=True)
        event={'timestamp':datetime.now(timezone.utc).isoformat(),'type':'assistant','sessionId':'c','message':{'id':'m','usage':{'input_tokens':2,'output_tokens':7},'content':'private conversation'}}
        path.write_text((json.dumps(event)+'\n')*2);scan=LocalUsage(self.store,self.root);scan.scan();scan.scan()
        self.assertEqual(snapshot(self.store)['total']['total_tokens'],9)
        self.assertNotIn('private conversation',str(self.store.db.execute('SELECT * FROM token_records').fetchall()))
        event['message']['id']='m2';path.write_text(json.dumps(event)+'\n');scan.scan()
        self.assertEqual(snapshot(self.store)['total']['total_tokens'],18)
    def test_idle_and_unknown_live_rate_differ(self):
        a=self.store.add_agent(None,'A','codex');s=self.store.add_session(a['id'],'S')
        self.assertEqual(snapshot(self.store)['total']['current_tps'],0)
        r=self.store.begin_run(s['id'],'x');self.assertIsNone(snapshot(self.store)['total']['current_tps'])
        self.store.finish_run(r['id'],'completed');self.assertEqual(snapshot(self.store)['total']['current_tps'],0)
    def test_existing_project_database_migrates_without_losing_bindings(self):
        import sqlite3
        path=self.root/'legacy.sqlite3';db=sqlite3.connect(path)
        db.executescript('''
        CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE agents(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),name TEXT NOT NULL,provider TEXT NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE sessions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),agent_id TEXT NOT NULL REFERENCES agents(id),title TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,native_session_id TEXT);
        ''')
        db.execute('INSERT INTO projects VALUES(?,?,?,?)',('p','Project',str(self.root),'2026-01-01'))
        db.execute('INSERT INTO agents VALUES(?,?,?,?,?,?)',('a','p','A','codex','role','2026-01-01'))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)',('s','p','a','Chat','completed','2026-01-01','2026-01-01','native-old'));db.commit();db.close()
        migrated=Store(path)
        try:
            self.assertEqual(migrated.get_session('s')['native_session_id'],'native-old')
            self.assertEqual(migrated.get_agent('a')['permission_mode'], 'ask')
            self.assertEqual(migrated.get_session('s')['workspace'],str(self.root))
            self.assertEqual(migrated.db.execute('PRAGMA foreign_key_check').fetchall(),[])
            migrated.add_agent(None,'Independent','claude')
            backups=list((self.root/'backups').glob('pre-0.3-*.sqlite3'))
            self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].stat().st_mode & 0o777,0o600)
            original=sqlite3.connect(backups[0])
            try:self.assertEqual(original.execute('SELECT native_session_id FROM sessions WHERE id=?',('s',)).fetchone()[0],'native-old')
            finally:original.close()
        finally:migrated.close()
