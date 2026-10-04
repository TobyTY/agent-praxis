# 0002. Toolchain and dependency policy

- Status: accepted
- Date: 2026-10-04

## Context

Rule A7: the hot path has zero runtime dependencies, and every Python dependency needs an
ADR. The repository still needs a TypeScript bundler, test runners and linters.

## Decision

- **Hooks (TypeScript):** runtime uses Node built-ins only. Dev dependencies: `typescript`,
  `esbuild` (bundles each hook to one `.mjs`), `vitest`, `fast-check`, `eslint` with
  `typescript-eslint`. Lockfile committed (`package-lock.json`, npm).
- **Core (Python ≥ 3.11):** runtime uses the standard library only (`sqlite3`, `tomllib`,
  `hmac`, `hashlib`, `argparse`, `json`). Dev dependencies: `pytest`, `hypothesis`, `ruff`,
  `mypy`. Managed with `uv`; `uv.lock` committed.
- **Codegen:** a stdlib-only Python script (`scripts/codegen.py`) turns `schemas/*.json` into
  TypeScript and Python types. No `json-schema-to-typescript` or `datamodel-code-generator`,
  because the schemas use a small subset of JSON Schema and an extra toolchain is not worth
  it.
- **Node target:** Node 20+ (CI tests 20 and 22). Bundles target `node20`, ESM.

## Alternatives

- `pnpm` for the hooks package: not installed on the maintainer machine; npm is enough for
  one package.
- Writing hooks in Python: Python start-up (~40-80 ms) plus import cost would eat most of the
  Windows wall-time budget.

## Consequences

- Config writing uses a tiny TOML emitter in `praxis.config`, since `tomllib` only reads.
- JSON Schema validation in Python is a small hand-written subset validator
  (`praxis.schema`), tested against the same fixtures as the TS side.
