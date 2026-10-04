// SessionEnd (Part G.4, ADR 0005). Spool the end, start a detached `praxis ingest --quiet`,
// exit at once. The host gives all SessionEnd hooks 1.5 s together and plugin timeouts
// cannot raise it, so this hook never waits on the child.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { delimiter, join } from "node:path";
import { type HookContext, type HookInput } from "../lib/hook.js";
import { appendSpool, logLine, nowIso } from "../lib/spool.js";

/** Resolve the praxis executable without a shell: PRAXIS_BIN, then PATH. Never a .cmd shim. */
export function findPraxis(env: NodeJS.ProcessEnv = process.env, platform = process.platform): string | null {
  const explicit = env.PRAXIS_BIN;
  if (explicit && existsSync(explicit)) return explicit;
  const names = platform === "win32" ? ["praxis.exe"] : ["praxis"];
  const pathVar = env.PATH ?? env.Path ?? "";
  for (const dir of pathVar.split(delimiter)) {
    if (!dir) continue;
    for (const name of names) {
      const candidate = join(dir, name);
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
}

export function handle(input: HookInput, ctx: HookContext) {
  const sessionId = typeof input.session_id === "string" ? input.session_id : "";
  if (!sessionId || !ctx.initialized || ctx.mode === "replay") return;
  appendSpool(ctx.home, {
    v: 1,
    ts: nowIso(),
    kind: "session_end",
    session_id: sessionId,
    data: { reason: typeof input.reason === "string" ? input.reason : null },
  });
  if (process.env.PRAXIS_NO_SPAWN === "1") return;
  const bin = findPraxis();
  if (!bin) {
    logLine(ctx.home, "session-end", "praxis executable not found; ingest deferred to the next praxis command");
    return;
  }
  const child = spawn(bin, ["ingest", "--quiet"], {
    detached: true,
    stdio: "ignore",
    windowsHide: true,
    env: { ...process.env, PRAXIS_HOME: ctx.home.root },
  });
  child.on("error", (e) => logLine(ctx.home, "session-end", `ingest spawn failed: ${e.message}`));
  child.unref();
  return undefined;
}
