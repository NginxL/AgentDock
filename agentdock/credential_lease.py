"""Short-lived ACP seed files with refresh recovery and source conflict checks.

Only credential files are copied back. Settings, proxy rules, conversation data
and arbitrary CLI output never overwrite native configuration.
"""

import fcntl
import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .acp_home import SEEDS, _private, prepare, seed_origin
from .errors import Conflict

AUTH_NAMES = {"auth.json", "oauth_creds.json", "google_accounts.json"}


def fingerprint(path):
    if path.is_symlink():
        raise Conflict("Credential lease paths must not be symbolic links")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise Conflict("Invalid credential lease file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(source, target):
    fingerprint(source)
    fingerprint(target)
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.parent.is_symlink():
        raise Conflict("Invalid credential directory")
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".credential-")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(source.read_bytes())
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def destinations(directory, seeds):
    for relative in seeds:
        path = directory
        for part in Path(relative).parts[:-1]:
            path = _private(path / part)
        target = path / Path(relative).name
        fingerprint(target)
        yield relative, target


def profile(provider, environment):
    """Stable recovery storage, also used by prompt-free model discovery."""
    seeds = SEEDS.get(provider, ())
    origins = {
        relative: seed_origin(relative, environment).expanduser().resolve()
        for relative in seeds
    }
    identity = hashlib.sha256(
        json.dumps({k: str(v) for k, v in origins.items()}, sort_keys=True).encode()
    ).hexdigest()
    source_home = Path(environment.get("HOME") or Path.home()).expanduser()
    root = _private(source_home / ".local/share/agentdock/credential-leases")
    path = root / (provider + "-" + identity)
    return _private(path), seeds, origins


def catalog_home(provider, environment):
    # This directory must outlive discovery failures: pending OAuth refreshes
    # cannot be placed under TemporaryDirectory's unconditional cleanup.
    path, _, _ = profile(provider, environment)
    return _private(path / "catalog-home")


def preserve_conflict(path, pending, cached_files):
    """Save the child's whole auth bundle before releasing a divergent lease.

    A deterministic directory makes a retry after a partial archive idempotent.
    It is outside the active session and never becomes a new login source.
    """
    hashes = {relative: fingerprint(cached) for relative, cached in cached_files}
    identity = hashlib.sha256(
        json.dumps([pending, hashes], sort_keys=True).encode()
    ).hexdigest()
    archive = _private(_private(path / "conflicts") / identity)
    backups = dict(destinations(archive, hashes))
    for relative, cached in cached_files:
        saved = backups[relative]
        existing = fingerprint(saved)
        if existing is not None and existing != hashes[relative]:
            raise Conflict("Preserved credential recovery data was modified")
        if cached.exists() and existing is None:
            replace(cached, saved)


@contextmanager
def credentials(provider, directory, environment, stop):
    """Serialize refreshes for the same source identity, retaining no idle copies."""
    path, seeds, origins = profile(provider, environment)
    lock_path, journal = path / "lease.lock", path / "pending.json"
    if lock_path.is_symlink() or journal.is_symlink():
        raise Conflict("Invalid credential lease storage")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + 30
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if stop.wait(0.05) or time.monotonic() > deadline:
                    raise Conflict(
                        "Another native run is refreshing this login; retry after it finishes"
                    )

        def finish(pending):
            target = Path(pending["target"])
            if not target.is_absolute() or target.is_symlink() or not target.is_dir():
                raise Conflict("Credential refresh recovery directory is unavailable")
            original = pending["hashes"]
            cached_files = [
                (relative, cached)
                for relative, cached in destinations(target, seeds)
                if Path(relative).name in AUTH_NAMES
            ]
            current = {key: fingerprint(origins[key]) for key, _ in cached_files}
            cached_hashes = {key: fingerprint(cached) for key, cached in cached_files}
            native_changed = any(
                current[key] not in (original[key], cached_hashes[key])
                for key, _ in cached_files
            )
            if native_changed:
                # An external CLI login is authoritative for future work. If our
                # child also changed credentials, preserve its entire auth bundle
                # separately, without mixing identities or poisoning pending.json.
                if any(
                    cached_hashes[key] is not None
                    and cached_hashes[key] not in (original[key], current[key])
                    for key, _ in cached_files
                ):
                    preserve_conflict(path, pending, cached_files)
            else:
                # Validate the whole bundle before copying any refreshed file.
                for relative, cached in cached_files:
                    if cached_hashes[relative] != current[relative]:
                        replace(cached, origins[relative])
            for relative, cached in destinations(target, seeds):
                cached.unlink(missing_ok=True)
            (target / ".agentdock-settings-copied").unlink(missing_ok=True)
            journal.unlink(missing_ok=True)

        if journal.exists():
            finish(json.loads(journal.read_text()))
        target = _private(Path(directory).absolute())
        # Older versions left permanent copies without a source fingerprint.
        # A different token may be a valid refresh; neither copy can safely win.
        for relative, cached in destinations(target, seeds):
            if (
                Path(relative).name in AUTH_NAMES
                and cached.exists()
                and fingerprint(cached) != fingerprint(origins[relative])
            ):
                raise Conflict(
                    "Legacy session credentials differ from the native login; both copies have been preserved"
                )
        # Old settings caches are renewed so changed proxy settings take effect.
        (target / ".agentdock-settings-copied").unlink(missing_ok=True)
        for _, cached in destinations(target, seeds):
            cached.unlink(missing_ok=True)
        pending = {
            "target": str(target),
            "hashes": {key: fingerprint(value) for key, value in origins.items()},
        }
        # Journal before prepare: a crash at any copy boundary can be recovered.
        descriptor_json = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor_json, "w") as output:
            json.dump(pending, output)
            output.flush()
            os.fsync(output.fileno())
        try:
            env = prepare(provider, target, environment)
            env["AGENTDOCK_CREDENTIAL_LOCK_FD"] = str(descriptor)
            yield env
        finally:
            finish(pending)
    finally:
        os.close(descriptor)
