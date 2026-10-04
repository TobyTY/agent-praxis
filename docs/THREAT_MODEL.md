# Threat model

Status: **Phase 0** (capture, ingest, snapshot, audit). Guard (Phase 2) and import scanning
(Phase 4) are designed but not built; rows below say what exists today.

## Assets

- Source code, secrets and credentials reachable from the developer's agent sessions.
- Praxis traces: prompts, tool inputs and outputs, assistant excerpts (redacted).
- Learned procedures and their evidence (from Phase 1).
- The integrity of Praxis itself: snapshot, key, config, hooks, audit log.

## Trust boundaries

1. **Agent session → hooks.** Hook input is JSON from Claude Code, but its content (prompts,
   tool output, file contents) can carry attacker-controlled text from repositories, web
   pages and MCP servers.
2. **Hooks → `$PRAXIS_HOME`.** Hooks only append to the spool, state log, blobs and a
   diagnostics log, and read the snapshot and key.
3. **`$PRAXIS_HOME` → control plane.** `praxis` treats every spool line as untrusted: schema
   check, size cap, second redaction pass.
4. **Control plane → `claude -p`** (Phase 1): internal calls run with `PRAXIS_MODE=internal`
   so Praxis hooks exit immediately and cannot recurse.

## Threats (STRIDE-tagged)

| ID | STRIDE | Threat | Mitigations | Status | Residual risk |
|---|---|---|---|---|---|
| T1 | T, E | Malicious imported skill | Pinned-SHA import, static scanner, advisory LLM judge, manifest approval, taint, scripts never run | Phase 4 | Novel obfuscation may pass scanning; taint bounds damage |
| T2 | T | Memory poisoning: injected text in repo files or web pages becomes a "learned" rule | Tool output fenced as data; every rule cites a user turn; replay verification; approval for capability expansion | Phase 1 | A user approving without reading |
| T3 | T, R | Agent tampers with Praxis | **Now:** snapshot HMAC with safe mode; hash-chained audit log; hooks never trust spool content. **Phase 2:** protected paths, static deny rules, ConfigChange block | Partial | Same-user malware outside the agent (see below) |
| T4 | E | Guard evasion (obfuscated shell, path tricks, homoglyphs) | Shell tokenizer, path canonicalization, IDNA normalization, red-team corpus | Phase 2 | Parser gaps |
| T5 | D, E | Hook failure modes | **Now:** budgets far below host timeouts (measured p95 ≈ 55-60 ms on Windows vs 180-250 ms budgets); watchdog at 80%; stdin read that does not wait for EOF; fail-open with audit outside taint | Partial | Timed-out PreToolUse hooks do not block (host behavior) |
| T6 | T | Evidence forgery / reward hacking | Grader outside worktree, before/after hashes, deterministic assertions | Phase 1 | Judge errors on rubric-only checks |
| T7 | I | Secret leakage into traces | **Now:** redaction before the first byte is written (hook) and again at ingest; 20 format rules + `KEY=value` rule + entropy rule from one rule file shared by both languages; `.env`, keys and credential files never stored as blobs; 234-item canary corpus at 100%; 10,000-input fuzz per language; `praxis forget` with VACUUM | Done (Phase 0 scope) | Secret formats with no known prefix, low entropy and no key name |
| T8 | T | Praxis supply chain | Zero runtime dependencies (Node built-ins, Python stdlib); lockfiles; SHA-pinned Actions; CODEOWNERS; CodeQL; Scorecard; gitleaks; Dependabot | Partial (signed releases in Phase 1) | — |
| T9 | D | Praxis slows the agent or floods context | Perf CI with Part L budgets and a 20% regression gate; injections capped at 2,000 chars; `PRAXIS_DISABLE=1` kill switch | Done (Phase 0 scope) | — |
| T10 | I | Cross-project leakage | Learned cards default to project scope; project id from the canonical repo root plus origin URL | Phase 1 | — |

## Known limits, stated plainly

- **The snapshot HMAC is not a defense against same-user code.** The key lives in
  `$PRAXIS_HOME/keys/snapshot.key`. Any process running as the user can read it and sign a
  forged snapshot. The HMAC catches corruption and naive tampering, including an agent that
  edits the JSON without the key.
- **Tail truncation of the audit log is undetectable from the file alone.** The chain proves
  that no entry was edited, reordered or removed from the middle. Dropping the last entries
  leaves a valid shorter chain. A future version may anchor the head hash elsewhere.
- **File permissions on Windows.** `chmod 0700/0600` only sets the read-only bit on
  Windows. Protection of `$PRAXIS_HOME` relies on the user-profile ACL, which by default
  excludes other non-admin users.
- **SessionEnd is unreliable under `claude -p`** (HOOK_CONTRACTS.md §4). Nothing in Praxis
  depends on it: ingest is idempotent and runs on any `praxis` command.
- **Redaction is pattern-based.** It replaces values with `‹redacted:<type>:<sha256[:8]>›`;
  the 8-hex-char prefix keeps equality checks possible and is not reversible in practice,
  but very short secrets could be brute-forced from it. Values shorter than 4 characters
  after a key name are not redacted.
- **Hooks are not a sandbox.** Use OS-level sandboxing (containers, VMs, Claude Code's
  sandbox mode) for untrusted repositories.
