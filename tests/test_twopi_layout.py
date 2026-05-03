"""
Tests for the twopi (radial) layout engine.
"""
import math
import pytest
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.twopi import TwopiLayout


def twopi_gv(text: str, **attrs) -> dict:
    graph = read_gv(text)
    for k, v in attrs.items():
        graph.set_graph_attr(k, v)
    return TwopiLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestTwopiBasic:

    def test_single_node(self):
        r = twopi_gv("graph G { a; }")
        assert len(r["nodes"]) == 1

    def test_two_nodes(self):
        r = twopi_gv("graph G { a -- b; }")
        assert len(r["nodes"]) == 2
        na, nb = node_by_name(r, "a"), node_by_name(r, "b")
        dist = math.sqrt((na["x"] - nb["x"])**2 + (na["y"] - nb["y"])**2)
        assert dist > 10

    def test_star_graph(self):
        r = twopi_gv("graph G { c -- a; c -- b; c -- d; c -- e; }")
        assert len(r["nodes"]) == 5

    def test_empty(self):
        r = twopi_gv("graph G { }")
        assert len(r["nodes"]) == 0

    def test_directed(self):
        r = twopi_gv("digraph G { a -> b -> c; }")
        assert r["graph"]["directed"] is True


class TestTwopiRadial:

    def test_root_at_center(self):
        """Root node should be at the origin."""
        r = twopi_gv('graph G { root=center; center -- a; center -- b; center -- c; }')
        nc = node_by_name(r, "center")
        assert nc["x"] == pytest.approx(0, abs=1)
        assert nc["y"] == pytest.approx(0, abs=1)

    def test_children_on_ring(self):
        """Direct children should be equidistant from root."""
        r = twopi_gv('graph G { root=c; c -- a; c -- b; c -- d; }')
        nc = node_by_name(r, "c")
        children = [node_by_name(r, n) for n in ("a", "b", "d")]
        radii = [math.sqrt((ch["x"] - nc["x"])**2 + (ch["y"] - nc["y"])**2)
                 for ch in children]
        avg = sum(radii) / len(radii)
        for rad in radii:
            assert rad == pytest.approx(avg, rel=0.1)

    def test_deeper_levels_farther(self):
        """Level 2 nodes should be farther from root than level 1."""
        r = twopi_gv('graph G { root=r; r -- a; a -- b; }')
        nr = node_by_name(r, "r")
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        dist_a = math.sqrt((na["x"] - nr["x"])**2 + (na["y"] - nr["y"])**2)
        dist_b = math.sqrt((nb["x"] - nr["x"])**2 + (nb["y"] - nr["y"])**2)
        assert dist_b > dist_a

    def test_ranksep_affects_radius(self):
        """Larger ranksep produces wider rings.

        Use a star graph (centre + 3 spokes) so the rings spread on
        both axes — a 3-path lays out vertically, leaving x-width
        invariant under ranksep changes.
        """
        r1 = twopi_gv('graph G { c -- a; c -- b; c -- d; }', ranksep="0.5")
        r2 = twopi_gv('graph G { c -- a; c -- b; c -- d; }', ranksep="2.0")
        bb1 = r1["graph"]["bb"]
        bb2 = r2["graph"]["bb"]
        # Compare layout extent — area of the bbox — instead of one axis.
        a1 = (bb1[2] - bb1[0]) * (bb1[3] - bb1[1])
        a2 = (bb2[2] - bb2[0]) * (bb2[3] - bb2[1])
        assert a2 > a1


class TestTwopiRoot:

    def test_root_attribute(self):
        """root graph attribute selects root node."""
        r = twopi_gv('graph G { root=x; a -- b -- x -- c; }')
        nx = node_by_name(r, "x")
        assert nx["x"] == pytest.approx(0, abs=1)
        assert nx["y"] == pytest.approx(0, abs=1)

    def test_node_root_attribute(self):
        """Node with root=true becomes root."""
        r = twopi_gv('graph G { a -- b; b [root=true]; }')
        nb = node_by_name(r, "b")
        assert nb["x"] == pytest.approx(0, abs=1)

    def test_auto_root(self):
        """Auto root selection picks graph center."""
        r = twopi_gv("graph G { a -- b -- c -- d -- e; }")
        assert len(r["nodes"]) == 5


class TestTwopiComponents:

    def test_disconnected(self):
        r = twopi_gv("graph G { a -- b; c -- d; }")
        na = node_by_name(r, "a")
        nc = node_by_name(r, "c")
        assert abs(na["x"] - nc["x"]) > 10 or abs(na["y"] - nc["y"]) > 10


