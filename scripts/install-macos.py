#!/usr/bin/env python3
"""Build and install a local macOS application without changing provider logins."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from macos_bundle import build_sources, bundle_at

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--import-agentmeter",
        action="store_true",
        help="Import local billing records with a backup; existing AgentDock records win",
    )
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("macOS 14+ and Apple Command Line Tools are required")
    binaries = build_sources()
    data = Path.home() / ".local/share/agentdock"
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.chmod(0o700)
    applications = Path.home() / "Applications"
    applications.mkdir(exist_ok=True)
    destination = applications / "AgentDock.app"
    existing = subprocess.run(
        ["pgrep", "-f", str(destination / "Contents/MacOS/AgentDock")],
        capture_output=True,
    )
    if existing.returncode == 0:
        parser.error("Quit AgentDock before updating it")
    # Acquiring the Store also rejects replacing a running workbench's configuration.
    sys.path.insert(0, str(ROOT))
    from agentdock.store import Store

    store = Store(data / "agentdock.sqlite3")
    try:
        if args.import_agentmeter:
            from agentdock.migration import import_agentmeter

            result = import_agentmeter(
                store,
                Path.home() / "Library/Preferences/io.github.nginxl.AgentMeter.plist",
                data,
            )
            print("Billing import:", result)
        settings_path = data / "config.json"
        settings = (
            json.loads(settings_path.read_text()) if settings_path.exists() else {}
        )
        settings.setdefault(
            "commands",
            {
                "codex": [shutil.which("codex") or "codex", "app-server"],
                "claude": [shutil.which("claude") or "claude"],
            },
        )
        settings["quota_command"] = [
            str(destination / "Contents/Helpers/AgentDockUsage")
        ]
        settings.pop("agentmeter_command", None)
        with tempfile.TemporaryDirectory(
            prefix="agentdock-install-", dir=applications
        ) as staging:
            bundle = bundle_at(Path(staging), binaries)
            if destination.exists():
                backup = (
                    data
                    / "backups"
                    / ("AgentDock-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".app")
                )
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), backup)
            os.replace(bundle, destination)
        temporary = data / "config.json.tmp"
        temporary.write_text(json.dumps(settings, indent=2) + "\n")
        temporary.chmod(0o600)
        os.replace(temporary, settings_path)
    finally:
        store.close()
    print("Installed:", destination)
    print(
        "Open AgentDock from Applications. Usage refreshes automatically every 10 minutes; agent tasks run only when requested."
    )


if __name__ == "__main__":
    main()
