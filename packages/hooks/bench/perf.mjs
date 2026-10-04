// Hook wall-time benchmark (Part L). Spawns each bundled hook N times as Claude Code would
// (node + script, JSON on stdin) and reports p50/p95 against the per-OS budgets.
//
//   node bench/perf.mjs [--runs 200] [--json] [--baseline bench/baseline.json] [--update-baseline]
//
// Exit 1 when a p95 exceeds its budget, or regresses > 20% against the stored baseline for
// this OS. Phase 0 measures the no-card case; 1,000-card fixtures arrive with routing.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHmac } from "node:crypto";

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, "..", "..", "..", "plugin", "dist");
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const RUNS = Number(opt("--runs", "200"));
const asJson = argv.includes("--json");
const baselinePath = opt("--baseline", join(here, "baseline.json"));
const updateBaseline = argv.includes("--update-baseline");
const os = process.platform === "win32" ? "windows" : process.platform === "darwin" ? "macos" : "linux";

// Wall p95 budgets in ms (Part L). capture is async in hooks.json, so it only needs to stay
// well under its own watchdog; 150/250 is a sanity bound, not a host requirement.
const BUDGETS = {
  "session-start.mjs": { linux: 150, macos: 150, windows: 250 },
  "route.mjs": { linux: 100, macos: 100, windows: 180 },
  "capture.mjs": { linux: 150, macos: 150, windows: 250 },
  "session-end.mjs": { linux: 150, macos: 150, windows: 250 },
};

function setupHome() {
  const root = mkdtempSync(join(tmpdir(), "praxis-perf-"));
  const key = "22".repeat(32);
  mkdirSync(join(root, "keys"), { recursive: true });
  mkdirSync(join(root, "snapshot"), { recursive: true });
  writeFileSync(join(root, "keys", "snapshot.key"), key);
  const body = {
    cards: [], db_version: 1, edges: [], generated_at: "2026-10-04T00:00:00.000Z", index: {},
    policy: { admin_commands: [], assistant_excerpt_chars: 1500, danger_rules: [], mode: "ask",
      protected_globs: [], store_assistant_text: "redacted-truncated", taint_on_webfetch: false },
    v: 1,
  };
  // Keys above are already sorted and the values contain nothing that needs escaping, so
  // JSON.stringify equals the canonical form here.
  const hmac = createHmac("sha256", Buffer.from(key, "hex")).update(JSON.stringify(body)).digest("hex");
  writeFileSync(join(root, "snapshot", "current.json"), JSON.stringify({ ...body, hmac_sha256: hmac }));
  return root;
}

const INPUTS = {
  "session-start.mjs": [[], { session_id: "perf", source: "startup", model: "m" }],
  "route.mjs": [[], { session_id: "perf", prompt: "add a dependency for parsing dates in the api layer" }],
  "capture.mjs": [["tool_ok"], { session_id: "perf", tool_name: "Bash", tool_input: { command: "pnpm test" },
    tool_response: { stdout: "ok\n".repeat(200), stderr: "" } }],
  "session-end.mjs": [[], { session_id: "perf", reason: "other" }],
};

function pct(sorted, p) {
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
}

const home = setupHome();
const env = { ...process.env, PRAXIS_HOME: home, PRAXIS_NO_SPAWN: "1" };
delete env.PRAXIS_MODE;
const results = {};
for (const [hook, [args, input]] of Object.entries(INPUTS)) {
  const script = join(dist, hook);
  const stdin = JSON.stringify({ cwd: home, ...input });
  for (let i = 0; i < 5; i++) spawnSync(process.execPath, [script, ...args], { input: stdin, env }); // warm cache
  const times = [];
  for (let i = 0; i < RUNS; i++) {
    const t0 = process.hrtime.bigint();
    const r = spawnSync(process.execPath, [script, ...args], { input: stdin, env });
    times.push(Number(process.hrtime.bigint() - t0) / 1e6);
    if (r.status !== 0) {
      console.error(`${hook} exited ${r.status}: ${r.stderr}`);
      process.exit(1);
    }
  }
  times.sort((a, b) => a - b);
  results[hook] = { p50: +pct(times, 50).toFixed(1), p95: +pct(times, 95).toFixed(1), budget: BUDGETS[hook][os] };
}

// Node start-up alone, for context: most of every hook's wall time.
const bare = [];
for (let i = 0; i < Math.min(RUNS, 50); i++) {
  const t0 = process.hrtime.bigint();
  spawnSync(process.execPath, ["-e", "0"]);
  bare.push(Number(process.hrtime.bigint() - t0) / 1e6);
}
bare.sort((a, b) => a - b);

const baseline = existsSync(baselinePath) ? JSON.parse(readFileSync(baselinePath, "utf8")) : {};
const failures = [];
for (const [hook, r] of Object.entries(results)) {
  if (r.p95 > r.budget) failures.push(`${hook}: p95 ${r.p95} ms > budget ${r.budget} ms`);
  const base = baseline[os]?.[hook]?.p95;
  if (base && r.p95 > base * 1.2) failures.push(`${hook}: p95 ${r.p95} ms regressed > 20% vs baseline ${base} ms`);
}

if (updateBaseline) {
  baseline[os] = Object.fromEntries(Object.entries(results).map(([h, r]) => [h, { p95: r.p95 }]));
  writeFileSync(baselinePath, JSON.stringify(baseline, null, 2) + "\n");
}

const report = { os, node: process.version, runs: RUNS, node_startup_p50: +pct(bare, 50).toFixed(1), results, failures };
if (asJson) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log(`hook wall time, ${RUNS} runs, ${os}, node ${process.version} (bare node start p50 ${report.node_startup_p50} ms)`);
  console.log("| hook | p50 ms | p95 ms | budget p95 ms |");
  console.log("|---|---|---|---|");
  for (const [hook, r] of Object.entries(results)) console.log(`| ${hook} | ${r.p50} | ${r.p95} | ${r.budget} |`);
  for (const f of failures) console.log(`FAIL ${f}`);
}
process.exit(failures.length ? 1 : 0);
