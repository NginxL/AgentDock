# Changelog

## Unreleased

### C1: Passive Claude quota / Claude 被动额度

- Remove direct Claude OAuth quota/profile requests, the quota credential reader, desktop quota snapshot probing and the quota experiment. Claude native switching is unavailable; remaining native switching removal is tracked by C2.
- Record bounded `rate_limit_event` observations for local/SSH device logins and managed accounts, without active quota probes. Preserve source and sampling time; absent percentages and reset times stay unknown.
- Migrate historical readings without relabeling them as run events; keep existing CLI proxy/certificate inheritance unchanged.
- 删除 Claude OAuth 额度／资料直连、额度凭据读取、桌面快照探测及额度实验开关；额度从本机／SSH 运行事件采集，界面显示来源和采样时间。旧值保留并标注升级前记录，原有代理及证书来源不变。

### Progress and final reply regressions

- Omit only an oversized individual progress event; keep later local and SSH tool/message progress visible until the cumulative display budget is reached.
- Bound final text after JSON escaping as well as before encoding, preserving the conclusion and an explicit marker without failing completed tasks on quotes or control characters.

### Follow-up review

- Remove credential-bearing self-hosted CI and refuse live model verification inside GitHub Actions; document removal of previously registered runners.
- Recover ACP credential conflicts without overwriting external logins, queue shared-login runs and allow cancellation during cross-controller waits.
- Exclude deletion tombstones from default dispatch and validate cleanup before committing deletion marks.
- Preserve actionable account error codes; read native public status without locking or migrating, and isolate corrupt legacy snapshots during startup.
- Preserve critical SSH accounting/control events after progress truncation, retain explicitly marked final reply tails, and remove event bodies from workbench state. See the [regression index](docs/REVIEW-FOLLOWUP.md) and [upgrade notes](docs/UPGRADING.md).

### Runtime and workflow foundations

- Require Python 3.11+, use the standard TOML parser and derive all build versions from one source.
- Allocate loopback ports automatically and avoid reverse-DNS lookups during local/SSH startup.
- Bundle frontend assets/notices in Python distributions, add the agentdock command and verify an isolated wheel installation.
- Build relocatable macOS apps with embedded Python; add optional Developer ID signing/notarization and manual live CLI verification.
- Keep native bundle resources immutable at runtime; add compatible-interpreter fallback for source installs.
- Keep dispatcher locks free during external cleanup and record sanitized background failures.
- Split quick-start READMEs from detailed bilingual user guides and document remaining acceptance boundaries.

- Add cancellation indexes to existing and new databases.
- Preserve the most recent actions of a failed run in account handovers, including long conversations.
- Add a reproducible isolated cancellation benchmark and migration/long-history regressions.
- Keep the workbench responsive during local/SSH cleanup, with durable deletion tombstones and retry after restart.
- Encrypt native account snapshots and recovery journals with a Keychain-held AES-GCM key; isolate Keychain authorization in the signed desktop host.
- Coalesce streaming progress, keep tasks running after display truncation, and allow per-agent execution time limits excluding approval waits.
- Add redacted rotating diagnostics, error IDs and a metadata-only diagnostic export.
- Replace frequent full-state refreshes with versioned changes and authenticated SSE; use WAL readers, scoped wakeups, numbered migrations and minute heatmap caching.
- Filter local transcript scans before opening unrelated files and include account branch histories.
- Gate automatic failover, native client switching, ACP integrations and undocumented Claude quota reads behind separate default-off experiments.
- Lease ACP credentials only while running/discovering, preserve interrupted refreshes, queue concurrent operations, and preserve divergent legacy credentials without overwriting either side.
- Add project-level human approval for agent delegation, batch task history, scoped FTS5 memory search and completed-event compaction.
- Separate protocol clients, native transport, immutable turn inputs, local/SSH executors and storage domains; centralize admin route execution guards.
- Bound individual text buffers instead of failing long turns on cumulative commentary, and size capability lifetimes for configured long runs.
- Add stable error codes and bilingual error messages independent of server wording, Ruff checks and strict types for new foundational modules.
- Use TanStack Query for model, state and metrics requests; split workspace/task UI, related form drafts, styles and bilingual copy; lazy-load account, usage and token pages.
- Update the source-map-js development dependency to remove its known advisory.
