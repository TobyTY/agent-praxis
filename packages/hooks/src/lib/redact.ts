// First-pass redaction, run before any byte reaches the spool (Part F.4, ADR 0004).
// Rules are generated from schemas/redaction-rules.json; core/praxis/capture/redact.py is
// the twin and both run the same canary corpus in tests.
import { createHash } from "node:crypto";
import { REDACTION_RULES } from "../generated/redaction-rules.js";

interface CompiledRule {
  type: string;
  re: RegExp;
  group: number | undefined;
}

const RULES: CompiledRule[] = REDACTION_RULES.rules.map((r) => ({
  type: r.type,
  re: new RegExp(r.pattern, "g" + r.flags),
  group: "group" in r ? (r.group as number) : undefined,
}));

const ENTROPY = REDACTION_RULES.entropy;
const ENTROPY_RE = new RegExp(ENTROPY.token_pattern, "g");
const TOKEN_RE = /‹redacted:[a-z_]+:[0-9a-f]{8}›/;

export function token(kind: string, value: string): string {
  const digest = createHash("sha256").update(value, "utf8").digest("hex").slice(0, 8);
  return `‹redacted:${kind}:${digest}›`;
}

export function shannonBits(s: string): number {
  if (!s) return 0;
  const counts = new Map<string, number>();
  for (const ch of s) counts.set(ch, (counts.get(ch) ?? 0) + 1);
  const n = [...s].length;
  let bits = 0;
  for (const c of counts.values()) bits -= (c / n) * Math.log2(c / n);
  return bits;
}

function hasClasses(s: string): boolean {
  const have = new Set<string>();
  for (const ch of s) {
    if (ch >= "0" && ch <= "9") have.add("digit");
    else if (ch >= "A" && ch <= "Z") have.add("upper");
    else if (ch >= "a" && ch <= "z") have.add("lower");
  }
  return ENTROPY.require_classes.every((c) => have.has(c));
}

export function redactText(text: string): string {
  let out = text;
  for (const rule of RULES) {
    rule.re.lastIndex = 0;
    if (rule.group === undefined) {
      out = out.replace(rule.re, (m) => token(rule.type, m));
    } else {
      const g = rule.group;
      out = out.replace(rule.re, (...args: unknown[]) => {
        // args: match, p1..pn, offset, string[, groups]
        const groups: string[] = [];
        for (let i = 1; i < args.length && typeof args[i] !== "number"; i++) {
          groups.push((args[i] as string | undefined) ?? "");
        }
        return groups.map((part, i) => (i + 1 === g ? token(rule.type, part) : part)).join("");
      });
    }
  }
  ENTROPY_RE.lastIndex = 0;
  return out.replace(ENTROPY_RE, (s) => {
    if (TOKEN_RE.test(s)) return s;
    return hasClasses(s) && shannonBits(s) >= ENTROPY.min_bits_per_char ? token(ENTROPY.type, s) : s;
  });
}

export function redactValue(value: unknown): unknown {
  if (typeof value === "string") return redactText(value);
  if (Array.isArray(value)) return value.map(redactValue);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) out[k] = redactValue(v);
    return out;
  }
  return value;
}

function globToRegExp(glob: string): RegExp {
  const body = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${body}$`);
}

const SENSITIVE = REDACTION_RULES.sensitive_path_globs.map(globToRegExp);
const SENSITIVE_EXCEPT = REDACTION_RULES.sensitive_path_exceptions.map(globToRegExp);

export function isSensitivePath(path: string): boolean {
  const name = (path.replace(/\\/g, "/").split("/").pop() ?? "").toLowerCase();
  if (SENSITIVE_EXCEPT.some((re) => re.test(name))) return false;
  return SENSITIVE.some((re) => re.test(name));
}
