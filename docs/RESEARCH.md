# Multi-agent workspace research

[简体中文](RESEARCH.zh-CN.md) · Researched: 2026-09-26

Scope: one interface for Codex, Claude and other agents, with inter-agent communication, subscription quotas and shared project memory.

Evidence comes from official repositories, documentation and provider terms. **Documented means supported by a primary source, not runtime-tested. Unverified does not mean unsupported.** None of the surveyed products was installed or launched. Recheck features and licenses when adopting a particular version.

## Findings

Agor is the closest product match. AionUi provides a useful communication design; AO provides useful task and workspace separation. An independently implemented, bounded workspace with a read-only AgentMeter bridge fits this project. The reviewed documentation does not establish that one candidate fully covers all three requirements: cross-provider collaboration, remaining subscription quota and controlled shared memory.

| Project / primary source | Documented management and communication | Memory and quota evidence | Locality / main repository license |
| --- | --- | --- | --- |
| [AionUi](https://github.com/iOfficeAI/AionUi) | Codex / Claude and other CLIs; ACP adapters; Team MCP, asynchronous mailboxes and task board. | Shared workspace/context documented; separate long-term shared memory and account quota unverified. | Local SQLite; Apache-2.0. |
| [Agor](https://github.com/preset-io/agor) | Multiple runtimes; built-in MCP for sessions, tasks and collaboration. | Shared Knowledge and per-prompt token/cost accounting documented; subscription quota unverified. | Self-hosted LibSQL / Postgres; **BUSL-1.1, source-available rather than OSI open source today**. |
| [Agent Orchestrator / AO](https://github.com/Untrivial-ai/agent-orchestrator) | Project orchestrator, workers, isolated worktrees and PR / CI tracking. | Persistent project planning documented; general shared memory retrieval and account quota unverified. | Local daemon; telemetry can be disabled; Apache-2.0. |
| [Happy](https://github.com/slopus/happy) | Claude / Codex desktop, web and mobile access; [control CLI](https://github.com/slopus/happy/blob/main/packages/happy-agent/README.md) can create, send, wait and stop. | Session synchronization documented; autonomous teams, shared semantic memory and quota panel unverified. | Local agents and encrypted relay synchronization; MIT. |
| [OpenHands Agent Canvas](https://github.com/OpenHands/OpenHands) | Current main repository supports OpenHands, Claude, Codex, Gemini / ACP and multiple backends. | General inter-agent mailbox, cross-provider memory and subscription quota unverified. | Self-hosting and remote/container execution; main repository MIT. |
| [opcode](https://github.com/winfunc/opcode) | Claude GUI and background agents; unified Codex support unverified. | CLAUDE.md editing, checkpoints and token/API costs documented; shared memory and subscription quota unverified. | Local data; README states no telemetry; AGPL-3.0. |

Licenses above come from the linked official repositories; dependencies, trademarks and model services have separate terms. Agor restricts commercially offering its orchestration functionality to third parties. It is a design reference, not a code source for this project. Local storage does not prevent cloud model requests from leaving the machine.

`ComposioHQ/agent-orchestrator` now redirects to `Untrivial-ai/agent-orchestrator`. OpenHands' current main README describes Agent Canvas. AO's [current documentation](https://docs.aoagents.dev/) distinguishes native terminal support from the smaller structured-chat capability set.

## Design choices supported by the research

| Decision | Evidence | Direction for AgentDock |
| --- | --- | --- |
| Separate client integration from collaboration. | AionUi separates ACP adapters from [Team MCP and mailboxes](https://github.com/iOfficeAI/AionUi#team-mode--coordinated-multi-agent-collaboration). | ACP manages agent sessions; project-scoped MCP tools expose an application mailbox. |
| Treat memory as managed information. | Agor [Knowledge](https://agor.live/guide/knowledge) has namespaces, versions, permissions, search and MCP access. | Project memory with provenance and versions; agents propose changes and humans review them. |
| Reuse one permission and state model. | Agor's [MCP surface](https://agor.live/guide/internal-mcp) uses the same daemon services as its UI. | UI and agent tools share validation; each run gets only its own project-scoped capabilities. |
| Separate message sharing from file sharing. | [AO](https://docs.aoagents.dev/) gives workers isolated workspaces. | Workspace write isolation requires its own implementation and acceptance checks. A mailbox does not supply it. |

ACP does not itself create a peer-to-peer agent network. An MCP mailbox is an application design, not a claim of A2A support. Queue acceptance is distinct from delivery and execution. The preview design uses explicit task starts; messages do not silently wake agents or create spending loops.

SQLite persistence, project scope and version-conflict checks are the initial memory direction. Retrieved memory is contextual data, not higher-priority instructions. Semantic retrieval, automatic consolidation, cross-project sharing and autonomous scheduling are separate capabilities; storing transcripts alone does not establish them.

## AgentMeter boundary

Account quota/reset windows, task token/cost usage and billing renewal dates are separate data. None should be inferred from another.

The design reuses [AgentMeter](https://github.com/NginxL/AgentMeter)'s read-only `--probe` interface. AgentDock receives normalized results without copying provider credentials. Displays must distinguish valid, stale, authentication-error and unknown states, preserve collection times and never turn missing values into zero remaining quota. Read-only probes can still contact providers and depend on changing interfaces. No automatic probes run before execution is enabled.

## Claude authentication requires a separate decision

[`claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp) uses the Claude Agent SDK. Anthropic's [official SDK documentation](https://code.claude.com/docs/en/agent-sdk/overview#get-started) restricts third-party products offering claude.ai login or its rate limits without prior approval, and directs developers to API-key authentication. The SDK-adapter integration path therefore uses API keys or supported cloud-provider credentials. It does **not** promise that a Pro / Max subscription can power this third-party application.

The [Claude Code legal documentation](https://code.claude.com/docs/en/legal-and-compliance) separately describes conditions for hosting the unmodified CLI and end-user sign-in, while prohibiting collection or intermediation of users' credentials. Those conditions do not automatically establish an exception for an SDK / ACP integration. Another workspace's technical integration guide cannot grant provider authorization.

The exact distribution, adapter version and authentication combination remains subject to verification. Reading subscription quota through AgentMeter is not authorization to execute Claude agents.

## Review boundaries

| Area | Evidence or pending validation |
| --- | --- |
| Market features and repository licenses | Primary documentation reviewed; no third-party runtime acceptance testing. |
| ACP / MCP, mailbox and reviewed memory | Design choices; implementation correctness must be established separately by project tests. |
| Real Codex / Claude execution, permissions and native session restoration | Not launched before user review; live compatibility remains unverified. |
| Live quota refresh and authentication | No probes before review; credentials, terms and failure states require separate validation. |
| Autonomous loops, semantic memory, remote multi-user access and workspace write isolation | Not inferred from the existence of an interface; evaluate each against its implementation and tests. |


## Protocol and memory components

| Component / primary source | Boundary | Preview decision |
| --- | --- | --- |
| [ACP: Agent Client Protocol](https://agentclientprotocol.com/protocol/v1/overview) | Client-to-agent sessions, events and permissions over stable stdio JSON-RPC; extensions require capability negotiation. | UI-to-agent interface with separately configured adapters. |
| [A2A](https://a2a-protocol.org/latest/specification/) | Agent discovery, tasks and artifacts across services; not local CLI or shared-database management. | Candidate for remote federation; not implemented. |
| [MCP](https://modelcontextprotocol.io/docs/learn/architecture) | Tools and context; not a scheduler or durable message queue. | Scoped messaging and memory tools backed by workbench services. |
| [Letta](https://docs.letta.com/tutorials/attaching-detaching-blocks/) | Memory blocks can be shared by Letta agents, rather than automatically connecting existing CLIs. | Reference for shared memory blocks; no additional runtime. |
| [Mem0](https://docs.mem0.ai/open-source/overview) | Configurable memory extraction/search with model, embedding and storage dependencies. | Semantic memory candidate; preview uses local keyword search. |
| [LangGraph](https://docs.langchain.com/oss/python/concepts/memory) | Thread checkpoints and namespaced cross-session stores. | Reference for scope isolation; no graph runtime dependency. |

[BeeAI Agent Communication Protocol](https://github.com/i-am-bee/acp) is a different use of “ACP”; its repository describes its merge into A2A. AgentDock uses **Agent Client Protocol**.
