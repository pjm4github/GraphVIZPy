"""Tests for D+.1 top_bound / bot_bound neighbor lookups."""
import pytest

from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
from gvpy.engines.layout.dot.regular_edge import bot_bound, top_bound
from gvpy.grammar.gv_reader import read_dot


def _layout(src):
    g = read_dot(src)
    layout = DotGraphInfo(g)
    layout.layout()
    return layout


class TestTopBound:

    def test_no_siblings_returns_none(self):
        layout = _layout("digraph { a -> b }")
        a = layout.lnodes["a"]
        b = layout.lnodes["b"]
        assert top_bound(layout, a, b.order, +1) is None
        assert top_bound(layout, a, b.order, -1) is None

    def test_finds_right_sibling(self):
        # a has two out-edges — pick the head with the lower order as
        # reference and verify top_bound(+1) returns the other.
        layout = _layout("digraph { a -> b; a -> c }")
        a = layout.lnodes["a"]
        b = layout.lnodes["b"]
        c = layout.lnodes["c"]
        low, high = (b, c) if b.order < c.order else (c, b)
        ans = top_bound(layout, a, low.order, +1)
        assert ans is not None and ans.head_name == high.name

    def test_no_right_sibling_past_highest(self):
        layout = _layout("digraph { a -> b; a -> c }")
        a = layout.lnodes["a"]
        high = max((layout.lnodes["b"], layout.lnodes["c"]),
                   key=lambda ln: ln.order)
        assert top_bound(layout, a, high.order, +1) is None

    def test_finds_left_sibling(self):
        layout = _layout("digraph { a -> b; a -> c }")
        a = layout.lnodes["a"]
        low, high = sorted((layout.lnodes["b"], layout.lnodes["c"]),
                            key=lambda ln: ln.order)
        ans = top_bound(layout, a, high.order, -1)
        assert ans is not None and ans.head_name == low.name

    def test_closest_of_two_siblings(self):
        # Three heads at orders 0, 1, 2.  From reference order 0,
        # the closest on the right should be order 1, not order 2.
        layout = _layout("digraph { a -> b; a -> c; a -> d }")
        a = layout.lnodes["a"]
        ref = min(layout.lnodes[n].order for n in ("b", "c", "d"))
        ans = top_bound(layout, a, ref, +1)
        assert ans is not None
        # The returned edge's head should be the next-higher order, not
        # the highest.
        ans_order = layout.lnodes[ans.head_name].order
        other_orders = sorted(layout.lnodes[n].order for n in ("b", "c", "d"))
        assert ans_order == other_orders[1]


class TestBotBound:

    def test_no_siblings_returns_none(self):
        layout = _layout("digraph { a -> b }")
        a = layout.lnodes["a"]
        b = layout.lnodes["b"]
        assert bot_bound(layout, b, a.order, +1) is None
        assert bot_bound(layout, b, a.order, -1) is None

    def test_finds_right_sibling(self):
        # c has two in-edges: a->c and b->c.  Symmetric to top_bound.
        layout = _layout("digraph { a -> c; b -> c }")
        a = layout.lnodes["a"]
        b = layout.lnodes["b"]
        c = layout.lnodes["c"]
        # Pick whichever has lower order as reference; find the other.
        ref_tail, other_tail = (a, b) if a.order < b.order else (b, a)
        ans = bot_bound(layout, c, ref_tail.order, +1)
        assert ans is not None
        assert ans.tail_name == other_tail.name


class TestRegressionSmokeTests:
    """Verify the neighbor-check wiring doesn't break routing."""

    def test_parallel_bundle_routes(self):
        # Two parallel a->b edges: bundle of 2, Multisep offsetting
        # should still run.
        layout = _layout("digraph { a -> b; a -> b }")
        edges = [le for le in layout.ledges
                 if not le.virtual and le.tail_name == "a"
                 and le.head_name == "b"]
        assert len(edges) == 2
        for le in edges:
            assert le.route.points, f"edge lost its spline: {le}"

    def test_multi_rank_chain_routes(self):
        # a -> b -> c -> d  plus a shortcut a -> d spanning 3 ranks.
        layout = _layout("digraph { a -> b; b -> c; c -> d; a -> d }")
        all_edges = layout.ledges + layout._chain_edges
        shortcut = next(le for le in all_edges
                        if le.orig_tail == "a" and le.orig_head == "d"
                        or (not le.virtual and le.tail_name == "a"
                            and le.head_name == "d"))
        assert shortcut.route.points or any(
            le.route.points for le in all_edges
            if (le.orig_tail or le.tail_name) == "a"
            and (le.orig_head or le.head_name) == "d")
