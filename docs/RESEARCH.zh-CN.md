# 多 Agent 工作台调研

> **0.1 设计历史记录。** 此处保留产品资料及最初的 ACP／邮箱方案评估；当前原生会话与主动调度实现见[架构设计](ARCHITECTURE.zh-CN.md)及[验证说明](REVIEW.zh-CN.md)。

[English](RESEARCH.md) · **简体中文** · [返回项目首页](../README.zh-CN.md)

调研日期：2026-09-26

目标：在同一界面管理 Codex、Claude 等 Agent，支持相互通信、订阅额度查询和项目共享记忆，为 AgentDock 的设计与代码评审提供依据。

本报告核对官方仓库 README、官方文档和发布方条款。**“已证实”指有一手文档支持，不代表已运行验收；“未核实”不等于产品不支持。**没有安装、启动或实测下列产品；功能、名称和许可证应在采用具体版本时重新核对。

## 结论

Agor 的产品覆盖最接近目标；AionUi 的团队通信设计和 AO 的任务隔离模式值得参考。建议独立实现小范围工作台，复用 AgentMeter 的只读额度出口，而不是把某个现成应用改名发布。当前资料不足以确认有一款候选同时完整满足跨厂商协作、订阅剩余额度和受控共享记忆。

## 候选证据表

