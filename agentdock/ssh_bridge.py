"""Private SSH stdio bridge; run workers and durable event logs outlive the channel."""
import json
import queue
import re
import signal
import sys
import threading
import time

from .ssh_worker import rpc, run_path, read, commands
from .catalog import Catalog

MAX_FRAME = 2097152


class EventReader:
    """Read only new complete records; reconnect can replay from a durable cursor."""
    def __init__(self, path, after):
        if type(after) is not int or after < 0: raise ValueError('Invalid cursor')
        self.path, self.after, self.offset = path, after, 0
        self.lease_at = 0

    def poll(self):
        if time.monotonic() - self.lease_at >= 2:
            (self.path / 'lease').touch(mode=0o600)
            self.lease_at = time.monotonic()
        events, size = [], 0
        try:
            with (self.path / 'events.jsonl').open('rb') as src:
                src.seek(self.offset)
                while True:
                    line = src.readline(MAX_FRAME + 1)
                    if not line: break
                    if len(line) > MAX_FRAME: raise ValueError('Event too large')
                    if not line.endswith(b'\n'): break
                    self.offset = src.tell()
                    event = json.loads(line)
                    if event['seq'] <= self.after: continue
                    events.append(event); size += len(line)
                    self.after = event['seq']
                    if len(events) >= 100 or size > 400000: break
        except FileNotFoundError: pass
        state = read(self.path / 'state.json', {'status': 'starting', 'updated_at': time.time()})
        if state['status'] in ('starting', 'running') and time.time() - state['updated_at'] > 20:
            state = {'status': 'failed', 'error': 'Remote worker stopped unexpectedly.'}
        return {'events': events, 'state': state}


def serve():
    stop, guard = threading.Event(), threading.Lock()
    outgoing, watchers = queue.Queue(64), {}
    capacity = threading.BoundedSemaphore(8)
    catalog = Catalog({'execution_enabled': True, 'commands': commands()})
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    def send(identifier, value=None, ok=True):
        frame = {'id': identifier, 'ok': ok, 'value': value}
        line = 'AGENTDOCK_FRAME ' + json.dumps(frame, ensure_ascii=False) + '\n'
        if len(line.encode()) > MAX_FRAME: raise ValueError('Frame too large')
        while not stop.is_set():
            try: outgoing.put(line, timeout=.1); return
            except queue.Full: continue

    def writer():
        try:
            while not stop.is_set():
                try: line = outgoing.get(timeout=.1)
                except queue.Empty: continue
                sys.stdout.write(line); sys.stdout.flush()
        except (OSError, ValueError): stop.set()

    def watch(identifier, request, cancelled):
        try:
            path = run_path(request['controller'], request['run_id'])
            if not path.is_dir(): raise ValueError('Run does not exist')
            reader = EventReader(path, request.get('after', 0))
            last, previous = 0, None
            while not stop.is_set() and not cancelled.is_set():
                value = reader.poll()
                terminal = value['state']['status'] not in ('starting', 'running')
                if value['events'] or value['state'] != previous or time.monotonic() - last >= 2:
                    send(identifier, value)
                    last, previous = time.monotonic(), value['state']
                if terminal and reader.after >= value['state'].get('last_seq', 0): return
                if len(value['events']) < 100: cancelled.wait(.03)
        except Exception: send(identifier, ok=False)
        finally:
            with guard: watchers.pop(identifier, None)

    def perform(identifier, request):
        try:
            if request.get('op') == 'probe': catalog.invalidate()
            value = catalog.read(request['provider']) if request.get('op') == 'models' and not request.get('account') else rpc(request)
            send(identifier, value)
        except Exception: send(identifier, ok=False)
        finally: capacity.release()

    def reader():
        try:
            while not stop.is_set():
                line = sys.stdin.buffer.readline(MAX_FRAME + 1)
                if not line: return
                if len(line) > MAX_FRAME or not line.endswith(b'\n'): raise ValueError('Invalid frame')
                frame = json.loads(line)
                identifier = frame.get('id', '')
                if not re.fullmatch('[a-f0-9]{32}', identifier): raise ValueError('Invalid request ID')
                if frame.get('op') == 'unsubscribe':
                    with guard:
                        if identifier in watchers: watchers[identifier].set()
                    continue
                request = frame['request']
                if request.get('op') == 'watch':
                    with guard:
                        if len(watchers) >= 32 or identifier in watchers:
                            send(identifier, ok=False); continue
                        cancelled = threading.Event(); watchers[identifier] = cancelled
                    threading.Thread(target=watch, args=(identifier, request, cancelled), daemon=True).start()
                elif request.get('op') in ('respond', 'cancel'):
                    # Fast control operations never wait behind model discovery.
                    try: send(identifier, rpc(request))
                    except Exception: send(identifier, ok=False)
                elif capacity.acquire(blocking=False):
                    threading.Thread(target=perform, args=(identifier, request), daemon=True).start()
                else: send(identifier, ok=False)
        except Exception: pass
        finally: stop.set()

    threading.Thread(target=writer, daemon=True).start()
    send('ready', {'protocol': 2})
    threading.Thread(target=reader, daemon=True).start()
    try:
        while not stop.wait(.2): pass
    finally:
        stop.set()
        with guard:
            for cancelled in watchers.values(): cancelled.set()
        # Finish metadata readers' finally blocks so their detached CLI groups
        # cannot survive a normal channel close. Durable run workers use leases.
        catalog.close()
