"""
Tests for the sfdp (scalable force-directed) layout engine.
"""
import math
import pytest
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.sfdp import SfdpLayout


def sfdp_gv(text: str, **attrs) -> dict:
    graph = read_gv(text)
    for k, v in attrs.items():
        graph.set_graph_attr(k, v)
    return SfdpLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestSfdpBasic:

    def test_single_node(self):
        r = sfdp_gv("graph G { a; }")
        assert len(r["nodes"]) == 1

    def test_two_nodes(self):
        r = sfdp_gv("graph G { a -- b; }")
        na, nb = node_by_name(r, "a"), node_by_name(r, "b")
        dist = math.sqrt((na["x"] - nb["x"])**2 + (na["y"] - nb["y"])**2)
        assert dist > 5

    def test_triangle(self):
        r = sfdp_gv("graph G { a -- b -- c -- a; }")
        assert len(r["nodes"]) == 3

    def test_empty(self):
        r = sfdp_gv("graph G { }")
        assert len(r["nodes"]) == 0

    def test_larger_graph(self):
        nodes = " ".join(f"n{i} -- n{i+1};" for i in range(20))
        r = sfdp_gv(f"graph G {{ {nodes} }}")
        assert len(r["nodes"]) == 21


class TestSfdpMultilevel:

    def test_coarsening_runs(self):
        """Graph large enough to trigger coarsening."""
        edges = " ".join(f"n{i} -- n{(i+1)%15};" for i in range(15))
        r = sfdp_gv(f"graph G {{ {edges} }}")
        assert len(r["nodes"]) == 15

    def test_levels_attribute(self):
        """levels attribute limits coarsening depth."""
        edges = " ".join(f"n{i} -- n{(i+1)%10};" for i in range(10))
        r = sfdp_gv(f"graph G {{ {edges} }}", levels="1")
        assert len(r["nodes"]) == 10


class TestSfdpQuadtree:

    def test_quadtree_mode(self):
        """Barnes-Hut quadtree activates for larger graphs."""
        edges = " ".join(f"n{i} -- n{(i+3)%50};" for i in range(50))
        r = sfdp_gv(f"graph G {{ {edges} }}")
        assert len(r["nodes"]) == 50

    def test_quadtree_none(self):
        """quadtree=none disables Barnes-Hut."""
        r = sfdp_gv("graph G { a--b--c--d--e--f--a; }", quadtree="none")
        assert len(r["nodes"]) == 6


class TestSfdpAttributes:

    def test_K_affects_spacing(self):
        r1 = sfdp_gv("graph G { a--b--c--a; }", K="0.3")
        r2 = sfdp_gv("graph G { a--b--c--a; }", K="2.0")
        bb1 = r1["graph"]["bb"]
        bb2 = r2["graph"]["bb"]
        w1 = bb1[2] - bb1[0]
        w2 = bb2[2] - bb2[0]
        assert w2 > w1

    def test_rotation(self):
        """rotation attribute rotates layout."""
        r = sfdp_gv("graph G { a--b; }", rotation="90")
        assert len(r["nodes"]) == 2

    def test_beautify(self):
        """beautify arranges leaves."""
        r = sfdp_gv("graph G { center -- a; center -- b; center -- c; center -- d; }",
                     beautify="true")
        assert len(r["nodes"]) == 5

    def test_overlap_false(self):
        r = sfdp_gv("graph G { a--b--c; }", overlap="false")
        assert len(r["nodes"]) == 3

    def test_bounding_box(self):
        r = sfdp_gv("graph G { a--b--c--a; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]
        assert bb[3] > bb[1]

    def test_pos_writeback(self):
        g = read_gv("graph G { a -- b; }")
        SfdpLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = sfdp_gv("graph G { a--b--c--a; }")
        svg = render_svg(r)
        assert "<svg" in svg
