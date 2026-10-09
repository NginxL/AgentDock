#!/usr/bin/env python3
"""Measure a settings-only delta with 300 large events; temporary data, no CLI."""

import json
import sys
import statistics
import tempfile
import time
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from agentdock.store import Store

    with tempfile.TemporaryDirectory(prefix="agentdock-state-benchmark-") as directory:
        root = Path(directory)
        store = Store(root / "state.sqlite3")
        try:
            project = store.add_project("Fixture", str(root))
            agent = store.add_agent(project["id"], "Fixture", "codex")
            session = store.add_session(agent["id"], "Fixture")
            for _ in range(300):
                store.append_event(
                    project["id"],
                    session["id"],
                    "tool_output",
                    {"text": "x" * 20000, "run_id": "r"},
                )
            version = store.state()["version"]
            store.update_session_settings(
                session["id"], {"model": None, "effort": None}
            )
            timings = []
            for _ in range(5):
                start = time.perf_counter()
                delta = store.state(version)
                data = json.dumps(delta).encode()
                timings.append((time.perf_counter() - start) * 1000)
            print(
                json.dumps(
                    {
                        "domains": sorted(set(delta) - {"version", "partial"}),
                        "bytes": len(data),
                        "snapshot_and_json_ms": round(
                            (time.perf_counter() - start) * 1000, 2
                        ),
                    }
                )
            )
        finally:
            store.close()


if __name__ == "__main__":
    main()
