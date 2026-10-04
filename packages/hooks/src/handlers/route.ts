// UserPromptSubmit (Part G.4). Phase 0: spool the redacted prompt only; card selection and
// injection arrive in Phase 1 (router v0) and Phase 3 (Composer).
import { type HookContext, type HookInput } from "../lib/hook.js";
import { redactText } from "../lib/redact.js";
import { appendSpool, nowIso } from "../lib/spool.js";
import { truncate } from "../lib/summarize.js";

export const PROMPT_MAX_CHARS = 8000;

/** Routing is skipped for short prompts, slash commands and prompts opting out (Part G.4). */
export function routable(prompt: string): boolean {
  const p = prompt.trim();
  return p.length >= 12 && !p.startsWith("/") && !p.includes("#px-off");
}

export function handle(input: HookInput, ctx: HookContext) {
  const sessionId = typeof input.session_id === "string" ? input.session_id : "";
  if (!sessionId || !ctx.initialized || ctx.mode === "replay") return;
  const prompt = typeof input.prompt === "string" ? input.prompt : "";
  appendSpool(ctx.home, {
    v: 1,
    ts: nowIso(),
    kind: "prompt",
    session_id: sessionId,
    prompt_id: typeof input.prompt_id === "string" ? input.prompt_id : null,
    agent_id: typeof input.agent_id === "string" ? input.agent_id : null,
    data: {
      text: truncate(redactText(prompt), PROMPT_MAX_CHARS),
      chars: prompt.length,
      routable: routable(prompt),
    },
  });
  return undefined;
}
