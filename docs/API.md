# Local API

**English** · [简体中文](API.zh-CN.md) · [Back to README](../README.md)

Version: 0.1 preview. All timestamps are UTC ISO 8601; IDs are UUID strings. Success responses are JSON. Errors are `{ "error": "message" }`, with HTTP 400 (invalid input), 401 (missing/invalid admin token), 403 (authorization/review mode), 404 (missing), 409 (state/version conflict), or 500 (sanitized internal failure).

## Authentication

Admin requests require `Authorization: Bearer <local admin token>`. `Host` must exactly match `127.0.0.1:<configured port>`; browser `Origin`, when present, must match that HTTP origin. POST bodies use `application/json` with a 256 KiB maximum. No CORS or remote binding is supported.

MCP requests use a separate per-run capability. It can access only `/mcp/tool` for the current project and agent, never admin APIs. Expired, cancelled and completed runs have no active tool authority.

## Human routes

| Method / route | JSON fields / result |
| --- | --- |
| `GET /api/state` | Projects, agents, sessions, messages, memories, proposals, recent events, cached quotas, subscriptions, pending approvals, runtime mode. No probe starts. |
| `POST /api/projects` | `name`, `path` (existing absolute trusted directory). Returns project. |
| `POST /api/agents` | `project_id`, `name`, `provider` (`codex` / `claude`), optional `role`. |
| `POST /api/sessions` | `agent_id`, `title`. Creates an idle session only. |
| `POST /api/sessions/{id}/run` | `prompt`. Requires execution enabled; returns run record. |
| `POST /api/sessions/{id}/cancel` | Empty object. Revokes tools and stops the active process group. |
| `GET /api/sessions/{id}/events?after=0` | `{events: [...]}` ordered by monotonically increasing `seq`, at most 500 per request. |
| `POST /api/messages` | `project_id`, `recipient_id`, `body`, optional `correlation_id`, `idempotency_key`. Sender must be `human`. |
| `POST /api/memories` | `project_id`, `key`, `content`, `expected_version` (0 for new). |
| `POST /api/memories/{id}/archive` | `expected_version`. Soft archive with version/history update. |
| `POST /api/proposals/{id}/approve` | `expected_version`. Must match both the proposal and current memory. |
| `POST /api/proposals/{id}/reject` | Empty object. Resolves a pending proposal. |
| `POST /api/approvals/{id}` | `option_id`, one of the still-pending provider options. |
| `POST /api/quotas/refresh` | `provider`. Explicit opt-in probe; requires execution enabled. |
| `POST /api/subscriptions` | `provider`, optional `plan`, `renewal_date` (`YYYY-MM-DD` or null), `monthly_cost` (nonnegative finite number or null), `currency` (three letters). |

Events contain `seq`, `id`, `project_id`, nullable `session_id`, `kind`, `payload`, `created_at`. Agent update payloads are text/data to render safely, never executable HTML. `GET /api/state` returns only the most recent 300 events; use the session cursor route for full event pagination.

## MCP tools

`python3 -m agentdock.mcp` speaks newline-delimited JSON-RPC over stdio. It implements `initialize`, `ping`, `tools/list`, `tools/call` and ignores notifications. It requires `AGENTDOCK_URL` and `AGENTDOCK_CAPABILITY` in its process environment. The workbench supplies those values only when creating a run; a user never pastes provider credentials into a tool call.

| Tool | Arguments | Effect |
| --- | --- | --- |
| `agent_list` | none | List agents in this project. |
| `message_send` | `recipient_id`, `body`; optional `correlation_id`, `idempotency_key` | Queue addressed message, bound sender identity. Does not start a run. |
| `inbox_read` | none | Up to 50 pending messages for this agent. |
| `inbox_ack` | `message_id` | Acknowledge own message only. |
| `memory_search` | optional `query` | Up to 20 approved, non-archived project entries, literal keyword search. |
| `memory_propose` | `key`, `content`, `expected_version` | Create pending proposal, not approved memory. |

Protocol/tool failures return sanitized errors. The bridge disables HTTP proxies and redirects, accepts only an explicit numeric loopback address, and applies request/response limits. MCP is a tool boundary; it is not A2A or a replacement for OS isolation.

---

**English** · [简体中文](API.zh-CN.md) · [Back to README](../README.md)
