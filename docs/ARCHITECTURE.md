# Architecture

**English** · [简体中文](ARCHITECTURE.zh-CN.md) · [Back to README](../README.md)

AgentDock 0.3 is a local, single-user workbench. It manages native sessions created through its own runtime. Automated verification uses simulated CLI processes; live provider interoperability remains an acceptance item.

## Components

```mermaid
flowchart LR
  Human[Human] --> UI[React workbench]
  UI -->|Loopback HTTP + admin token| API[Python service]
  API --> DB[(SQLite)]
  API --> Queue[Bounded dispatcher]
  Queue -->|App Server JSON-RPC| Codex[Codex CLI]
  Queue -->|Bidirectional JSON stream| Claude[Claude Code CLI]
  Codex --> MCP[Scoped MCP tools]
  Claude --> MCP
  MCP --> API
  API --> Meter[Built-in usage helper]
```

| Component | Code | Responsibility |
| --- | --- | --- |
| Workbench | `web/src/` | Projects, agents, conversations, execution queue, task handoffs, reviewed memory, quotas and permission prompts. Chinese is the default; English is selectable. |
| HTTP boundary | `agentdock/server.py` | Loopback Host/Origin validation, bearer authentication, bounded requests, and separate human/tool routes. |
| Durable state | `agentdock/store.py` | Native bindings, task ownership, transactional queue claims, delivery/result links, memory history, token hashes and approvals. |
| Dispatcher | `agentdock/runtime.py` | Explicit submission, automatic dispatch and result return, task settlement, approval deadlines and cancellation. |
| Native transports | `agentdock/providers.py` | Codex App Server and Claude stream-json protocols, stream parsing, session identity checks, bounded output and process cleanup. |
| Agent tools | `agentdock/mcp.py` | Five tools: agent discovery, addressed dispatch, task status, memory search and memory proposals. |
| Quota bridge | `agentdock/quota.py` | Scheduled and page-entry Codex/Claude probes through the built-in macOS helper, sanitized snapshots and freshness rules. |

The browser's `?demo=1` mode reads fictional fixtures and makes no API requests. It cannot execute agents, dispatch tasks or refresh quotas.

## Sessions and turns

A session belongs to one agent and optionally a project. Its working directory is fixed when created. Its `native_session_id` is initially empty and is bound only by that session's active run. Once bound, a different native ID is rejected. IDs belonging to another managed session cannot be rebound.

Codex starts or resumes a thread through `codex app-server`. Claude starts with a generated session UUID or resumes the saved UUID through the native CLI. Each turn launches a bounded subprocess and closes it afterwards; conversation continuity comes from the provider's native persisted session, not a long-running process or replayed UI history.

Each conversation stores native history, indexes and caches in `sessions/<session-id>/codex` or `sessions/<session-id>/claude`, under the local AgentDock data directory or the remote SSH controller’s private directory. Codex isolates both `CODEX_HOME` and SQLite storage, snapshots settings and links existing file credentials for the native CLI to use. Claude uses a private `CLAUDE_CONFIG_DIR` and retains the original credential-store location through `CLAUDE_SECURESTORAGE_CONFIG_DIR`, with copied settings. Child processes do not inherit the Codex desktop control pipe or session identifiers. Native clients remain responsible for credential refresh.

Automatic workspaces live in the conversation’s `workspace` subdirectory; explicit project directories stay shared. Deletion requires this session and linked tasks to be idle, then removes private files and records. A failed remote cleanup leaves the record available for retry. Upgrades migrate only AgentDock-owned native histories. Codex successfully resumes the private copy before removing its legacy duplicate through the native API; unrelated desktop and terminal sessions are not imported.

Agent names and optional roles are defined by the user, independently of the CLI provider. Each turn reads the latest saved role when building its prompt. Role edits preserve existing native bindings and history; they do not rewrite a prompt already sent to a provider.

