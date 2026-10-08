"""native io; no process is started at import."""
from __future__ import annotations
from collections import deque
import json
import os
import re
import selectors
import subprocess
import threading
import time
from .text_buffer import bounded_text
from .processes import stop_group as _stop_group
from .provider_common import ProviderError, ProviderCancelled, _MAX_LINE, _MAX_RESULT, _MAX_APPROVALS


class _Pipe:
    """One worker owns pipe IO. Stderr is bounded and drained, never recorded."""
    def __init__(self, command, cwd, env, stop, timeout):
        self.stop = stop
        self.deadline = time.monotonic() + timeout
        self.waiting_approval = False
        self.process = None
        self.selector = selectors.DefaultSelector()
        self.buffer, self.writes = bytearray(), bytearray()
        self.messages = deque()
        self.total = self.count = 0
        self.stdout_open = True
        self.check()
        try:
            native_env, descriptors = dict(env), {}
            lease_fd = native_env.pop('AGENTDOCK_ACCOUNT_LOCK_FD', None)
            if lease_fd is not None:
                fd = int(lease_fd)
                if fd < 3: raise ValueError('Invalid credential lease')
                os.fstat(fd)
                # The native process retains the account lock if the controller
                # dies, so a restarted controller cannot overwrite a refresh.
                descriptors['pass_fds'] = (fd,)
            credential_fd = native_env.pop('AGENTDOCK_CREDENTIAL_LOCK_FD', None)
            if credential_fd is not None:
                fd = int(credential_fd)
                if fd < 3: raise ValueError('Invalid credential lease')
                os.fstat(fd)
                descriptors['pass_fds'] = (*descriptors.get('pass_fds', ()), fd)
            execution_fd=native_env.pop('AGENTDOCK_EXECUTION_LOCK_FD',None)
            if execution_fd is not None:
                fd=int(execution_fd)
                os.fstat(fd)
                descriptors['pass_fds']=(*descriptors.get('pass_fds',()),fd)
            self.process = subprocess.Popen(command, cwd=cwd, env=native_env, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            start_new_session=True, bufsize=0, **descriptors)
            for stream, name in ((self.process.stdout, "stdout"), (self.process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                self.selector.register(stream, selectors.EVENT_READ, name)
            os.set_blocking(self.process.stdin.fileno(), False)
        except Exception:
            self.close()
            raise ProviderError("Could not start the configured native CLI. Check its installation and configuration.") from None

    def check(self):
        if self.stop.is_set():
            raise ProviderCancelled()
        if not self.waiting_approval and time.monotonic() >= self.deadline:
            raise ProviderError("Agent run timed out and its processes were stopped.")

    def send(self, message):
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > _MAX_LINE or len(self.writes) + len(encoded) > _MAX_LINE * 2:
            raise ProviderError("Native CLI request exceeded the size limit.")
        self.writes.extend(encoded)
        try:
            self.selector.get_key(self.process.stdin)
        except KeyError:
            self.selector.register(self.process.stdin, selectors.EVENT_WRITE, "stdin")

    def next(self, timeout=None):
        until=time.monotonic()+timeout if timeout is not None else None
        while True:
            self.check()
            if self.messages:
                return self.messages.popleft()
            if until is not None and time.monotonic()>=until: return None
            if not self.stdout_open:
                raise ProviderError("Native CLI exited before the turn completed. Check CLI login and compatibility.")
            for key, _ in self.selector.select(timeout=0.05):
                if key.data == "stdin":
                    try:
                        count = os.write(key.fd, self.writes)
                    except BlockingIOError:
                        continue
                    except (BrokenPipeError, OSError):
                        raise ProviderError("Native CLI closed its input unexpectedly.") from None
                    del self.writes[:count]
                    if not self.writes:
                        self.selector.unregister(key.fileobj)
                    continue
                try:
                    data = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not data:
                    self.selector.unregister(key.fileobj)
                    if key.data == "stdout":
                        self.stdout_open = False
                        if self.buffer:
                            raise ProviderError("Native CLI ended with an incomplete protocol message.")
                    continue
                self.total += len(data)
                # Lifetime byte/message totals are telemetry, not a run limit.
                # Each protocol frame and the in-memory queue remain bounded;
                # noisy output is truncated by the event sink, not by killing CLI.
                if key.data == "stderr":
                    continue
                self.buffer.extend(data)
                while b"\n" in self.buffer:
                    line, _, tail = self.buffer.partition(b"\n")
                    self.buffer = bytearray(tail)
                    if len(line) > _MAX_LINE:
                        raise ProviderError("Native CLI message exceeded the line limit.")
                    try:
                        message = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise ProviderError("Native CLI emitted invalid JSON.") from None
                    if not isinstance(message, dict):
                        raise ProviderError("Native CLI emitted an invalid protocol message.")
                    self.count += 1
                    self.messages.append(message)
                if len(self.buffer) > _MAX_LINE:
                    raise ProviderError("Native CLI message exceeded the line limit.")

    def cancel_notice(self, message):
        """Best effort only; process-group termination is always authoritative."""
        try:
            self.writes.clear()
            data = json.dumps(message, separators=(",", ":")).encode() + b"\n"
            os.write(self.process.stdin.fileno(), data)
        except (OSError, ValueError):
            pass

    def close(self):
        self.selector.close()
        if self.process:
            _stop_group(self.process)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream:
                    stream.close()

class _Callbacks:
    def __init__(self, pipe, emit, bind_session, approve, secrets):
        self.pipe, self.emit_callback = pipe, emit
        self.bind_session, self.approve_callback = bind_session, approve
        self.secrets = [v for k, v in secrets.items() if v and re.search(r"TOKEN|KEY|SECRET|CAPABILITY", k, re.I)]
        self.approvals = 0
        from .stream_buffer import StreamBuffer
        self.stream = StreamBuffer(emit)

    def clean(self, value):
        encoded = json.dumps(value, ensure_ascii=False)
        for secret in self.secrets:
            # JSON quoting handles secrets with quotes/newlines correctly.
            encoded = encoded.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[redacted]")
        if len(encoded.encode()) > _MAX_RESULT:
            raise ProviderError("Native CLI event exceeded the size limit.")
        return json.loads(encoded)

    def emit(self, kind, payload):
        try:
            value = self.clean(payload)
        except ProviderError:
            if kind not in ('tool_call', 'tool_result', 'tool_output', 'agent_update', 'reasoning_chunk', 'reasoning_message'):
                raise
            value = {'truncated': True, 'text': '[Output truncated: individual event exceeded the display limit.]'}
        self.stream.push(kind, value)

    def text(self, text, *, item_id=None, provider=None, part=0, phase=None, complete=False):
        if not isinstance(text, str):
            raise ProviderError("Native CLI returned an invalid text event.")
        if text or complete:
            text = bounded_text(text)
            payload = {"content": {"type": "text", "text": text}}
            if item_id is not None:
                payload.update(item_id=item_id, provider=provider, part=part)
            if phase in ("commentary", "final_answer"):
                payload["phase"] = phase
            self.emit("agent_message" if complete else "agent_message_chunk", payload)

    def approve(self, request, allow="accept", deny="decline"):
        return self.approve_options(request, [
            {"optionId": allow, "name": "Allow once", "kind": "allow_once"},
            {"optionId": deny, "name": "Deny", "kind": "reject_once"}])

    def approve_options(self, request, options):
        self.approvals += 1
        if self.approvals > _MAX_APPROVALS:
            raise ProviderError("Native CLI exceeded the permission request limit.")
        request = self.clean(request)
        done, answer = threading.Event(), []
        options = self.clean(options)

        def decide():
            try:
                answer.append(self.approve_callback(request, options))
            except Exception:
                answer.append(None)
            finally:
                done.set()

        self.stream.flush()
        # Human approval has its own bounded wait. It does not consume execution
        # time, but cancellation still stops the entire process group immediately.
        started = time.monotonic()
        self.pipe.waiting_approval = True
        threading.Thread(target=decide, daemon=True, name="agentdock-permission").start()
        try:
            while not done.wait(0.05):
                self.pipe.check()
                if time.monotonic() - started > 120:
                    raise ProviderError('Permission request expired; no action was approved.')
        finally:
            self.pipe.deadline += time.monotonic() - started
            self.pipe.waiting_approval = False
        self.pipe.check()
        if not answer or answer[0] not in [option['optionId'] for option in options]:
            raise ProviderError("Permission request was not resolved; the agent run was stopped.")
        return answer[0]