| 项目 / 官方来源 | 已证实的统一管理与通信 | 记忆与额度：已证实 / 未核实 | 本地性与主仓许可证 |
| --- | --- | --- | --- |
| [AionUi](https://github.com/iOfficeAI/AionUi) | 支持 Codex、Claude 等 CLI；ACP 接入；Team MCP、异步邮箱和共享任务板协调 Leader / Teammate。 | 已证实共享工作目录和任务上下文；独立长期共享记忆、账号剩余额度未核实。 | SQLite 本地存储；Apache-2.0。 |
| [Agor](https://github.com/preset-io/agor) | 多种 Agent 运行时；内置 MCP 支持子会话、任务和团队协作。 | 已证实共享 Knowledge 和逐提示 token / 成本统计；订阅剩余额度未核实。 | 自托管 LibSQL / Postgres；**BUSL-1.1，当前属源码可用，不是 OSI 开源**。 |
| [Agent Orchestrator / AO](https://github.com/Untrivial-ai/agent-orchestrator) | 多 harness；项目 Orchestrator 派发和跟进 Worker；独立 worktree、PR / CI 看板。 | 已证实持久化项目规划会话；通用共享记忆检索、账号剩余额度未核实。 | 本地 daemon；遥测可关闭；Apache-2.0。 |
| [Happy](https://github.com/slopus/happy) | Claude / Codex 的桌面、Web、移动端入口；[控制 CLI](https://github.com/slopus/happy/blob/main/packages/happy-agent/README.md)可创建会话、发送、等待和停止。 | 已证实会话同步；自主跨 Agent 团队、共享语义记忆和额度面板未核实。 | 本机运行、端到端加密同步中继；MIT。 |
| [OpenHands Agent Canvas](https://github.com/OpenHands/OpenHands) | 当前主仓支持 OpenHands、Claude、Codex、Gemini / ACP，以及本地、远程和云 backend。 | 任意 Agent 间邮箱、跨厂商共享记忆和订阅额度面板未核实。 | 可自托管，支持容器与远程执行；主仓 MIT。 |
| [opcode](https://github.com/winfunc/opcode) | Claude Code GUI、自定义 Claude Agent、后台执行；Codex 统一支持未核实。 | 已证实 CLAUDE.md 编辑、检查点、token / API 成本分析；通用共享记忆和订阅余额未核实。 | 本地数据，README 声称无遥测；AGPL-3.0。 |

许可证信息来自表中官方主仓；不代表依赖、模型服务和商标采用相同条款。Agor 的附加授权限制将其编排能力作为产品或服务向第三方商业提供，因此仅参考公开设计，不复制其代码。“本地存储”也不意味着调用云模型时内容不会发送给模型提供商。

名称需区分：`ComposioHQ/agent-orchestrator` 已重定向到 `Untrivial-ai/agent-orchestrator`；OpenHands 主仓当前 README 使用 Agent Canvas 名称。AO 的 [当前文档](https://docs.aoagents.dev/)还区分原生终端接入和结构化 Chat；两者能力不能混为一谈。

## 协议与记忆组件比较

| 方案 / 一手来源 | 适用边界 | 首版选择 |
| --- | --- | --- |
| [ACP：Agent Client Protocol](https://agentclientprotocol.com/protocol/v1/overview) | 客户端与编码 Agent 的会话、事件与审批；稳定传输为 stdio JSON-RPC，不能默认所有 Agent 都支持扩展。 | 用于 UI → Agent；配置 Codex / Claude 的独立适配器。 |
| [A2A](https://a2a-protocol.org/latest/specification/) | AgentCard、任务与产物、跨服务委派；不负责本地 CLI 管理或共享数据库。 | 远程联邦边界的候选，首版未实现。 |
| [MCP](https://modelcontextprotocol.io/docs/learn/architecture) | 向 Agent 提供工具和上下文，不自动提供调度与持久邮箱。 | 用于受限通信与记忆工具；消息语义由工作台实现。 |
| [Letta](https://docs.letta.com/tutorials/attaching-detaching-blocks/) | 多个 Letta Agent 可以挂载共享 memory block；不是现有 CLI 的通用记忆插件。 | 参考共享块，首版不用额外运行时。 |
| [Mem0](https://docs.mem0.ai/open-source/overview) | 可配置模型、嵌入和存储的记忆提取/检索层，带来额外服务与数据流。 | 语义记忆候选，首版使用本地关键词查询。 |
| [LangGraph](https://docs.langchain.com/oss/python/concepts/memory) | Checkpointer 保存线程状态，Store 按 namespace 提供跨会话记忆。 | 参考范围隔离；不为包装现有 Agent 引入完整图运行时。 |

另一个同名缩写是 [BeeAI Agent Communication Protocol](https://github.com/i-am-bee/acp)，其仓库已说明并入 A2A；它与 Agent Client Protocol 不是同一个协议。首版所说的 ACP 始终指后者。

## 通信与记忆的设计选择

| 问题 | 证据与判断 | AgentDock 的设计选择 |
| --- | --- | --- |
| 一个协议能否同时解决 UI 接入和 Agent 互通？ | AionUi 分别使用 ACP 接入和 Team MCP 协作。[官方 Team Mode](https://github.com/iOfficeAI/AionUi#team-mode--coordinated-multi-agent-collaboration) | ACP 管理 Agent 会话；项目邮箱与 MCP 工具负责通信，分别建模。 |
| 是否应把全部聊天记录自动共享？ | Agor Knowledge 提供文档、命名空间、版本、权限、搜索和 MCP 读写。[Knowledge 文档](https://agor.live/guide/knowledge) | 首版使用项目级记忆条目：保留来源和版本；Agent 提议、人工审核；上下文只按需引用。 |
| UI 和 Agent 是否各实现一套操作？ | Agor MCP 与界面使用同一 daemon 服务和事件。[MCP 文档](https://agor.live/guide/internal-mcp) | 两种入口共用状态与权限校验；Agent 仅获得当前项目、当前运行所需的工具权限。 |
| 多 Agent 是否必须共用同一目录？ | AO 将任务绑定独立工作区，防止并行改动相互覆盖。[AO 文档](https://docs.aoagents.dev/) | 通信共享与文件共享分离；工作区隔离是正式并行写代码前的验收项，不能由邮箱功能推断已经解决。 |

ACP 是 UI / 客户端与 Agent 的接口；把邮箱作为 MCP 工具提供给 Agent，是应用层协作设计。不能把这种实现称为已经支持 A2A，也不能把“消息写入队列”展示为“对方已执行”。预览版选择人工显式启动任务，邮箱消息不自动唤醒 Agent，避免未经观察的循环调用和额度消耗。

共享记忆采用 SQLite 持久化、项目范围和版本冲突检测作为首版方向。检索结果应标注为上下文数据，不能提升为系统指令。长期语义检索、自动归纳、跨项目共享与自动调度属于独立能力，不能仅凭保存了对话记录就宣称已具备。

## AgentMeter 集成边界

需要分别展示三类数据：账号配额及重置时间、当前任务 token / 成本、订阅续费信息。三者不能互相推导；额度重置不是续费，API 成本也不是订阅余额。

首版设计复用 [AgentMeter](https://github.com/NginxL/AgentMeter/blob/main/README.zh-CN.md) 的只读 `--probe` 出口，AgentDock 只接收标准化结果，不复制提供商凭据。额度显示必须区分有效、过期、认证失败与未知；保留采集时间，未知值不能写成剩余 0%。探测仍可能请求提供商服务器，“只读”不代表离线或接口长期稳定。用户启用执行前，不自动启动探测。

## Claude 接入必须单独审查

[`claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp) 明确基于 Claude Agent SDK。Anthropic 的 [Agent SDK 正式文档](https://code.claude.com/docs/en/agent-sdk/overview#get-started)指出：未经事先批准，第三方开发者不能为自己的产品提供 claude.ai 登录或其速率额度，应使用文档提供的 API key 认证方式。因此，SDK 适配器的集成说明采用 API key 或其支持的云推理认证；**不能承诺“Claude Pro / Max 登录后即可用于该第三方应用”。**

Anthropic 的 [Claude Code 法律与合规文档](https://code.claude.com/docs/en/legal-and-compliance)另有未修改 CLI 二进制的托管条件，允许符合条件的最终用户自行登录，并禁止第三方收集或中介其凭据。这是需要分别核对的路径，不能自动推导出 SDK / ACP 适配器获得相同许可。上游工作台的技术接入说明也不能代替模型提供商的授权。

待核实：具体分发方式、适配器版本与所选认证方式的组合是否满足当前条款；现有 AgentMeter 读取订阅额度的方式也不构成运行 Claude Agent 的授权。

## 评审时需要确认的范围

| 范围 | 状态 / 验收依据 |
| --- | --- |
| 市场功能和主仓许可证 | 已按以上一手来源核对；没有第三方产品运行验收。 |
| ACP / MCP、任务邮箱、人工审核记忆 | 作为预览版设计选择；代码正确性应由项目测试结果单独证明。 |
| 真正运行 Codex / Claude、系统权限提示、原生会话恢复 | 用户评审前不启动；真实适配兼容性待验收。 |
| 真实额度刷新、凭据和订阅使用条件 | 用户评审前不探测；认证、条款和错误状态需分别验收。 |
| 自动团队循环、长期语义记忆、远程多用户、工作区写隔离 | 不从首版接口存在推断为已完成；按具体实现和独立测试判断。 |

---

[English](RESEARCH.md) · **简体中文** · [返回项目首页](../README.zh-CN.md)
