# Praxis

**Coding-agent skills that prove they work before they're kept, and can't do more than they should.**

> **Status: pre-alpha, Phase 0 of 4.** What works today is the foundation: the Claude Code
> plugin captures your sessions locally, redacts secrets before anything touches disk, and
> the `praxis` CLI ingests them into SQLite with a tamper-evident audit log. Learning,
> verification, the Guard and the router arrive in Phases 1-3 (see
> [docs/PROGRESS.md](docs/PROGRESS.md)). Nothing here learns or blocks anything yet.

Praxis turns a coding agent's own experience into verified, governed procedural memory. It
improves the agent's memory, not the model's weights.

- **Verified learning.** A procedure learned from your sessions is kept only after replaying
  the moment it was learned from shows it fixes the mistake without regressions.
- **Zero-trust skills.** Every skill gets a capability manifest; lower-trust skills in context
  narrow what tool calls are allowed.
- **Composition.** Conflicting skills are detected and never injected together.

## Install (from source, Phase 0)

Requirements: Claude Code 2.1.248+, Node 20+, Python 3.11+, [uv](https://docs.astral.sh/uv/).

```bash
uv tool install "git+https://github.com/TobyTY/agent-praxis#subdirectory=core"
```

```bash
praxis init --install-plugin
```

`praxis init` creates `~/.praxis` (owner-only), a snapshot signing key, the config and an
empty snapshot, then installs the Claude Code plugin from this repository's marketplace and
runs `praxis doctor`. Start a Claude Code session as usual; afterwards:

```bash
praxis status
```

Other commands: `praxis ingest`, `praxis forget --session ID | --project ID | --all`,
`praxis audit verify`, `praxis uninstall [--purge]`. Every command takes `--json`.
Kill switch: `PRAXIS_DISABLE=1`.

## What is captured, and what is not

Captured locally under `~/.praxis`, never sent anywhere: session starts and ends, your
prompts, tool names with short redacted input summaries, shell exit codes with the first and
last 2 KB of output, edit payloads (needed to rebuild file state for replays), and a
truncated excerpt of each final assistant message. Secrets are replaced with
`‹redacted:<type>:<hash8>›` before the first byte is written, and again at ingest. Edits to
`.env`, key and credential files are recorded without their content. Set
`privacy.store_assistant_text = "none"` to drop assistant excerpts; `praxis forget` deletes
data and compacts the database so it does not linger in free pages.

## Phase 0 numbers

| Check | Result |
|---|---|
| Hook wall time p95, 200 runs, GitHub runners (budgets: Linux/macOS 100-150 ms, Windows 180-250 ms) | Linux 25-27 ms, macOS 39-65 ms, Windows 67-89 ms |
| Redaction canary corpus (234 secrets, 26 formats, 9 contexts) | 100% removed, Python and TypeScript byte-identical |
| Redaction fuzzing | 10,000 inputs per language, no crash |
| Golden hook tests | 28 cases |
| Real Claude Code session captured and ingested | Yes ([evidence](docs/evidence/phase0-e2e-capture.json)) |

CI runs the hook, core and perf suites on Linux, macOS and Windows.

## How it works

```
Interfaces   Claude Code hooks (plugin) · praxis CLI · MCP server (Phase 4)
Mind         Learner · Guard · Composer       control plane: Python, on demand
Memory       Episodic traces · Skill graph    SQLite + content-addressed files
```

Hooks are small single-file Node bundles with no dependencies. They read a signed snapshot,
append one line to a spool file and exit; they never call a model, open the database or
touch the network. The `praxis` CLI does everything else. Design: [docs/MASTER_PROMPT.md](docs/MASTER_PROMPT.md);
host facts it relies on: [docs/HOOK_CONTRACTS.md](docs/HOOK_CONTRACTS.md); decisions:
[docs/adr/](docs/adr/).

## Security

Read [SECURITY.md](SECURITY.md) and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). In short:
local only, no telemetry, redaction before disk, a signed snapshot with safe mode on
tampering, and a hash-chained audit log. Hooks are not a sandbox; use OS-level sandboxing
for untrusted repositories.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under [Apache-2.0](LICENSE).
