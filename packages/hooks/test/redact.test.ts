import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { isSensitivePath, redactText, redactValue, shannonBits, token } from "../src/lib/redact.js";
import { REDACTION_RULES } from "../src/generated/redaction-rules.js";
import { corpus } from "./canaries.js";
import { REPO } from "./paths.js";

const CORPUS = corpus();
const leaks = (text: string, secrets: string[]) =>
  secrets.filter((s) => text.includes(s) || (s.length >= 16 && text.includes(s.slice(4, 16))));

describe("redaction canary corpus (Part M.4)", () => {
  it("has at least 200 canaries", () => {
    expect(CORPUS.length).toBeGreaterThanOrEqual(200);
  });

  it("removes 100% of canaries", () => {
    const leaked = CORPUS.filter((c) => leaks(redactText(c.text), c.secrets).length > 0);
    expect(leaked.map((c) => c.type)).toEqual([]);
  });

  it("matches the Python implementation byte for byte (shared digest)", () => {
    const h = createHash("sha256");
    for (const c of CORPUS) {
      h.update(redactText(c.text), "utf8");
      h.update("\n");
    }
    const expected = readFileSync(join(REPO, "tests", "fixtures", "redaction-corpus.sha256"), "ascii").trim();
    expect(h.digest("hex")).toBe(expected);
  });

  it("is idempotent", () => {
    for (const c of CORPUS) {
      const once = redactText(c.text);
      expect(redactText(once)).toBe(once);
    }
  });
});

describe("redaction rules", () => {
  it("compile without flags beyond the shared subset", () => {
    for (const r of REDACTION_RULES.rules) expect(() => new RegExp(r.pattern, "g" + r.flags)).not.toThrow();
  });

  it("produce stable tokens that hide the value", () => {
    expect(token("kv", "hunter2hunter2")).toBe(token("kv", "hunter2hunter2"));
    expect(token("kv", "hunter2hunter2")).toMatch(/^‹redacted:kv:[0-9a-f]{8}›$/);
  });

  it("leave benign developer text alone", () => {
    const benign = [
      "pnpm install && pnpm test",
      "git commit -m 'fix: handle empty input'",
      "src/components/UserProfileCard.tsx",
      "commit 3f2a9c1b8e7d6f5a4b3c2d1e0f9a8b7c6d5e4f3a",
      "550e8400-e29b-41d4-a716-446655440000",
      "C:\\Users\\dev\\project\\README.md",
    ];
    for (const b of benign) expect(redactText(b)).toBe(b);
  });

  it("recurse into values", () => {
    const out = redactValue({ a: ["DB_PASSWORD=abcdefghijkl"], n: 3 }) as { a: string[]; n: number };
    expect(out.a[0]).not.toContain("abcdefghijkl");
    expect(out.n).toBe(3);
  });

  it("compute entropy", () => {
    expect(shannonBits("")).toBe(0);
    expect(shannonBits("ab")).toBeCloseTo(1);
  });

  it("flag sensitive paths", () => {
    for (const p of [".env", "/repo/.env.local", "C:\\keys\\server.pem", "id_ed25519", "credentials.json"]) {
      expect(isSensitivePath(p)).toBe(true);
    }
    for (const p of [".env.example", "id_ed25519.pub", "src/env.ts"]) expect(isSensitivePath(p)).toBe(false);
  });
});

describe("redaction fuzzing", () => {
  it("never throws on 10,000 random inputs", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 300, unit: "binary" }), (s) => typeof redactText(s) === "string"),
      { numRuns: 10_000 },
    );
  });

  it("removes canaries surrounded by random noise", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 80 }), fc.constantFrom(...CORPUS), fc.string({ maxLength: 80 }), (a, c, b) => {
        const out = redactText(`${a} ${c.text} ${b}`);
        return c.secrets.every((s) => !out.includes(s));
      }),
      { numRuns: 500 },
    );
  });
});
