# 二次审查修复与复验

账号和凭据相关目标已由[开发计划](DEVELOPMENT-PLAN.md)取代；下表保留历史修复证据。C1 已删除 Claude 额度／资料直连及其 `NetworkError`，其余公开错误码约定保留。

审查基线：[`c183c5a`](https://github.com/NginxL/AgentDock/commit/c183c5a)。下表按原审查编号列出行为、验证入口和提交。测试使用临时数据库、虚构凭据及模拟 CLI；真实账号换号、OAuth 刷新和生产 SSH 验收仍由使用者完成。

## 修复对应表

| 编号 | 当前行为 | 回归测试 / 提交 |
| --- | --- | --- |
| 1 公开仓库 runner | 删除真实 CLI 的 self-hosted 工作流；手动真实验证脚本在 GitHub Actions 内拒绝运行，即使提供启用参数。仓库中现存工作流仅选择 GitHub 托管机器。实际 runner 注册状态另见下方边界。 | `test_live_e2e_gate.py`；[`b41a247`](https://github.com/NginxL/AgentDock/commit/b41a247) |
| 2 ACP 租约冲突 | 原生 CLI 外部刷新后，清理未变化的子进程副本；两侧都刷新则先将子进程完整认证文件组保存到私有冲突目录，再释放恢复日志。保留原生当前登录；磁盘失败保留日志供重试。 | `test_credential_lease.py`：旧冲突日志恢复、两侧刷新、身份不混用、归档失败重试；[`89009fc`](https://github.com/NginxL/AgentDock/commit/89009fc) |
| 3 ACP 并发 | 同一登记设备、同一 ACP 服务在调度器中排队；跨控制端锁等待支持取消，没有 30 秒失败期限。模型发现遇到占用立即返回明确提示。 | `test_runtime.py`、`test_store.py`、`test_credential_lease.py`；[`3c38d56`](https://github.com/NginxL/AgentDock/commit/3c38d56) |
| 4 默认派工目标 | 普通派工和项目任务均排除 `deleting=1` 的会话；删除标记不再改变会话活动时间。没有健康会话时创建新的会话。 | `test_deletion_lifecycle.py`；[`e01c0de`](https://github.com/NginxL/AgentDock/commit/e01c0de) |
| 5 账号错误 | `AccountError`、`KeychainError`、`NetworkError` 接入公开错误协议，同时保持 `ValueError` 兼容。常见错误有稳定 code 和中英文提示；未知内部异常继续脱敏。 | `test_account_public_errors.py`、`errorMessages.test.ts`；[`8966dce`](https://github.com/NginxL/AgentDock/commit/8966dce) |
| 6 删除前置校验 | 执行开关、设备及本机必要命令检查在提交删除标记前完成。删除 Agent 时任一会话校验失败，全部标记回滚且不做清理；已经开始清理后的失败仍保留可重试标记。 | `test_deletion_lifecycle.py`：审阅模式、Agent 多会话原子校验、并发读写及重启重试；[`e01c0de`](https://github.com/NginxL/AgentDock/commit/e01c0de) |
| 7 远端事件截断 | 本机和 SSH 共用关键事件策略，保留 `token_usage`、`account_rate_limit`、`input_receipt`、`input_control`、`model_info`、远程控制及最终回复。普通进度截断不影响结算。 | `test_remote_output.py`：实际 worker 存储超过 5,000 条和 8 MiB 两种情况；`test_runtime.py`；[`985bd97`](https://github.com/NginxL/AgentDock/commit/985bd97) |
| 8 原生快照状态 | 构造时尝试一次旧快照迁移，损坏文件单独记录脱敏诊断并保留原件，其他快照继续迁移。状态查询不加操作锁、不迁移、不解密；损坏的待恢复日志仍显示需要恢复。显式换号对无效快照继续拒绝。 | `test_native_accounts.py`：持锁查询、坏 JSON、无效格式、启动锁竞争；[`8966dce`](https://github.com/NginxL/AgentDock/commit/8966dce) |
| 9 状态响应体积 | 全量和增量状态均不返回会话事件；事件通过会话历史接口和 SSE 获取。演示模式继续使用本地事件样例。 | `test_state_sync.py`、不含 events 的 `App.test.tsx` 实时状态样例；[`eaa4394`](https://github.com/NginxL/AgentDock/commit/eaa4394) |
| 10 最终回复结尾 | 协议与结算使用同一文本规则：保留尾部，原文及 JSON 转义后的字符串内容均最多 120,000 UTF-8 字节，截断标记计入上限；已符合上限的文本再次经过边界不会缩短。运行记录、最终消息和任务报告分页保持一致。 | `test_text_buffer.py`、`test_runtime.py`、`test_tasks.py`：9 万字符、超限英文及中文、分页结论；[`e4d7163`](https://github.com/NginxL/AgentDock/commit/e4d7163)，转义修正见下方 B |

## 后续回归 A / B

复验基线：[`8d541ac`](https://github.com/NginxL/AgentDock/commit/8d541ac)。

| 问题 | 当前行为 | 回归依据 |
| --- | --- | --- |
| A 单条大事件隐藏后续进度 | 单条超限仅替换该条为 `output_truncated`（`scope=event`），以替换后的实际体积计入预算；只有累计 5,000 条或 8 MiB 超限才保持本轮截断状态（`scope=run`）。本机和 SSH 行为一致。 | `test_progress_limits.py`：本机 150 KB、远端 310 KB，以及单条 9 MB 后的工具调用和文本进度；`test_remote_output.py`：累计超限后仍保留关键事件。提交 [`7c786f8`](https://github.com/NginxL/AgentDock/commit/7c786f8)。 |
| B 最终回复转义膨胀导致失败 | 公共文本缓冲同时约束原文及 JSON 转义后的字符串内容，给事件元数据留出空间。只在超限时截掉前部，保留结论和单个明确标记；重复经过协议及结算边界不继续缩短。 | `test_text_buffer.py`：引号、反斜杠、全部控制字符、中文、边界值及幂等；`test_providers.py`、`test_acp.py`：模拟 Codex、Claude、ACP 原生协议后写入真实事件表；`test_runtime.py`：最终事件与运行结果一致、状态为完成。提交 [`5bfb7b7`](https://github.com/NginxL/AgentDock/commit/5bfb7b7)。 |

复现脚本的隔离验证结果：150,000 字符工具结果后仍收到 `tool_call` 和 `agent_message_chunk`，累计截断标志保持关闭。大量引号和控制字符两种回复保存后的事件均为 120,060 字节，保留结论和截断标记，未触发 `Event too large`。测试数据使用固定 UUID 长度和 ASCII 元数据；实际事件体积随元数据变化，测试同时覆盖最长允许的消息标识。

最终文本的 120,000 字节预算按 JSON 转义后的内容计量，因此引号、反斜杠和控制字符很多时，实际保留的原始字符会减少。全量原生记录仍由原生 CLI 管理；工作台不会无提示地丢掉结尾。

## 状态响应测量

`python3 scripts/benchmarks/state_events.py` 创建 300 条各含 20,000 字符的事件，随后仅修改会话模型设置，测量五次增量快照读取与 JSON 编码的中位数。所有数据位于临时目录，不读取现有账号或会话。

同机 Python 3.13.14，2026-10-09：

| 版本 | 返回的数据域 | 响应字节 | 读取与 JSON 编码中位数 |
| --- | --- | ---: | ---: |
| `c183c5a` | `events`、`sessions` | 6,082,916 | 20.72 ms |
| 修复后 | `sessions` | 812 | 0.24 ms |

两版使用同一测量脚本。路径长度会影响少量字节，耗时随设备及负载变化；测试断言响应不含事件并小于 10 KB，不以耗时作为通过门槛。

此测量验证的是移除事件内容后的响应体积，不是按行同步。增量快照仍返回发生变化的数据域的完整集合；300 个会话中仅修改一个设置时，仍会返回全部会话，参见 [API 状态边界](API.zh-CN.md#状态与任务记录)。

## 完整验证

| 检查 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -q` | Python 3.13.14，465 项通过；包含 A / B 新增的 8 项回归 |
| `npm --prefix web test` | 27 个测试文件、221 项通过 |
| `npm --prefix web run build` | TypeScript 和生产构建通过 |
| `ruff check agentdock`、`ruff format --check agentdock tests scripts setup.py`、`mypy` | 全部通过；严格类型覆盖 3 个基础模块 |
| [GitHub Checks：A / B 代码修复提交](https://github.com/NginxL/AgentDock/actions/runs/37879999007) | `5bfb7b7`：Python 3.11/3.13、前端和 wheel、macOS Swift、规范检查全部通过 |

## 验收边界

- **Runner 注册**属于 GitHub 仓库或组织设置，无法从源码确认。本次未获取注册清单；若曾登记含真实登录的 `agentdock-live` runner，仍须在仓库 Settings → Actions → Runners 撤销，并检查组织 runner group 是否授权此公开仓库。删除工作流不等于撤销注册。详见[分发与验证](DISTRIBUTION.md#live-cli-verification)。
- **账号及网络**：没有执行真实换号、登录或 OAuth 刷新，没有修改原生 CLI 代理和生产 SSH 配置。自动冲突恢复的验证依据为临时凭据和模拟刷新；真实客户端验收仍待完成。
- **升级**：远端 Python 3.11+、ACP 默认关闭、诊断和类型检查范围见[升级说明](UPGRADING.md)。
- **冲突凭据**：私有 `conflicts` 存档没有自动过期清理，可能长期保留 refresh token，须人工核对后删除；详见[凭据生命周期](EXPERIMENTS.md#acp-credential-lifetime--acp-凭据生命周期)。
