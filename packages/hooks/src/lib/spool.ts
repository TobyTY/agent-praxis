// Append-only writers: spool lines, per-session state log, content-addressed blobs,
// and the size-capped diagnostics log. One appendFileSync per line; no locks (Part D.2).
import { appendFileSync, existsSync, mkdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import type { HomePaths } from "./env.js";
import type { SpoolLine } from "../generated/types.js";

export const MAX_LINE_BYTES = 64 * 1024;
const LOG_MAX_BYTES = 1024 * 1024;

/** File-name form of a session id. Must match core/praxis/forget.py::safe_session. */
export function safeSession(sessionId: string): string {
  return sessionId.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 128) || "_";
}

export function nowIso(): string {
  return new Date().toISOString();
}

function ensureDir(dir: string): void {
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true, mode: 0o700 });
}

export function sha256(data: string | Buffer): string {
  return createHash("sha256").update(data).digest("hex");
}

/** Store a payload under blobs/sha256/ab/cdef… and return its digest. */
export function writeBlob(home: HomePaths, payload: string): string {
  const digest = sha256(payload);
  const dir = join(home.blobs, digest.slice(0, 2));
  const path = join(dir, digest.slice(2));
  if (!existsSync(path)) {
    ensureDir(dir);
    writeFileSync(path, payload, { mode: 0o600 });
  }
  return digest;
}

/** Append one spool line. Oversized input/outcome payloads move to a blob first. */
export function appendSpool(home: HomePaths, line: SpoolLine): void {
  let text = JSON.stringify(line);
  if (Buffer.byteLength(text) > MAX_LINE_BYTES) {
    const moved = { input: line.input ?? null, outcome: line.outcome ?? null, data: line.data ?? null };
    const blob = writeBlob(home, JSON.stringify(moved));
    text = JSON.stringify({ ...line, input: null, outcome: null, data: { oversized: true }, blob });
  }
  const day = line.ts.slice(0, 10);
  const dir = join(home.spool, day);
  ensureDir(dir);
  appendFileSync(join(dir, `${safeSession(line.session_id)}.jsonl`), text + "\n", { mode: 0o600 });
}

export function appendState(home: HomePaths, sessionId: string, entry: Record<string, unknown>): void {
  ensureDir(home.state);
  appendFileSync(join(home.state, `${safeSession(sessionId)}.jsonl`), JSON.stringify({ ts: nowIso(), ...entry }) + "\n", {
    mode: 0o600,
  });
}

/** Diagnostics only (never stdout). Rotates once at 1 MB; failures are swallowed. */
export function logLine(home: HomePaths, hook: string, message: string): void {
  try {
    ensureDir(home.logs);
    const path = join(home.logs, "hooks.log");
    try {
      if (statSync(path).size > LOG_MAX_BYTES) renameSync(path, path + ".1");
    } catch {
      /* no log yet */
    }
    appendFileSync(path, `${nowIso()} ${hook} ${message.replace(/\s+/g, " ").slice(0, 2000)}\n`, { mode: 0o600 });
  } catch {
    /* logging must never break a hook */
  }
}
