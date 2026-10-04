#!/usr/bin/env python3
"""Build and install a local macOS application without changing provider logins."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-agentmeter", action="store_true", help="Import local billing records with a backup; existing AgentDock records win")
    args = parser.parse_args()
    if sys.platform != "darwin": parser.error("macOS 14+ and Apple Command Line Tools are required")
    npm = shutil.which("npm")
    if not npm: parser.error("Node.js 20.19+ and npm are required to build the interface")
    if not (ROOT / "web/node_modules").exists():
        subprocess.run([npm, "ci", "--ignore-scripts"], cwd=ROOT / "web", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "web", check=True)
    subprocess.run(["swift", "build", "--package-path", str(ROOT / "native"), "-c", "release"], check=True)
    binaries = Path(subprocess.check_output(["swift", "build", "--package-path", str(ROOT / "native"), "-c", "release", "--show-bin-path"], text=True).strip())
    data = Path.home() / ".local/share/agentdock"
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.chmod(0o700)
    applications = Path.home() / "Applications"
    applications.mkdir(exist_ok=True)
    destination = applications / "AgentDock.app"
    existing = subprocess.run(["pgrep", "-f", str(destination / "Contents/MacOS/AgentDock")], capture_output=True)
    if existing.returncode == 0: parser.error("Quit AgentDock before updating it")
    # Acquiring the Store also rejects replacing a running workbench's configuration.
    sys.path.insert(0, str(ROOT))
    from agentdock.store import Store
    store = Store(data / "agentdock.sqlite3")
    try:
        if args.import_agentmeter:
            from agentdock.migration import import_agentmeter
            result = import_agentmeter(store, Path.home() / "Library/Preferences/io.github.nginxl.AgentMeter.plist", data)
            print("Billing import:", result)
        settings_path = data / "config.json"
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
        settings.setdefault("commands", {
            "codex": [shutil.which("codex") or "codex", "app-server"],
            "claude": [shutil.which("claude") or "claude"],
        })
        settings["quota_command"] = [str(destination / "Contents/Helpers/AgentDockUsage")]
        settings.pop("agentmeter_command", None)
        with tempfile.TemporaryDirectory(prefix="agentdock-install-", dir=applications) as staging:
            bundle = Path(staging) / "AgentDock.app"
            contents = bundle / "Contents"
            resources = contents / "Resources"
            for p in (contents / "MacOS", contents / "Helpers", resources / "workbench/web"):
                p.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binaries / "AgentDock", contents / "MacOS/AgentDock")
            shutil.copy2(binaries / "AgentDockUsage", contents / "Helpers/AgentDockUsage")
            shutil.copytree(ROOT / "agentdock", resources / "workbench/agentdock", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copytree(ROOT / "web/dist", resources / "workbench/web/dist")
            shutil.copy2(ROOT / "LICENSE", resources / "LICENSE.txt")
            shutil.copy2(ROOT / "NOTICE.md", resources / "NOTICE.md")
            licenses = resources / "dependency-licenses"
            licenses.mkdir()
            for name in ("react", "react-dom", "scheduler"):
                license_file = ROOT / "web/node_modules" / name / "LICENSE"
                if license_file.exists(): shutil.copy2(license_file, licenses / (name + ".txt"))
            shutil.copy2(ROOT / "web/src/assets/providers/LICENSE", licenses / "lobe-icons.txt")
            (resources / "runtime.json").write_text(json.dumps({"python": sys.executable, "path": os.environ.get("PATH", "/usr/bin:/bin")}))
            info = {
                "CFBundleExecutable": "AgentDock", "CFBundleIdentifier": "io.github.nginxl.AgentDock",
                "CFBundleName": "AgentDock", "CFBundleDisplayName": "AgentDock", "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "0.3.0", "CFBundleVersion": "31", "LSMinimumSystemVersion": "14.0",
                "NSHighResolutionCapable": True, "CFBundleIconFile": "AppIcon",
                "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
                "NSHumanReadableCopyright": "Copyright © 2026 NginxL. MIT License.",
            }
            (contents / "Info.plist").write_bytes(plistlib.dumps(info))
            subprocess.run(["swift", str(ROOT / "scripts/make-icon.swift"), str(resources / "AppIcon.icns")], check=True)
            subprocess.run(["codesign", "--force", "--sign", "-", str(contents / "Helpers/AgentDockUsage")], check=True)
            subprocess.run(["codesign", "--force", "--sign", "-", str(bundle)], check=True)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
            if destination.exists():
                backup = data / "backups" / ("AgentDock-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".app")
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
    print("Open AgentDock from Applications. Usage refreshes automatically every 10 minutes; agent tasks run only when requested.")


if __name__ == "__main__": main()
