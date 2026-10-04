# Validation and compatibility

**English** · [简体中文](REVIEW.zh-CN.md) · [README](../README.md) · [Architecture](ARCHITECTURE.md)

ACP checks exercise model/effort options, continued sessions, message phases, permission choices, timeouts/cancellation, invalid messages, private directories and cleanup with deterministic peers. An isolated SSH worker verifies remote discovery, model reading and continuation. Live Trae model discovery and two-turn dialogue passed with unchanged original configuration hashes. Other new services still need live account and tool validation; see [CLI support](PROVIDERS.md).

## Implementation status

AgentDock 0.3 combines a React interface, a Python standard-library service, and SQLite storage. Native Codex and Claude Code processes execute tasks; the dispatcher retains their session identifiers and routes work and results. Five scoped MCP tools expose collaboration and reviewed project memory. The macOS application bundles a dedicated usage helper that supplies sanitized quota snapshots through `--probe`.

| Area | Implemented | Acceptance boundary |
| --- | --- | --- |
| Interface | Chinese by default, English switching, project navigation, native-session status, conversation events, task dispatch, approvals, shared memory, and quota summaries. | Offline previews use the actual interface with fictional fixtures. They do not demonstrate real model execution, subscriptions, or quota availability. |
| Native providers | Codex app-server JSON-RPC; Claude Code stream-json control messages; retained native IDs, text/tool events, permission decisions, deadlines, and process-group cleanup. | Local CLI conversations and tool events passed. Additional client releases, accounts and models still require acceptance testing. |
| Collaboration | Automatic dispatch, workspace-aware queuing, native-session continuation, result return, retry deduplication, depth and run limits, and cancellation of task descendants. | Real model behavior during delegation and long-running collaboration requires live acceptance. |
| Shared memory | Project isolation, literal keyword search, version conflicts, agent proposals, human approval, soft archive, and database history. | Vector search, automatic extraction, a complete history browser, and cross-project sharing are not implemented. |
| Quotas | Built-in usage helpers for Codex and Claude, timeout/throttle handling, unknown/stale/error states, and separate manual subscription records. | Local Codex quota queries and Claude Desktop snapshot reads passed; additional accounts and comparison with official usage pages remain unverified. |
| Recovery | Additive database migration, historical mailbox preservation, one owner per native session and environment, overlapping-workspace exclusion, database instance locking, and no automatic task replay after restart. | Existing Codex App or unrelated terminal sessions cannot be imported. Automatic worktrees and remote multi-user access are not implemented. |
| SSH environments | Remote CLI execution, model discovery, ordered progress, native continuation, permission/MCP round trips, idempotent submission, cancellation and a 90-second lease. | Two-turn Linux conversations passed for both providers. Extended outages, host reboot and complex tool workflows require deployment-specific acceptance. |

## Provider compatibility

| Provider | Locally inspected version | Contract used |
| --- | --- | --- |
| Codex | `codex-cli 0.154.0` | Generated app-server JSON schemas and official app-server documentation: `initialize`, `thread/start`, `thread/resume`, `turn/start`, approval requests, event notifications, and `turn/interrupt`. |
| Claude Code | `2.1.283` | Native CLI help and Anthropic's public control-protocol definitions: `--print`, `--input-format stream-json`, `--output-format stream-json`, `--resume`, `--session-id`, and stdio permission requests. |

These are **contract inspection versions**, not a claim of end-to-end compatibility or a supported minimum across all releases. Claude's adapter uses `--permission-mode manual` by default, or `bypassPermissions` when the user selects Full access, with `--permission-prompt-tool stdio`. Unsupported flags fail; the adapter never automatically retries with broader permissions. The native CLI decides authentication using its own supported local configuration. AgentDock does not require an API key, export provider credentials, change login state, or install an agent SDK.

In Ask for approval mode, Codex starts an app-server process owned by the run, with `workspace-write`, `untrusted` command approval, and user review. It creates or resumes only an AgentDock-owned thread. Claude uses its manual permission policy and sends permission prompts to the workbench; an approval returns the original tool input for that action, while denial does not grant it. Existing native policies and managed restrictions still apply. AgentDock itself does not provide a separate operating-system sandbox.

Full access selects Codex `danger-full-access` plus `never`, or Claude `bypassPermissions`. Offline tests cover both providers, local and SSH forwarding, native resume after reducing permissions, invalid values, migration defaults and prevention of model-initiated permission edits. Isolated local CLI initialization accepted both modes; Codex returned the requested sandbox and approval policy. Full-access model tool execution on production hosts is not part of this validation.

