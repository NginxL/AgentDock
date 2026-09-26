import json
import tempfile
import unittest
from unittest.mock import Mock
from agentdock.store import Store
from agentdock.server import API
from agentdock.mcp import Bridge

class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Store(':memory:'); self.runtime=Mock(); self.quota=Mock()
        self.api=API(self.store,self.runtime,self.quota,'test-admin')
        self.h={'Host':'127.0.0.1:47831','Authorization':'Bearer test-admin','Content-Type':'application/json','Origin':'http://127.0.0.1:47831'}
    def tearDown(self): self.store.close(); self.tmp.cleanup()
    def call(self,method,path,payload=None,headers=None): return self.api.dispatch(method,path,self.h if headers is None else headers,json.dumps(payload or {}).encode())
    def test_auth_host_origin(self):
        for override in ({'Authorization':''},{'Host':'evil.example:47831'},{'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'}): self.assertEqual(self.call('GET','/api/state',headers={**self.h,**override})[0],401 if 'Authorization' in override else 403)
        status,state=self.call('GET','/api/state'); self.assertEqual(status,200); self.assertFalse(state['runtime']['enabled']); self.assertNotIn('test-admin',json.dumps(state))
    def test_review_mode_never_invokes_runtime_or_quota(self):
        for path in ('/api/sessions/x/run','/api/sessions/x/cancel','/api/quotas/refresh','/api/approvals/x','/api/messages','/api/runs/x/cancel'): self.assertEqual(self.call('POST',path,{'prompt':'go','provider':'codex'})[0],403)
        self.assertEqual(self.runtime.mock_calls,[]); self.assertEqual(self.quota.mock_calls,[])
    def test_scoped_tools_cannot_call_human_approval_endpoints(self):
        _,p=self.call('POST','/api/projects',{'name':'P','path':self.tmp.name})
        _,a=self.call('POST','/api/agents',{'project_id':p['id'],'name':'A','provider':'codex'})
        _,s=self.call('POST','/api/sessions',{'agent_id':a['id'],'title':'Task'})
        r=self.store.begin_run(s['id'],'Hi'); token=self.store.issue_capability(r['id']); h={**self.h,'Authorization':'Bearer '+token}
        status,proposal=self.call('POST','/mcp/tool',{'name':'memory_propose','arguments':{'key':'Fact','content':'Value','expected_version':0}},h)
        self.assertEqual(status,200)
        self.assertEqual(self.call('GET','/api/state',headers=h)[0],401)
        route='/api/proposals/'+proposal['id']+'/approve'
        self.assertEqual(self.call('POST',route,{'expected_version':0},h)[0],401)
        self.assertEqual(self.call('POST',route,{'expected_version':0})[0],200)
    def test_human_cannot_impersonate_agent(self): self.assertEqual(self.call('POST','/api/messages',{'sender_id':'agent'})[0],403)
    def test_content_type_json_size_and_nan(self):
        self.assertEqual(self.call('POST','/api/projects',headers={**self.h,'Content-Type':'text/plain'})[0],400)
        for body in (b'{bad',b' '*262145,b'{"monthly_cost": NaN}'):
            self.assertEqual(self.api.dispatch('POST','/api/subscriptions',self.h,body)[0],400)

class MCPTests(unittest.TestCase):
    def test_handshake_tools_and_impersonation(self):
        calls=[]; b=Bridge(lambda name,args:calls.append((name,args)) or {'ok':True})
        self.assertIn('error',b.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'}))
        r=b.handle({'jsonrpc':'2.0','id':2,'method':'initialize','params':{'protocolVersion':'2025-06-18'}})
        self.assertEqual(r['result']['protocolVersion'],'2025-06-18')
        self.assertIsNone(b.handle({'jsonrpc':'2.0','method':'notifications/initialized'}))
        self.assertEqual(len(b.handle({'jsonrpc':'2.0','id':3,'method':'tools/list'})['result']['tools']),5)
        bad=b.handle({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'message_send','arguments':{'sender_id':'fake','recipient_id':'x','body':'Hi'}}})
        self.assertIn('error',bad); self.assertEqual(calls,[])
        r=b.handle({'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'agent_list'}})
        self.assertFalse(r['result']['isError']); self.assertEqual(calls,[('agent_list',{})])
    def test_private_tool_error_not_returned(self):
        def fail(*args): raise ValueError('sk-private-credential')
        b=Bridge(fail); b.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
        r=b.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'agent_list'}})
        self.assertTrue(r['result']['isError']); self.assertNotIn('sk-private',json.dumps(r))

if __name__=='__main__': unittest.main()
