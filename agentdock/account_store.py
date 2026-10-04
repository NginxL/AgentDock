"""Account metadata and immutable execution identities; credentials never enter SQLite."""
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone


class AccountStore:
    def _migrate_accounts(self):
        with self.transaction():
            self.db.execute('''CREATE TABLE IF NOT EXISTS accounts(
                id TEXT PRIMARY KEY,label TEXT NOT NULL,provider TEXT NOT NULL,
                environment_id TEXT NOT NULL REFERENCES environments(id),status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,quota TEXT NOT NULL DEFAULT '{}',generation INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 0,cooldown_until TEXT,last_used_at TEXT,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            if 'identity' not in {row[1] for row in self.db.execute('PRAGMA table_info(accounts)')}:
                self.db.execute("ALTER TABLE accounts ADD COLUMN identity TEXT NOT NULL DEFAULT '{}'")
            for table in ('agents', 'sessions', 'runs'):
                fields = {'account_id': 'TEXT REFERENCES accounts(id)',
                          'account_policy': "TEXT NOT NULL DEFAULT 'manual'",
                          'account_ids': "TEXT NOT NULL DEFAULT '[]'"}
                if table != 'agents':
                    fields.update(account_generation='INTEGER NOT NULL DEFAULT 0', account_branch='INTEGER NOT NULL DEFAULT 0')
                if table == 'runs':
                    fields.update(account_selection_pending='INTEGER NOT NULL DEFAULT 0', next_attempt_at='TEXT')
                columns = {row[1] for row in self.db.execute('PRAGMA table_info(' + table + ')')}
                for name, definition in fields.items():
                    if name not in columns:
                        self.db.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + name + ' ' + definition)
            self.db.execute('''CREATE TABLE IF NOT EXISTS session_account_branches(
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,branch INTEGER NOT NULL,
                account_id TEXT REFERENCES accounts(id),generation INTEGER NOT NULL DEFAULT 0,
                native_session_id TEXT,created_at TEXT NOT NULL,PRIMARY KEY(session_id,branch))''')
            self.db.execute('''INSERT OR IGNORE INTO session_account_branches
                SELECT id,account_branch,account_id,account_generation,native_session_id,created_at FROM sessions''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS run_attempts(
                id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                number INTEGER NOT NULL,account_id TEXT REFERENCES accounts(id),generation INTEGER NOT NULL,
                account_branch INTEGER NOT NULL,status TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,created_at TEXT NOT NULL,finished_at TEXT,UNIQUE(run_id,number))''')
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_account_attempt ON run_attempts(run_id) WHERE status='running'")
            # A restarted process must never silently replay an interrupted attempt.
            self.db.execute("UPDATE run_attempts SET status='interrupted',finished_at=? WHERE status='running'", (self._account_now(),))

    @staticmethod
    def _account_now():
        return datetime.now(timezone.utc).isoformat(timespec='microseconds')

    @staticmethod
    def _account_error(code):
        from .store import Invalid
        if code is not None and (not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_.:-]{0,79}', code)):
            raise Invalid('Use a public account error code, never credential or CLI output')
        return code

    @staticmethod
    def _account_date(value):
        from .store import Invalid
        if value is None: return None
        try:
            if not isinstance(value, str) or len(value) > 64: raise ValueError()
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None: raise ValueError()
            return parsed.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            raise Invalid('Use a timezone-aware account timestamp') from None

    def accounts(self, provider=None, environment_id=None, include_removed=False):
        with self.lock:
            return self._all("SELECT * FROM accounts WHERE (? IS NULL OR provider=?) AND (? IS NULL OR environment_id=?) AND (? OR status<>'removed') ORDER BY priority DESC,created_at,id",
                             (provider, provider, environment_id, environment_id, include_removed))

    def get_account(self, account_id):
        with self.lock: return self._one('accounts', account_id)

    def session_accounts(self, session_id):
        """Include retired branches and removed account metadata during cleanup."""
        with self.lock:
            self._one('sessions', session_id)
            return self._all('''SELECT DISTINCT accounts.* FROM accounts
                JOIN session_account_branches AS branch ON branch.account_id=accounts.id
                WHERE branch.session_id=? ORDER BY accounts.id''', (session_id,))

    def add_account(self, provider, label, environment_id='local', priority=0):
        from .store import Invalid, text
        if provider not in ('codex', 'claude'): raise Invalid('Managed accounts support Codex and Claude Code')
        if isinstance(priority, bool) or not isinstance(priority, int) or not -100 <= priority <= 100:
            raise Invalid('Account priority must be between -100 and 100')
        with self.transaction():
            self._one('environments', environment_id)
            timestamp = self._account_now()
            item = dict(id=str(uuid.uuid4()), label=text(label, 'label', 100), provider=provider,
                        environment_id=environment_id, priority=priority, created_at=timestamp, updated_at=timestamp)
            self.db.execute('''INSERT INTO accounts(id,label,provider,environment_id,priority,created_at,updated_at)
                VALUES(:id,:label,:provider,:environment_id,:priority,:created_at,:updated_at)''', item)
            return self._one('accounts', item['id'])

    def _account_in_use(self, account_id):
        return self.db.execute("SELECT 1 FROM runs WHERE account_id=? AND status IN ('queued','running')", (account_id,)).fetchone() is not None

    def update_account(self, account_id, changes):
        from .store import Invalid, Conflict, text
        if not isinstance(changes, dict) or not changes or set(changes) - {'label', 'priority', 'status', 'enabled'}:
            raise Invalid('Only account label, priority and enabled status can be changed')
        changes = dict(changes)
        if 'enabled' in changes:
            if not isinstance(changes['enabled'], bool) or 'status' in changes: raise Invalid('Invalid account enabled setting')
            changes['status'] = 'ready' if changes.pop('enabled') else 'disabled'
        with self.transaction():
            account = self._one('accounts', account_id)
            if account['status'] == 'removed': raise Conflict('This account was removed')
            label = text(changes.get('label', account['label']), 'label', 100)
            priority = changes.get('priority', account['priority'])
            if isinstance(priority, bool) or not isinstance(priority, int) or not -100 <= priority <= 100:
                raise Invalid('Account priority must be between -100 and 100')
            status = changes.get('status', account['status'])
            if 'status' in changes:
                if status not in ('disabled', 'ready'): raise Invalid('Use enabled or disabled account status')
                if self._account_in_use(account_id): raise Conflict('Wait for account tasks before changing its enabled status')
                if status == 'ready' and account['status'] != 'disabled':
                    raise Conflict('Sign in before enabling this account')
                # Re-enabling requires native login validation, not trusting an old token.
                if status == 'ready': status = 'pending'
            self.db.execute('UPDATE accounts SET label=?,priority=?,status=?,updated_at=? WHERE id=?',
                            (label, priority, status, self._account_now(), account_id))
            return self._one('accounts', account_id)

    def set_account_status(self, account_id, status, error=None, cooldown_until=None, quota=None):
        from .store import Invalid, Conflict
        if status not in ('pending', 'ready', 'expired', 'cooldown', 'disabled'): raise Invalid('Invalid account status')
        error = self._account_error(error)
        cooldown_until = self._account_date(cooldown_until)
        if status == 'cooldown' and cooldown_until is None: raise Invalid('Account cooldown needs a reset time')
        with self.transaction():
            account = self._one('accounts', account_id)
            if account['status'] == 'removed': raise Conflict('This account was removed')
            if status in ('pending', 'disabled') and self._account_in_use(account_id):
                raise Conflict('Wait for account tasks before changing login state')
            if status == 'ready' and not account['generation']: raise Conflict('Complete account login first')
            clean_quota = self._clean_account_quota(quota) if quota is not None else account['quota']
            self.db.execute('UPDATE accounts SET status=?,error=?,cooldown_until=?,quota=?,updated_at=? WHERE id=?',
                            (status, error, cooldown_until if status == 'cooldown' else None, json.dumps(clean_quota), self._account_now(), account_id))
            return self._one('accounts', account_id)

    def complete_account_login(self, account_id):
        from .store import Conflict
        with self.transaction():
            account = self._one('accounts', account_id)
            if account['status'] == 'removed': raise Conflict('This account was removed')
            if self._account_in_use(account_id): raise Conflict('Wait for account tasks before replacing its login')
            self.db.execute("UPDATE accounts SET generation=generation+1,status='ready',error=NULL,cooldown_until=NULL,quota='{}',updated_at=? WHERE id=?",
                            (self._account_now(), account_id))
            return self._one('accounts', account_id)

    def remove_account(self, account_id, cleanup=None):
        from .store import Conflict
        with self.transaction():
            account = self._one('accounts', account_id)
            if account['status'] == 'removed': return {'ok': True}
            if self._account_in_use(account_id): raise Conflict('Wait for account tasks before removing its login')
            if cleanup is not None: cleanup(account)
            # Labels and frozen identities remain for historical attribution. Native
            # credential cleanup happens first; a failure leaves removal retryable.
            self.db.execute("UPDATE accounts SET status='removed',error=NULL,quota='{}',cooldown_until=NULL,updated_at=? WHERE id=?", (self._account_now(),account_id))
        return {'ok': True}

    def _clean_account_quota(self, quota):
        from .store import Invalid
        if not isinstance(quota, dict): raise Invalid('Invalid account quota')
        output = {}
        if 'fetched_at' in quota: output['fetched_at'] = self._account_date(quota['fetched_at'])
        if 'status' in quota:
            if quota['status'] not in ('ok', 'ready', 'unknown', 'stale', 'error', 'exhausted'): raise Invalid('Invalid quota status')
            output['status'] = quota['status']
        windows = quota.get('windows', [])
        if not isinstance(windows, list) or len(windows) > 10: raise Invalid('Invalid quota windows')
        output['windows'] = []
        for window in windows:
            if not isinstance(window, dict): raise Invalid('Invalid quota window')
            clean = {}
            for key in ('used_percent', 'remaining_percent', 'duration_minutes', 'window_minutes'):
                if key in window:
                    value = window[key]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                        raise Invalid('Invalid quota value')
                    if key.endswith('_percent') and value > 100: raise Invalid('Invalid quota percentage')
                    clean[key] = value
            for key in ('resets_at', 'reset_at'):
                if key in window: clean[key] = self._account_date(window[key])
            # Native text and arbitrary metadata can contain credentials; never persist them.
            if 'name' in window and window['name'] in ('primary', 'secondary', 'session', 'weekly', 'daily'):
                clean['name'] = window['name']
            output['windows'].append(clean)
        return output

    def set_account_quota(self, account_id, quota):
        from .store import Conflict
        clean = self._clean_account_quota(quota)
        with self.transaction():
            account = self._one('accounts', account_id)
            if account['status'] == 'removed': raise Conflict('This account was removed')
            self.db.execute('UPDATE accounts SET quota=?,updated_at=? WHERE id=?', (json.dumps(clean), self._account_now(), account_id))
            return self._one('accounts', account_id)

    def set_account_identity(self, account_id, identity):
        """Save only bounded display metadata returned by the native login check."""
        from .store import Invalid, Conflict
        if not isinstance(identity, dict): raise Invalid('Invalid account identity metadata')
        clean = {}
        email = identity.get('email')
        if email is not None:
            if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@]{1,128}@[^\s@]{1,128}', email):
                raise Invalid('Invalid account email')
            clean['email'] = email
        plan = identity.get('plan')
        if plan is not None:
            if not isinstance(plan, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._+/-]{0,79}', plan):
                raise Invalid('Invalid account plan')
            clean['plan'] = plan
        with self.transaction():
            account = self._one('accounts', account_id)
            if account['status'] == 'removed': raise Conflict('This account was removed')
            self.db.execute('UPDATE accounts SET identity=?,updated_at=? WHERE id=?', (json.dumps(clean),self._account_now(),account_id))
            return self._one('accounts', account_id)

    def _account_settings(self, provider, environment_id, account_id=None, account_policy='manual', account_ids=None):
        from .store import Invalid
        if account_policy not in ('manual', 'auto', 'failover'): raise Invalid('Invalid account policy')
        account_ids = [] if account_ids is None else account_ids
        if not isinstance(account_ids, list) or len(account_ids) > 100 or any(not isinstance(v, str) for v in account_ids) or len(set(account_ids)) != len(account_ids):
            raise Invalid('Account pool must contain unique account identities')
        if account_id is not None and not isinstance(account_id, str): raise Invalid('Invalid account identity')
        if provider not in ('codex', 'claude') and (account_id or account_ids or account_policy != 'manual'):
            raise Invalid('Managed accounts support Codex and Claude Code')
        for identifier in set(account_ids + ([account_id] if account_id else [])):
            account = self._one('accounts', identifier)
            if account['provider'] != provider or account['environment_id'] != environment_id:
                raise Invalid('Account must match this service and device')
            if account['status'] == 'removed': raise Invalid('Choose an account that has not been removed')
        if account_ids and account_id and account_id not in account_ids: raise Invalid('Default account must belong to the selected pool')
        if account_policy == 'manual' and account_ids: raise Invalid('Manual accounts do not use a pool')
        return dict(account_id=account_id, account_policy=account_policy, account_ids=list(account_ids))

    @staticmethod
    def _account_window_reset(account, window):
        reset = window.get('resets_at', window.get('reset_at'))
        value = window.get('remaining_percent', 100 - window.get('used_percent', 0))
        if not reset and value <= 0 and account['quota'].get('fetched_at'):
            # Older observations could persist a rejected limit with no native
            # reset. Use a bounded cooldown for both admission and queued retry.
            reset = (datetime.fromisoformat(account['quota']['fetched_at']) + timedelta(seconds=60)).isoformat()
        return reset

    def _account_remaining(self, account):
        remaining = []
        for window in account['quota'].get('windows', []):
            reset = self._account_window_reset(account, window)
            if reset and datetime.fromisoformat(reset) <= datetime.now(timezone.utc): continue
            if 'remaining_percent' in window: remaining.append(window['remaining_percent'])
            elif 'used_percent' in window: remaining.append(100 - window['used_percent'])
        return min(remaining) if remaining else 100

    def _account_available(self, account):
        if account['status'] not in ('ready', 'cooldown') or account['generation'] < 1: return False
        if account['status'] == 'cooldown':
            if not account['cooldown_until'] or datetime.fromisoformat(account['cooldown_until']) > datetime.now(timezone.utc): return False
        return self._account_remaining(account) > 0

    def _choose_account(self, provider, environment_id, settings, excluded=()):
        from .store import Conflict
        policy, chosen, pool = settings['account_policy'], settings['account_id'], settings['account_ids']
        if policy == 'manual' or (policy == 'auto' and chosen is not None):
            if chosen is None: return None
            account = self._one('accounts', chosen)
            if chosen in excluded or not self._account_available(account): raise Conflict('Selected account is unavailable; sign in or wait for quota reset')
            return account
        candidates = [a for a in self.accounts(provider, environment_id)
                      if a['id'] not in excluded and (not pool or a['id'] in pool) and self._account_available(a)]
        # Preserve a healthy conversation identity. Rank new choices by explicit pool,
        # priority, remaining quota, then least recent use for equally healthy accounts.
        candidates.sort(key=lambda a: (a['id'] != chosen, pool.index(a['id']) if pool else 0,
                                       -a['priority'], -self._account_remaining(a), a['last_used_at'] or '', a['id']))
        if not candidates: raise Conflict('No ready account is available for this service and device')
        return candidates[0]

    def _new_account_branch(self, session, account_id, generation, activate=True):
        branch = self.db.execute('SELECT COALESCE(MAX(branch),-1)+1 FROM session_account_branches WHERE session_id=?', (session['id'],)).fetchone()[0]
        self.db.execute('INSERT INTO session_account_branches VALUES(?,?,?,?,NULL,?)',
                        (session['id'], branch, account_id, generation, self._account_now()))
        if activate:
            self.db.execute('UPDATE sessions SET account_id=?,account_generation=?,account_branch=?,native_session_id=NULL,updated_at=? WHERE id=?',
                            (account_id, generation, branch, self._account_now(), session['id']))
            self._event(session['project_id'], session['id'], 'account_changed',
                        {'account_id': account_id, 'account_branch': branch, 'previous_account_id': session['account_id']})
        return branch

    def _freeze_run_account(self, session, run):
        from .store import Conflict
        provider = self._one('agents', session['agent_id'])['provider']
        try:
            account = self._choose_account(provider, session['environment_id'], session)
        except Conflict:
            if session['account_policy'] == 'manual': raise
            # Freeze the pool even if there is no healthy identity yet. The runtime
            # can wait for a known reset; it never falls back to the device login.
            run.update(account_id=session['account_id'], account_generation=session['account_generation'], account_branch=session['account_branch'],
                       account_policy=session['account_policy'], account_ids=session['account_ids'], account_selection_pending=1)
            return
        account_id, generation = (account['id'], account['generation']) if account else (None, 0)
        branch = session['account_branch']
        if (account_id, generation) != (session['account_id'], session['account_generation']):
            branch = self._new_account_branch(session, account_id, generation, activate=False)
        run.update(account_id=account_id, account_generation=generation, account_branch=branch,
                   account_policy=session['account_policy'], account_ids=session['account_ids'], account_selection_pending=0)
        if account:
            self.db.execute('UPDATE accounts SET last_used_at=? WHERE id=?', (self._account_now(), account_id))

    def switch_session_account(self, session_id, account_id, account_policy='manual', account_ids=None):
        with self.transaction():
            session = self._one('sessions', session_id)
            self._check_session_deletion(session_id)  # Also guards outstanding delegated replies.
            provider = self._one('agents', session['agent_id'])['provider']
            settings = self._account_settings(provider, session['environment_id'], account_id, account_policy, account_ids)
            account = self._choose_account(provider, session['environment_id'], settings)
            account_id, generation = (account['id'], account['generation']) if account else (None, 0)
            if (account_id, generation) != (session['account_id'], session['account_generation']):
                self._new_account_branch(session, account_id, generation)
            self.db.execute('UPDATE sessions SET account_id=?,account_policy=?,account_ids=?,updated_at=? WHERE id=?',
                            (account_id, account_policy, json.dumps(settings['account_ids']), self._account_now(), session_id))
            return self._one('sessions', session_id)

    def account_attempts(self, run_id):
        with self.lock:
            self._one('runs', run_id)
            return self._all('SELECT * FROM run_attempts WHERE run_id=? ORDER BY number', (run_id,))

    def reserve_run_account(self, run_id, *, fallback=False):
        from .store import Conflict
        with self.transaction():
            run = self._one('runs', run_id)
            if run['status'] != 'running': raise Conflict('Account execution requires an active run')
            session = self._one('sessions', run['session_id'])
            attempts = self._all('SELECT * FROM run_attempts WHERE run_id=? ORDER BY number', (run_id,))
            if attempts and attempts[-1]['status'] == 'running':
                if fallback: raise Conflict('Finish the previous attempt before selecting another account')
                return attempts[-1]
            if attempts and not fallback: raise Conflict('This run already has a finished account attempt')
            if run['account_selection_pending'] and not attempts:
                provider = self._one('agents', run['agent_id'])['provider']
                busy = [row[0] for row in self.db.execute("SELECT account_id FROM runs WHERE status='running' AND id<>? AND account_id IS NOT NULL", (run_id,))]
                account = self._choose_account(provider, session['environment_id'], run, busy)
                branch = self._new_account_branch(session, account['id'], account['generation'])
                run.update(account_id=account['id'], account_generation=account['generation'], account_branch=branch)
                self.db.execute('UPDATE runs SET account_id=?,account_generation=?,account_branch=?,account_selection_pending=0 WHERE id=?',
                                (account['id'], account['generation'], branch, run_id))
            if fallback:
                if run['account_policy'] != 'failover' or not attempts or attempts[-1]['status'] != 'rejected' or attempts[-1]['progress'] or len(attempts) >= 3:
                    raise Conflict('Automatic account fallback is not safe for this run')
                provider = self._one('agents', run['agent_id'])['provider']
                busy = [row[0] for row in self.db.execute("SELECT account_id FROM runs WHERE status='running' AND id<>? AND account_id IS NOT NULL", (run_id,))]
                account = self._choose_account(provider, session['environment_id'], run, [a['account_id'] for a in attempts] + busy)
                if account is None: raise Conflict('Fallback requires a managed account')
                branch = self._new_account_branch(session, account['id'], account['generation'])
                run.update(account_id=account['id'], account_generation=account['generation'], account_branch=branch)
                self.db.execute('UPDATE runs SET account_id=?,account_generation=?,account_branch=? WHERE id=?',
                                (account['id'], account['generation'], branch, run_id))
            if run['account_id']:
                account = self._one('accounts', run['account_id'])
                if account['generation'] != run['account_generation']:
                    raise Conflict('Account login changed after this task was queued')
                if not self._account_available(account):
                    raise Conflict('The frozen account is unavailable; wait for reset or use safe account fallback')
                if self.db.execute("SELECT 1 FROM runs WHERE status='running' AND id<>? AND account_id=?", (run_id,run['account_id'])).fetchone():
                    raise Conflict('This account is finishing another task; retry when its lease is free')
                if account['status'] == 'cooldown':
                    # Availability above proves the known reset has passed and no
                    # other quota window still blocks admission. Do not leave a
                    # successfully admitted account showing an old cooldown.
                    self.db.execute("UPDATE accounts SET status='ready',error=NULL,cooldown_until=NULL,updated_at=? WHERE id=?",
                                    (self._account_now(), account['id']))
            branch = self.db.execute('SELECT * FROM session_account_branches WHERE session_id=? AND branch=?',
                                     (session['id'], run['account_branch'])).fetchone()
            if branch is None: raise Conflict('Account conversation branch is missing')
            # A queued turn retains its branch even if an earlier turn failed over.
            self.db.execute('UPDATE sessions SET account_id=?,account_generation=?,account_branch=?,native_session_id=? WHERE id=?',
                            (run['account_id'], run['account_generation'], run['account_branch'], branch['native_session_id'], session['id']))
            timestamp = self._account_now()
            item = dict(id=str(uuid.uuid4()), run_id=run_id, number=len(attempts) + 1, account_id=run['account_id'],
                        generation=run['account_generation'], account_branch=run['account_branch'], created_at=timestamp)
            self.db.execute('''INSERT INTO run_attempts(id,run_id,number,account_id,generation,account_branch,status,created_at)
                VALUES(:id,:run_id,:number,:account_id,:generation,:account_branch,'running',:created_at)''', item)
            if run['account_id']: self.db.execute('UPDATE accounts SET last_used_at=? WHERE id=?', (timestamp, run['account_id']))
            return self._one('run_attempts', item['id'])

    def reject_unavailable_run_account(self, run_id, error_code='account_unavailable'):
        """Record a preflight rejection without starting a native CLI or sending a prompt."""
        from .store import Conflict
        error_code = self._account_error(error_code)
        with self.transaction():
            run = self._one('runs', run_id)
            if run['status'] != 'running' or run['account_selection_pending'] or not run['account_id']:
                raise Conflict('Preflight rejection requires a frozen managed account')
            attempts = self._all('SELECT * FROM run_attempts WHERE run_id=? ORDER BY number', (run_id,))
            if attempts:
                if attempts[-1]['status'] == 'rejected' and not attempts[-1]['progress']: return attempts[-1]
                raise Conflict('This run already has an execution attempt')
            if self._account_available(self._one('accounts', run['account_id'])):
                raise Conflict('The account is available')
            timestamp = self._account_now()
            item = dict(id=str(uuid.uuid4()),run_id=run_id,account_id=run['account_id'],generation=run['account_generation'],
                        account_branch=run['account_branch'],error_code=error_code,timestamp=timestamp)
            self.db.execute('''INSERT INTO run_attempts(id,run_id,number,account_id,generation,account_branch,status,error_code,created_at,finished_at)
                VALUES(:id,:run_id,1,:account_id,:generation,:account_branch,'rejected',:error_code,:timestamp,:timestamp)''', item)
            return self._one('run_attempts', item['id'])

    def next_account_retry(self, run_id):
        """Earliest known reset in the frozen pool; None means user/login action is needed."""
        with self.lock:
            run = self._one('runs', run_id)
            session = self._one('sessions', run['session_id'])
            provider = self._one('agents', run['agent_id'])['provider']
            attempts = self._all('SELECT * FROM run_attempts WHERE run_id=? ORDER BY number', (run_id,))
            if attempts and (run['account_policy'] != 'failover' or attempts[-1]['status'] != 'rejected' or attempts[-1]['progress'] or len(attempts) >= 3): return None
            excluded = {a['account_id'] for a in attempts}
            dates = []
            for account in self.accounts(provider, session['environment_id']):
                if account['id'] in excluded: continue
                if (run['account_policy'] == 'manual' or (run['account_policy'] == 'auto' and run['account_id'])) and account['id'] != run['account_id']: continue
                if run['account_ids'] and account['id'] not in run['account_ids']: continue
                if account['status'] not in ('ready', 'cooldown'): continue
                if self._account_available(account): return self._account_now()
                deadlines = []
                if account['cooldown_until']: deadlines.append(account['cooldown_until'])
                unknown = False
                for window in account['quota'].get('windows', []):
                    if window.get('remaining_percent', 100 - window.get('used_percent', 0)) <= 0:
                        reset = self._account_window_reset(account, window)
                        if reset: deadlines.append(reset)
                        else: unknown = True
                if deadlines and not unknown:
                    latest = max(datetime.fromisoformat(v) for v in deadlines)
                    if latest > datetime.now(timezone.utc): dates.append(latest)
            return min(dates).isoformat() if dates else None

    def requeue_account_run(self, run_id, retry_at):
        from .store import Conflict, Invalid
        retry_at = self._account_date(retry_at)
        if retry_at is None or datetime.fromisoformat(retry_at) <= datetime.now(timezone.utc): raise Invalid('Account retry must be in the future')
        with self.transaction():
            run = self._one('runs', run_id)
            if run['status'] != 'running': raise Conflict('Only an active account task can wait for a reset')
            attempts = self._all('SELECT * FROM run_attempts WHERE run_id=? ORDER BY number', (run_id,))
            if attempts and (run['account_policy'] != 'failover' or attempts[-1]['status'] != 'rejected' or attempts[-1]['progress'] or len(attempts) >= 3):
                raise Conflict('This task cannot safely retry after a reset')
            self.db.execute("UPDATE runs SET status='queued',next_attempt_at=?,updated_at=? WHERE id=?", (retry_at,self._account_now(),run_id))
            self._refresh_session(run['session_id'], 'queued')
            self._event(run['project_id'],run['session_id'],'account_waiting',{'run_id':run_id,'retry_at':retry_at})
            return self._one('runs', run_id)

    def account_usage_bindings(self):
        with self.lock:
            return {(row['provider'], self.metric_identity(row['environment_id'], row['native_session_id'])): row['account_id']
                    for row in self.db.execute('''SELECT agents.provider,sessions.environment_id,branch.native_session_id,branch.account_id
                        FROM session_account_branches AS branch JOIN sessions ON sessions.id=branch.session_id
                        JOIN agents ON agents.id=sessions.agent_id WHERE branch.native_session_id IS NOT NULL''')}

    def mark_account_attempt_progress(self, attempt_id):
        from .store import Conflict
        with self.transaction():
            attempt = self._one('run_attempts', attempt_id)
            if attempt['status'] != 'running': raise Conflict('Account attempt is no longer active')
            self.db.execute('UPDATE run_attempts SET progress=1 WHERE id=?', (attempt_id,))
            return self._one('run_attempts', attempt_id)

    def finish_account_attempt(self, attempt_id, status, error_code=None, progress=False):
        from .store import Invalid, Conflict
        if status not in ('completed', 'rejected', 'failed', 'cancelled', 'interrupted'): raise Invalid('Invalid account attempt status')
        if not isinstance(progress, bool): raise Invalid('Invalid account progress flag')
        error_code = self._account_error(error_code)
        with self.transaction():
            attempt = self._one('run_attempts', attempt_id)
            if attempt['status'] != 'running':
                if attempt['status'] == status and attempt['error_code'] == error_code: return attempt
                raise Conflict('Account attempt is already finished')
            progress = bool(progress or attempt['progress'])
            if status == 'rejected' and progress: raise Conflict('An attempt with work performed cannot be marked safely rejected')
            self.db.execute('UPDATE run_attempts SET status=?,error_code=?,progress=?,finished_at=? WHERE id=?',
                            (status, error_code, int(progress), self._account_now(), attempt_id))
            return self._one('run_attempts', attempt_id)
