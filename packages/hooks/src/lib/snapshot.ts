// Snapshot loading with HMAC verification (Part E.3). Any failure means safe mode.
import { createHmac, timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";
import type { HomePaths } from "./env.js";
import type { Snapshot } from "../generated/types.js";
import { canonical } from "./canonical.js";

export type SnapshotState =
  | { status: "ok"; snapshot: Snapshot }
  | { status: "uninitialized" }
  | { status: "invalid"; reason: string };

export function hmacOf(body: Record<string, unknown>, key: Buffer): string {
  const { hmac_sha256: _ignored, ...unsigned } = body;
  return createHmac("sha256", key).update(canonical(unsigned), "utf8").digest("hex");
}

export function loadSnapshot(home: HomePaths): SnapshotState {
  let keyHex: string;
  try {
    keyHex = readFileSync(home.key, "utf8").trim();
  } catch {
    return { status: "uninitialized" };
  }
  let raw: string;
  try {
    raw = readFileSync(home.snapshot, "utf8");
  } catch {
    return { status: "invalid", reason: "snapshot missing" };
  }
  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return { status: "invalid", reason: "snapshot is not valid JSON" };
  }
  if (!/^[0-9a-f]{64}$/.test(keyHex)) return { status: "invalid", reason: "snapshot key malformed" };
  const claimed = body.hmac_sha256;
  if (typeof claimed !== "string" || !/^[0-9a-f]{64}$/.test(claimed)) {
    return { status: "invalid", reason: "snapshot has no HMAC" };
  }
  const actual = hmacOf(body, Buffer.from(keyHex, "hex"));
  if (!timingSafeEqual(Buffer.from(actual, "hex"), Buffer.from(claimed, "hex"))) {
    return { status: "invalid", reason: "snapshot HMAC mismatch" };
  }
  if (body.v !== 1) return { status: "invalid", reason: `unsupported snapshot version ${String(body.v)}` };
  return { status: "ok", snapshot: body as unknown as Snapshot };
}
