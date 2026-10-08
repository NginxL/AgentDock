# 本地 API

[English](API.md) · **简体中文** · [项目说明](../README.zh-CN.md) · [架构设计](ARCHITECTURE.zh-CN.md)

版本：**0.3 预览版**。工作台记录的 ID 为 UUID 字符串；`native_session_id` 是由提供商管理的原生会话标识。时间戳采用 UTC 时区的 ISO 8601 格式。除 SSE 接口外，成功响应为 JSON；错误响应为 `{ "error": "message" }`。

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

## 模型与用量接口

`provider` 支持 `codex`、`claude`、`trae`、`pi`、`cursor`、`antigravity`、`grok`、`opencode`、`gemini`、`qwen`。详见[CLI 接入](PROVIDERS.zh-CN.md)。

`GET /api/providers?environment_id=local` 需要管理员令牌，返回 `environment_id` 和服务标识到 `{name, available, reason, supports_ask}` 的映射。本机只检测可执行文件，SSH 只读取已连接设备的检测结果；不启动 CLI 或 SSH，不要求启用执行。`reason` 为 `not_installed`、`adapter_required`、`connect_required` 或 null。

`GET /api/models/{provider}` 需要启用执行，执行本机客户端元信息握手，不发送提示词。返回 `models: [{id, name, efforts}]`，缓存五分钟，只保留白名单模型元信息。可选 `environment_id`（默认 `local`）和 `account_id` 指定同服务、同设备的托管账号；不传 `account_id` 时沿用设备登录。托管账号缓存还按账号标识与登录版本隔离。

`GET /api/metrics` 只读本地统计，返回 `total`、`providers`、`agents`、`scan_status` 和 `as_of`。每组包括输入、输出、缓存读取、缓存写入、总 Token、会话数量、当前及平均 TPS、60 个三秒曲线点。此接口的 `as_of`、`updated_at` 使用 Unix 秒；`current_tps: null` 表示活跃期间缺少采样。数据源索引在启用执行后每十秒扫描变更；界面每三秒读取统计，不触发模型调用。

所有统计只包含已配置 Agent 绑定的原生会话。没有 Agent 时，总量为零，提供方、Agent 和每日活跃集合为空。`GET /api/state` 和 `GET /api/quotas` 中沿用设备登录的 `quotas` 集合只返回已配置 Agent 使用的服务；菜单接口对尚无快照的服务返回 `status: "unknown"` 和空窗口。未配置服务的额度刷新请求会被拒绝。

`activity` 包含 `today`（服务端本地日期）、`days`（最近 365 天已记录日期的 `date` 与 `tokens`）、`updated_at`（最新源记录时间，无记录时为 null）及 `status`（`pending`、`scanning`、`ready`、`partial` 或 `disabled`）。无记录的日期不产生正用量。Codex 每日活跃首次从历史起点分块补全，独立于累计值及 TPS 的快速扫描；重启后继续索引进度，不请求提供方接口。

独立会话的 `project_id` 为 null，拥有固定 `workspace`。独立 Agent 的队友列表和记忆搜索为空，项目派工与记忆提议被拒绝。

任务事件包含 `reasoning_chunk`、`reasoning_message`（替换同一 `item_id`、`part` 的最终摘要）、`tool_call`、`tool_output` 和 `tool_result`，均携带 `run_id`，工具输出增量使用 `item_id`。Codex 提供思考摘要，Claude 提供公开输出的 thinking 块。`run_finished.status` 表示最终状态，`runs.result` 保留最终回复。会话先按游标加载历史，再订阅实时事件；仅在旧服务不支持流式接口时回退到每秒读取。

ACP 将公开思考、消息与工具事件转为同一事件流；最终工具调用之后的助手文本作为最终回复。`context_usage` 的 `used`、`size` 仅表示上下文占用，不进入 Token/TPS 统计。

`agent_message_chunk` 携带文本增量；`agent_message` 替换同一 `provider`、`item_id`、`part` 的完整文本。Codex 可选的 `phase` 区分 `commentary` 和 `final_answer`。这些消息项归入实时过程，`assistant_message` 和 `runs.result` 提供最终回复。Codex 未提供阶段时取最后一条助手消息，明确标为进展的消息不作为回复。Claude 优先使用结果字段，缺失时采用最后一条助手消息的文本块。界面在最终回复到达时收起过程，并移除过程区中重复的回复文本。

