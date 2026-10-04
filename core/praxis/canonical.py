"""Canonical JSON shared with the TypeScript hooks (packages/hooks/src/lib/canonical.ts).

Sorted keys, no whitespace, UTF-8 without escaping non-ASCII, and numbers formatted the
way JavaScript's JSON.stringify formats them. Both the snapshot HMAC and the audit hash
chain depend on byte-identical output in both languages.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any


def _js_number(x: float) -> str:
    if not math.isfinite(x):
        raise ValueError("non-finite numbers are not valid JSON")
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    r = repr(x)
    if "e" in r and 1e-6 <= abs(x) < 1e21:
        # Python switches to exponent form below 1e-4, JavaScript only below 1e-6.
        return format(Decimal(r), "f")
    if "e" in r:
        mantissa, exp = r.split("e")
        sign = "-" if exp.startswith("-") else "+"
        return f"{mantissa}e{sign}{int(exp.lstrip('+-'))}"
    return r


def dumps(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _js_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return "[" + ",".join(dumps(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: _utf16_key(kv[0]))
        return "{" + ",".join(f"{dumps(str(k))}:{dumps(v)}" for k, v in items) + "}"
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def _utf16_key(s: str) -> list[int]:
    # JavaScript sorts strings by UTF-16 code units; Python by code points. They differ only
    # for astral characters, but the HMAC must not depend on that.
    b = s.encode("utf-16-be", "surrogatepass")
    return [int.from_bytes(b[i : i + 2], "big") for i in range(0, len(b), 2)]
