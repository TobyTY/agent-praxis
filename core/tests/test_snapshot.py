from __future__ import annotations

import json
import sqlite3

import pytest

from praxis import canonical, config, snapshot
from praxis.paths import Home

from .canaries import REPO

HMAC_FIXTURE = REPO / "tests" / "fixtures" / "snapshot-hmac.json"


def test_compiled_snapshot_verifies(home: Home) -> None:
    body = snapshot.verify_file(home.snapshot, snapshot.read_key(home))
    assert body["v"] == 1 and body["cards"] == [] and body["policy"]["mode"] == "ask"
    assert body["policy"]["admin_commands"] == snapshot.ADMIN_COMMANDS


def test_snapshot_is_canonical_on_disk(home: Home) -> None:
    raw = home.snapshot.read_text(encoding="utf-8")
    assert raw == canonical.dumps(json.loads(raw))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["policy"].__setitem__("mode", "minimal"),
        lambda b: b["policy"]["protected_globs"].pop(),
        lambda b: b.__setitem__("cards", [{"id": "x"}]),
    ],
)
def test_tampering_is_detected(home: Home, mutate: object) -> None:
    body = json.loads(home.snapshot.read_text(encoding="utf-8"))
    mutate(body)  # type: ignore[operator]
    home.snapshot.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(snapshot.SnapshotError, match="HMAC mismatch"):
        snapshot.verify_file(home.snapshot, snapshot.read_key(home))


def test_wrong_key_fails(home: Home) -> None:
    with pytest.raises(snapshot.SnapshotError):
        snapshot.verify_file(home.snapshot, b"\x00" * 32)


def test_previous_kept_and_rollback(home: Home, conn: sqlite3.Connection) -> None:
    first = home.snapshot.read_text(encoding="utf-8")
    cfg = config.load(home.config)
    cfg["guard"]["mode"] = "strict"
    snapshot.compile_snapshot(home, conn, cfg)
    assert home.snapshot_previous.read_text(encoding="utf-8") == first
    snapshot.rollback(home)
    assert home.snapshot.read_text(encoding="utf-8") == first


def test_key_not_regenerated(home: Home) -> None:
    key = home.key.read_text()
    assert snapshot.generate_key(home) is False
    assert home.key.read_text() == key


def test_no_temp_files_left(home: Home) -> None:
    assert not [p for p in home.snapshot_dir.iterdir() if p.name.endswith(".tmp")]


def test_hmac_fixture_parity() -> None:
    """tests/fixtures/snapshot-hmac.json is also verified by the TypeScript suite."""
    fx = json.loads(HMAC_FIXTURE.read_text(encoding="utf-8"))
    assert snapshot.sign(fx["snapshot"], bytes.fromhex(fx["key_hex"])) == fx["snapshot"]["hmac_sha256"]


def test_size_target_at_1000_cards(home: Home) -> None:
    card = {
        "id": "card_01J9Z0000000000000000000",
        "slug": "px-example-card-slug",
        "v": 3,
        "status": "active",
        "tier": "T0",
        "scope": {"kind": "project", "project_id": "prj_0123456789abcdef", "paths": ["**"]},
        "summary": "x" * 130,
        "path": "/home/user/.praxis/cards/px-example-card-slug/SKILL.md",
        "caps": ["exec:pnpm install", "fs.write:/home/user/project/**"],
        "caps_approved": True,
        "content_sha256": "0" * 64,
        "evidence_label": "5/5 vs 1/5 - claude-opus-5",
        "stale": False,
    }
    body = {"v": 1, "cards": [card] * 1000}
    assert len(canonical.dumps(body).encode()) < 2 * 1024 * 1024
