# 本地 API

[English](API.md) · **简体中文** · [项目说明](../README.zh-CN.md) · [架构设计](ARCHITECTURE.zh-CN.md)

版本：**0.2 预览版**。工作台记录的 ID 为 UUID 字符串；`native_session_id` 是由提供商管理的原生会话标识。时间戳采用 UTC 时区的 ISO 8601 格式。成功响应为 JSON，错误响应为 `{ "error": "message" }`。

| HTTP 状态码 | 含义 |
| --- | --- |
| `400` | 输入或 JSON 请求体无效。 |
| `401` | 管理员令牌缺失或无效。 |
| `403` | 无权访问、未启用执行，或达到协作上限。 |
| `404` | 资源或接口不存在。 |
| `405` | MCP 接口要求使用 POST。 |
| `409` | 状态、幂等键、归属或记忆版本冲突。 |
| `413` | HTTP 请求体超过大小限制。 |
| `500` | 已去除敏感信息的内部错误，不能据此认为操作成功。 |

## 身份认证与请求边界

管理员请求必须携带 `Authorization: Bearer <local admin token>`，占位符替换为本地管理员令牌。`Host` 必须与 `127.0.0.1:<configured port>` 完全一致，端口为配置值。浏览器请求如果携带 `Origin`，必须与同一 HTTP 来源一致；跨站请求会被拒绝。POST 请求体使用 `application/json`，最大为 256 KiB。不支持 CORS 或绑定远程地址。

MCP 请求使用独立的单次运行能力令牌。该凭据只能通过 `/mcp/tool` 访问正在执行的项目、Agent 和会话的工具，不能访问管理员 API。运行结束或取消时撤销令牌，令牌最长有效期为一小时。

默认禁用执行。仅审阅模式允许管理项目、Agent、会话、记忆和订阅记录；启动任务、发送可执行消息、处理运行审批和刷新提供商额度会被拒绝。读取状态不会启动进程或额度探测。

## 用户操作接口

| 方法与路径 | JSON 字段与返回结果 |
| --- | --- |
| `GET /api/state` | 返回项目、Agent、会话、`runs`、消息、记忆、提议、近期事件、缓存额度、订阅、待处理审批和运行模式。 |
| `GET /api/quotas` | 通过 `quotas` 返回经过时效判断的 Codex／Claude 缓存快照。需要管理员令牌，不启动提供方查询，不返回项目或会话数据。 |
| `POST /api/projects` | `name`、`path`（已存在且可信的目录绝对路径）。返回项目。 |
| `POST /api/agents` | `project_id`、`name`、`provider`（`codex` / `claude`），以及可选的 `role`（默认空）。 |
| `POST /api/agents/{id}` | `name`（1–100 字符）与 `role`（最多 4,000 字符）至少提供一项。`role: ""` 清空角色；省略的字段保持原值。仅允许这两个字段，返回更新后的 Agent。 |
| `POST /api/sessions` | `agent_id`、`title`。创建空闲工作台会话，此时不会启动原生命令行客户端。 |
| `POST /api/sessions/{id}/run` | `prompt`（最多 24,000 字符）。将新一轮任务加入执行队列，返回运行记录。 |
| `POST /api/sessions/{id}/cancel` | 空对象。取消该会话尚未结束的逻辑任务，包括排队、执行中或等待委派结果的任务，以及它们现有的后代任务。返回 `{ "ok": true }`。 |
| `POST /api/runs/{id}/cancel` | 空对象。取消指定运行所属的逻辑任务，包括它现有的排队或正在执行的后代任务。返回 `{ "ok": true }`。 |
| `GET /api/sessions/{id}/events?after=0` | 返回 `{ "events": [...] }`，按递增的 `seq` 排序，每次最多返回 500 条。 |
| `POST /api/messages` | `project_id`、`recipient_id`、`body`（最多 12,000 字符）；可选 `recipient_session_id`、`correlation_id`、`idempotency_key`。以 `human` 身份派发任务，返回投递记录。 |
| `POST /api/memories` | `project_id`、`key`、`content`、`expected_version`（新建键时为 0）。 |
| `POST /api/memories/{id}/archive` | `expected_version`。执行软归档，同时新增版本与历史记录。 |
| `POST /api/proposals/{id}/approve` | `expected_version`。必须同时匹配提议中的预期版本和当前记忆版本。 |
| `POST /api/proposals/{id}/reject` | 空对象。拒绝待处理的提议。 |
| `POST /api/approvals/{id}` | `option_id`，必须为 AgentDock 返回的、仍待处理的审批选项之一。 |
| `POST /api/quotas/refresh` | `provider`（`codex` / `claude`）。点击“额度与订阅”时调用，必须启用执行；与服务定时刷新共用节流。 |
| `POST /api/quotas/authorize` | `provider: "claude"`。仅管理员可调用，须启用执行并使用内置组件。允许显示钥匙串授权提示，最多等待 180 秒；普通刷新不会显示提示。 |
| `POST /api/subscriptions` | `provider`；可选 `plan`、`renewal_date`（`YYYY-MM-DD` 或 null）、`monthly_cost`（非负有限数值或 null）、`currency`（三个字母，默认为 `USD`）。 |

