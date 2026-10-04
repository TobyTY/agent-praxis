"""Second-pass redaction (Part F.4). Rules come from schemas/redaction-rules.json (ADR 0004).

The TypeScript twin in packages/hooks/src/lib/redact.ts runs first, before a spool line is
written. This module runs again at ingest and export, so a rule added later also cleans
lines captured before it existed.
"""

from __future__ import annotations

import fnmatch
import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from praxis.generated.redaction_rules import REDACTION_RULES

_RULES: list[tuple[str, re.Pattern[str], int | None]] = [
    (r["type"], re.compile(r["pattern"]), r.get("group")) for r in REDACTION_RULES["rules"]
]
_ENTROPY = REDACTION_RULES["entropy"]
_ENTROPY_RE = re.compile(_ENTROPY["token_pattern"])
_TOKEN_RE = re.compile(r"‹redacted:[a-z_]+:[0-9a-f]{8}›")


def token(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    return f"‹redacted:{kind}:{digest}›"


def shannon_bits(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def _has_classes(s: str) -> bool:
    need = set(_ENTROPY["require_classes"])
    have = set()
    for ch in s:
        if ch.isdigit():
            have.add("digit")
        elif ch.isupper():
            have.add("upper")
        elif ch.islower():
            have.add("lower")
    return need <= have


def _replacer(kind: str, group: int | None) -> Callable[[re.Match[str]], str]:
    def whole(m: re.Match[str]) -> str:
        return token(kind, m.group(0))

    def one_group(m: re.Match[str]) -> str:
        # The rule's groups partition the match; only group `group` is the secret.
        return "".join(
            token(kind, part) if i == group else part for i, part in enumerate(m.groups(), start=1)
        )

    return whole if group is None else one_group


def redact_text(text: str) -> str:
    for kind, pattern, group in _RULES:
        text = pattern.sub(_replacer(kind, group), text)

    def _entropy(m: re.Match[str]) -> str:
        s = m.group(0)
        if _TOKEN_RE.search(s):
            return s
        if _has_classes(s) and shannon_bits(s) >= _ENTROPY["min_bits_per_char"]:
            return token(_ENTROPY["type"], s)
        return s

    return _ENTROPY_RE.sub(_entropy, text)


def redact_value(value: Any) -> Any:
    """Recursively redact every string in a JSON-like value. Keys are left as they are."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    return value


def is_sensitive_path(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatchcase(name, g) for g in REDACTION_RULES["sensitive_path_exceptions"]):
        return False
    return any(fnmatch.fnmatchcase(name, g) for g in REDACTION_RULES["sensitive_path_globs"])
