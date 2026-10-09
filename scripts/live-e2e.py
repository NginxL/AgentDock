#!/usr/bin/env python3
"""Manual smoke test on a trusted machine with separately provisioned CLI logins."""

import argparse
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import uuid
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler
from pathlib import Path

STAGES = [
    "codex dialogue and resume",
    "claude dialogue and resume",
    "project dispatch",
    "result return to original owner",
    "delivery and acceptance",
]
ROOT = Path(__file__).resolve().parents[1]


def run_live(timeout):
    sys.path.insert(0, str(ROOT))
    from agentdock.loopback_server import LoopbackServer
    from agentdock.runtime import Runtime
    from agentdock.server import API, handler_for
    from agentdock.store import Store

    with (
        tempfile.TemporaryDirectory(prefix="agentdock-live-") as temporary,
        ExitStack() as cleanup,
    ):
        root = Path(temporary)
        store = Store(root / "data/state.sqlite3")
        cleanup.callback(store.close)
        workspace = root / "workspace"
        workspace.mkdir()
        project = store.add_project("Live verification", str(workspace))
        agents = {
            provider: store.add_agent(
                project["id"],
                "Fixture " + provider,
                provider,
                role="Verification only. Use only AgentDock collaboration tools. Do not run shell commands or read or write files.",
            )
            for provider in ("codex", "claude")
        }
        server = LoopbackServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        server.daemon_threads = True
        cleanup.callback(server.server_close)
        runtime = Runtime(
            store,
            {
                "execution_enabled": True,
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "python": sys.executable,
                "package_root": str(ROOT),
                "run_timeout": 120,
                "approval_timeout": 5,
            },
        )
        cleanup.callback(runtime.close)
        api = API(
            store, runtime, None, secrets.token_urlsafe(32), server.server_port, True
        )
        cleanup.callback(api.close)
        server.RequestHandlerClass = handler_for(api, root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cleanup.callback(server.shutdown)
        deadline = time.monotonic() + timeout

        def wait(predicate):
            while time.monotonic() < deadline:
                if store.state()["approvals"]:
                    raise RuntimeError(
                        "Unexpected CLI approval; no permissions were automatically granted"
                    )
                failed = [
                    r
                    for r in store.state()["runs"]
                    if r["status"] in ("failed", "cancelled", "interrupted")
                ]
                if failed:
                    raise RuntimeError(
                        "A native turn failed; no login or account rotation was attempted"
                    )
                if predicate():
                    return
                time.sleep(0.2)
            raise TimeoutError("Live verification deadline exceeded")

        for provider, agent in agents.items():
            session = store.add_session(agent["id"], "Resume check")
            run = runtime.start(
                session["id"], "Reply with the word READY. Do not use tools."
            )
            wait(lambda: store.get_run(run["id"])["status"] == "completed")
            native_id = store.get_session(session["id"])["native_session_id"]
            assert native_id
            followup = runtime.start(
                session["id"], "Reply with the word CONTINUED. Do not use tools."
            )
            wait(lambda: store.get_run(followup["id"])["status"] == "completed")
            assert store.get_session(session["id"])["native_session_id"] == native_id
            print(
                json.dumps(
                    {"stage": provider + " dialogue and resume", "status": "passed"}
                ),
                flush=True,
            )

        criterion = "Worker returned VERIFIED through project dispatch"
        task = store.create_task(
            project["id"],
            "Dispatch smoke test",
            criterion,
            criterion,
            agents["codex"]["id"],
            acceptance_policy="human",
        )
        prompt = (
            "Use message_send once to recipient_id "
            + agents["claude"]["id"]
            + " with body: 'Reply exactly VERIFIED. Do not use tools.', task_role worker and idempotency_key smoke. "
            "Finish this turn immediately after dispatch. Results return automatically. "
            "When the worker result arrives, call task_deliver with summary VERIFIED and checks "
            + json.dumps(
                [
                    {
                        "criterion": criterion,
                        "status": "passed",
                        "evidence": "Worker result contains VERIFIED",
                    }
                ]
            )
            + ". Do not deliver before receiving the actual result. Never run commands or modify files."
        )
        runtime.submit_task(task["id"], prompt, "develop", str(uuid.uuid4()))
        wait(
            lambda: (
                store.get_task(task["id"])["status"] == "review"
                and not store.pending_runs()
            )
        )
        detail = store.task_detail(task["id"])
        runs = detail["runs"]
        assert any(
            r["origin"] == "delegate"
            and r["agent_id"] == agents["claude"]["id"]
            and "VERIFIED" in (r["result"] or "")
            for r in runs
        )
        assert any(
            r["origin"] == "reply" and r["agent_id"] == agents["codex"]["id"]
            for r in runs
        )
        assert detail["deliveries"]
        store.accept_task(task["id"])
        assert store.get_task(task["id"])["status"] == "completed"
        for stage in STAGES[2:]:
            print(json.dumps({"stage": stage, "status": "passed"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Consume real model quota on a trusted machine outside GitHub Actions",
    )
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"live": False, "stages": STAGES}))
        return
    if os.environ.get("AGENTDOCK_LIVE_E2E") != "1":
        parser.error("Live tests require AGENTDOCK_LIVE_E2E=1 and a trusted machine")
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        parser.error("Live CLI verification must run outside GitHub Actions")
    if not 60 <= args.timeout <= 900:
        parser.error("timeout must be between 60 and 900 seconds")
    try:
        run_live(args.timeout)
    except Exception as error:
        # Never upload prompts, provider error text, credentials, or temporary databases.
        print(
            json.dumps({"status": "failed", "category": type(error).__name__}),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
