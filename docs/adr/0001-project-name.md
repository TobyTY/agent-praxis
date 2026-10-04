# 0001. Project name: Praxis, distributed as `agent-praxis`

- Status: accepted
- Date: 2026-10-04

## Context

The master prompt uses the working name `praxis` and asks for an availability check on
GitHub, PyPI and npm (Phase 0, task 2). On 2026-10-04:

| Name | GitHub (TobyTY) | PyPI | npm |
|---|---|---|---|
| `praxis` | free | **taken** | **taken** |
| `praxis-ai` | free | taken | taken |
| `praxis-skills` | free | free | taken |
| `praxis-memory` | free | free | taken |
| `praxis-cc` | free | free | free |
| `praxisd` | free | free | free |
| `agent-praxis` | free | free | free |

## Decision

- Brand and docs: **Praxis**.
- Repository: `TobyTY/agent-praxis`. PyPI distribution: `agent-praxis`.
- CLI command: `praxis`. Python import package: `praxis`.
- Claude Code plugin name: `praxis`. Materialized skill prefix: `px-`.

The maintainer chose `agent-praxis` from the free candidates.

## Alternatives

- `praxis-cc`: ties the name to one host; the core is meant to stay portable.
- `praxisd`: implies a daemon, and v1 has none.

## Consequences

- The import package `praxis` can collide with the unrelated PyPI `praxis` package if a user
  installs both into one environment. Installing with `uv tool install agent-praxis` or
  `pipx` isolates it. Revisit before 1.0 if a collision report arrives.
- No npm package is published: the hooks ship bundled inside the plugin.
