# 0004. One redaction rule file for TypeScript and Python

- Status: accepted
- Date: 2026-10-04

## Context

Redaction runs twice: in `capture.mjs` before a line touches disk (Part F.4) and in
`praxis ingest` / `praxis evidence export` as a second pass. Two hand-written rule sets drift.

## Decision

Rules live in `schemas/redaction-rules.json`: an ordered list of
`{id, type, pattern, flags, group?}` regexes plus the key-name pattern, the sensitive-path
globs and the entropy parameters. `scripts/codegen.py` embeds the file into
`packages/hooks/src/generated/redaction-rules.ts` and `core/praxis/generated/redaction_rules.py`.
Patterns use the common subset of JavaScript and Python regex syntax; a test compiles every
pattern in both engines and runs the canary corpus through both implementations.

Replacement token: `‹redacted:<type>:<sha256[:8]>›`.

## Consequences

- Patterns cannot use lookbehind or engine-specific syntax.
- The canary corpus is generated at test time from fragments, so no secret-shaped literal is
  ever committed. This keeps GitHub push protection and gitleaks quiet without allowlists.
