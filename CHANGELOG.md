# Changelog

All notable changes are listed here. Versions follow SemVer; before 1.0, minor releases may
change configuration, never silently.

## Unreleased

### Added (Phase 0: foundations)

- Claude Code plugin with SessionStart, UserPromptSubmit, PostToolUse, PostToolUseFailure,
  Stop and SessionEnd hooks that capture sessions to a local spool, redacted before write.
- `praxis` CLI: `init`, `doctor`, `status`, `ingest`, `forget`, `audit verify`, `uninstall`.
- SQLite schema, idempotent ingest with a second redaction pass.
- HMAC-signed snapshot with safe mode on tampering; hash-chained audit log.
- JSON Schemas with generated TypeScript and Python types; one shared redaction rule file.
- Golden hook tests, redaction canary corpus and fuzzing, hook latency benchmark, CI on
  Linux, macOS and Windows.
