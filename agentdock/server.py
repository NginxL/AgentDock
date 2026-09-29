"""Loopback HTTP boundary. Importing this module never binds a port or starts agents."""
from __future__ import annotations
import argparse
import hmac
import json
import os
import secrets
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from . import __version__
from .store import Store, Invalid, Missing, Conflict, Forbidden

MAX_BODY = 262144


class API:
    def __init__(self, store, runtime, quota, admin_token, port=47831, execution_enabled=False):
        self.store=store; self.runtime=runtime; self.quota=quota
        from .catalog import Catalog
        self.catalog=Catalog(getattr(runtime, "config", {}))
        self.usage=None
        self.admin_token=admin_token; self.port=port; self.execution_enabled=execution_enabled

    def dispatch(self, method, path, headers, body=b""):
        headers={k.lower():v for k,v in headers.items()}
        try:
            self._boundary(headers)
            parsed=urlsplit(path)
            token=headers.get("authorization","")
            if not token.startswith("Bearer "): return 401,{"error":"Authentication required"}
            token=token[7:]
            if parsed.path=="/mcp/tool":
                if method!="POST": return 405,{"error":"POST required"}
                payload=self._json(headers,body)
                if payload.get("name") in ("message_send", "task_status"):
                    if not self.execution_enabled: raise Forbidden("Execution is disabled for review")
                    return 200,self.runtime.respond_tool(token,payload.get("name"),payload.get("arguments",{}))
                return 200,self.store.respond_tool(token,payload.get("name"),payload.get("arguments",{}))
            if not hmac.compare_digest(token,self.admin_token): return 401,{"error":"Invalid workbench token"}
            if method=="GET" and parsed.path=="/api/metrics":
                from .metrics import snapshot
                result=snapshot(self.store)
                result["scan_status"]=self.usage.status if self.usage else "disabled"
                result["activity"]["status"]=self.usage.activity_status if self.usage else "disabled"
                return 200,result
            if method=="GET" and parsed.path=="/api/quotas":
                quotas=[]
                for provider,env in self.store.configured_connections():
                    value=self._quota(provider,env) or {"provider":provider,"status":"unknown","windows":[]}
                    if env!='local': value={**value,'environment_id':env,'environment_name':self.store.get_environment(env)['name']}
                    quotas.append({**value, 'agent_names': self.store.connection_agent_names(provider, env)})
                return 200,{'quotas':quotas}
            if method=="GET" and parsed.path=="/api/state":
                state=self.store.state()
                connections=set(self.store.configured_connections())
                state["quotas"]=[self._quota(q["provider"],q.get('environment_id','local')) or q for q in state["quotas"] if (q["provider"],q.get('environment_id','local')) in connections]
                state["subscriptions"]=[s for s in state["subscriptions"] if (s["provider"],s.get('environment_id','local')) in connections]
                state["runtime"]={"enabled":self.execution_enabled,"version":__version__}
                return 200,state
            parts=parsed.path.strip("/").split("/")
            if method=="GET" and len(parts)==3 and parts[:2]==["api","models"]:
                environment_id=parse_qs(parsed.query).get('environment_id',['local'])[0]
                if environment_id!='local':
                    if not self.execution_enabled: raise Forbidden('Execution is disabled for review')
                    return 200,self.runtime.remote.models(environment_id,parts[2])
                return 200,self.catalog.read(parts[2])
            if method=="GET" and len(parts)==4 and parts[:2]==["api","sessions"] and parts[3]=="events":
                query=parse_qs(parsed.query)
                return 200,{"events":self.store.session_events(parts[2],int(query.get("after",[0])[0]))}
            if method!="POST": return 404,{"error":"Route not found"}
            p=self._json(headers,body)
            if parsed.path=="/api/environments": result=self.store.add_environment(p.get('name'),p.get('ssh_host'),p.get('python','python3'))
            elif len(parts)==4 and parts[:2]==['api','environments']:
                if parts[3]=='connect':
                    if not self.execution_enabled: raise Forbidden('Execution is disabled for review')
                    result=self.runtime.remote.connect(parts[2])
                elif parts[3]=='remove': self.store.remove_environment(parts[2]); result={'ok':True}
                else: raise Missing('Route not found')
            elif parsed.path=="/api/projects": result=self.store.add_project(p.get("name"),p.get("path"),p.get('environment_id','local'))
            elif parsed.path=="/api/agents": result=self.store.add_agent(p.get("project_id"),p.get("name"),p.get("provider"),p.get("role",""),p.get("workspace"),p.get("model"),p.get("effort"),p.get('environment_id','local'),p.get('permission_mode','ask'))
            elif len(parts)==3 and parts[:2]==["api","agents"]: result=self.store.update_agent(parts[2],p)
            elif parsed.path=="/api/sessions": result=self.store.add_session(p.get("agent_id"),p.get("title"))
            elif parsed.path=="/api/messages":
                if p.get("sender_id","human")!="human": raise Forbidden("Human endpoint cannot impersonate an agent")
                if not self.execution_enabled: raise Forbidden("Execution is disabled for review")
                result=self.runtime.send_message(p.get("project_id"),p.get("recipient_id"),p.get("body"),p.get("correlation_id"),p.get("idempotency_key"),p.get("recipient_session_id"))
            elif parsed.path=="/api/memories": result=self.store.put_memory(p.get("project_id"),p.get("key"),p.get("content"),p.get("expected_version"))
            elif parsed.path=="/api/subscriptions": result=self.store.save_subscription(p.get("provider"),p.get("plan",""),p.get("renewal_date"),p.get("monthly_cost"),p.get("currency","USD"),p.get('environment_id','local'))
            elif parsed.path=="/api/quotas/refresh":
                if not self.execution_enabled: raise Forbidden("Execution is disabled for review")
                if p.get('environment_id','local')=='local': result=self.quota.refresh(p.get("provider"))
                else: result=self.quota.refresh(p.get("provider"),environment_id=p['environment_id'])
            elif len(parts)==4 and parts[:2]==["api","sessions"]:
                if parts[3]=='delete': return 200,self.runtime.delete_session(parts[2])
                if not self.execution_enabled: raise Forbidden("Execution is disabled for review")
                if parts[3]=="run": result=self.runtime.start(parts[2],p.get("prompt"))
                elif parts[3]=="cancel": self.runtime.cancel(parts[2]); result={"ok":True}
                else: raise Missing("Route not found")
            elif len(parts)==4 and parts[:2]==["api","runs"] and parts[3]=="cancel":
                if not self.execution_enabled: raise Forbidden("Execution is disabled for review")
                self.runtime.cancel_run(parts[2]); result={"ok":True}
            elif len(parts)==4 and parts[:2]==["api","memories"] and parts[3]=="archive": result=self.store.archive_memory(parts[2],p.get("expected_version"))
            elif len(parts)==4 and parts[:2]==["api","proposals"]:
                if parts[3]=="approve": result=self.store.approve_proposal(parts[2],p.get("expected_version"))
                elif parts[3]=="reject": result=self.store.reject_proposal(parts[2])
                else: raise Missing("Route not found")
            elif len(parts)==3 and parts[:2]==["api","approvals"]:
                if not self.execution_enabled: raise Forbidden("Execution is disabled for review")
                self.runtime.approve(parts[2],p.get("option_id")); result={"ok":True}
            else: raise Missing("Route not found")
            return 200,result
        except Forbidden as error: return 403,{"error":str(error)}
        except Missing: return 404,{"error":"Resource not found"}
        except Conflict as error: return 409,{"error":str(error)}
        except (Invalid,ValueError,TypeError) as error: return 400,{"error":str(error)[:300]}
        except Exception: return 500,{"error":"Operation failed. No successful result was recorded; inspect local configuration."}

    def _quota(self, provider, environment_id):
        return self.quota.cached(provider) if environment_id=='local' else self.quota.cached(provider,environment_id)

    def _boundary(self, headers):
        expected="127.0.0.1:"+str(self.port)
        if headers.get("host")!=expected: raise Forbidden("Unexpected Host")
        origin=headers.get("origin")
        if origin is not None and origin!="http://"+expected: raise Forbidden("Cross-origin requests are not allowed")
        if headers.get("sec-fetch-site") in ("cross-site",): raise Forbidden("Cross-site requests are not allowed")

    @staticmethod
    def _json(headers, body):
        if len(body)>MAX_BODY: raise Invalid("Request too large")
        if headers.get("content-type","").split(";",1)[0].strip()!="application/json": raise Invalid("application/json required")
        try:
            value=json.loads(body,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite number")))
        except (ValueError,UnicodeError): raise Invalid("Invalid JSON")
        if not isinstance(value,dict): raise Invalid("JSON object required")
        return value


def handler_for(api, web_root):
    web_root=Path(web_root).resolve()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # Do not log prompts, URLs or bearer tokens.
        def _reply(self,status,body,kind="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type",kind)
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path.startswith(("/api/","/mcp/")): return self._api()
            try: api._boundary(dict((k.lower(),v) for k,v in self.headers.items()))
            except Forbidden: return self._reply(403,b"Forbidden","text/plain")
            relative=urlsplit(self.path).path.lstrip("/") or "index.html"
            candidate=(web_root/relative).resolve()
            if web_root not in candidate.parents or not candidate.is_file(): return self._reply(404,b"Build frontend with npm ci && npm run build in web/ first.","text/plain")
            suffix=candidate.suffix
            types={".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".svg":"image/svg+xml",".png":"image/png",".ico":"image/x-icon"}
            if suffix not in types: return self._reply(404,b"Not found","text/plain")
            self._reply(200,candidate.read_bytes(),types[suffix])
        def do_POST(self): self._api()
        def _api(self):
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<=length<=MAX_BODY: return self._reply(413,b'{"error":"Request too large"}')
                self.connection.settimeout(10)
                body=self.rfile.read(length) if length else b""
            except (ValueError,TimeoutError): return self._reply(400,b'{"error":"Invalid request body"}')
            status,result=api.dispatch(self.command,self.path,dict(self.headers),body)
            self._reply(status,json.dumps(result,ensure_ascii=False).encode())
    return Handler


def main(argv=None):
    parser=argparse.ArgumentParser(description="AgentDock local workbench. Execution is disabled unless explicitly enabled.")
    parser.add_argument("--data-dir",default=str(Path.home()/".local/share/agentdock"))
    parser.add_argument("--port",type=int,default=47831)
    parser.add_argument("--config",type=Path)
    parser.add_argument("--enable-execution",action="store_true")
    args=parser.parse_args(argv)
    if not 1024<=args.port<=65535: parser.error("port must be between 1024 and 65535")
    config={}
    if args.config:
        config=json.loads(args.config.read_text())
        if not isinstance(config,dict): parser.error("config must be an object")
    commands=config.get("commands",{"codex":["codex","app-server"],"claude":["claude"]})
    if not isinstance(commands,dict) or any(k not in ("codex","claude") or not isinstance(v,list) or not v or any(not isinstance(x,str) or not x for x in v) for k,v in commands.items()): parser.error("commands must contain codex/claude argument lists")
    command=config.get("quota_command",config.get("agentmeter_command"))
    if command is not None and (not isinstance(command,list) or not command or any(not isinstance(x,str) or not x or "\x00" in x for x in command)): parser.error("quota_command must be an argument list")
    data=Path(args.data_dir).expanduser(); data.mkdir(parents=True,exist_ok=True,mode=0o700); data.chmod(0o700)
    # Never rotate a live instance's token while trying to start another one.
    store=Store(data/"agentdock.sqlite3")
    try:
        server=ThreadingHTTPServer(("127.0.0.1",args.port),BaseHTTPRequestHandler)
    except BaseException:
        store.close()
        raise
    server.daemon_threads=False
    server.block_on_close=True
    token=secrets.token_urlsafe(32)
    token_path=data/"admin.token"
    descriptor=os.open(token_path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,"w") as output: output.write(token+"\n")
    token_path.chmod(0o600)
    from .runtime import Runtime
    from .quota import QuotaService
    runtime_config={"execution_enabled":args.enable_execution,"commands":commands,"base_url":"http://127.0.0.1:"+str(args.port),"python":sys.executable,"package_root":str(Path(__file__).resolve().parent.parent),"approval_timeout":120,"run_timeout":900}
    runtime=Runtime(store,runtime_config)
    quota=QuotaService(store,command,args.enable_execution,source="AgentMeter" if "agentmeter_command" in config and "quota_command" not in config else "AgentDock")
    quota.remote=runtime.remote
    api=API(store,runtime,quota,token,args.port,args.enable_execution)
    server.RequestHandlerClass=handler_for(api,Path(__file__).resolve().parent.parent/"web/dist")
    def stop(*_): threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    print("AgentDock: http://127.0.0.1:"+str(args.port))
    print("Local access token file: "+str(token_path))
    print("Execution: "+("native sessions and automatic task dispatch enabled" if args.enable_execution else "disabled (review mode)"))
    try:
        from .metrics import LocalUsage
        api.usage=LocalUsage(store)
        if args.enable_execution: api.usage.start()
        quota.start_auto_refresh()
        server.serve_forever(poll_interval=0.3)
    finally: api.usage.close() if api.usage else None; api.catalog.close(); runtime.close(); quota.close(); server.server_close(); store.close()

if __name__=="__main__": main()
