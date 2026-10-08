"""Bounded, ordered delta batching without delaying control/final messages."""
import threading


class StreamBuffer:
    def __init__(self, emit, interval=.1, max_bytes=16384):
        self.emit = emit
        self.interval, self.max_bytes = interval, max_bytes
        self.lock = threading.RLock()
        self.pending = None
        self.parts = []
        self.size = 0
        self.timer = None
        self.failure = None

    def push(self, kind, payload):
        with self.lock:
            if self.failure:
                raise self.failure
            field = 'content' if isinstance(payload.get('content'), dict) else 'text'
            text = payload[field].get('text') if field == 'content' else payload.get('text')
            if kind not in ('agent_message_chunk', 'reasoning_chunk', 'tool_output') or not isinstance(text, str):
                self.flush()
                return self.emit(kind, payload)
            metadata = {**payload, field: {**payload[field], 'text': ''} if field == 'content' else ''}
            key = (kind, metadata, field)
            if self.pending != key:
                self.flush()
                self.pending = key
            self.parts.append(text)
            self.size += len(text.encode())
            if self.size >= self.max_bytes:
                self.flush()
            elif self.timer is None:
                self.timer = threading.Timer(self.interval, self._tick)
                self.timer.daemon = True
                self.timer.start()

    def _tick(self):
        try:
            self.flush()
        except Exception as error:
            with self.lock:
                self.failure = error

    def flush(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            if not self.parts:
                return
            kind, payload, field = self.pending
            text = ''.join(self.parts)
            if field == 'content':
                payload = {**payload, 'content': {**payload['content'], 'text': text}}
            else:
                payload = {**payload, 'text': text}
            self.pending, self.parts, self.size = None, [], 0
            self.emit(kind, payload)

    def close(self):
        self.flush()
        if self.failure:
            raise self.failure
