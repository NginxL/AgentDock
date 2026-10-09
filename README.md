<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="AgentDock logo" /></p>
<h1 align="center">AgentDock</h1>
<p align="center">Native agent sessions. Connected work. One clear workspace.</p>

**English** · [简体中文](README.zh-CN.md) · [Checks](https://github.com/NginxL/AgentDock/actions/workflows/check.yml)

AgentDock is a local, single-user workbench for Codex and Claude Code CLIs on your Mac or an SSH host. Keep native conversations, delegate work to a project teammate, receive results in the original conversation, and review delivery against acceptance criteria. Project roles, history and reviewed memory stay separate from everyday chats.

![Workspace with fictional demo data](docs/images/workspace.en.jpg)

**Developer preview.** The backend uses Python's standard library and SQLite; the interface uses React, and the macOS shell uses Swift. Additional ACP providers, automatic failover and Codex native client switching remain default-off experiments while the [development plan](docs/DEVELOPMENT-PLAN.md) is implemented in reviewed batches. Claude quota comes only from running CLI sessions. [Capabilities and boundaries](docs/EXPERIMENTS.md).

## Quick start

Source development needs Python **3.11+**, Node.js **20.19+**, and an installed, authenticated agent CLI. SSH hosts also need Python 3.11+. Existing provider networking remains in effect.

```bash
git clone https://github.com/NginxL/AgentDock.git
cd AgentDock
python3 -m venv .venv
npm --prefix web ci --ignore-scripts
npm --prefix web run build
.venv/bin/python -m agentdock
```

Open the printed loopback URL and enter the token from the printed local file. The port is allocated automatically. This starts in review mode; add `--enable-execution` to run agents. Data is private to `~/.local/share/agentdock`. Project files are shared when explicitly selected; conversation records stay isolated.

For a macOS source installation, run `.venv/bin/python scripts/install-macos.py` (macOS 14+ and Apple Command Line Tools). Distributed app builds include Python; Python wheels include the web interface and an `agentdock` command. See [building and installing packages](docs/DISTRIBUTION.md); notarized releases require the maintainer's Apple credentials.

## Documentation

- [User guide](docs/USER_GUIDE.md): conversations, settings, models, deletion and usage.
- [Project tasks](docs/TASKS.md), [accounts](docs/ACCOUNTS.md), [providers](docs/PROVIDERS.md), [SSH](docs/SSH.md).
- [Architecture](docs/ARCHITECTURE.md), [API](docs/API.md), [credential protection](docs/CREDENTIALS.md).
- [Review fixes and measurements](docs/REMEDIATION.md), [validation](docs/REVIEW.md), [changelog](CHANGELOG.md).
- [Optional real CLI verification](docs/DISTRIBUTION.md#live-cli-verification): manual, on a trusted machine outside GitHub Actions.

[Upgrade notes](docs/UPGRADING.md) · [Follow-up review and regression index](docs/REVIEW-FOLLOWUP.md)

## Development

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
./scripts/check.sh
.venv/bin/ruff check agentdock
.venv/bin/ruff format --check agentdock tests scripts setup.py
.venv/bin/mypy
```

Regular tests use fake CLIs and temporary data. They do not switch real accounts or submit model requests. [Report an issue](https://github.com/NginxL/AgentDock/issues) with sanitized steps and the diagnostic error ID.

[MIT](LICENSE) · [Third-party notices](NOTICE.md). AgentDock is independent of the CLI providers; their subscriptions and service terms still apply.
