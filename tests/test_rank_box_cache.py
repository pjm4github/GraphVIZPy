"""Regression test: ``rank_box`` must return independent Box copies.

Before the fix, :func:`splines.rank_box` cached and returned the *same*
:class:`Box` object across calls.  :func:`routespl.routesplines_`
mutates the box's x-extents in place (tightens after routing), which
poisoned the cache for the next edge fetching the same rank — start
and end x-bounds would be ``±inf`` from the previous route's reset
step, making :func:`Pshortestpath` see a degenerate corridor and fail.

Symptom on the test corpus: 2239.dot dropped 45/86 edges, 1472.dot
dropped 36/154.  Fix: return a fresh Box copy from ``rank_box``.
"""
import math

from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
from gvpy.engines.layout.dot.path import SplineInfo
from gvpy.engines.layout.dot.splines import rank_box
from gvpy.grammar.gv_reader import read_dot


def _prime_layout():
    g = read_dot("digraph { rankdir=LR; a -> b -> c; a -> c }")
    layout = DotGraphInfo(g)
    layout.layout()
    sp = layout._spline_info or SplineInfo()
    # The routing pass clears _spline_info at the end; re-create one
    # so rank_box has a place to cache.
    if layout._spline_info is None:
        sp = SplineInfo()
        sp.left_bound = 0.0
        sp.right_bound = 1000.0
        layout._spline_info = sp
    return layout, sp


def test_rank_box_returns_fresh_copy():
    layout, sp = _prime_layout()
    b1 = rank_box(layout, sp, 0)
    b2 = rank_box(layout, sp, 0)
    # Two fetches for the same rank must not share the same object.
    assert b1 is not b2, "rank_box must return a fresh copy per call"
    # Mutating the returned box must not affect subsequent fetches.
    b1.ll_x = float("inf")
    b1.ur_x = float("-inf")
    b3 = rank_box(layout, sp, 0)
    assert math.isfinite(b3.ll_x) and math.isfinite(b3.ur_x), (
        "rank_box cache was poisoned by caller's in-place mutation")
