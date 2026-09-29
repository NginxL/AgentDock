"""Multiplex bounded JSON frames over one app-owned SSH process per device."""
import json
import os
import queue
import selectors
import subprocess
import threading
import time
import uuid

from .processes import stop_group
from .providers import ProviderCancelled, ProviderError

PREFIX = b'AGENTDOCK_FRAME '
MAX_FRAME = 2097152


class TransportError(ProviderError):
    pass


class Subscription:
    def __init__(self, channel, identifier, streaming=False):
        self.channel, self.identifier = channel, identifier
        self.frames = queue.Queue(32)
        self.streaming, self.last_frame = streaming, time.monotonic()

    def next(self, stop=None, timeout=.05):
        if stop and stop.is_set(): raise ProviderCancelled()
        try: frame = self.frames.get(timeout=timeout)
        except queue.Empty:
            if self.channel.closed.is_set(): raise TransportError('SSH connection interrupted.')
            if self.streaming and time.monotonic() - self.last_frame > 15:
                self.channel.close()
                raise TransportError('SSH event stream timed out.')
            return None
        self.last_frame = time.monotonic()
        if not frame.get('ok'): raise ProviderError('Remote operation failed. Reconnect and check the remote CLI.')
        return frame['value']

    def close(self):
        self.channel.forget(self.identifier)
        try: self.channel.send({'op': 'unsubscribe', 'id': self.identifier})
        except TransportError: pass


class Channel:
    def __init__(self, argv, bootstrap, *, env=None, cwd=None):
        self.closed = threading.Event()
        self.guard = threading.Lock()
        self.pending = {}
        self.outgoing = queue.Queue(64)
        self.last_activity = time.monotonic()
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, start_new_session=True, env=env, cwd=cwd)
        self.ready = Subscription(self, 'ready')
        self.pending['ready'] = self.ready
        self.outgoing.put(self.encode({**bootstrap, 'stream': True}))
        self.thread = threading.Thread(target=self._io, daemon=True, name='agentdock-ssh')
        self.thread.start()

    @staticmethod
    def encode(value):
        line = json.dumps(value, ensure_ascii=False).encode() + b'\n'
        if len(line) > MAX_FRAME: raise TransportError('SSH request exceeded the limit.')
        return line

    def send(self, value):
        if self.closed.is_set(): raise TransportError('SSH connection interrupted.')
        try: self.outgoing.put_nowait(self.encode(value))
        except queue.Full:
            self.closed.set()
            raise TransportError('SSH output queue exceeded the limit.') from None
        self.last_activity = time.monotonic()

    def forget(self, identifier):
        with self.guard: self.pending.pop(identifier, None)

    def wait_ready(self, stop=None):
        deadline = time.monotonic() + 35
        # Ready is shared by concurrent callers; leave the acknowledged state set.
        while not getattr(self, '_ready', False):
            value = self.ready.next(stop)
            if value is not None:
                self._ready = True
                self.forget('ready')
                return
            if time.monotonic() >= deadline: raise TransportError('SSH connection timed out.')

    def subscribe(self, request, stop=None):
        self.wait_ready(stop)
        identifier = uuid.uuid4().hex
        subscription = Subscription(self, identifier, request.get('op') == 'watch')
        with self.guard:
            if len(self.pending) >= 64: raise TransportError('Too many pending SSH requests.')
            self.pending[identifier] = subscription
        try: self.send({'id': identifier, 'request': request})
        except Exception:
            self.forget(identifier)
            raise
        return subscription

    def request(self, request, stop=None):
        subscription = self.subscribe(request, stop)
        deadline = time.monotonic() + (5 if request.get('op') == 'cancel' else 35)
        try:
            while True:
                value = subscription.next(stop)
                if value is not None: return {'ok': True, 'value': value}
                if time.monotonic() >= deadline: raise TransportError('SSH request timed out.')
        finally: self.forget(subscription.identifier)

    def _io(self):
        selector = selectors.DefaultSelector()
        output, writes, noise = bytearray(), bytearray(), 0
        try:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                os.set_blocking(stream.fileno(), False)
            selector.register(self.process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(self.process.stderr, selectors.EVENT_READ, 'stderr')
            registered = False
            while not self.closed.is_set():
                if not writes:
                    try: writes.extend(self.outgoing.get_nowait())
                    except queue.Empty: pass
                if writes and not registered:
                    selector.register(self.process.stdin, selectors.EVENT_WRITE, 'stdin'); registered = True
                if not writes and registered:
                    selector.unregister(self.process.stdin); registered = False
                for key, _ in selector.select(.01):
                    try:
                        if key.data == 'stdin':
                            count = os.write(key.fd, writes); del writes[:count]
                            continue
                        chunk = os.read(key.fd, 65536)
                    except BlockingIOError: continue
                    if not chunk:
                        if key.data == 'stdout': return
                        selector.unregister(key.fileobj); continue
                    if key.data == 'stderr':
                        noise += len(chunk)
                    else:
                        output.extend(chunk)
                        while b'\n' in output:
                            line, _, remaining = output.partition(b'\n'); output = bytearray(remaining)
                            if len(line) > MAX_FRAME: raise ValueError('frame size')
                            if not line.startswith(PREFIX):
                                noise += len(line); continue  # SSH login banners are not protocol frames.
                            frame = json.loads(line[len(PREFIX):])
                            with self.guard: target = self.pending.get(frame.get('id'))
                            if target: target.frames.put_nowait(frame)
                        if len(output) > MAX_FRAME: raise ValueError('frame size')
                    if noise > MAX_FRAME: raise ValueError('excessive diagnostic output')
                with self.guard: busy = bool(self.pending)
                if not busy and time.monotonic() - self.last_activity > 300: return
        except (OSError, ValueError, TypeError, AttributeError, queue.Full):
            pass  # Never expose stderr, native configuration or remote payloads.
        finally:
            self.closed.set()
            selector.close()
            self.process.stdin.close()
            try: self.process.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
            stop_group(self.process)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr): stream.close()

    def close(self):
        self.closed.set()
        if threading.current_thread() is not self.thread: self.thread.join(3)
