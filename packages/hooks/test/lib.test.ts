import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { canonical } from "../src/lib/canonical.js";
import { homePaths } from "../src/lib/env.js";
import { canonicalPath, findGit, projectInfo, readHead, readOriginUrl } from "../src/lib/project.js";
import { hmacOf, loadSnapshot } from "../src/lib/snapshot.js";
import { appendSpool, MAX_LINE_BYTES, safeSession } from "../src/lib/spool.js";
import { routable } from "../src/handlers/route.js";
import { findPraxis } from "../src/handlers/session-end.js";
import { REPO } from "./paths.js";

const fixture = (name: string) => JSON.parse(readFileSync(join(REPO, "tests", "fixtures", name), "utf8"));
const tmp = () => mkdtempSync(join(tmpdir(), "praxis-test-"));

describe("canonical JSON parity with Python", () => {
  for (const c of fixture("canonical.json").cases as Array<{ value: unknown; expected: string }>) {
    it(c.expected.slice(0, 40), () => expect(canonical(c.value)).toBe(c.expected));
  }
});

describe("snapshot HMAC", () => {
  it("verifies the Python-signed fixture", () => {
    const fx = fixture("snapshot-hmac.json");
    expect(hmacOf(fx.snapshot, Buffer.from(fx.key_hex, "hex"))).toBe(fx.snapshot.hmac_sha256);
  });

  it("reports uninitialized, ok, and tampered states", () => {
    const root = tmp();
    const home = homePaths(root);
    expect(loadSnapshot(home).status).toBe("uninitialized");
    const fx = fixture("snapshot-hmac.json");
    mkdirSync(join(root, "keys"), { recursive: true });
    mkdirSync(join(root, "snapshot"), { recursive: true });
    writeFileSync(home.key, fx.key_hex);
    expect(loadSnapshot(home)).toEqual({ status: "invalid", reason: "snapshot missing" });
    writeFileSync(home.snapshot, JSON.stringify(fx.snapshot));
    expect(loadSnapshot(home).status).toBe("ok");
    writeFileSync(home.snapshot, JSON.stringify({ ...fx.snapshot, cards: [] }));
    expect(loadSnapshot(home)).toEqual({ status: "invalid", reason: "snapshot HMAC mismatch" });
    writeFileSync(home.snapshot, "{not json");
    expect(loadSnapshot(home).status).toBe("invalid");
  });
});

describe("project identity", () => {
  it("normalizes paths per platform", () => {
    expect(canonicalPath("C:\\Repo\\Src\\", "win32")).toBe("c:/repo/src");
    expect(canonicalPath("/Users/A/Repo", "darwin")).toBe("/users/a/repo");
    expect(canonicalPath("/home/a/Repo/", "linux")).toBe("/home/a/Repo");
    expect(canonicalPath("\\\\?\\C:\\Repo", "win32")).toBe("c:/repo");
  });

  it("reads HEAD, packed refs, origin and worktree layouts without git", () => {
    const repo = tmp();
    const git = join(repo, ".git");
    mkdirSync(join(git, "refs", "heads"), { recursive: true });
    writeFileSync(join(git, "HEAD"), "ref: refs/heads/main\n");
    writeFileSync(join(git, "packed-refs"), "# pack-refs\n" + "a".repeat(40) + " refs/heads/main\n");
    writeFileSync(
      join(git, "config"),
      '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://bot:' + "s3cr3tvalue" + "@git.example.com/r.git\n",
    );
    const layout = findGit(join(repo))!;
    expect(readHead(layout)).toBe("a".repeat(40));
    const origin = readOriginUrl(layout);
    expect(origin).not.toContain("s3cr3tvalue");
    writeFileSync(join(git, "refs", "heads", "main"), "b".repeat(40) + "\n");
    expect(readHead(layout)).toBe("b".repeat(40));

    const sub = join(repo, "deep", "dir");
    mkdirSync(sub, { recursive: true });
    const a = projectInfo(sub);
    const b = projectInfo(repo);
    expect(a.projectId).toBe(b.projectId);
    expect(a.projectId).toMatch(/^prj_[0-9a-f]{16}$/);
    expect(a.isGit).toBe(true);

    const wt = tmp();
    writeFileSync(join(wt, ".git"), `gitdir: ${git}\n`);
    expect(findGit(wt)?.commonDir).toBe(git);
  });

  it("falls back to the directory outside git", () => {
    const dir = tmp();
    const info = projectInfo(dir);
    expect(info.isGit).toBe(false);
    expect(info.gitHead).toBeNull();
  });
});

describe("spool", () => {
  it("uses the same session file name rule as Python", () => {
    expect(safeSession("abc-123_X")).toBe("abc-123_X");
    expect(safeSession("../../etc/passwd")).toBe("______etc_passwd");
    expect(safeSession("")).toBe("_");
    expect(safeSession("x".repeat(500))).toHaveLength(128);
  });

  it("moves oversized payloads into a blob", () => {
    const home = homePaths(tmp());
    appendSpool(home, {
      v: 1,
      ts: "2026-10-04T00:00:00.000Z",
      kind: "tool_ok",
      session_id: "s",
      input: { big: "x".repeat(MAX_LINE_BYTES) },
    });
    const text = readFileSync(join(home.spool, "2026-10-04", "s.jsonl"), "utf8");
    expect(Buffer.byteLength(text)).toBeLessThan(MAX_LINE_BYTES);
    const line = JSON.parse(text);
    expect(line.blob).toMatch(/^[0-9a-f]{64}$/);
    expect(readdirSync(home.blobs)).toHaveLength(1);
  });
});

describe("route", () => {
  it("skips short prompts, slash commands and opt-outs", () => {
    expect(routable("install the deps")).toBe(true);
    expect(routable("hi")).toBe(false);
    expect(routable("/review this pull request")).toBe(false);
    expect(routable("install the deps #px-off")).toBe(false);
  });
});

describe("session-end", () => {
  it("resolves praxis from PATH and never a .cmd shim on Windows", () => {
    const dir = tmp();
    writeFileSync(join(dir, "praxis.cmd"), "");
    expect(findPraxis({ PATH: dir }, "win32")).toBeNull();
    writeFileSync(join(dir, "praxis.exe"), "");
    expect(findPraxis({ PATH: dir }, "win32")).toBe(join(dir, "praxis.exe"));
    expect(findPraxis({ PRAXIS_BIN: join(dir, "praxis.exe"), PATH: "" }, "linux")).toBe(join(dir, "praxis.exe"));
  });
});
