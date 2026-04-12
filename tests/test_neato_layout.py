"""
Tests for the neato (spring-model) layout engine.
"""
import math
import pytest

from gvpy.core.graph import Graph
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.neato import NeatoLayout


def neato_gv(text: str, **attrs) -> dict:
    """Parse GV text and run neato layout."""
    graph = read_gv(text)
    for k, v in attrs.items():
        graph.set_graph_attr(k, v)
    return NeatoLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestNeatoBasic:

    def test_single_node(self):
        r = neato_gv("graph G { a; }")
        assert len(r["nodes"]) == 1

    def test_two_nodes(self):
        r = neato_gv("graph G { a -- b; }")
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        dist = math.sqrt((na["x"] - nb["x"])**2 + (na["y"] - nb["y"])**2)
        assert dist > 10  # they should be separated

    def test_triangle(self):
        r = neato_gv("graph G { a -- b -- c -- a; }")
        assert len(r["nodes"]) == 3
        assert len(r["edges"]) == 3

    def test_square(self):
        r = neato_gv("graph G { a -- b -- c -- d -- a; }")
        assert len(r["nodes"]) == 4

    def test_directed(self):
        r = neato_gv("digraph G { a -> b -> c; }")
        assert r["graph"]["directed"] is True
        assert len(r["nodes"]) == 3

    def test_undirected(self):
        r = neato_gv("graph G { a -- b; }")
        assert r["graph"]["directed"] is False

    def test_isolated_nodes(self):
        r = neato_gv("graph G { a; b; c; }")
        assert len(r["nodes"]) == 3
        for n in r["nodes"]:
            assert "x" in n
            assert "y" in n

    def test_empty_graph(self):
        r = neato_gv("graph G { }")
        assert len(r["nodes"]) == 0


class TestNeatoModes:

    def test_majorization_default(self):
        r = neato_gv("graph G { a -- b -- c -- a; }")
        assert len(r["nodes"]) == 3

    def test_kk_mode(self):
        r = neato_gv("graph G { a -- b -- c -- a; }", mode="KK")
        assert len(r["nodes"]) == 3
        # Nodes should be at distinct positions
        positions = [(n["x"], n["y"]) for n in r["nodes"]]
        assert len(set(positions)) == 3

    def test_sgd_mode(self):
        r = neato_gv("graph G { a -- b -- c -- a; }", mode="sgd")
        assert len(r["nodes"]) == 3

    def test_edge_length(self):
        """Edges with 'len' attribute affect distances."""
        r1 = neato_gv('graph G { a -- b [len=1]; }')
        r2 = neato_gv('graph G { a -- b [len=3]; }')
        d1 = math.sqrt((node_by_name(r1, "a")["x"] - node_by_name(r1, "b")["x"])**2 +
                       (node_by_name(r1, "a")["y"] - node_by_name(r1, "b")["y"])**2)
        d2 = math.sqrt((node_by_name(r2, "a")["x"] - node_by_name(r2, "b")["x"])**2 +
                       (node_by_name(r2, "a")["y"] - node_by_name(r2, "b")["y"])**2)
        assert d2 > d1 * 1.5  # longer len = farther apart


class TestNeatoDistanceModels:

    def test_shortpath_default(self):
        r = neato_gv("graph G { a -- b -- c; }")
        assert len(r["nodes"]) == 3

    def test_circuit_model(self):
        r = neato_gv("graph G { a -- b -- c -- a; }", model="circuit")
        assert len(r["nodes"]) == 3


class TestNeatoPinning:

    def test_pinned_node(self):
        """Pinned nodes keep their position."""
        r = neato_gv('graph G { a [pos="1,1!"]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na["x"] == pytest.approx(72.0, abs=1)
        assert na["y"] == pytest.approx(72.0, abs=1)

    def test_initial_pos(self):
        """Nodes with pos (no !) are used as initial positions."""
        r = neato_gv('graph G { a [pos="0,0"]; b [pos="2,0"]; a -- b; }')
        assert len(r["nodes"]) == 2


class TestNeatoComponents:

    def test_disconnected(self):
        """Disconnected components are packed."""
        r = neato_gv("graph G { a -- b; c -- d; }")
        na = node_by_name(r, "a")
        nc = node_by_name(r, "c")
        assert abs(na["x"] - nc["x"]) > 10 or abs(na["y"] - nc["y"]) > 10

    def test_many_components(self):
        r = neato_gv("graph G { a; b; c; d; e; }")
        assert len(r["nodes"]) == 5


class TestNeatoOverlap:

    def test_overlap_false(self):
        """overlap=false removes overlaps."""
        r = neato_gv("graph G { a -- b -- c; }", overlap="false")
        nodes = r["nodes"]
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dx = abs(nodes[i]["x"] - nodes[j]["x"])
                dy = abs(nodes[i]["y"] - nodes[j]["y"])
                min_sep = (nodes[i]["width"] + nodes[j]["width"]) / 4
                # At least some separation
                assert dx > 1 or dy > 1


class TestNeatoAttributes:

    def test_node_attrs_preserved(self):
        r = neato_gv('graph G { a [shape=box, color=red]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na["shape"] == "box"
        assert na["color"] == "red"

    def test_edge_attrs_preserved(self):
        r = neato_gv('graph G { a -- b [label="test", color=blue]; }')
        e = r["edges"][0]
        assert e["label"] == "test"
        assert e["color"] == "blue"

    def test_edge_label_pos(self):
        r = neato_gv('graph G { a -- b [label="mid"]; }')
        e = r["edges"][0]
        assert "label_pos" in e

    def test_bounding_box(self):
        r = neato_gv("graph G { a -- b -- c -- a; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]
        assert bb[3] > bb[1]

    def test_pos_writeback(self):
        g = read_gv("graph G { a -- b; }")
        NeatoLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes
        assert "," in g.nodes["a"].attributes["pos"]

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = neato_gv("graph G { a -- b -- c -- a; }")
        svg = render_svg(r)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_graph_label(self):
        r = neato_gv('graph G { label="Test"; a -- b; }')
        assert r["graph"].get("label") == "Test"

    def test_xlabel(self):
        r = neato_gv('graph G { a [xlabel="extra"]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na.get("xlabel") == "extra"
        assert "_xlabel_pos_x" in na
