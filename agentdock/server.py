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
from .store import Store, Invalid, Missing, Conflict, Forbidden
from .registry import availability as availability
from .registry import commands as resolve_commands

MAX_BODY = 262144


class API:
    def __init__(self, store, runtime, quota, admin_token, port=47831, execution_enabled=False):
        self.store=store; self.runtime=runtime; self.quota=quota
        from .catalog import Catalog
        self.catalog=Catalog(getattr(runtime, "config", {}))
        self.usage=None
        self.admin_token=admin_token; self.port=port; self.execution_enabled=execution_enabled
        self.closed = threading.Event()
        self.stream_slots = threading.BoundedSemaphore(32)

    def close(self):
        self.closed.set()
        with self.store.changed:
            self.store.changed.notify_all()
            for condition in self.store._session_conditions.values():
                condition.notify_all()
        self.catalog.close()

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
                if payload.get("name") in ("message_send", "task_status", "task_context", "task_history", "task_result", "task_ask", "task_deliver", "task_review"):
                    if not self.execution_enabled: raise Forbidden("Execution is disabled for review")
                    return 200,self.runtime.respond_tool(token,payload.get("name"),payload.get("arguments",{}))
                return 200,self.store.respond_tool(token,payload.get("name"),payload.get("arguments",{}))
            if not hmac.compare_digest(token,self.admin_token): return 401,{"error":"Invalid workbench token"}
            from .routes import dispatch_admin
            payload = self._json(headers, body) if method == 'POST' else {}
            return 200, dispatch_admin(self, method, parsed, payload)
        except Forbidden as error: return 403,{'error':str(error), 'code':getattr(error, 'code', 'forbidden')}
        except Missing: return 404,{'error':'Resource not found', 'code':'not_found'}
        except Conflict as error: return 409,{'error':str(error), 'code':getattr(error, 'code', 'state_conflict')}
        except Invalid as error: return 400,{'error':str(error)[:300], 'code':getattr(error, 'code', 'invalid_request')}
        except (ValueError,TypeError): return 400,{'error':'Invalid request', 'code':'invalid_request'}
        except Exception as error:
            from .diagnostics import failure
            return 500,{'error':'Operation failed. Export diagnostics and include the error ID.',
                        'code':'internal_error', 'error_id':failure(error, 'api')}

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
            parsed = urlsplit(self.path)
            if parsed.path == '/api/state/stream':
                return self._state_stream()
            parts = parsed.path.strip('/').split('/')
            if len(parts) == 5 and parts[:2] == ['api', 'sessions'] and parts[3:] == ['events', 'stream']:
                return self._events(parts[2], parsed.query)
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
        def _state_stream(self):
            status, result = api.dispatch('GET', '/api/state/version', dict(self.headers))
            if status != 200:
                return self._reply(status, json.dumps(result).encode())
            if not api.stream_slots.acquire(blocking=False):
                return self._reply(503, b'{"error":"Too many event streams","code":"stream_limit"}')
            try:
                self.connection.settimeout(10)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                version = result['version']
                while not api.closed.is_set() and not api.store.closed:
                    self.wfile.write(('data: ' + json.dumps({'version': version}) + '\n\n').encode())
                    self.wfile.flush()
                    version = api.store.wait_state_version(version, api.closed)
            except OSError:
                pass
            finally:
                api.stream_slots.release()
                self.close_connection = True
        def _events(self, session_id, query):
            # Reuse precisely the history endpoint's host/origin/token boundary.
            status, result = api.dispatch('GET', '/api/sessions/' + session_id + '/events?' + query, dict(self.headers))
            if status != 200: return self._reply(status, json.dumps(result).encode())
            if not api.stream_slots.acquire(blocking=False):
                return self._reply(503, b'{"error":"Too many event streams"}')
            try:
                after = max(0, int(parse_qs(query).get('after', ['0'])[0]))
                self.connection.settimeout(10)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(b': connected\n\n'); self.wfile.flush()
                events = result['events']
                while not api.closed.is_set() and not api.store.closed:
                    if events:
                        # Keep each frame bounded even when history has many tool outputs.
                        batch, size = [], 0
                        for event in events:
                            size += len(json.dumps(event, ensure_ascii=False).encode())
                            if batch and size > 1048576: break
                            batch.append(event)
                        events = batch
                        after = events[-1]['seq']
                        frame = 'id: ' + str(after) + '\ndata: ' + json.dumps({'events': events}, ensure_ascii=False) + '\n\n'
                        self.wfile.write(frame.encode())
                    else: self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
                    events = api.store.wait_session_events(session_id, after, api.closed)
            except (OSError, Missing): pass
            finally:
                api.stream_slots.release()
                self.close_connection = True
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
    from .credential_broker import initialize
    initialize()
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
    commands=config.get("commands", {})
    try:
        if not isinstance(commands,dict): raise ValueError('commands must be an object')
        resolve_commands(commands)
    except ValueError as error: parser.error(str(error))
    command=config.get("quota_command",config.get("agentmeter_command"))
    if command is not None and (not isinstance(command,list) or not command or any(not isinstance(x,str) or not x or "\x00" in x for x in command)): parser.error("quota_command must be an argument list")
    data=Path(args.data_dir).expanduser(); data.mkdir(parents=True,exist_ok=True,mode=0o700); data.chmod(0o700)
    from .diagnostics import configure
    configure(data)
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
    runtime_config={"execution_enabled":args.enable_execution,"commands":commands,"base_url":"http://127.0.0.1:"+str(args.port),"python":sys.executable,"package_root":str(Path(__file__).resolve().parent.parent),"approval_timeout":config.get("approval_timeout",120),"run_timeout":config.get("run_timeout",900)}
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
    finally: api.close(); api.usage.close() if api.usage else None; runtime.close(); quota.close(); server.server_close(); store.close()

if __name__=="__main__": main()
