// Deterministic, inert canary corpus. Twin of core/tests/canaries.py (see that file).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { REPO } from "./paths.js";

interface Template {
  type: string;
  parts: Array<["lit", string] | ["rand", string, number]>;
  secret: "all" | "rand";
}

interface Templates {
  seed: number;
  charsets: Record<string, string>;
  templates: Template[];
  contexts: string[];
}

export interface Canary {
  type: string;
  text: string;
  secrets: string[];
}

const TEMPLATES = JSON.parse(readFileSync(join(REPO, "tests", "fixtures", "canary-templates.json"), "utf8")) as Templates;

export class XorShift32 {
  private x: number;
  constructor(seed: number) {
    this.x = seed >>> 0 || 1;
  }
  next(): number {
    let x = this.x;
    x ^= x << 13;
    x >>>= 0;
    x ^= x >>> 17;
    x ^= x << 5;
    this.x = x >>> 0;
    return this.x;
  }
}

export function corpus(): Canary[] {
  const rng = new XorShift32(TEMPLATES.seed);
  const out: Canary[] = [];
  for (const tpl of TEMPLATES.templates) {
    for (const ctx of TEMPLATES.contexts) {
      let whole = "";
      const rand: string[] = [];
      for (const part of tpl.parts) {
        if (part[0] === "lit") {
          whole += part[1];
        } else {
          const cs = TEMPLATES.charsets[part[1]]!;
          let s = "";
          for (let i = 0; i < part[2]; i++) s += cs[rng.next() % cs.length];
          rand.push(s);
          whole += s;
        }
      }
      out.push({ type: tpl.type, text: ctx.replaceAll("{c}", whole), secrets: tpl.secret === "all" ? [whole] : rand });
    }
  }
  return out;
}
