"""Reproduce cancellation planning on an isolated database; never opens user data."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agentdock.store import Store, now


def measure(store, session):
    samples = []
    for _ in range(3):
        start = time.perf_counter()
        assert store.cancellable_tasks(session) == []
        samples.append(time.perf_counter() - start)
    return round(statistics.median(samples) * 1000, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=8000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / 'benchmark.sqlite3')
        try:
            agent = store.add_agent(None, 'Benchmark', 'codex')
            session = store.add_session(agent['id'], 'Benchmark')['id']
            stamp = now()
            with store.transaction():
                store.db.executemany('''INSERT INTO runs
                    (id,session_id,agent_id,prompt,status,created_at,updated_at,task_run_id,root_run_id)
                    VALUES(?,?,?,'fixture','completed',?,?,?,?)''',
                    [(str(i), session, agent['id'], stamp, stamp, str(i), str(i)) for i in range(args.runs)])
                for name in ('runs_task', 'runs_session', 'messages_sender_run'):
                    store.db.execute('DROP INDEX ' + name)
            before = measure(store, session)
            store._migrate_read_indexes()
            after = measure(store, session)
            print(json.dumps({'runs': args.runs, 'before_ms': before, 'after_ms': after,
                              'speedup': round(before / max(after, .001), 1)}))
        finally:
            store.close()


if __name__ == '__main__':
    main()
