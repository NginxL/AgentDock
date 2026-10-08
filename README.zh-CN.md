<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="AgentDock 图标" /></p>
<h1 align="center">AgentDock</h1>
<p align="center">原生 Agent 会话、项目协作与交付验收。</p>

[English](README.md) · **简体中文** · [自动检查](https://github.com/NginxL/AgentDock/actions/workflows/check.yml)

AgentDock 是本地单用户的 Agent CLI 工作台，连接本机或 SSH 设备上的 Codex、Claude Code。保留原生会话，将项目工作派给其他 Agent，把结果送回发起会话，再按验收标准检查交付。项目中的角色、会话和已审核记忆与日常对话分别保存。

![工作台，展示虚构演示数据](docs/images/workspace.zh-CN.jpg)

**开发预览版。** 后端使用 Python 标准库与 SQLite，界面使用 React，macOS 外壳使用 Swift。更多 ACP Agent、自动换号、本机客户端换号及非公开 Claude 额度查询有各自的实验开关，默认关闭。见[功能边界](docs/EXPERIMENTS.md)。

## 快速开始

源码开发需要 Python **3.11+**、Node.js **20.19+**，以及已安装并登录的 Agent CLI。SSH 设备也需要 Python 3.11+。继续沿用对应 CLI 的现有网络配置。

```bash
git clone https://github.com/NginxL/AgentDock.git
cd AgentDock
python3 -m venv .venv
npm --prefix web ci --ignore-scripts
npm --prefix web run build
.venv/bin/python -m agentdock
```

打开终端显示的本机网址，从提示的本地文件读取令牌。端口自动分配，默认以只读审阅模式启动；添加 `--enable-execution` 才能运行 Agent。数据位于 `~/.local/share/agentdock`。手动选择的项目目录共用，会话记录分别隔离。

macOS 源码安装运行 `.venv/bin/python scripts/install-macos.py`，需要 macOS 14+ 和 Apple Command Line Tools。分发版应用内置 Python；Python 安装包内含前端及 `agentdock` 启动命令。见[构建与安装包](docs/DISTRIBUTION.md)；正式签名和苹果公证需要维护者提供发布凭据。

## 文档

- [使用指南](docs/USER_GUIDE.zh-CN.md)：会话、设置、模型、删除和用量。
- [项目任务](docs/TASKS.zh-CN.md)、[账号](docs/ACCOUNTS.zh-CN.md)、[服务](docs/PROVIDERS.zh-CN.md)、[SSH](docs/SSH.zh-CN.md)。
- [架构](docs/ARCHITECTURE.zh-CN.md)、[接口](docs/API.zh-CN.md)、[凭据保护](docs/CREDENTIALS.md)。
- [审查整改与测量](docs/REMEDIATION.md)、[验证记录](docs/REVIEW.zh-CN.md)、[变更记录](CHANGELOG.md)。
- [可选真实 CLI 验证](docs/DISTRIBUTION.md#live-cli-verification)：需专用设备和显式开启，默认不运行。

## 开发检查

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
./scripts/check.sh
.venv/bin/ruff check agentdock
.venv/bin/ruff format --check agentdock tests scripts setup.py
.venv/bin/mypy
```

常规测试使用模拟 CLI 和临时数据，不切换真实账号、不发送模型请求。[反馈问题](https://github.com/NginxL/AgentDock/issues)时可附脱敏复现步骤和诊断错误 ID。

[MIT 许可](LICENSE) · [第三方声明](NOTICE.zh-CN.md)。AgentDock 独立于各 CLI 提供方；订阅及服务条款仍然适用。
