"""Explicit native-client login switching, separate from managed task credentials.

Saved native logins are captured from their own client, never copied from a
managed account. This avoids two independent clients rotating the same OAuth
refresh token. No background task reads or writes a native login.
"""
import base64
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .accounts import AccountError, _directory, _identity, _now, _read, _safe_label, _write
from .account_keychain import Keychain, KeychainError, claude_service
from . import credential_broker
from .account_network import claude_network, claude_get, NetworkError
from .registry import commands

_AUTH_KEYS = ('oauth:tokenCache', 'oauth:tokenCacheV2', 'lastKnownAccountUuid')
_COOKIES = ('Cookies', 'Cookies-journal', 'Cookies-wal', 'Cookies-shm',
            'Network/Cookies', 'Network/Cookies-journal', 'Network/Cookies-wal', 'Network/Cookies-shm')
_BUNDLES = {'codex': 'com.openai.codex', 'claude_code': 'com.anthropic.claudefordesktop',
            'claude_desktop': 'com.anthropic.claudefordesktop'}
_CLIENTS = {'codex': ('codex',), 'claude': ('claude_code', 'claude_desktop')}
_MAX = 64 * 1024 * 1024


def _bytes(path, limit=_MAX):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise AccountError('Native login files must not contain symbolic links.')
    try:
        with path.open('rb') as handle: data = handle.read(limit + 1)
    except FileNotFoundError: return None
    if len(data) > limit: raise AccountError('Native login storage exceeded its size limit.')
    return data


def _atomic(path, data, limit=_MAX):
    _bytes(path, limit)  # Refuse links before touching an existing native path.
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try: os.fsync(parent)
        finally: os.close(parent)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _encode(data): return base64.b64encode(data).decode() if data is not None else None
def _decode(data): return base64.b64decode(data, validate=True) if data is not None else None


def _json(data):
    value = json.loads(data or b'{}')
    if not isinstance(value, dict): raise AccountError('Unsupported native login format.')
    return value


def _email(value):
    if not isinstance(value, str) or not re.fullmatch(r'[^\s@]{1,128}@[^\s@]{1,128}', value):
        raise AccountError('Cannot verify the native account email. Sign in in that client first.')
    return value


