"""Account control plane: public metadata stays here, credentials stay on their device."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import threading
import time

from .accounts import AccountManager, AccountError
from .store import Conflict, Forbidden, Invalid


def account_usage(store, accounts):
    """Attribute all native branches to their account without mixing logins."""
    with store.lock:
        rows = store._all('''SELECT b.account_id, SUM(t.input_tokens) AS input_tokens,
            SUM(t.output_tokens) AS output_tokens, SUM(t.total_tokens) AS total_tokens
            FROM session_account_branches b JOIN sessions s ON s.id=b.session_id
            JOIN agents a ON a.id=s.agent_id JOIN token_records t ON t.provider=a.provider
            AND t.native_id=CASE WHEN s.environment_id='local' THEN b.native_session_id
                                ELSE s.environment_id || ':' || b.native_session_id END
            WHERE b.account_id IS NOT NULL GROUP BY b.account_id''')
    totals = {row.pop('account_id'): row for row in rows}
    return [{**a, 'usage': totals.get(a['id'], {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0})}
            for a in accounts]


class AccountService:
    def __init__(self, store, runtime):
        self.store, self.runtime = store, runtime
        self.manager = AccountManager(store.workspaces.parent / 'accounts', runtime.config.get('commands', {}))
        from .native_accounts import NativeAccounts
        self.native = NativeAccounts(self.manager)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._refreshing = {}
        self._refresh_after = {}
        self._failures = {}

    def _enabled(self):
        if not self.runtime.enabled or self._stop.is_set():
            raise Forbidden('Account operations require execution to be enabled')

    def _call(self, account, operation, **arguments):
        self._enabled()
        if account['status'] == 'removed': raise Conflict('This account was removed; choose another account')
        if account['environment_id'] != 'local':
            return self.runtime.remote.rpc(account['environment_id'], {
                'op': 'account', 'controller': self.store.controller_id,
                'account': {'id': account['id'], 'provider': account['provider'], 'generation': account['generation']},
                'action': operation, **arguments}, install=True)
        method = getattr(self.manager, operation)
        return method(account, **arguments)

    def watch(self):
        if not self.runtime.enabled: return
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._monitor, daemon=True, name='agentdock-accounts')
                self._thread.start()

    def _monitor(self):
        # Login completion survives a closed panel. Refresh never submits a task.
        while not self._stop.wait(2):
            for account in self.store.accounts():
                if self._stop.is_set(): return
                if account['provider'] == 'claude' and account['status'] != 'pending' and not self.store.features()['claude_quota']: continue
                try:
                    if account['status'] == 'pending': self.login_status(account['id'])
                    elif account['status'] in ('ready', 'cooldown') and time.monotonic() >= self._refresh_after.get(account['id'], 0):
                        self.refresh(account['id'])
                except Exception:
                    # Login/transport diagnostics are intentionally not logged.
                    continue

    def start_login(self, identifier, method=None):
        self._enabled()
        with self._lock:
            account = self.store.get_account(identifier)
            if method is None:
                method = 'device' if account['environment_id'] != 'local' and account['provider'] == 'codex' else 'browser'
            if account['environment_id'] != 'local' and account['provider'] == 'codex' and method != 'device':
                raise Invalid('Use device-code sign-in for Codex on an SSH device')
            if account['status'] in ('disabled', 'removed'):
                raise Conflict('Enable this account before signing in')
            pending = self.store.set_account_status(identifier, 'pending')
            try: job = self._call(account, 'start', method=method)
            except Exception:
                with self.store.lock:
                    if self._unchanged(pending, self.store.get_account(identifier)):
                        self.store.set_account_status(identifier, account['status'], error=account.get('error'),
                                                      cooldown_until=account.get('cooldown_until'))
                raise
        self.watch()
        return job

    def login_status(self, identifier):
        account = self.store.get_account(identifier)
        job = self._call(account, 'status')
        if job.get('status') == 'completed':
            with self._lock:
                current = self.store.get_account(identifier)
                if self._unchanged(account, current) and current['status'] == 'pending':
                    self.check(identifier)
                    if self.store.get_account(identifier)['status'] == 'ready':
                        self._refresh_after.pop(identifier, None)
                        self.runtime._wake.set()
        elif job.get('status') in ('failed', 'cancelled'):
            with self._lock, self.store.lock:
                current = self.store.get_account(identifier)
                if self._unchanged(account, current) and current['status'] == 'pending':
                    self.store.set_account_status(identifier, 'expired', error='login_required')
        return job

    def cancel(self, identifier):
        return self._call(self.store.get_account(identifier), 'cancel')

    def submit(self, identifier, code):
        return self._call(self.store.get_account(identifier), 'submit', code=code)

    @staticmethod
    def _unchanged(before, after):
        # Native checks can take seconds. UI changes and a newer login must win
        # over their old response, including disable/re-enable with the same
        # generation. The Store lock at the write site makes this comparison
        # and the resulting metadata update atomic with Store callers.
        return all(before.get(key) == after.get(key) for key in ('generation', 'status', 'updated_at'))

    def check(self, identifier):
        account = self.store.get_account(identifier)
        value = self._call(account, 'check')
        with self._lock, self.store.lock:
            current = self.store.get_account(identifier)
            if not self._unchanged(account, current) or current['status'] in ('disabled', 'removed'): return value
            if value.get('logged_in') is True:
                if hasattr(self.store, 'set_account_identity'):
                    self.store.set_account_identity(identifier, {'email': value.get('email'), 'plan': value.get('plan')})
                if current['generation'] == 0 or current['status'] in ('pending', 'expired'):
                    self.store.complete_account_login(identifier)
                    self._refresh_after.pop(identifier, None)
                    self._failures.pop(identifier, None)
                elif current['status'] != 'cooldown': self.store.set_account_status(identifier, 'ready')
            else: self.store.set_account_status(identifier, 'expired', error='login_required')
        return value

    @staticmethod
    def _quota(value):
        windows = []
        for item in value.get('windows', [])[:10]:
            used = item.get('used_percent')
            if not isinstance(used, (int, float)) or isinstance(used, bool) or not 0 <= used <= 100: continue
            window = {'name': item.get('name', 'primary'), 'remaining_percent': 100-used}
            reset = item.get('resets_at')
            if isinstance(reset, (int, float)):
                try: reset = datetime.fromtimestamp(reset, timezone.utc).isoformat()
                except (ValueError, OverflowError, OSError): reset = None
            if isinstance(reset, str): window['reset_at'] = reset
            duration = item.get('duration_mins')
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
                window['duration_minutes'] = duration
            windows.append(window)
        return {'windows': windows, 'status': 'ok' if windows else 'unknown',
                'fetched_at': value.get('fetched_at') or datetime.now(timezone.utc).isoformat()}

    def refresh(self, identifier, force=False):
        """Coalesce simultaneous readers and respect vendor retry times."""
        with self._lock:
            now = time.monotonic()
            current = self.store.get_account(identifier)
            retry = current['quota'].get('retry_at')
            if retry and datetime.fromisoformat(retry) > datetime.now(timezone.utc): return current
            if not force and now < self._refresh_after.get(identifier, 0): return current
            pending = self._refreshing.get(identifier)
            owner = pending is None
            if owner:
                pending = self._refreshing[identifier] = threading.Event()
        if not owner:
            if not pending.wait(30): raise AccountError('Quota refresh is still running. Try again shortly.')
            return self.store.get_account(identifier)
        try: return self._refresh(identifier)
        finally:
            with self._lock:
                self._refreshing.pop(identifier, None)
                pending.set()

    def _refresh(self, identifier):
        account = self.store.get_account(identifier)
        self._enabled()
        if account['provider'] == 'claude' and not self.store.features()['claude_quota']:
            return self.store.set_account_quota(identifier, {'windows': [], 'status': 'unknown', 'error_code': 'experimental_disabled'})
        try: value = self._call(account, 'refresh')
        except (AccountError, OSError, TimeoutError):
            value = {'windows': [], 'error_code': 'quota_unavailable'}
        with self._lock, self.store.lock:
            current = self.store.get_account(identifier)
            if not self._unchanged(account, current) or current['status'] in ('disabled', 'removed'):
                return current
            if value.get('logged_in') is False:
                return self.store.set_account_status(identifier, 'expired', error='login_required')
            quota = self._quota(value)
            if not quota['windows'] and current['quota'].get('windows'):
                quota = {**current['quota'], 'status': 'stale'}
            error = value.get('error_code') or (None if quota['status'] == 'ok' else 'quota_unavailable')
            quota['checked_at'] = datetime.now(timezone.utc).isoformat()
            if error:
                self._failures[identifier] = min(6, self._failures.get(identifier, 0) + 1)
                seconds = max(60 * 2 ** (self._failures[identifier] - 1), value.get('retry_after', 0))
                quota.update(error_code=error, retry_at=(datetime.now(timezone.utc) + timedelta(seconds=min(86400, seconds))).isoformat())
                if not quota['windows']: quota['status'] = 'error'
            else:
                self._failures.pop(identifier, None)
                seconds = 600
            self._refresh_after[identifier] = time.monotonic() + seconds
            if hasattr(self.store, 'set_account_identity') and value.get('email'):
                self.store.set_account_identity(identifier, {'email': value.get('email'), 'plan': value.get('plan')})
            result = self.store.set_account_quota(identifier, quota)
            resets = [w.get('reset_at') for w in quota['windows'] if w['remaining_percent'] <= 0 and w.get('reset_at')
                      and w.get('name') not in ('weekly_sonnet', 'weekly_opus')]
            if resets and current['status'] in ('ready', 'cooldown'):
                result = self.store.set_account_status(identifier, 'cooldown', cooldown_until=max(resets))
            elif quota['status'] == 'ok' and quota['windows'] and current['status'] == 'cooldown':
                result = self.store.set_account_status(identifier, 'ready')
            return result

    def remove(self, identifier):
        self._enabled()
        with self._lock:
            account = self.store.get_account(identifier)
            def cleanup(_):
                if account['environment_id'] == 'local':
                    with self.native.removing(account): self._call(account, 'remove')
                else: self._call(account, 'remove')
            return self.store.remove_account(identifier, cleanup=cleanup)

    def native_status(self, identifier):
        self._enabled()
        self.store.require_feature('native_switching')
        return self.native.status(self.store.get_account(identifier))

    def native_action(self, identifier, operation, client):
        self._enabled()
        self.store.require_feature('native_switching')
        if operation not in ('capture', 'switch', 'recover'): raise Invalid('Invalid native account operation')
        with self._lock:
            account = self.store.get_account(identifier)
            if account['environment_id'] != 'local' or account['status'] in ('disabled', 'removed'):
                raise Conflict('Choose an enabled local account')
            with self.manager.lease(account, timeout=0):
                # Account task credentials and native credentials never overlap;
                # the lease prevents deletion/re-login of the selected card.
                return getattr(self.native, operation)(account, client)

    @contextmanager
    def credentials(self, account, session_home, stop):
        if account['environment_id'] != 'local': raise Invalid('Remote credentials belong on the remote device')
        with self.manager.credential_session(account, session_home, stop=stop) as environment:
            yield environment

    def models(self, account, catalog):
        self._enabled()
        if account['status'] not in ('ready', 'cooldown'):
            raise Conflict('Sign in to this account before reading its models')
        if account['environment_id'] != 'local':
            return self.runtime.remote.models(account['environment_id'], account['provider'], account=account)
        with self.manager.lease(account):
            return catalog.read(account['provider'], account_id=account['id'], generation=account['generation'],
                                environment=self.manager.environment(account))

    def close(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=2)