事件流使用带 Bearer 请求头的流式 `fetch`，令牌不进入 URL。事件提交 SQLite 后通知订阅者；查询游标与进入等待使用同一把锁，避免衔接时丢失事件。每条 SSE 数据帧约束为约 1 MiB，最多 32 条连接，空闲时每 10 秒发送保活。慢连接写入超时后关闭，界面从已接收游标补读。普通增量最多合并 30 毫秒再渲染，最终回复与结束状态立即刷新。

## 身份认证与请求边界

管理员请求必须携带 `Authorization: Bearer <local admin token>`，占位符替换为本地管理员令牌。`Host` 必须与 `127.0.0.1:<configured port>` 完全一致，端口为配置值。浏览器请求如果携带 `Origin`，必须与同一 HTTP 来源一致；跨站请求会被拒绝。POST 请求体使用 `application/json`，最大为 256 KiB。不支持 CORS 或绑定远程地址。

MCP 请求使用独立的单次运行能力令牌。该凭据只能通过 `/mcp/tool` 访问正在执行的项目、Agent 和会话的工具，不能访问管理员 API。运行结束或取消时撤销令牌，令牌最长有效期为一小时。

默认禁用执行。仅审阅模式允许管理项目、Agent、会话、记忆、订阅和账号元数据；账号原生登录／检查／刷新／删除、启动任务、发送可执行消息、处理运行审批和刷新提供商额度会被拒绝。读取状态不会启动进程或额度探测。

## 用户操作接口

### 运行环境路由

`environment_id` 默认为 `local`。`GET /api/state` 包含 `environments`；项目与 Agent 在创建时可指定环境，会话在创建时记录 Agent 的环境。修改 Agent 的 `environment_id` 只影响新会话，已有会话保留原环境。`GET /api/models/{provider}?environment_id=<id>` 查询所选环境，SSH 查询要求先完成连接检查。本机与 SSH 模型列表均在控制端按环境／服务分别缓存五分钟，选用托管账号时还按账号标识与登录版本隔离；相同组合的并发 SSH 查询合并为一次，重新连接会使对应环境的缓存失效。读取失败不缓存。

界面为已配置且已连接的 Agent 提前读取模型元信息，最多同时预读两个组合，与会话和 Agent 设置共享一分钟的内存缓存；页面可见时每分钟检查缓存。重复打开菜单复用已有列表；缓存过期后在保留列表的同时刷新。工作台凭据、服务、运行环境及托管账号登录版本分别隔离，断开工作台或重新连接环境后清理界面缓存。模型发现不提交 Agent 提示词。

沿用设备登录的额度刷新与人工账单记录写入接受 `environment_id`，按环境与提供方划分作用域。托管订阅账号使用下方独立账号接口。返回的 SSH 快照与订阅包含环境 ID；菜单快照包含兼容字段 `environment_name`，以及该连接下的自定义名称数组 `agent_names`。菜单使用这些名称展示，不附加设备标签；名称不作为路由标识。远端统计来自托管任务的用量事件，不扫描远端历史。`transport_status` 事件报告 `reconnecting` 或 `connected`，不代表任务结束。

| 方法与路径 | JSON 字段与返回结果 |
| --- | --- |
| `POST /api/environments` | `name`、`ssh_host`；可选 `python`，默认为 `python3`。只创建 SSH 记录，不连接主机。 |
| `POST /api/environments/{id}/connect` | 空对象。要求启用执行；安装私有执行组件，返回 Python 和 CLI 版本元信息，不发送模型提示词。 |
| `POST /api/environments/{id}/remove` | 空对象。移除未使用的 SSH 记录；关联项目或 Agent 时拒绝移除，不删除远端文件。 |

显式远端工作目录必须是 POSIX 绝对路径，并在任务开始时存在。Agent 目录留空则在首次执行时创建私有目录；只有同环境项目才会自动继承项目路径。详见 [SSH 协议说明](SSH.zh-CN.md)。

### 托管订阅账号

使用流程见[账号配置与隔离](ACCOUNTS.zh-CN.md)。以下接口仅管理员可用，支持 `codex` 和 `claude`，每个账号绑定一个 `environment_id`。托管凭据保留在所选设备，不进入 SQLite 或 API 响应。`account_policy` 为 `manual` 且 `account_id` 为 null 时，继续沿用设备原有登录。

