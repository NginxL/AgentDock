# Local API

**English** · [简体中文](API.zh-CN.md) · [README](../README.md) · [Architecture](ARCHITECTURE.md)

Version: **0.3 preview**. Workbench IDs are UUID strings; `native_session_id` is an opaque provider-owned identifier. Timestamps use UTC ISO 8601. Success responses are JSON. Error responses are `{ "error": "message" }`.

| HTTP status | Meaning |
| --- | --- |
| `400` | Invalid input or JSON body. |
| `401` | Missing or invalid administrator token. |
| `403` | Access denied, execution disabled, or collaboration limit reached. |
| `404` | Resource or route not found. |
| `405` | The MCP endpoint requires POST. |
| `409` | State, idempotency, ownership, or memory-version conflict. |
| `413` | HTTP request body exceeds the size limit. |
| `500` | Sanitized internal failure; success must not be assumed. |

## Model and usage endpoints

`GET /api/models/{codex|claude}` requires execution to be enabled. It performs a native metadata handshake without sending a prompt. Returns `models: [{id, name, efforts}]`, cached for five minutes. Only allowlisted metadata is returned; account information is discarded.

`GET /api/metrics` reads local counters and returns `total`, `providers`, `agents`, `scan_status` and `as_of`. Groups contain input, output, cache read/write, total tokens, session counts, current/average TPS and 60 three-second chart points. Here `as_of` and `updated_at` use Unix seconds; `current_tps: null` means an active run has no valid sample. With execution enabled, changed source files are indexed every ten seconds; the UI reads metrics every three seconds without invoking models.

All metric groups include only native sessions bound to registered agents. With no agents, totals are zero and provider, agent and daily activity collections are empty. `GET /api/state` and `GET /api/quotas` expose only configured providers; missing snapshots have `status: "unknown"` and no windows in the menu response. Quota refresh rejects unconfigured providers.

`activity` contains `today` (the server’s local calendar date), `days` (`date` and `tokens` per recorded day over the last 365 days), `updated_at` (latest source timestamp, or null) and `status` (`pending`, `scanning`, `ready`, `partial` or `disabled`). Days without recorded usage have no positive count. Initial Codex activity backfill reads bounded chunks from the start of history independently of the fast totals/TPS scan; progress survives restarts. No provider request is made.

Independent sessions have a null `project_id` and fixed `workspace`. Independent agents receive empty teammate/memory searches; project dispatch and memory proposals are denied.

Task events include `reasoning_chunk`, `reasoning_message` (a final replacement for the same `item_id` and `part`), `tool_call`, `tool_output` and `tool_result`. Each carries `run_id`; tool chunks use `item_id`. Codex supplies reasoning summaries; Claude supplies published thinking blocks. `run_finished.status` is authoritative for terminal state, and `runs.result` preserves the final reply. Visible conversations poll events every second and drain full cursor pages.

## Authentication and request boundary

Administrator requests require `Authorization: Bearer <local admin token>`. `Host` must exactly match `127.0.0.1:<configured port>`. Browser `Origin`, when present, must match the same HTTP origin; cross-site requests are rejected. POST bodies use `application/json` and are limited to 256 KiB. CORS and remote binding are not supported.

MCP requests use a separate per-run capability. That credential grants access only to `/mcp/tool` for the executing project's agent and session. It cannot access administrator APIs. The capability is revoked when a run ends or is cancelled, and expires after at most one hour.

Execution is disabled by default. In review mode, project, agent, session, memory, and subscription records can be managed; starting tasks, sending executable messages, resolving runtime approvals, and refreshing provider quotas are rejected. Reading state never starts a process or quota probe.

## Human routes

### Environment routing

`environment_id` defaults to `local`. `GET /api/state` includes `environments`. Projects and agents accept an environment on creation; sessions capture their agent's environment at creation. Updating an agent's `environment_id` changes the destination of new conversations only; existing sessions keep their environment. `GET /api/models/{provider}?environment_id=<id>` queries the selected environment; SSH reads require a successful connection check. Local and SSH model catalogs are cached in the controller for five minutes per environment/provider. Concurrent SSH lookups for the same pair share one request; reconnecting invalidates that environment's cache. Failed lookups are not cached.

The interface preloads metadata when entering a conversation and shares a one-minute memory cache with agent settings. Reopening a menu reuses the list; expired entries remain visible during refresh. Workbench credentials, providers and environments have separate cache scopes. Disconnecting or reconnecting clears the interface cache. Discovery never submits an agent prompt.