The prompt contains the current task and a bounded reference block with the agent role and approved project memory. Private conversation history remains with the native CLI. Shared memories and teammate results are marked as reference data, not authority; this labeling does not guarantee resistance to prompt injection.

Authentication and model selection follow the locally installed CLI's configuration. Execution uses the CLI’s authentication; the built-in quota helper reads a Claude Desktop quota snapshot or queries the Codex-owned App Server without reading credentials. Compatibility depends on the installed CLI and its provider/account configuration. Existing desktop or terminal conversations cannot currently be attached.

## Queue and task settlement

Human submission creates a `queued` run. The dispatcher claims work transactionally and starts at most four workers. Runs belonging to the same agent, or using equal or parent/child overlapping canonical workspace paths, execute sequentially. Independent workspaces can execute in parallel. This prevents concurrent managed writes; it is not a filesystem sandbox.

```mermaid
stateDiagram-v2
  [*] --> queued: explicit submission or addressed task
  queued --> running: agent and workspace available
  queued --> cancelled: cancel
  running --> completed: native turn finishes
  running --> failed: protocol, process or deadline error
  running --> cancelled: cancel
  queued --> interrupted: restart
  running --> interrupted: restart
```

A run represents **one native turn**, not necessarily a complete delegated task. `root_run_id` groups the collaboration chain; `parent_run_id` records causality. `task_run_id` groups a task's initial turn and later result-consumption turns.

An agent calls `message_send` with the target agent, task body and optional target session. Identity is derived from the active run capability. Both agents must belong to the same project. The service atomically creates a delivery and queued run; the returned ID tracks real work. If no target session is given, the target's most recently updated managed session is used, or a new session is created.

```mermaid
sequenceDiagram
  participant A as Agent A
  participant Q as Dispatcher
  participant B as Agent B
  participant C as Agent C
  A->>Q: Delegate task to B
  Note over A: Finish current turn
  Q->>B: Start or resume native session
  B->>Q: Delegate subtask to C
  Note over B: Finish turn; task is waiting
  Q->>C: Execute subtask
  C-->>Q: Result
  Q->>B: Resume with C result
  B-->>Q: Final combined result
  Q->>A: Resume with B result
```

Completed initial turns with outstanding child results leave their delivery in `waiting`. Settlement waits for child deliveries and their result-return turns before publishing the final task result. A return run resumes the exact requesting session and belongs to that sender's logical task. The message's `reply_run_id` makes scheduling idempotent. Human-addressed tasks have no automatic return session.

Dispatch depth is limited to three and each chain to 16 runs, including reserved result-return capacity. A conflicting idempotency key is rejected. These bounds constrain automation; they do not estimate or cap provider billing. Agents are instructed to finish their current turn after dispatch so that a shared workspace can become available.

Cancellation stops queued/running descendants, revokes scoped tools, and terminates active process groups. A cancelled child can report cancellation to a still-active parent task. Failure or cancellation prevents a stopped task from being resumed by a late result. Workbench restart marks unfinished runs/deliveries interrupted, invalidates approvals and capabilities, and never replays them automatically.

## Permission handling and process limits

Each agent stores `permission_mode`: `ask` by default (including migrated records), or `full_access`. The authenticated human API validates the enum; queued/running tasks prevent changes. The dispatcher passes the setting to the local adapter or remote worker on every turn, including native resumes. Model output and MCP capabilities cannot change it.

| Mode | Codex | Claude Code |
| --- | --- | --- |
| `ask` | `approvalPolicy: untrusted`, `sandbox: workspace-write`, user review | `--permission-mode manual`, stdio permission requests |
| `full_access` | `approvalPolicy: never`, `sandbox: danger-full-access` | `--permission-mode bypassPermissions` |

