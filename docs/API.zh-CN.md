# 本地 API

[English](API.md) · **简体中文** · [返回说明文档](../README.zh-CN.md)

版本：0.1 预览版。所有时间戳均采用 UTC 时区的 ISO 8601 格式；ID 为 UUID 字符串。成功响应为 JSON。错误响应为 `{ "error": "message" }`，HTTP 状态码包括：400（输入无效）、401（管理员令牌缺失或无效）、403（无权访问或处于仅审阅模式）、404（资源不存在）、409（状态或版本冲突）和 500（已去除敏感信息的内部错误）。

## 身份认证

管理员请求必须携带 `Authorization: Bearer <local admin token>`，其中占位符替换为本地管理员令牌。`Host` 必须与 `127.0.0.1:<configured port>` 完全一致，其中端口为配置值；浏览器请求如果携带 `Origin`，也必须与该 HTTP 来源一致。POST 请求体使用 `application/json`，最大为 256 KiB。不支持 CORS 或绑定远程地址。

MCP 请求使用独立的、绑定单次运行的能力令牌。该令牌只能通过 `/mcp/tool` 访问当前项目和 Agent 的工具，不能访问管理员 API。运行过期、取消或完成后，工具访问权限失效。

## 用户操作接口

| 方法与路径 | JSON 字段与返回结果 |
| --- | --- |
| `GET /api/state` | 返回项目、Agent、会话、消息、记忆、提议、近期事件、缓存额度、订阅、待处理审批和运行模式。不会启动额度探测。 |
| `POST /api/projects` | `name`、`path`（已存在、可信的目录绝对路径）。返回项目。 |
| `POST /api/agents` | `project_id`、`name`、`provider`（`codex` / `claude`），以及可选的 `role`。 |
| `POST /api/sessions` | `agent_id`、`title`。仅创建空闲会话。 |
| `POST /api/sessions/{id}/run` | `prompt`。必须启用执行功能；返回运行记录。 |
| `POST /api/sessions/{id}/cancel` | 空对象。撤销工具权限并停止正在运行的进程组。 |
| `GET /api/sessions/{id}/events?after=0` | 返回 `{events: [...]}`，按单调递增的 `seq` 排序，每次请求最多返回 500 条。 |
| `POST /api/messages` | `project_id`、`recipient_id`、`body`，以及可选的 `correlation_id`、`idempotency_key`。发送者必须为 `human`。 |
| `POST /api/memories` | `project_id`、`key`、`content`、`expected_version`（新建时为 0）。 |
| `POST /api/memories/{id}/archive` | `expected_version`。执行软归档，同时更新版本和历史记录。 |
| `POST /api/proposals/{id}/approve` | `expected_version`。必须同时匹配提议记录中的版本和当前记忆版本。 |
| `POST /api/proposals/{id}/reject` | 空对象。拒绝待处理的提议。 |
| `POST /api/approvals/{id}` | `option_id`，必须是提供商给出的、仍待审批的选项之一。 |
| `POST /api/quotas/refresh` | `provider`。由用户显式触发额度探测；必须启用执行功能。 |
| `POST /api/subscriptions` | `provider`，以及可选的 `plan`、`renewal_date`（`YYYY-MM-DD` 或 null）、`monthly_cost`（非负有限数值或 null）、`currency`（三个字母的货币代码）。 |

事件包含 `seq`、`id`、`project_id`、可为 null 的 `session_id`、`kind`、`payload` 和 `created_at`。Agent 更新事件的载荷应作为文本或数据安全展示，不能作为可执行 HTML。`GET /api/state` 仅返回最近 300 条事件；完整事件分页请使用会话事件接口的游标。

## MCP 工具

`python3 -m agentdock.mcp` 通过标准输入与标准输出传输以换行分隔的 JSON-RPC 消息。它实现 `initialize`、`ping`、`tools/list`、`tools/call`，并忽略通知消息。进程环境中必须包含 `AGENTDOCK_URL` 和 `AGENTDOCK_CAPABILITY`。工作台仅在创建运行时提供这些值，用户无需在工具调用中粘贴提供商凭据。

| 工具 | 参数 | 作用 |
| --- | --- | --- |
| `agent_list` | 无 | 列出当前项目的 Agent。 |
| `message_send` | `recipient_id`、`body`；可选 `correlation_id`、`idempotency_key` | 将定向消息加入队列，发送者身份由系统绑定。不会启动运行。 |
| `inbox_read` | 无 | 读取当前 Agent 最多 50 条待处理消息。 |
| `inbox_ack` | `message_id` | 只能确认发给当前 Agent 的消息。 |
| `memory_search` | 可选 `query` | 通过字面关键词检索，返回当前项目最多 20 条已批准、未归档的记忆。 |
| `memory_propose` | `key`、`content`、`expected_version` | 创建待审核提议，不会直接写入已批准的记忆。 |

协议或工具调用失败时，返回已去除敏感信息的错误。桥接程序禁用 HTTP 代理与重定向，只接受显式指定的数字形式回环地址，并限制请求和响应大小。MCP 定义工具访问边界，不是 A2A 协议，也不能替代操作系统隔离。

---

[English](API.md) · **简体中文** · [返回说明文档](../README.zh-CN.md)
