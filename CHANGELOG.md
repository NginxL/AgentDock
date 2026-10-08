# Changelog

## Unreleased

- Add cancellation indexes to existing and new databases.
- Preserve the most recent actions of a failed run in account handovers, including long conversations.
- Add a reproducible isolated cancellation benchmark and migration/long-history regressions.
- Keep the workbench responsive during local/SSH cleanup, with durable deletion tombstones and retry after restart.
- Encrypt native account snapshots and recovery journals with a Keychain-held AES-GCM key; isolate Keychain authorization in the signed desktop host.
