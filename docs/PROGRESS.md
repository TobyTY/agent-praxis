# Progress

One phase at a time (Rule A1). Each phase ends at a gate; the maintainer approves the next.

## Phase 0: Foundations (2026-10-04)

### Tasks

- [x] 1. Read Appendix A; `docs/HOOK_CONTRACTS.md` with version-tagged facts; every
      [verify] item resolved or scheduled (§8 of that file)
- [x] 2. Name availability checked; `agent-praxis` chosen (ADR 0001)
- [x] 3. Repository scaffold: license, NOTICE, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT,
      CHANGELOG, CLAUDE.md, PROGRESS.md, CI on three OSes
- [x] 4. JSON Schemas with generated TypeScript and Python types (`scripts/codegen.py`)
- [x] 5. SQLite migrations, spool format, idempotent ingest with redaction
- [x] 6. Hooks: `session-start` (no materialization), `route` (spool only), `capture`,
      `session-end`; plugin packaging; CLI `init`, `doctor`, `status`, `ingest`, `forget`,
      `audit verify`, `uninstall`
- [x] 7. Audit log; snapshot compiler (no cards) with HMAC and safe mode

### Gate

| Criterion | Target | Result | Pass |
|---|---|---|---|
| Golden hook tests on Linux, macOS, Windows | all pass | 28 cases pass in CI on ubuntu, macos, windows x Node 20, 22 (run 37200552908) | yes |
| No-op hook wall p95 within Part L budgets | Linux/macOS ≤ 100-150 ms, Windows ≤ 180-250 ms | perf CI, 200 runs, p95: Linux 25.5-27.3 ms, macOS 39.4-65.3 ms, Windows 67.5-89.2 ms (local Windows 55-59 ms) | yes |
| Real Claude Code session captured and ingested | documented | `docs/evidence/phase0-e2e-capture.json`, 10/10 required checks | yes |
| Redaction canary corpus | 100% | 234/234 in Python and TypeScript, identical output digest | yes |
| `praxis forget --all` leaves no trace data | test | `test_forget_all_leaves_no_trace` greps every file under home, including the SQLite file after VACUUM | yes |

### Deviations from the master prompt

- `PostModelSwitch` not registered: rejected by the 2.1.248 plugin validator (ADR 0006).
- Hooks never write the audit chain; they spool audit facts (ADR 0003).
- Snapshot `policy` carries the two privacy settings the capture hook needs.
- Extra table `spool_files` for idempotent ingest offsets.
- SessionEnd is unreliable under `claude -p`; nothing depends on it (HOOK_CONTRACTS.md §4).

## Phase 1: Learner (not started)

Waiting for approval of the Phase 0 gate.
