# Praxis (agent-praxis)

Verified procedural memory for coding agents. Spec: `docs/MASTER_PROMPT.md`. Phase status:
`docs/PROGRESS.md`. Host facts: `docs/HOOK_CONTRACTS.md` (update it before changing hooks).

## Commands

- Codegen (after editing `schemas/`): `python scripts/codegen.py` (CI: `--check`)
- Hooks: `cd packages/hooks && npm ci && npm run build && npx vitest run`
- Hooks lint/types: `npm run lint && npm run typecheck`
- Hook latency (Part L): `node packages/hooks/bench/perf.mjs`
- Core: `cd core && uv sync && uv run pytest && uv run ruff check . && uv run python -m mypy`
- Live capture check (spends usage): `PRAXIS_LIVE=1 uv run --project core python scripts/e2e_capture.py`

## Invariants (never weaken without an ADR)

- Hot path = `packages/hooks/src`: Node built-ins only, no LLM, no network, no SQLite, no
  locks, no blocking spawns. One JSON object on stdout at most. Never exit 1 to block.
- `plugin/dist/*.mjs` is generated and committed; rebuild after any hook change.
- Redact before writing to disk. Rules live only in `schemas/redaction-rules.json`.
- Never commit secret-shaped literals; canaries are assembled at test time.
- Hooks write audit facts to the spool; only `praxis` appends to `audit/audit.jsonl`.
- `PRAXIS_MODE=internal` → hooks exit 0; `replay` → no capture or routing.
- Python runtime deps: none (stdlib). Any dependency needs an ADR.
- Tests never touch the real `~/.praxis` or `~/.claude` (use temp dirs, `CLAUDE_CONFIG_DIR`).
- No `git push`, releases or publishing without the maintainer's explicit go-ahead.
- Commits carry no AI co-author trailers.

## Map

- `schemas/` JSON Schemas + redaction rules → generated types in both languages
- `packages/hooks/src/{session-start,route,capture,session-end}.ts` entry points
- `packages/hooks/src/handlers/` hook logic; `src/lib/` shared hot-path code
- `plugin/` Claude Code plugin (`hooks/hooks.json`, `dist/`); marketplace in `.claude-plugin/`
- `core/praxis/` CLI (`cli.py`), ingest + redaction (`capture/`), `snapshot.py`, `audit.py`,
  `forget.py`, `db/migrations/`
- `tests/hooks/<hook>/<case>.{in,out}.json` golden hook cases; `tests/fixtures/` shared
  parity fixtures
- `docs/adr/` decisions; `docs/evidence/` recorded gate evidence
