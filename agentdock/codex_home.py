"""Keep managed Codex transcripts separate from the user's desktop and terminal."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading


def _private(path):
    if path.is_symlink(): raise ValueError('Codex storage must not be a symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _copy(source, destination):
    _private(destination.parent)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            with source.open('rb') as incoming: shutil.copyfileobj(incoming, output)
            output.flush(); os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


def _owned_rollout(home, native_id, cwd):
    # Only a server-owned native ID is passed here. Never import other CLI chats.
    if not native_id: return None
    for folder in ('sessions', 'archived_sessions'):
        root = home / folder
        if not root.is_dir(): continue
        for path in root.rglob('*' + native_id + '*.jsonl'):
            if path.is_symlink(): continue
            with path.open('rb') as stream:
                row = json.loads(stream.readline(1024 * 1024))
            meta = row.get('payload', {})
            if (row.get('type') == 'session_meta' and meta.get('id') == native_id
                    and meta.get('originator') == 'agentdock'):
                return path
    return None


def prepare(home, environment, native_id=None, cwd=None, managed=False):
    """Snapshot settings, reuse file credentials, and import an owned legacy rollout.

    Settings are copies so native trust/cache writes cannot alter the desktop's
    config. Login files are links: token refresh remains owned by the native CLI.
    Session directories and state databases are never linked or copied wholesale.
    """
    home = Path(home).expanduser().absolute()
    source = Path(environment.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()
    if home.resolve() == source: raise ValueError('Codex session storage must be independent')
    _private(home)
    with (home / '.prepare.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in ('config.toml', 'managed_config.toml', 'AGENTS.md', 'AGENTS.override.md', 'hooks.json'):
            original, target = source / name, home / name
            if original.is_file(): _copy(original, target)
            elif target.exists(): target.unlink()
        # These native resources retain their configured identities and login state.
        for name in ('auth.json', '.credentials.json', 'skills', 'rules', 'plugins'):
            # The account credential lease owns copying and refreshing these
            # private files. A symlink can be replaced by an atomic CLI refresh.
            if managed and name in ('auth.json', '.credentials.json'):
                continue
            original, target = source / name, home / name
            if target.is_symlink():
                if target.resolve() == original.resolve(): continue
                target.unlink()
            if target.exists(): raise ValueError('Conflicting isolated Codex resource')
            if original.exists(): target.symlink_to(original, target_is_directory=original.is_dir())
        legacy = _owned_rollout(source, native_id, cwd) if native_id else None
        if legacy:
            # Native resume discovers this exact transcript in the private session tree.
            destination = home / 'sessions' / Path(*legacy.relative_to(source).parts[1:])
            if not _owned_rollout(home, native_id, cwd): _copy(legacy, destination)
    env = dict(environment, CODEX_HOME=str(home), CODEX_SQLITE_HOME=str(home))
    # Config-file sqlite_home takes precedence over CODEX_SQLITE_HOME.
    flags = ['-c', 'sqlite_home=' + json.dumps(str(home)), '-c', 'log_dir=' + json.dumps(str(home / 'log'))]
    if managed:
        # An explicitly selected subscription must not silently use a project
        # gateway, API key or the operating system's default credential entry.
        flags += ['-c', 'model_provider="openai"', '-c', 'forced_login_method="chatgpt"',
                  '-c', 'cli_auth_credentials_store="file"']
    return env, flags, legacy


def retire_legacy(command, environment, native_id):
    """Remove only an AgentDock-owned legacy transcript from the shared CLI store."""
    source = Path(environment.get('CODEX_HOME') or Path.home()/'.codex').expanduser().resolve()
    if not _owned_rollout(source, native_id, None): return
    from .providers import _Pipe, _Codex, _Callbacks
    pipe = _Pipe(list(command) + ['--listen', 'stdio://'], str(Path.home()), environment, threading.Event(), 25)
    try:
        adapter = _Codex(pipe, _Callbacks(pipe, lambda *a: None, lambda *a: None, lambda *a: None, {}))
        adapter.request('initialize', {'clientInfo': {'name': 'agentdock', 'version': '0.3.0'}})
        pipe.send({'method': 'initialized', 'params': {}})
        adapter.request('thread/delete', {'threadId': native_id})
    finally:
        pipe.close()
