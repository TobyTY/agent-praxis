"""Snapshot compiler (Part E.3).

The snapshot is the only state the hooks read. It is written atomically
(temp, fsync, rename), the previous one is kept for rollback, and it carries an
HMAC-SHA256 over its canonical JSON so the hooks can detect corruption and naive
tampering. The HMAC does not stop a same-user process that can read the key
(THREAT_MODEL.md, T3).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from hashlib import sha256
from pathlib import Path
from typing import Any

from praxis import audit, canonical
from praxis.db.conn import current_version
from praxis.paths import Home, claude_config_dir, restrict_file

ADMIN_COMMANDS = ["praxis unlock", "praxis disable", "praxis uninstall"]

# Danger rule ids (Part I.2). Phase 2 implements their detection; the snapshot already
# carries the list so the policy shape is stable.
DANGER_RULES = [
    "rm_rf_outside_project",
    "git_push_force",
    "git_reset_hard",
    "git_clean_fdx",
    "chmod_recursive_777",
    "dd",
    "mkfs",
    "shell_rc_write",
    "git_hooks_write",
    "package_publish",
]


class SnapshotError(Exception):
    pass


def generate_key(home: Home) -> bool:
    """Create the snapshot key if missing. Returns True when a new key was written."""
    if home.key.exists():
        return False
    home.key.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(home.key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(secrets.token_hex(32))
    restrict_file(home.key)
    return True


def read_key(home: Home) -> bytes:
    try:
        return bytes.fromhex(home.key.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as e:
        raise SnapshotError(f"snapshot key unreadable: {e}") from e


def protected_globs(home: Home) -> list[str]:
    cc = claude_config_dir()
    root = home.root.as_posix()
    return [
        f"{root}/**",
        f"{cc.as_posix()}/settings.json",
        f"{cc.as_posix()}/settings.local.json",
        f"{cc.as_posix()}/skills/px-*/**",
        f"{cc.as_posix()}/plugins/**/praxis/**",
        "**/.claude/settings.json",
        "**/.claude/settings.local.json",
    ]


def sign(body: dict[str, Any], key: bytes) -> str:
    unsigned = {k: v for k, v in body.items() if k != "hmac_sha256"}
    return hmac.new(key, canonical.dumps(unsigned).encode("utf-8"), sha256).hexdigest()


def verify_file(path: Path, key: bytes) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SnapshotError(f"snapshot unreadable: {e}") from e
    if not isinstance(body, dict) or not isinstance(body.get("hmac_sha256"), str):
        raise SnapshotError("snapshot has no hmac_sha256")
    if not hmac.compare_digest(sign(body, key), body["hmac_sha256"]):
        raise SnapshotError("snapshot HMAC mismatch")
    return body


def build(home: Home, conn: sqlite3.Connection, cfg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    # Phase 0: no routable cards yet. Phase 1 fills cards, Phase 3 fills edges and index.
    return {
        "v": 1,
        "generated_at": audit.now_iso(),
        "db_version": current_version(conn),
        "policy": {
            "mode": cfg["guard"]["mode"],
            "protected_globs": protected_globs(home),
            "danger_rules": DANGER_RULES,
            "admin_commands": ADMIN_COMMANDS,
            "taint_on_webfetch": cfg["guard"]["taint_on_webfetch"],
            # Privacy settings the capture hook needs; hooks never parse config.toml.
            "store_assistant_text": cfg["privacy"]["store_assistant_text"],
            "assistant_excerpt_chars": cfg["privacy"]["assistant_excerpt_chars"],
        },
        "cards": [],
        "edges": [],
        "index": {},
    }


def write_atomic(path: Path, data: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    restrict_file(tmp)
    os.replace(tmp, path)


def compile_snapshot(home: Home, conn: sqlite3.Connection, cfg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = read_key(home)
    body = build(home, conn, cfg)
    body["hmac_sha256"] = sign(body, key)
    home.snapshot_dir.mkdir(parents=True, exist_ok=True)
    if home.snapshot.exists():
        write_atomic(home.snapshot_previous, home.snapshot.read_text(encoding="utf-8"))
    write_atomic(home.snapshot, canonical.dumps(body))
    return body


def rollback(home: Home) -> None:
    if not home.snapshot_previous.exists():
        raise SnapshotError("no previous snapshot to roll back to")
    verify_file(home.snapshot_previous, read_key(home))
    write_atomic(home.snapshot, home.snapshot_previous.read_text(encoding="utf-8"))
