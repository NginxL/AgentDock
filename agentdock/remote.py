"""SSH control plane with durable remote events and idempotent turn submission."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shlex
import threading
import time
import zipfile
from pathlib import Path

from .providers import ProviderCancelled, ProviderError
from .ssh_transport import Channel, TransportError
from .store import Conflict, Forbidden


# This fixed bootstrap receives data on stdin. Prompts, directories, and tokens
# are never interpolated into a shell command. No root, service or shell changes.
BOOTSTRAP = r'''
import base64,hashlib,io,json,os,pathlib,re,shutil,sys,tempfile,zipfile
os.umask(0o077)
try:
 raw=sys.stdin.buffer.readline(2097153)
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
 if request.get('stream'):
  from agentdock.ssh_bridge import serve
  serve()
  sys.exit(0)
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
    def __init__(self, store, enabled=False, transport=None, channel_factory=None):
        self.store, self.enabled = store, enabled
        self.digest, self.bundle = bundle()
        self.transport = transport or self._ssh
        self.streaming = transport is None
        self.channel_factory = channel_factory or Channel
        self._channel_guard = threading.Lock()
        self._channels = {}
        self.closed = threading.Event()
        self._connections = threading.Lock()
        self._model_guard = threading.Lock()
        self._model_locks, self._model_cache, self._model_generations = {}, {}, {}

    def _channel(self, environment, payload):
        host, python = environment['ssh_host'], environment['python']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*', host): raise ProviderError('Invalid SSH destination.')
        command = shlex.quote(python) + ' -c ' + shlex.quote(BOOTSTRAP)
        argv = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
                '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
                '--', host, command]
        key = (environment['id'], host, python)
        with self._channel_guard:
            if self.closed.is_set(): raise ProviderCancelled()
            channel = self._channels.get(key)
            if channel is None or channel.closed.is_set():
                if channel: channel.close()
                try: channel = self.channel_factory(argv, payload)
                except OSError: raise TransportError('Could not start SSH.') from None
                self._channels[key] = channel
            return channel

    def _ssh(self, environment, payload, stop=None):
        return self._channel(environment, payload).request(payload['request'], stop)

    def _watch(self, environment_id, request, stop):
        environment = self.store.get_environment(environment_id)
        channel = self._channel(environment, {'digest': self.digest})
        return channel.subscribe({**request, 'op': 'watch'}, stop)

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
            with self._model_guard:
                self._model_generations[environment_id] = self._model_generations.get(environment_id, 0) + 1
                for key in list(self._model_cache):
                    if key[0] == environment_id: self._model_cache.pop(key)
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
        if not self.enabled or self.closed.is_set(): raise Forbidden('Remote execution is disabled.')
        self.check({'environment_id': environment_id, 'provider': provider})
        key = (environment_id, provider)
        with self._model_guard:
            lock = self._model_locks.setdefault(key, threading.Lock())
        # Cache only public model metadata, scoped to device and provider.
        with lock:
            if not self.enabled or self.closed.is_set(): raise Forbidden('Remote execution is disabled.')
            self.check({'environment_id': environment_id, 'provider': provider})
            with self._model_guard:
                generation = self._model_generations.get(environment_id, 0)
                cached = self._model_cache.get(key)
                if cached and time.monotonic() - cached[0] < 300: return cached[1]
            value = self.rpc(environment_id, {'op': 'models', 'provider': provider})
            with self._model_guard:
                if not self.closed.is_set() and generation == self._model_generations.get(environment_id, 0):
                    self._model_cache[key] = (time.monotonic(), value)
            return value

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

        started, subscription = False, None
        try:
            while not stop.is_set() and not self.closed.is_set():
                try:
                    if not started:
                        call({'op': 'start', 'spec': spec})
                        started = True
                    if self.streaming:
                        if subscription is None:
                            subscription = self._watch(environment_id, {**identity, 'after': cursor}, stop)
                        value = subscription.next(stop)
                    else:
                        value = call({'op': 'poll', 'after': cursor})
                    with guard: answers = list(completed.items())
                    for identifier, response in answers:
                        call({'op': 'respond', 'request_id': identifier, 'response': response})
                        with guard: completed.pop(identifier, None)
                    if value is None: continue
                    if cursor == 0 or disconnected is not None:
                        self.store.update_environment_status(environment_id, 'connected')
                    if disconnected is not None:
                        emit('transport_status', {'status': 'connected'})
                        disconnected = None
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
                    state = value['state']
                    if state['status'] not in ('running', 'starting') and cursor >= state.get('last_seq', 0):
                        if state['status'] == 'completed': return state['result']
                        if state['status'] == 'cancelled': raise ProviderCancelled()
                        raise ProviderError(state.get('error') or 'The remote agent failed.')
                    if not self.streaming and len(value['events']) < 100: stop.wait(.4)
                except TransportError:
                    if subscription:
                        subscription.close(); subscription = None
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
            if subscription: subscription.close()
            # No local credentials or HTTP listener are exposed to the SSH host.
            # If SSH cannot deliver cancellation, the remote lease stops its children.
            try: self.rpc(environment_id, {**identity, 'op': 'cancel'})
            except Exception: pass

    def close(self):
        self.closed.set()
        with self._channel_guard:
            channels = list(self._channels.values()); self._channels.clear()
        for channel in channels: channel.close()
        with self._model_guard: self._model_cache.clear()