def _codex_identity(value):
    if value.get('auth_mode') not in (None, 'chatgpt') or value.get('OPENAI_API_KEY'):
        raise AccountError('Only subscription logins can be saved here.')
    tokens = value.get('tokens') or {}
    try:
        part = tokens['id_token'].split('.')[1]
        claims = _json(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        account_id = tokens.get('account_id') or claims['https://api.openai.com/auth']['chatgpt_account_id']
        if not isinstance(account_id, str) or not account_id: raise ValueError()
        return {'email': _email(claims.get('email')), 'account_id': account_id}
    except (KeyError, ValueError, IndexError, AttributeError):
        raise AccountError('Cannot identify the native Codex subscription login.') from None


def _desktop_token(cache, account_id):
    """Decode Electron safeStorage only in memory; saved snapshots stay encrypted."""
    encrypted = _decode(cache)
    if not encrypted or encrypted[:3] != b'v10' or len(encrypted[3:]) % 16:
        raise AccountError('This Claude desktop login format is not supported.')
    password = Keychain().read('Claude Safe Storage', 'Claude')
    if password is None: raise KeychainError()
    key = hashlib.pbkdf2_hmac('sha1', password, b'saltysalt', 1003, 16)
    library = ctypes.CDLL('/usr/lib/system/libcommonCrypto.dylib')
    library.CCCrypt.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                               ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                               ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    output = ctypes.create_string_buffer(len(encrypted))
    count = ctypes.c_size_t()
    if library.CCCrypt(1, 0, 1, key, 16, b' ' * 16, encrypted[3:], len(encrypted)-3,
                       output, len(output), ctypes.byref(count)):
        raise AccountError('Cannot read the Claude desktop login.')
    values = _json(output.raw[:count.value])
    candidates = [v for k, v in values.items() if k.startswith('acct:' + account_id + '|') and 'user:profile' in k
                  and isinstance(v, dict) and isinstance(v.get('expiresAt'), (int, float))
                  and v['expiresAt'] > time.time() * 1000 and isinstance(v.get('token'), str)]
    if not candidates: raise AccountError('Open Claude desktop to refresh its login, then save it again.')
    return max(candidates, key=lambda v: v['expiresAt'])['token']


class MacClients:
    """All native paths are derived locally, never accepted from an HTTP request."""
    def __init__(self, commands_config=None, home=None, environment=None):
        self.home = Path(home or Path.home()).resolve()
        self.environment = dict(os.environ if environment is None else environment)
        self.commands_config = commands_config or {}

    def _home(self, client):
        if client == 'codex':
            # Desktop normally shares ~/.codex. Do not assume a CLI override
            # also applies to a desktop launched by Launch Services.
            home = Path(self.environment.get('CODEX_HOME') or self.home / '.codex').expanduser()
            if home.resolve() != (self.home / '.codex').resolve():
                raise AccountError('Native desktop switching requires the default Codex home.')
            return home
        if client == 'claude_code': return Path(self.environment.get('CLAUDE_CONFIG_DIR') or self.home / '.claude').expanduser()
        return self.home / 'Library/Application Support/Claude'

    def _subscription_only(self, client):
        if client != 'claude_code': return
        keys = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
                'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
        values = dict(self.environment)
        home = self._home(client)
        for name in ('settings.json', 'settings.local.json'):
            config = _json(_bytes(home / name))
            if config.get('apiKeyHelper'): raise AccountError('The native Claude CLI uses an API key helper. Subscription switching is unavailable.')
            values.update(config.get('env', {}))
        metadata = _json(_bytes(home / '.claude.json' if self.environment.get('CLAUDE_CONFIG_DIR') else self.home / '.claude.json'))
        if any(values.get(key) for key in keys) or metadata.get('primaryApiKey'):
            raise AccountError('The native Claude CLI uses an API key or Relay. Its configuration has not been changed.')

    def _codex_store(self):
        home = self._home('codex')
        text = (_bytes(home / 'config.toml') or b'').decode()
        # Read top-level scalar keys only, without needing a TOML dependency on
        # Python 3.9. Anything ambiguous is rejected rather than rewritten.
        top = re.split(r'^\s*\[', text, maxsplit=1, flags=re.M)[0]
        def scalar(key, default):
            entries = re.findall(r'^\s*' + key + r'\s*=\s*[\"\']([^\"\']+)[\"\']\s*(?:#.*)?$', top, re.M)
            if len(entries) > 1 or (re.search(r'^\s*' + key + r'\s*=', top, re.M) and not entries):
                raise AccountError('Unsupported native Codex credential configuration.')
            return entries[0] if entries else default
        mode = scalar('cli_auth_credentials_store', 'file')
        if scalar('model_provider', 'openai') != 'openai':
            raise AccountError('The native Codex CLI uses a custom provider. Its configuration has not been changed.')
        if mode not in ('file', 'keyring', 'auto') or scalar('auth_keyring_backend', 'direct') != 'direct':
            raise AccountError('This Codex credential store is not supported for native switching.')
        return mode, ('Codex Auth', 'cli|' + hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:16])

    def read(self, client):
        self._subscription_only(client)
        home = self._home(client)
        if client == 'codex':
            mode, slot = self._codex_store()
            keychain = Keychain().read(*slot) if mode in ('keyring', 'auto') else None
            auth = _bytes(home / 'auth.json')
            return {'auth': _encode(auth), 'keychain': _encode(keychain), 'mode': mode}
        if client == 'claude_code':
            slot = claude_service(self.environment)
            keychain = Keychain().read(*slot)
            config_path = home / '.claude.json' if self.environment.get('CLAUDE_CONFIG_DIR') else self.home / '.claude.json'
            metadata = _json(_bytes(config_path))
            return {'auth': _encode(_bytes(home / '.credentials.json')), 'keychain': _encode(keychain),
                    'oauthAccount': metadata.get('oauthAccount')}
        config = _json(_bytes(home / 'config.json'))
        return {'config': {k: config[k] for k in _AUTH_KEYS if k in config},
                'cookies': {k: _encode(_bytes(home / k)) for k in _COOKIES}}

    def write(self, client, snapshot):
        home = self._home(client)
        if client == 'codex':
            mode, slot = self._codex_store()
            if mode != snapshot['mode']: raise AccountError('Codex credential storage changed. Save this login again.')
            if mode in ('keyring', 'auto'): Keychain().write(*slot, _decode(snapshot['keychain']))
            _atomic(home / 'auth.json', _decode(snapshot['auth']))
        elif client == 'claude_code':
            Keychain().write(*claude_service(self.environment), _decode(snapshot['keychain']))
            _atomic(home / '.credentials.json', _decode(snapshot['auth']))
            config_path = home / '.claude.json' if self.environment.get('CLAUDE_CONFIG_DIR') else self.home / '.claude.json'
            config = _json(_bytes(config_path))
            if snapshot['oauthAccount'] is None: config.pop('oauthAccount', None)
            else: config['oauthAccount'] = snapshot['oauthAccount']
            _atomic(config_path, json.dumps(config, ensure_ascii=False, indent=2).encode())
        else:
            config = _json(_bytes(home / 'config.json'))
            for key in _AUTH_KEYS:
                if key in snapshot['config']: config[key] = snapshot['config'][key]
                else: config.pop(key, None)
            for name in _COOKIES: _atomic(home / name, _decode(snapshot['cookies'].get(name)))
            _atomic(home / 'config.json', json.dumps(config, ensure_ascii=False, indent=2).encode())

    def identity(self, client, snapshot, *, online=False):
        if client == 'codex':
            active = snapshot['keychain'] if snapshot['mode'] == 'keyring' else snapshot['keychain'] or snapshot['auth']
            return _codex_identity(_json(_decode(active)))
        if client == 'claude_code':
            metadata = snapshot.get('oauthAccount') or {}
            if not online and metadata.get('accountUuid') and metadata.get('emailAddress'):
                return {'email': _email(metadata['emailAddress']), 'account_id': metadata['accountUuid'],
                        'organization_id': metadata.get('organizationUuid')}
            credentials = _json(_decode(snapshot['keychain'] or snapshot['auth']))
            token = credentials.get('claudeAiOauth', {}).get('accessToken')
            if not token: raise AccountError('Sign in to Claude Code with a subscription first.')
        else:
            config = snapshot['config']
            token = _desktop_token(config.get('oauth:tokenCacheV2'), config.get('lastKnownAccountUuid', ''))
        network = claude_network(self.environment, commands(self.commands_config).get('claude', ()), strict=True)
        try: profile = claude_get('profile', token, network)
        except NetworkError: raise AccountError('Cannot verify the native Claude login through its existing network configuration.') from None
        value = profile.get('account', {})
        identifier = value.get('uuid')
        if not isinstance(identifier, str) or not identifier: raise AccountError('Cannot identify this native login.')
        if client == 'claude_desktop' and identifier != snapshot['config'].get('lastKnownAccountUuid'):
            raise AccountError('Claude desktop identity changed. Open it and save its login again.')
        if client == 'claude_code' and (snapshot.get('oauthAccount') or {}).get('accountUuid') not in (None, identifier):
            raise AccountError('Claude Code identity metadata is out of date. Sign in in that client and save it again.')
        return {'email': _email(value.get('email')), 'account_id': identifier,
                'organization_id': profile.get('organization', {}).get('uuid')}

    def app(self, client):
        names = ('ChatGPT.app', 'Codex.app') if client == 'codex' else ('Claude.app',)
        for parent in (Path('/Applications'), self.home / 'Applications'):
            for name in names:
                path = parent / name
                try:
                    with (path / 'Contents/Info.plist').open('rb') as handle: info = plistlib.load(handle)
                    if info.get('CFBundleIdentifier') == _BUNDLES[client]: return path
                except (OSError, ValueError, plistlib.InvalidFileException): continue
        return None

    def running(self, client):
        bundle = _BUNDLES[client]
        result = subprocess.run(['/usr/bin/osascript', '-e', 'application id "' + bundle + '" is running'],
                                capture_output=True, timeout=5)
        if result.returncode: raise AccountError('Cannot control the desktop app. Check macOS Privacy & Security > Automation for AgentDock.')
        return result.stdout.strip() == b'true'

    def stop(self, client):
        running = self.running(client) if self.app(client) else False
        # Claude Code can be running inside Claude desktop. Stopping the app
        # first also avoids switching an embedded Code task underneath it.
        if running:
            result = subprocess.run(['/usr/bin/osascript', '-e', 'tell application id "' + _BUNDLES[client] + '" to quit'],
                                    capture_output=True, timeout=20)
            if result.returncode: raise AccountError('The desktop app did not quit. Finish its tasks and try again.')
            deadline = time.monotonic() + 10
            while self.running(client):
                if time.monotonic() >= deadline: raise AccountError('The desktop app is still running. No login was changed.')
                time.sleep(.1)
        try: self.ensure_idle(client)
        except Exception:
            if running: self.start(client)
            raise
        return running

    def ensure_idle(self, client):
        result = subprocess.run(['/bin/ps', '-axo', 'comm=,args='], capture_output=True, timeout=5)
        if result.returncode: raise AccountError('Cannot check active CLI tasks.')
        names = {'codex', 'codex-cli'} if client == 'codex' else {'claude'}
        app = self.app(client)
        for line in result.stdout.decode(errors='replace').splitlines():
            command = line.strip().split(' ', 1)[0]
            script = (r'(?:@openai/codex/[^\s]*|[/\\]codex)\.js(?:\s|$)' if client == 'codex'
                      else r'(?:@anthropic-ai/claude-code/[^\s]*|[/\\]claude)\.js(?:\s|$)')
            if (app and str(app) + '/Contents/' in line) or Path(command).name in names or (Path(command).name in ('node', 'bun') and re.search(script, line)):
                raise AccountError('A native CLI is still running. Finish and close its tasks before switching.')

    def start(self, client):
        app = self.app(client)
        if app:
            result = subprocess.run(['/usr/bin/open', str(app)], capture_output=True, timeout=10)
            if result.returncode: raise AccountError('Open the desktop app manually to confirm the restored login.')


