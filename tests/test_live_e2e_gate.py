import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class LiveVerificationGateTests(unittest.TestCase):
    def test_default_only_describes_stages_and_live_requires_explicit_opt_in(self):
        script = Path(__file__).resolve().parents[1] / "scripts/live-e2e.py"
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "AGENTDOCK_LIVE_E2E"
        }
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        plan = json.loads(result.stdout)
        self.assertFalse(plan["live"])
        self.assertEqual(len(plan["stages"]), 5)
        blocked = subprocess.run(
            [sys.executable, str(script), "--live"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("trusted machine", blocked.stderr)

    def test_ci_cannot_enable_live_credentials_with_the_model_usage_opt_in(self):
        script = Path(__file__).resolve().parents[1] / "scripts/live-e2e.py"
        blocked = subprocess.run(
            [sys.executable, str(script), "--live"],
            capture_output=True,
            text=True,
            env={**os.environ, "AGENTDOCK_LIVE_E2E": "1", "GITHUB_ACTIONS": "true"},
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("outside GitHub Actions", blocked.stderr)
        self.assertEqual(blocked.stdout, "")
