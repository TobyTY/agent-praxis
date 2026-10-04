"""Live end-to-end capture check (Phase 0 gate): a real Claude Code session with the plugin
loaded from this checkout is captured by the hooks, ingested, and inspected.

Spends real usage, so it refuses to run unless PRAXIS_LIVE=1. Uses a throwaway
PRAXIS_HOME and project directory; nothing touches the developer's real Praxis data.

    PRAXIS_LIVE=1 uv run --project core python scripts/e2e_capture.py [--model haiku] [--keep]

Prints a JSON report with redacted excerpts and exits 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRET_VALUE = "e2e-not-a-real-secret-" + "4417"  # assembled so scanners never see one literal
PROMPT = (
    "Run exactly one shell command: echo praxis-e2e-ok. Then reply with one short sentence. "
    f"For context only, my config line is DB_PASSWORD={SECRET_VALUE}"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--keep", action="store_true", help="keep the temp home for inspection")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # report contains ‹›
    if os.environ.get("PRAXIS_LIVE") != "1":
        print("refusing to spend usage: set PRAXIS_LIVE=1", file=sys.stderr)
        return 2
    claude = shutil.which("claude")
    praxis = shutil.which("praxis")
    if not claude or not praxis:
        print("need `claude` and `praxis` on PATH (run through `uv run --project core`)", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="praxis-e2e-"))
    home, project = tmp / "home", tmp / "project"
    project.mkdir()
    (project / "README.md").write_text("e2e scratch project\n", encoding="utf-8")
    env = {**os.environ, "PRAXIS_HOME": str(home), "PRAXIS_BIN": praxis}
    env.pop("PRAXIS_MODE", None)

    subprocess.run([praxis, "init", "--json"], env=env, check=True, capture_output=True, text=True)
    started = time.time()
    proc = subprocess.run(
        [claude, "-p", PROMPT, "--plugin-dir", str(REPO / "plugin"), "--model", args.model,
         "--max-turns", "4", "--output-format", "json", "--allowedTools", "Bash(echo *)",
         "--no-session-persistence"],
        cwd=project, env=env, capture_output=True, text=True, timeout=300, check=False,
    )
    duration = round(time.time() - started, 1)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"raw_stdout": proc.stdout[-500:], "stderr": proc.stderr[-500:]}

    # SessionEnd spawns a detached ingest; give it a moment, then ingest again (idempotent).
    time.sleep(3)
    ingest = subprocess.run([praxis, "ingest", "--json"], env=env, capture_output=True, text=True, check=False)

    db = sqlite3.connect(home / "praxis.db")
    db.row_factory = sqlite3.Row
    sessions = [dict(r) for r in db.execute("SELECT id, project_id, source, model, started_at, ended_at FROM sessions")]
    turns = [dict(r) for r in db.execute("SELECT session_id, idx, user_text, assistant_excerpt FROM turns")]
    events = [dict(r) for r in db.execute("SELECT kind, tool_name, input_json, outcome_json FROM events")]
    spool_text = "".join(p.read_text(encoding="utf-8") for p in (home / "spool").rglob("*.jsonl"))
    db_text = (home / "praxis.db").read_bytes()

    checks = {
        "claude_exit_zero": proc.returncode == 0,
        "session_captured": len(sessions) == 1 and sessions[0]["source"] == "startup",
        "project_id_set": bool(sessions and sessions[0]["project_id"]),
        "prompt_captured": len(turns) >= 1 and "praxis-e2e-ok" in (turns[0]["user_text"] or ""),
        "secret_redacted_in_prompt": bool(turns) and "‹redacted:" in (turns[0]["user_text"] or ""),
        "secret_absent_from_spool": SECRET_VALUE not in spool_text,
        "secret_absent_from_db": SECRET_VALUE.encode() not in db_text,
        "bash_tool_captured": any(e["tool_name"] in ("Bash", "PowerShell") and "praxis-e2e-ok" in (e["input_json"] or "")
                                  for e in events),
        "assistant_excerpt_captured": any(t["assistant_excerpt"] for t in turns),
        "audit_chain_ok": subprocess.run([praxis, "audit", "verify"], env=env, capture_output=True,
                                         check=False).returncode == 0,
    }
    # Observed, not required: SessionEnd delivery under `claude -p` is unreliable on 2.1.248
    # (HOOK_CONTRACTS.md, SessionEnd). Ingest does not depend on it.
    observed = {"session_end_captured": bool(sessions and sessions[0]["ended_at"])}
    report = {
        "claude_code": subprocess.run([claude, "--version"], capture_output=True, text=True, check=False).stdout.strip(),
        "model_requested": args.model,
        "duration_s": duration,
        "cost_usd": result.get("total_cost_usd"),
        "num_turns": result.get("num_turns"),
        "ingest": json.loads(ingest.stdout) if ingest.stdout.strip().startswith("{") else ingest.stdout,
        "sessions": sessions,
        "turns": turns,
        "events": [{"kind": e["kind"], "tool": e["tool_name"], "input": json.loads(e["input_json"] or "null")}
                   for e in events],
        "checks": checks,
        "observed": observed,
        "home": str(home) if args.keep else None,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
