"""Deterministic, inert canary corpus (Part M.4). Twin of packages/hooks/test/canaries.ts.

Strings are assembled from tests/fixtures/canary-templates.json with xorshift32, so both
languages produce byte-identical corpora and nothing secret-shaped is committed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = json.loads((REPO / "tests" / "fixtures" / "canary-templates.json").read_text(encoding="utf-8"))


class XorShift32:
    def __init__(self, seed: int) -> None:
        self.x = seed & 0xFFFFFFFF or 1

    def next(self) -> int:
        x = self.x
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.x = x & 0xFFFFFFFF
        return self.x


@dataclass(frozen=True)
class Canary:
    type: str
    text: str
    secrets: tuple[str, ...]


def corpus() -> list[Canary]:
    rng = XorShift32(TEMPLATES["seed"])
    charsets = TEMPLATES["charsets"]
    out: list[Canary] = []
    for tpl in TEMPLATES["templates"]:
        for ctx in TEMPLATES["contexts"]:
            whole, rand_parts = "", []
            for part in tpl["parts"]:
                if part[0] == "lit":
                    whole += part[1]
                else:
                    cs = charsets[part[1]]
                    s = "".join(cs[rng.next() % len(cs)] for _ in range(part[2]))
                    rand_parts.append(s)
                    whole += s
            secrets = (whole,) if tpl["secret"] == "all" else tuple(rand_parts)
            out.append(Canary(tpl["type"], ctx.replace("{c}", whole), secrets))
    return out