Quota refresh and subscription writes accept `environment_id` and are scoped to that environment/provider pair. Returned SSH snapshots and subscriptions include the environment ID. Menu snapshots retain `environment_name` for compatibility and include `agent_names`, the custom names associated with that connection. The menu displays these names without device labels; names are not routing identifiers. Remote metrics use managed usage events, not remote history scans. `transport_status` events report `reconnecting` or `connected` without completing the run.

| Method / route | JSON fields / result |
| --- | --- |
| `POST /api/environments` | `name`, `ssh_host`; optional `python` (default `python3`). Creates an SSH record without contacting the host. |
| `POST /api/environments/{id}/connect` | Empty object. Requires execution enabled; installs the private runner and returns Python/CLI version metadata. Does not send a model prompt. |
| `POST /api/environments/{id}/remove` | Empty object. Removes an unused SSH record. Rejects environments linked to projects or agents; leaves remote files intact. |

Remote explicit workspaces must be absolute POSIX paths and exist when a task starts. A blank agent workspace uses a private directory created on first execution. A project path is inherited only within the same environment. See [SSH contract](SSH.md).

### Workbench operations

| Method / route | JSON fields / result |
| --- | --- |
| `GET /api/state` | Projects, agents, sessions, `runs`, messages, memories, proposals, recent events, cached quotas, subscriptions, pending approvals, and runtime mode. |
| `GET /api/quotas` | Cached Codex/Claude snapshots in `quotas`, with freshness applied. Requires the administrator token; never starts a provider probe or returns project/conversation data. |
| `GET /api/directories` | Query `environment_id` (default `local`) and `path` (default `~`). Administrator-only, read-only listing of up to 200 directories; returns `path`, `parent`, `directories` and `truncated`, never file contents. SSH browsing requires execution enabled and a connected runner. Resolves paths on the selected host. |
| `POST /api/projects` | `name`, `path` (existing absolute trusted directory). Returns a project. |
| `POST /api/agents` | `name`, `provider`; optional `project_id` (null for an independent agent), `role`, `workspace`, `model`, `effort`, `permission_mode` (`ask`, default; or `full_access`). Blank independent workspaces are created privately; project agents use the project path. |
| `POST /api/agents/{id}` | Update `name`, `role`, `model`, `effort`, `permission_mode`, `environment_id`. Changing location is allowed during active tasks and freezes existing session defaults. Omitted model, effort and workspace reset to the new location’s defaults. `workspace` may change before any conversation exists or together with location; `project_id` may change only before any conversation exists. Other model/permission changes require no queued or running tasks. Provider is immutable. |
| `POST /api/agents/{id}/delete` | Empty object; human authentication required. Deletes the agent and all its sessions through private-directory cleanup. Rejects queued, running or unresolved linked tasks. Shared projects, memory and other agents are kept. |
| `POST /api/sessions` | `agent_id`, `title`. Creates an idle workbench session; no native CLI starts yet. |
| `POST /api/sessions/{id}/run` | `prompt` (up to 24,000 characters). Enqueues a turn and returns its run record. |
| `POST /api/sessions/{id}/cancel` | Empty object. Cancels this session's unfinished logical tasks, including queued/active runs, tasks waiting for delegated results, and their existing descendants. Returns `{ "ok": true }`. |
| `POST /api/sessions/{id}/settings` | Required `model` and `effort` (each nullable), or `{ "inherit": true }` to restore agent defaults. Human authentication required. Affects only future messages in this conversation; submitted tasks keep their settings. |
| `POST /api/sessions/{id}/delete` | Empty object; requires human authentication. Rejects active or linked unfinished tasks. Removes private directories, runs and events; remote cleanup must succeed before local records are removed. Shared project directories and native logins are kept. |
| `POST /api/runs/{id}/cancel` | Empty object. Cancels the logical task containing this run, including its existing queued/active descendants. Returns `{ "ok": true }`. |
| `GET /api/sessions/{id}/events?after=0` | `{ "events": [...] }`, ordered by increasing `seq`, at most 500 per request. |
| `POST /api/messages` | `project_id`, `recipient_id`, `body` (up to 12,000 characters); optional `recipient_session_id`, `correlation_id`, `idempotency_key`. Dispatches as `human` and returns the delivery record. |
| `POST /api/memories` | `project_id`, `key`, `content`, `expected_version` (0 for a new key). |
| `POST /api/memories/{id}/archive` | `expected_version`. Soft archive with a new version and history entry. |
| `POST /api/proposals/{id}/approve` | `expected_version`. Must match both the proposal's expected version and the current memory version. |
| `POST /api/proposals/{id}/reject` | Empty object. Rejects a pending proposal. |
| `POST /api/approvals/{id}` | `option_id`, one of the still-pending options returned by AgentDock. |
| `POST /api/quotas/refresh` | `provider` (`codex` / `claude`). Invoked when selecting Usage & billing; requires execution enabled. Shares the provider throttle with the service-owned timer. |
| `POST /api/subscriptions` | `provider`; optional `plan`, `renewal_date` (`YYYY-MM-DD` or null), `monthly_cost` (nonnegative finite number or null), `currency` (three letters, defaults to `USD`). |

