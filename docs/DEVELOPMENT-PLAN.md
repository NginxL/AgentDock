# AgentDock 审查结论与合规开发计划

> 整理日期：2026-10-09　｜　代码基线：`f00da1a`（main）　｜　分工：你开发，Claude review
>
> - 代码位置均以 `f00da1a` 为准。
> - 合规判断基于各服务商的公开条款，不构成法律意见，最终解释以服务商为准。
> - 每完成一批，请更新 2.9 节的状态表，并把提交范围发给 reviewer 复核。
> - **本文取代此前的账号方案。** `docs/ACCOUNTS*.md`、`docs/CREDENTIALS.md`、`docs/EXPERIMENTS.md`、`docs/REVIEW-FOLLOWUP.md` 中与本文冲突的内容，一律以本文为准，并在阶段 0 中同步修改。

## 目录

- 第一部分　调整后的审查结论
  - 1.1 总体结论
  - 1.2 调整的结论
  - 1.3 被计划取代的修复
  - 1.4 补充的遗漏
  - 1.5 维持不变的结论
  - 1.6 当前状态与未闭环事项
- 第二部分　合规的后续开发计划（参考 Magpie）
  - 2.1 合规底线
  - 2.2 Magpie 能力取舍
  - 2.3 阶段 0：合规收敛（C1–C8）
    - 2.3.9 迁移总则（升级规则）
  - 2.4 阶段 1：稳定性与安全（S2–S8）
  - 2.5 阶段 2：借鉴 Magpie 的体验（M1–M7）
  - 2.6 阶段 3：分发与工程（D1–D4）
  - 2.7 明确不做的事
  - 2.8 里程碑与依赖
  - 2.9 协作与 review
- 附录 A　三轮审查明细
- 附录 B　参考资料

---

# 第一部分　调整后的审查结论

## 1.1 总体结论

- **技术方面：** 三轮审查共提出 22 + 10 + 2 个问题。正确性、性能、架构类的结论都成立，截至 `f00da1a` 已全部修复并复验。
- **账号和凭据方面：** 第一轮给的是"加固功能"的建议，这个方向错了。按已确认的服务商规定，正确的结论是"这些功能不该存在"。
- **判断失误：** 第一轮审查时没有先核实官方条款。因此，按原建议做的快照加密、Swift 钥匙串代理和 ACP 凭据租约，会在阶段 0 中删除。
- **主链路是合规的：** AgentDock 驱动用户自己安装的、未修改的官方 CLI，用的是用户本人的登录，真正干活的是 CLI 本身，AgentDock 只通过 MCP 提供协作工具。这正是官方明确允许的用法，应当保持。

## 1.2 调整的结论

| 原条目 | 原建议 | 调整后的结论 | 计划项 |
|---|---|---|---|
| 第一轮 #1　本机换号把凭据存成明文 | 存回钥匙串，或加密后保存 | 删除本机换号：保存客户端的登录凭据本身就不被允许 | C2 |
| 第一轮 #2　钥匙串授权落在 Python 上 | 把钥匙串访问挪到签名的 Swift 程序 | AgentDock 不访问钥匙串，也不读取任何 token | C1、C2 |
| 第一轮 #3　多账号自动切换 | 先评估条款；默认关闭，开启时提示风险 | 删除自动切换和"自动选择"，账号只能手动指定 | C3 |
| 第一轮 #3　直连额度接口 | 定性为"不稳定、有条款风险" | 在 Claude Code 之外使用订阅 token，与官方规定冲突，必须删除 | C1 |
| 第一轮 #4　ACP 凭据按会话复制 | 统一走"租约 + 复制进、复制回" | 这个建议本身就是中转凭据；改为完全不复制，凭据只留在 CLI 自己的存储中 | C4 |
| 第一轮 #19　发布门槛 | 做签名、公证的安装包 | 结论不变，补充：对外分发前确认商业条款 | D4 |
| 第一轮 #22　功能范围 | 把本机换号拆成实验功能 | 改为删除 | C2 |

## 1.3 被计划取代的修复

这几条的修复本身是正确的，但修复所在的代码会在阶段 0 中删除。

| 原条目 | 修复内容 | 取代它的计划项 |
|---|---|---|
| 第二轮 #2 | ACP 凭据租约的永久锁死 | C4（删除租约） |
| 第二轮 #3 | 同一 ACP 服务并发运行 30 秒后失败 | C4。届时再评估调度器的按服务排队是否保留 |
| 第二轮 #8 | 本机换号状态查询与启动崩溃 | C2（删除本机换号） |

## 1.4 补充的遗漏

| 问题 | 结论 | 计划项 |
|---|---|---|
| 账号登录嵌在 AgentDock 自己的界面中：后台运行登录命令、抓取登录链接、代收确认码 | 接近"在自己的应用里提供 Claude.ai 登录"。改为由用户在终端里用官方 CLI 完成登录 | C6 |
| 服务选择器和卡片中使用了 Claude 的标志 | 官方只允许用纯文字说明；使用标志需要书面许可 | C7 |
| `admin.token` 可被同一系统用户读取，进而调用审批等管理接口 | 中低风险，需评估并加固 | S8 |
| 自动派工会放大用量，而 Pro/Max 额度以普通个人使用为前提 | 建议默认开启"派工需人工确认" | C8 |

## 1.5 维持不变的结论

- **第一轮：** #5–#18、#20、#21（正确性、性能、架构、规范类），已修复或部分完成，剩余工作见阶段 1。
- **第二轮：** #1、#4、#5、#6、#7、#9、#10。其中 #5 的错误码约定对删除后剩下的账号功能仍然适用。
- **第三轮：** A、B。

