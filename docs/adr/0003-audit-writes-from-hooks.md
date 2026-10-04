# 0003. Hooks never write the audit chain directly

- Status: accepted
- Date: 2026-10-04

## Context

The audit log is a hash chain (Part F.5): every entry includes the hash of the previous one.
Appending safely needs exclusive access to the tail. Hooks run in parallel and may not wait
on locks (Part D.2).

## Decision

Hooks write audit-worthy facts (safe-mode entry, internal errors, later Guard decisions) as
spool lines with `kind: "audit"`. `praxis ingest` moves them into the chain in spool order,
holding a file lock. The control plane is the only writer of `audit/audit.jsonl`.

The hooks also write a size-capped, rotated `logs/hooks.log` for diagnostics; it is not
part of the chain.

## Alternatives

- Lock-free append from hooks with a per-line hash of only the entry: breaks the chain
  property.
- A per-hook lock with a short timeout: violates the hot-path rule and still fails open.

## Consequences

- An audit fact reaches the chain only after the next ingest. The spool line itself is
  durable, and `praxis audit verify` reports un-ingested audit lines as pending.
- If a same-user process deletes spool lines before ingest, those facts are lost. This is
  inside the residual risk already accepted for T3.
