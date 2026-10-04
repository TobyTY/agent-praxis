// Shared hook runner: the rules every hook follows (Part G.3).
// - PRAXIS_DISABLE=1 or PRAXIS_MODE=internal: exit 0 before reading anything.
// - Read all of stdin with a deadline; invalid JSON: log and exit 0.
// - Print at most one JSON object, written synchronously so exit cannot truncate it.
// - Internal errors: log, spool an audit fact, exit 0 (fail open; Guard under taint fails
//   closed from Phase 2 and overrides `onError`).
// - Self-timeout at 80% of the budget: exit with no decision.
import { existsSync, writeSync } from "node:fs";
import { homePaths, isDisabled, praxisHome, praxisMode, type HomePaths, type PraxisMode } from "./env.js";
import { appendSpool, logLine, nowIso } from "./spool.js";

export interface HookInput {
  session_id?: string;
  cwd?: string;
  hook_event_name?: string;
  agent_id?: string;
  prompt_id?: string;
  [key: string]: unknown;
}

export interface HookContext {
  name: string;
  home: HomePaths;
  mode: PraxisMode;
  args: string[];
  startedAt: number;
  /** False until `praxis init` created the key. Hooks then write nothing to disk. */
  initialized: boolean;
}

export interface HookResult {
  output?: Record<string, unknown>;
  exitCode?: number;
}

export interface HookSpec {
  name: string;
  /** Wall-clock budget in ms; the hook gives up at 80% of it (Part L). */
  budgetMs: number;
  handler: (input: HookInput, ctx: HookContext) => HookResult | void;
}

const MAX_STDIN_BYTES = 8 * 1024 * 1024;

function finish(result: HookResult | void): never {
  const out = result?.output;
  if (out) writeSync(1, JSON.stringify(out));
  process.exit(result?.exitCode ?? 0);
}

/** Resolve on EOF, or as soon as the bytes so far form one complete JSON value. The host
 *  does not always close stdin promptly (observed on SessionEnd under `claude -p`, 2.1.248),
 *  and waiting for EOF there burns the whole 1.5 s SessionEnd budget. */
function readStdin(deadlineMs: number): Promise<string> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    let size = 0;
    const timer = setTimeout(() => resolve(Buffer.concat(chunks).toString("utf8")), deadlineMs);
    process.stdin.on("data", (c: Buffer) => {
      size += c.length;
      if (size <= MAX_STDIN_BYTES) chunks.push(c);
      const text = Buffer.concat(chunks).toString("utf8");
      if (text.trimEnd().endsWith("}")) {
        try {
          JSON.parse(text);
          clearTimeout(timer);
          process.stdin.pause();
          resolve(text);
        } catch {
          /* incomplete; keep reading */
        }
      }
    });
    process.stdin.on("end", () => {
      clearTimeout(timer);
      resolve(Buffer.concat(chunks).toString("utf8"));
    });
    process.stdin.on("error", () => {
      clearTimeout(timer);
      resolve("");
    });
  });
}

export function auditFact(home: HomePaths, sessionId: string, action: string, details: Record<string, unknown>): void {
  try {
    appendSpool(home, {
      v: 1,
      ts: nowIso(),
      kind: "audit",
      session_id: sessionId,
      data: { actor: "hook", action, target: null, details },
    });
  } catch {
    /* the log line below is the fallback */
  }
}

export async function runHook(spec: HookSpec): Promise<never> {
  const startedAt = Date.now();
  if (isDisabled()) process.exit(0);
  const mode = praxisMode();
  if (mode === "internal") process.exit(0);

  const home = homePaths(praxisHome());
  const initialized = existsSync(home.key);
  const ctx: HookContext = { name: spec.name, home, mode, args: process.argv.slice(2), startedAt, initialized };
  const giveUpAt = Math.floor(spec.budgetMs * 0.8);
  const watchdog = setTimeout(() => {
    if (initialized) logLine(home, spec.name, `self-timeout after ${giveUpAt} ms`);
    process.exit(0);
  }, giveUpAt);
  watchdog.unref();

  // Leave time between the stdin deadline and the watchdog so a hook whose input arrived
  // without EOF still does its work.
  const raw = await readStdin(Math.floor(giveUpAt * 0.6));
  let input: HookInput;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("input is not an object");
    input = parsed as HookInput;
  } catch (e) {
    if (initialized) logLine(home, spec.name, `invalid stdin JSON: ${(e as Error).message}`);
    process.exit(0);
  }

  try {
    finish(spec.handler(input, ctx));
  } catch (e) {
    const err = e as Error;
    if (!initialized) process.exit(0);
    logLine(home, spec.name, `internal error: ${err.stack ?? err.message}`);
    if (typeof input.session_id === "string" && input.session_id) {
      auditFact(home, input.session_id, "hook_error", { hook: spec.name, message: err.message.slice(0, 500) });
    }
    process.exit(0);
  }
}