| 方法与路径 | JSON 字段与返回结果 |
| --- | --- |
| `GET /api/accounts` | `{ "accounts": [...] }`，返回未删除的账号及实测 `usage`，不发起原生查询。 |
| `POST /api/accounts` | `provider`、`label`（1～100 字符）；可选 `environment_id`（默认 `local`）、`priority`（−100～100 的整数，默认 0）。只创建 `pending` 元数据，不登录。 |
| `POST /api/accounts/{id}` | `label`、`priority` 或 `enabled`（布尔值）。服务和设备不可修改；停用／启用前必须结束使用此账号的排队和执行任务。重新启用先设为 `pending`，启用执行时再检查原生登录。也可使用 `status: "disabled"`／`"ready"`，但不能与 `enabled` 同传；`ready` 只能请求重新启用停用账号，不能声明登录成功。 |
| `POST /api/accounts/{id}/login` | 可选 `method`：`browser` 或 `device`。SSH Codex 默认且仅支持 `device`，其余默认 `browser`；Claude 仅支持 `browser`。返回公开登录任务。 |
| `GET /api/accounts/{id}/login` | 读取公开登录任务，并确认已完成的原生授权。要求启用执行，不发起新登录。 |
| `POST /api/accounts/{id}/input` | `code`：官方登录流程提供的确认码，不是密码或 API Token。 |
| `POST /api/accounts/{id}/cancel` | 空对象；取消该账号的登录任务。仅关闭面板不会取消。 |
| `POST /api/accounts/{id}/check` | 空对象；检查原生登录，返回白名单登录元信息。新登录或恢复登录成功后递增 `generation`。 |
| `POST /api/accounts/{id}/refresh` | 空对象；刷新原生登录与额度元信息，不发送模型提示词，返回账号记录。 |
| `POST /api/accounts/{id}/delete` | 空对象；有排队或执行任务使用此账号时拒绝。清理设备上的托管登录后保留 `removed` 历史标记；清理失败可重试。已有会话保留。 |
| `GET /api/accounts/{id}/native` | 仅读取已保存的本机客户端元数据；要求启用执行。不读取当前原生凭据。 |
| `POST /api/accounts/{id}/native` | `operation` 为 `capture`、`switch` 或 `recover`；`client` 为匹配账号服务的 `codex`、`claude_code` 或 `claude_desktop`。仅本机 macOS。明确退出／重开相关桌面应用，仍有 CLI 运行时拒绝。先保存原生登录并核对邮箱，再切换。仅返回公开状态，不返回凭据。 |

所有带账号操作后缀的 POST 接口要求启用执行。元数据接口不接受凭据、任意 CLI 命令、额度读数或登录版本更新。公开登录任务只允许 `id`、`status`、`method`、`url`、`device_code`、`error_code`、`created_at`、`updated_at`；CLI 尚未提供的字段可以缺省。官方授权由用户完成；排队或执行中的任务已固定登录时，不允许替换凭据。

| 账号字段 | 含义 |
| --- | --- |
| `id`、`label`、`provider`、`environment_id` | 工作台标识、自定义名称、固定的服务和设备。 |
| `status`、`error` | `pending`、`ready`、`expired`、`cooldown`、`disabled` 或 `removed`；错误为脱敏公开代码，不保存原始 CLI 输出。 |
| `generation`、`priority`、`last_used_at` | 已验证登录版本、选择优先级、最近选择／预留时间。 |
| `identity` | 原生检查返回的可选 `email`、`plan`，只保存白名单字段。 |
| `quota`、`cooldown_until` | 标准化快照与已知重试时间。`quota` 含 `status`、可选 `fetched_at`、`windows`；窗口可含 `name`、`used_percent`、`remaining_percent`、`duration_minutes`／`window_minutes`、`resets_at`／`reset_at`，未知值缺省。 |
| `usage`、时间戳 | 此账号保留的原生会话分支所产生的 `input_tokens`、`output_tokens`、`total_tokens` 只读总和；`created_at`、`updated_at`。删除会话也会移除对应统计记录。 |

Codex 从账号专属 App Server 读取额度；托管 Claude 账号沿用现有 CLI 网络设置查询 OAuth 额度接口，不发送模型提示词、不自行续期令牌。查询失败保留最后成功样本并标记过期，更新 checked_at、error_code 与 retry_at。并发读取合并，正常刷新间隔为 10 分钟；失败退避和服务端 Retry-After 同样约束手动刷新。未知／过期不按满额处理，设备登录和人工账单记录保持独立。

