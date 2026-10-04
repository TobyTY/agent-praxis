// SessionStart (Part G.4). Phase 0: spool the start, compute the project id, reset taint
// on /clear, verify the snapshot (safe mode on failure). Materializing the resident set
// arrives in Phase 1.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { auditFact, type HookContext, type HookInput } from "../lib/hook.js";
import { projectInfo } from "../lib/project.js";
import { loadSnapshot } from "../lib/snapshot.js";
import { appendSpool, appendState, nowIso, safeSession } from "../lib/spool.js";

const NOT_INITIALIZED =
  "Praxis is installed but not initialized, so nothing is captured. Run `praxis init` in a terminal to start.";

/** True when this session's state log already records `notice` (one message per session). */
function alreadyNoticed(ctx: HookContext, sessionId: string, notice: string): boolean {
  const path = join(ctx.home.state, `${safeSession(sessionId)}.jsonl`);
  if (!existsSync(path)) return false;
  try {
    return readFileSync(path, "utf8").includes(`"notice":"${notice}"`);
  } catch {
    return false;
  }
}

export function handle(input: HookInput, ctx: HookContext) {
  const sessionId = typeof input.session_id === "string" ? input.session_id : "";
  if (!sessionId) return;
  if (!ctx.initialized) {
    // Nothing may be written before init; show the hint once per process start only.
    return input.source === "startup" ? { output: { systemMessage: NOT_INITIALIZED } } : undefined;
  }
  const source = typeof input.source === "string" ? input.source : null;
  const cwd = typeof input.cwd === "string" ? input.cwd : process.cwd();

  if (ctx.mode !== "replay") {
    const project = projectInfo(cwd);
    appendSpool(ctx.home, {
      v: 1,
      ts: nowIso(),
      kind: "session_start",
      session_id: sessionId,
      project_id: project.projectId,
      agent_id: typeof input.agent_id === "string" ? input.agent_id : null,
      data: {
        source,
        model: typeof input.model === "string" ? input.model : null,
        agent_type: typeof input.agent_type === "string" ? input.agent_type : null,
        root_hash: project.rootHash,
        git_head: project.gitHead,
        is_git: project.isGit,
      },
    });
  }

  // Taint resets only when context is cleared (Part F.3), never on compaction or resume.
  if (source === "clear") appendState(ctx.home, sessionId, { taint: "reset", reason: "clear" });

  const snap = loadSnapshot(ctx.home);
  if (snap.status === "invalid") {
    if (alreadyNoticed(ctx, sessionId, "safe_mode")) return;
    appendState(ctx.home, sessionId, { notice: "safe_mode" });
    auditFact(ctx.home, sessionId, "safe_mode_entered", { reason: snap.reason });
    return {
      output: {
        systemMessage: `Praxis is in safe mode (${snap.reason}): routing is off and only built-in protections apply. Run \`praxis doctor\`.`,
      },
    };
  }
  if (snap.status === "ok" && snap.snapshot.cards.length > 0) {
    const n = snap.snapshot.cards.length;
    return {
      output: {
        hookSpecificOutput: {
          hookEventName: "SessionStart",
          additionalContext: `Praxis is active for this project: ${n} verified procedure${n === 1 ? "" : "s"} available.`,
        },
      },
    };
  }
  return undefined;
}
