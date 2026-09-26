# Validation and compatibility

**English** · [简体中文](REVIEW.zh-CN.md) · [README](../README.md) · [Architecture](ARCHITECTURE.md)

## Implementation status

AgentDock 0.2 combines a React interface, a Python standard-library service, and SQLite storage. Native Codex and Claude Code processes execute tasks; the dispatcher retains their session identifiers and routes work and results. Five scoped MCP tools expose collaboration and reviewed project memory. AgentMeter remains a separate application that supplies quota snapshots through `--probe`.

| Area | Implemented | Acceptance boundary |
| --- | --- | --- |
| Interface | Chinese by default, English switching, project navigation, native-session status, conversation events, task dispatch, approvals, shared memory, and quota summaries. | Offline previews use the actual interface with fictional fixtures. They do not demonstrate real model execution, subscriptions, or quota availability. |
| Native providers | Codex app-server JSON-RPC; Claude Code stream-json control messages; retained native IDs, text/tool events, permission decisions, deadlines, and process-group cleanup. | Wire contracts have been checked against documentation and local CLI metadata. Real login and model execution remain unverified. |
| Collaboration | Automatic dispatch, workspace-aware queuing, native-session continuation, result return, retry deduplication, depth and run limits, and cancellation of task descendants. | Real model behavior during delegation and long-running collaboration requires live acceptance. |
| Shared memory | Project isolation, literal keyword search, version conflicts, agent proposals, human approval, soft archive, and database history. | Vector search, automatic extraction, a complete history browser, and cross-project sharing are not implemented. |
| Quotas | AgentMeter probes for Codex and Claude, timeout/throttle handling, unknown/stale/error states, and separate manual subscription records. | Real Keychain prompts, account compatibility, and agreement with official usage pages remain unverified. |
| Recovery | Additive database migration, historical mailbox preservation, one owner per native session, overlapping-workspace exclusion, database instance locking, and no automatic task replay after restart. | Existing Codex App or unrelated terminal sessions cannot be imported. Remote devices, automatic worktrees, and remote multi-user access are not implemented. |

## Provider compatibility

| Provider | Locally inspected version | Contract used |
| --- | --- | --- |
| Codex | `codex-cli 0.154.0` | Generated app-server JSON schemas and official app-server documentation: `initialize`, `thread/start`, `thread/resume`, `turn/start`, approval requests, event notifications, and `turn/interrupt`. |
| Claude Code | `2.1.268` | Native CLI help and Anthropic's public control-protocol definitions: `--print`, `--input-format stream-json`, `--output-format stream-json`, `--resume`, `--session-id`, and stdio permission requests. |

These are **contract inspection versions**, not a claim of end-to-end compatibility or a supported minimum across all releases. Claude's adapter uses `--permission-mode manual` and `--permission-prompt-tool stdio`; a CLI that does not accept those flags will fail rather than fall back to permission bypass. The native CLI decides authentication using its own supported local configuration. AgentDock does not require an API key, export provider credentials, change login state, or install an agent SDK.

Codex starts an app-server process owned by the run, with `workspace-write`, `untrusted` command approval, and user review. It creates or resumes only an AgentDock-owned thread. Claude uses its manual permission policy and sends permission prompts to the workbench; an approval returns the original tool input for that action, while denial does not grant it. Existing native policies and managed restrictions still apply. AgentDock itself does not provide a separate operating-system sandbox.

The native process ends after a foreground turn, but the native conversation persists for the next run. Claude's child environment sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` to disable native background work, as described in the [official environment-variable documentation](https://code.claude.com/docs/en/env-vars). The setting does not change the user's global environment or other Claude processes. Registered agents collaborate through AgentDock's dispatcher. This is session continuation, not attachment to an already running desktop or terminal process. Quota visibility and execution authentication are independent: a quota snapshot does not establish that a provider can execute tasks.

