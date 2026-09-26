# Validation and compatibility

**English** · [简体中文](REVIEW.zh-CN.md) · [Back to README](../README.md)

## Implementation status

AgentDock combines a local React interface, a Python standard-library service and SQLite storage. ACP manages Codex and Claude adapter sessions; MCP exposes project mailboxes and memory tools. AgentMeter remains a separate application and supplies read-only quota data through `--probe`.

| Area | Implemented | Live acceptance or capability boundary |
| --- | --- | --- |
| Interface | Chinese/English switching, projects, roles, sessions, task events, run/cancel controls and permission approvals. | The application has not been launched for browser acceptance. The current illustration is explicitly marked as a design mockup. |
| Agent integration | ACP v1 over stdio, initialization, sessions, prompts, updates, permissions and cancellation; commands configured on the server. | Actual `codex-acp` and `claude-agent-acp` versions and account compatibility require verification. |
| Communication | Project-scoped mailboxes with bound sender identities, deduplication and acknowledgments; six MCP tools. | Real model tool use requires verification. Automatic wake-up and autonomous team loops are not implemented. |
| Memory | Project isolation, keyword search, version conflicts, Agent proposals, human approval, soft archive and database history. | Vector search, automatic extraction, a complete history browser and cross-project sharing are not implemented. |
| Quotas | AgentMeter probes for fixed providers, timeouts, throttling, unknown/stale/error states and manual billing records. | Real login, Keychain prompts and quota refresh require verification. Continued availability is not guaranteed for every account or provider endpoint. |
| Lifecycle | Process-group cancellation, approval expiry, exclusion of overlapping working directories, a single-instance database lock and no task replay after restart. | OS-level sandboxing, automatic worktree creation and remote multi-user access are not implemented. |

The Claude ACP adapter uses the Agent SDK and requires an API key for execution. Displaying existing Pro/Max quota does not authorize SDK inference. Authentication compatibility must be reviewed before launch when choosing ACP, an unmodified CLI or another officially supported execution path.

## Isolated verification

Backend tests use temporary SQLite stores, direct HTTP dispatcher calls and fake ACP/AgentMeter Python subprocesses. Frontend tests use DOM simulation and mocked HTTP. The build produces static assets. None of these checks starts the AgentDock HTTP service, a real coding agent or a provider quota request.

Local verification passed **45 backend tests and 16 interface tests**, Python bytecode compilation, TypeScript checks and the Vite production build on macOS with Python 3.9.6 and Node.js 20.20.2. The interface regression suite includes delayed state refresh and out-of-order polling, verifying that a task submitted after session creation targets the new session.

Coverage includes rejection of cross-project and cross-identity access, tool revocation after cancellation, compare-and-swap write conflicts, memory approval provenance, rejection of expired approvals, malformed protocol messages, output limits, child-process group cleanup, rejection of multiple instances using one database, parent/child directory conflicts, stale or unknown quota values, interface requests and language switching.

Reproduce these checks without launching the application:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q agentdock tests
cd web
npm ci --ignore-scripts
npm test
npm run build
```

CI performs these isolated checks on Python 3.9/3.12 and Node 20. Passing them does not establish live-provider compatibility. Real agent execution and real quota refresh have not passed acceptance testing.

## Code review checklist

1. [Architecture](ARCHITECTURE.md): ACP, MCP, quota and shared-memory boundaries; explicit execution and human approval requirements.
2. [Storage](../agentdock/store.py): project isolation, message semantics, memory versions and provenance, run permissions and locks.
3. [Runtime](../agentdock/runtime.py) and [MCP bridge](../agentdock/mcp.py): ACP fields, approval expiry, tool authority and cancellation.
4. [Quota bridge](../agentdock/quota.py) and [local server](../agentdock/server.py): quota accuracy, local authentication, shutdown order and execution disabled by default.
5. [Interface](../web/src/) and [tests](../tests/): consistency between visible state and the API, error handling and boundary coverage.

## Live acceptance requirements

Begin these steps only after explicitly deciding to run the preview:

- Pin adapter versions and verify official authentication in disposable, trusted worktrees.
- Confirm that one Codex task and one Claude task stream results, request permissions correctly, cancel fully and recover cleanly after restart.
- Verify Codex-to-Claude and Claude-to-Codex mailbox exchange without uncontrolled automatic calls. Confirm that memory proposals require review and version conflicts are visible.
- Refresh real AgentMeter quotas and compare remaining amounts and reset times with the official usage page, including authentication failures and stale caches.
- Inspect the Chinese and English interface and capture demonstration screenshots without private information.

The preview does not install services, start at login, register global MCP configuration, alter AgentMeter or modify existing provider logins.

---

**English** · [简体中文](REVIEW.zh-CN.md) · [Back to README](../README.md)
