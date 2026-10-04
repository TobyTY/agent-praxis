from __future__ import annotations

import sqlite3
from pathlib import Path

from praxis import audit, forget
from praxis.capture.ingest import ingest
from praxis.paths import Home

from . import spoolutil as su

CANARY = "PRAXIS_CANARY_forget_7f3a91"


def _trace_files(home: Home) -> list[Path]:
    return [
        p
        for d in (home.spool, home.state, home.blobs, home.replay, home.logs)
        for p in d.rglob("*")
        if p.is_file()
    ]


def _files_containing(home: Home, needle: str) -> list[str]:
    hits = []
    for p in home.root.rglob("*"):
        if p.is_file() and needle.encode() in p.read_bytes():
            hits.append(p.relative_to(home.root).as_posix())
    return hits


def _blob(home: Home, digest: str) -> Path:
    p = home.blob_path(digest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"payload {CANARY}", encoding="utf-8")
    return p


def test_forget_all_leaves_no_trace(home: Home, conn: sqlite3.Connection) -> None:
    su.session(home, "s1", text=f"remember {CANARY}")
    su.session(home, "s2", project="prj_other", text=f"other {CANARY}")
    _blob(home, "ab" * 32)
    (home.state / "s1.jsonl").write_text(f'{{"taint":"low","x":"{CANARY}"}}\n', encoding="utf-8")
    (home.logs / "hooks.log").write_text(f"diag {CANARY}\n", encoding="utf-8")
    ingest(home, conn)
    assert _files_containing(home, CANARY)  # precondition: data really is there

    result = forget.forget_all(home, conn)
    forget.record(home, "all", None, result)

    assert result.sessions == 2
    assert _trace_files(home) == []
    for table in ("sessions", "turns", "events", "signals", "projects", "spool_files", "usage", "runs"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table  # noqa: S608
    conn.close()
    # Deleted rows must not survive in free pages, the WAL, or anywhere else under home.
    assert _files_containing(home, CANARY) == []
    entry = home.audit.read_text(encoding="utf-8").splitlines()[-1]
    assert '"action":"forget"' in entry and CANARY not in entry
    assert audit.verify(home.audit).ok


def test_forget_session_is_scoped(home: Home, conn: sqlite3.Connection) -> None:
    su.session(home, "keep", text="keep me")
    su.session(home, "drop", text="drop me")
    ingest(home, conn)
    shared_blob = _blob(home, "ab" * 32)  # referenced by both sessions' Write events
    result = forget.forget_sessions(home, conn, ["drop"])
    assert result.sessions == 1 and result.spool_files == 1
    assert [r[0] for r in conn.execute("SELECT id FROM sessions")] == ["keep"]
    assert conn.execute("SELECT COUNT(*) FROM turns WHERE session_id='drop'").fetchone()[0] == 0
    assert shared_blob.exists()  # still referenced by "keep"
    assert not list(home.spool.glob("*/drop.jsonl")) and list(home.spool.glob("*/keep.jsonl"))


def test_forget_session_removes_unshared_blob(home: Home, conn: sqlite3.Connection) -> None:
    su.session(home, "only")
    blob = _blob(home, "ab" * 32)
    ingest(home, conn)
    result = forget.forget_sessions(home, conn, ["only"])
    assert result.blobs == 1 and not blob.exists()


def test_forget_project(home: Home, conn: sqlite3.Connection) -> None:
    su.session(home, "a1", project="prj_a")
    su.session(home, "a2", project="prj_a")
    su.session(home, "b1", project="prj_b")
    ingest(home, conn)
    result = forget.forget_project(home, conn, "prj_a")
    assert result.sessions == 2
    assert [r[0] for r in conn.execute("SELECT id FROM sessions")] == ["b1"]
    assert [r[0] for r in conn.execute("SELECT id FROM projects")] == ["prj_b"]


def test_safe_session_matches_hook_rule() -> None:
    assert forget.safe_session("abc-123_X") == "abc-123_X"
    assert forget.safe_session("../../etc/passwd") == "______etc_passwd"
    assert forget.safe_session("") == "_"
    assert len(forget.safe_session("x" * 500)) == 128


def test_forget_removes_derived_learning_rows(home: Home, conn: sqlite3.Connection) -> None:
    su.session(home, "s1")
    ingest(home, conn)
    ts = "2026-10-04T00:00:00Z"
    conn.execute(
        "INSERT INTO signals (id, type, session_id, event_ids_json, confidence, created_at)"
        " VALUES ('sig1', 'S1', 's1', '[]', 0.9, ?)",
        (ts,),
    )
    conn.execute(
        "INSERT INTO test_cases (id, kind, signal_id, repo_commit, state_blob, capsule_md, trigger_prompt,"
        " assertions_json, fidelity) VALUES ('tc1', 'targeted', 'sig1', 'abc', 'blob', 'cap', 'p', '[]', 'exact')"
    )
    conn.execute(
        "INSERT INTO runs (id, test_case_id, arm, trial, started_at, passed, assertion_results_json, trace_blob)"
        " VALUES ('r1', 'tc1', 'A', 1, ?, 1, '[]', 'b')",
        (ts,),
    )
    conn.execute(
        "INSERT INTO cards (id, slug, status, tier, origin, current_version, scope_json, created_at, updated_at)"
        " VALUES ('c1', 'px-x', 'candidate', 'T0', 'learned', 1, '{}', ?, ?)",
        (ts, ts),
    )
    conn.execute(
        "INSERT INTO cards (id, slug, status, tier, origin, current_version, scope_json, created_at, updated_at)"
        " VALUES ('c2', 'px-y', 'active', 'T0', 'learned', 1, '{}', ?, ?)",
        (ts, ts),
    )
    result = forget.forget_sessions(home, conn, ["s1"])
    assert result.rows["signals"] == 1 and result.rows["test_cases"] == 1 and result.rows["runs"] == 1
    su.session(home, "s2")
    ingest(home, conn)
    result = forget.forget_all(home, conn)
    # Unverified candidates carry trace-derived text and go; verified cards stay.
    assert result.rows["cards"] == 1
    assert [r[0] for r in conn.execute("SELECT id FROM cards")] == ["c2"]
