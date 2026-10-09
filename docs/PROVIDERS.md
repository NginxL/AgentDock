# Agent CLI support

**English** · [简体中文](PROVIDERS.zh-CN.md) · [README](../README.md)

Add an agent, select its device, then choose an installed service. The list shows provider icons and disables entries whose CLI or adapter is missing. Discovery checks executables without starting a model request or installing software. Local discovery can be refreshed in the provider menu; after a remote installation, use **Connect / check** to update that device's inventory.

## CLI entry points

These commands must be available on the selected device. Existing Codex and Claude Code transports remain separate; other entries use ACP v1 over standard input/output.

| Service / configuration key | Default command | Requirement / source |
| --- | --- | --- |
| Codex / `codex` | `codex app-server` | [Codex App Server](https://developers.openai.com/codex/app-server/) |
| Claude Code / `claude` | `claude` | [Streaming CLI](https://code.claude.com/docs/en/cli-reference) |
| Trae CLI / `trae` | `traecli acp` | [CLI reference](https://docs.trae.cn/cli_command-line-parameters); older releases are detected through local help and use `acp serve`. |
| Pi / `pi` | `pi-acp` | Install both [Pi](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) and the separate [pi-acp adapter](https://github.com/svkozak/pi-acp). |
| Cursor CLI / `cursor` | `cursor-agent acp`, or `agent acp` | [Cursor ACP](https://cursor.com/docs/cli/acp) |
| Antigravity / `antigravity` | `agy_acp_server.par` | The [ACP server](https://github.com/agentclientprotocol/registry/blob/main/antigravity-acp/agent.json) is required; the desktop app or `agy` command alone is insufficient. |
| Grok Build / `grok` | `grok --no-auto-update agent stdio` | [Headless CLI](https://docs.x.ai/build/cli/headless-scripting) |
| OpenCode / `opencode` | `opencode acp` | [ACP integration](https://opencode.ai/docs/acp/) |
| Gemini CLI / `gemini` | `gemini --acp` | [ACP registry](https://github.com/agentclientprotocol/registry/blob/main/gemini/agent.json) |
| Qwen Code / `qwen` | `qwen --acp` | [ACP registry](https://github.com/agentclientprotocol/registry/blob/main/qwen-code/agent.json) |

Detection confirms only that a command exists. Authentication, provider entitlement, models and protocol support are checked when the CLI is contacted. Sign in using the CLI on that device first. ACP adapter releases and authentication formats can differ from the corresponding desktop client. PiCode is not a separate entry: the identified [PiCode desktop project](https://github.com/Davidcreador/pi-code) uses Pi underneath.

## Conversations, settings and permissions

ACP initialization discovers capabilities and model/effort options without submitting a prompt. A conversation creates its own native session; later turns use `session/resume` or `session/load` when advertised. A CLI that cannot resume returns an error instead of silently starting a new conversation. Replayed history is discarded because AgentDock already stores those messages.

Published thinking, progress, tool calls and final text use the same conversation UI as Codex and Claude Code. The process opens while a reply is pending and collapses when the final reply arrives. Model and reasoning options come from the CLI; unsupported selections fail before sending the task. Cancellation notifies the session and terminates its owned process group.

**Ask when needed** forwards the CLI's permission choices to the user. **Full access** automatically selects a single unambiguous allow-once tool choice; questions with multiple positive choices still require a response. The CLI and operating system enforce the actual tool and sandbox policy. AgentDock does not advertise client-side file or terminal execution to ACP agents.

Pi's adapter does not intercept ordinary Pi tool execution, so Pi requires the user's explicit **Full access** selection. The adapter accepts MCP configuration but does not forward it to Pi: receiving tasks and reading approved memory included in the task prompt work, but initiating handoffs and proposing memory through AgentDock MCP tools are not available through this adapter. See [adapter limitations](https://github.com/svkozak/pi-acp#limitations).

## Files and credentials

Each ACP conversation gets a private `sessions/<session-id>/<provider>` home on its actual device. HOME, XDG directories and known provider-specific state variables point there. Selected settings and file credentials are copied once into that directory; native conversations are not imported. Files are owner-readable/writable, and deleting the conversation removes these private copies. Existing provider settings are not overwritten. Proxy and API authentication environment variables remain available to the child process.

Configuration and OAuth formats vary by CLI. Credentials outside the supported file locations, OS credential stores, or settings that explicitly redirect storage elsewhere require separate compatibility checks. Antigravity's credential-file location has not been verified, so no credential files are automatically copied for it. A trusted launcher configured below can supply the required authentication while preserving the private state directories. Authentication failures stop the run; AgentDock does not silently open a login flow or switch to a different account.

Explicit project directories remain shared. Blank workspaces are created inside each conversation's private directory. SSH agents use the same registry and ACP client on the remote device; AgentDock does not install agent CLIs or change native CLI/SSH settings there.

## Custom launchers

`commands` in the local server configuration overrides individual entries; remaining services are discovered automatically. For the macOS app this file is `~/.local/share/agentdock/config.json`. Command values are argument arrays, never shell strings:

```json
{"commands":{"gemini":["/absolute/path/to/gemini","--acp"],"pi":["/absolute/path/to/pi-acp"]}}
```

A remote device can override entries in its private `~/.local/share/agentdock/ssh/commands.json`, as a direct provider-to-argv object. Reconnect after changing it. Custom launchers must preserve AgentDock's private HOME/XDG variables and emit ACP messages on stdout. Diagnostics belong on stderr.

## Usage and validation

Codex quota comes from its App Server; Claude quota comes only from events during actual CLI runs. Other providers show unknown quota instead of another provider's snapshot. ACP context occupancy is not cumulative token consumption; it is never added to token totals or TPS. Throughput without an output-token sample remains unknown during execution.

Offline checks exercise every ACP registry entry with deterministic peers: model configuration, two-turn continuation, streaming phases, permission options, cancellation, malformed messages, private storage and deletion. An isolated SSH worker check covers discovery, models and continued ACP conversations without contacting production infrastructure. Local Trae verification passed model discovery and two consecutive turns with unchanged original configuration hashes. Codex and Claude live checks are documented in [Validation](REVIEW.md). Other ACP entries have protocol-fixture coverage; live account, authentication and tool execution compatibility remains unverified.

Commands were checked against primary CLI documentation and [ACP Registry revision `01f372c`](https://github.com/agentclientprotocol/registry/tree/01f372c271a2344ec944dd36f6305b20171a7e1d) on 2026-09-29. ACP behavior follows [session setup](https://agentclientprotocol.com/protocol/v1/session-setup), [prompt turns](https://agentclientprotocol.com/protocol/v1/prompt-turn) and [configuration options](https://agentclientprotocol.com/protocol/v1/session-config-options).
