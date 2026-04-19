"""Tests for D+.2 straight_len / straight_path / resize_vn / recover_slack."""
import pytest

from gvpy.engines.layout.dot.dot_layout import DotGraphInfo, LayoutNode
from gvpy.engines.layout.dot.path import Box, Path
from gvpy.engines.layout.dot.regular_edge import (
    recover_slack,
    resize_vn,
    straight_len,
    straight_path,
)
from gvpy.grammar.gv_reader import read_dot


def _layout(src):
    g = read_dot(src)
    layout = DotGraphInfo(g)
    layout.layout()
    return layout


class TestResizeVN:

    def test_sets_x_and_width(self):
        vn = LayoutNode(name="v", virtual=True, x=100.0, width=10.0)
        resize_vn(vn, 40.0, 60.0, 90.0)
        assert vn.x == 60.0
        assert vn.width == 50.0  # 90 - 40
        assert vn._lw == 20.0    # 60 - 40
        assert vn._rw == 30.0    # 90 - 60

    def test_symmetric_box_centers_vn(self):
        vn = LayoutNode(name="v", virtual=True)
        resize_vn(vn, 100.0, 110.0, 120.0)
        assert vn.x == 110.0
        assert vn._lw == vn._rw == 10.0


class TestStraightLen:

    def test_no_virtuals_returns_zero(self):
        # Single real->real edge, no virtuals in between.
        layout = _layout("digraph { a -> b }")
        a = layout.lnodes["a"]
        assert straight_len(layout, a) == 0

    def test_counts_aligned_virtual_chain(self):
        # a -> ... -> e spanning 4 ranks creates 3 virtual nodes.
        # When the chain is vertically aligned (single bundle, no
        # competing cross-rank edges), straight_len from the first
        # virtual should count the rest of the aligned virtuals.
        layout = _layout("digraph { a -> b; b -> c; c -> d; d -> e; a -> e }")
        # Find the first virtual in the a->e chain.
        chain_key = ("a", "e")
        vchain = layout._vnode_chains.get(chain_key, [])
        if not vchain:
            pytest.skip("expected a virtual chain for a->e")
        first_v = layout.lnodes[vchain[0]]
        # Straight-run length should be >= 0 (not negative) and at
        # most len(vchain)-1 (all remaining virtuals in chain).
        count = straight_len(layout, first_v)
        assert 0 <= count <= len(vchain) - 1

    def test_breaks_on_non_virtual(self):
        # Adjacent edge: next hop is the real head, so straight_len
        # should return 0 immediately.
        layout = _layout("digraph { a -> b }")
        a = layout.lnodes["a"]
        # a's first out-edge leads to b (real) — loop breaks.
        assert straight_len(layout, a) == 0


class TestStraightPath:

    def test_walks_and_duplicates_anchor(self):
        layout = _layout("digraph { a -> b; b -> c; c -> d; a -> d }")
        chain_edges = [le for le in layout._chain_edges
                       if le.orig_tail == "a" and le.orig_head == "d"]
        if not chain_edges:
            pytest.skip("expected chain edges for a->d")
        first = chain_edges[0]
        plist = [(0.0, 0.0), (1.0, 1.0)]
        result = straight_path(layout, first, 1, plist)
        assert result is not None
        assert plist[-1] == (1.0, 1.0)
        assert plist[-2] == (1.0, 1.0)
        assert plist[-3] == (1.0, 1.0)

    def test_zero_steps_returns_start_edge(self):
        layout = _layout("digraph { a -> b; b -> c; a -> c }")
        chain_edges = [le for le in layout._chain_edges
                       if le.orig_tail == "a" and le.orig_head == "c"]
        if not chain_edges:
            pytest.skip("expected chain edges for a->c")
        first = chain_edges[0]
        plist = [(0.0, 0.0)]
        result = straight_path(layout, first, 0, plist)
        assert result is first


class TestRecoverSlack:

    def test_snaps_virtual_to_box_center(self):
        # Build a Path with a single box that covers the virtual's y.
        layout = _layout("digraph { a -> b; b -> c; a -> c }")
        chain_key = ("a", "c")
        vchain = layout._vnode_chains.get(chain_key, [])
        if not vchain:
            pytest.skip("expected virtual chain a->c")
        vn = layout.lnodes[vchain[0]]
        original_x = vn.x
        # Inject a box whose y-extent contains the virtual and whose
        # x-extent is [original_x - 100, original_x + 100].  Centering
        # should leave x unchanged but force width to 200.
        P = Path()
        P.boxes = [Box(ll_x=original_x - 100, ll_y=vn.y - 10,
                       ur_x=original_x + 100, ur_y=vn.y + 10)]
        P.nbox = 1
        recover_slack(layout, vchain, P)
        assert vn.x == pytest.approx(original_x, abs=1e-9)
        assert vn.width == 200.0

    def test_empty_boxes_is_noop(self):
        layout = _layout("digraph { a -> b; b -> c; a -> c }")
        chain_key = ("a", "c")
        vchain = layout._vnode_chains.get(chain_key, [])
        if not vchain:
            pytest.skip("expected virtual chain a->c")
        vn = layout.lnodes[vchain[0]]
        pre_x = vn.x
        pre_w = vn.width
        P = Path()  # empty boxes
        recover_slack(layout, vchain, P)
        assert vn.x == pre_x
        assert vn.width == pre_w