Cancellation acknowledgment means the stop request was accepted. Poll `runs` for the final state. Active runs lose MCP authority immediately; their native process groups are interrupted and terminated. A queued run never launches after cancellation. Cancelling work does not roll back filesystem changes already made by a CLI.

Names and roles are user-defined and independent of `provider`. Updates require the workbench administrator token and are allowed in review mode; a run capability cannot change roles. Each turn reads the latest role when building its prompt; prompts already submitted to a native CLI are unchanged. Updating does not recreate sessions or clear history. Provider is immutable. Existing conversations retain their project, workspace, environment and native identity. On a location change, each existing conversation retains its model, effort and permission defaults in `agent_defaults`; explicit conversation model overrides take precedence. `{ "inherit": true }` restores those frozen defaults, or current agent defaults for conversations that have not been detached by a location change.

## State and task records

`GET /api/state` includes the most recent **300 runs** and **300 events**, in chronological order. Other collections are not paginated. Run history has no separate pagination endpoint in this preview. The session events endpoint supports cursor pagination; use the last returned `seq` as the next `after` value.

| Record | Relevant fields |
| --- | --- |
| Agent | `id`, `project_id`, `environment_id`, `name`, `provider`, `role`, `workspace`, `workspace_is_default` (derived in state responses), `model`, `effort`, `permission_mode`. Permission changes require the human access token; MCP capabilities cannot edit agents. |
| Session | `id`, `project_id`, `agent_id`, `title`, `status`, `native_session_id`, `environment_id`, `workspace`, `agent_defaults`, `model`, `effort`, `model_override`, `created_at`, `updated_at`. Native identity is null before first execution and cannot be supplied or changed through the public API. |
| Run | `id`, `session_id`, `project_id`, `agent_id`, `prompt`, `status`, `origin`, `parent_run_id`, `root_run_id`, `task_run_id`, `depth`, `delivery_id`, `model`, `effort`, `permission_mode`, `result`, `error`, timestamps. Model, effort and permissions are captured at submission. |
| Delivery (`messages`) | `id`, `project_id`, `sender_id`, `recipient_id`, `sender_session_id`, `recipient_session_id`, `sender_run_id`, `run_id`, `reply_run_id`, `body`, `status`, `result`, `error`, `correlation_id`, `idempotency_key`, timestamps. |
| Approval | `id`, `run_id`, `session_id`, `project_id`, `request`, `options`, `status`, `picked_option_id`, `created_at`. State returns pending approvals only. |

A run's `origin` is `human`, `delegate`, or `reply`. Its lifecycle is `queued` → `running` → `completed`, `failed`, or `cancelled`; an unfinished run found after restart becomes `interrupted`. Session status reflects active or queued work before its last terminal status.

`task_run_id` groups the initial turn and subsequent result-processing turns that belong to one logical assignment. `root_run_id` identifies the whole collaboration tree. A completed turn does not necessarily mean its logical assignment has finished.

The `messages` collection is the delivery audit trail. Without `recipient_session_id`, delivery selects the latest conversation on the agent’s current location, or creates one there. An explicit conversation and result continuations use that conversation’s original location. A successful submission produces a queued run; it does **not** mean the recipient has finished. Its `waiting` status means the recipient has finished a turn but still needs child results or continuation turns before final delivery. Only a settled delivery has a final status/result. `reply_run_id`, when present, identifies the continuation scheduled for the sender; inspect that run to determine whether the sender has processed the result. `acknowledged_at` is the recipient's start time, not a manual inbox acknowledgment.

Events contain `seq`, `id`, `project_id`, nullable `session_id`, `kind`, `payload`, and `created_at`. Lifecycle events include `run_queued`, `run_started`, `run_finished`, `message_queued`, `reply_queued`, and `task_settled`. Text and tool events include `agent_message_chunk`, `assistant_message`, `tool_call`, and `tool_result`. Treat all provider payloads as untrusted display data, never executable HTML or authorization.

Native model confirmation emits a `model_info` event containing `run_id`, `native_id`, `model`, and, when available, `effort` and `model_provider`. Values come from the CLI protocol, never from parsing the assistant’s reply.

## Dispatch and continuation

`message_send` and `POST /api/messages` schedule real execution when execution is enabled. With `recipient_session_id`, the specified session must belong to the recipient in the same project. Without it, AgentDock uses that agent's most recently updated session, or creates one if none exists. Agent-to-self delegation is rejected.

