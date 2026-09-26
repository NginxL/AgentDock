"""Process-group cleanup shared by native sessions and bounded quota probes."""
import os
import signal
import subprocess
import threading

_lock = threading.Lock()


def stop_group(process):
    # close() and an IO worker may both attempt to reap the same process.
    with _lock:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            except PermissionError:
                if process.poll() is None:
                    raise
                break
            try:
                process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
