from __future__ import annotations

import json
from pathlib import Path

import pytest

from praxis import audit, cli, config
from praxis.paths import Home

from . import spoolutil as su


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("PRAXIS_PLUGIN_DIR", str(tmp_path / "no-plugin"))
    return tmp_path / "home"


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, object]]:
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    return code, json.loads(out)


def test_init_creates_home(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run(capsys, "init", "--home", str(isolated))
    home = Home.resolve(isolated)
    assert home.key.exists() and home.config.exists() and home.snapshot.exists() and home.db.exists()
    assert data["new_key"] is True
    assert code in (0, 1)  # 1 only when node is missing on the test machine
    key = home.key.read_text()
    code, data = run(capsys, "init", "--home", str(isolated))
    assert data["new_key"] is False and home.key.read_text() == key
    assert audit.verify(home.audit).entries == 2


def test_commands_require_init(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run(capsys, "status", "--home", str(isolated))
    assert code == 1 and data["error"] == "not_initialized"
    code, _ = run(capsys, "ingest", "--quiet", "--home", str(isolated))
    assert code == 0  # detached ingest before init is a no-op, not a failure


def test_status_and_ingest(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "init", "--home", str(isolated))
    home = Home.resolve(isolated)
    su.session(home, "s1")
    code, data = run(capsys, "status", "--home", str(isolated))
    assert data["spool_bytes_pending"] > 0 and data["safe_mode"] is False
    code, data = run(capsys, "ingest", "--home", str(isolated))
    assert code == 0 and data["lines"] == 8
    code, data = run(capsys, "status", "--home", str(isolated))
    assert data["counts"]["sessions"] == 1 and data["spool_bytes_pending"] == 0  # type: ignore[index]


def test_status_reports_safe_mode(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "init", "--home", str(isolated))
    home = Home.resolve(isolated)
    home.snapshot.write_text(
        home.snapshot.read_text(encoding="utf-8").replace('"ask"', '"minimal"'), encoding="utf-8"
    )
    _, data = run(capsys, "status", "--home", str(isolated))
    assert data["safe_mode"] is True
    code, data = run(capsys, "doctor", "--home", str(isolated))
    assert code == 1 and data["safe_mode"] is True


def test_forget_all_needs_yes_non_interactive(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "init", "--home", str(isolated))
    code, data = run(capsys, "forget", "--all", "--home", str(isolated))
    assert code == 1 and data["error"] == "confirmation_required"
    code, data = run(capsys, "forget", "--all", "--yes", "--home", str(isolated))
    assert code == 0 and data["scope"] == "all"


def test_forget_requires_scope(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "init", "--home", str(isolated))
    code, data = run(capsys, "forget", "--home", str(isolated))
    assert code == 2 and data["error"] == "no_scope"


def test_audit_verify_detects_tamper(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "init", "--home", str(isolated))
    home = Home.resolve(isolated)
    code, _ = run(capsys, "audit", "verify", "--home", str(isolated))
    assert code == 0
    home.audit.write_text(
        home.audit.read_text(encoding="utf-8").replace('"init"', '"edit"'), encoding="utf-8"
    )
    code, data = run(capsys, "audit", "verify", "--home", str(isolated))
    assert code == 1 and data["line"] == 1


def test_uninstall_purge(isolated: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "init", "--home", str(isolated))
    skills = tmp_path / "claude-config" / "skills"
    (skills / "px-owned").mkdir(parents=True)
    (skills / "px-owned" / cli.OWNER_MARKER).write_text("")
    (skills / "px-not-ours").mkdir()
    code, data = run(capsys, "uninstall", "--purge", "--home", str(isolated))
    assert code == 1 and data["error"] == "confirmation_required"
    code, data = run(capsys, "uninstall", "--purge", "--yes", "--home", str(isolated))
    assert code == 0 and data["purged"] is True and data["skills_removed"] == ["px-owned"]
    assert not isolated.exists()
    assert (skills / "px-not-ours").exists()  # never delete a px-* dir Praxis did not create


def test_bad_config_reports_error(isolated: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "init", "--home", str(isolated))
    home = Home.resolve(isolated)
    home.config.write_text('[guard]\nmode = "yolo"\n', encoding="utf-8")
    code, data = run(capsys, "status", "--home", str(isolated))
    assert code == 1 and "guard.mode" in str(data["error"])


def test_config_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "c.toml"
    p.write_text(config.dump(config.DEFAULTS), encoding="utf-8")
    assert config.load(p) == config.DEFAULTS
    p.write_text("[router]\nmax_cards = 2\n[learner]\ndaily_cost_usd = 5\n", encoding="utf-8")
    cfg = config.load(p)
    assert cfg["router"]["max_cards"] == 2 and cfg["learner"]["daily_cost_usd"] == 5.0
    for bad in (
        "[nope]\nx = 1\n",
        "[router]\nnope = 1\n",
        "[router]\nmax_cards = true\n",
        '[privacy]\nstore_assistant_text = "all"\n',
    ):
        p.write_text(bad, encoding="utf-8")
        with pytest.raises(config.ConfigError):
            config.load(p)


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    from praxis.db.conn import LATEST_VERSION, apply_migrations, connect, current_version

    c = connect(tmp_path / "x.db")
    assert current_version(c) == LATEST_VERSION
    assert apply_migrations(c) == LATEST_VERSION
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "projects",
        "sessions",
        "turns",
        "events",
        "signals",
        "cards",
        "card_versions",
        "edges",
        "test_cases",
        "runs",
        "evidence",
        "usage",
        "budgets",
        "spool_files",
    } <= tables
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_doctor_self_tests_the_real_hooks(
    isolated: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    if not shutil.which("node"):
        pytest.skip("node not installed")
    monkeypatch.setenv("PRAXIS_PLUGIN_DIR", str(su.REPO / "plugin"))
    run(capsys, "init", "--home", str(isolated))
    code, data = run(capsys, "doctor", "--home", str(isolated))
    hooks = {h["hook"]: h for h in data["hooks"]}  # type: ignore[union-attr]
    assert set(hooks) == {"session-start.mjs", "route.mjs", "capture.mjs", "session-end.mjs"}
    assert all(h["ok"] for h in hooks.values()), hooks
    assert code == 0
