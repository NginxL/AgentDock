"""Local token accounting. No prompts, credentials or provider requests are stored here."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
import time

FIELDS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'total_tokens')


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**15 else None


def normalize(provider, raw):
    if not isinstance(raw, dict): return None
    raw = {''.join('_' + c.lower() if c.isupper() else c for c in k): v for k, v in raw.items()}
    inp, out = count(raw.get('input_tokens')), count(raw.get('output_tokens'))
    read = count(raw.get('cached_input_tokens', raw.get('cache_read_input_tokens', 0)))
    write = count(raw.get('cache_write_input_tokens', raw.get('cache_creation_input_tokens', 0)))
    if any(v is None for v in (inp, out, read, write)): return None
    if provider == 'claude': inp += read + write
    if read > inp or write > inp: return None
    return dict(zip(FIELDS, (inp, out, read, write, inp + out)))


def timestamp(value):
    try:
        t = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return t.timestamp() if t.tzinfo else None
    except (TypeError, ValueError, AttributeError): return None


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS token_records(provider TEXT NOT NULL,native_id TEXT NOT NULL,record_id TEXT NOT NULL,input_tokens INTEGER NOT NULL,output_tokens INTEGER NOT NULL,cache_read_tokens INTEGER NOT NULL,cache_write_tokens INTEGER NOT NULL,total_tokens INTEGER NOT NULL,updated_at REAL NOT NULL,source TEXT NOT NULL,PRIMARY KEY(provider,native_id,record_id));
    CREATE TABLE IF NOT EXISTS token_spans(provider TEXT NOT NULL,native_id TEXT NOT NULL,record_id TEXT NOT NULL,counter INTEGER NOT NULL,started_at REAL NOT NULL,ended_at REAL NOT NULL,tokens INTEGER NOT NULL,PRIMARY KEY(provider,native_id,record_id,counter));
    CREATE TABLE IF NOT EXISTS token_files(path TEXT PRIMARY KEY,inode INTEGER NOT NULL,offset INTEGER NOT NULL,mtime INTEGER NOT NULL,state TEXT NOT NULL);
    ''')


def record(store, provider, native_id, record_id, usage, at, source, span=None):
    if provider not in ('codex', 'claude') or not isinstance(native_id, str) or not native_id or len(native_id) > 512: return
    if not isinstance(record_id, str) or not record_id or len(record_id) > 512: return
    if not isinstance(at, (float, int)) or not math.isfinite(at) or not 0 < at <= time.time() + 60: return
    if not usage or any(count(usage.get(k)) is None for k in FIELDS): return
    with store.transaction():
        old = store.db.execute('SELECT * FROM token_records WHERE provider=? AND native_id=? AND record_id=?', (provider, native_id, record_id)).fetchone()
        # Repeated content blocks, live events, rescans and archived copies share identity.
        values = [max(usage[k], old[k] if old else 0) for k in FIELDS]
        values[-1] = values[0] + values[1]
        stamp = max(at, old['updated_at'] if old else 0)
        store.db.execute('INSERT OR REPLACE INTO token_records VALUES(?,?,?,?,?,?,?,?,?,?)', (provider, native_id, record_id, *values, stamp, source))
        if span:
            start, delta = span
            # Live and log streams may report different intermediate counters.
            # Only the not-yet-accounted output can contribute another span.
            if count(delta) is not None:
                delta = min(delta, max(0, usage['output_tokens'] - (old['output_tokens'] if old else 0)))
            if isinstance(start, (int,float)) and math.isfinite(start) and 0 < at-start <= 3600 and count(delta) is not None and 0 < delta <= usage['output_tokens'] and at > time.time()-180:
                store.db.execute('INSERT OR IGNORE INTO token_spans VALUES(?,?,?,?,?,?,?)', (provider, native_id, record_id, usage['output_tokens'], start, at, delta))
        store.db.execute('DELETE FROM token_spans WHERE ended_at<?', (time.time()-240,))


def snapshot(store, at=None):
    at = at or time.time()
    with store.lock:
        bindings = {(r['provider'], r['native_session_id']): r['agent_id'] for r in store.db.execute('SELECT agents.provider,sessions.native_session_id,sessions.agent_id FROM sessions JOIN agents ON agents.id=sessions.agent_id WHERE native_session_id IS NOT NULL')}
        rows = [dict(r) for r in store.db.execute('SELECT provider,native_id,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens,SUM(cache_read_tokens) cache_read_tokens,SUM(cache_write_tokens) cache_write_tokens,SUM(total_tokens) total_tokens,MAX(updated_at) updated_at FROM token_records GROUP BY provider,native_id')]
        spans = [dict(r) for r in store.db.execute('SELECT * FROM token_spans WHERE ended_at>? AND ended_at<=?', (at-180, at))]
        running = [dict(r) for r in store.db.execute("SELECT runs.agent_id,agents.provider,sessions.native_session_id FROM runs JOIN agents ON runs.agent_id=agents.id JOIN sessions ON runs.session_id=sessions.id WHERE runs.status='running'")]
        agent_ids = [r[0] for r in store.db.execute('SELECT id FROM agents')]
    for row in rows: row['agent_id'] = bindings.get((row['provider'], row['native_id']))
    def group(provider=None, agent_id=None):
        chosen = [r for r in rows if (not provider or r['provider']==provider) and (not agent_id or r['agent_id']==agent_id)]
        samples = [r for r in spans if (not provider or r['provider']==provider) and (not agent_id or bindings.get((r['provider'],r['native_id']))==agent_id)]
        active = [r for r in running if (not provider or r['provider']==provider) and (not agent_id or r['agent_id']==agent_id)]
        # Fixed 3-second buckets; distribute only measured output over its measured interval.
        points = []
        for i in range(60):
            end = at-180+(i+1)*3; start = end-3
            tokens = sum(r['tokens'] * max(0, min(end,r['ended_at'])-max(start,r['started_at']))/(r['ended_at']-r['started_at']) for r in samples)
            points.append(round(tokens/3, 2))
        recent = [r for r in samples if r['ended_at'] >= at-15]
        observed = {(r['provider'],r['native_id']) for r in recent}
        # Unknown during a run until its first measured usage sample. Idle really is zero.
        current = sum(points[-5:])/5 if recent else None if active else 0
        return {**{k: sum(r[k] for r in chosen) for k in FIELDS}, 'sessions': len(chosen), 'active_sessions': len(observed | {(r['provider'],r['native_session_id'] or r['agent_id']) for r in active}), 'current_tps': round(current,2) if current is not None else None, 'average_tps': round(sum(points)/60,2), 'points': points, 'updated_at': max((r['updated_at'] for r in chosen), default=None)}
    return {'as_of': at, 'total': group(), 'providers': {p: group(provider=p) for p in ('codex','claude')}, 'agents': {a: group(agent_id=a) for a in agent_ids}, 'unassigned_sessions': sum(r['agent_id'] is None for r in rows)}


class LocalUsage:
    """Incremental scanner; Codex cumulative totals need only a bounded tail read."""
    def __init__(self, store, home=None):
        self.store, self.home = store, Path(home or Path.home())
        self.environment = dict(os.environ) if home is None else {}
        self.stop = threading.Event()
        self.thread = None
        self.status = 'pending'
        self.scanned = 0
        self.failures = 0

    def start(self):
        if self.thread: return
        self.thread = threading.Thread(target=self._loop, name='local-token-usage', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join()

    def _loop(self):
        while not self.stop.is_set():
            try: self.scan()
            except Exception: self.status = 'partial'
            self.stop.wait(10)

    def scan(self):
        self.status = 'scanning'; self.failures = 0; pending = False
        codex = Path(self.environment.get('CODEX_HOME') or self.home/'.codex').expanduser()
        claude = Path(self.environment.get('CLAUDE_CONFIG_DIR') or self.home/'.claude').expanduser()
        roots = [('codex', codex/'sessions'), ('codex', codex/'archived_sessions'), ('claude', claude/'projects')]
        for provider, root in roots:
            if not root.is_dir(): continue
            for path in root.rglob('*.jsonl'):
                if self.stop.is_set(): return
                if path.is_symlink(): continue
                try: pending = self._file(provider, path) or pending
                except (OSError, ValueError, KeyError, TypeError): self.failures += 1
        self.status = 'partial' if self.failures else 'scanning' if pending else 'ready'

    def _file(self, provider, path):
        stat = path.stat()
        with self.store.lock:
            saved = self.store.db.execute('SELECT * FROM token_files WHERE path=?', (str(path),)).fetchone()
        if saved and saved['inode']==stat.st_ino and saved['mtime']==stat.st_mtime_ns and saved['offset']==stat.st_size: return
        state = json.loads(saved['state']) if saved and saved['inode']==stat.st_ino and saved['offset']<=stat.st_size else {}
        offset = saved['offset'] if saved and saved['inode']==stat.st_ino and saved['offset']<=stat.st_size else 0
        state["initialized"] = True
        latest = None
        with path.open('rb') as src:
            if provider == 'codex':
                first = src.readline(1024*1024)
                try:
                    meta = json.loads(first)
                    native_id = meta.get('payload',{}).get('id') if meta.get('type')=='session_meta' else None
                except ValueError: native_id = None
                if not native_id: return
                start = max(offset, stat.st_size-8*1024*1024)
                src.seek(start)
                if start > offset: src.readline(1024*1024)  # discard partial tail line
                state['id'] = native_id
            else:
                src.seek(offset)
            budget = 16*1024*1024
            while budget > 0 and not self.stop.is_set():
                pos = src.tell(); line = src.readline(1024*1024); budget -= len(line)
                if not line: break
                if not line.endswith(b'\n'):
                    if src.tell() == stat.st_size: src.seek(pos); break
                    # Oversized tool/text lines cannot be token-only events; drain them.
                    while line and not line.endswith(b'\n') and not self.stop.is_set(): line=src.readline(1024*1024)
                    continue
                if provider == 'codex' and b'"token_count"' not in line: continue
                if provider == 'claude' and b'"usage"' not in line and b'"type":"user"' not in line and b'"type": "user"' not in line: continue
                try: event=json.loads(line)
                except ValueError: continue
                at=timestamp(event.get('timestamp'))
                if at is None: continue
                if provider == 'codex':
                    p=event.get('payload',{})
                    if p.get('type')!='token_count': continue
                    usage=normalize(provider,(p.get('info') or {}).get('total_token_usage'))
                    identity=state['id']; key='total'
                else:
                    m=event.get('message',{})
                    if event.get('type')=='user':
                        state['at']=at
                        continue
                    if event.get('type')!='assistant' or not isinstance(m,dict): continue
                    usage=normalize(provider,m.get('usage')); identity=event.get('sessionId'); key=m.get('id')
                if usage:
                    prior=state.get('last')
                    if provider=='codex':
                        span=(prior['at'],usage['output_tokens']-prior['out']) if prior and at>prior['at'] else None
                    else:
                        start=prior['at'] if prior else state.get('at')
                        delta=usage['output_tokens']-(prior['out'] if prior and prior.get('key')==key else 0)
                        span=(start,delta) if start and at>start else None
                    if provider == 'codex':
                        latest = (identity,key,usage,at,span)
                        if at > time.time()-180 and span: record(self.store,provider,identity,key,usage,at,'local',span)
                    else: record(self.store,provider,identity,key,usage,at,'local',span)
                    state['last']={'at':at,'out':usage['output_tokens'],'key':key}
            offset=src.tell()
        if latest:
            identity,key,usage,at,span = latest
            record(self.store,provider,identity,key,usage,at,'local',span)
        with self.store.transaction():
            self.store.db.execute('INSERT OR REPLACE INTO token_files VALUES(?,?,?,?,?)',(str(path),stat.st_ino,offset,stat.st_mtime_ns,json.dumps(state)))
        self.scanned+=1
        return offset < stat.st_size
