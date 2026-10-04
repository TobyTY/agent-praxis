// Project identity from the filesystem only: no `git` process (Part D.2 forbids blocking
// spawns). Reads .git, HEAD, packed-refs and config directly.
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { sha256 } from "./spool.js";
import { redactText } from "./redact.js";

export interface ProjectInfo {
  projectId: string;
  rootHash: string;
  gitHead: string | null;
  isGit: boolean;
}

/** Normalize separators and, on case-insensitive platforms, case (Rule A10). */
export function canonicalPath(p: string, platform: NodeJS.Platform = process.platform): string {
  let out = resolve(p).replace(/\\/g, "/");
  if (out.startsWith("//?/")) out = out.slice(4);
  if (out.length > 1 && out.endsWith("/")) out = out.slice(0, -1);
  return platform === "win32" || platform === "darwin" ? out.toLowerCase() : out;
}

interface GitLayout {
  root: string;
  gitDir: string;
  commonDir: string;
}

export function findGit(start: string): GitLayout | null {
  let dir = resolve(start);
  for (let i = 0; i < 64; i++) {
    const dotGit = join(dir, ".git");
    if (existsSync(dotGit)) {
      try {
        if (statSync(dotGit).isDirectory()) return { root: dir, gitDir: dotGit, commonDir: dotGit };
        // Worktree or submodule: ".git" is a file containing "gitdir: <path>".
        const m = /^gitdir:\s*(.+)$/m.exec(readFileSync(dotGit, "utf8"));
        if (m?.[1]) {
          const gitDir = resolve(dir, m[1].trim());
          let commonDir = gitDir;
          const commonFile = join(gitDir, "commondir");
          if (existsSync(commonFile)) commonDir = resolve(gitDir, readFileSync(commonFile, "utf8").trim());
          return { root: dir, gitDir, commonDir };
        }
      } catch {
        return null;
      }
    }
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
  return null;
}

export function readHead(git: GitLayout): string | null {
  try {
    const head = readFileSync(join(git.gitDir, "HEAD"), "utf8").trim();
    const ref = /^ref:\s*(.+)$/.exec(head)?.[1];
    if (!ref) return /^[0-9a-f]{40,64}$/.test(head) ? head : null;
    for (const base of [git.gitDir, git.commonDir]) {
      const refPath = join(base, ...ref.split("/"));
      if (existsSync(refPath)) return readFileSync(refPath, "utf8").trim();
    }
    const packed = join(git.commonDir, "packed-refs");
    if (existsSync(packed)) {
      for (const line of readFileSync(packed, "utf8").split("\n")) {
        const [sha, name] = line.trim().split(" ");
        if (name === ref && sha) return sha;
      }
    }
  } catch {
    /* unreadable repository state is not an error for capture */
  }
  return null;
}

export function readOriginUrl(git: GitLayout): string {
  try {
    const config = readFileSync(join(git.commonDir, "config"), "utf8");
    const section = /\[remote\s+"origin"\]([\s\S]*?)(?=\n\s*\[|$)/.exec(config)?.[1] ?? "";
    const url = /^\s*url\s*=\s*(.+)$/m.exec(section)?.[1]?.trim() ?? "";
    // Credentials embedded in a remote URL must not influence or leak through the id.
    return redactText(url);
  } catch {
    return "";
  }
}

export function projectInfo(cwd: string): ProjectInfo {
  const git = findGit(cwd);
  const root = canonicalPath(git ? git.root : cwd);
  const remote = git ? readOriginUrl(git) : "";
  return {
    projectId: "prj_" + sha256(`${root}\n${remote}`).slice(0, 16),
    rootHash: sha256(root),
    gitHead: git ? readHead(git) : null,
    isGit: git !== null,
  };
}

