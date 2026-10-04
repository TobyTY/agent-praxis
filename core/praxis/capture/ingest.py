"""Spool to SQLite (Part E.6).

Idempotent: each spool file has a stored byte offset, and only complete lines (ending in
a newline) past that offset are read. A line still being appended by a hook is picked up
on the next run. Malformed lines are skipped and counted, never fatal.

Every string is redacted a second time here (ADR 0004), so a rule added after capture
still cleans older lines before they reach the database.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from praxis import audit
from praxis.capture.redact import redact_value
from praxis.paths import Home

KINDS = {
    "session_start",
    "prompt",
    "tool_ok",
    "tool_fail",
    "turn_end",
    "model_switch",
    "activation",
    "guard",
    "audit",
    "session_end",
}
EVENT_KINDS = {"tool_ok", "tool_fail", "model_switch", "activation", "guard"}
MAX_LINE_BYTES = 64 * 1024


@dataclass
class IngestStats:
    files: int = 0
    lines: int = 0
    malformed: int = 0
    sessions: int = 0
    turns: int = 0
    events: int = 0
    audits: int = 0
    by_file: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "by_file"}


def _valid(line: Any) -> bool:
    return (
        isinstance(line, dict)
        and line.get("v") == 1
        and line.get("kind") in KINDS
        and isinstance(line.get("session_id"), str)
        and bool(line["session_id"])
        and isinstance(line.get("ts"), str)
    )


def _ensure_session(conn: sqlite3.Connection, line: dict[str, Any], stats: IngestStats) -> None:
    cur = conn.execute(
        "INSERT OR IGNORE INTO sessions (id, started_at) VALUES (?, ?)",
        (line["session_id"], line["ts"]),
    )
    stats.sessions += cur.rowcount


def _current_turn(conn: sqlite3.Connection, session_id: str) -> int | None:
    row = conn.execute("SELECT MAX(idx) FROM turns WHERE session_id = ?", (session_id,)).fetchone()
    return None if row[0] is None else int(row[0])


def _append_audit(home: Home, line: dict[str, Any]) -> None:
    data = line.get("data") or {}
    audit.append(
        home.audit,
        actor=str(data.get("actor", "hook")),
        action=str(data.get("action", "unknown")),
        target=data.get("target"),
        details={**(data.get("details") or {}), "session_id": line["session_id"], "hook_ts": line["ts"]},
    )


def _apply(conn: sqlite3.Connection, line: dict[str, Any], stats: IngestStats) -> None:
    kind = line["kind"]
    sid = line["session_id"]
    data = line.get("data") or {}

    if kind == "session_start":
        project_id = line.get("project_id")
        if project_id:
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, root_hash, created_at) VALUES (?, ?, ?)",
                (project_id, data.get("root_hash") or "", line["ts"]),
            )
        cur = conn.execute(
            "INSERT OR IGNORE INTO sessions (id, project_id, started_at, source, model, cc_version, git_head)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                project_id,
                line["ts"],
                data.get("source"),
                data.get("model"),
                data.get("cc_version"),
                data.get("git_head"),
            ),
        )
        stats.sessions += cur.rowcount
        if cur.rowcount == 0:
            # Session row was created earlier by a line that arrived first, or this is a
            # resume/clear: keep the first start time, fill fields that were missing.
            conn.execute(
                "UPDATE sessions SET project_id = COALESCE(project_id, ?), source = COALESCE(source, ?),"
                " model = COALESCE(?, model), git_head = COALESCE(git_head, ?) WHERE id = ?",
                (project_id, data.get("source"), data.get("model"), data.get("git_head"), sid),
            )
        return

    _ensure_session(conn, line, stats)

    if kind == "prompt":
        last = _current_turn(conn, sid)
        idx = 0 if last is None else last + 1
        conn.execute(
            "INSERT INTO turns (id, session_id, idx, prompt_id, user_text) VALUES (?, ?, ?, ?, ?)",
            (f"{sid}:{idx}", sid, idx, line.get("prompt_id"), data.get("text")),
        )
        stats.turns += 1
    elif kind == "turn_end":
        current = _current_turn(conn, sid)
        if current is not None:
            conn.execute(
                "UPDATE turns SET assistant_excerpt = ? WHERE session_id = ? AND idx = ?",
                (data.get("excerpt"), sid, current),
            )
    elif kind in EVENT_KINDS:
        conn.execute(
            "INSERT INTO events (session_id, turn_idx, ts, kind, tool_name, tool_use_id, agent_id,"
            " input_json, outcome_json, blob) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                _current_turn(conn, sid),
                line["ts"],
                kind,
                line.get("tool"),
                line.get("tool_use_id"),
                line.get("agent_id"),
                json.dumps(line.get("input"), ensure_ascii=False) if line.get("input") is not None else None,
                json.dumps(line.get("outcome") or data or None, ensure_ascii=False),
                line.get("blob"),
            ),
        )
        stats.events += 1
        if kind == "model_switch" and data.get("to"):
            conn.execute("UPDATE sessions SET model = ? WHERE id = ?", (data["to"], sid))
    elif kind == "session_end":
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (line["ts"], sid))


def spool_files(home: Home) -> list[Path]:
    if not home.spool.exists():
        return []
    return sorted(p for p in home.spool.glob("*/*.jsonl") if p.is_file())


def ingest(home: Home, conn: sqlite3.Connection) -> IngestStats:
    stats = IngestStats()
    with audit.file_lock(home.root / "ingest"):
        for path in spool_files(home):
            rel = path.relative_to(home.root).as_posix()
            row = conn.execute("SELECT offset, malformed FROM spool_files WHERE path = ?", (rel,)).fetchone()
            offset = int(row["offset"]) if row else 0
            malformed = int(row["malformed"]) if row else 0
            size = path.stat().st_size
            if size < offset:
                # Truncated or replaced (forget, manual edit): start over for this file.
                offset = 0
            if size == offset:
                continue
            stats.files += 1
            with path.open("rb") as f:
                f.seek(offset)
                chunk = f.read(size - offset)
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            complete = chunk[: end + 1]
            pending_audit: list[dict[str, Any]] = []
            conn.execute("BEGIN IMMEDIATE")
            try:
                for raw in complete.split(b"\n")[:-1]:
                    if not raw.strip():
                        continue
                    stats.lines += 1
                    try:
                        if len(raw) > MAX_LINE_BYTES:
                            raise ValueError("line too long")
                        line = json.loads(raw.decode("utf-8"))
                        if not _valid(line):
                            raise ValueError("invalid spool line")
                    except (ValueError, UnicodeDecodeError):
                        stats.malformed += 1
                        malformed += 1
                        continue
                    line = redact_value(line)
                    if line["kind"] == "audit":
                        pending_audit.append(line)
                    else:
                        _apply(conn, line, stats)
                conn.execute(
                    "INSERT INTO spool_files (path, offset, malformed, updated_at) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(path) DO UPDATE SET offset = excluded.offset,"
                    " malformed = excluded.malformed, updated_at = excluded.updated_at",
                    (rel, offset + end + 1, malformed, audit.now_iso()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            # Audit entries go to the chain only after the offset commit, so a failed
            # transaction never leaves a duplicate chain entry on retry.
            for line in pending_audit:
                _append_audit(home, line)
                stats.audits += 1
            stats.by_file[rel] = stats.lines
    return stats
