from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from praxis import config, snapshot
from praxis.db.conn import connect
from praxis.paths import Home


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Home:
    """An initialized $PRAXIS_HOME in a temp dir. CLAUDE_CONFIG_DIR is isolated too, so no
    test can read or touch the developer's real Claude Code configuration."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.delenv("PRAXIS_HOME", raising=False)
    h = Home.resolve(tmp_path / "praxis-home")
    h.ensure()
    h.config.write_text(config.dump(config.DEFAULTS), encoding="utf-8")
    snapshot.generate_key(h)
    conn = connect(h.db)
    snapshot.compile_snapshot(h, conn, config.load(h.config))
    conn.close()
    return h


@pytest.fixture
def conn(home: Home) -> Iterator[sqlite3.Connection]:
    c = connect(home.db)
    yield c
    c.close()
