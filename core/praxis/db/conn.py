"""SQLite connection and forward-only migrations."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from praxis.paths import restrict_file


def _migrations() -> list[tuple[int, str]]:
    out = []
    for entry in resources.files("praxis.db").joinpath("migrations").iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:4].isdigit():
            out.append((int(name[:4]), entry.read_text(encoding="utf-8")))
    return sorted(out)


LATEST_VERSION = max(v for v, _ in _migrations())


def connect(path: Path, *, migrate: bool = True) -> sqlite3.Connection:
    new = not path.exists()
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    if new:
        restrict_file(path)
    if migrate:
        apply_migrations(conn)
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not has_table:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def apply_migrations(conn: sqlite3.Connection) -> int:
    version = current_version(conn)
    for number, sql in _migrations():
        if number <= version:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _split(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        version = number
    return version


def _split(sql: str) -> list[str]:
    """Split a migration into statements. Migrations contain no triggers or string literals
    with semicolons, which keeps this simple; sqlite3.complete_statement guards the rest."""
    statements, buf = [], ""
    for line in sql.splitlines(keepends=True):
        stripped = line.split("--", 1)[0]
        buf += stripped
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip():
        raise ValueError("migration ends with an incomplete statement")
    return statements
