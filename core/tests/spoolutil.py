"""Write spool lines the way the hooks do, for control-plane tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from praxis.forget import safe_session
from praxis.paths import Home

from .canaries import REPO

__all__ = ["REPO", "line", "session", "spool_path", "write"]


def spool_path(home: Home, session_id: str, day: str = "2026-10-04") -> Path:
    p = home.spool / day / f"{safe_session(session_id)}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def line(kind: str, session_id: str, ts: str = "2026-10-04T10:00:00.000Z", **kw: Any) -> dict[str, Any]:
    return {"v": 1, "ts": ts, "kind": kind, "session_id": session_id, **kw}


def write(home: Home, *lines: dict[str, Any], raw: str | None = None, day: str = "2026-10-04") -> Path:
    sid = lines[0]["session_id"] if lines else "raw"
    p = spool_path(home, sid, day)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        if raw is not None:
            f.write(raw)
    return p


def session(home: Home, sid: str, project: str = "prj_test", text: str = "add a package please") -> Path:
    return write(
        home,
        line(
            "session_start",
            sid,
            project_id=project,
            data={"source": "startup", "model": "m1", "root_hash": "rh"},
        ),
        line("prompt", sid, data={"text": text}),
        line(
            "tool_ok",
            sid,
            tool="Bash",
            tool_use_id="t1",
            input={"command": "pnpm add x"},
            outcome={"exit": 0},
        ),
        line(
            "tool_fail", sid, tool="Bash", tool_use_id="t2", input={"command": "npm i"}, outcome={"exit": 1}
        ),
        line("turn_end", sid, data={"excerpt": "done"}),
        line("prompt", sid, data={"text": "now run the tests"}),
        line(
            "tool_ok",
            sid,
            tool="Write",
            tool_use_id="t3",
            input={"file_path": "/p/a.ts"},
            outcome={"bytes": 1},
            blob="ab" * 32,
        ),
        line("session_end", sid, data={"reason": "other"}),
    )