Agent 和会话可接受 `account_id`（可空）、`account_policy`（默认 `manual`，另有 `auto`、`failover`）以及 `account_ids`（有序、不重复的账号池，默认 `[]`，最多 100 项）。所有引用必须与服务／设备一致，已删除账号不可选。固定账号策略不能包含账号池；非空池必须包含所选默认账号。

- `manual`：固定使用所选账号；null 表示沿用设备登录，不自动替换。
- `auto`：首次自动选择，后续保持该账号。空池搜索同服务同设备账号，非空池保留传入顺序。
- `failover`：优先当前健康账号，再按池顺序、优先级、已报告剩余额度及最近使用时间选择。原生拒绝只有在尚未观察到工作时才允许改用其他账号。

会话在创建时复制 Agent 的账号设置，后续修改 Agent 不改变已有会话。运行记录固定策略、账号池和已选身份／登录版本；自动策略暂无可用身份时，可以等待已知恢复时间。账号被占用时等待，不消耗尝试次数。手动修改要求会话空闲；新账号进入新的 `account_branch` 并重置 `native_session_id`，保留旧消息并传递有界的近期历史。不允许传入任意原生标识，也不跨账号恢复原生会话。

`GET /api/state` 包含全部 `accounts`（含已删除历史标记）及最近 300 条 `account_attempts`，后者按新到旧排序。尝试记录包含 `id`、`run_id`、`number`、`account_id`、`generation`、`account_branch`、`status`、`progress`、`error_code`、`created_at`、`finished_at`；状态为 `running`、`completed`、`rejected`、`failed`、`cancelled` 或 `interrupted`。仅运行时可更新，每轮最多尝试 3 个不同账号。自动切换要求结构化的执行前认证／额度拒绝，且无已观察到的文本、推理、工具、审批或协作动作；普通输出中的错误词不触发切换。已知恢复时间的等待保留 `queued` 和 `next_attempt_at`，仍可取消；重启后中断未完成任务，不自动重放。

### 工作台操作

