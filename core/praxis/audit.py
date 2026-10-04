"""Hash-chained audit log (Part F.5).

Each line: {seq, ts, actor, action, target, details, prev, hash} where
hash = sha256(prev + canonical_json(entry without hash)). The control plane is the only
writer (ADR 0003); a lock file serializes appends across concurrent `praxis` processes.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from praxis import canonical
from praxis.paths import restrict_file

GENESIS = "0" * 64
LOCK_STALE_SECONDS = 60


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@contextmanager
def file_lock(path: Path, timeout: float = 10.0) -> Iterator[None]:
    """Exclusive lock via O_EXCL lock file. Steals locks older than LOCK_STALE_SECONDS,
    which only happens after a crash, since every holder finishes within milliseconds."""
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not acquire {lock}") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def entry_hash(prev: str, entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256((prev + canonical.dumps(body)).encode("utf-8")).hexdigest()


def _tail(path: Path) -> tuple[int, str]:
    """Return (seq, hash) of the last entry, reading only the end of the file."""
    if not path.exists() or path.stat().st_size == 0:
        return 0, GENESIS
    with path.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        block = min(size, 65536)
        while True:
            f.seek(size - block)
            data = f.read(block)
            lines = data.rstrip(b"\n").split(b"\n")
            if len(lines) > 1 or block == size:
                last = json.loads(lines[-1])
                return int(last["seq"]), str(last["hash"])
            block = min(size, block * 2)


def append(
    path: Path,
    actor: str,
    action: str,
    target: str | None = None,
    details: dict[str, Any] | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        seq, prev = _tail(path)
        entry: dict[str, Any] = {
            "seq": seq + 1,
            "ts": ts or now_iso(),
            "actor": actor,
            "action": action,
            "target": target,
            "details": details or {},
            "prev": prev,
        }
        entry["hash"] = entry_hash(prev, entry)
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(canonical.dumps(entry) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if new:
            restrict_file(path)
    return entry


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    error: str | None = None
    line: int | None = None


def verify(path: Path) -> VerifyResult:
    if not path.exists():
        return VerifyResult(True, 0)
    prev, count = GENESIS, 0
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                return VerifyResult(False, count, "malformed line", lineno)
            if entry.get("seq") != count + 1:
                return VerifyResult(False, count, f"sequence gap: expected {count + 1}", lineno)
            if entry.get("prev") != prev:
                return VerifyResult(False, count, "prev hash does not match previous entry", lineno)
            if entry_hash(prev, entry) != entry.get("hash"):
                return VerifyResult(False, count, "entry hash mismatch (edited entry)", lineno)
            prev, count = entry["hash"], count + 1
    return VerifyResult(True, count)
