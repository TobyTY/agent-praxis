// PostToolUse / PostToolUseFailure / Stop / PostModelSwitch (Part G.4). Async in hooks.json,
// so nothing here can block Claude. Spool append only.
import { type HookContext, type HookInput } from "../lib/hook.js";
import { loadSnapshot } from "../lib/snapshot.js";
import { redactText, redactValue } from "../lib/redact.js";
import { appendSpool, nowIso, writeBlob } from "../lib/spool.js";
import { storeEditPayload, summarizeFail, summarizeInput, summarizeOk, truncate } from "../lib/summarize.js";

const KINDS = new Set(["tool_ok", "tool_fail", "turn_end", "model_switch"]);
const DEFAULT_EXCERPT_CHARS = 1500;

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function s(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

export function handle(input: HookInput, ctx: HookContext) {
  const sessionId = s(input.session_id) ?? "";
  const kind = ctx.args[0] ?? "";
  if (!sessionId || !ctx.initialized || ctx.mode === "replay" || !KINDS.has(kind)) return;
  const base = {
    v: 1 as const,
    ts: nowIso(),
    session_id: sessionId,
    agent_id: s(input.agent_id),
    prompt_id: s(input.prompt_id),
  };

  if (kind === "tool_ok" || kind === "tool_fail") {
    const tool = s(input.tool_name) ?? "unknown";
    const toolInput = obj(input.tool_input);
    let blob = storeEditPayload(ctx.home, tool, toolInput);
    const response = obj(input.tool_response);
    const outcome =
      kind === "tool_ok" ? summarizeOk(tool, input.tool_response) : summarizeFail(input.error, input.is_interrupt);
    if (typeof input.duration_ms === "number") outcome.duration_ms = input.duration_ms;
    if (response.bashEditDiff && !blob) {
      // v2.1.269+, public beta (HOOK_CONTRACTS.md §4): keep it for replay fidelity.
      blob = writeBlob(ctx.home, JSON.stringify(redactValue({ tool, bashEditDiff: response.bashEditDiff })));
      outcome.bash_edit_diff = true;
    }
    const mcp = obj(input.mcp_server);
    appendSpool(ctx.home, {
      ...base,
      kind,
      tool,
      tool_use_id: s(input.tool_use_id),
      input: summarizeInput(tool, toolInput),
      outcome,
      blob,
      data: Object.keys(mcp).length ? { mcp_server: { name: s(mcp.name), source: s(mcp.source) } } : null,
    });
    return;
  }

  if (kind === "turn_end") {
    const snap = loadSnapshot(ctx.home);
    const policy = snap.status === "ok" ? snap.snapshot.policy : null;
    const store = policy ? policy.store_assistant_text !== "none" : true;
    const max = policy?.assistant_excerpt_chars ?? DEFAULT_EXCERPT_CHARS;
    const text = s(input.last_assistant_message) ?? "";
    appendSpool(ctx.home, {
      ...base,
      kind,
      data: { excerpt: store ? truncate(redactText(text), max) : null, chars: text.length },
    });
    return;
  }

  // model_switch
  appendSpool(ctx.home, {
    ...base,
    kind: "model_switch",
    data: { from: s(input.from_model), to: s(input.to_model), source: s(input.source) },
  });
  return undefined;
}