| 方法与路径 | JSON 字段与返回结果 |
| --- | --- |
| `GET /api/state` | 返回项目、Agent、会话、`runs`、消息、记忆、提议、近期事件、缓存额度、订阅、`accounts`、`account_attempts`、待处理审批和运行模式。 |
| `GET /api/quotas` | 通过 `quotas` 返回经过时效判断的 服务缓存快照。需要管理员令牌，不启动提供方查询，不返回项目或会话数据。 |
| `GET /api/directories` | 查询参数 `environment_id`（默认 `local`）及 `path`（默认 `~`）。仅管理员可用，只读返回最多 200 个目录，包含 `path`、`parent`、`directories`、`truncated`，不读取文件内容。SSH 浏览要求启用执行并连接远端组件；路径在所选设备上解析。 |
| `POST /api/projects` | `name`、`path`（已存在且可信的目录绝对路径）。返回项目。 |
| `POST /api/projects/{id}/agents` | `source_agent_id`；可选 `name`、`role`、`workspace`。按目标项目创建独立成员，复制来源默认设置，不复制会话或历史。同设备默认用项目目录；跨设备必须明确填写目录。需要用户令牌，不启动 CLI。 |
| `POST /api/agents` | `name`、`provider`；可选 `project_id`（null 为独立 Agent）、`role`、`workspace`、`model`、`effort`、`account_id`、`account_policy`、`account_ids`、`permission_mode`（默认 `ask`，或 `full_access`）。独立 Agent 的空目录自动创建，关联项目则沿用项目路径。 |
| `POST /api/agents/{id}` | 更新 `name`、`role`、`model`、`effort`、`permission_mode`、`environment_id`、`account_id`、`account_policy`、`account_ids`。账号设置只影响新会话；切换设备须使用匹配的账号设置。切换位置允许在任务执行期间进行，并保留旧会话的默认设置；未提供的模型、思考强度和目录重置为新位置默认值。`workspace` 可在尚无会话或同时切换位置时修改；`project_id` 仅在尚无会话且无来源引用时可修改；有关联来源的成员须在另一项目单独添加。其他模型及权限变更须无排队和运行任务。提供方不可更改。 |
| `POST /api/agents/{id}/delete` | 空对象；用户认证接口。清理此 Agent 的全部会话专属目录后删除 Agent 和会话记录。存在排队、执行中或未结束的协作任务时拒绝删除。共用项目、共享记忆及其他 Agent 保留。 |
| `POST /api/sessions` | `agent_id`、`title`；可选上述账号字段，原子覆盖复制的 Agent 默认设置。创建空闲工作台会话，此时不会启动原生命令行客户端。 |
| `POST /api/sessions/{id}/account` | `account_id`（可空）；可选 `account_policy`（默认 `manual`）、`account_ids`（默认 `[]`）。修改空闲会话的账号设置；有排队、运行或未结束的委派任务时拒绝。身份或登录版本改变时新建原生分支。 |
| `POST /api/sessions/{id}/settings` | `{ "model": string或null, "effort": string或null }` 覆盖当前会话设置，或 `{ "inherit": true }` 恢复使用 Agent 默认值。仅影响后续提交的消息，不启动 CLI，不更改 Agent 或原生配置。 |
| `POST /api/sessions/{id}/run` | `prompt`（最多 24,000 字符）。将新一轮任务加入执行队列，返回运行记录。 |
| `POST /api/sessions/{id}/cancel` | 空对象。取消该会话尚未结束的逻辑任务，包括排队、执行中或等待委派结果的任务，以及它们现有的后代任务。返回 `{ "ok": true }`。 |
| `POST /api/sessions/{id}/delete` | 空对象；用户认证接口。阻止删除运行中或仍有关联任务的会话，清理专属目录、运行记录与事件；从未运行且无原生绑定的远端会话无需连接；其余远端会话自动准备当前清理程序，清理成功后才移除本机记录。SSH 清理失败返回 `409` 并保留记录供重试。共用项目目录与原生登录保留。 |
| `POST /api/runs/{id}/cancel` | 空对象。取消指定运行所属的逻辑任务，包括它现有的排队或正在执行的后代任务。返回 `{ "ok": true }`。 |
| `GET /api/sessions/{id}/events?after=0` | 返回 `{ "events": [...] }`，按递增的 `seq` 排序，每次最多返回 500 条。 |
| `GET /api/sessions/{id}/events/stream?after=0` | 使用相同的管理员认证返回 SSE。`data` 为 `{ "events": [...] }`，`id` 为本批最后一个 `seq`；断线后携带最后接收的游标重连。 |
| `POST /api/messages` | `project_id`、`recipient_id`、`body`（最多 12,000 字符）；可选 `recipient_session_id`、`correlation_id`、`idempotency_key`。以 `human` 身份派发任务，返回投递记录。 |
| `POST /api/memories` | `project_id`、`key`、`content`、`expected_version`（新建键时为 0）。 |
| `POST /api/memories/{id}/archive` | `expected_version`。执行软归档，同时新增版本与历史记录。 |
| `POST /api/proposals/{id}/approve` | `expected_version`。必须同时匹配提议中的预期版本和当前记忆版本。 |
| `POST /api/proposals/{id}/reject` | 空对象。拒绝待处理的提议。 |
| `POST /api/approvals/{id}` | `option_id`，必须为 AgentDock 返回的、仍待处理的审批选项之一。 |
| `POST /api/quotas/refresh` | `provider`。Codex／Claude 使用已有读取器，其他已配置服务返回未知额度，不发起探测。点击“额度与订阅”时调用，必须启用执行；与服务定时刷新共用节流。 |
| `POST /api/subscriptions` | `provider`；可选 `plan`、`renewal_date`（`YYYY-MM-DD` 或 null）、`monthly_cost`（非负有限数值或 null）、`currency`（三个字母，默认为 `USD`）。 |

取消接口返回成功，表示已接收停止请求；最终状态通过 `runs` 确认。正在执行的任务会立即失去 MCP 权限，其原生进程组将被中断并终止。排队任务取消后不会启动。取消操作不会回滚命令行客户端已经产生的文件改动。

名称和角色由用户定义，与 `provider` 独立。更新接口使用工作台管理员令牌，在仅审阅模式也可调用；智能体的执行令牌不能修改角色。每轮构建提示词时读取最新角色，已提交给原生 CLI 的提示词保持不变。更新不会重建会话或清除历史。`provider` 不可修改；已有会话的项目、目录和环境固定；只有切换账号分支或确认重新登录才改变原生标识。切换位置时，已有会话将模型、思考强度及权限默认值保存在 `agent_defaults`；会话单独设置的模型覆盖优先。`{ "inherit": true }` 恢复这些已保存的默认值；未因切换位置而独立的会话仍沿用当前 Agent 默认设置。