Invalid values are rejected before starting a native CLI. Full access removes routine CLI approval prompts, subject to system account permissions and upstream managed policies; it does not widen AgentDock MCP capabilities. The Claude child process receives `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, so shell and subagent work stays in the foreground and finishes within the managed turn; user-wide settings are unchanged. Permissions appear as human-only, single-use options in the UI. Unknown control requests are rejected; Codex's unsupported elicitation forms are declined. The provider's own permission behavior still applies; the UI does not guarantee every upstream action will prompt.

Runs have a 15-minute deadline. An unanswered permission request expires after 120 seconds. The native transport bounds stdout/stderr to 8 MiB combined, each JSON line to 512 KiB, protocol messages to 10,000 and permission/control requests to 64. The dispatcher separately caps stored events to 5,000 and 8 MiB per run. Stderr is drained but not persisted; stable errors omit raw provider details. Shared process-group cleanup handles native CLIs and quota probes.

## SSH execution environments

`environments` stores local and SSH connections. Agents, projects and sessions carry `environment_id`, defaulting existing records to `local`. The migration backs up existing databases before adding environment ownership. An agent's environment is immutable; native identity, workspace exclusion, quota snapshots and subscription records are scoped by environment.

`remote.py` submits turns through system SSH. `ssh_worker.py` installs under a content-addressed private directory and runs the existing remote CLI. Run requests are persisted with a fingerprint before acknowledgment; retrying the same Run ID does not launch another worker. Ordered events carry progress and control requests. Final state is returned only after prior events have been consumed. The SSH transport does not expose the local API or forward local credentials.

Permission and MCP requests return to the local controller with a request ID. Responses return to the same remote worker; terminal replies are stored separately from progress. Short disconnections resume from an event cursor. A 90-second lease, explicit cancellation and process-group cleanup bound unattended execution. Controller restart does not replay unfinished work. Remote records currently have no automatic retention cleanup. See [SSH lifecycle and identity](SSH.md).

The local history scanner excludes remote bindings. Remote token/TPS counters come from managed live events and use environment-prefixed identities. Remote Codex quota reads use its own App Server; remote Claude returns unknown. Remote readings never fall back to local accounts.

## Shared memory

Approved memory is keyed by `(project_id, key)` and records content, version, author, source, archive state and timestamps. Every accepted change creates a history row. `expected_version` provides transactional compare-and-swap semantics.

Human writes update approved entries. Agents can only create proposals; a human reviews each proposal against its base version. Conflicts remain pending. Archived entries are excluded from search and task context. Search is literal, parameterized keyword matching. Automatic extraction, semantic embeddings and cross-project memory sharing are not implemented.

The UI presents versions, provenance and proposal review. Full revision browsing/export and retention controls are not available; history remains in SQLite.

## Quotas and subscriptions

With execution enabled and a helper configured, the local service owns one 600-second refresh loop, starting 10 minutes after startup. Selecting Usage & billing also invokes `configured quota_command + --probe + codex|claude`; overlapping page requests are coalesced. All paths share the 35-second probe timeout and 60-second per-provider throttle. Hidden windows and multiple tabs do not create extra timers. Missed ticks do not produce a catch-up burst, and shutdown stops the timer and drains owned probes. Import, cache reads, demo mode and review mode never launch probes. Automatic reads never request interactive Keychain authorization.

Snapshots retain provider, plan, remaining percentages, reset timestamps, source sample time and status. Unknown values stay null. Readings older than 15 minutes become stale. After a reset time passes, its percentage becomes unknown until refreshed. A failed refresh preserves old readings with an error/stale state. Account identifiers and raw stderr are discarded.

Renewal dates and amounts are manual subscription records, distinct from quota resets and model-call costs. The bundled helper reads the Claude Desktop snapshot or queries the Codex-owned App Server; provider accounts are unchanged. Quota visibility grants no execution permission.

## Trust and persistence

The server binds to `127.0.0.1`, checks exact Host/Origin values and provides no CORS or remote binding. A human access token is written to a mode-0600 file in the private data directory and kept only in browser memory. Per-run MCP capabilities are hashed in SQLite, expire after one hour and are revoked when execution ends. They cannot access human approval routes.

A file lock prevents concurrent service instances from corrupting restart recovery. It does not isolate hostile processes running as the same OS user. Native CLIs may have that user's filesystem/network access; stronger isolation requires a separate user, container or VM.

AgentDock has no external backend or analytics. Agent execution and quota reads can contact configured providers. Local databases, tokens, environment files and `config.local*.json` are ignored by Git. Keep configuration under other names outside the repository or explicitly ignore it.

Upgrading a 0.1 store preserves historical messages as `legacy` records without dispatching them. Old sessions without native bindings start new native sessions when explicitly run. The former ACP command configuration must be replaced with native CLI commands. See [validation](REVIEW.md) and the [API contract](API.md).

## macOS installation and connection

`native/Sources/AgentDockDesktop` provides a native window and nonpersistent WebView. The app owns a local Python child process. After that child reports readiness, the access token is injected only into the same-origin main page’s memory, never URLs, logs or browser storage. Quitting stops the service. External links open in the system browser.

An `NSStatusItem` and native `NSMenu` keep a menu-bar entry available while the main window is hidden. Closing the window does not stop tasks; explicit quit drains the owned backend. The menu reads the authenticated, cache-only `GET /api/quotas` endpoint without separate provider-refresh controls. The service owns the automatic refresh schedule. Its ephemeral HTTP client rejects redirects. A same-origin main-frame bridge shares the interface language with the native menus; only that preference is persisted.

`quota_command` points to bundled `AgentDockUsage`; legacy `agentmeter_command` remains compatible. Codex queries its native App Server, which handles authentication. Claude reads only version 2 of `~/Library/Application Support/Claude/plan-usage-history.json`, bounded to 4 MiB, with no Keychain or network access. Ambiguous multi-organization snapshots are rejected. `fetchedAt` preserves the source sample time; missing reset times remain unknown.

## Independent agents, models and metering

An agent may have no project. Conversations without an explicit workspace receive a private `sessions/<session-id>/workspace` directory; explicitly selected project directories remain shared. Session ownership and workspace freeze at creation. Workspace exclusion applies equally to independent agents. Their MCP tools cannot read project memories or dispatch project tasks.

`catalog.py` discovers models and efforts through Codex `model/list` and the Claude control handshake, drops account fields and caches metadata for five minutes. Saved agent settings reach future Codex `turn/start` requests as `model/effort`, or Claude as `--model/--effort`. Omitted settings preserve native client/session behavior without modifying global configuration.

The scanner and all usage aggregates are scoped to native sessions bound to registered agents. With no bindings, the scanner skips source files. Quotas and menu entries follow the distinct providers of configured agents, and unconfigured providers are never probed. Existing unlinked records and CLI files are preserved but excluded.

`metrics.py` indexes local token logs and accepts live usage events from `providers.py`. Codex stores cumulative native-thread counters; Claude merges repeated blocks by session and message ID. Live events, log scans and archived copies share deduplication keys. Cache counters are not added to input twice. The index stores counters, times and identifiers, not log text. Codex reads bounded cumulative tails; Claude scans incrementally by file offset. Missing log history cannot be reconstructed.

Daily activity groups usage by the server’s local calendar date. Codex maintains cumulative high-water marks per session/day, then takes positive differences against the previous checkpoint, including baselines before the visible year. Claude aggregates deduplicated message counters. A separate persisted file cursor backfills Codex history in 16 MiB chunks, with a 64 MiB budget per pass, without blocking fast totals/TPS updates. Only dates, counters, timestamps and identifiers enter the activity index.

The three-minute chart spreads measured output increments over their reported interval in three-second buckets; current TPS averages the last fifteen seconds. Batched reports and missing measurements cannot establish token-by-token generation speed. Token statistics and quota snapshots are independent datasets, not billing estimates.

---

**English** · [简体中文](ARCHITECTURE.zh-CN.md) · [Back to README](../README.md)
