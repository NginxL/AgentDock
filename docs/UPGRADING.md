# Upgrade notes / 升级说明

## C1: Claude quota from runs / Claude 运行额度

Migration 14 removes `claude_quota` from saved feature settings and keeps historical Claude quota values and sample timestamps under `source: legacy_snapshot`. New observations use `source: cli_event`. Unknown values stay unknown; opening or refreshing the page does not launch Claude, an SSH quota probe, or a provider request. Identity checks still use the official CLI. Existing proxy and certificate sources remain unchanged. Claude native switching no longer offers capture, switch or recovery; use the official client. Removal and cleanup of all native snapshots belongs to C2 in the [development plan](DEVELOPMENT-PLAN.md).

第 14 号迁移删除已保存的 `claude_quota` 开关，保留历史 Claude 额度及采样时间，并标记为 `source: legacy_snapshot`；新的运行采样为 `source: cli_event`。未知值仍显示未知，打开或刷新页面不会启动 Claude、SSH 额度探测或服务商请求。身份检查继续调用官方 CLI；代理和证书来源保持不变。Claude 本机换号不再提供保存、切换、恢复，请使用官方客户端；全部原生快照的删除清理由[开发计划](DEVELOPMENT-PLAN.md) C2 处理。

## Python on local and SSH devices / 本机与远端 Python

The service and SSH worker require **Python 3.11+**. A bundled macOS build includes a compatible interpreter; a source install and each SSH device need their own compatible Python. Ubuntu 22.04 commonly defaults to Python 3.10 and RHEL 9 to 3.9, so their default `python3` may fail the connection check. Install a separate supported interpreter and select its command or absolute path in **Agent settings → Advanced connection settings → Remote Python**. Do not replace the operating system's Python. See [SSH setup](SSH.md).

服务和 SSH 执行端均要求 **Python 3.11+**。macOS 分发版自带兼容运行时；源码安装及每台 SSH 设备仍需兼容 Python。Ubuntu 22.04 常见默认版本为 3.10，RHEL 9 为 3.9，直接使用其 `python3` 会无法连接。请独立安装兼容版本，并在 **Agent 设置 → 高级连接设置 → 远端 Python**填写命令名或绝对路径；保留操作系统自带 Python。见 [SSH 配置](SSH.zh-CN.md)。

## Existing agents and accounts / 已有 Agent 与账号

Additional ACP agents, automatic failover and Codex native-client account switching each have a default-off experiment switch. This also applies when an old database first receives those switches. Existing Trae and other ACP agents retain their settings and history, but cannot execute until **Accounts → Experimental features → Additional agents** is enabled with acknowledgement. Previously selected automatic account policies also remain gated. Later upgrades retain already saved feature choices. See [experiment boundaries](EXPERIMENTS.md).

更多 ACP Agent、自动换号、Codex 本机客户端换号分别受默认关闭的实验开关控制；旧数据库首次迁移到这些开关时也默认关闭。已有 Trae 等 ACP Agent 的配置和历史保留，但需要在 **账号 → 实验功能 → 更多 Agent**中确认并开启后才能继续运行。旧自动换号策略同样受开关约束；之后的升级保留已保存的开关选择。见[功能边界](EXPERIMENTS.md)。

CLI network settings remain authoritative. This upgrade does not introduce a per-account proxy or rewrite existing proxy configuration. Native snapshot migration requires the protected desktop credential channel; a malformed snapshot is retained and logged without blocking normal service startup. Status queries neither decrypt snapshots nor change native logins.

网络仍沿用对应 CLI 的配置，不新增按账号配置的代理，不改写现有代理设置。原生快照迁移需要桌面受保护的凭据通道；损坏的快照保留并记录诊断，不阻断普通服务启动。查询状态不解密快照、不改变原生登录。

## Diagnostics and verification / 诊断与验证范围

Diagnostic exports contain error IDs, exception types and source frame locations, not exception messages, prompts, tokens or credentials. Reproductions and the visible error code may still be needed to diagnose failures. Ruff checks backend code; formatting covers backend, tests and scripts. Strict mypy currently covers `errors.py`, `text_buffer.py` and `turn.py`; frontend validation uses TypeScript, Vitest and the production build, with no ESLint gate yet.

诊断包包含错误 ID、异常类型和调用栈位置，不含异常原文、提示词、令牌或凭据。排查可能仍需复现步骤和界面错误码。Ruff 检查后端源码，格式检查覆盖后端、测试和脚本；严格 mypy 当前覆盖 `errors.py`、`text_buffer.py`、`turn.py` 三个模块。前端使用 TypeScript、Vitest 和生产构建验证，尚无 ESLint 检查。

Public-repository CI must not have access to a runner containing real CLI logins. Previously registered credential-bearing runners require removal from repository or organization settings. The source workflow removal does not unregister a machine. See [live verification boundaries](DISTRIBUTION.md#live-cli-verification).

公开仓库 CI 不能接入存有真实 CLI 登录的 runner。曾登记的此类 runner 需要从仓库或组织设置撤销；删除源码工作流不会自动取消机器注册。见[真实验证边界](DISTRIBUTION.md#live-cli-verification)。
