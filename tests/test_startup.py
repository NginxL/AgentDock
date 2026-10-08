import json
import os
import selectors
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler

from agentdock.server import write_access_token
from agentdock.loopback_server import LoopbackServer

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = {
    k: v for k, v in os.environ.items() if not k.startswith("AGENTDOCK_CREDENTIAL_")
}


class StartupTests(unittest.TestCase):
    def test_loopback_start_never_performs_dns(self):
        with patch("socket.getfqdn", side_effect=AssertionError("Unexpected DNS")):
            with LoopbackServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as server:
                self.assertGreater(server.server_port, 1023)

    def test_automatic_port_preserves_host_and_token_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            process = subprocess.Popen(
                [sys.executable, "-u", "-m", "agentdock", "--data-dir", temporary],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=ENVIRONMENT,
            )
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(
                        selector.select(10), "Backend did not report readiness"
                    )
                line = process.stdout.readline().strip()
                self.assertTrue(line.startswith("AgentDock: http://127.0.0.1:"))
                origin = line.removeprefix("AgentDock: ")
                self.assertNotEqual(
                    int(origin.rsplit(":", 1)[1]), occupied.getsockname()[1]
                )
                token = (Path(temporary) / "admin.token").read_text().strip()
                self.assertNotIn(token, line)
                request = Request(
                    origin + "/api/state", headers={"Authorization": "Bearer " + token}
                )
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(json.load(response)["agents"], [])
                request.add_header("Origin", "http://127.0.0.1:1")
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=5)
                self.assertEqual(error.exception.code, 403)
                # A second instance must not rotate this instance's token.
                second = subprocess.run(
                    [sys.executable, "-m", "agentdock", "--data-dir", temporary],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=ENVIRONMENT,
                )
                self.assertEqual(second.returncode, 1)
                self.assertIn("Error ID:", second.stderr)
                self.assertEqual(
                    (Path(temporary) / "admin.token").read_text().strip(), token
                )
            finally:
                process.terminate()
                process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0)

    def test_token_write_is_private_atomic_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "admin.token"
            write_access_token(target, "fixture")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            elsewhere = Path(temporary) / "external"
            elsewhere.write_text("do not overwrite")
            target.unlink()
            target.symlink_to(elsewhere)
            with self.assertRaises(ValueError):
                write_access_token(target, "replacement")
            self.assertEqual(elsewhere.read_text(), "do not overwrite")
            self.assertEqual(list(Path(temporary).glob(".admin-*")), [])

    def test_invalid_timeouts_are_rejected_before_startup(self):
        for settings in (
            {"run_timeout": 0},
            {"run_timeout": True},
            {"run_timeout": float("nan")},
            {"approval_timeout": 10000},
        ):
            with (
                self.subTest(settings=settings),
                tempfile.TemporaryDirectory() as temporary,
            ):
                config = Path(temporary) / "config.json"
                config.write_text(json.dumps(settings))
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "agentdock",
                        "--config",
                        str(config),
                        "--data-dir",
                        str(Path(temporary) / "data"),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=ROOT,
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if not k.startswith("AGENTDOCK_CREDENTIAL_")
                    },
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((Path(temporary) / "data").exists())
