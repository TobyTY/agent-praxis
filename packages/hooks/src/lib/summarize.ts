// Turns raw tool I/O into small, redacted spool fields (Part G.4 capture.mjs).
// Everything returned here has already been through redactText.
import type { HomePaths } from "./env.js";
import { isSensitivePath, redactText, redactValue } from "./redact.js";
import { writeBlob } from "./spool.js";

export const HEAD_TAIL_BYTES = 2048;
const SHELL_TOOLS = new Set(["Bash", "PowerShell"]);
const EDIT_TOOLS = new Set(["Write", "Edit", "MultiEdit", "NotebookEdit"]);

export function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max) + `… [${s.length - max} more chars]`;
}

function headTail(s: string): { head: string; tail: string; bytes: number } {
  const bytes = Buffer.byteLength(s);
  if (s.length <= HEAD_TAIL_BYTES * 2) return { head: redactText(s), tail: "", bytes };
  return { head: redactText(s.slice(0, HEAD_TAIL_BYTES)), tail: redactText(s.slice(-HEAD_TAIL_BYTES)), bytes };
}

function str(v: unknown): string {
  if (typeof v === "string") return v;
  if (v === undefined || v === null) return "";
  return JSON.stringify(v);
}

function pathOf(toolInput: Record<string, unknown>): string | null {
  const p = toolInput.file_path ?? toolInput.notebook_path ?? toolInput.path;
  return typeof p === "string" ? p : null;
}

/** Small redacted view of tool_input: short string fields only, plus shell commands. */
export function summarizeInput(tool: string, toolInput: Record<string, unknown>): Record<string, unknown> {
  if (SHELL_TOOLS.has(tool)) {
    return { command: truncate(redactText(str(toolInput.command)), HEAD_TAIL_BYTES) };
  }
  const out: Record<string, unknown> = {};
  const path = pathOf(toolInput);
  if (path) {
    out.file_path = redactText(path);
    if (isSensitivePath(path)) out.sensitive = true;
  }
  for (const [k, v] of Object.entries(toolInput)) {
    if (k in out || k === "content" || k === "old_string" || k === "new_string" || k === "edits") continue;
    if (typeof v === "string") out[k] = truncate(redactText(v), 200);
    else if (typeof v === "number" || typeof v === "boolean") out[k] = v;
  }
  return out;
}

/** Edit payloads are kept as blobs so Phase 1 can rebuild file state for replays. Never for
 *  sensitive paths (.env, keys, credentials): those are recorded as "edited", content-free. */
export function storeEditPayload(home: HomePaths, tool: string, toolInput: Record<string, unknown>): string | null {
  if (!EDIT_TOOLS.has(tool)) return null;
  const path = pathOf(toolInput);
  if (path && isSensitivePath(path)) return null;
  return writeBlob(home, JSON.stringify({ tool, tool_input: redactValue(toolInput) }));
}

export function summarizeOk(tool: string, response: unknown): Record<string, unknown> {
  if (SHELL_TOOLS.has(tool) && response && typeof response === "object") {
    const r = response as Record<string, unknown>;
    const stdout = headTail(str(r.stdout));
    const stderr = headTail(str(r.stderr));
    const exit = typeof r.exitCode === "number" ? r.exitCode : typeof r.exit_code === "number" ? r.exit_code : 0;
    return {
      exit,
      bytes: stdout.bytes + stderr.bytes,
      stdout_head: stdout.head,
      stdout_tail: stdout.tail,
      stderr_head: stderr.head,
      interrupted: r.interrupted === true,
    };
  }
  return { bytes: Buffer.byteLength(str(response)) };
}

export function summarizeFail(error: unknown, isInterrupt: unknown): Record<string, unknown> {
  const text = str(error);
  const m = /^Exit code (-?\d+)/.exec(text);
  const ht = headTail(text);
  return {
    exit: m?.[1] !== undefined ? Number(m[1]) : null,
    bytes: ht.bytes,
    error_head: ht.head,
    error_tail: ht.tail,
    is_interrupt: isInterrupt === true,
  };
}
