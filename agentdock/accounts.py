"""Native subscription logins owned by AgentDock, never the ambient CLI login.

The account home owns credentials; conversation homes own history. A filesystem
lease serializes native refreshes for an account, including across SSH workers.
No OAuth API client or token refresh implementation lives in this module.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pty
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import termios
import threading
import time
from urllib.parse import urlsplit, parse_qs
import uuid


class AccountError(ValueError):
    """Public errors must not contain CLI output, paths, or credential material."""


_TERMINAL = {'completed', 'failed', 'cancelled'}
_PUBLIC_JOB = ('id', 'status', 'method', 'url', 'device_code', 'error_code', 'created_at', 'updated_at')
_AUTH_HOSTS = {'auth.openai.com', 'chatgpt.com', 'claude.ai', 'console.anthropic.com', 'platform.claude.com'}
_CREDENTIALS = {'codex': ('auth.json',), 'claude': ('.credentials.json',)}
_MAX_FILE = 1024 * 1024
_NETWORK_ENV = {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy',
                'all_proxy', 'no_proxy', 'NODE_EXTRA_CA_CERTS', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}


def _identity(value):
    if not isinstance(value, str): raise AccountError('Invalid account identity.')
    try:
        if str(uuid.UUID(value)) != value: raise ValueError()
    except (ValueError, AttributeError): raise AccountError('Invalid account identity.') from None
    return value


def _directory(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise AccountError('Account storage must not contain symbolic links.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _read(path, default=None):
    if path.is_symlink(): raise AccountError('Account storage must not contain symbolic links.')
    try:
        with path.open('rb') as handle:
            data = handle.read(_MAX_FILE + 1)
        if len(data) > _MAX_FILE: raise AccountError('Account storage exceeded its size limit.')
        return json.loads(data)
    except FileNotFoundError: return default
    except (ValueError, UnicodeError): raise AccountError('Account storage is invalid.') from None


def _write(path, value):
    if path.is_symlink(): raise AccountError('Account storage must not contain symbolic links.')
    _directory(path.parent)
    data = json.dumps(value, ensure_ascii=False).encode()
    if len(data) > _MAX_FILE: raise AccountError('Account storage exceeded its size limit.')
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _copy_credential(source, target):
    # Validate JSON before publishing, without exposing its contents to callers.
    data = _read(source)
    if data is None and source.exists(): raise AccountError('Native login data is invalid.')
    if data is not None:
        if not isinstance(data, dict): raise AccountError('Native login data is invalid.')
        _write(target, data)
    elif target.exists() or target.is_symlink():
        if target.is_symlink(): raise AccountError('Managed credentials must not be symbolic links.')
        target.unlink()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _public_job(job):
    return {key: job[key] for key in _PUBLIC_JOB if key in job}


def _login_hints(text):
    """Accept only native vendor authorization URLs; discard all other output."""
    hints = {}
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)
    for candidate in re.findall(r'https://[^\s<>"\x1b]+', text):
        candidate = candidate.rstrip(').,')
        if len(candidate) > 8192: continue
        try:
            parts = urlsplit(candidate)
            params = parse_qs(parts.query)
            if (parts.hostname not in _AUTH_HOSTS or parts.username or parts.password
                    or parts.port not in (None, 443) or parts.fragment
                    or any(re.search(r'token|secret|password|api.?key', key, re.I) for key in params)):
                continue
            if not any(word in parts.path.lower() for word in ('oauth', 'auth', 'device', 'login')):
                continue
            hints['url'] = candidate
        except ValueError: continue
    match = re.search(r'\b([A-Z0-9]{4}-[A-Z0-9]{4})\b', text)
    if match: hints['device_code'] = match.group(1)
    return hints


class AccountManager:
    def __init__(self, root, commands_config=None, *, stop=None):
        path = Path(root).expanduser().absolute()
        if path.is_symlink(): raise AccountError('Account storage must not be a symbolic link.')
        # System home and temporary-directory aliases may be symlinks. Resolve
        # that trusted parent once; child account paths must never be links.
        self._storage_parent = path.parent
        self.root = path.parent.resolve() / path.name
        self.commands_config = commands_config or {}
        self._leases = threading.local()
        self.stop = stop if stop is not None else threading.Event()

    def _profile(self, account):
        if not isinstance(account, dict) or account.get('provider') not in _CREDENTIALS:
            raise AccountError('Only Codex and Claude Code subscription accounts are supported.')
        identity = _identity(account.get('id'))
        root = _directory(self.root)
        home = _directory(root / identity)
        profile = {'id': identity, 'provider': account['provider']}
        previous = _read(home / 'profile.json')
        if previous is not None and previous != profile:
            raise AccountError('The account provider cannot be changed.')
        if previous is None: _write(home / 'profile.json', profile)
        return profile, home

    def environment(self, account, base_env=None):
        profile, home = self._profile(account)
        native = _directory(home / profile['provider'])
        environment = dict(os.environ if base_env is None else base_env)
        environment.pop('AGENTDOCK_ACCOUNT_LOCK_FD', None)
        if profile['provider'] == 'claude':
            source = Path(environment.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
            # Only explicit network fields are inherited. Never copy a native
            # settings document, apiKeyHelper, endpoint, API key, or auth file.
            for name in ('settings.json', 'settings.local.json'):
                try:
                    settings = _read(source / name, {})
                    inherited = settings.get('env', {}) if isinstance(settings, dict) else {}
                    if isinstance(inherited, dict):
                        for key in _NETWORK_ENV:
                            value = inherited.get(key)
                            if key not in environment and isinstance(value, str) and '\x00' not in value:
                                environment[key] = value
                except (OSError, AccountError): pass
        # Proxy variables deliberately survive. Endpoint/key overrides must not
        # send a subscription credential to a previously configured Relay.
        for key in list(environment):
            if (key.startswith(('OPENAI_', 'ANTHROPIC_', 'CODEX_', 'CLAUDE_', 'CLAUDECODE'))
                    or key in ('AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT')):
                environment.pop(key, None)
        environment['AGENTDOCK_ACCOUNT_HOME'] = str(native)
        lock_fd = getattr(self._leases, 'accounts', {}).get(profile['id'])
        if lock_fd is not None: environment['AGENTDOCK_ACCOUNT_LOCK_FD'] = str(lock_fd)
        if profile['provider'] == 'codex':
            environment['CODEX_HOME'] = str(native)
            environment['CODEX_SQLITE_HOME'] = str(native)
            config = native / 'config.toml'
            if config.is_symlink(): raise AccountError('Account configuration must not be a symbolic link.')
            if not config.exists():
                descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w') as out:
                    out.write('cli_auth_credentials_store = "file"\nmodel_provider = "openai"\n')
        else:
            environment['CLAUDE_CONFIG_DIR'] = str(native)
            environment['CLAUDE_SECURESTORAGE_CONFIG_DIR'] = str(native)
            environment['CLAUDE_CODE_AUTO_CONNECT_IDE'] = '0'
        return environment

    @contextmanager
    def lease(self, account, stop=None, timeout=60, recover=True):
        profile, home = self._profile(account)
        stop = stop if stop is not None else self.stop
        lockpath = home / '.credential.lock'
        if lockpath.is_symlink(): raise AccountError('Invalid account lock.')
        fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        registered = False
        try:
            deadline = time.monotonic() + max(0, timeout)
            while True:
                if stop.is_set(): raise AccountError('Account operation cancelled.')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise AccountError('This account is busy. Try again after its current operation.')
                    stop.wait(min(.05, max(0, deadline - time.monotonic())))
            if recover: self._recover(profile, home)
            accounts = getattr(self._leases, 'accounts', {})
            accounts[profile['id']] = fd
            self._leases.accounts = accounts
            registered = True
            yield fd
        finally:
            if registered: self._leases.accounts.pop(profile['id'], None)
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _session_target(self, session_home, provider):
        target = Path(session_home).absolute() / provider
        # Canonicalize the trusted data parent (e.g. /var or /home aliases), not
        # any session component: a symlink inside a session must be rejected.
        try:
            relative = target.relative_to(self.root.parent)
        except ValueError:
            # Only replace the trusted prefix captured at construction. Resolving
            # a session's parent here would hide links inside sessions/branches.
            try: relative = target.relative_to(self._storage_parent)
            except ValueError: raise AccountError('Session credentials must stay in AgentDock storage.') from None
            target = self.root.parent / relative
        parts = relative.parts
        if (len(parts) not in (3, 5) or parts[0] != 'sessions' or parts[-1] != provider
                or (len(parts) == 5 and (parts[2] != 'branches' or not re.fullmatch(r'[1-9][0-9]{0,6}', parts[3])))):
            raise AccountError('Invalid managed conversation storage.')
        _identity(parts[1])
        if any(part.is_symlink() for part in (target, *target.parents)):
            raise AccountError('Session storage must not contain symbolic links.')
        return target

    @staticmethod
    def _fingerprint(path):
        value = _read(path)
        if value is None:
            if path.exists(): raise AccountError('Native login data is invalid.')
            return None
        if not isinstance(value, dict): raise AccountError('Native login data is invalid.')
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def _recover(self, profile, home, discard=False):
        journal = home / '.pending-session.json'
        pending = _read(journal)
        if pending is None: return
        if not isinstance(pending, dict) or pending.get('provider') != profile['provider']:
            raise AccountError('Pending native login recovery is invalid.')
        relative = pending.get('target')
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise AccountError('Pending native login recovery is invalid.')
        target = self._session_target((self.root.parent / relative).parent, profile['provider'])
        if str(target.relative_to(self.root.parent)) != relative:
            raise AccountError('Pending native login recovery is invalid.')
        source = home / profile['provider']
        expected = pending.get('source_hashes', {})
        names = _CREDENTIALS[profile['provider']]
        if not isinstance(expected, dict) or set(expected) != set(names):
            raise AccountError('Pending native login recovery is invalid.')
        # An orphan CLI inherits the credential lease FD; recovery cannot reach
        # this point until it closes, even when the AgentDock parent was killed.
        if pending.get('phase') not in (None, 'copying', 'committed'):
            raise AccountError('Pending native login recovery is invalid.')
        if not discard and target.is_dir() and pending.get('phase') != 'committed':
            for name in names:
                current = self._fingerprint(source / name)
                recovered = self._fingerprint(target / name)
                if current not in (expected[name], recovered):
                    raise AccountError('Account credentials changed during recovery. Sign in again before continuing.')
            for name in names:
                _copy_credential(target / name, source / name)
            pending['phase'] = 'committed'
            _write(journal, pending)
        for name in names: (target / name).unlink(missing_ok=True)
        journal.unlink()

    @contextmanager
    def session_cleanup(self, accounts):
        """Recover refreshed credentials before any conversation files disappear.

        All branch leases stay held through removal. A native process surviving
        a controller crash still owns its inherited lease and blocks cleanup.
        """
        if not isinstance(accounts, list): raise AccountError('Invalid session accounts.')
        profiles = {}
        for account in accounts:
            if not isinstance(account, dict) or account.get('provider') not in _CREDENTIALS:
                raise AccountError('Invalid session account.')
            identifier = _identity(account.get('id'))
            if identifier in profiles and profiles[identifier]['provider'] != account['provider']:
                raise AccountError('The account provider cannot be changed.')
            profiles[identifier] = account
        with ExitStack() as stack:
            existing = []
            for identifier, account in sorted(profiles.items()):
                path = self.root / identifier
                if path.is_symlink(): raise AccountError('Account storage must not contain symbolic links.')
                # Removed or never-prepared accounts have nothing to recover.
                # Do not recreate their native storage during session deletion.
                if not path.exists(): continue
                stack.enter_context(self.lease(account, timeout=0, recover=False))
                existing.append(account)
            for account in existing:
                profile, home = self._profile(account)
                self._recover(profile, home)
            yield

    @contextmanager
    def credential_session(self, account, session_home, base_env=None, stop=None):
        """Root must prepare/run the conversation with managed=True inside this lease.

        This is deliberately copy-in/copy-out, not an auth.json symlink: native
        atomic refresh replaces a symlink rather than updating its target.
        """
        with self.lease(account, stop=stop) as lock_fd:
            env = self.environment(account, base_env)
            source = Path(env['AGENTDOCK_ACCOUNT_HOME'])
            env['AGENTDOCK_ACCOUNT_LOCK_FD'] = str(lock_fd)
            target = _directory(self._session_target(session_home, account['provider']))
            if source == target: raise AccountError('Session history must be separate from account storage.')
            for name in _CREDENTIALS[account['provider']]:
                _copy_credential(source / name, target / name)
            journal = source.parent / '.pending-session.json'
            pending = {'provider': account['provider'], 'phase': 'copying', 'target': str(target.relative_to(self.root.parent)),
                             'source_hashes': {name: self._fingerprint(source / name)
                                              for name in _CREDENTIALS[account['provider']]}}
            _write(journal, pending)
            try:
                yield env
            finally:
                for name in _CREDENTIALS[account['provider']]:
                    _copy_credential(target / name, source / name)
                _write(journal, dict(pending, phase='committed'))
                # Session history must not become a second long-lived credential
                # store. Remove copies only after all refresh writes succeeded.
                for name in _CREDENTIALS[account['provider']]:
                    (target / name).unlink(missing_ok=True)
                journal.unlink(missing_ok=True)

    def _command(self, account, login=False, method='browser'):
        from .registry import commands
        command = commands(self.commands_config).get(account['provider'])
        if not command: raise AccountError('The native CLI is not installed on this device.')
        command = list(command)
        if account['provider'] == 'codex':
            if command[-1] == 'app-server': command.pop()
            command += ['-c', 'cli_auth_credentials_store="file"', '-c', 'model_provider="openai"',
                        '-c', 'forced_login_method="chatgpt"']
            command += ['login'] if login else ['app-server', '--listen', 'stdio://']
            if login and method == 'device': command += ['--device-auth']
        else:
            command += ['--setting-sources', 'user']
            command += ['auth', 'login', '--claudeai'] if login else ['auth', 'status', '--json']
        return command

    def start(self, account, method='browser'):
        if method not in ('browser', 'device') or (account.get('provider') == 'claude' and method != 'browser'):
            raise AccountError('This native CLI does not support the requested login method.')
        profile, home = self._profile(account)
        with self.lease(account, timeout=0, recover=False):
            previous = self.status(account)
            if previous.get('status') not in _TERMINAL | {'idle'}:
                raise AccountError('An account login is already in progress.')
            self._recover(profile, home, discard=True)
            job = {'id': str(uuid.uuid4()), 'status': 'starting', 'method': method,
                   'created_at': _now(), 'updated_at': _now(), 'heartbeat': time.time(),
                   'command': self._command(profile, login=True, method=method),
                   'commands_config': {profile['provider']: self.commands_config[profile['provider']]}
                       if profile['provider'] in self.commands_config else {}}
            _write(home / 'login.json', job)
            environment = self.environment(profile)
            environment.pop('AGENTDOCK_ACCOUNT_LOCK_FD', None)
            environment['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent)
            try:
                child = subprocess.Popen([sys.executable, '-m', 'agentdock.accounts', '_login', str(self.root),
                                          profile['id'], job['id']], env=environment, cwd=home,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                job.update(status='failed', error_code='login_start_failed', updated_at=_now())
                _write(home / 'login.json', job)
                raise AccountError('Could not start the native login process.') from None
            # Reap local children without keeping short SSH RPC processes alive.
            threading.Thread(target=child.wait, daemon=True).start()
            return _public_job(job)

    def status(self, account):
        _, home = self._profile(account)
        job = _read(home / 'login.json', {'status': 'idle'})
        if job.get('status') not in _TERMINAL | {'idle'} and time.time() - job.get('heartbeat', 0) > 30:
            return dict(_public_job(job), status='failed', error_code='login_worker_stopped')
        return _public_job(job)

    def cancel(self, account):
        _, home = self._profile(account)
        current = self.status(account)
        if current['status'] in _TERMINAL | {'idle'}: return current
        # The worker owns its subprocess. Never kill a persisted (possibly reused) PID.
        _write(home / ('cancel-' + _identity(current['id']) + '.json'), True)
        return dict(current, status='cancelling')

    def submit(self, account, code):
        _, home = self._profile(account)
        current = self.status(account)
        if current['status'] in _TERMINAL | {'idle'}: raise AccountError('No native login is awaiting input.')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=#-]{8,2048}', code):
            raise AccountError('Invalid native login confirmation code.')
        _write(home / ('input-' + _identity(current['id']) + '.json'), code)
        return current

    def _codex(self, account, method, params):
        from .providers import _Pipe, _Codex, _Callbacks, ProviderError
        environment = self.environment(account)
        pipe = _Pipe(self._command(account), environment['AGENTDOCK_ACCOUNT_HOME'], environment,
                     self.stop, 25)
        try:
            adapter = _Codex(pipe, _Callbacks(pipe, lambda *a: None, lambda *a: None, lambda *a: None, {}))
            adapter.request('initialize', {'clientInfo': {'name': 'agentdock', 'version': '0.3.0'}})
            pipe.send({'method': 'initialized', 'params': {}})
            return adapter.request(method, params)
        except ProviderError:
            raise AccountError('Native account status is unavailable. Check the CLI and login.') from None
        finally: pipe.close()

    def _check(self, account):
        if account['provider'] == 'codex':
            value = self._codex(account, 'account/read', {'refreshToken': False}).get('account')
            valid = isinstance(value, dict) and value.get('type') == 'chatgpt'
            return {'status': 'ready' if valid else 'login_required', 'logged_in': valid,
                    'email': _safe_label(value.get('email')) if valid else None,
                    'plan': _safe_label(value.get('planType')) if valid else None}
        environment = self.environment(account)
        raw = _bounded_command(self._command(account), environment, environment['AGENTDOCK_ACCOUNT_HOME'], stop=self.stop)
        try: value = json.loads(raw)
        except ValueError: raise AccountError('Native account status is unavailable. Check the CLI version.') from None
        if not isinstance(value, dict): raise AccountError('Native account status is unavailable.')
        valid = value.get('loggedIn') is True and value.get('authMethod') in ('claude.ai', 'oauth', 'subscription')
        return {'status': 'ready' if valid else 'login_required', 'logged_in': valid,
                'email': _safe_label(value.get('email')) if valid else None,
                'plan': _safe_label(value.get('subscriptionType')) if valid else None}

    def check(self, account):
        with self.lease(account, timeout=0): return self._check(account)

    def refresh(self, account):
        with self.lease(account, timeout=0):
            result = self._check(account)
            result.update(provider=account['provider'], fetched_at=_now(), windows=[])
            if not result['logged_in']: return result
            if account['provider'] != 'codex':
                return dict(result, error_code='quota_unavailable')
            raw = self._codex(account, 'account/rateLimits/read', {})
            buckets = raw.get('rateLimitsByLimitId')
            rate = raw.get('rateLimits', {})
            if isinstance(buckets, dict) and buckets: rate = buckets.get('codex', next(iter(buckets.values())))
            if not isinstance(rate, dict): return dict(result, error_code='quota_unavailable')
            result['plan'] = _safe_label(rate.get('planType')) or result['plan']
            for key in ('primary', 'secondary'):
                window = rate.get(key)
                if not isinstance(window, dict): continue
                used, duration, resets = (window.get(k) for k in ('usedPercent', 'windowDurationMins', 'resetsAt'))
                result['windows'].append({'name': key, 'used_percent': _number(used, 0, 100),
                                          'duration_mins': _number(duration, 0, 1e9),
                                          'resets_at': _number(resets, 0, 1e12)})
            return result

    def remove(self, account):
        profile, home = self._profile(account)
        with self.lease(account, timeout=0, recover=False):
            if self.status(account).get('status') not in _TERMINAL | {'idle'}:
                raise AccountError('Cancel the active login before removing this account.')
            # Every native command first creates its provider home. Only our
            # own untouched metadata proves native storage was never prepared;
            # missing credential files alone cannot rule out a Keychain login.
            untouched = type(account.get('generation')) is int and account['generation'] == 0 and all(
                path.name in ('profile.json', '.credential.lock') for path in home.iterdir())
            self._recover(profile, home, discard=True)
            if account['provider'] == 'claude' and not untouched:
                # Native logout owns the account-scoped Keychain item on macOS
                # and the credential file elsewhere. Never call security(1) or
                # delete/overwrite a default CLI's login ourselves.
                environment = self.environment(account)
                command = self._command(account)[:-3] + ['auth', 'logout']
                _bounded_command(command, environment, environment['AGENTDOCK_ACCOUNT_HOME'], require_success=True, stop=self.stop)
            shutil.rmtree(home)


def _safe_label(value):
    if not isinstance(value, str) or len(value) > 254 or re.search(r'[\x00-\x1f\x7f]', value): return None
    if re.search(r'\b(?:sk-|eyJ)[A-Za-z0-9_-]{16,}', value): return None
    return value


def _number(value, minimum, maximum):
    return value if type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum else None


def _bounded_command(command, environment, cwd, require_success=False, *, stop=None):
    from .processes import stop_group
    stop = stop if stop is not None else threading.Event()
    if stop.is_set(): raise AccountError('Account operation cancelled.')
    environment = dict(environment)
    inherited = environment.pop('AGENTDOCK_ACCOUNT_LOCK_FD', None)
    descriptors = (int(inherited),) if inherited is not None else ()
    try:
        process = subprocess.Popen(command, env=environment, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
                                   pass_fds=descriptors)
    except OSError: raise AccountError('Could not start the native account command.') from None
    output, deadline = bytearray(), time.monotonic() + 15
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                if stop.is_set(): raise AccountError('Account operation cancelled.')
                if time.monotonic() >= deadline: raise AccountError('Native account status timed out.')
                if not selector.select(.1): continue
                data = os.read(process.stdout.fileno(), 8192)
                if not data: break
                output.extend(data)
                if len(output) > 65536: raise AccountError('Native account status exceeded its size limit.')
        while process.poll() is None:
            if stop.wait(.05): raise AccountError('Account operation cancelled.')
            if time.monotonic() >= deadline: raise AccountError('Native account command timed out.')
        code = process.returncode
        if require_success and code != 0: raise AccountError('Native account logout failed. The account was retained.')
        return output.decode('utf-8', errors='replace')
    finally:
        stop_group(process)
        process.stdout.close()


def _login_worker(root, account_id, job_id):
    """Detached, bounded worker. stdout/stderr are never persisted or returned."""
    from .processes import stop_group
    manager = AccountManager(root)
    home = manager.root / _identity(account_id)
    profile = _read(home / 'profile.json')
    _identity(job_id)
    process = None
    master = None
    job = _read(home / 'login.json')
    if not isinstance(job, dict) or job.get('id') != job_id: return
    manager.commands_config = job.get('commands_config', {})
    cancel = home / ('cancel-' + job_id + '.json')
    inbox = home / ('input-' + job_id + '.json')
    try:
        with manager.lease(profile, timeout=10) as lock_fd, ExitStack() as cleanup:
            # A delayed worker may resume after its stale job was replaced.
            # The lease protects native credentials; the job identity protects
            # a newer login from an obsolete worker and its terminal status.
            current = _read(home / 'login.json', {})
            if current.get('id') != job_id: return
            job.update(status='waiting', heartbeat=time.time(), updated_at=_now())
            _write(home / 'login.json', job)
            environment = manager.environment(profile)
            environment.pop('AGENTDOCK_ACCOUNT_LOCK_FD', None)
            master, slave = pty.openpty()
            attr = termios.tcgetattr(slave)
            attr[3] &= ~termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, attr)
            try:
                process = subprocess.Popen(job['command'], env=environment, cwd=environment['AGENTDOCK_ACCOUNT_HOME'],
                                           stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                                           pass_fds=(lock_fd,))
                cleanup.callback(stop_group, process)
            finally: os.close(slave)
            deadline, heartbeat, text = time.monotonic() + 300, 0, ''
            with selectors.DefaultSelector() as selector:
                selector.register(master, selectors.EVENT_READ)
                while process.poll() is None:
                    if cancel.exists():
                        job.update(status='cancelled'); break
                    if time.monotonic() >= deadline:
                        job.update(status='failed', error_code='login_timeout'); break
                    if inbox.exists():
                        code = _read(inbox)
                        inbox.unlink()
                        if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9._~+/=#-]{8,2048}', code):
                            os.write(master, (code + '\n').encode())
                    if selector.select(.1):
                        try: chunk = os.read(master, 8192)
                        except OSError as exc:
                            if exc.errno == errno.EIO: chunk = b''
                            else: raise
                        text = (text + chunk.decode('utf-8', errors='replace'))[-16384:]
                        job.update(_login_hints(text))
                    if time.monotonic() - heartbeat > .5:
                        job.update(heartbeat=time.time(), updated_at=_now())
                        _write(home / 'login.json', job)
                        heartbeat = time.monotonic()
            if job['status'] not in _TERMINAL:
                if process.returncode == 0 and manager._check(profile)['logged_in']:
                    job['status'] = 'completed'
                else: job.update(status='failed', error_code='login_not_confirmed')
    except Exception:
        job.update(status='failed', error_code='native_login_failed')
    finally:
        if process is not None: stop_group(process)
        if master is not None: os.close(master)
        for path in (cancel, inbox): path.unlink(missing_ok=True)
        # Keep only safe public metadata at completion, never the command/output.
        job = dict(_public_job(job), heartbeat=time.time(), updated_at=_now())
        job.pop('url', None); job.pop('device_code', None)
        current = _read(home / 'login.json', {})
        if current.get('id') == job_id:
            _write(home / 'login.json', job)


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '_login':
        _login_worker(*sys.argv[2:])
    else:
        raise SystemExit(2)
