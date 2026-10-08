"""Build a relocatable macOS bundle without reading the user's AgentDock data."""

import ast
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def version():
    module = ast.parse((ROOT / "agentdock/__init__.py").read_text())
    return next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
    )


def build_sources():
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("Building from source requires Node.js 20.19+ and npm")
    if not (ROOT / "web/node_modules").exists():
        subprocess.run([npm, "ci", "--ignore-scripts"], cwd=ROOT / "web", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "web", check=True)
    command = [
        "swift",
        "build",
        "--package-path",
        str(ROOT / "native"),
        "-c",
        "release",
    ]
    subprocess.run(command, check=True)
    return Path(
        subprocess.check_output(command + ["--show-bin-path"], text=True).strip()
    )


def bundle_at(parent, binaries, python_runtime=None, identity="-", build_number="36"):
    bundle = Path(parent) / "AgentDock.app"
    contents = bundle / "Contents"
    resources = contents / "Resources"
    for path in (contents / "MacOS", contents / "Helpers", resources / "workbench/web"):
        path.mkdir(parents=True, exist_ok=False)
    shutil.copy2(binaries / "AgentDock", contents / "MacOS/AgentDock")
    shutil.copy2(binaries / "AgentDockUsage", contents / "Helpers/AgentDockUsage")
    shutil.copytree(
        ROOT / "agentdock",
        resources / "workbench/agentdock",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "static"),
    )
    shutil.copytree(ROOT / "web/dist", resources / "workbench/web/dist")
    for name in ("LICENSE", "NOTICE.md"):
        shutil.copy2(ROOT / name, resources / name)
    licenses = resources / "dependency-licenses"
    licenses.mkdir()
    for name in (
        "react",
        "react-dom",
        "scheduler",
        "@tanstack/query-core",
        "@tanstack/react-query",
    ):
        source = ROOT / "web/node_modules" / name / "LICENSE"
        if source.exists():
            shutil.copy2(source, licenses / (name.replace("/", "-") + ".txt"))
    shutil.copy2(ROOT / "web/src/assets/providers/LICENSE", licenses / "lobe-icons.txt")
    if python_runtime:
        runtime = Path(python_runtime).resolve()
        subprocess.run(
            [
                str(runtime / "bin/python3"),
                "-I",
                "-c",
                "import sys; assert sys.version_info >= (3,11)",
            ],
            check=True,
        )
        # Portable distributions contain relative links. Reject host-specific ones.
        for path in runtime.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(runtime):
                raise ValueError("Python runtime contains an external symbolic link")
        shutil.copytree(runtime, resources / "Python", symlinks=True)
        subprocess.run(
            [
                str(resources / "Python/bin/python3"),
                "-I",
                "-c",
                "import sqlite3, ssl, tomllib; print('Embedded Python verified')",
            ],
            check=True,
        )
    else:
        (resources / "runtime.json").write_text(
            json.dumps(
                {
                    "python": sys.executable,
                    "path": os.environ.get("PATH", "/usr/bin:/bin"),
                }
            )
        )
    info = {
        "CFBundleExecutable": "AgentDock",
        "CFBundleIdentifier": "io.github.nginxl.AgentDock",
        "CFBundleName": "AgentDock",
        "CFBundleDisplayName": "AgentDock",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version(),
        "CFBundleVersion": build_number,
        "LSMinimumSystemVersion": "14.0",
        "NSHighResolutionCapable": True,
        "CFBundleIconFile": "AppIcon",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSAppleEventsUsageDescription": "AgentDock quits and reopens a native client only when you choose to save, switch or recover its account login.",
        "NSHumanReadableCopyright": "Copyright © 2026 NginxL. MIT License.",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    subprocess.run(
        [
            "swift",
            str(ROOT / "scripts/make-icon.swift"),
            str(resources / "AppIcon.icns"),
        ],
        check=True,
    )
    options = ["--options", "runtime", "--timestamp"] if identity != "-" else []
    signing = ["codesign", "--force", "--sign", identity, *options]
    if python_runtime:
        # Sign individual Mach-O files before the enclosing bundle, including extension modules.
        magic = {
            bytes.fromhex(value)
            for value in (
                "feedface",
                "cefaedfe",
                "feedfacf",
                "cffaedfe",
                "cafebabe",
                "bebafeca",
            )
        }
        for path in sorted((resources / "Python").rglob("*")):
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as stream:
                    native = stream.read(4) in magic
                if native:
                    subprocess.run(
                        signing + [str(path)], check=True, stdout=subprocess.DEVNULL
                    )
    subprocess.run(signing + [str(contents / "Helpers/AgentDockUsage")], check=True)
    subprocess.run(signing + [str(bundle)], check=True)
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True
    )
    return bundle