## 1.6 当前状态与未闭环事项

- **基线测试（`f00da1a`）：** 后端 465 项、前端 221 项；生产构建、ruff、ruff format、mypy 均通过。后续批次的验证记录见附录 A.4。
- **自托管 runner：** 如果曾经注册过 `agentdock-live` runner，需要在仓库 Settings → Actions → Runners 中注销，并检查组织的 runner group；那台机器上的 CLI 登录建议退出后重新登录。
- **GitHub CI：** reviewer 查询时被 API 限流，没能核对，以你提供的运行记录为准。

---

# 第二部分　合规的后续开发计划（参考 Magpie）

## 2.1 合规底线

### Anthropic 的规定

来源：Claude Code 官方文档"Legal and compliance"页的认证与凭据使用一节，以下为意译。

- **OAuth 登录：** 只面向订阅用户，用于正常使用 Claude Code 和 Anthropic 自家的应用。
- **第三方开发者：**
  - 构建产品时应使用 API key；
  - 不得在自己的应用中提供 Claude.ai 登录；
  - 不得替用户用 Free/Pro/Max 凭据转发请求；
  - 不得收集、存储或中转 Claude.ai 的凭据和会话 token；
  - 登录必须走 Anthropic 自己的流程。
- **明确允许：** 用户用自己的订阅登录未修改的 Claude Code 程序；用户配置和管理自己的 API key。
- **额度：** Pro/Max 的额度以普通个人使用为前提；Anthropic 可以不经通知直接执行限制。
- **在产品中运行 Claude Code：** 需要同意商业条款，并满足三个条件：
  - 不修改程序；
  - 不替用户付费、转售或中转用量；
  - 每个用户用自己的凭据登录。
- **名称与标志：** 可以用纯文字说明产品运行 Claude Code；其他使用 Anthropic 名称或标志的情况需要书面许可。

### 其他服务商

- **OpenAI：**
  - Codex app-server 是官方提供给集成方的接口；
  - 使用条款禁止规避速率限制——这一条只能通过第三方条款追踪网站确认，官方页面返回 403，请自行核对原文。
- **Gemini、Qwen、Trae、Cursor 等 ACP 服务：** 条款没有逐一核实，保持实验开关默认关闭。

### AgentDock 的七条底线

阶段 0 完成后必须全部满足，之后每个新功能都要逐条对照：

1. 只驱动用户自己安装的、未修改的官方 CLI，安装包不捆绑这些 CLI。
2. 登录只在官方 CLI 中由用户本人完成；AgentDock 不展示、不转发登录链接和确认码。
3. AgentDock 不读取、不复制、不移动、不存储任何凭据文件或 token，也不直接调用服务商接口。
4. 一个会话、一个 Agent 只使用用户手动指定的一个账号；不在账号之间自动分摊额度。
5. 不把订阅或账号提供给其他工具或其他人使用，不提供模型网关。
6. 不做任何规避服务商识别的设计。
7. 服务商一律用纯文字名称或中性图标表示。

## 2.2 Magpie 能力取舍

