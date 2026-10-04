# Security policy

Praxis runs inside coding agents, next to source code and a shell. Security reports are
welcome and taken seriously.

## Supported versions

| Version | Supported |
|---|---|
| 0.0.x (pre-release, `main`) | Yes |

Until 1.0, only the latest release and `main` receive fixes.

## Reporting a vulnerability

Report privately through a
[GitHub Security Advisory](https://github.com/TobyTY/agent-praxis/security/advisories/new).
Do not open a public issue, and do not include real secrets or unredacted traces.

- Acknowledgement within **72 hours**.
- Triage and a severity assessment within **7 days**.
- A fix or a documented mitigation as fast as severity requires; you are credited in the
  advisory unless you ask otherwise.

## Scope

In scope: the hooks in `plugin/` and `packages/hooks/`, the `praxis` CLI and Python package
in `core/`, the redaction rules, the snapshot and audit integrity checks, and the release
pipeline. Out of scope: Claude Code itself (report to Anthropic), third-party skills you
import, and attacks that need an attacker who already runs code as your user (see residual
risk below).

## Safe harbor

Good-faith research that respects this policy, avoids privacy violations and data
destruction, and gives us reasonable time to fix before disclosure will not be pursued
legally. Test only against your own installation.

## Security invariants

Each invariant has dedicated tests. A change that weakens one needs an ADR and maintainer
review (CODEOWNERS).

1. **Guard only subtracts.** Praxis never returns `permissionDecision: "allow"` and never
   adds permission allow rules. *(Guard ships in Phase 2.)*
2. **No third-party code execution.** Imported scripts are never run.
3. **Learned cards cannot grant themselves power.** Capabilities come only from observed,
   passing replays; network, out-of-project and dangerous capabilities need human approval.
4. **Untrusted text never becomes instructions to the Learner.** Tool output is fenced as
   data; every learned rule must cite a user turn.
5. **Graders sit outside the replay's reach.**
6. **Praxis protects itself.** Agent sessions cannot write Praxis data, config, Claude Code
   settings or Praxis hook files. *(Enforced from Phase 2.)*
7. **Local by default.** No telemetry; no network calls except internal `claude -p` runs the
   user enabled. Traces are redacted before they touch disk. *(Phase 0: enforced and tested
   with a 234-item canary corpus, 100% removal, and 10,000-input fuzzing in both languages.)*
8. **Fail safe, never silently.** Security-path errors are audited. A tampered snapshot puts
   the hooks in safe mode and tells the user once per session. *(Phase 0: snapshot HMAC,
   safe mode, hash-chained audit log.)*
9. **Honest residual risk.** Hooks are not a sandbox: timed-out PreToolUse hooks do not
   block, `if` filters are best effort, and a same-user process can read local keys. Use
   OS-level sandboxing for untrusted work.

Details: [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).
