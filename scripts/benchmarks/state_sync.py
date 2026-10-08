#!/usr/bin/env python3
"""Compare full and unchanged state reads in a disposable database."""

import json
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agentdock.store import Store

with tempfile.TemporaryDirectory() as directory:
    store = Store(Path(directory) / "state.sqlite3")
    try:
        agent = store.add_agent(None, "Benchmark", "codex")
        with store.transaction():
            for index in range(8000):
                store.db.execute(
                    """INSERT INTO sessions
                    (id,agent_id,title,status,created_at,updated_at,workspace)
                    VALUES(?,?,?,'completed','2026-10-01','2026-10-01',?)""",
                    (
                        str(uuid.uuid4()),
                        agent["id"],
                        "Fixture " + str(index),
                        directory,
                    ),
                )
        version = store.state_version()
        result = {}
        for label, since in [("full", None), ("unchanged", version)]:
            samples = []
            for _ in range(5):
                start = time.perf_counter()
                encoded = json.dumps(store.state(since)).encode()
                samples.append((time.perf_counter() - start) * 1000)
            result[label] = {
                "median_ms": round(statistics.median(samples), 3),
                "bytes": len(encoded),
            }
        print(json.dumps(result, indent=2))
    finally:
        store.close()
