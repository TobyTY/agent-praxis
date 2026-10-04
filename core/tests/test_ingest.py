from __future__ import annotations

import json
import sqlite3

from praxis import audit
from praxis.capture.ingest import ingest
from praxis.paths import Home

from . import spoolutil as su


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608


def test_session_roundtrip(home: Home, conn: sqlite3.Connection) -> None:
    su.session(home, "s1")
    stats = ingest(home, conn)
    assert stats.lines == 8 and stats.malformed == 0
    s = conn.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone()
    assert s["project_id"] == "prj_test" and s["model"] == "m1" and s["ended_at"]
    turns = conn.execute("SELECT idx, user_text, assistant_excerpt FROM turns ORDER BY idx").fetchall()
    assert [(t[0], t[1], t[2]) for t in turns] == [
        (0, "add a package please", "done"),
        (1, "now run the tests", None),
    ]
    events = conn.execute("SELECT kind, turn_idx, tool_name FROM events ORDER BY id").fetchall()
    assert [tuple(e) for e in events] == [
        ("tool_ok", 0, "Bash"),
        ("tool_fail", 0, "Bash"),
        ("tool_ok", 1, "Write"),
    ]
    assert _count(conn, "projects") == 1


def test_idempotent(home: Home, conn: sqlite3.Connection) -> None:
    su.session(home, "s1")
    ingest(home, conn)
    again = ingest(home, conn)
    assert again.lines == 0 and _count(conn, "events") == 3 and _count(conn, "turns") == 2


def test_incremental_and_partial_line(home: Home, conn: sqlite3.Connection) -> None:
    p = su.write(home, su.line("session_start", "s2", data={"source": "startup"}))
    with p.open("a", encoding="utf-8") as f:
        f.write('{"v":1,"ts":"t","kind":"prompt","session_id":"s2","data":{"text":"half')  # hook mid-write
    ingest(home, conn)
    assert _count(conn, "turns") == 0
    with p.open("a", encoding="utf-8") as f:
        f.write(' done"}}\n')
    stats = ingest(home, conn)
    assert stats.lines == 1 and _count(conn, "turns") == 1
    assert conn.execute("SELECT user_text FROM turns").fetchone()[0] == "half done"


def test_malformed_lines_counted_not_fatal(home: Home, conn: sqlite3.Connection) -> None:
    su.write(
        home,
        su.line("session_start", "s3"),
        raw='not json\n{"v":2}\n{"v":1,"kind":"nope","session_id":"s3","ts":"x"}\n',
    )
    stats = ingest(home, conn)
    assert stats.malformed == 3 and stats.lines == 4
    row = conn.execute("SELECT malformed FROM spool_files").fetchone()
    assert row[0] == 3


def test_oversized_line_rejected(home: Home, conn: sqlite3.Connection) -> None:
    big = su.line("prompt", "s4", data={"text": "x" * 70_000})
    stats = (su.write(home, big), ingest(home, conn))[1]
    assert stats.malformed == 1


def test_events_before_session_start(home: Home, conn: sqlite3.Connection) -> None:
    # Async capture can land before SessionStart's line; ingest must not drop it.
    su.write(
        home,
        su.line("tool_ok", "s5", tool="Read"),
        su.line("session_start", "s5", project_id="prj_x", data={"source": "resume", "model": "m"}),
    )
    ingest(home, conn)
    s = conn.execute("SELECT project_id, model FROM sessions WHERE id='s5'").fetchone()
    assert tuple(s) == ("prj_x", "m")


def test_second_pass_redaction(home: Home, conn: sqlite3.Connection) -> None:
    secret = "DB_PASSWORD=" + "q7Lm2xV9pR4t"
    su.write(home, su.line("session_start", "s6"), su.line("prompt", "s6", data={"text": f"use {secret}"}))
    ingest(home, conn)
    text = conn.execute("SELECT user_text FROM turns").fetchone()[0]
    assert "q7Lm2xV9pR4t" not in text and "‹redacted:kv:" in text


def test_audit_lines_go_to_chain(home: Home, conn: sqlite3.Connection) -> None:
    su.write(
        home,
        su.line(
            "audit",
            "s7",
            data={
                "actor": "hook",
                "action": "safe_mode_entered",
                "details": {"reason": "snapshot HMAC mismatch"},
            },
        ),
    )
    stats = ingest(home, conn)
    assert stats.audits == 1
    res = audit.verify(home.audit)
    assert res.ok
    last = json.loads(home.audit.read_text(encoding="utf-8").splitlines()[-1])
    assert last["action"] == "safe_mode_entered" and last["details"]["session_id"] == "s7"
    assert ingest(home, conn).audits == 0  # not duplicated


def test_truncated_file_restarts(home: Home, conn: sqlite3.Connection) -> None:
    p = su.session(home, "s8")
    ingest(home, conn)
    p.write_text(json.dumps(su.line("session_start", "s8")) + "\n", encoding="utf-8")
    stats = ingest(home, conn)
    assert stats.lines == 1  # re-read from offset 0, duplicates ignored by primary keys


def test_spool_line_schema_matches_hooks() -> None:
    from praxis.capture.ingest import KINDS

    schema = json.loads((su.REPO / "schemas" / "spool-line.schema.json").read_text(encoding="utf-8"))
    assert set(schema["properties"]["kind"]["enum"]) == KINDS
