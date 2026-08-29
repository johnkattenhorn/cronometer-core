# Changelog

## 1.0.0 — 2026-07-22
- Initial cronometer-core: shared core generating the Cronometer CLI + FastMCP server.
- `PasswordSessionAuth` GWT-RPC login (in-memory ~1h token, nonce query-param + shared
  cookie jar, permutation self-heal on HTTP 500); `NullTokenStore`.
- 8 read ops incl. `get-protein-status` / `get-weekly-summary` composites; 5 CSV parsers.
- Added `--text` human-readable output (group-level flag).
