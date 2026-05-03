"""
Tests for the fdp (force-directed placement) layout engine.
"""
import math
import pytest

from gvpy.core.graph import Graph
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.fdp import FdpLayout


def fdp_gv(text: str, **attrs) -> dict:
    graph = read_gv(text)
    for k, v in attrs.items():
        graph.set_graph_attr(k, v)
    return FdpLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestFdpBasic:

    def test_single_node(self):
        r = fdp_gv("graph G { a; }")
        assert len(r["nodes"]) == 1

    def test_two_nodes(self):
        r = fdp_gv("graph G { a -- b; }")
        na, nb = node_by_name(r, "a"), node_by_name(r, "b")
        dist = math.sqrt((na["x"] - nb["x"])**2 + (na["y"] - nb["y"])**2)
        assert dist > 5

    def test_triangle(self):
        r = fdp_gv("graph G { a -- b -- c -- a; }")
        assert len(r["nodes"]) == 3
        assert len(r["edges"]) == 3

    def test_square(self):
        r = fdp_gv("graph G { a -- b -- c -- d -- a; }")
        assert len(r["nodes"]) == 4

    def test_directed(self):
        r = fdp_gv("digraph G { a -> b -> c; }")
        assert r["graph"]["directed"] is True

    def test_empty(self):
        r = fdp_gv("graph G { }")
        assert len(r["nodes"]) == 0


class TestFdpForces:

    def test_edge_length(self):
        """Edges with larger 'len' produce more separation."""
        r1 = fdp_gv('graph G { a -- b [len=0.5]; }')
        r2 = fdp_gv('graph G { a -- b [len=3]; }')
        d1 = math.sqrt((node_by_name(r1, "a")["x"] - node_by_name(r1, "b")["x"])**2 +
                       (node_by_name(r1, "a")["y"] - node_by_name(r1, "b")["y"])**2)
        d2 = math.sqrt((node_by_name(r2, "a")["x"] - node_by_name(r2, "b")["x"])**2 +
                       (node_by_name(r2, "a")["y"] - node_by_name(r2, "b")["y"])**2)
        assert d2 > d1 * 1.3

    def test_K_affects_spacing(self):
        """Larger K produces wider layout."""
        r1 = fdp_gv('graph G { a -- b -- c -- a; }', K="0.3")
        r2 = fdp_gv('graph G { a -- b -- c -- a; }', K="1.5")
        bb1 = r1["graph"]["bb"]
        bb2 = r2["graph"]["bb"]
        w1 = bb1[2] - bb1[0]
        w2 = bb2[2] - bb2[0]
        assert w2 > w1


class TestFdpPinning:

    def test_pinned_node(self):
        r = fdp_gv('graph G { a [pos="1,1!"]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na["x"] == pytest.approx(72.0, abs=2)
        assert na["y"] == pytest.approx(72.0, abs=2)


class TestFdpComponents:

    def test_disconnected(self):
        r = fdp_gv("graph G { a -- b; c -- d; }")
        na = node_by_name(r, "a")
        nc = node_by_name(r, "c")
        assert abs(na["x"] - nc["x"]) > 10 or abs(na["y"] - nc["y"]) > 10


class TestFdpOverlap:

    def test_overlap_false(self):
        r = fdp_gv("graph G { a -- b -- c; }", overlap="false")
        nodes = r["nodes"]
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dx = abs(nodes[i]["x"] - nodes[j]["x"])
                dy = abs(nodes[i]["y"] - nodes[j]["y"])
                assert dx > 1 or dy > 1


class TestFdpAttributes:

    def test_node_attrs(self):
        r = fdp_gv('graph G { a [shape=box, color=red]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na["shape"] == "box"
        assert na["color"] == "red"

    def test_edge_attrs(self):
        r = fdp_gv('graph G { a -- b [label="test", color=blue]; }')
        e = r["edges"][0]
        assert e["label"] == "test"
        assert e["color"] == "blue"

    def test_bounding_box(self):
        r = fdp_gv("graph G { a -- b -- c -- a; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]
        assert bb[3] > bb[1]

    def test_pos_writeback(self):
        g = read_gv("graph G { a -- b; }")
        FdpLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = fdp_gv("graph G { a -- b -- c -- a; }")
        svg = render_svg(r)
        assert "<svg" in svg
        assert "</svg>" in svg


class TestFdpAlignment:
    """§4.F C-alignment tests for the lib/fdpgen/ port."""

    def test_grid_build(self):
        """build_grid bins nodes into cells of the requested size."""
        from gvpy.engines.layout.fdp.grid import build_grid

        class FakeLN:
            def __init__(self, x, y):
                self.x, self.y = x, y

        lnodes = {
            "a": FakeLN(0, 0),
            "b": FakeLN(50, 0),
            "c": FakeLN(0, 50),
            "d": FakeLN(120, 120),
        }
        grid = build_grid(["a", "b", "c", "d"], lnodes, cell_size=100)
        # a, b, c all in cell (0, 0); d in cell (1, 1).
        assert sorted(grid[(0, 0)]) == ["a", "b", "c"]
        assert grid[(1, 1)] == ["d"]

    def test_neighbour_offsets(self):
        """Moore neighbourhood — 8 cells, excluding (0, 0)."""
        from gvpy.engines.layout.fdp.grid import neighbour_offsets
        offsets = neighbour_offsets()
        assert len(offsets) == 8
        assert (0, 0) not in offsets
        assert (-1, -1) in offsets
        assert (1, 1) in offsets

    def test_overlap_dispatch_via_common_adjust(self):
        """``overlap=`` modes route through common.adjust dispatcher.

        Each named mode should layout cleanly without raising.
        """
        for ov in ("true", "fdp", "scale", "scalexy", "voronoi",
                   "compress"):
            r = fdp_gv(
                f"graph G {{ overlap={ov}; "
                f"node [shape=box, width=2.0, height=1.5]; "
                f"a -- b; b -- c; c -- a; }}"
            )
            assert len(r["nodes"]) == 3

    def test_splines_default_emits_bezier(self):
        """``splines=spline`` (default) produces bezier edge routes
        — fdp reuses the common edge_routing helper."""
        r = fdp_gv("graph G { a -- b -- c -- a; }")
        for e in r["edges"]:
            assert e.get("spline_type") == "bezier"
            assert (len(e["points"]) - 1) % 3 == 0

    def test_splines_polyline_mode(self):
        """``splines=polyline`` produces polyline routes."""
        r = fdp_gv("graph G { splines=polyline; a -- b -- c -- a; }")
        for e in r["edges"]:
            assert e.get("spline_type") == "polyline"

    def test_xlayout_clears_overlap(self):
        """``overlap=fdp`` runs the xlayout force-based overlap pass
        and produces non-overlapping output on a small case."""
        r = fdp_gv(
            "graph G { overlap=fdp; "
            "node [shape=box, width=2.0, height=1.5]; "
            "a -- b; a -- c; a -- d; b -- c; c -- d; b -- d; }"
        )
        nodes = r["nodes"]
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                ovx = abs(a["x"] - b["x"]) < (a["width"] + b["width"]) / 2
                ovy = abs(a["y"] - b["y"]) < (a["height"] + b["height"]) / 2
                assert not (ovx and ovy), (
                    f"overlap pair after xlayout: {a['name']} {b['name']}"
                )