## 状态与任务记录

`GET /api/state` 包含最近 **300 条运行记录**和 **300 条事件**，按时间顺序返回。`account_attempts` 包含最近 300 次尝试，按新到旧排序。其他集合暂不分页。此预览版没有单独的运行历史分页接口。会话事件接口支持游标分页，可将上次返回的最后一个 `seq` 作为下一次请求的 `after`。

| 记录 | 主要字段 |
| --- | --- |
| Agent | `id`、`project_id`、`source_agent_id`（可空来源引用）、`environment_id`、`name`、`provider`、`role`、`workspace`、`workspace_is_default`（状态响应中的派生字段）、`model`、`effort`、`permission_mode`、`account_id`、`account_policy`、`account_ids`。修改权限需要用户访问令牌，MCP 能力令牌不能编辑 Agent。 |
| 会话 | `id`、`project_id`、`agent_id`、`title`、`status`、`native_session_id`、`environment_id`、`workspace`、`agent_defaults`、`model`、`effort`、`model_override`、`account_id`、`account_policy`、`account_ids`、`account_generation`、`account_branch`、`created_at`、`updated_at`。首次执行前或切换分支后原生标识为 null，公共 API 不允许直接指定它。 |
| 运行 | `id`、`session_id`、`project_id`、`agent_id`、`prompt`、`status`、`origin`、`parent_run_id`、`root_run_id`、`task_run_id`、`depth`、`delivery_id`、`model`、`effort`、`permission_mode`、`result`、`error`、`account_id`、`account_policy`、`account_ids`、`account_generation`、`account_branch`、`account_selection_pending`、`next_attempt_at`、时间戳。模型、推理等级和权限在提交时记录。 |
| 投递（`messages`） | `id`、`project_id`、`sender_id`、`recipient_id`、`sender_session_id`、`recipient_session_id`、`sender_run_id`、`run_id`、`reply_run_id`、`body`、`status`、`result`、`error`、`correlation_id`、`idempotency_key`、时间戳。 |
| 审批 | `id`、`run_id`、`session_id`、`project_id`、`request`、`options`、`status`、`picked_option_id`、`created_at`。状态接口只返回待处理审批。 |

运行的 `origin` 为 `human`（用户任务）、`delegate`（委派任务）或 `reply`（结果回传后继续执行）。生命周期为 `queued`（排队）→ `running`（执行中）→ `completed`（完成）、`failed`（失败）或 `cancelled`（取消）；重启时仍未结束的任务变为 `interrupted`（中断）。会话状态优先反映正在执行或排队的任务，否则显示最近的终态。

`task_run_id` 将同一逻辑任务的初始轮次及后续结果处理轮次归为一组；`root_run_id` 标识整棵协作任务树。某轮执行完成，不一定代表它所属的逻辑任务已经完成。

`messages` 集合保存投递审计记录。未指定 `recipient_session_id` 时，投递选择 Agent 当前运行位置的最近会话，无会话则在该位置创建；显式指定会话及结果续接均使用会话原位置。提交成功会产生排队任务，**不代表接收方已经完成**。`waiting` 状态表示接收方已结束某轮执行，但仍须等待子任务结果或后续处理轮次，才能最终交付。只有任务结算后的投递记录才表示最终状态和结果。若存在 `reply_run_id`，它指向发送方的结果处理轮次；需检查该运行，判断发送方是否已处理结果。`acknowledged_at` 表示接收方开始执行的时间，不再表示人工确认收件。

事件包含 `seq`、`id`、`project_id`、可为 null 的 `session_id`、`kind`、`payload` 和 `created_at`。生命周期事件包括 `run_queued`、`run_started`、`run_finished`、`message_queued`、`reply_queued` 和 `task_settled`；文本与工具事件包括 `agent_message_chunk`、`assistant_message`、`tool_call` 和 `tool_result`。所有提供商载荷均应作为不可信展示数据处理，不能作为可执行 HTML 或授权依据。

原生客户端确认模型后发送 `model_info` 事件，含 `run_id`、`native_id`、`model`，以及可用时的 `effort` 与 `model_provider`。这些值来自 CLI 协议，不解析回复文本来推测模型。

## 派发与会话续接

启用执行后，`message_send` 和 `POST /api/messages` 会安排真实执行。指定 `recipient_session_id` 时，该会话必须属于同项目的目标 Agent；未指定时，使用目标 Agent 最近更新的会话，若没有会话则新建。Agent 不能向自己委派任务。

