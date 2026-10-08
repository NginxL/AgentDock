# Builds, installation and live verification

## Runtime and version

Python 3.11+ is required locally and on SSH hosts. Select a compatible remote interpreter in the connection's advanced settings; AgentDock never upgrades a remote system interpreter. The version comes from `agentdock/__init__.py`; Python metadata, web builds and macOS bundle metadata read that value.

The desktop host prefers `Resources/Python/bin/python3`. Source installations can fall back from an unavailable saved interpreter to compatible Homebrew/PATH interpreters. Existing CLI environment and proxy settings remain unchanged. Both the desktop service and SSH worker's MCP bridge bind IPv4 loopback without reverse-DNS lookup. The desktop trusts only the complete readiness line from its own child and the actual allocated port.

`--port 0` is the default; an explicit fixed port remains supported. A second process cannot own the same database or rotate its access token. Configure `run_timeout` (30–86,400 seconds, default 900) and `approval_timeout` (1–120 seconds, default 120); an Agent's own run timeout overrides the service default.

## Python packages

Build the interface before building a source distribution or wheel:

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run build
.venv/bin/python -m pip install build==1.4.0
.venv/bin/python -m build
pipx install dist/agentdock_workbench-*.whl
agentdock
```

The wheel includes static frontend assets and dependency notices. Installing a built wheel needs Python 3.11+, but no Node or Swift toolchain. A source distribution includes the prebuilt interface; it does not download or build frontend dependencies during installation. PyPI publication is not configured.

CI installs the wheel into a fresh environment and verifies its frontend, authenticated state API, automatic port and clean shutdown using temporary data, with execution disabled.

## macOS packages

**Build packages** is a manual GitHub Actions workflow for Apple Silicon and Intel. It creates a portable Python distribution, builds the Swift shell and web assets, then uploads an app ZIP. Download the artifact matching the Mac's architecture and copy AgentDock.app to Applications. Default artifacts are ad-hoc signed and **not notarized**.

For a local package build:

```bash
uv python install --install-dir dist/portable-python --no-bin 3.13
.venv/bin/python scripts/package-macos.py --python-runtime dist/portable-python/cpython-3.13.<patch>-macos-aarch64-none
```

Use the actual directory printed by uv. Packaging does not install or launch the app, open user databases, change proxy configuration or switch accounts. All runtime symlinks must stay inside the portable distribution. The copied Python is checked after relocation; native files are signed before the enclosing app.

Choosing **notarize** in the workflow requires these repository secrets:

| Secrets | Purpose |
| --- | --- |
| `APPLE_SIGNING_IDENTITY`, `APPLE_CERTIFICATE_P12_BASE64`, `APPLE_CERTIFICATE_PASSWORD` | Developer ID Application certificate |
| `APPLE_TEMP_KEYCHAIN_PASSWORD` | Temporary runner keychain |
| `APPLE_NOTARY_KEY_BASE64`, `APPLE_NOTARY_KEY_ID`, `APPLE_NOTARY_ISSUER_ID` | App Store Connect notarization key |

Signing material exists only in the isolated GitHub runner and is removed even if the job fails. The workflow checks notarization, staples the ticket and verifies Gatekeeper assessment before uploading the notarized ZIP. **Signing and notarization with real Apple credentials remain unverified.** No certificate or key is included in the repository.

Sources: [GitHub runner architectures](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [uv portable Python installation](https://docs.astral.sh/uv/guides/install-python/), [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

## Live CLI verification

`python3 scripts/live-e2e.py` prints the verification plan and performs no model requests. Executing it requires both `--live` and `AGENTDOCK_LIVE_E2E=1` on a **dedicated** runner with separately provisioned Codex and Claude Code logins:

- Two turns for each provider verify dialogue and native resume.
- A project owner delegates a bounded acknowledgement to a worker, receives its result, submits delivery and reaches acceptance.
- The test has a total deadline, fails on unexpected approvals and never automatically grants full access, retries another account or performs account switching.

The **Optional live CLI verification** workflow requires an `agentdock-live` self-hosted runner. Manual runs require the explicit model-usage confirmation. Nightly runs are skipped unless repository variable `LIVE_E2E_ENABLED=true`. Pull requests cannot trigger it. It consumes provider quota when enabled.

Only stage/status metadata is printed. Temporary databases, prompts, transcripts, authentication data and raw provider errors are not uploaded. CLI authentication and proxy configuration must be provisioned on the dedicated runner; the workflow does not contain them. Current automated verification covers the opt-in gate and fake-protocol collaboration; **real execution of this new workflow remains unverified**. Native account switching and actual OAuth refresh remain manual acceptance items.