取消接口返回成功，表示已接收停止请求；最终状态通过 `runs` 确认。正在执行的任务会立即失去 MCP 权限，其原生进程组将被中断并终止。排队任务取消后不会启动。取消操作不会回滚命令行客户端已经产生的文件改动。

名称和角色由用户定义，与 `provider` 独立。更新接口使用工作台管理员令牌，在仅审阅模式也可调用；智能体的执行令牌不能修改角色。每轮构建提示词时读取最新角色，已提交给原生 CLI 的提示词保持不变。更新不会重建会话或清除历史。`provider` 与 `project_id` 不可通过此接口修改，以保留原生会话归属。

## 状态与任务记录

`GET /api/state` 包含最近 **300 条运行记录**和 **300 条事件**，按时间顺序返回。其他集合暂不分页。此预览版没有单独的运行历史分页接口。会话事件接口支持游标分页，可将上次返回的最后一个 `seq` 作为下一次请求的 `after`。

| 记录 | 主要字段 |
| --- | --- |
| 会话 | `id`、`project_id`、`agent_id`、`title`、`status`、`native_session_id`、`created_at`、`updated_at`。首次执行前原生标识为 null，公共 API 不允许指定或修改它。 |
| 运行 | `id`、`session_id`、`project_id`、`agent_id`、`prompt`、`status`、`origin`、`parent_run_id`、`root_run_id`、`task_run_id`、`depth`、`delivery_id`、`result`、`error`、时间戳。 |
| 投递（`messages`） | `id`、`project_id`、`sender_id`、`recipient_id`、`sender_session_id`、`recipient_session_id`、`sender_run_id`、`run_id`、`reply_run_id`、`body`、`status`、`result`、`error`、`correlation_id`、`idempotency_key`、时间戳。 |
| 审批 | `id`、`run_id`、`session_id`、`project_id`、`request`、`options`、`status`、`picked_option_id`、`created_at`。状态接口只返回待处理审批。 |

运行的 `origin` 为 `human`（用户任务）、`delegate`（委派任务）或 `reply`（结果回传后继续执行）。生命周期为 `queued`（排队）→ `running`（执行中）→ `completed`（完成）、`failed`（失败）或 `cancelled`（取消）；重启时仍未结束的任务变为 `interrupted`（中断）。会话状态优先反映正在执行或排队的任务，否则显示最近的终态。

`task_run_id` 将同一逻辑任务的初始轮次及后续结果处理轮次归为一组；`root_run_id` 标识整棵协作任务树。某轮执行完成，不一定代表它所属的逻辑任务已经完成。

`messages` 集合保存投递审计记录。提交成功会产生排队任务，**不代表接收方已经完成**。`waiting` 状态表示接收方已结束某轮执行，但仍须等待子任务结果或后续处理轮次，才能最终交付。只有任务结算后的投递记录才表示最终状态和结果。若存在 `reply_run_id`，它指向发送方的结果处理轮次；需检查该运行，判断发送方是否已处理结果。`acknowledged_at` 表示接收方开始执行的时间，不再表示人工确认收件。

事件包含 `seq`、`id`、`project_id`、可为 null 的 `session_id`、`kind`、`payload` 和 `created_at`。生命周期事件包括 `run_queued`、`run_started`、`run_finished`、`message_queued`、`reply_queued` 和 `task_settled`；文本与工具事件包括 `agent_message_chunk`、`assistant_message`、`tool_call` 和 `tool_result`。所有提供商载荷均应作为不可信展示数据处理，不能作为可执行 HTML 或授权依据。

## 派发与会话续接

启用执行后，`message_send` 和 `POST /api/messages` 会安排真实执行。指定 `recipient_session_id` 时，该会话必须属于同项目的目标 Agent；未指定时，使用目标 Agent 最近更新的会话，若没有会话则新建。Agent 不能向自己委派任务。

Agent 的发送者身份、原始会话和父任务均由运行能力令牌确定，API 客户端不能冒用该身份。以 `human` 身份派发时，不会为发送方 Agent 创建自动续接任务。

Agent 间委派必须等接收方的逻辑任务结算后，才向**确切的原发送会话**回传最终结果。例如，B 为 A 工作时委派给 C，B 会等待 C 回传并完成自身的后续处理，再向 A 返回最终答复。多个子任务统一跟踪，不会将中间的派工说明作为已完成成果返回。

