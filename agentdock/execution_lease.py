"""Native processes inherit this lock, so controller death cannot imply idle."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from .errors import Conflict


@contextmanager
def lease(home):
    path = Path(home)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Invalid execution storage")
    descriptor = os.open(
        path / "execution.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict(
                "The previous native session process is still running"
            ) from None
        yield descriptor
    finally:
        os.close(descriptor)


def assert_idle(home):
    home = Path(home)
    paths = [home / "execution.lock", *home.glob("branches/*/execution.lock")]
    for path in paths:
        if not path.exists():
            continue
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Conflict(
                    "A previous native process still owns this task conversation",
                    code="a_previous_native_process_still_owns_this_task_conversation",
                ) from None
        finally:
            os.close(descriptor)