Agent 的发送者身份、原始会话和父任务均由运行能力令牌确定，API 客户端不能冒用该身份。以 `human` 身份派发时，不会为发送方 Agent 创建自动续接任务。

Agent 间委派必须等接收方的逻辑任务结算后，才向**确切的原发送会话**回传最终结果。例如，B 为 A 工作时委派给 C，B 会等待 C 回传并完成自身的后续处理，再向 A 返回最终答复。多个子任务统一跟踪，不会将中间的派工说明作为已完成成果返回。

完成、失败和取消的任务，只要原请求方仍有效，都可以安排结果处理轮次；失败和取消按真实状态回传。已停止的请求方不会被重新唤醒，中断的任务不会重放。每次继续处理都会恢复原生会话，并可在同一组上限内继续委派。

共用工作目录或托管账号的 Agent 顺序执行。发送方委派后应结束当前轮次，不应等待或轮询尚在等待同一工作目录的接收方。使用不同托管账号且工作目录互不重叠时可以并行执行。

`idempotency_key` 按项目与发送者划分作用域。使用相同键重试相同任务会返回原投递记录；改变接收者、正文、关联标识、发送方运行或会话，或显式指定不同目标会话，会返回冲突。它用于同一次发送运行中的重试去重，不用于合并无关任务。

## 项目任务

详见[任务流程与保留规则](TASKS.zh-CN.md)。这些接口要求管理员令牌。`GET /api/state` 增加 `tasks` 和未回答的 `task_questions`；原会话、派工接口保持兼容。

| 接口 | 参数 / 结果 |
| --- | --- |
| `POST /api/tasks` | `project_id`, `title`, `goal`, `criteria`（每行一项）, `owner_id`；可选 `acceptance_policy: owner/human`、`review_required`、`workspace_mode: shared/worktree`、`source_session_id`。只保存任务。 |
| `GET /api/tasks/{id}` | 任务及 inputs、questions、deliveries、reviews、journal、runs、sessions、workspaces；`can_steer_run_id` 表示可即时调整的活动轮次。 |
| `POST /api/tasks/{id}/inputs` | `body`, `intent: record/discuss/develop`, `request_id`；可选 `action: queue/steer`、`expected_run_id`（steer 必填）。相同请求标识与内容幂等，改变内容返回冲突。仅 record 无需启用执行。 |
| `POST /api/tasks/{id}/questions/{question_id}/answer` | `answer`。相同答案重试幂等；不能修改已确认答案。保存后按任务状态决定是否继续负责人。 |
| `POST /api/tasks/{id}/settings` | `title`, `goal`, `criteria`, `acceptance_policy`, `review_required`。等待执行结束或暂停后编辑；修改使旧交付失效。 |
| `POST /api/tasks/{id}/pause`、`cancel` | 空对象；停止整个任务的活动及排队运行。 |
| `POST /api/tasks/{id}/resume` | 可选 `owner_id`、`intent: develop/discuss`、用于恢复去重的 `request_id`；先核对旧执行停止，再创建新原生会话继续。 |
| `POST /api/tasks/{id}/accept` | 空对象；所有验收条件成立后完成。 |
| `POST /api/tasks/{id}/reopen`、`archive` | 空对象；只接受已完成或已取消且执行已结束的任务。 |

任务状态为 `draft/active/waiting_input/review/completed/paused/interrupted/cancelled/archived`。`review` 表示执行已结束、尚未验收，也可能尚无正式交付；接口仍验证全部验收条件。任务、输入、问题与报告跨会话持久化。`work_task_id` 与现有派工链的 `task_run_id` 是不同标识。

即时调整使用 Codex `turn/steer` 与 `expectedTurnId`；`accepted/rejected/unknown` 区分回执，最终运行结束后已接收的输入成为 `processed`。未知回执不重试，不会偷偷转入队列。只有选中任务及角色匹配的活动能力令牌才能读取任务上下文或写入问题/报告。

## MCP 工具

`python3 -m agentdock.mcp` 通过标准输入与标准输出传输以换行分隔的 JSON-RPC 消息，实现 `initialize`、`ping`、`tools/list` 和 `tools/call`，通知消息不返回响应。支持协议版本 `2025-11-25`、`2025-06-18`、`2025-03-26` 和 `2024-11-05`。