完成、失败和取消的任务，只要原请求方仍有效，都可以安排结果处理轮次；失败和取消按真实状态回传。已停止的请求方不会被重新唤醒，中断的任务不会重放。每次继续处理都会恢复原生会话，并可在同一组上限内继续委派。

共用工作目录的 Agent 顺序执行。发送方委派后应结束当前轮次，不应等待或轮询尚在等待同一工作目录的接收方。互不重叠的独立工作目录可以并行执行。

`idempotency_key` 按项目与发送者划分作用域。使用相同键重试相同任务会返回原投递记录；改变接收者、正文、关联标识、发送方运行或会话，或显式指定不同目标会话，会返回冲突。它用于同一次发送运行中的重试去重，不用于合并无关任务。

## MCP 工具

`python3 -m agentdock.mcp` 通过标准输入与标准输出传输以换行分隔的 JSON-RPC 消息，实现 `initialize`、`ping`、`tools/list` 和 `tools/call`，通知消息不返回响应。支持协议版本 `2025-11-25`、`2025-06-18`、`2025-03-26` 和 `2024-11-05`。

工作台通过子进程环境提供 `AGENTDOCK_URL` 和 `AGENTDOCK_CAPABILITY`，工具参数不接受提供商凭据。桥接程序禁用 HTTP 代理与重定向，只接受 `http://127.0.0.1:<port>`，限制输入输出大小，并对工具错误去除敏感信息。

| 工具 | 参数 | 作用 |
| --- | --- | --- |
| `agent_list` | 无 | 列出当前项目中的 Agent，包含调用者；不会启动它们。 |
| `message_send` | `recipient_id`、`body`；可选 `recipient_session_id`、`correlation_id`、`idempotency_key` | 创建可执行投递，返回其标识与状态；接收方满足执行条件后运行，结果会触发发送方会话继续处理。 |
| `task_status` | `message_id` | 查看当前项目内调用者发送或接收的投递状态与结果；返回快照，不阻塞等待。 |
| `memory_search` | 可选 `query` | 按字面关键词检索，最多返回 20 条已批准、未归档的项目记忆。 |
| `memory_propose` | `key`、`content`、`expected_version` | 创建待人工审核的提议，不能直接覆盖已批准记忆。 |

0.2 协议不再提供旧的 `inbox_read` 和 `inbox_ack`。MCP 工具不能授予提供商执行权限；原生工具审批通过经过身份认证的工作台审批流程处理。

## 执行上限与升级行为

每个原生进程执行一轮前台任务后退出。Claude 子进程环境设置 `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`，AgentDock 不托管其原生后台任务。已登记 Agent 之间的委派通过 `message_send` 和持久化调度队列完成。此设置不修改用户全局环境，也不影响其他 Claude 进程。

| 边界 | 当前行为 |
| --- | --- |
| 并发 | 最多 4 个原生进程同时执行。同一 Agent，以及路径相同或互为父子目录的工作区，不能并发执行。 |
| 协作 | 根任务深度为 0，委派深度最多为 3。每个根任务最多产生 16 次运行，包含根任务、委派任务和结果续接。新委派会预留结果回传所需容量，因此可能在实际运行次数未满 16 次时即被拒绝。 |
| 超时 | 服务采用 15 分钟运行时限和 2 分钟审批时限；到期后停止任务，不授予权限。 |
| 输出 | 原生输出最多 8 MiB，单条协议消息最多 512 KiB。运行事件和最终文本另有大小限制；保存的最终文本最多 64,000 字符，自动结果回传最多包含 12,000 字符。 |
| 额度 | 启用执行并配置额度组件后，每 600 秒自动刷新；点击额度页也会触发。同一提供商的刷新间隔至少为 60 秒，探测超时为 35 秒。超过 15 分钟的快照标记为过期；超过重置时间后，剩余额度改为未知。 |

SQLite 采用增量迁移，保留已有项目、会话、历史与记忆。旧邮箱模型中没有可执行 `run_id` 的消息会变为 `legacy` 历史记录，永远不会自动派发。原生会话绑定在首次 0.2 执行时建立，不导入旧适配器会话。

重启后，原先排队或执行中的轮次，以及排队、执行或等待子结果的投递记录，均标记为 `interrupted`，待处理审批取消，能力令牌撤销。不会自动重放未完成任务。用户重新提交任务时，可以恢复 AgentDock 自己拥有的原生会话；尚未实现导入 Codex App 或其他终端的既有会话。

---

[English](API.md) · **简体中文** · [项目说明](../README.zh-CN.md) · [架构设计](ARCHITECTURE.zh-CN.md)
