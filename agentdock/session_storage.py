"""Private, disposable CLI state for one AgentDock conversation."""
import os
from pathlib import Path
import shutil
import uuid

from .codex_home import _private, _copy


def session_directory(root, session_id):
    if str(uuid.UUID(session_id)) != session_id: raise ValueError('Invalid session identity')
    root = Path(root).absolute()
    if root.is_symlink(): raise ValueError('Invalid session storage')
    path = root / session_id
    if path.is_symlink(): raise ValueError('Invalid session storage')
    return path


def remove_session_directory(root, session_id):
    path = session_directory(root, session_id)
    # rmtree unlinks credential/resource symlinks without traversing their targets.
    if path.exists(): shutil.rmtree(path)


def prepare_claude(home, environment, native_id=None):
    home = _private(Path(home).absolute())
    source = Path(environment.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').expanduser().resolve()
    if home.resolve() == source: raise ValueError('Claude session storage must be independent')
    for name in ('settings.json', 'settings.local.json', 'CLAUDE.md'):
        if (source/name).is_file(): _copy(source/name, home/name)
        elif (home/name).exists(): (home/name).unlink()
    preferences = source/'.claude.json' if environment.get('CLAUDE_CONFIG_DIR') else Path.home()/'.claude.json'
    if preferences.is_file(): _copy(preferences, home/'.claude.json')
    for original in claude_rollouts(source, native_id):
        destination = home / original.relative_to(source)
        if not destination.exists(): _copy(original, destination)
        sidecars = original.with_suffix('')
        if sidecars.is_dir() and not sidecars.is_symlink() and not destination.with_suffix('').exists():
            shutil.copytree(sidecars, destination.with_suffix(''), symlinks=True)
    for name in ('skills', 'commands', 'agents', 'rules', 'plugins'):
        target = home/name
        if not target.exists() and not target.is_symlink() and (source/name).exists(): target.symlink_to(source/name, target_is_directory=True)
    env = dict(environment)
    # Claude itself accesses its existing credential store. AgentDock never reads
    # tokens or calls the macOS Keychain. Empty means the native default entry.
    env['CLAUDE_SECURESTORAGE_CONFIG_DIR'] = environment.get('CLAUDE_SECURESTORAGE_CONFIG_DIR', environment.get('CLAUDE_CONFIG_DIR', ''))
    env['CLAUDE_CONFIG_DIR'] = str(home)
    env['CLAUDE_CODE_AUTO_CONNECT_IDE'] = '0'
    for key in ('CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_PARENT_SESSION_ID', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_JOB_DIR'):
        env.pop(key, None)
    return env


def claude_rollouts(source, native_id):
    if not native_id: return []
    if str(uuid.UUID(native_id)) != native_id: raise ValueError('Invalid Claude session identity')
    return [p for p in (source/'projects').glob('*/' + native_id + '.jsonl') if p.is_file() and not p.is_symlink()]


def retire_legacy_claude(environment, native_id):
    source = Path(environment.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude').expanduser().resolve()
    for path in claude_rollouts(source, native_id):
        path.unlink()
        sidecars = path.with_suffix('')
        if sidecars.is_dir() and not sidecars.is_symlink(): shutil.rmtree(sidecars)