Magpie 是开源的本地模型网关和账号调度工具（[usemagpie.ai](https://usemagpie.ai/zh/)）。它的界面和工程细节值得借鉴。

但它的 Claude 订阅链路不能照搬：每次请求启动真实的 `claude` 程序，再经 MCP 把 OpenCode、Codex 等调用方的工具接入。它的参考文档写明，这样做是为了不被 Anthropic 的系统提示分类器识别为第三方流量。这违反第 2、3、5、6 条底线。

| Magpie 能力 | AgentDock 的做法 | 计划项 |
|---|---|---|
| 每个账号独立的配置目录，登录和刷新交给 CLI | **借鉴**：已有，再把登录交还终端、去掉凭据复制 | C6、C4 |
| 订阅作为供应商，给其他 Agent 使用（Claude 走真实 CLI 并规避识别） | **不做** | — |
| 读取、刷新、写回客户端的 OAuth 凭据 | **不做**，并删除现有同类代码 | C1、C2 |
| 账号调度：智能、顺序、轮流、用量少优先、周额度节奏 | **不做**自动调度；周额度节奏只做展示 | C3、M5 |
| 账号状态规则：429 按 Retry-After 暂停，其他失败逐次加长暂停，失败账号不删除 | **合规改造**：只用于同一账号的等待、重试和提示，不切换到其他账号 | C3、M1 |
| 首字节前重试，Agent 看不到错误 | **借鉴**：同一账号的临时网络错误，在没有任何输出前重试 | S9 |
| 菜单栏按 Agent 显示当前模型并一键切换；"方案"一次切换所有 Agent | **借鉴**：只改 AgentDock 自己的设置 | M2 |
| 按意图路由：用小模型给每轮内容分类 | **合规简化**：用已知的任务类型（讨论、执行、审查）选模型，不额外调用模型 | M3 |
| 供应商页：列出正在使用它的 Agent；账号池视图：用量、重置时间、请求数、错误数 | **借鉴**：账号视图，去掉改道、轮换类指标 | M1 |
| 按 Agent、模型统计 token、缓存命中、费用 | **借鉴** | M6 |
| 额度从 CLI 自己获取（不直连接口），读取频率有上限 | **借鉴**：Claude 从运行事件被动获取，Codex 用官方接口并限频 | C1、M5 |
| 密钥只在工具内，Agent 看不到；不读取 shell 环境中的密钥 | **合规改造**：AgentDock 不保存密钥，API 计费账号也由官方 CLI 登录、凭据存在 CLI 自己那里 | M4 |
| 改写配置时原子写入、只改必要项、保留注释 | **借鉴**：默认不改原生配置；确需改动时遵守这一规则 | M2 |
| CLI 与 TUI | **借鉴** | M7 |
| 签名公证、自动更新、多平台、小体积 | **借鉴**：自动更新、Linux；Windows 依赖 POSIX，暂不支持 | D1、D2 |
| 集中参考文档、LESSONS.md、AGENTS.md | **借鉴** | D3 |
| 多协议转换网关（让一个 CLI 使用另一家的模型） | **不做**：超出 AgentDock 的定位，各家条款需单独评估 | — |
| 插件系统 | **暂不做**：会扩大攻击面 | — |

## 2.3 阶段 0：合规收敛（C1–C8，约 1.5 周）

**阶段 0 是删除相关能力，不是加固。** 被删除的功能不保留实验开关。唯一保留的实验开关是 `acp_agents`，原因是这些服务商的条款还没核实，它与账号方案无关。

**顺序：** C1 → C3 → C2 → C6 → C4 → C7 → C5 → C8。每项写明目标、改动、迁移、测试、验收，其中验收就是 review 时检查的内容。所有升级规则汇总在 2.3.9 节的迁移总则中。

### C1　去掉直接用 Claude OAuth token 调接口的代码

- **目标：** 不再读取 Claude token，不再直接请求 `api.anthropic.com`。
- **改动：**
  - 删除 `account_network.claude_get`（`agentdock/account_network.py:158`），以及只为它服务的严格网络解析；
  - 删除 `AccountManager.refresh` 中的 Claude 额度分支（`agentdock/accounts.py:678` 起）和 `account_keychain.claude_credentials`；
  - 账号身份改用 `claude auth status --json`；
  - 额度改为在运行中解析 stream-json 的 `rate_limit_event`（`agentdock/claude_protocol.py:157` 已在解析），保存窗口、重置时间和采样时间；
  - 不做主动查询：Claude Code 2.1.284 没有可以非交互运行的用量命令；
  - 删除实验开关 `claude_quota`。
- **迁移：** 已有 Claude 额度保留原数值和采样时间，标注"来源：升级前记录"（`legacy_snapshot`）；新运行事件标注"来源：上次运行"（`cli_event`）。旧值来自直接查询或桌面快照，不能改标为运行事件；没有数据时显示"未知"。
- **测试：** 模拟的 `rate_limit_event` 能更新额度；没有事件时显示未知；身份解析正确。
- **验收：** `grep -rnE "api\.anthropic\.com|accessToken|claudeAiOauth|oauth-2025-04-20" agentdock native` 结果为空；额度页显示数据来源和时间。

### C3　账号只能手动指定

- **目标：** 对所有服务，都不再在账号之间自动选择或切换。
- **改动：**
  - `account_policy` 只接受 `manual`（`agentdock/account_store.py:398`）；
  - 删除 `auto`、`failover` 的逻辑（`account_store.py:496–498、693、842–855、900`），以及 `agentdock/runtime.py:903` 的重试分支；
  - 删除账号池 `account_ids` 和实验开关 `automatic_failover`；
  - 额度耗尽时：在同一账号内等到已知的重置时间后继续执行排队任务，或提示用户手动换账号；
  - 前端 `AccountSelection` 只保留"沿用设备登录"和"指定账号"；
  - 文案改为：多账号是给用途不同的独立账号用的（例如个人和公司），不是为了叠加额度。
- **迁移：** 按 2.3.9 节的"账号策略的升级规则"执行。要点是：
  - 不静默改用其他账号；
  - 也不静默改为沿用设备登录；
  - 无法确定账号的对象，要标记为"需要选择账号"。
- **测试：** 被限流时不会产生第二次尝试；旧策略按 2.3.9 节迁移正确；API 拒绝非 `manual` 的取值。
- **验收：** `grep -rn "failover\|automatic_failover" agentdock web/src` 只剩迁移代码；每个运行在 `run_attempts` 中最多一条记录。

### C2　删除本机换号和凭据代理

- **目标：** 不再保存或切换任何客户端的登录。
- **改动：**
  - 删除 `native_accounts.py`、`credential_broker.py`、`account_keychain.py`，以及 `account_service` 中的 `native_status`、`native_action` 和对应路由；
  - 删除 Swift 的 `CredentialCore`、`CredentialChecks`，以及 `main.swift` 中的凭据管道；恢复普通的 stdin/stderr，stderr 改为写入日志文件；
  - 删除前端的本机客户端面板和实验开关 `native_switching`；
  - 文档写明：切换客户端账号，请在客户端里使用官方的登录、退出功能。
- **迁移：**
  - 启动时删除 `accounts/native-clients/` 下的快照、`previous.json` 和 `pending.json`；
  - 桌面端直接删除自己创建的钥匙串条目 `io.github.nginxl.AgentDock.snapshots`；
  - 提示用户一次，并说明 SSD 上无法保证彻底擦除。
- **测试：** 用带旧快照的数据目录启动，快照被清除；Swift 构建和桌面检查通过。
- **验收：** `grep -rnE "Claude Safe Storage|Claude Code-credentials|Codex Auth|SecItem" agentdock native web/src` 结果为空；上述模块文件已不存在。

### C6　登录交还官方 CLI

- **目标：** 登录完全在官方 CLI 中由用户本人完成。
- **改动：**
  - 删除后台登录：`agentdock/accounts.py` 中的 `start`（516）、`_login_worker`（864）、`_login_hints`（148）、`submit`（598），以及 `login`、`input`、`cancel` 路由。
  - 账号页的"登录"改为显示命令，并提供复制按钮：
    - Claude 订阅：`CLAUDE_CONFIG_DIR=<账号目录> claude auth login`
    - Claude API 计费：在同样的命令后加 `--console`
    - Codex：`CODEX_HOME=<账号目录> codex login`
    - SSH 设备：先显示 `ssh <host>`，再显示在远端执行的命令
  - 命令中的环境变量必须和运行时完全一致。`accounts.py:257` 目前还额外设置了 `CLAUDE_SECURESTORAGE_CONFIG_DIR`，需要结合 C4 统一处理。
  - 用户点"检查登录"时，AgentDock 用 `claude auth status --json` 或 Codex 的 `account/read` 确认。
  - 可选：桌面版直接打开"终端"应用并执行这条命令，不读取输出。
- **测试：** 覆盖登录成功、未登录、CLI 缺失三种情况；在终端登录后，运行能识别登录；上述路由已移除。
- **验收：** `grep -rnE "openpty|_login_hints|_login_worker" agentdock` 结果为空；界面上不再有确认码输入框。

### C4　不再复制凭据文件和可能含密钥的配置文件

- **目标：** 凭据和可能含密钥的配置只存在于 CLI 自己的目录中。AgentDock 不读、不复制、不移动、不写回。
- **范围：** 不只是 `auth.json`。以下文件都可能含密钥（API key、Bearer 头、`apiKeyHelper`、`primaryApiKey`、`.env` 变量），全部停止复制，也不做符号链接：

  | 来源 | 当前复制的文件 | 代码位置 |
  |---|---|---|
  | Codex | `config.toml`、`managed_config.toml`、`hooks.json` | `agentdock/codex_home.py:78` |
  | Claude | `settings.json`、`settings.local.json`、`.claude.json` | `agentdock/session_storage.py:38–49` |
  | ACP | `acp_home.SEEDS` 中的全部文件：`.env`、`settings.json`、`opencode.json`、`cli-config.json`、`models.json`、`traecli.toml` 等，以及各类 `auth.json`、`oauth_creds.json` | `agentdock/acp_home.py` |
  | 托管账号 | 每轮复制进、复制回的 `auth.json`、`.credentials.json` | `agentdock/accounts.py:434` |

- **改动：**
  - **运行设置：** AgentDock 自己需要的设置，在运行时通过官方参数传入，只传非敏感项：
    - Codex 用 `-c key=value`，现在已经这样传 `sqlite_home`、`log_dir`；
    - Claude 用 `--settings`、`--setting-sources`。
  - **不含密钥的指令和资源：** `CLAUDE.md`、`AGENTS.md`、`AGENTS.override.md`、`skills`、`commands`、`agents`、`rules`、`plugins` 可以继续用符号链接共享。
  - **代理和证书：** 保持现有来源不变，即进程环境变量，加上 `account_network.NETWORK_ENV` 白名单（只取网络相关的键，不保存、不记录、不传递其他键）。
  - **托管账号：** 会话直接以账号目录作为 `CLAUDE_CONFIG_DIR` 或 `CODEX_HOME` 运行，这个目录由官方 CLI 登录时生成。
    - 删除 `credential_session`、`_copy_credential`、`_fingerprint` 和恢复日志；
    - 会话之间靠原生会话 ID 区分；
    - 删除会话时只删除该会话自己的原生记录：Codex 用 app-server 的 `thread/delete`，Claude 删除对应的 jsonl。
  - **沿用设备登录：** 提供两种模式，作为 Agent 设置，默认使用隔离模式。
    - **隔离模式（默认）：** 会话继续使用私有目录，保持隔离，目录里只放三类东西：
      1. 凭据的符号链接——需要先实测确认 CLI 刷新时写回的是链接目标，确认不了就禁用隔离模式；
      2. 指令和资源的符号链接；
      3. AgentDock 写入的非敏感运行设置。
      用户全局配置中的其他设置（自定义模型服务商、钩子等）在隔离会话中不生效，需要在界面和文档中说明。
    - **原生模式：** 直接使用 CLI 的默认目录，不做任何复制或链接，完全沿用用户原有的配置；会话会出现在原生客户端的历史中。
  - **ACP：** 删除 `credential_lease.py` 和 `acp_home` 的种子复制，改为使用 CLI 的默认目录。只有当 CLI 提供独立的数据目录变量、且不需要搬动凭据和配置时，才做会话隔离。ACP 仍放在实验开关后面。
  - **SSH：** 同步修改 `ssh_worker` 中对 `credential_session` 的调用和远端的种子复制。
- **迁移：** 按 2.3.9 节的"凭据与配置的升级规则"执行。
- **测试：**
  - 同一账号下两个会话的历史互不干扰，删除一个不影响另一个；
  - 在终端登录后，运行可用；
  - 两种模式下，网络变量都与升级前一致；
  - 隔离模式下，会话目录中不存在任何配置文件副本；
  - 原生模式下，用户配置文件的哈希不变，除非 CLI 自己写入（例如信任记录），这种情况要在文档中写明；
  - SSH 路径覆盖同样的情况。
- **验收：**
  - `grep -rnE "credential_session|_copy_credential|credential_lease|oauth_creds\.json" agentdock` 只剩迁移清理代码；
  - `codex_home.prepare`、`session_storage.prepare_claude`、`acp_home.prepare` 中不再出现上表中的任何文件名；
  - 代码中不再打开任何凭据文件或上述配置文件。

### C7　替换品牌图标

- **改动：**
  - 删除 `web/src/assets/providers/claude.svg`（在 `web/src/ProviderIcon.tsx:5` 被引用），改为纯文字或中性图标；
  - lobe-icons 的 MIT 许可只覆盖图标代码，不包含商标使用权；其他厂商的标志按各自规范处理，拿不准的同样改为中性图标；
  - 更新 README 和 `docs/images` 中带标志的截图。
- **验收：** 仓库中不再有 Claude 或 Anthropic 的标志文件，截图已更新。

### C5　文档写明合规边界

- **改动：**
  - README、ACCOUNTS、PROVIDERS 的中英文版本都新增"合规边界"一节：列出七条底线，并附官方链接；
  - 删除"自动切换""本机换号"等描述；
  - UPGRADING 写明哪些功能被删除，以及升级时的迁移行为。
- **验收：** 中英文结构一致；文档描述与代码行为一致。

### C8　降低自动化放大用量

- **改动：**
  - 项目中有 Claude Agent 时，"派工需人工确认"（`confirm_dispatch`，目前默认关闭）默认开启；
  - 文档提示：额度以普通个人使用为前提。
- **验收：** 新建项目的默认值正确；已有项目不受影响。

### 2.3.9 迁移总则（升级规则）

升级只在启动时执行一次，迁移脚本按 `user_version` 编号。整个迁移遵守三条：
- 不静默改变账号或计费身份；
- 不改变 CLI 原有的网络和代理设置；
- 不读取任何凭据内容。

#### 账号策略的升级规则（C3）

| 对象 | 规则 |
|---|---|
| Agent，策略为 `auto` 或 `failover` | 改为 `manual`。按以下优先级确定账号：<br>1. 已有的首选账号 `account_id`；<br>2. 该 Agent 最近一个会话当前使用的账号；<br>3. 账号池中第一个状态为可用的账号。<br>都没有时，标记为"需要选择账号"。**不得静默改为沿用设备登录**，因为那会改变计费身份 |
| 会话 | 保留当前分支（`account_branch`）绑定的账号，策略改为 `manual`，清空账号池；原生会话 ID 不变，可以继续续聊。没有绑定账号的会话，按上一行的规则确定账号或标记"需要选择账号" |
| 排队和运行中的任务 | 升级就是一次重启，按现有规则（`agentdock/store.py:134`）标为"中断"，不自动重放。`account_selection_pending`、`next_attempt_at` 等字段只作为历史保留。用户重新提交时，使用迁移后的固定账号 |
| 标记为"需要选择账号"的 Agent 或会话 | 不能运行；提交时提示用户选择一个托管账号，或明确选择"沿用设备登录" |
| 历史记录 | `run_attempts`、`session_account_branches` 保留，用于历史展示和用量归属；之后不再产生自动切换的记录 |
| 实验开关 | 从 metadata 的 `experimental_features` 中删除 `automatic_failover`、`native_switching`、`claude_quota`，只保留 `acp_agents` |
| 用户提示 | 升级后在账号页显示一次变更说明：哪些对象被改为固定账号，哪些需要选择账号 |

#### 凭据与配置的升级规则（C1、C2、C4）

| 对象 | 规则 |
|---|---|
| 会话目录中的凭据和配置副本 | 删除 C4 表中列出的所有文件（只删除，不读取）。保留原生会话记录（Claude transcript、Codex rollout），保证可以续聊 |
| 改为以账号目录运行的托管账号会话 | 把会话目录中的原生记录移到账号目录对应的位置，保持原生会话 ID 不变，然后删除会话目录中的副本。移动失败时保留原位置并标记"需要处理"，不能静默丢失历史 |
| `credential-leases/`，含 `conflicts` 归档 | 整个目录删除 |
| `accounts/native-clients/` 与钥匙串条目 `io.github.nginxl.AgentDock.snapshots` | 删除，见 C2 |
| 账号目录中的 `.pending-session.json` 恢复日志 | 删除 |
| 网络与代理 | 不迁移、不改写，运行时的来源保持不变 |

#### 迁移验收

准备一份迁移测试数据集，包含：
- `auto` / `failover` 策略的 Agent：有首选账号、没有首选账号、账号都不可用三种；
- 有多个账号分支的会话；
- 排队中的任务，包括正在等待冷却的；
- 带旧凭据和配置副本的会话目录；
- `credential-leases/` 和 `native-clients/` 目录。

升级后逐项检查：
1. 不存在 `auto` / `failover` 策略；
2. "需要选择账号"的对象被明确标记，且不能运行；
3. 原生会话 ID 不变，并且可以续聊；
4. 会话目录中不存在任何凭据或配置副本，按文件名清单检查；
5. 运行时的网络变量与升级前一致；
6. 用户原有配置文件的哈希不变。

## 2.4 阶段 1：稳定性与安全（S2–S9，约 1 周）

> 原 S1（冲突凭据归档清理）在 C4 完成后自然消失，已移除。

- **S2　行级增量同步**
  - sessions、messages、tasks 按 `updated_at > since` 返回，删除的记录通过 ID 列表下发。
  - 验收：在 300 个会话中改一个会话，增量响应小于 10 KB（目前约 211 KB）。
- **S3　诊断增强**
  - 在不记录原文的前提下，记录稳定的错误码（`PublicError.code`、`ProviderError.code`）。
  - 验收：诊断包中能看到错误码的分布。
- **S4　扩大检查范围**
  - 前端加 ESLint 并纳入 CI；
  - mypy 逐模块扩大覆盖，先做 `event_policy`、`deletions`、`state_sync`、`run_store`。
- **S5　真实验收**
  - 在可信机器上用 `scripts/live-e2e.py` 跑一遍：Codex、Claude 各两轮对话，再加派工、结果回传和任务验收；
  - 记录各 CLI 的版本；CLI 每次大版本更新后重跑。
- **S6　事件压缩移出全局锁**
  - 现状：`compact_run_events`（`agentdock/runtime.py:961`）在 `self._lock`（937 行）内执行，长任务结束时会短暂阻塞调度，以及其他运行的工具调用和审批。
  - 改为在锁外或后台线程执行。
- **S7　流式缓冲线程**
  - 现状：`StreamBuffer` 每个批次都新建一个 `threading.Timer`（`agentdock/stream_buffer.py:47`）。
  - 改为单个刷新线程，或在读循环里按时间刷新。
- **S8　本机管理接口防护**
  - 现状：`admin.token` 是同一系统用户可读的文件。Agent 只要能读到它并访问本机端口，就能调用审批等管理接口。
  - 建议：
    - 桌面版改为通过启动管道传递令牌，不写入文件；
    - 审批接口增加一个只存在于界面会话内的二次令牌；
    - 评估各 CLI 的沙箱是否允许访问回环地址。
- **S9　同一账号的首字节前重试（借鉴 Magpie）**
  - 只针对同一账号的临时网络错误：在没有任何输出、工具调用和审批之前，自动重试有限次数，并逐次加长等待；
  - 不切换账号，不重试服务商明确拒绝的请求（额度、认证）。
  - 验收：模拟连接失败时重试成功；有输出后失败则不重试；额度拒绝不重试。

## 2.5 阶段 2：借鉴 Magpie 的体验（M1–M7，约 3–4 周）

每项都要对照 2.1 的七条底线。

### M1　账号视图（参考 Magpie 的供应商页和账号池视图）

- **内容：** 每个账号显示：
  - 类型：订阅或 API 计费；
  - 登录状态；
  - 额度窗口与重置时间：Claude 来自运行事件，Codex 来自官方接口；
  - 请求数、Agent 实际看到的错误、最近的错误码；
  - 等待重置的剩余时间；
  - 正在使用这个账号的 Agent 和会话。
- **合规要点：** 只展示，不切换；不显示"改道""轮换"类指标；数据来自 `run_attempts` 表、运行记录和官方 CLI 输出。
- **验收：** 有账号、无数据、等待重置三种状态显示正确；"谁在用"的列表与实际绑定一致。

### M2　菜单栏面板与"方案"（参考 Magpie 的菜单栏和方案）

- **内容：**
  - 菜单栏按 Agent 显示当前模型、账号和运行状态，可以一键切换该 Agent 的默认模型；
  - "方案"预设一次切换一组 Agent 的模型、思考强度、权限和账号，由用户手动触发。
- **合规要点：**
  - 只改 AgentDock 自己的设置，运行时通过 `--model` 等官方参数传入，不改写原生 CLI 的全局配置；
  - 如果将来确实需要改写用户配置文件，按 Magpie 的做法：原子写入、只改必要项、保留注释和顺序。
- **验收：** 切换只影响之后的运行，排队和运行中的任务不受影响；原生配置文件的哈希不变。

### M3　按任务类型选模型（Magpie 意图路由的合规简化版）

- **内容：** 项目任务的讨论、执行、审查，分别配置默认模型和思考强度。
- **合规要点：** 直接用已知的任务类型，不调用额外模型给每轮内容分类，也就不会把内容多发给一家服务商。
- **验收：** 新建对应类型的会话时自动带上预设，用户可以覆盖；覆盖后不再被预设改回。

### M4　API 计费账号（Magpie 供应商的合规替代）

- **内容：**
  - 用户在终端用官方命令登录 API 计费账号（`claude auth login --console`、`codex login --with-api-key`），AgentDock 识别计费类型并在界面上标注；
  - 订阅额度用完时，提示用户二选一：等待重置，或手动把这个 Agent 切到自己的 API 计费账号。
- **合规要点：** AgentDock 不保存任何密钥，凭据存在官方 CLI 自己的存储中；只在用户本人名下的账号之间由用户手动切换。
- **验收：** 能识别两种计费类型；额度用完时出现提示，且不会自动切换。

### M5　额度与节奏提示（参考 Magpie 的用量统计和周额度节奏）

- **内容：**
  - Claude 从运行中的 `rate_limit_event` 被动获取额度；
  - Codex 用 app-server 的官方接口读取，并限制频率（参考 Magpie：启动后读一次；打开额度页时最多 30 秒一次；其余时间 5–15 分钟随机一次）；
  - 显示"按当前速度，重置前预计用到 X%"。
- **合规要点：** 只做展示，不据此自动调度。
- **验收：** 读取频率符合上限；没有数据时显示未知；节奏估算有单元测试。

### M6　用量统计增强（参考 Magpie 按 Agent、模型统计）

- **内容：**
  - 按 Agent、模型统计 token 和缓存命中率；
  - API 计费账号按可配置的单价表估算费用，并标明"估算，不是账单"；
  - 订阅账号只显示 token。
- **验收：** 统计口径与现有 token 记录一致；单价表可以配置；没有单价时不显示费用。

### M7　命令行与 TUI（参考 Magpie 的 CLI 和 TUI）

- **内容：**
  - 增加 `agentdock status`、`agentdock send <agent> <text>`、`agentdock tasks`、`agentdock accounts`，复用现有 API 和令牌；
  - TUI 可选。
- **验收：** 命令输出稳定，可用于脚本；令牌不出现在命令行参数和日志中。

## 2.6 阶段 3：分发与工程（D1–D4）

- **D1　自动更新（参考 Magpie）：** 后台检查更新源并下载，校验签名后在下次启动时安装。
- **D2　多平台：**
  - Linux 提供桌面安装包，或者至少提供 wheel 加 systemd 用户服务的说明；
  - Windows 依赖 POSIX 能力（`fcntl`、`pty`、进程组），暂不支持，可以通过 WSL 使用。
- **D3　文档（参考 Magpie）：**
  - 集中参考文档：接口、文件位置、环境变量、行为规则；
  - LESSONS.md，记录这几轮 review 的经验：
    - 截断只在累计超限时持续生效；
    - 删除时先预检、再打标记；
    - 错误码跟着异常类型走；
    - 增量同步不返回大字段；
    - 不读取任何凭据；
  - AGENTS.md / CLAUDE.md：开发约定、检查命令、七条底线。
- **D4　分发前合规确认：**
  - 对外分发安装包前，就"在产品中运行 Claude Code 是否需要另行同意商业条款"咨询 Anthropic；
  - 继续不捆绑 Claude Code，不用 Anthropic 的名称或标志作为产品名称、标志。

## 2.7 明确不做的事

- 把任何订阅变成供应商或网关，提供给其他 Agent、工具或其他人使用。
- 在多个订阅账号之间做智能路由、轮流使用或故障转移。
- 读取、刷新、写回任何客户端的 OAuth token；解密客户端的本地存储。
- 任何规避服务商识别的设计。
- 协议转换网关，让一个 CLI 使用另一家的模型。
- 用额外的模型给每一轮内容分类。
- 插件系统（暂不做）。

## 2.8 里程碑与依赖

| 周次 | 内容 | 产出 |
|---|---|---|
| 第 1 周 | C1、C3、C2 | 去掉 token 直连、自动切换和本机换号 |
| 第 2 周 | C6、C4、C7、C5、C8 | 登录交还 CLI、不再复制凭据、替换图标、补文档、调整默认值 |
| 第 3 周 | S2–S9 | 行级同步、扩大检查范围、真实验收、本机防护、首字节前重试 |
| 第 4–5 周 | M1、M4、M5 | 账号视图、API 计费账号、额度与节奏提示 |
| 第 6–7 周 | M2、M3、M6 | 菜单栏与方案、按任务类型选模型、用量统计 |
| 之后 | M7、D1–D4 | 命令行、自动更新、多平台、文档、分发确认 |

**依赖关系：**
- C1、C2 完成后，钥匙串访问和 Swift 凭据代理可以整体删除。
- C4 依赖 C3（账号模型更简单）和 C6（登录方式确定）。
- M1 依赖 C3，M4 依赖 C6，M5 依赖 C1。
- C5 在阶段 0 的最后写，描述的是最终状态。

## 2.9 协作与 review

### 开发约定

- **提交：** 一项一个提交（或一个 PR），提交信息带上计划编号，例如 `C1: …`。
- **提交前在本机跑这些检查：**

```bash
python3 -m unittest discover -s tests
npm --prefix web test
npm --prefix web run build
ruff check agentdock
ruff format --check agentdock tests scripts setup.py
mypy
```

- **涉及 Swift 时：** 另外运行 `swift build --package-path native -c release` 和各项 `swift run … Checks`。
- **完成标准：** 验收标准全部满足；有对应的测试；中英文文档同步；CHANGELOG 有记录；没有新增规范检查错误；对照七条底线没有违反。

### Review 方式

- **你：** 每批完成后，发来提交范围、对应的计划编号，以及已经跑过的检查。
- **reviewer 会做这些事：**
  - 对照该项的验收标准逐条检查；
  - 跑全量检查；
  - 运行该项的 grep 断言；
  - 针对改动写复现脚本；
  - 对照七条底线检查；
  - 结果用文字列出：问题、位置、复现方式、修复方向。

### 状态表

| 编号 | 状态 | 提交 | review 结论 |
|---|---|---|---|
| C1 | 已完成，本地验证通过 | `C1: Replace Claude OAuth queries with passive CLI quota observations` | 待复核 |
| C3 | 待开始 | | |
| C2 | 待开始 | | |
| C6 | 待开始 | | |
| C4 | 待开始 | | |
| C7 | 待开始 | | |
| C5 | 待开始 | | |
| C8 | 待开始 | | |
| S2–S9 | 待开始 | | |
| M1–M7 | 待开始 | | |
| D1–D4 | 待开始 | | |

---

# 附录 A　三轮审查明细

## A.1 第一轮：整体审查（2026-10-08，基线 `f2171af`）

| # | 问题 | 当前状态 |
|---|---|---|
| 1 | 本机换号把钥匙串里的凭据存成 base64 明文文件 | 结论已调整：删除功能（C2） |
| 2 | 钥匙串授权落在通用 Python 解释器上 | 结论已调整：不访问钥匙串（C1、C2） |
| 3 | 多账号自动切换有条款风险；直接调用非公开额度接口 | 结论已调整：删除自动切换和直连（C1、C3） |
| 4 | ACP 凭据按会话复制；Codex 凭据符号链接在刷新时可能失效 | 结论已调整：完全不复制（C4） |
| 5 | 长任务被硬上限整轮杀掉 | 已修复 |
| 6 | 删除时在数据库事务内做网络 IO | 已修复 |
| 7 | 取消查询缺索引，耗时平方级增长 | 已修复（2 万条记录：15.7 s → 21 ms） |
| 8 | 换号交接只读得到会话前 500 个事件 | 已修复 |
| 9 | 完全没有日志 | 已修复；S3 继续增强 |
| 10 | 前端轮询全量状态 | 已修复；S2 做行级增量 |
| 11 | SQLite 单连接全局锁、迁移无版本号、事件无清理 | 已修复 |
| 12 | 用量扫描每 10 秒全量读盘 | 已修复 |
| 13 | 按服务分支的逻辑散落各处 | 部分完成：协议层已拆分 |
| 14 | 本机、远端两套执行路径 | 已修复 |
| 15 | 上帝对象、手写路由 | 已修复 |
| 16 | 代码规范和错误约定 | 已修复；S4 扩大检查范围 |
| 17 | 前端组件过大 | 已修复 |
| 18 | 版本号分散；仍在 Python 3.9 | 已修复 |
| 19 | 发布门槛高，端口写死 | 已修复；补充 D4 |
| 20 | 缺少真实 CLI 验收 | 部分完成；S5 |
| 21 | 协作细节：历史分页、派工无人确认、记忆检索 | 已修复；C8 调整默认值 |
| 22 | 功能铺得太开，文档太长 | 结论已调整：本机换号删除；C5 补合规边界 |

## A.2 第二轮：整改提交审查（2026-10-09，`f2171af..c183c5a`）

| # | 位置 | 问题 | 修复提交 | 状态 |
|---|---|---|---|---|
| 1 | `.github/workflows/live-e2e.yml` | 公开仓库挂着存有真实登录的自托管 runner | `b41a247` | 已修复；runner 是否注销需人工确认 |
| 2 | `agentdock/credential_lease.py` | 原始凭据被外部刷新后，ACP 服务被永久锁死 | `89009fc` | 已修复，被 C4 取代 |
| 3 | `agentdock/providers.py` | 同一 ACP 服务并发运行 30 秒后失败、不排队 | `3c38d56` | 已修复，被 C4 取代 |
| 4 | `agentdock/message_store.py` | "删除中"的会话被选为默认派工目标 | `e01c0de` | 已修复 |
| 5 | `agentdock/server.py` | 账号错误被吞成 "Invalid request" | `8966dce` | 已修复 |
| 6 | `agentdock/deletions.py` | 删除被拒绝后，会话仍被标成删除中 | `e01c0de` | 已修复 |
| 7 | `agentdock/ssh_worker.py` | 远端截断白名单把 `token_usage` 写成了 `usage` | `985bd97` | 已修复 |
| 8 | `agentdock/native_accounts.py` | 换号期间查状态报错；损坏的快照会阻断启动 | `8966dce` | 已修复，被 C2 取代 |
| 9 | `agentdock/state_sync.py` | 增量同步每次都带上 300 条事件（实测 6 MB） | `eaa4394` | 已修复 |
| 10 | `agentdock/runtime.py` | 两层截断方向相反，长回复的结尾被丢掉 | `e4d7163` | 已修复 |

## A.3 第三轮：修复引入的回归（`c183c5a..8d541ac`）

| # | 位置 | 问题 | 修复提交 | 状态 |
|---|---|---|---|---|
| A | `runtime.py`、`ssh_worker.py` | 出现一个 128–256 KB 的普通事件后，本轮后面的进度全部消失 | `7c786f8` | 已修复 |
| B | `runtime.py`、`event_store.py` | 接近 120 KB、转义多的最终回复超出事件大小上限，运行被记为失败 | `5bfb7b7` | 已修复 |

## A.4 验证记录

| 提交 | 后端测试 | 前端测试 | 其他 |
|---|---|---|---|
| `f2171af`（基线） | 389（Python 3.9） | 213 | 构建 |
| `c183c5a` | 430（Python 3.13） | 216 | 构建、ruff、format、mypy |
| `8d541ac` | 457 | 221 | 同上 |
| `f00da1a` | 465 | 221 | 同上；全部复现脚本通过 |
| C1：Claude 被动额度 | 470（Python 3.13） | 225 | 生产构建、ruff、format、mypy、Swift release 构建及四组 Swift 检查通过 |

C1 验证覆盖：本机／SSH 托管账号与设备登录的额度事件、缺失和异常数值、旧登录版本事件拒绝、刷新不启动 CLI 或改变采样时间、第 14 号迁移的历史值／时间保留与重复启动、Claude 本机换号入口拒绝。源码中 C1 指定的凭据字段及接口地址检索结果为空。代理继承测试确认白名单、既有优先级和源配置不变。

C1 的 CLI 输入来自协议模拟；真实 Claude 限额事件与官方用量页核对仍待 S5 验收。C2–C8 的删除及迁移要求尚未完成。

---

# 附录 B　参考资料

- Claude Code — Legal and compliance：<https://code.claude.com/docs/en/legal-and-compliance>
- Codex App Server：<https://developers.openai.com/codex/app-server>
- OpenAI — Using your ChatGPT plan in other apps and sites：<https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites>（无法直接打开，内容来自搜索摘要）
- ConductAtlas — OpenAI Terms of Use 条款记录：<https://conductatlas.com/platform/openai/openai-terms-of-use/provision/CA-P-078688/no-interference-with-or-disruption-of-services/>
- magpie 官网：<https://usemagpie.ai/zh/>
- magpie 源码：<https://github.com/yetone/magpie>
- magpie 参考文档：<https://github.com/yetone/magpie/blob/main/docs/reference.md>
- 本仓库：`docs/REVIEW-FOLLOWUP.md`、`docs/REMEDIATION.md`
