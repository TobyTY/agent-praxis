// Environment switches shared by every hook (Rule A11, Part G.3).
import { homedir } from "node:os";
import { join, resolve } from "node:path";

export type PraxisMode = "normal" | "internal" | "replay";

export function praxisHome(env: NodeJS.ProcessEnv = process.env): string {
  const fromEnv = env.PRAXIS_HOME;
  if (fromEnv && fromEnv.trim()) {
    const p = fromEnv.trim();
    return resolve(p.startsWith("~") ? join(homedir(), p.slice(1)) : p);
  }
  return join(homedir(), ".praxis");
}

export function praxisMode(env: NodeJS.ProcessEnv = process.env): PraxisMode {
  const m = env.PRAXIS_MODE;
  return m === "internal" || m === "replay" ? m : "normal";
}

export function isDisabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.PRAXIS_DISABLE === "1";
}

export interface HomePaths {
  root: string;
  spool: string;
  state: string;
  blobs: string;
  snapshot: string;
  key: string;
  logs: string;
}

export function homePaths(root: string): HomePaths {
  return {
    root,
    spool: join(root, "spool"),
    state: join(root, "state"),
    blobs: join(root, "blobs", "sha256"),
    snapshot: join(root, "snapshot", "current.json"),
    key: join(root, "keys", "snapshot.key"),
    logs: join(root, "logs"),
  };
}
