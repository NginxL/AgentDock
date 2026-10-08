"""Private ACP CLI state; copy selected settings, never native conversations.

Original configuration/authentication files are read only. Copies and all HOME /
XDG state belong to one AgentDock session and are removed with that session.
"""
import os
from pathlib import Path
import shutil


SEEDS = {
    'trae': ('.trae/traecli.toml', '.trae/traecli.yaml', '.trae/auth.json',
             '.config/trae_cli/trae_cli.yaml', 'Library/Application Support/trae_cli/trae_cli.yaml'),
    'gemini': ('.gemini/settings.json', '.gemini/oauth_creds.json', '.gemini/google_accounts.json', '.gemini/.env'),
    'qwen': ('.qwen/settings.json', '.qwen/oauth_creds.json', '.qwen/.env'),
    'cursor': ('.cursor/cli-config.json', '.cursor/auth.json', '.cursor/mcp.json',
               '.config/cursor/cli-config.json', '.config/cursor/auth.json'),
    'pi': ('.pi/agent/settings.json', '.pi/agent/models.json', '.pi/agent/auth.json'),
    'opencode': ('.config/opencode/opencode.json', '.config/opencode/opencode.jsonc',
                 '.config/opencode/config.json', '.local/share/opencode/auth.json'),
    'grok': ('.grok/config.toml', '.grok/auth.json'),
    'antigravity': (),
}


def _private(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Invalid isolated CLI directory')
    path.chmod(0o700)
    return path


def seed_origin(relative, environment):
    source = Path(environment.get('HOME') or Path.home()).expanduser()
    if relative.startswith('.gemini/') and environment.get('GEMINI_CLI_HOME'):
        return Path(environment['GEMINI_CLI_HOME']) / relative
    roots = {'.pi/agent/': 'PI_CODING_AGENT_DIR', '.qwen/': 'QWEN_HOME',
             '.grok/': 'GROK_HOME', '.cursor/': 'CURSOR_CONFIG_DIR',
             '.config/': 'XDG_CONFIG_HOME', '.local/share/': 'XDG_DATA_HOME'}
    for prefix, key in roots.items():
        if relative.startswith(prefix) and environment.get(key):
            return Path(environment[key]) / relative[len(prefix):]
    return source / relative


def prepare(provider, directory, environment):
    env = dict(environment)
    source = Path(env.get('HOME') or Path.home()).expanduser()
    target = _private(Path(directory))
    marker = target/'.agentdock-settings-copied'
    if marker.is_symlink(): raise ValueError('Invalid isolated CLI marker')
    if not marker.exists():
        for relative in SEEDS.get(provider, ()):
            origin = seed_origin(relative, environment)
            if not origin.is_file() or origin.stat().st_size > 4*1024*1024: continue
            destination = target/relative
            # Never follow a CLI-created destination symlink back into native state.
            current = target
            for part in Path(relative).parts[:-1]: current = _private(current/part)
            if destination.is_symlink(): raise ValueError('Invalid isolated CLI settings')
            if not destination.exists():
                with destination.open('xb') as output:
                    os.chmod(destination, 0o600)
                    with origin.open('rb') as input_file: shutil.copyfileobj(input_file, output)
        marker.touch(mode=0o600, exist_ok=False)
    env.update(HOME=str(target), XDG_CONFIG_HOME=str(_private(target/'.config')),
               XDG_DATA_HOME=str(_private(target/'.local/share')),
               XDG_STATE_HOME=str(_private(target/'.local/state')),
               XDG_CACHE_HOME=str(_private(target/'.cache')),
               GEMINI_CLI_HOME=str(target), PI_CODING_AGENT_DIR=str(target/'.pi/agent'),
               QWEN_HOME=str(target/'.qwen'), QWEN_RUNTIME_DIR=str(target/'.qwen'),
               GROK_HOME=str(target/'.grok'), CURSOR_CONFIG_DIR=str(target/'.cursor'))
    # Do not attach new clients to an already running desktop/IDE conversation.
    for key in ('GEMINI_CLI_IDE_PID', 'GEMINI_CLI_TRUSTED_FOLDERS_PATH', 'GEMINI_CLI_TRUST_WORKSPACE',
                'OPENCODE_CONFIG', 'OPENCODE_CONFIG_DIR', 'OPENCODE_CONFIG_CONTENT',
                'OPENCODE_TEST_HOME', 'PI_CODING_AGENT_SESSION_DIR', 'GROK_LOG_FILE', 'GROK_DEBUG_LOG',
                'CURSOR_TRACE_ID', 'CURSOR_CONVERSATION_ID'):
        env.pop(key, None)
    return env
