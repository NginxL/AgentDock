# Agent CLI 支持

[English](PROVIDERS.md) · **简体中文** · [项目首页](../README.zh-CN.md)

添加 Agent 时先选择设备，再选择已安装的服务。列表展示品牌图标，缺少 CLI 或适配器的条目显示为不可用。检测只查找可执行文件，不提交模型请求，也不安装软件。本机安装完成后可在服务菜单中刷新；远端安装后点击“连接 / 检查”更新该设备的检测结果。

## CLI 入口

以下命令需要在所选设备上可用。Codex、Claude Code 保留各自原生通信方式；其他服务通过标准输入输出使用 ACP v1。

| 服务 / 配置标识 | 默认命令 | 要求 / 来源 |
| --- | --- | --- |
| Codex / `codex` | `codex app-server` | [Codex App Server](https://developers.openai.com/codex/app-server/) |
| Claude Code / `claude` | `claude` | [流式 CLI](https://code.claude.com/docs/en/cli-reference) |
| Trae CLI / `trae` | `traecli acp` | [命令参考](https://docs.trae.cn/cli_command-line-parameters)；通过本机帮助信息识别旧版本并改用 `acp serve`。 |
| Pi / `pi` | `pi-acp` | 同时安装 [Pi](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) 和独立的 [pi-acp 适配器](https://github.com/svkozak/pi-acp)。 |
| Cursor CLI / `cursor` | `cursor-agent acp` 或 `agent acp` | [Cursor ACP](https://cursor.com/docs/cli/acp) |
| Antigravity / `antigravity` | `agy_acp_server.par` | 需要 [ACP 服务程序](https://github.com/agentclientprotocol/registry/blob/main/antigravity-acp/agent.json)，仅安装桌面版或 `agy` 命令不够。 |
| Grok Build / `grok` | `grok --no-auto-update agent stdio` | [无界面 CLI](https://docs.x.ai/build/cli/headless-scripting) |
| OpenCode / `opencode` | `opencode acp` | [ACP 集成](https://opencode.ai/docs/acp/) |
| Gemini CLI / `gemini` | `gemini --acp` | [ACP 注册表](https://github.com/agentclientprotocol/registry/blob/main/gemini/agent.json) |
| Qwen Code / `qwen` | `qwen --acp` | [ACP 注册表](https://github.com/agentclientprotocol/registry/blob/main/qwen-code/agent.json) |

检测到命令不代表账号、模型或协议已验证。首次调用时再核对这些能力；使用前应先在对应设备的 CLI 中登录。ACP 适配器的版本和登录格式可能与桌面客户端不同。PiCode 不作为独立服务列出：已确认的 [PiCode 桌面项目](https://github.com/Davidcreador/pi-code) 底层使用 Pi。

## 会话、模型与权限

ACP 初始化读取能力、模型及推理选项，不发送提示词。每个会话创建自己的原生会话；后续轮次按服务声明的能力使用 `session/resume` 或 `session/load`。不支持续聊时明确报错，不会悄悄新建会话。加载时回放的旧消息不会重复写入 AgentDock。

客户端公开的思考内容、进展、工具调用和最终文本沿用统一会话界面。等待回复时展开过程，最终回复到达后收起。模型及推理等级来自 CLI；不支持的选项会在发送任务前被拒绝。取消操作通知原生会话并结束本次运行所属的进程组。

**需要时询问**将 CLI 提供的权限选项交给用户选择；**完全访问**会自动选择唯一、明确的单次允许选项，存在多个正向选项的提问仍需用户回答。实际工具权限及沙箱策略由 CLI 和操作系统执行。AgentDock 不向 ACP 服务声明客户端文件操作或终端执行能力。

Pi 的适配器不拦截普通工具执行，因此需要用户明确选择**完全访问**。该适配器接收但尚未向 Pi 转发 MCP 配置：可以接收任务、读取任务提示词中提供的已审阅记忆；通过 AgentDock MCP 工具主动派工和提出记忆更新暂不可用。详见[适配器限制](https://github.com/svkozak/pi-acp#limitations)。

## 文件与凭据

每个 ACP 会话在实际运行设备上拥有独立的 `sessions/<session-id>/<provider>` 目录。HOME、XDG 目录和已知的服务专用状态变量指向此处。首次创建时复制选定的设置及文件凭据，不导入原生历史。副本仅允许当前用户读写，删除会话时一并清理；原有服务设置不会被覆盖。子进程保留代理及 API 认证环境变量。

各 CLI 的配置和 OAuth 格式不同。支持范围之外的凭据文件、系统凭据存储，以及显式指定其他存储位置的设置，需要单独验证兼容性。Antigravity 的凭据文件位置尚未确认，因此不自动复制其凭据文件；可通过下述可信启动器提供所需认证，同时保留私有状态目录。认证失败会终止运行，不会自动打开登录流程或切换账号。

手动指定的项目目录保持共用；留空的工作目录在每个会话目录内独立创建。SSH Agent 在远端复用同一注册表和 ACP 客户端；AgentDock 不在远端安装 Agent CLI，也不修改原生 CLI 或 SSH 配置。

## 自定义启动器

本机服务配置中的 `commands` 只覆盖指定条目，其余服务仍自动发现。macOS 应用使用 `~/.local/share/agentdock/config.json`。命令必须是参数数组，不是 shell 字符串：

```json
{"commands":{"gemini":["/absolute/path/to/gemini","--acp"],"pi":["/absolute/path/to/pi-acp"]}}
```

远端可在私有文件 `~/.local/share/agentdock/ssh/commands.json` 中填写服务标识到参数数组的映射，修改后重新连接。启动器需保留 AgentDock 设置的私有 HOME/XDG 环境，标准输出仅写 ACP 消息，诊断信息写标准错误。

## 用量与验证范围

额度读取仍针对 Codex 和 Claude；其他服务显示额度未知，不会借用其他服务的数据。ACP 上下文占用不是累计 Token 消耗，不参与累计用量或 TPS。运行中没有输出 Token 样本时，吞吐显示未知。

离线测试使用确定性协议模拟进程，覆盖全部 ACP 服务条目的模型配置、两轮续聊、流式阶段、权限选项、取消、异常消息、私有存储和删除。独立 SSH worker 测试覆盖检测、模型读取和连续对话，不连接生产环境。本机 Trae 已通过模型读取及真实两轮对话，原有配置文件校验值未变。Codex 和 Claude 的实机验证见[验证说明](REVIEW.zh-CN.md)。其余 ACP 服务已通过协议模拟测试；真实账号、认证和工具执行兼容性待验证。

命令依据官方 CLI 资料及 [ACP Registry `01f372c` 版本](https://github.com/agentclientprotocol/registry/tree/01f372c271a2344ec944dd36f6305b20171a7e1d) 于 2026-09-29 核对。通信行为依据 ACP 的[会话设置](https://agentclientprotocol.com/protocol/v1/session-setup)、[对话轮次](https://agentclientprotocol.com/protocol/v1/prompt-turn)和[配置选项](https://agentclientprotocol.com/protocol/v1/session-config-options)。
