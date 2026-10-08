"""Opt-in real CLI file-write probe using only disposable, fictional credentials.

This does not test OAuth refresh or switch a real account. Network is pointed at
a closed loopback proxy. HOME, CODEX_HOME, source and symlink all live in a temp dir.
"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True, type=Path)
    cli = parser.parse_args().codex.absolute()
    with tempfile.TemporaryDirectory(prefix="agentdock-auth-probe-") as directory:
        root = Path(directory)
        private = root / "codex"
        private.mkdir()
        source = root / "fixture-auth.json"
        source.write_text("{}")
        source.chmod(0o600)
        target = private / "auth.json"
        target.symlink_to(source)
        env = {
            "HOME": str(root),
            "CODEX_HOME": str(private),
            "PATH": str(cli.parent) + os.pathsep + "/usr/bin:/bin",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
        }
        version = subprocess.run(
            [str(cli), "--version"], env=env, capture_output=True, text=True, timeout=10
        )
        result = subprocess.run(
            [
                str(cli),
                "-c",
                'cli_auth_credentials_store="file"',
                "login",
                "--with-api-key",
            ],
            input=b"sk-fixture-not-a-real-credential\n",
            env=env,
            cwd=root,
            capture_output=True,
            timeout=15,
        )
        print(
            json.dumps(
                {
                    "version": version.stdout.strip(),
                    "exit_code": result.returncode,
                    "symlink_preserved": target.is_symlink(),
                    "source_changed": source.read_text() != "{}",
                    "oauth_refresh_tested": False,
                }
            )
        )


if __name__ == "__main__":
    main()