An agent's sender identity, original session, and parent run come from its run capability. API clients cannot impersonate that identity. A `human` dispatch does not create an automatic continuation for a sender agent.

For agent-to-agent delegation, the recipient's logical assignment must settle before its final result returns to the **exact originating session**. If B delegates to C while working for A, B waits for C's result and completes its own continuation before its final response returns to A. Multiple child deliveries are tracked together; intermediate dispatch messages are not returned as finished work.

Completed, failed, and cancelled assignments can schedule a result turn while the requester remains active. Failures and cancellations are returned with their actual status. Stopped requesters receive no new continuation, and interrupted work is not replayed. The native provider session is resumed for each continuation; it may delegate additional work within the same limits.

Agents sharing a workspace run sequentially. After delegating, the sender should finish its current turn; it should not wait or poll for a recipient that is waiting for the same workspace. Independent, non-overlapping workspaces can run concurrently.

`idempotency_key` is scoped to project and sender. Repeating the same key and assignment returns the same delivery; changing the recipient, body, correlation, sender run/session, or explicitly selected target session returns a conflict. This deduplicates retries within the same sending run, not unrelated tasks.

## MCP tools

`python3 -m agentdock.mcp` uses newline-delimited JSON-RPC over stdio. It implements `initialize`, `ping`, `tools/list`, and `tools/call`; notifications receive no response. Supported protocol versions are `2025-11-25`, `2025-06-18`, `2025-03-26`, and `2024-11-05`.

The workbench supplies `AGENTDOCK_URL` and `AGENTDOCK_CAPABILITY` through the child process environment. Provider credentials are not accepted as tool arguments. The bridge disables HTTP proxies and redirects, requires `http://127.0.0.1:<port>`, bounds input/output, and sanitizes tool failures.

| Tool | Arguments | Effect |
| --- | --- | --- |
| `agent_list` | none | Lists agents in the current project, including the caller. Does not start them. |
| `message_send` | `recipient_id`, `body`; optional `recipient_session_id`, `correlation_id`, `idempotency_key` | Creates an executable delivery and returns its IDs/status. The recipient runs when eligible; its result schedules a continuation in the sender's session. |
| `task_status` | `message_id` | Returns the status and result of a delivery the caller sent or received in this project. A snapshot, not a blocking wait. |
| `memory_search` | optional `query` | Returns up to 20 approved, non-archived project memories using literal keyword matching. |
| `memory_propose` | `key`, `content`, `expected_version` | Creates a proposal for human review. Cannot directly overwrite approved memory. |

The former `inbox_read` and `inbox_ack` tools are not part of the 0.2 protocol. MCP tools cannot grant provider permissions; native tool approvals use the authenticated workbench approval flow.

## Execution limits and upgrade behavior

Each native process executes one foreground turn and exits afterward. Claude's child environment sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`; its native background tasks are not managed by AgentDock. Delegation between registered agents uses `message_send` and the persistent dispatcher. This setting does not change the user's global environment or other Claude processes.

| Boundary | Current behavior |
| --- | --- |
| Concurrency | At most 4 active native processes. The same agent and identical or parent/child workspace paths cannot execute concurrently. |
| Collaboration | Root depth is 0; delegation depth is at most 3. Each root task admits at most 16 runs, including the root, delegated tasks, and result continuations. New delegations reserve capacity for their replies and may therefore be rejected before 16 runs exist. |
| Timeouts | The service uses a 15-minute run deadline and a 2-minute approval deadline. Expiry stops the run without granting permission. |
| Output | Native output is capped at 8 MiB, with a 512 KiB protocol-line limit. Runtime events and final text have additional bounds; stored final text is capped at 64,000 characters, and automatic result handoffs include at most 12,000 characters. |
| Quotas | The service refreshes every 600 seconds when execution and a helper are enabled. Selecting Usage & billing also triggers refresh. A provider refresh is throttled to once per 60 seconds, with a 35-second probe timeout. Snapshots older than 15 minutes become stale; remaining quota becomes unknown once its reset time passes. |

SQLite migration is additive: projects, sessions, history, and memory remain available. Messages from the earlier mailbox model without an executable `run_id` become `legacy` audit records and are never dispatched. Native bindings are created on the first 0.2 execution; older adapter sessions are not imported.

After restart, previously queued/running turns and queued/running/waiting deliveries become `interrupted`, approvals are cancelled, and capabilities are revoked. No unfinished task is replayed automatically. A new explicit submission may resume an existing native session owned by AgentDock; importing Codex App or unrelated terminal sessions is not implemented.

---

**English** · [简体中文](API.zh-CN.md) · [README](../README.md) · [Architecture](ARCHITECTURE.md)
