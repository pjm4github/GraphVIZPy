"""Parity tests for gvpy.engines.layout.ortho.partition (Phase 4 port).

Compares Python's decomposition against the C harness in
``filters/partition_harness/``.  Rectangles are sorted lexicographically
on both sides before comparison because the two code paths use
different segment-insertion orders (C uses ``srand48(173)`` +
``drand48()``; Python uses identity) — the final rectangle set is
deterministic and permutation-invariant by construction, but internal
trapezoid numbering differs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gvpy.engines.layout.ortho.partition import (
    format_partition,
    load_fixture,
    partition,
)


FIXTURE_DIR = (
    Path(__file__).parent.parent
    / "filters" / "partition_harness" / "fixtures"
)
EXPECTED_DIR = Path(__file__).parent / "fixtures" / "partition"


def _fixture_names() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.in"))


@pytest.mark.parametrize("name", _fixture_names())
def test_matches_c_harness(name: str):
    in_path = FIXTURE_DIR / f"{name}.in"
    expected_path = EXPECTED_DIR / f"{name}.expected"
    assert in_path.exists(), f"missing input fixture: {in_path}"
    assert expected_path.exists(), (
        f"missing expected output: {expected_path}"
    )

    cells, ncells, bb = load_fixture(str(in_path))
    rects = partition(cells, ncells, bb)

    actual = format_partition(ncells, rects)
    expected = expected_path.read_text(encoding="utf-8")

    actual_lines = [ln.rstrip() for ln in actual.splitlines()]
    expected_lines = [ln.rstrip() for ln in expected.splitlines()]

    if actual_lines != expected_lines:
        for i, (a, e) in enumerate(zip(actual_lines, expected_lines)):
            if a != e:
                pytest.fail(
                    f"fixture {name}: first divergence at line {i}\n"
                    f"  python: {a!r}\n"
                    f"  c    : {e!r}\n"
                    f"  (total: py={len(actual_lines)} c={len(expected_lines)})"
                )
        pytest.fail(
            f"fixture {name}: line count differs "
            f"(py={len(actual_lines)}, c={len(expected_lines)})"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
