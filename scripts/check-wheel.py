#!/usr/bin/env python3
"""Verify an installed wheel using private temporary data and no CLI execution."""

import json
import os
import selectors
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    with tempfile.TemporaryDirectory(prefix="agentdock-wheel-check-") as directory:
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "agentdock", "--data-dir", directory],
            cwd=directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                k: v
                for k, v in os.environ.items()
                if not k.startswith("AGENTDOCK_CREDENTIAL_")
            },
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(10):
                    raise RuntimeError("Packaged server did not start")
            line = process.stdout.readline().strip()
            if not line.startswith("AgentDock: http://127.0.0.1:"):
                raise RuntimeError("Packaged server did not report a loopback address")
            origin = line.removeprefix("AgentDock: ")
            with urlopen(origin, timeout=5) as response:
                assert b'<div id="root">' in response.read(), (
                    "Frontend missing from wheel"
                )
            token = (Path(directory) / "admin.token").read_text().strip()
            request = Request(
                origin + "/api/state", headers={"Authorization": "Bearer " + token}
            )
            with urlopen(request, timeout=5) as response:
                assert json.load(response)["agents"] == []
        finally:
            process.terminate()
            process.communicate(timeout=15)
        assert process.returncode == 0
    print(
        "Installed package: bundled frontend, private data, dynamic port, shutdown verified"
    )


if __name__ == "__main__":
    main()