工作台通过子进程环境提供 `AGENTDOCK_URL` 和 `AGENTDOCK_CAPABILITY`，工具参数不接受提供商凭据。桥接程序禁用 HTTP 代理与重定向，只接受 `http://127.0.0.1:<port>`，限制输入输出大小，并对工具错误去除敏感信息。

| 工具 | 参数 | 作用 |
| --- | --- | --- |
| `agent_list` | 无 | 列出当前项目中的 Agent，包含调用者；不会启动它们。 |
| `message_send` | `recipient_id`、`body`；可选 `recipient_session_id`、`correlation_id`、`idempotency_key`、`task_role: worker/reviewer` | 创建可执行投递，返回其标识与状态；接收方满足执行条件后运行，结果会触发发送方会话继续处理。 |
| `task_status` | `message_id` | 查看当前项目内调用者发送或接收的投递状态与结果；返回快照，不阻塞等待。 |
| `memory_search` | 可选 `query` | 按字面关键词检索，最多返回 20 条已批准、未归档的项目记忆。 |
| `memory_propose` | `key`、`content`、`expected_version` | 创建待人工审核的提议，不能直接覆盖已批准记忆。 |
| `task_context` | 无 | 当前任务的有界摘要、目标、要求、输入、问题、结果与工作区。 |
| `task_history` | 可选 `after`, `offset` | 顺序分页读取完整持久记录；按返回的 `next_after/next_offset` 接续，直到 `record: null`。JSON 文本可跨页。 |
| `task_result` | `run_id`，可选 `offset` | 当前任务的完整最终报告，按 `next_offset` 继续；删除执行会话后仍可从持久记录读取。 |
| `task_ask` | `question`，可选 `options` | 保存待确认问题；之后结束当前轮次。 |
| `task_deliver` | `summary`, `checks`，可选 `artifacts`, `risks` | 仅负责人提交；checks 每项包含 criterion、status、evidence。 |
| `task_review` | `verdict: approved/changes_requested/unverified`, `summary` | 仅独立审查者为当前版本提交报告。 |

0.2 协议不再提供旧的 `inbox_read` 和 `inbox_ack`。MCP 工具不能授予提供商执行权限；原生工具审批通过经过身份认证的工作台审批流程处理。

## 执行上限与升级行为

每个原生进程执行一轮前台任务后退出。Claude 子进程环境设置 `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`，AgentDock 不托管其原生后台任务。已登记 Agent 之间的委派通过 `message_send` 和持久化调度队列完成。此设置不修改用户全局环境，也不影响其他 Claude 进程。

| 边界 | 当前行为 |
| --- | --- |
| 并发 | 最多 4 个原生进程同时执行。同一 Agent、同一托管账号，以及路径相同或互为父子目录的工作区，不能并发执行。 |
| 协作 | 根任务深度为 0，委派深度最多为 3。每个根任务最多产生 16 次运行，包含根任务、委派任务和结果续接。新委派会预留结果回传所需容量，因此可能在实际运行次数未满 16 次时即被拒绝。 |
| 超时 | 服务采用 15 分钟运行时限和 2 分钟审批时限；到期后停止任务，不授予权限。 |
| 输出 | 原生输出最多 8 MiB，单条协议消息最多 512 KiB。运行事件和最终文本另有大小限制；保存的最终文本最多 64,000 字符，自动结果回传最多包含 12,000 字符。 |
| 设备登录额度 | 启用执行并配置额度组件后，每 600 秒自动刷新；点击额度页也会触发。同一提供商的刷新间隔至少为 60 秒，探测超时为 35 秒。超过 15 分钟的快照标记为过期；超过重置时间后，剩余额度改为未知。 |

SQLite 采用增量迁移，保留已有项目、会话、历史与记忆。旧邮箱模型中没有可执行 `run_id` 的消息会变为 `legacy` 历史记录，永远不会自动派发。原生会话绑定在首次 0.2 执行时建立，不导入旧适配器会话。

重启后，原先排队或执行中的轮次，以及排队、执行或等待子结果的投递记录，均标记为 `interrupted`，待处理审批取消，能力令牌撤销。不会自动重放未完成任务。用户重新提交任务时，可以恢复 AgentDock 自己拥有的原生会话；尚未实现导入 Codex App 或其他终端的既有会话。

---

[English](API.md) · **简体中文** · [项目说明](../README.zh-CN.md) · [架构设计](ARCHITECTURE.zh-CN.md)
