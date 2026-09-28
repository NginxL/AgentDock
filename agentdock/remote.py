"""SSH control plane with durable remote events and idempotent turn submission."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import selectors
import shlex
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from .providers import ProviderCancelled, ProviderError
from .processes import stop_group
from .store import Conflict, Forbidden


class TransportError(ProviderError):
    pass


# This fixed bootstrap receives data on stdin. Prompts, directories, and tokens
# are never interpolated into a shell command. No root, service or shell changes.
BOOTSTRAP = r'''
import base64,hashlib,io,json,os,pathlib,re,shutil,sys,tempfile,zipfile
os.umask(0o077)
try:
 raw=sys.stdin.buffer.read(2097153)
 if len(raw)>2097152: raise ValueError('size')
 request=json.loads(raw)
 digest=request['digest']
 if not re.fullmatch('[a-f0-9]{64}',digest): raise ValueError('digest')
 root=pathlib.Path.home()/'.local/share/agentdock/ssh/runtimes'
 target=root/digest
 if 'bundle' in request:
  content=base64.b64decode(request['bundle'],validate=True)
  if hashlib.sha256(content).hexdigest()!=digest: raise ValueError('digest mismatch')
  root.mkdir(parents=True,exist_ok=True,mode=0o700)
  if root.is_symlink() or target.is_symlink(): raise ValueError('directory')
  if not target.exists():
   temp=pathlib.Path(tempfile.mkdtemp(prefix='.install-',dir=root))
   try:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
     if sum(f.file_size for f in archive.infolist())>2097152: raise ValueError('size')
     for file in archive.infolist():
      if not re.fullmatch('agentdock/[a-z_]+[.]py',file.filename): raise ValueError('path')
      path=temp/file.filename; path.parent.mkdir(exist_ok=True,mode=0o700)
      path.write_bytes(archive.read(file)); path.chmod(0o600)
    try: os.rename(temp,target)
    except OSError:
     if not target.is_dir(): raise
   finally:
    if temp.exists(): shutil.rmtree(temp)
 if target.is_symlink() or not (target/'agentdock/ssh_worker.py').is_file(): raise ValueError('connect first')
 sys.path.insert(0,str(target))
 from agentdock.ssh_worker import rpc
 result={'ok':True,'value':rpc(request['request'])}
except Exception:
 result={'ok':False,'error':'Remote operation failed. Reconnect the environment and check the remote CLI.'}
print('AGENTDOCK_RESPONSE '+json.dumps(result,ensure_ascii=False))
'''


def bundle():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(__file__).parent.glob('*.py')):
            # Deterministic archive IDs across app launches and installs.
            info = zipfile.ZipInfo('agentdock/' + path.name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    data = output.getvalue()
    return hashlib.sha256(data).hexdigest(), base64.b64encode(data).decode()


class RemoteManager:
    def __init__(self, store, enabled=False, transport=None):
        self.store, self.enabled = store, enabled
        self.digest, self.bundle = bundle()
        self.transport = transport or self._ssh
        self.closed = threading.Event()
        self._connections = threading.Lock()

    def _ssh(self, environment, payload, stop=None):
        host, python = environment['ssh_host'], environment['python']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*', host): raise ProviderError('Invalid SSH destination.')
        command = shlex.quote(python) + ' -c ' + shlex.quote(BOOTSTRAP)
        argv = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
                '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
                '--', host, command]
        process = None
        selector = selectors.DefaultSelector()
        output, errors, writes = bytearray(), 0, bytearray(json.dumps(payload).encode())
        deadline = time.monotonic() + (5 if payload["request"].get("op") == "cancel" else 35)
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
            for stream, name, event in ((process.stdin, 'stdin', selectors.EVENT_WRITE),
                                        (process.stdout, 'stdout', selectors.EVENT_READ),
                                        (process.stderr, 'stderr', selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event, name)
            while selector.get_map():
                if self.closed.is_set() or (stop and stop.is_set()): raise ProviderCancelled()
                if time.monotonic() >= deadline: raise TransportError('SSH connection timed out.')
                for key, _ in selector.select(.1):
                    try:
                        if key.data == 'stdin':
                            count = os.write(key.fd, writes); del writes[:count]
                            if not writes: selector.unregister(key.fileobj); key.fileobj.close()
                            continue
                        chunk = os.read(key.fd, 65536)
                    except BlockingIOError: continue
                    if not chunk: selector.unregister(key.fileobj); continue
                    if key.data == 'stdout': output.extend(chunk)
                    else: errors += len(chunk)
                    if len(output) + errors > 2097152: raise TransportError('SSH response exceeded the limit.')
            process.wait(timeout=max(.1, deadline - time.monotonic()))
            if process.returncode: raise TransportError('SSH connection failed. Check the host, network and SSH authentication.')
            lines = [line for line in output.splitlines() if line.startswith(b'AGENTDOCK_RESPONSE ')]
            if len(lines) != 1: raise TransportError('The remote runner did not return a valid response.')
            return json.loads(lines[0][len(b'AGENTDOCK_RESPONSE '):])
        except (OSError, ValueError, subprocess.SubprocessError):
            raise TransportError('SSH connection failed. Check the host, network and SSH authentication.') from None
        finally:
            selector.close()
            if process:
                stop_group(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream: stream.close()

    def rpc(self, environment_id, request, *, install=False, stop=None):
        if not self.enabled or self.closed.is_set(): raise Forbidden('Remote execution is disabled.')
        environment = self.store.get_environment(environment_id)
        if environment['kind'] != 'ssh': raise ValueError('Select an SSH environment')
        payload = {'digest': self.digest, 'request': request}
        if install: payload['bundle'] = self.bundle
        response = self.transport(environment, payload, stop)
        if not isinstance(response, dict) or not response.get('ok'):
            raise ProviderError('Remote operation failed. Reconnect the environment and check the remote CLI.')
        return response['value']

    def connect(self, environment_id):
        if not self.enabled: raise Forbidden('Remote execution is disabled.')
        if self.store.get_environment(environment_id)['kind'] != 'ssh': raise ValueError('Select an SSH environment')
        with self._connections:
            self.store.update_environment_status(environment_id, 'connecting')
            try:
                result = self.rpc(environment_id, {'op': 'probe'}, install=True)
                return self.store.update_environment_status(environment_id, 'connected', {**result, 'digest': self.digest})
            except Exception:
                self.store.update_environment_status(environment_id, 'error')
                raise Conflict('SSH connection failed. Check SSH access, Python 3.9+ and the installed CLIs.') from None

    def check(self, agent):
        environment = self.store.get_environment(agent['environment_id'])
        if environment['payload'].get('digest') != self.digest:
            raise Conflict('Connect this SSH environment before starting an agent.')
        if not environment['payload'].get('providers', {}).get(agent['provider'], {}).get('available'):
            raise Conflict('The selected native CLI was not found on this environment.')

    def models(self, environment_id, provider):
        self.check({'environment_id': environment_id, 'provider': provider})
        return self.rpc(environment_id, {'op': 'models', 'provider': provider})

    def run(self, environment_id, run_id, spec, stop, emit, bind, approve, tool):
        identity = {'controller': self.store.controller_id, 'run_id': run_id}
        cursor, disconnected = 0, None
        pending, completed = {}, {}
        guard = threading.Lock()

        def respond(event):
            p = event['payload']; identifier = p['request_id']
            try:
                if event['kind'] == 'remote_bind': value = bind(p['native_id'])
                elif event['kind'] == 'remote_approval': value = approve(p['request'], p['options'])
                else: value = tool(p['name'], p['arguments'])
                answer = {'ok': True, 'value': value}
            except Exception: answer = {'ok': False}
            with guard: completed[identifier] = answer

        def call(request):
            return self.rpc(environment_id, {**identity, **request}, stop=stop)

        started = False
        try:
            while not stop.is_set() and not self.closed.is_set():
                try:
                    if not started:
                        call({'op': 'start', 'spec': spec})
                        started = True
                    value = call({'op': 'poll', 'after': cursor})
                    if disconnected is not None:
                        emit('transport_status', {'status': 'connected'})
                        disconnected = None
                    self.store.update_environment_status(environment_id, 'connected')
                    for event in value['events']:
                        if event['seq'] <= cursor: continue
                        if event['seq'] != cursor + 1: raise ProviderError('The remote event sequence has a gap.')
                        if event['kind'] in ('remote_bind', 'remote_approval', 'remote_tool'):
                            identifier = event['payload']['request_id']
                            if identifier not in pending:
                                pending[identifier] = threading.Thread(target=respond, args=(event,), daemon=True)
                                pending[identifier].start()
                        else:
                            emit(event['kind'], event['payload'])
                        cursor = event['seq']
                    with guard: answers = list(completed.items())
                    for identifier, response in answers:
                        call({'op': 'respond', 'request_id': identifier, 'response': response})
                        with guard: completed.pop(identifier, None)
                    state = value['state']
                    if state['status'] not in ('running', 'starting') and cursor >= state.get('last_seq', 0):
                        if state['status'] == 'completed': return state['result']
                        if state['status'] == 'cancelled': raise ProviderCancelled()
                        raise ProviderError(state.get('error') or 'The remote agent failed.')
                    if len(value['events']) < 100: stop.wait(.4)
                except TransportError:
                    if disconnected is None:
                        disconnected = time.monotonic()
                        emit('transport_status', {'status': 'reconnecting'})
                        self.store.update_environment_status(environment_id, 'reconnecting')
                    if time.monotonic() - disconnected > 45:
                        self.store.update_environment_status(environment_id, 'disconnected')
                        raise ProviderError('SSH remained disconnected. The remote task will stop when its 90-second lease expires.') from None
                    stop.wait(1)
            raise ProviderCancelled()
        finally:
            # No local credentials or HTTP listener are exposed to the SSH host.
            # If SSH cannot deliver cancellation, the remote lease stops its children.
            try: self.rpc(environment_id, {**identity, 'op': 'cancel'})
            except Exception: pass

    def close(self):
        self.closed.set()
