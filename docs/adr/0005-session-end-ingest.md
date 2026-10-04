# 0005. SessionEnd spawns a detached ingest; plugins cannot extend the budget

- Status: accepted
- Date: 2026-10-04

## Context

SessionEnd hooks share a 1.5 s budget. The docs state that `timeout` values on
plugin-provided hooks do not raise it. Ingest can take seconds.

## Decision

`session-end.mjs` appends `session_end` to the spool, then spawns `praxis ingest --quiet`
with `detached: true`, `stdio: "ignore"`, `windowsHide: true`, calls `unref()` and exits. It
never waits on the child. If the `praxis` executable cannot be found, it logs to
`hooks.log` and exits 0; the next `praxis` command or `praxis worker` ingests later
because ingest is idempotent.

The executable is resolved from `PRAXIS_BIN`, then `PATH`. On Windows the hook resolves
`praxis.exe` (uv and pipx install a real `.exe` shim), never a `.cmd`.

## Consequences

- No hooks.json `timeout` on SessionEnd: it would be ignored.
- Survival of the detached child after Claude Code exits is tested on Windows in Phase 0
  (see PROGRESS.md).
