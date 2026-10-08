# Changelog

## Unreleased

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
- Lease ACP credentials only while running/discovering, preserve interrupted refreshes, and reject concurrent or divergent legacy credentials without overwriting either side.
- Add project-level human approval for agent delegation, batch task history, scoped FTS5 memory search and completed-event compaction.
- Separate protocol clients, native transport, immutable turn inputs, local/SSH executors and storage domains; centralize admin route execution guards.
- Bound individual text buffers instead of failing long turns on cumulative commentary, and size capability lifetimes for configured long runs.