Official protocol material: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [Claude Code CLI](https://code.claude.com/docs/en/cli-reference), and [Anthropic's control-protocol implementation](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/query.py).

## Isolated verification

Backend checks use temporary SQLite databases, fake native CLI processes, and fake AgentMeter probes. Dispatcher integration tests use a temporary loopback HTTP endpoint and the actual MCP bridge, but all coding agents are deterministic local fixtures. No real model, provider login, or live quota endpoint is involved.

Frontend checks use simulated DOM and HTTP responses. The production build validates TypeScript and generates static assets. The offline demonstration renders fictional projects, conversations, and quota values; it disables execution, mutation, and provider requests. Screenshots of that mode illustrate the interface only.

| Test area | Coverage |
| --- | --- |
| Native protocol | New and resumed sessions, metadata-only Codex resume, exact native identity, streaming without duplicate final text, permission allow/deny round trips, child-scoped Claude foreground policy, mismatched session/turn IDs, invalid JSON, early exits, and sanitized failures. |
| Resource bounds | Output limits, permission expiry, run deadlines while approval is blocked, cancellation, descendant-process cleanup, and MCP authority revocation. |
| Dispatcher and MCP | Automatic delivery and return to the exact requesting session, final-result settlement after nested or multiple child tasks, queued-work admission, workspace exclusion, idempotency, failure propagation, cancellation, and reserved reply capacity. |
| Storage and authorization | Project and sender isolation, native-session ownership, database migration, restart behavior, single-instance locking, memory version conflicts, and reviewed provenance. |
| Quotas and interface | Stale/unknown/zero quota distinctions, explicit refresh, delayed state updates, safe rendering, language switching, and consistency between visible status and API records. |

Reproduce the automated checks without starting a real agent:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q agentdock tests
cd web
npm ci --ignore-scripts
npm test
npm run build
```

[CI](../.github/workflows/check.yml) runs backend checks on Python 3.9 and 3.12, and frontend checks on Node 20. Passing these checks validates the local contracts and lifecycle behavior exercised by fixtures. It does not validate actual provider accounts, model decisions, CLI releases beyond those inspected, or live quota accuracy.

## Code review map

| Area | Review focus |
| --- | --- |
| [Architecture](ARCHITECTURE.md) and [API](API.md) | Native sessions, task lifecycle, result return, memory review, execution limits, and review mode. |
| [Storage](../agentdock/store.py) | Ownership, durable task relationships, migration, idempotency, version checks, and restart handling. |
| [Dispatcher](../agentdock/runtime.py) and [providers](../agentdock/providers.py) | Queue admission, session binding, approvals, bounded IO, cancellation, and result propagation. |
| [MCP bridge](../agentdock/mcp.py), [quota bridge](../agentdock/quota.py), and [server](../agentdock/server.py) | Capability scope, fixed provider commands, loopback authentication, output sanitization, and shutdown order. |
| [Interface](../web/src/) and [tests](../tests/) | Accurate execution states, read-only offline previews, bilingual copy, safe display of agent output, and regressions. |

## Live acceptance requirements

Real execution is a separate, explicitly enabled acceptance step. Use trusted disposable workspaces and complete these checks before relying on the preview for regular work:

1. Verify native CLI authentication and the configured CLI versions. Complete two turns with each provider and confirm that the second turn resumes the same native conversation.
2. Verify permission allow, denial, expiry, cancellation, and restart behavior. Confirm queued tasks do not launch after cancellation and unfinished tasks do not replay after restart.
3. Run a Codex → Claude → Codex collaboration and a nested delegation. Confirm the original sender receives the final result in its original conversation and that limits stop repeated delegation.
4. Verify shared-memory proposal review, version conflicts, and project isolation. Compare real AgentMeter remaining quotas and reset times with official usage pages, including failure and stale-cache states.
5. Inspect both interface languages using live sessions. Confirm errors, queued work, approvals, results, and unknown quota states are understandable and contain no exposed credentials.

Real agent execution, real quota refresh, and existing desktop-session import have **not** passed live acceptance; existing-session import is not implemented. The preview does not install a background service, start at login, register global MCP configuration, or alter AgentMeter or provider logins.

---

**English** · [简体中文](REVIEW.zh-CN.md) · [README](../README.md) · [Architecture](ARCHITECTURE.md)
