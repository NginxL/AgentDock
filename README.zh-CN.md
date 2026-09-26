<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="AgentDock 标志" /></p>
<h1 align="center">AgentDock</h1>
<p align="center">原生会话，任务协作，一个清晰的工作台。</p>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>
<p align="center"><a href="https://github.com/NginxL/AgentDock/actions/workflows/check.yml"><img src="https://github.com/NginxL/AgentDock/actions/workflows/check.yml/badge.svg" alt="自动检查" /></a> <img src="https://img.shields.io/badge/version-0.2_preview-6366f1" alt="0.2 预览版" /> <img src="https://img.shields.io/badge/Python-3.9%2B-3776ab" alt="Python 3.9 及以上" /> <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-187c68" alt="MIT 许可证" /></a></p>

AgentDock 将 Codex 和 Claude Code 接入同一个本地工作台，管理会话、任务交接、项目共享记忆与可用额度。智能体通过原生 CLI 执行，后续对话沿用各自的原生会话。发送给同伴的任务会进入执行队列，结果自动回到发起任务的会话。

界面默认中文，支持完整切换为英文。后端采用 Python 标准库与 SQLite，前端使用 React。

> **开发者预览版。** 默认关闭执行。自动检查已覆盖模拟原生 CLI 协议和任务交接；真实模型调用与账号兼容性仍需验收。

[架构设计](docs/ARCHITECTURE.zh-CN.md) · [接口说明](docs/API.zh-CN.md) · [验证与兼容性](docs/REVIEW.zh-CN.md) · [反馈问题](https://github.com/NginxL/AgentDock/issues)

## 工作台

![AgentDock 中文工作台，展示原生会话、任务状态与额度](docs/images/workspace.zh-CN.png)

*离线演示模式下的实际界面截图。图中的项目、对话和额度均为虚构数据。*

<details>
<summary>查看任务派工与额度界面</summary>

**任务派工：**查看目标会话、执行结果与回传状态。

![任务派工与结果回传界面](docs/images/dispatch.zh-CN.png)

**额度与订阅：**额度窗口及重置时间与订阅续费记录分开展示。图中数值均为虚构演示数据。

![Codex 和 Claude 额度及订阅界面](docs/images/usage.zh-CN.png)

</details>

## 功能

| 能力 | 说明 |
| --- | --- |
| 原生会话 | 调用已安装的 Codex 或 Claude Code CLI，保存原生会话 ID，后续轮次继续原会话；展示流式输出与权限请求。 |
| 任务交接 | 向指定智能体和会话派工；工作目录繁忙时自动排队，任务完成或失败后将结果送回发起会话；记录执行、去重、取消与回传任务。 |
| 共享记忆 | 项目知识与私有对话分开管理；支持来源、版本、关键词检索、智能体提议审核和归档历史。 |
| 额度与订阅 | 接入 [AgentMeter](https://github.com/NginxL/AgentMeter)，展示 Codex／Claude 剩余额度、重置时间及过期或错误状态；续费日期与订阅费用单独记录。 |
| 本地工作台 | 紧凑项目导航、会话与执行记录面板、中英文切换，以及不发送接口请求的只读演示。 |

## 快速开始

需要 macOS 或 Linux、Python 3.9+、Node.js 20.19+ 和 npm。执行任务还需要单独安装兼容的 Codex 或 Claude Code CLI，并完成其正常本地登录配置。AgentMeter 为可选组件。

```bash
git clone https://github.com/NginxL/AgentDock.git
cd AgentDock
npm --prefix web ci --ignore-scripts
npm --prefix web run build
cp config.example.json config.local.json
python3 -m agentdock --config config.local.json
```

打开终端显示的本机地址，读取终端提示的本地令牌文件并输入令牌。默认地址为 `http://127.0.0.1:47831`。令牌仅保存在界面内存中，不放入网址或浏览器本地存储。地址加上 `?demo=1` 可查看虚构数据，演示模式不执行任务、不请求接口。

工作台默认处于**评审模式**。创建项目、查看已有数据不会启动智能体或读取额度。准备就绪后，可显式开启执行：

```bash
python3 -m agentdock --config config.local.json --enable-execution
```

选择可信项目目录，创建智能体并提交任务。开启执行期间，同伴派工和结果回传轮次会自动执行；额度刷新仍需手动触发。

## 配置

[`config.example.json`](config.example.json) 包含全部公开配置项：

```json
{
  "commands": {
    "codex": ["codex", "app-server"],
    "claude": ["claude"]
  },
  "agentmeter_command": ["/Applications/AgentMeter.app/Contents/MacOS/AgentMeter"]
}
```

如果服务的 `PATH` 中没有相应 CLI，请使用可执行文件的绝对路径。机器专属配置保存在 Git 忽略的 `config.local.json` 中。界面和智能体均不能指定执行命令。

AgentDock 使用 Codex App Server 与 Claude CLI 的双向 JSON 流，不使用 Claude Agent SDK、不要求新增 API Key，也不读取提供方的凭据存储。登录、模型选择、账号资格和费用由原生 CLI 及其配置的服务决定。展示额度不等于授予执行权限。详见[兼容性与验证](docs/REVIEW.zh-CN.md)。

## 协作流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as Codex 会话
    participant D as AgentDock 调度器
    participant A as Claude Code 会话
    U->>C: 分析需求并安排实现
    C->>D: 提交目标明确、含上下文的任务
    D-->>C: 返回排队任务 ID
    Note over C: 结束当前轮次
    D->>A: 创建或恢复会话并执行
    A-->>D: 返回结果或失败原因
    D->>C: 恢复发起会话并送达结果
    C-->>U: 审阅结果并完成任务
```

同一智能体的会话，以及使用相同或父子目录的任务，按顺序执行；独立工作目录可以并行。每条协作链最多包含 16 个执行任务，派工深度最多三层。取消任务会同时取消其后续派生任务。应用重启将未完成任务标记为中断，不自动重放。

## 数据与边界

状态保存在 `~/.local/share/agentdock`，同一数据库只允许一个实例占用。历史、任务记录和共享记忆存储在本地。执行智能体会将任务上下文发送到其配置的模型服务；刷新额度也可能访问提供方服务。

当前版本管理**由 AgentDock 创建的会话**，尚未接入已有桌面或终端会话、远程设备及多用户访问。提供方权限请求会显示在界面中；工作台本身不提供操作系统沙箱。凭据仍由原生 CLI 和 AgentMeter 管理，每次执行的 MCP 令牌会过期，并在执行结束后撤销。

从 0.1 升级时，需要将 ACP 命令改为上述原生命令。历史消息保留为旧版记录，不会自动派发。尚无原生绑定的会话会建立新的提供方会话，旧存储文本不会被静默重放为原生历史。

## 开发与贡献

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q agentdock tests
npm --prefix web test
npm --prefix web run build
```

测试使用临时数据库、模拟 CLI 进程和虚构界面数据，不调用真实编码智能体或额度服务。[验证文档](docs/REVIEW.zh-CN.md)列出了覆盖范围与真实环境待验收项。提交问题时请附脱敏复现步骤，并保持中英文文档一致。

## 许可证

采用 [MIT 许可证](LICENSE)。外部 CLI 与 AgentMeter 需要单独安装，适用各自的许可证和服务条款，详见[声明](NOTICE.zh-CN.md)。

---

[English](README.md) · **简体中文**
