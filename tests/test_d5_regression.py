"""Regression gate for TODO §1 D5 (cluster-straddle mincross).

The fixture ``test_data/d5_regression.dot`` packs four distinct D5
failure modes into ~20 nodes:

- Case A — adjacent-rank RL-flip (2796 class)
- Case B — thread-through cluster (2239 class)
- Case C — multi-rank edge routing through non-member cluster
  (aa1332 class, long virtual chain)
- Case D — nested-cluster interclrep / make_chain (skeleton
  edge creation)

We run the Python layout, count edges whose routed spline crosses
a non-member cluster's bbox, and assert the number is within a
tight baseline.  Any change that raises the count above the
recorded baseline fails the test and flags a D5 regression —
shrinking the baseline below 4 is how D5 fixes land.

The baseline is sensitive to dict-iteration ordering inside
``layout._clusters`` (known from ``memory/feedback_set_nondeterminism``);
we run with ``PYTHONHASHSEED=0`` via a subprocess so the count is
reproducible across Python invocations.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "test_data" / "d5_regression.dot"

# Baseline — tightened as D5 fixes land, reject any increase.
#   2026-04-22: 4 (fixture landing, legacy run_mincross backend)
#   2026-04-22: 1 (after switching run_mincross to cluster_medians /
#                  cluster_reorder / cluster_transpose C-aligned
#                  backend — `order_by_weighted_median` used raw
#                  order indices as mvals instead of
#                  ``VAL = MC_SCALE * order + port.order``).
BASELINE_VISIBLE_CROSSINGS = 1


@pytest.mark.skipif(not FIXTURE.exists(),
                    reason="d5_regression.dot fixture missing")
def test_d5_regression_baseline_holds():
    """Run ``count_cluster_crossings.py`` with a pinned hash seed
    and assert the visible cluster-crossing count doesn't exceed
    the recorded baseline.

    The recipe is intentionally subprocess-based: Python's set-
    iteration order varies per interpreter launch unless
    ``PYTHONHASHSEED`` is set at startup (setting it inside the
    test is too late — the layout module already imported).
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    # Clear D5 traces so stderr stays clean.
    env.pop("GV_TRACE", None)

    result = subprocess.run(
        [sys.executable,
         str(REPO / "porting_scripts" / "count_cluster_crossings.py"),
         str(FIXTURE)],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=60,
    )
    m = re.search(r"(\d+) edges cross non-member clusters", result.stdout)
    assert m, (
        f"count_cluster_crossings didn't report a count; "
        f"stdout:\n{result.stdout}\nstderr tail:\n{result.stderr[-500:]}"
    )
    crossings = int(m.group(1))
    assert crossings <= BASELINE_VISIBLE_CROSSINGS, (
        f"D5 regression: {crossings} cluster crossings vs baseline "
        f"{BASELINE_VISIBLE_CROSSINGS}.  Inspect the listed offenders "
        f"in:\n{result.stdout}"
    )


@pytest.mark.skipif(not FIXTURE.exists(),
                    reason="d5_regression.dot fixture missing")
def test_d5_regression_runs_without_exception():
    """The fixture must lay out end-to-end without the layout
    engine raising.  Guards against structural regressions
    (nested-cluster parsing, interclrep chain builder, etc.) that
    would manifest as exceptions rather than crossing counts."""
    from gvpy.grammar.gv_reader import read_dot_file
    from gvpy.engines.layout.dot.dot_layout import DotLayout
    g = read_dot_file(str(FIXTURE))
    result = DotLayout(g).layout()
    # Sanity — graph, nodes, edges, and the four clusters survive.
    assert result["graph"]["bb"]
    assert len(result["nodes"]) >= 15
    cluster_names = {c["name"] for c in result.get("clusters", [])}
    assert "cluster_A_left" in cluster_names
    assert "cluster_A_right" in cluster_names
    assert "cluster_B" in cluster_names
    assert "cluster_C" in cluster_names
    assert "cluster_D_outer" in cluster_names
    assert "cluster_D_inner" in cluster_names
