from __future__ import annotations

import hashlib
import re
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from praxis.capture.redact import is_sensitive_path, redact_text, redact_value, shannon_bits, token
from praxis.generated.redaction_rules import REDACTION_RULES

from .canaries import REPO, corpus

CORPUS = corpus()
DIGEST_FILE = REPO / "tests" / "fixtures" / "redaction-corpus.sha256"


def _leaks(text: str, secrets: tuple[str, ...]) -> list[str]:
    return [s for s in secrets if s in text or (len(s) >= 16 and s[4:16] in text)]


def test_corpus_size() -> None:
    assert len(CORPUS) >= 200


def test_corpus_fully_redacted() -> None:
    leaked = [(c.type, c.text) for c in CORPUS if _leaks(redact_text(c.text), c.secrets)]
    assert leaked == [], f"{len(leaked)}/{len(CORPUS)} canaries leaked: {leaked[:3]}"


def test_corpus_digest_matches_typescript() -> None:
    # The TS suite checks the same digest: both implementations must redact byte-identically.
    h = hashlib.sha256()
    for c in CORPUS:
        h.update(redact_text(c.text).encode("utf-8"))
        h.update(b"\n")
    actual = h.hexdigest()
    expected = DIGEST_FILE.read_text(encoding="ascii").strip() if DIGEST_FILE.exists() else None
    assert actual == expected, (
        f"redaction corpus digest changed; if intended, write {actual} to {DIGEST_FILE}"
    )


def test_patterns_compile_in_python() -> None:
    for rule in REDACTION_RULES["rules"]:
        re.compile(rule["pattern"])


def test_idempotent() -> None:
    for c in CORPUS:
        once = redact_text(c.text)
        assert redact_text(once) == once


def test_token_is_stable_and_hides_value() -> None:
    t = token("kv", "hunter2hunter2")
    assert t == token("kv", "hunter2hunter2")
    assert "hunter2" not in t
    assert re.fullmatch(r"‹redacted:kv:[0-9a-f]{8}›", t)


def test_benign_text_untouched() -> None:
    benign = [
        "pnpm install && pnpm test",
        "git commit -m 'fix: handle empty input'",
        "src/components/UserProfileCard.tsx",
        "commit 3f2a9c1b8e7d6f5a4b3c2d1e0f9a8b7c6d5e4f3a",
        "550e8400-e29b-41d4-a716-446655440000",
        "The quick brown fox jumps over the lazy dog",
        "max_tokens = 1000",
        "C:\\Users\\dev\\project\\README.md",
    ]
    changed = [b for b in benign if redact_text(b) != b]
    # max_tokens matches the key pattern (TOKEN) and its value is >= 4 chars: accepted noise.
    assert changed == ["max_tokens = 1000"]


def test_redact_value_recurses() -> None:
    v = {"a": ["DB_PASSWORD=abcdefghijkl"], "b": {"c": "ok"}, "n": 3}
    out = redact_value(v)
    assert "abcdefghijkl" not in str(out)
    assert out["b"] == {"c": "ok"} and out["n"] == 3


def test_entropy() -> None:
    assert shannon_bits("") == 0
    assert shannon_bits("aaaa") == 0
    assert abs(shannon_bits("ab") - 1.0) < 1e-9


def test_sensitive_paths() -> None:
    for p in [
        ".env",
        "/repo/.env.local",
        "C:\\keys\\server.pem",
        "id_ed25519",
        "~/.npmrc",
        "credentials.json",
    ]:
        assert is_sensitive_path(p), p
    for p in [".env.example", "id_ed25519.pub", "src/env.ts", "README.md"]:
        assert not is_sensitive_path(p), p


@settings(max_examples=10_000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text(max_size=300))
def test_fuzz_never_crashes(s: str) -> None:
    out = redact_text(s)
    assert isinstance(out, str)


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=80), st.sampled_from(CORPUS), st.text(max_size=80))
def test_fuzz_canary_in_noise_is_removed(prefix: str, canary: object, suffix: str) -> None:
    from .canaries import Canary

    assert isinstance(canary, Canary)
    # Separate with whitespace: a canary glued to random word characters is a different
    # token and may legitimately not match a format rule.
    text = f"{prefix} {canary.text} {suffix}"
    out = redact_text(text)
    assert not [s for s in canary.secrets if s in out]


def test_digest_file_is_ascii(tmp_path: Path) -> None:
    if DIGEST_FILE.exists():
        assert re.fullmatch(r"[0-9a-f]{64}\s*", DIGEST_FILE.read_text(encoding="ascii"))
