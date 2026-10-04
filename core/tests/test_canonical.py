from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from praxis import canonical

from .canaries import REPO

CASES = json.loads((REPO / "tests" / "fixtures" / "canonical.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["expected"][:30])
def test_fixture(case: dict[str, object]) -> None:
    assert canonical.dumps(case["value"]) == case["expected"]


def test_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical.dumps(float("nan"))


json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(2**53), 2**53)
    | st.text(max_size=20)
    | st.floats(allow_nan=False, allow_infinity=False),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=20,
)


@given(json_values)
def test_roundtrip_is_stable(v: object) -> None:
    once = canonical.dumps(v)
    assert canonical.dumps(json.loads(once)) == once
