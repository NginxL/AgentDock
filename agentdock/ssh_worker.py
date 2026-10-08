"""Private SSH runner. Only this controller's runs live here; CLI settings stay native."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .providers import execute, ProviderError, ProviderCancelled
from .session_storage import session_directory, remove_session_directory

ROOT = Path.home() / '.local/share/agentdock/ssh'
LEASE_SECONDS = 90
MAX_JSON = 2 * 1024 * 1024


def atomic(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def read(path, default=None):
    try:
        if path.stat().st_size > MAX_JSON: raise ValueError('File exceeds limit')
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def private(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir(): raise ValueError('Invalid runner directory')
    path.chmod(0o700)
    return path


def run_path(controller, run_id):
    for value in (controller, run_id):
        if str(uuid.UUID(value)) != value: raise ValueError('Invalid run identity')
    return private(private(ROOT / 'controllers') / controller) / run_id


def commands():
    from .registry import commands as discover
    return discover(read(ROOT/'commands.json', {}))


def probe():
    from .registry import availability
    providers = availability(commands())
    return {'python': '.'.join(map(str, sys.version_info[:3])), 'providers': providers,
            'protocol': 1, 'runtime': 'ssh', 'lease_seconds': LEASE_SECONDS}


def quota(provider, stop=None):
    # Linux Claude Code has no documented quota snapshot. Do not read its credentials.
    if provider != 'codex':
        return {'provider': provider, 'error_code': 'unavailable'}
    from datetime import datetime, timezone
    from .providers import _Pipe, _Codex, _Callbacks
    command = commands().get(provider)
    if not command: return {'provider': provider, 'error_code': 'not_installed'}
    pipe = _Pipe(command + ['--listen', 'stdio://'], str(Path.home()), dict(os.environ),
                 stop if stop is not None else threading.Event(), 25)
    try:
        adapter = _Codex(pipe, _Callbacks(pipe, lambda *a: None, lambda *a: None, lambda *a: None, {}))
        adapter.request('initialize', {'clientInfo': {'name': 'agentdock', 'version': '0.3.0'}})
        pipe.send({'method': 'initialized', 'params': {}})
        response = adapter.request('account/rateLimits/read', {})
        rate = response.get('rateLimits', {})
        buckets = response.get('rateLimitsByLimitId')
        if isinstance(buckets, dict) and buckets:
            rate = buckets.get('codex', next(iter(buckets.values())))
        windows = []
        for name in ('primary', 'secondary'):
            value = rate.get(name)
            if not isinstance(value, dict): continue
            duration = value.get('windowDurationMins')
            reset = value.get('resetsAt')
            windows.append({'title': str(duration) + 'm' if duration else name,
                'usedPercent': value.get('usedPercent'),
                'resetsAt': datetime.fromtimestamp(reset, timezone.utc).isoformat() if isinstance(reset, (int, float)) else None})
        return {'provider': provider, 'fetchedAt': datetime.now(timezone.utc).isoformat(),
                'plan': rate.get('planType'), 'windows': windows}
    finally:
        pipe.close()


def rpc(request, *, stop=None, catalog=None):
    if stop is not None and stop.is_set(): raise ProviderCancelled()
    operation = request.get('op')
    if operation == 'probe': return probe()
    if operation == 'directories':
        from .directories import list_directories
        return list_directories(request.get('path', '~'))
    if operation == 'models':
        from .catalog import Catalog
        catalog = catalog if catalog is not None else Catalog({'execution_enabled': True, 'commands': commands()}, stop=stop)
        if request.get('account'):
            manager, account = account_manager(request, stop=stop)
            with manager.lease(account):
                return catalog.read(
                    request['provider'], account_id=account['id'], generation=account.get('generation', 0),
                    environment=manager.environment(account))
        return catalog.read(request['provider'])
    if operation == 'account':
        manager, account = account_manager(request, stop=stop)
        action = request.get('action')
        if action not in ('start', 'status', 'cancel', 'submit', 'check', 'refresh', 'remove'):
            raise ValueError('Invalid account operation')
        if action == 'start': return manager.start(account, request.get('method', 'browser'))
        if action == 'submit': return manager.submit(account, request.get('code'))
        return getattr(manager, action)(account)
    if operation == 'quota': return quota(request['provider'], stop=stop)
    if operation=='task_workspace':
        from .task_workspace import prepare
        parent=run_path(request['controller'],request['task_id']).parent
        return prepare(parent/'tasks',request['task_id'],request['agent_id'],request['source'])
    if operation=='recovery_status':
        from .execution_lease import assert_idle
        from .store import Conflict
        parent=run_path(request['controller'],request['session_id']).parent
        idle=True
        for identifier in request.get('run_ids',[]):
            item=run_path(request['controller'],identifier)
            if not item.exists(): continue
            saved=read(item/'request.json',{}).get('spec',{})
            if saved.get('session_id')!=request['session_id']: raise ValueError('Recovery run belongs to another session')
            (item/'cancel').touch(mode=0o600)
            with (item/'worker.lock').open('a') as lock:
                try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError: idle=False
        try: assert_idle(parent/'sessions'/request['session_id'])
        except Conflict: idle=False
        return {'idle':idle}
    if operation == 'delete_session':
        from .accounts import AccountManager
        parent = run_path(request['controller'], request['session_id']).parent
        accounts = request.get('accounts', [])
        if not isinstance(accounts, list) or any(not isinstance(account, dict)
                or account.get('provider') != request.get('provider') for account in accounts):
            raise ValueError('Invalid session accounts')
        run_paths = [run_path(request['controller'], identifier) for identifier in request['run_ids']]
        for item in run_paths:
            saved = read(item/'request.json', {}).get('spec', {})
            if saved and (saved.get('session_id') not in (None, request['session_id'])
                    or saved.get('session_id') is None and saved.get('native_session_id') not in (None, request.get('native_session_id'))):
                raise ValueError('Remote run belongs to another session')
            state = read(item/'state.json', {})
            if state.get('status') in ('starting','running') and time.time()-state.get('updated_at',0) < LEASE_SECONDS:
                raise ValueError('Remote session is still running')
        with AccountManager(parent/'accounts', stop=stop).session_cleanup(accounts):
            if not request.get('managed_account') and request.get('provider') == 'codex' and request.get('native_session_id'):
                from .codex_home import retire_legacy
                retire_legacy(commands()['codex'], dict(os.environ), request['native_session_id'], stop=stop)
            elif not request.get('managed_account') and request.get('provider') == 'claude' and request.get('native_session_id'):
                from .session_storage import retire_legacy_claude
                retire_legacy_claude(dict(os.environ), request['native_session_id'])
            remove_session_directory(parent/'sessions', request['session_id'])
            for item in run_paths:
                if item.exists(): shutil.rmtree(item)
        return {'ok': True}
    path = run_path(request['controller'], request['run_id'])
    if operation == 'start':
        private(path)
        # The persisted request is the idempotency record. Never replay a completed run.
        encoded = json.dumps(request['spec'], sort_keys=True, separators=(',', ':')).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        with (path / 'start.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            old = read(path / 'request.json')
            if old:
                if old['fingerprint'] != fingerprint: raise ValueError('Run identity conflict')
                return {'accepted': True}
            (path / 'lease').touch(mode=0o600)
            atomic(path / 'request.json', {'spec': request['spec'], 'fingerprint': fingerprint})
            atomic(path / 'state.json', {'status': 'starting', 'updated_at': time.time()})
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            subprocess.Popen([sys.executable, '-m', 'agentdock.ssh_worker', '--run', str(path)],
                             cwd=str(Path.home()), env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {'accepted': True}
    if not path.is_dir(): raise ValueError('Remote run does not exist')
    if operation=='steer':
        item=request['input']
        if (not isinstance(item,dict) or set(item)!={'id','body','turn_id'}
                or str(uuid.UUID(item['id']))!=item['id'] or not isinstance(item['body'],str)
                or not item['body'].strip() or len(item['body'])>24000
                or not isinstance(item['turn_id'],str) or len(item['turn_id'])>256): raise ValueError('Invalid adjustment')
        directory=private(path/'inputs')
        target=directory/(item['id']+'.json')
        with (directory/'input.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            old=read(target)
            if old is not None and old!=item: raise ValueError('Adjustment identity conflict')
            if old is None: atomic(target,item)
        return {'accepted':True}
    if operation == 'poll':
        (path / 'lease').touch(mode=0o600)
        after = request.get('after', 0)
        if not isinstance(after, int) or after < 0: raise ValueError('Invalid cursor')
        events, size = [], 0
        try:
            with (path / 'events.jsonl').open() as src:
                for line in src:
                    if not line.endswith('\n'): break
                    event = json.loads(line)
                    if event['seq'] <= after: continue
                    events.append(event); size += len(line)
                    if len(events) >= 100 or size > 400000: break
        except FileNotFoundError: pass
        state = read(path / 'state.json', {'status': 'starting', 'updated_at': time.time()})
        # A hard-killed worker cannot leave a permanently running task in the UI.
        if state['status'] in ('starting', 'running') and time.time() - state['updated_at'] > 20:
            state = {'status': 'failed', 'error': 'Remote worker stopped unexpectedly.'}
        return {'events': events, 'state': state}
    if operation == 'respond':
        identifier = request['request_id']
        if not re.fullmatch(r'[a-f0-9]{32}', identifier): raise ValueError('Invalid request identity')
        private(path / 'responses')
        atomic(path / 'responses' / (identifier + '.json'), request['response'])
        return {'ok': True}
    if operation == 'cancel':
        (path / 'cancel').touch(mode=0o600)
        return {'ok': True}
    raise ValueError('Unknown operation')


def account_manager(request, *, stop=None):
    from .accounts import AccountManager
    account = request['account']
    if not isinstance(account, dict) or account.get('provider') not in ('codex', 'claude'):
        raise ValueError('Invalid account profile')
    if request.get('provider', account['provider']) != account['provider']:
        raise ValueError('Account service mismatch')
    if 'generation' in account and (type(account['generation']) is not int or not 0 <= account['generation'] < 2**63):
        raise ValueError('Invalid account login generation')
    parent = run_path(request['controller'], account['id']).parent
    return AccountManager(parent / 'accounts', commands(), stop=stop), account


def work(path):
    stop = threading.Event()
    event_lock = threading.Lock()
    sequence, total = 0, 0
    truncated = False
    spec = read(path / 'request.json')['spec']
    if (path/'cancel').exists() or time.time()-(path/'lease').stat().st_mtime>LEASE_SECONDS:
        atomic(path/'state.json',{'status':'cancelled','last_seq':0,'updated_at':time.time()})
        return
    active = True
    token = secrets.token_urlsafe(32)

    def emit(kind, payload):
        nonlocal sequence, total, truncated
        with event_lock:
            encoded = json.dumps(payload, ensure_ascii=False).replace(token, '[redacted]')
            size = len(encoded.encode())
            essential = kind.startswith('remote_') or kind in ('usage', 'input_receipt') or (
                kind == 'agent_message' and payload.get('phase') == 'final_answer')
            if not essential and (size > 300000 or total + size > 8 * 1024 * 1024 or sequence >= 5000):
                if truncated: return
                truncated = True
                kind = 'output_truncated'
                encoded = json.dumps({'text': 'Progress display limit reached; the task continues.'})
            total += len(encoded.encode())
            sequence += 1
            with (path / 'events.jsonl').open('a') as output:
                output.write(json.dumps({'seq': sequence, 'kind': kind, 'payload': json.loads(encoded)}, ensure_ascii=False) + '\n')
                output.flush()
                if kind.startswith('remote_'): os.fsync(output.fileno())

    def control(kind, payload):
        identifier = uuid.uuid4().hex
        emit(kind, {**payload, 'request_id': identifier})
        deadline = time.monotonic() + 125
        while not stop.wait(0.05):
            response = read(path / 'responses' / (identifier + '.json'))
            if response is not None:
                if not response.get('ok'): raise ProviderError('Remote control request was rejected.')
                return response.get('value')
            if time.monotonic() >= deadline: raise ProviderError('Remote control request expired.')
        raise ProviderCancelled()

    class BridgeHandler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            try:
                if self.path != '/mcp/tool' or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                    raise ValueError('Invalid capability')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 262144: raise ValueError('Invalid request size')
                self.connection.settimeout(10)
                data = json.loads(self.rfile.read(length))
                response = control('remote_tool', {'name': data.get('name'), 'arguments': data.get('arguments', {})})
                body = json.dumps(response).encode(); status = 200
            except Exception:
                body, status = b'{"error":"Tool unavailable"}', 403
            try:
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            except OSError: pass

    def monitor():
        heartbeat = 0
        try:
            while active and not stop.wait(0.2):
                if (path / 'cancel').exists() or time.time() - (path / 'lease').stat().st_mtime > LEASE_SECONDS:
                    stop.set()
                if time.monotonic() - heartbeat > 2:
                    atomic(path / 'state.json', {'status': 'running', 'updated_at': time.time()})
                    heartbeat = time.monotonic()
        except OSError:
            stop.set()  # Never continue a task whose lease or status cannot be tracked.

    server = ThreadingHTTPServer(('127.0.0.1', 0), BridgeHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    watcher = threading.Thread(target=monitor, daemon=True); watcher.start()
    state = {'status': 'failed', 'error': 'Remote native CLI failed.'}
    try:
        cwd = spec['cwd']
        home = session_directory(path.parent/'sessions', spec.get('session_id', path.name))
        expected = '~/.local/share/agentdock/ssh/controllers/' + path.parent.name + '/sessions/' + home.name + '/workspace'
        if cwd == expected:
            destination = home/'workspace'
            if not destination.exists():
                legacy = spec.get('legacy_workspace')
                if legacy and legacy.startswith('~/.local/share/agentdock/workspaces/'):
                    source = Path(legacy).expanduser()
                    if source.is_dir():
                        private(home)
                        shutil.copytree(source, destination, symlinks=True)
            cwd = str(private(destination))
        # Only auto-create AgentDock-owned workspaces; explicit user paths must already exist.
        if cwd.startswith('~/.local/share/agentdock/workspaces/'):
            identifier = cwd.rsplit('/', 1)[-1]
            if str(uuid.UUID(identifier)) != identifier: raise ValueError('Invalid workspace')
            cwd = str(private(Path.home() / '.local/share/agentdock/workspaces' / identifier))
        if not Path(cwd).is_absolute() or not Path(cwd).is_dir():
            raise ProviderError('The remote working directory does not exist.')
        command = commands().get(spec['provider'])
        if not command: raise ProviderError('The remote native CLI was not found.')
        mcp = {'command': sys.executable, 'args': ['-m', 'agentdock.mcp'], 'env': {
            'PYTHONPATH': str(Path(__file__).resolve().parent.parent),
            'AGENTDOCK_URL': 'http://127.0.0.1:' + str(server.server_address[1]),
            'AGENTDOCK_CAPABILITY': token}}
        branch = spec.get('account_branch', 0)
        if not isinstance(branch, int) or isinstance(branch, bool) or not 0 <= branch <= 1000000:
            raise ValueError('Invalid account branch')
        if branch: home = home / 'branches' / str(branch)
        managed = bool(spec.get('account'))
        lease = nullcontext(None)
        if managed:
            manager, account = account_manager({'controller': path.parent.name,
                'account': spec['account'], 'provider': spec['provider']})
            lease = manager.credential_session(account, str(home), stop=stop)
        with lease as account_env:
            from .input_control import InputControl
            class RemoteInput(InputControl):
                def take(self):
                    pending=[]
                    for file in sorted((path/'inputs').glob('*.json')):
                        item=read(file)
                        if item['id'] in self.seen: continue
                        self.seen.add(item['id']); pending.append(item)
                    return pending
            result = execute(spec['provider'], command, cwd, spec['prompt'], spec.get('native_session_id'), mcp, stop,
                emit, lambda native_id: control('remote_bind', {'native_id': native_id}),
                lambda request, options: control('remote_approval', {'request': request, 'options': options}),
                timeout=spec.get('timeout', 900), model=spec.get('model'), effort=spec.get('effort'),
                permission_mode=spec.get('permission_mode', 'ask'), session_home=str(home),
                control=RemoteInput(),
                **({'base_environment': account_env, 'managed_account': True} if managed else {}))
        state = {'status': 'completed', 'result': result}
    except ProviderCancelled:
        state = {'status': 'cancelled'}
    except ProviderError as error:
        state = {'status': 'failed', 'error': str(error)[:500], 'error_code': error.code,
                 'retry_after': error.retry_after, 'rejected': error.rejected}
    except Exception:
        pass
    finally:
        active = False; stop.set(); watcher.join(timeout=2)
        server.shutdown(); server.server_close()
        atomic(path / 'state.json', {**state, 'last_seq': sequence, 'updated_at': time.time()})


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    if args.run:
        with (args.run / 'worker.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            work(args.run)
        return
    try:
        line = sys.stdin.buffer.read(MAX_JSON + 1)
        if len(line) > MAX_JSON: raise ValueError('Request exceeds limit')
        result = {'ok': True, 'value': rpc(json.loads(line))}
    except Exception:
        result = {'ok': False, 'error': 'Remote operation failed. Check SSH, CLI login and the selected directory.'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
