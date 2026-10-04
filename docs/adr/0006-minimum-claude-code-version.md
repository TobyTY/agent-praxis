# 0006. Minimum Claude Code version and version-gated hooks

- Status: accepted
- Date: 2026-10-04

## Context

The docs describe features newer than the maintainer's installed CLI (2.1.248):
PostModelSwitch (2.1.251), `bashEditDiff` (2.1.269), `scratchpad_dir` (2.1.257). The
2.1.248 plugin validator rejects a `hooks.json` containing `PostModelSwitch`, so shipping
it would break the plugin for anyone on an older version.

## Decision

- Minimum supported Claude Code version for v0.x: **2.1.248**.
- `hooks.json` registers only events that the minimum version validates.
- Newer input fields are read when present and never required.
- `capture.mjs` keeps its `model_switch` branch so enabling the hook later is a manifest
  change only.
- `praxis doctor` will report the Claude Code version once version-gated features exist.

## Consequences

- Model changes mid-session are not captured until PostModelSwitch is registered. The
  Learner falls back to SessionStart `model` to mark evidence stale (H.8).
- Revisit when raising the minimum version; update HOOK_CONTRACTS.md first.
