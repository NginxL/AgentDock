# Experimental integrations / 实验功能

The Accounts page contains four separate switches. All default to off, including when upgrading an existing database. Enabling requires acknowledging the displayed limitations. Disabling waits until queued and running work has stopped. Daily conversations, project tasks and manually selected managed accounts remain available.

账号页有四个独立开关，新安装和旧库升级均默认关闭。开启前需了解对应限制；有排队或运行任务时不能停用。日常对话、项目任务及手动选择托管账号仍可使用。

| Feature / 功能 | Boundary / 边界 |
| --- | --- |
| Automatic failover / 自动换号 | Only a structured rejection before any progress permits an attempt with another explicitly allowed account. Existing failover settings are also gated. Account rotation must not be used to evade service limits. / 仅在明确拒绝且尚无进展时尝试允许的其他账号，旧策略也受开关限制，不得用于规避服务限制。 |
| Native client switching / 本机客户端换号 | Explicit capture, switch and recovery can quit/reopen the chosen client. Snapshots are encrypted; native acceptance remains manual. / 显式保存、切换和恢复可能退出并重开所选客户端；快照已加密，真实换号需人工验收。 |
| Additional ACP agents / 更多 Agent | Fixture coverage proves protocol behavior; installed client versions and real model execution need acceptance. / 协议测试覆盖不等于已验证所有 CLI 版本和真实模型任务。 |
| Claude subscription quota / Claude 订阅额度 | Uses undocumented OAuth usage endpoints. Failure means unknown quota, not zero. Claude Code's proxy settings remain the source. / 使用非公开接口，失败显示未知而非零额度；继续沿用 Claude Code 自身代理。 |

[OpenAI's terms](https://openai.com/policies/terms-of-use/) prohibit circumventing rate limits and restrictions. [Anthropic's consumer terms](https://www.anthropic.com/legal/consumer-terms) constrain automated access except where permitted. These are implementation boundaries, not a determination that every multi-account use violates a contract. A switch being available is not provider authorization.

OpenAI 条款禁止规避限流和限制；Anthropic 消费者条款也对未经许可的自动化访问设有限制。这不等于断言所有多账号使用都违规；功能可开启也不代表已获服务商许可。

## ACP credential lifetime / ACP 凭据生命周期

Runs and model discovery acquire a lock for the same native credential source. Seed files are copied into private storage only for that operation. Refreshed authentication files are copied back after checking source fingerprints; settings and proxy files are never copied back. All seed copies are removed after successful reconciliation. An interrupted copy retains a metadata journal for retry, without credential contents. The native child inherits the lease, so a crashed controller cannot recover while the child still uses credentials.

运行及模型读取会锁定同一凭据来源，仅在操作期间保留私有副本。刷新认证文件在核对源指纹后回写，设置及代理文件不回写；核对并回写成功后清理全部种子文件。复制中断保留不含凭据内容的恢复日志，可重试。子进程继承锁，控制端崩溃也不会在原生进程仍运行时回收凭据。

If an external CLI changes the native login during a lease, later runs use that current native login. Unchanged child copies are discarded. When both sides changed, the child's complete authentication bundle is preserved under `~/.local/share/agentdock/credential-leases/<profile>/conflicts/<digest>/` with private permissions; it is never automatically restored. The active journal is cleared only after preservation succeeds. Old conflicting journals recover the same way, so one external refresh does not permanently block the provider. A failed disk write retains the journal for retry.

租约期间原生 CLI 若更新登录，后续运行沿用当前原生登录。子进程未改变凭据时直接清理副本；两侧均改变时，将子进程的完整认证文件组保存在上述私有 `conflicts` 目录，避免混用账号或覆盖原生登录，也不自动恢复该副本。保存成功后清理活动恢复日志，旧版遗留的冲突日志按相同规则恢复。磁盘写入失败仍保留日志供重试，正常外部刷新不会永久锁住服务。

## Project delegation / 项目派工

Each project can enable **Ask me before agents delegate work**. Delegated work remains queued after the sender finishes; native full access does not bypass this decision. Approval releases that one dispatch, rejection returns a cancelled result, cancellation invalidates pending decisions, and restart requires explicit recovery. Changing the project preference does not approve requests already pending.

项目可启用 **Agent 派工需我确认**。发起者结束当前轮后，派工仍排队等待；完全访问权限不能跳过确认。批准只放行这一条，拒绝回传取消结果，取消任务会使待确认请求失效，重启后需显式恢复。修改项目开关不会自动批准已经等待的派工。

Model discovery keeps recovery storage outside temporary workspaces. Legacy credential copies with unknown provenance that differ from the native login are preserved and require reconciliation; they are never silently discarded.

模型发现的恢复存储位于临时工作目录之外。旧版本遗留凭据若与原生登录不同，会保留并要求核对，不能自动判定哪份是有效刷新结果。