class TestTwopiAttributes:

    def test_node_attrs(self):
        r = twopi_gv('graph G { a [shape=box, color=red]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na["shape"] == "box"

    def test_bounding_box(self):
        r = twopi_gv("graph G { a -- b -- c -- a; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]

    def test_pos_writeback(self):
        g = read_gv("graph G { a -- b; }")
        TwopiLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = twopi_gv("graph G { c -- a; c -- b; c -- d; }")
        svg = render_svg(r)
        assert "<svg" in svg


class TestTwopiAlignment:
    """§4.T C-alignment tests for the lib/twopigen/circle.c port."""

    def test_centre_finding_picks_max_sleaf(self):
        """find_center_node should pick the most-interior node.

        For a 5-path a-b-c-d-e the centre is c (max distance to any
        leaf = 2).  The C algorithm selects the node with highest
        s_leaf, which is the same definition.
        """
        r = twopi_gv("graph G { a -- b -- c -- d -- e; }")
        nc = node_by_name(r, "c")
        assert nc["x"] == pytest.approx(0, abs=1)
        assert nc["y"] == pytest.approx(0, abs=1)

    def test_is_leaf(self):
        """is_leaf returns True for nodes with at most one distinct
        neighbour (excluding self-loops)."""
        from gvpy.engines.layout.twopi.circle import is_leaf
        adj = {"a": ["b"], "b": ["a", "c"], "c": ["b"]}
        assert is_leaf("a", adj)
        assert not is_leaf("b", adj)
        assert is_leaf("c", adj)
        # Self-loop only — still a leaf.
        assert is_leaf("d", {"d": ["d"]})

    def test_subtree_size_counts_leaves(self):
        """``stsize`` per node equals the number of leaves in its
        BFS-tree subtree."""
        from gvpy.engines.layout.twopi import TwopiLayout
        # Centre c with 3 spokes — c has 3 leaf children, stsize=3.
        graph = read_gv('graph G { root=c; c -- a; c -- b; c -- d; }')
        layout = TwopiLayout(graph)
        layout.layout()
        assert layout.lnodes["c"].stsize == 3
        assert layout.lnodes["a"].stsize == 1
        assert layout.lnodes["b"].stsize == 1
        assert layout.lnodes["d"].stsize == 1

    def test_get_ranksep_array_default(self):
        """``ranksep`` empty string ⇒ all rings DEF_RANKSEP apart."""
        from gvpy.engines.layout.twopi.circle import (
            get_ranksep_array, DEF_RANKSEP,
        )
        ranks = get_ranksep_array("", 3)
        assert ranks[0] == 0.0
        assert ranks[1] == DEF_RANKSEP
        assert ranks[2] == 2 * DEF_RANKSEP
        assert ranks[3] == 3 * DEF_RANKSEP

    def test_get_ranksep_array_explicit_list(self):
        """Colon-separated ranksep gives per-ring deltas; last value
        repeats."""
        from gvpy.engines.layout.twopi.circle import get_ranksep_array
        ranks = get_ranksep_array("0.5:1.0:2.0", 5)
        # In points: 0.5 → 36, 1.0 → 72, 2.0 → 144.  Cumulative.
        assert ranks[0] == 0.0
        assert ranks[1] == pytest.approx(36.0)
        assert ranks[2] == pytest.approx(36.0 + 72.0)
        assert ranks[3] == pytest.approx(36.0 + 72.0 + 144.0)
        # Beyond list — repeat the last delta (144).
        assert ranks[4] == pytest.approx(36.0 + 72.0 + 144.0 + 144.0)
        assert ranks[5] == pytest.approx(36.0 + 72.0 + 144.0 + 144.0 * 2)

    def test_splines_default_emits_bezier(self):
        """``splines=spline`` (default) produces bezier edge routes
        — twopi reuses the neato spline router."""
        r = twopi_gv("graph G { c -- a; c -- b; c -- d; }")
        for e in r["edges"]:
            assert e.get("spline_type") == "bezier"
            assert (len(e["points"]) - 1) % 3 == 0

    def test_overlap_dispatch_via_neato_adjust(self):
        """``overlap=`` attribute routes through the neato dispatcher."""
        # No crash + one of the C-aligned modes works end-to-end.
        for ov in ("true", "false", "scale", "voronoi", "compress"):
            r = twopi_gv(
                f"graph G {{ overlap={ov}; "
                f"node [shape=box, width=2.0, height=1.5]; "
                f"c -- a; c -- b; c -- d; c -- e; }}"
            )
            assert len(r["nodes"]) == 5
