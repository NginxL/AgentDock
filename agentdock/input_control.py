"""Thread-safe, once-only delivery of a live adjustment to one native turn."""

import threading


class InputControl:
    def __init__(self):
        self.lock = threading.Lock()
        self.turn_id = None
        self.pending = []
        self.seen = set()

    @property
    def available(self):
        with self.lock:
            return self.turn_id is not None

    def attach(self, turn_id):
        with self.lock:
            self.turn_id = turn_id

    def submit(self, identifier, body):
        with self.lock:
            if identifier in self.seen:
                return
            self.seen.add(identifier)
            self.pending.append(
                {"id": identifier, "body": body, "turn_id": self.turn_id}
            )

    def take(self):
        with self.lock:
            pending, self.pending = self.pending, []
            return pending

    def close(self):
        with self.lock:
            self.turn_id = None