The native process ends after a foreground turn, but the native conversation persists for the next run. Claude's child environment sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` to disable native background work, as described in the [official environment-variable documentation](https://code.claude.com/docs/en/env-vars). The setting does not change the user's global environment or other Claude processes. Registered agents collaborate through AgentDock's dispatcher. This is session continuation, not attachment to an already running desktop or terminal process. Quota visibility and execution authentication are independent: a quota snapshot does not establish that a provider can execute tasks.

Official protocol material: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [Claude Code CLI](https://code.claude.com/docs/en/cli-reference), and [Anthropic's control-protocol implementation](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/query.py).

Local Codex 0.154.0 and Claude Code 2.1.283 passed two-turn text continuation in private storage, native identity continuity, reported-model metadata, absence of test conversations in original client directories, and unchanged configuration hashes. Claude credential reuse covers the default macOS login store. Codex verification covers file credentials. Keyring-only login is bound to CODEX_HOME and cannot be reused directly in an isolated session; use a separate AgentDock account. Real keyring migration and authorization have not been tested.

## Isolated verification

Project reuse checks cover separate project names, roles, settings, native bindings, directories, memory, tool capabilities and cancellation, including everyday conversations. Deletion and schema migration preserve other members. Browser tests cover the shared conversation index, project/everyday filters, explicit recipients, drafts, creation, missing IDs and history navigation. Production SSH hosts and real model requests are not used by these checks.

Backend checks use temporary SQLite databases, fake native CLI processes, and fake Built-in usage helpers. Dispatcher integration tests use a temporary loopback HTTP endpoint and the actual MCP bridge, but all coding agents are deterministic local fixtures. No real model, provider login, or live quota endpoint is involved.

Frontend checks use simulated DOM and HTTP responses. The production build validates TypeScript and generates static assets. The offline demonstration renders fictional projects, conversations, and quota values; it disables execution, mutation, and provider requests. Screenshots of that mode illustrate the interface only.

| Test area | Coverage |
| --- | --- |
| Native protocol | New and resumed sessions, metadata-only Codex resume, exact native identity, published thinking summaries and tool output streams, streaming without duplicate final text, permission allow/deny round trips, child-scoped Claude foreground policy, mismatched session/turn IDs, invalid JSON, early exits, and sanitized failures. |
| Resource bounds | Output limits, permission expiry, run deadlines while approval is blocked, cancellation, descendant-process cleanup, and MCP authority revocation. |
| Dispatcher and MCP | Automatic delivery and return to the exact requesting session, final-result settlement after nested or multiple child tasks, queued-work admission, workspace exclusion, idempotency, failure propagation, cancellation, and reserved reply capacity. |
| Storage and authorization | Project and sender isolation, user-defined role persistence and administrator-only edits, native-session ownership, database migration, restart behavior, single-instance locking, memory version conflicts, and reviewed provenance. |
| Quotas and interface | Role creation/editing/clearing without provider presets, future-turn role changes, preservation of failed-edit drafts and native history, stale/unknown/zero quota distinctions, configured-agent quota scope, empty-state behavior, task status transitions and expandable execution details, page-entry refresh, repeated-click coalescing, delayed state updates, safe rendering, language switching, and consistency between visible status and API records. |

Conversation checks cover distinct question bubbles, public process output and final replies; automatic expansion before a reply, collapse on final arrival, manual toggles preserved across event updates, and separate state per task. Protocol fixtures cover missing Codex phases, native message identity, completed-text replacement, Claude multi-block replies, and exclusion of commentary from final results. Legacy joined results are split for display only when complete event groups reproduce the stored text exactly; incomplete history is preserved.

Persistent transport checks use real pipes, the SSH bootstrap and a loopback HTTP server with isolated fake native CLIs. They cover shared channels across tasks, cursor replay after disconnection, no duplicate task launch, independent approvals, cancellation during slow model discovery, and cleanup of metadata processes on exit. SSE checks cover authentication boundaries, commit/subscribe races, unpublished rollbacks, bounded history batches, split UTF-8, replay deduplication and fallback to older servers. Model prewarming queries metadata only for configured connections and shares the menu cache.

Reproduce the automated checks without starting a real agent:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q agentdock tests
cd web
npm ci --ignore-scripts
npm test
npm run build
cd ..
swift run --package-path native MeterChecks
swift run --package-path native MeterProviderChecks
swift run --package-path native DesktopChecks
```

[CI](../.github/workflows/check.yml) runs backend checks on Python 3.9 and 3.12, and frontend checks on Node 20, plus desktop builds and offline usage checks on macOS. Desktop checks cover menu quota formatting, expiration, unknown values, bounded summaries, and both languages. The API and interface checks cover cache-only reads, automatic page-entry refresh, absence of Keychain authorization controls, and language synchronization. Timer checks use simulated time to verify 600-second intervals, provider failure isolation, non-interactive reads, missed-tick handling and shutdown cleanup. Passing these checks validates the local contracts and lifecycle behavior exercised by fixtures. It does not validate actual provider accounts, model decisions, CLI releases beyond those inspected, or live quota accuracy.

Runtime relocation checks cover local-to-SSH and SSH-to-local execution for both providers, queued and active tasks, native continuation, frozen model and permission defaults, explicit versus automatic dispatch, repeated moves, restart persistence, and cleanup on each original location. These checks use deterministic fixtures, without production model requests.

The agent setup checks cover inline SSH registration and retry, connection reuse, deferred model discovery, preserved collapsed drafts, and equal agent names with separate session and quota bindings. Menu summaries use custom names and retain compatibility with older quota snapshots.

Device setup checks cover blank user-entered SSH addresses, reuse and replacement of saved connections, read-only directory browsing on each selected host, bounded listings, cancellation and retries. Composer checks cover Enter submission, Shift+Enter, IME confirmation, empty and disabled drafts, and duplicate-submit prevention.

Project navigation checks cover the unified entry, project listing and creation, Agents/Tasks/Memory navigation, content isolation across projects, return paths from project conversations, browser history and both languages. Existing `messages`, `memory` and project-scoped `workspace` links still open the corresponding project view; unavailable projects return to the list. Navigation does not change persisted records or execution permissions.

## Code review map

SSH tests execute the actual bootstrap and detached runner under an isolated home directory with fake CLIs. They cover lost acknowledgments, event-read retries, permission responses, shared-memory calls, cancellation, expired leases, final-result persistence and environment isolation. A separate live Linux check exercised Codex 0.155.1 and Claude Code 2.1.277 model discovery, two-turn continuation and usage events. Existing Codex, Claude and SSH configuration files were compared against pre-test hashes. See [SSH verification scope](SSH.md#verification-scope).

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
4. Verify shared-memory proposal review, version conflicts, and project isolation. Compare real remaining quotas and reset times with official usage pages, including failure and stale-cache states.
5. Inspect both interface languages using live sessions. Confirm errors, queued work, approvals, results, and unknown quota states are understandable and contain no exposed credentials.

Desktop startup, automatic local connection, shutdown cleanup, and live Codex/Claude quota reads have passed local macOS checks. Two-turn conversations and token events passed for both providers. Additional accounts, tool approvals, long-running collaboration and official-page quota comparisons still require live acceptance; existing-session import is not implemented. The installer does not register a background service, login item, or global MCP configuration, and does not alter provider logins.


## 0.3 verification

Dedicated conversation-page tests cover agent entry, return navigation, browser back and forward, unavailable links, and separate conversation selections and drafts per agent. The overview does not fetch conversation events; opening an agent fetches only the selected conversation.

Automated coverage includes independent agent execution, project-memory isolation, overlapping directories, legacy database migration, model/effort forwarding, usage events, repeated message blocks, live/history deduplication, archived copies, append/truncation, and idle versus unknown TPS. Native quota checks cover source timestamps, unknown resets, invalid percentages and ambiguous organizations.

Local smoke tests ran two consecutive turns each with Codex and Claude, verified the same native session retained a test marker, and received usage events. Native model discovery and Claude Desktop snapshot reads passed. Automated tests use offline fixtures; live checks are separate from CI and do not establish compatibility across all models, accounts or releases.

---

**English** · [简体中文](REVIEW.zh-CN.md) · [README](../README.md) · [Architecture](ARCHITECTURE.md)

Local manager checks confirmed Codex and Claude CLI messages, tool events, final replies and running-to-completed transitions in isolated workspaces. Offline protocol tests cover thinking deltas and summary replacement; the presence of thinking text in a real task depends on what its CLI publishes. Unbound local history is excluded from all statistics, and configuring an agent does not trigger history import.
