#!/usr/bin/env python3
"""Release-runner operations; no installed apps or login entries are touched."""

import base64
import os
import subprocess
import sys
from pathlib import Path


def run(*command):
    subprocess.run(
        command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def main(action):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("This helper runs only in the isolated GitHub release job")
    temporary = Path(os.environ["RUNNER_TEMP"])
    keychain = str(temporary / "agentdock-release.keychain-db")
    certificate = temporary / "signing.p12"
    key = temporary / "notary.p8"
    if action == "prepare":
        for variable in (
            "CERTIFICATE",
            "CERTIFICATE_PASSWORD",
            "KEYCHAIN_PASSWORD",
            "SIGNING_IDENTITY",
            "NOTARY_KEY",
            "NOTARY_KEY_ID",
            "NOTARY_ISSUER",
        ):
            if not os.environ.get(variable):
                raise ValueError("Missing Apple signing or notarization secrets")
        for path, variable in ((certificate, "CERTIFICATE"), (key, "NOTARY_KEY")):
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stream:
                stream.write(base64.b64decode(os.environ[variable], validate=True))
        password = os.environ["KEYCHAIN_PASSWORD"]
        run("security", "create-keychain", "-p", password, keychain)
        run("security", "set-keychain-settings", "-lut", "21600", keychain)
        run("security", "unlock-keychain", "-p", password, keychain)
        run(
            "security",
            "import",
            str(certificate),
            "-P",
            os.environ["CERTIFICATE_PASSWORD"],
            "-A",
            "-t",
            "cert",
            "-f",
            "pkcs12",
            "-k",
            keychain,
        )
        run(
            "security",
            "set-key-partition-list",
            "-S",
            "apple-tool:,apple:",
            "-k",
            password,
            keychain,
        )
        run("security", "list-keychains", "-d", "user", "-s", keychain)
    elif action == "build":
        distributions = list((temporary / "portable-python").glob("cpython-3.13.*"))
        if len(distributions) != 1:
            raise ValueError("Expected one portable Python runtime")
        identity = (
            os.environ["SIGNING_IDENTITY"]
            if os.environ.get("NOTARIZE") == "true"
            else "-"
        )
        subprocess.run(
            [
                sys.executable,
                "scripts/package-macos.py",
                "--python-runtime",
                str(distributions[0]),
                "--identity",
                identity,
            ],
            check=True,
        )
    elif action == "notarize":
        run(
            "xcrun",
            "notarytool",
            "submit",
            "dist/AgentDock.zip",
            "--wait",
            "--key",
            str(key),
            "--key-id",
            os.environ["NOTARY_KEY_ID"],
            "--issuer",
            os.environ["NOTARY_ISSUER"],
        )
        run("xcrun", "stapler", "staple", "dist/AgentDock.app")
        run("spctl", "--assess", "--type", "execute", "dist/AgentDock.app")
        Path("dist/AgentDock.zip").unlink()
        run(
            "ditto",
            "-c",
            "-k",
            "--keepParent",
            "dist/AgentDock.app",
            "dist/AgentDock.zip",
        )
    elif action == "cleanup":
        subprocess.run(["security", "delete-keychain", keychain], capture_output=True)
        certificate.unlink(missing_ok=True)
        key.unlink(missing_ok=True)
    else:
        raise ValueError("Unknown release operation")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception:
        # Child argument lists can include signing passwords: never render them.
        raise SystemExit(
            "Release operation failed; check secret availability and build diagnostics."
        ) from None
