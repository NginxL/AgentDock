"""Supported CLI entry points. Discovery never executes or installs a program."""
import os
from pathlib import Path
import shutil
import re


# ACP arguments are part of the command prefix, so administrators can replace
# an entry with a wrapper without shell interpolation or implicit downloads.
PROVIDERS = {
    'codex': ('Codex', ('codex',), ('app-server',)),
    'claude': ('Claude Code', ('claude',), ()),
    'trae': ('Trae CLI', ('traecli',), ('acp',)),
    'pi': ('Pi', ('pi-acp',), ()),
    'cursor': ('Cursor CLI', ('cursor-agent', 'agent'), ('acp',)),
    'antigravity': ('Antigravity', ('agy_acp_server.par',), ()),
    'grok': ('Grok Build', ('grok',), ('--no-auto-update', 'agent', 'stdio')),
    'opencode': ('OpenCode', ('opencode',), ('acp',)),
    'gemini': ('Gemini CLI', ('gemini',), ('--acp',)),
    'qwen': ('Qwen Code', ('qwen',), ('--acp',)),
}
ACP_PROVIDERS = frozenset(PROVIDERS) - {'codex', 'claude'}


def find_binary(name):
    found = shutil.which(name)
    if found:
        return found
    if '/' in name:
        return None
    for directory in (Path.home()/'.local/bin', Path.home()/'.npm-global/bin',
                      Path.home()/'.bun/bin', Path.home()/'.opencode/bin',
                      Path('/opt/homebrew/bin'), Path('/usr/local/bin')):
        path = directory/name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def commands(overrides=None):
    result = {}
    for provider, (_, candidates, arguments) in PROVIDERS.items():
        binary = next((found for name in candidates if (found := find_binary(name))), None)
        if binary:
            result[provider] = [binary, *arguments]
    for provider, command in (overrides or {}).items():
        if provider not in PROVIDERS or not isinstance(command, list) or not command or any(
                not isinstance(arg, str) or not arg or '\x00' in arg for arg in command):
            raise ValueError('commands must contain supported provider argument lists')
        result[provider] = list(command)
    return result


def acp_command(provider, command, cwd, env, stop):
    """Resolve Trae's two published ACP launch forms, before any prompt.

    Explicit wrapper commands remain untouched. Help output is bounded using
    the same process-group lifecycle as protocol IO, and is never displayed.
    """
    argv = list(command)
    if provider == 'trae' and argv[1:] == ['acp']:
        from .processes import stop_group
        from .provider_common import ProviderError, ProviderCancelled
        import subprocess
        try:
            process = subprocess.Popen(argv + ['--help'], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise ProviderError('Could not start Trae. Check the CLI command on this device.') from None
        try:
            # Help is a small local command. Bound both its lifetime and captured output.
            import selectors
            import time
            output = bytearray()
            deadline = time.monotonic() + 5
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if stop.is_set(): raise ProviderCancelled()
                    if time.monotonic() > deadline: raise ProviderError('Trae ACP command detection timed out.')
                    if not selector.select(.05): continue
                    chunk = os.read(process.stdout.fileno(), 8192)
                    if not chunk: break
                    output.extend(chunk)
                    if len(output) > 65536: raise ProviderError('Trae ACP help exceeded the size limit.')
            if re.search(rb'^\s+serve\s+', output, re.M): argv += ['serve']
        finally:
            stop_group(process)
            process.stdout.close()
    if provider == 'trae' and argv[1:] == ['acp', 'serve']:
        argv += ['--permission-mode', 'default']
    elif provider in ('gemini', 'qwen') and argv[1:] == ['--acp']:
        argv += ['--approval-mode', 'default']
    if provider == 'antigravity' and os.sys.platform.startswith('linux') and len(argv) == 1:
        argv += ['--uid=']
    return argv


def availability(configured=None):
    configured = commands(configured)
    result = {}
    for provider, (name, _, _) in PROVIDERS.items():
        command = configured.get(provider)
        available = bool(command and find_binary(command[0]))
        if available and provider == 'pi' and Path(command[0]).name == 'pi-acp' and not find_binary('pi'):
            available = False
        reason = None if available else ('adapter_required' if provider in ('pi', 'antigravity') else 'not_installed')
        # pi-acp delegates tools to Pi, which does not gate them through ACP.
        result[provider] = {'name': name, 'available': available, 'reason': reason,
                            'supports_ask': provider != 'pi'}
    return result
