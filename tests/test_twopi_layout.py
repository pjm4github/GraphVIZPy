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
        """Larger ranksep produces wider rings."""
        r1 = twopi_gv('graph G { r -- a -- b; }', ranksep="0.5")
        r2 = twopi_gv('graph G { r -- a -- b; }', ranksep="2.0")
        bb1 = r1["graph"]["bb"]
        bb2 = r2["graph"]["bb"]
        w1 = bb1[2] - bb1[0]
        w2 = bb2[2] - bb2[0]
        assert w2 > w1


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
