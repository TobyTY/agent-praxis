"""`praxis forget` (Part F.4): delete trace data for a session, a project, or everything.

Deletes spool files, state logs, database rows, blobs and derived candidates, then
VACUUMs so deleted rows do not survive in free pages. The audit log records that a
deletion happened and its counts, never the deleted content.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from praxis import audit
from praxis.paths import Home

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def safe_session(session_id: str) -> str:
    """File-name form of a session id. Must match packages/hooks/src/lib/spool.ts."""
    return _UNSAFE.sub("_", session_id)[:128] or "_"


@dataclass
class ForgetResult:
    sessions: int = 0
    spool_files: int = 0
    blobs: int = 0
    rows: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


# Children first so foreign keys never block a delete.
_SESSION_TABLES = [
    ("usage", "session_id"),
    ("events", "session_id"),
    ("turns", "session_id"),
]


def _blob_refs_in_spool(path: Path) -> set[str]:
    refs: set[str] = set()
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for raw in f:
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(line, dict) and isinstance(line.get("blob"), str):
                    refs.add(line["blob"])
    except OSError:
        pass
    return refs


def _delete_blob(home: Home, digest: str) -> bool:
    try:
        path = home.blob_path(digest)
    except ValueError:
        return False
    if path.exists():
        path.unlink()
        return True
    return False


def _vacuum(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def forget_sessions(home: Home, conn: sqlite3.Connection, session_ids: list[str]) -> ForgetResult:
    result = ForgetResult()
    blobs: set[str] = set()
    for sid in session_ids:
        safe = safe_session(sid)
        for path in home.spool.glob(f"*/{safe}.jsonl"):
            blobs |= _blob_refs_in_spool(path)
            conn.execute("DELETE FROM spool_files WHERE path = ?", (path.relative_to(home.root).as_posix(),))
            path.unlink()
            result.spool_files += 1
        (home.state / f"{safe}.jsonl").unlink(missing_ok=True)
        blobs |= {
            r[0]
            for r in conn.execute("SELECT blob FROM events WHERE session_id = ? AND blob IS NOT NULL", (sid,))
        }
        conn.execute("BEGIN IMMEDIATE")
        try:
            signal_ids = [r[0] for r in conn.execute("SELECT id FROM signals WHERE session_id = ?", (sid,))]
            if signal_ids:
                marks = ",".join("?" * len(signal_ids))
                case_ids = [
                    r[0]
                    for r in conn.execute(
                        f"SELECT id FROM test_cases WHERE signal_id IN ({marks})",  # noqa: S608
                        signal_ids,
                    )
                ]
                if case_ids:
                    cmarks = ",".join("?" * len(case_ids))
                    n = conn.execute(f"DELETE FROM runs WHERE test_case_id IN ({cmarks})", case_ids).rowcount  # noqa: S608
                    result.rows["runs"] = result.rows.get("runs", 0) + n
                    n = conn.execute(f"DELETE FROM test_cases WHERE id IN ({cmarks})", case_ids).rowcount  # noqa: S608
                    result.rows["test_cases"] = result.rows.get("test_cases", 0) + n
                n = conn.execute(f"DELETE FROM signals WHERE id IN ({marks})", signal_ids).rowcount  # noqa: S608
                result.rows["signals"] = result.rows.get("signals", 0) + n
            for table, col in _SESSION_TABLES:
                n = conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (sid,)).rowcount  # noqa: S608
                result.rows[table] = result.rows.get(table, 0) + n
            n = conn.execute("DELETE FROM sessions WHERE id = ?", (sid,)).rowcount
            result.sessions += n
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    still_used = {r[0] for r in conn.execute("SELECT blob FROM events WHERE blob IS NOT NULL")}
    for digest in blobs - still_used:
        result.blobs += _delete_blob(home, digest)
    _vacuum(conn)
    return result


def forget_project(home: Home, conn: sqlite3.Connection, project_id: str) -> ForgetResult:
    sids = [r[0] for r in conn.execute("SELECT id FROM sessions WHERE project_id = ?", (project_id,))]
    result = forget_sessions(home, conn, sids)
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return result


def forget_all(home: Home, conn: sqlite3.Connection) -> ForgetResult:
    result = ForgetResult()
    result.spool_files = sum(1 for _ in home.spool.glob("*/*.jsonl")) if home.spool.exists() else 0
    result.blobs = sum(1 for p in home.blobs.rglob("*") if p.is_file()) if home.blobs.exists() else 0
    for d in (home.spool, home.state, home.blobs, home.replay, home.logs):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Derived candidates: cards that never passed verification carry trace-derived text.
        cand = [r[0] for r in conn.execute("SELECT id FROM cards WHERE status IN ('candidate', 'rejected')")]
        if cand:
            marks = ",".join("?" * len(cand))
            conn.execute(f"DELETE FROM edges WHERE src IN ({marks}) OR dst IN ({marks})", cand + cand)  # noqa: S608
            conn.execute(f"DELETE FROM card_versions WHERE card_id IN ({marks})", cand)  # noqa: S608
            result.rows["cards"] = conn.execute(f"DELETE FROM cards WHERE id IN ({marks})", cand).rowcount  # noqa: S608
        for table in (
            "runs",
            "test_cases",
            "signals",
            "usage",
            "events",
            "turns",
            "sessions",
            "projects",
            "spool_files",
        ):
            result.rows[table] = conn.execute(f"DELETE FROM {table}").rowcount  # noqa: S608
        result.sessions = result.rows["sessions"]
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    _vacuum(conn)
    return result


def record(home: Home, scope: str, target: str | None, result: ForgetResult) -> None:
    audit.append(
        home.audit, actor="user", action="forget", target=target, details={"scope": scope, **result.as_dict()}
    )
