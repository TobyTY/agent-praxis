# Contributing

Thanks for helping. Praxis runs next to people's source code and shell, so correctness and
security come before speed.

## Setup

```bash
cd packages/hooks && npm ci && npm run build && npx vitest run
```

```bash
cd core && uv sync && uv run pytest
```

`CLAUDE.md` lists every build, lint and test command.

## Rules

- **Hooks stay dependency-free.** Code under `packages/hooks/src` may import only `node:`
  built-ins and local modules (eslint enforces this). Rebuild `plugin/dist` and commit it.
- **Schemas are the source of truth.** Edit `schemas/*.json`, run `python scripts/codegen.py`,
  commit the generated files.
- **Redaction rules** live only in `schemas/redaction-rules.json` and must compile in both
  JavaScript and Python. If the shared corpus digest changes, explain why in the PR.
- **No secret-shaped literals** in code, tests or fixtures. Build test secrets at runtime
  (see `tests/fixtures/canary-templates.json`).
- **Security-relevant changes** need adversarial tests and must keep every invariant in
  SECURITY.md. Decisions get an ADR in `docs/adr/`.
- **Host behavior** (hook fields, exit codes, timeouts) is recorded in
  `docs/HOOK_CONTRACTS.md` with the Claude Code version it was checked against.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/).

## Reporting security issues

Privately, through a GitHub Security Advisory. See SECURITY.md.
