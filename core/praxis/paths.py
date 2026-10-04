"""Locations under $PRAXIS_HOME (Part D.6).

Every path the control plane touches is derived here so `forget`, `uninstall` and the
protected-path list cannot drift apart.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


def default_home() -> Path:
    env = os.environ.get("PRAXIS_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".praxis"


@dataclass(frozen=True)
class Home:
    root: Path

    @classmethod
    def resolve(cls, root: Path | None = None) -> Home:
        return cls((root or default_home()).expanduser().resolve())

    @property
    def config(self) -> Path:
        return self.root / "config.toml"

    @property
    def db(self) -> Path:
        return self.root / "praxis.db"

    @property
    def spool(self) -> Path:
        return self.root / "spool"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def blobs(self) -> Path:
        return self.root / "blobs" / "sha256"

    @property
    def cards(self) -> Path:
        return self.root / "cards"

    @property
    def evidence(self) -> Path:
        return self.root / "evidence"

    @property
    def snapshot_dir(self) -> Path:
        return self.root / "snapshot"

    @property
    def snapshot(self) -> Path:
        return self.snapshot_dir / "current.json"

    @property
    def snapshot_previous(self) -> Path:
        return self.snapshot_dir / "previous.json"

    @property
    def key(self) -> Path:
        return self.root / "keys" / "snapshot.key"

    @property
    def audit(self) -> Path:
        return self.root / "audit" / "audit.jsonl"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def replay(self) -> Path:
        return self.root / "replay"

    @property
    def unlock(self) -> Path:
        return self.root / "unlock"

    def blob_path(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError(f"not a sha256 hex digest: {sha256!r}")
        return self.blobs / sha256[:2] / sha256[2:]

    def ensure(self) -> None:
        """Create the directory tree with owner-only permissions where the OS supports it."""
        for d in (
            self.root,
            self.spool,
            self.state,
            self.blobs,
            self.cards,
            self.evidence,
            self.snapshot_dir,
            self.key.parent,
            self.audit.parent,
            self.logs,
            self.replay,
        ):
            d.mkdir(parents=True, exist_ok=True)
            restrict_dir(d)


def restrict_dir(path: Path) -> None:
    # On Windows, chmod only toggles the read-only bit; the user profile ACL is the
    # effective protection. Documented in THREAT_MODEL.md.
    if sys.platform != "win32":
        path.chmod(stat.S_IRWXU)


def restrict_file(path: Path) -> None:
    if sys.platform != "win32":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def claude_config_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"