class NativeAccounts:
    def __init__(self, manager, platform=None, vault=None):
        self.root = manager.root / 'native-clients'
        self.platform = platform or MacClients(manager.commands_config)
        self.vault = vault or credential_broker
        if self.vault.available():
            self.protect_legacy()

    def _client(self, account, client):
        if account.get('environment_id') != 'local' or client not in _CLIENTS.get(account.get('provider'), ()):
            raise AccountError('Choose a matching local native client.')
        _identity(account['id'])
        if sys.platform != 'darwin': raise AccountError('Native client switching is available on macOS.')
        if not self.vault.available():
            raise AccountError('Open AgentDock desktop to use protected native credentials.')
        return client

    @contextmanager
    def _lock(self):
        root = _directory(self.root)
        descriptor = os.open(root / '.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise AccountError('Another native account operation is running.') from None
            yield
        finally: os.close(descriptor)

    def _path(self, identifier, client): return self.root / _identity(identifier) / (client + '.json')

    def _save(self, path, value):
        _directory(path.parent)
        data = json.dumps(value).encode()
        if len(data) > _MAX: raise AccountError('Native login snapshot exceeded its size limit.')
        sealed = self.vault.seal(data, str(path.absolute()))
        public = {key: value[key] for key in ('identity', 'saved_at', 'client') if key in value}
        _atomic(path, json.dumps({'schema': 2, 'public': public, 'sealed': sealed}).encode(), limit=96 * 1024 * 1024)

    def _load(self, path):
        data = _bytes(path, 96 * 1024 * 1024)
        if data is None:
            return None
        value = _json(data)
        if value.get('schema') == 2:
            return _json(self.vault.unseal(value['sealed'], str(path.absolute())))
        # Upgrade old base64-only snapshots atomically, without a plaintext
        # backup. If Keychain authorization fails, no native login is touched.
        self._save(path, value)
        return value

    def protect_legacy(self):
        if not self.root.exists():
            return
        with self._lock():
            for path in (*self.root.glob('*/*.json'), self.root / 'previous.json', self.root / 'pending.json'):
                raw = _bytes(path, 96 * 1024 * 1024)
                if raw is not None and _json(raw).get('schema') != 2:
                    self._load(path)

    def _public(self, path):
        value = _json(_bytes(path, 96 * 1024 * 1024))
        return value.get('public') if value.get('schema') == 2 else None

    def status(self, account):
        available = sys.platform == 'darwin' and account['environment_id'] == 'local' and self.vault.available()
        if available:
            self.protect_legacy()
        clients = []
        for client in _CLIENTS.get(account['provider'], ()):
            saved = self._public(self._path(account['id'], client)) if available else None
            clients.append({'id': client, 'saved': bool(saved), 'saved_at': saved.get('saved_at') if saved else None,
                            'identity': saved.get('identity') if saved else None})
        pending = self._public(self.root / 'pending.json')
        previous = pending or self._public(self.root / 'previous.json')
        return {'available': available, 'clients': clients, 'recovery_needed': bool(pending),
                'recovery_client': previous.get('client') if previous else None}

    @staticmethod
    def _match(account, identity):
        expected = (account.get('identity') or {}).get('email')
        if not expected: raise AccountError('Sign in to this AgentDock account before saving a native login.')
        if expected.casefold() != identity['email'].casefold():
            raise AccountError('The native client is signed in to a different account. Choose its matching account card.')

    def capture(self, account, client):
        self._client(account, client)
        with self._lock():
            if (self.root / 'pending.json').exists(): raise AccountError('Recover the previous native login operation first.')
            running = self.platform.stop(client)
            try:
                snapshot = self.platform.read(client)
                identity = self.platform.identity(client, snapshot, online=True)
                self._match(account, identity)
                for path in self.root.glob('*/' + client + '.json'):
                    existing = self._load(path)
                    if path != self._path(account['id'], client) and existing and existing['identity']['account_id'] == identity['account_id']:
                        raise AccountError('This native login is already saved on another account card.')
                if self.platform.read(client) != snapshot: raise AccountError('The native login changed while saving. Try again.')
                if client in ('codex', 'claude_code') and snapshot.get('keychain'): snapshot = {**snapshot, 'auth': None}
                self._save(self._path(account['id'], client), {'identity': identity, 'snapshot': snapshot, 'saved_at': _now()})
            finally:
                if running: self.platform.start(client)
        return self.status(account)

    def _preserve_current(self, client, snapshot):
        # Save rotated credentials back to the matching native profile before
        # replacing them. Never update a profile by a stale "current" pointer.
        if client == 'claude_desktop':
            identifier = snapshot.get('config', {}).get('lastKnownAccountUuid')
        else:
            try: identifier = self.platform.identity(client, snapshot, online=client == 'claude_code')['account_id']
            except (AccountError, KeychainError, ValueError):
                if snapshot.get('auth') or snapshot.get('keychain'):
                    raise AccountError('Cannot identify the current login safely. Open the native client and sign in again.') from None
                return
        if client in ('codex', 'claude_code') and snapshot.get('keychain'): snapshot = {**snapshot, 'auth': None}
        for path in self.root.glob('*/' + client + '.json'):
            saved = self._load(path)
            if saved and saved['identity']['account_id'] == identifier:
                saved.update(snapshot=snapshot, saved_at=_now())
                self._save(path, saved)

    def switch(self, account, client):
        self._client(account, client)
        with self._lock():
            journal_path = self.root / 'pending.json'
            if journal_path.exists(): raise AccountError('Recover the previous native login operation first.')
            target = self._load(self._path(account['id'], client))
            if not target: raise AccountError('Save this account from the native client before switching to it.')
            self._match(account, target['identity'])
            running = self.platform.stop(client)
            writing = False
            try:
                previous = self.platform.read(client)
                self._preserve_current(client, previous)
                # The target might have been the active account, freshly saved.
                target = self._load(self._path(account['id'], client))
                self._save(journal_path, {'client': client, 'snapshot': previous, 'was_running': running})
                self.platform.ensure_idle(client)
                if self.platform.read(client) != previous: raise AccountError('The native login changed. Try again after closing the client.')
                writing = True
                self.platform.write(client, target['snapshot'])
                if self.platform.read(client) != target['snapshot']: raise AccountError('Native login verification failed.')
                self._save(self.root / 'previous.json', {'client': client, 'snapshot': previous, 'was_running': running})
                journal_path.unlink()
            except Exception:
                if journal_path.exists() and writing:
                    try:
                        self.platform.write(client, previous)
                        if self.platform.read(client) != previous: raise AccountError('Native login recovery failed.')
                        journal_path.unlink()
                    except Exception:
                        raise AccountError('Native switch failed. Use Recover previous login before trying again.') from None
                elif journal_path.exists(): journal_path.unlink()
                raise
            finally:
                if running and not journal_path.exists(): self.platform.start(client)
        return {**self.status(account), 'result': 'restored', 'login_confirmation': 'client_required'}

    def recover(self, account, client):
        self._client(account, client)
        with self._lock():
            path = self.root / 'pending.json'
            if not path.exists(): path = self.root / 'previous.json'
            previous = self._load(path)
            if not previous or previous.get('client') != client: raise AccountError('No recovery snapshot is available for this client.')
            running = self.platform.stop(client)
            restored = False
            try:
                self.platform.write(client, previous['snapshot'])
                if self.platform.read(client) != previous['snapshot']: raise AccountError('Native login recovery failed.')
                path.unlink()
                restored = True
            finally:
                if restored and (running or previous['was_running']): self.platform.start(client)
        return self.status(account)

    @contextmanager
    def removing(self, account):
        with self._lock():
            if (self.root / 'pending.json').exists(): raise AccountError('Recover the interrupted native switch before deleting accounts.')
            path = self.root / _identity(account['id'])
            if path.is_symlink(): raise AccountError('Invalid native login storage.')
            yield
            if path.exists(): shutil.rmtree(path)
            (self.root / 'previous.json').unlink(missing_ok=True)

    def remove(self, account):
        with self.removing(account): pass
