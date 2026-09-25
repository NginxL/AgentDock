# Review brief / 评审说明

## Decision summary / 决策摘要

独立实现 AgentDock，本地 React UI + Python 标准库服务 + SQLite。ACP 管理 Codex / Claude 适配器会话；MCP 提供项目邮箱和记忆工具；AgentMeter 通过只读 `--probe` 复用。名称不绑定某个模型厂商，原 AgentMeter 保持独立。

选择依据：AionUi 的 ACP / Team MCP 分层、Agor 的受控知识条目和 AO 的工作区隔离都贴近目标，但已核实的文档不足以证明存在完全覆盖全部需求的现成方案。比较和认证边界见[中文调研](RESEARCH.zh-CN.md) / [English research](RESEARCH.md)。没有复制这些项目的代码。

## Implementation status / 实现状态

| 领域 | 已实现 | 待实机验收 / 后续决策 |
| --- | --- | --- |
| UI | 中英切换、项目/角色/会话、任务事件、运行与取消入口、权限审批。 | 未启动应用或浏览器验收；当前图片为标记的设计示意。 |
| Agent 接入 | ACP v1 stdio、初始化/会话/prompt/更新/权限/取消；服务端命令配置。 | 真实 codex-acp、claude-agent-acp 版本与账号兼容性。 |
| 互通 | 同项目身份绑定邮箱、去重、确认；6 个 MCP 工具。 | 真实模型是否按任务调用工具；自动唤醒/自动团队循环未实现。 |
| 记忆 | 项目隔离、关键词检索、版本冲突、Agent 提议/人工批准、软归档及数据库历史。 | 向量语义检索、自动提取、UI 完整版本浏览、跨项目共享未实现。 |
| 额度 | AgentMeter 固定 provider 探测、超时/限流、未知/过期/错误；手动账期。 | 真实登录、钥匙串提示、实际刷新；不承诺所有账号或提供商接口长期可用。 |
| 生命周期 | 进程组取消、审批过期、工作目录重叠互斥、数据库单实例锁、重启不重放。 | 操作系统级沙箱、自动创建 worktree、远程多用户未实现。 |

Claude ACP 使用 Agent SDK，执行端要求 API key；现有 Pro / Max 额度展示不构成 SDK 推理授权。这会影响后续是否采用 ACP、未修改 CLI 或其他官方支持路径的选择，需在启动前审查。

## Validation approach / 验证方式

Backend tests use temporary SQLite stores, direct HTTP dispatcher calls and fake ACP/AgentMeter Python subprocesses. Frontend tests use DOM simulation and mocked HTTP. Build produces static assets. None of these starts the AgentDock HTTP service, a real coding agent or a provider quota request.

Local verification: 45 backend tests and 16 UI tests passed; Python bytecode compilation, TypeScript checks and the Vite production build passed (macOS, Python 3.9.6, Node.js 20.20.2). The UI regression suite includes delayed state refresh and out-of-order polling, verifying that a task after session creation targets the new session.

覆盖：跨项目/跨身份访问拒绝、取消后工具失效、CAS 并发写冲突、记忆审核来源、过期审批拒绝、异常协议/输出大小、子进程组回收、同库多实例拒绝、父子目录冲突、缓存额度过期/未知、界面请求与语言切换。

Reproduce without launching the app:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q agentdock tests
cd web
npm ci --ignore-scripts
npm test
npm run build
```

CI performs these isolated checks on Python 3.9 / 3.12 and Node 20. Passing them is not a substitute for live-provider acceptance. No claim is made that real agent execution or real quota refresh has passed.

## Review order / 建议审查顺序

1. [Architecture](ARCHITECTURE.md)：ACP、MCP、配额与共享记忆的边界，以及是否接受显式运行、人工审核的首版范围。
2. `agentdock/store.py`：项目隔离、消息语义、记忆版本/来源、运行权限和锁。
3. `agentdock/runtime.py` / `mcp.py`：真实 ACP 字段、审批时效、工具授权和取消路径。
4. `agentdock/quota.py` / `server.py`：额度真实性、本地认证、关闭顺序和默认禁执行。
5. `web/src/` / `tests/`：可见状态与 API 一致性、异常和边界覆盖。

## After-review acceptance / 评审后的验收门槛

Only begin these steps after explicitly deciding to run the preview:

- Pin adapter versions and verify official authentication on disposable, trusted worktrees.
- Confirm one Codex task and one Claude task stream results, request permissions correctly, cancel fully and recover cleanly after restart.
- Verify Codex→Claude and Claude→Codex mailbox exchange without automatic runaway calls; confirm memory proposals require review and conflicts are visible.
- Refresh real AgentMeter quotas and compare remaining/reset values with the official usage page, including auth failure and stale cache.
- Review the real Chinese/English interface and capture privacy-safe demonstration screenshots.

Review preview does not install services, start at login, register global MCP configuration, alter AgentMeter or modify existing provider logins.
