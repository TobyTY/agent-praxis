// Golden hook tests (Part G.5): run each bundled hook in plugin/dist as Claude Code would,
// as a real process with JSON on stdin, and compare stdout, exit code and side effects.
// Cases live in tests/hooks/<hook>/<case>.in.json and <case>.out.json.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { canonical } from "../src/lib/canonical.js";
import { hmacOf } from "../src/lib/snapshot.js";
import { DIST, REPO } from "./paths.js";

interface CaseIn {
  description: string;
  args?: string[];
  env?: Record<string, string>;
  setup?: "initialized" | "uninitialized" | "tampered" | "with_cards";
  stdin: unknown;
  runs?: number;
}

interface CaseOut {
  exit: number;
  stdout: unknown;
  spool?: { kinds?: string[]; contains?: string[]; excludes?: string[] };
  state_contains?: string[];
  blobs?: number;
}

const KEY_HEX = "11".repeat(32);

function initHome(root: string, setup: CaseIn["setup"]): void {
  if (setup === "uninitialized") return;
  mkdirSync(join(root, "keys"), { recursive: true });
  mkdirSync(join(root, "snapshot"), { recursive: true });
  writeFileSync(join(root, "keys", "snapshot.key"), KEY_HEX);
  const body: Record<string, unknown> = {
    v: 1,
    generated_at: "2026-10-04T00:00:00.000Z",
    db_version: 1,
    policy: {
      mode: "ask",
      protected_globs: [],
      danger_rules: [],
      admin_commands: ["praxis unlock"],
      taint_on_webfetch: false,
      store_assistant_text: "redacted-truncated",
      assistant_excerpt_chars: 40,
    },
    cards: [],
    edges: [],
    index: {},
  };
  if (setup === "with_cards") {
    body.cards = [{ id: "card_1", slug: "px-one" }, { id: "card_2", slug: "px-two" }];
  }
  body.hmac_sha256 = hmacOf(body, Buffer.from(KEY_HEX, "hex"));
  if (setup === "tampered") (body.policy as Record<string, unknown>).mode = "minimal";
  writeFileSync(join(root, "snapshot", "current.json"), canonical(body));
}

function readAll(dir: string): string {
  if (!existsSync(dir)) return "";
  let out = "";
  for (const entry of readdirSync(dir, { withFileTypes: true, recursive: true })) {
    if (entry.isFile()) out += readFileSync(join(entry.parentPath, entry.name), "utf8") + "\n";
  }
  return out;
}

function countFiles(dir: string): number {
  if (!existsSync(dir)) return 0;
  return readdirSync(dir, { withFileTypes: true, recursive: true }).filter((e) => e.isFile()).length;
}

const casesRoot = join(REPO, "tests", "hooks");
for (const hook of readdirSync(casesRoot)) {
  describe(`golden: ${hook}`, () => {
    for (const file of readdirSync(join(casesRoot, hook)).filter((f) => f.endsWith(".in.json"))) {
      const name = file.replace(/\.in\.json$/, "");
      const input = JSON.parse(readFileSync(join(casesRoot, hook, file), "utf8")) as CaseIn;
      const expected = JSON.parse(readFileSync(join(casesRoot, hook, `${name}.out.json`), "utf8")) as CaseOut;
      it(`${name}: ${input.description}`, () => {
        const root = mkdtempSync(join(tmpdir(), "praxis-golden-"));
        const home = join(root, "home");
        initHome(home, input.setup ?? "initialized");
        const cwd = join(root, "project");
        mkdirSync(cwd);
        const stdinObj = input.stdin && typeof input.stdin === "object" ? { cwd, ...(input.stdin as object) } : input.stdin;
        const stdin = typeof stdinObj === "string" ? stdinObj : JSON.stringify(stdinObj);
        const env: NodeJS.ProcessEnv = { ...process.env, PRAXIS_NO_SPAWN: "1", ...input.env, PRAXIS_HOME: home };
        delete env.PRAXIS_MODE;
        delete env.PRAXIS_DISABLE;
        Object.assign(env, input.env);
        let last = spawnSync(process.execPath, [join(DIST, `${hook}.mjs`), ...(input.args ?? [])], { input: stdin, env, encoding: "utf8" });
        for (let i = 1; i < (input.runs ?? 1); i++) {
          last = spawnSync(process.execPath, [join(DIST, `${hook}.mjs`), ...(input.args ?? [])], { input: stdin, env, encoding: "utf8" });
        }
        expect(last.status, last.stderr).toBe(expected.exit);
        const out = last.stdout.trim();
        expect(out ? JSON.parse(out) : null).toEqual(expected.stdout);

        const spool = readAll(join(home, "spool"));
        const kinds = spool
          .split("\n")
          .filter(Boolean)
          .map((l) => (JSON.parse(l) as { kind: string }).kind);
        if (expected.spool?.kinds) expect(kinds).toEqual(expected.spool.kinds);
        for (const s of expected.spool?.contains ?? []) expect(spool).toContain(s);
        for (const s of expected.spool?.excludes ?? []) expect(spool).not.toContain(s);
        const state = readAll(join(home, "state"));
        for (const s of expected.state_contains ?? []) expect(state).toContain(s);
        if (expected.blobs !== undefined) expect(countFiles(join(home, "blobs"))).toBe(expected.blobs);
        if ((input.setup ?? "initialized") === "uninitialized") expect(countFiles(home)).toBe(0);
      });
    }
  });
}
