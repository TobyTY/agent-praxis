from __future__ import annotations

import json
import threading
from pathlib import Path

from praxis import audit


def _lines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines()


def test_empty_log_verifies(tmp_path: Path) -> None:
    assert audit.verify(tmp_path / "missing.jsonl").ok


def test_chain_appends_and_verifies(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"
    for i in range(5):
        e = audit.append(p, "user", "test", f"t{i}", {"i": i})
        assert e["seq"] == i + 1
    res = audit.verify(p)
    assert res.ok and res.entries == 5
    first = json.loads(_lines(p)[0])
    assert first["prev"] == audit.GENESIS


def test_edit_is_detected(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"
    for i in range(3):
        audit.append(p, "user", "test", None, {"i": i})
    lines = _lines(p)
    entry = json.loads(lines[1])
    entry["details"]["i"] = 99
    lines[1] = json.dumps(entry)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = audit.verify(p)
    assert not res.ok and res.line == 2 and "hash mismatch" in (res.error or "")


def test_deletion_is_detected(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"
    for i in range(3):
        audit.append(p, "user", "test", None, {"i": i})
    lines = _lines(p)
    p.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    res = audit.verify(p)
    assert not res.ok and "sequence gap" in (res.error or "")


def test_tail_truncation_is_not_detectable(tmp_path: Path) -> None:
    # Truncating the tail cannot be detected from the file alone; the chain stays valid.
    # THREAT_MODEL.md records this: a same-user process can drop trailing entries.
    p = tmp_path / "audit.jsonl"
    for i in range(3):
        audit.append(p, "user", "test", None, {"i": i})
    p.write_text(_lines(p)[0] + "\n", encoding="utf-8")
    assert audit.verify(p).ok


def test_concurrent_appends_keep_chain(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"

    def worker(n: int) -> None:
        for i in range(10):
            audit.append(p, "user", "test", None, {"w": n, "i": i})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    res = audit.verify(p)
    assert res.ok and res.entries == 40


def test_stale_lock_is_stolen(tmp_path: Path) -> None:
    import os
    import time

    p = tmp_path / "audit.jsonl"
    lock = p.with_name(p.name + ".lock")
    lock.write_text("12345")
    old = time.time() - audit.LOCK_STALE_SECONDS - 5
    os.utime(lock, (old, old))
    audit.append(p, "user", "test")
    assert audit.verify(p).entries == 1
