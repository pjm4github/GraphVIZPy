"""
Tests for the circo (circular) layout engine.
"""
import math
import pytest

from gvpy.core.graph import Graph
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.circo import CircoLayout


def circo_dot(dot_text: str) -> dict:
    """Parse DOT text and run circo layout, return JSON result."""
    graph = read_gv(dot_text)
    return CircoLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


# ═══════════════════════════════════════════════════════════════
#  Basic layout
# ═══════════════════════════════════════════════════════════════


class TestCircoBasic:

    def test_single_node(self):
        """Single node placed at origin."""
        r = circo_dot("digraph G { a; }")
        na = node_by_name(r, "a")
        assert na["x"] == pytest.approx(0, abs=1)
        assert na["y"] == pytest.approx(0, abs=1)

    def test_two_nodes(self):
        """Two connected nodes placed on opposite sides."""
        r = circo_dot("digraph G { a -> b; }")
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        # They should be separated
        dist = math.sqrt((na["x"] - nb["x"])**2 + (na["y"] - nb["y"])**2)
        assert dist > 20

    def test_triangle(self):
        """Three nodes form a triangle on a circle."""
        r = circo_dot("digraph G { a -> b -> c -> a; }")
        assert len(r["nodes"]) == 3
        assert len(r["edges"]) == 3

    def test_cycle_four(self):
        """Four-node cycle placed on circle."""
        r = circo_dot("digraph G { a -> b -> c -> d -> a; }")
        nodes = r["nodes"]
        assert len(nodes) == 4
        # All nodes should be roughly equidistant from center
        cx = sum(n["x"] for n in nodes) / 4
        cy = sum(n["y"] for n in nodes) / 4
        dists = [math.sqrt((n["x"] - cx)**2 + (n["y"] - cy)**2) for n in nodes]
        # All distances should be roughly equal (on a circle)
        assert max(dists) - min(dists) < max(dists) * 0.2

    def test_undirected(self):
        """Undirected graph layout."""
        r = circo_dot("graph G { a -- b -- c -- a; }")
        assert r["graph"]["directed"] is False
        assert len(r["nodes"]) == 3

    def test_isolated_nodes(self):
        """Isolated nodes get positions."""
        r = circo_dot("digraph G { a; b; c; }")
        for name in ("a", "b", "c"):
            n = node_by_name(r, name)
            assert n is not None
            assert "x" in n
            assert "y" in n


# ═══════════════════════════════════════════════════════════════
#  Circular placement
# ═══════════════════════════════════════════════════════════════


class TestCircoCircularPlacement:

    def test_nodes_on_circle(self):
        """Nodes in a cycle are placed at equal angles on a circle."""
        r = circo_dot("digraph G { a -> b -> c -> d -> e -> a; }")
        nodes = r["nodes"]
        N = len(nodes)
        assert N == 5
        # Compute center
        cx = sum(n["x"] for n in nodes) / N
        cy = sum(n["y"] for n in nodes) / N
        # All should be at roughly the same radius
        radii = [math.sqrt((n["x"] - cx)**2 + (n["y"] - cy)**2) for n in nodes]
        avg_r = sum(radii) / N
        for r_val in radii:
            assert r_val == pytest.approx(avg_r, rel=0.15)

    def test_large_cycle(self):
        """10-node cycle has reasonable radius."""
        r = circo_dot("digraph G { a->b->c->d->e->f->g->h->i->j->a; }")
        assert len(r["nodes"]) == 10
        # BB should be large enough
        bb = r["graph"]["bb"]
        w = bb[2] - bb[0]
        h = bb[3] - bb[1]
        assert w > 100
        assert h > 100

    def test_mindist_affects_radius(self):
        """mindist attribute increases circle radius."""
        r1 = circo_dot("digraph G { a -> b -> c -> a; }")
        r2 = circo_dot('digraph G { mindist=3; a -> b -> c -> a; }')
        # Larger mindist → larger bounding box
        bb1 = r1["graph"]["bb"]
        bb2 = r2["graph"]["bb"]
        w1 = bb1[2] - bb1[0]
        w2 = bb2[2] - bb2[0]
        assert w2 > w1


# ═══════════════════════════════════════════════════════════════
#  Biconnected components
# ═══════════════════════════════════════════════════════════════


class TestCircoBiconnected:

    def test_single_block(self):
        """Complete graph is a single biconnected component."""
        r = circo_dot("digraph G { a->b; b->c; c->a; }")
        assert len(r["nodes"]) == 3

    def test_two_blocks_with_cut(self):
        """Two triangles sharing a cut vertex produce two blocks."""
        r = circo_dot("digraph G { a->b->c->a; c->d->e->c; }")
        nodes = r["nodes"]
        assert len(nodes) == 5
        # All nodes should have positions
        for n in nodes:
            assert "x" in n
            assert "y" in n

    def test_tree_structure(self):
        """Tree graph: each edge is its own biconnected component."""
        r = circo_dot("digraph G { a->b; a->c; b->d; b->e; }")
        assert len(r["nodes"]) == 5
        assert len(r["edges"]) == 4

    def test_oneblock_attribute(self):
        """oneblock=true skips biconnected decomposition."""
        r = circo_dot('digraph G { oneblock=true; a->b; b->c; c->d; d->a; }')
        assert len(r["nodes"]) == 4


# ═══════════════════════════════════════════════════════════════
#  Edge crossing reduction
# ═══════════════════════════════════════════════════════════════


class TestCircoCrossings:

    def test_crossing_count_no_crossings(self):
        """Simple cycle has no crossings."""
        order = ["a", "b", "c", "d"]
        adj = {"a": ["b", "d"], "b": ["a", "c"],
               "c": ["b", "d"], "d": ["c", "a"]}
        assert CircoLayout._count_crossings(order, adj) == 0

    def test_crossing_count_with_crossings(self):
        """K4 on a circle has crossings."""
        order = ["a", "b", "c", "d"]
        adj = {"a": ["b", "c", "d"], "b": ["a", "c", "d"],
               "c": ["a", "b", "d"], "d": ["a", "b", "c"]}
        assert CircoLayout._count_crossings(order, adj) > 0

    def test_crossing_reduction_improves(self):
        """Crossing reduction should not increase crossings."""
        order = ["a", "c", "b", "d"]  # deliberately bad
        adj = {"a": ["b"], "b": ["a", "c"], "c": ["b", "d"], "d": ["c"]}
        c_before = CircoLayout._count_crossings(order, adj)
        layout = CircoLayout.__new__(CircoLayout)
        improved = layout._reduce_crossings(order, adj)
        c_after = CircoLayout._count_crossings(improved, adj)
        assert c_after <= c_before


# ═══════════════════════════════════════════════════════════════
#  Disconnected components
# ═══════════════════════════════════════════════════════════════


class TestCircoComponents:

    def test_two_components(self):
        """Two disconnected components are laid out and packed."""
        r = circo_dot("digraph G { a->b; c->d; }")
        na = node_by_name(r, "a")
        nc = node_by_name(r, "c")
        # Components should be separated horizontally
        assert abs(na["x"] - nc["x"]) > 20 or abs(na["y"] - nc["y"]) > 20

    def test_single_node_components(self):
        """Multiple isolated nodes are packed."""
        r = circo_dot("digraph G { a; b; c; d; }")
        assert len(r["nodes"]) == 4


# ═══════════════════════════════════════════════════════════════
#  Attributes and output
# ═══════════════════════════════════════════════════════════════


class TestCircoAttributes:

    def test_node_attributes_preserved(self):
        """Node attributes are passed through to JSON."""
        r = circo_dot('digraph G { a [shape=box, color=red]; b; a->b; }')
        na = node_by_name(r, "a")
        assert na["shape"] == "box"
        assert na["color"] == "red"

    def test_edge_attributes_preserved(self):
        """Edge attributes are passed through to JSON."""
        r = circo_dot('digraph G { a -> b [label="test", color=blue]; }')
        e = r["edges"][0]
        assert e["label"] == "test"
        assert e["color"] == "blue"

    def test_edge_label_pos(self):
        """Edge labels get a computed position."""
        r = circo_dot('digraph G { a -> b [label="mid"]; }')
        e = r["edges"][0]
        assert "label_pos" in e
        assert len(e["label_pos"]) == 2

    def test_bounding_box(self):
        """Bounding box is computed correctly."""
        r = circo_dot("digraph G { a -> b -> c -> a; }")
        bb = r["graph"]["bb"]
        assert len(bb) == 4
        assert bb[2] > bb[0]  # max_x > min_x
        assert bb[3] > bb[1]  # max_y > min_y

    def test_root_attribute(self):
        """root attribute selects starting node for DFS."""
        r = circo_dot('digraph G { root=c; a->b->c->a; }')
        assert len(r["nodes"]) == 3

    def test_pos_writeback(self):
        """Layout writes pos back to node attributes."""
        g = read_gv("digraph G { a -> b; }")
        CircoLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes
        assert "," in g.nodes["a"].attributes["pos"]

    def test_svg_output(self):
        """Circo layout can be rendered to SVG."""
        from gvpy.render.svg_renderer import render_svg
        r = circo_dot("digraph G { a -> b -> c -> a; }")
        svg = render_svg(r)
        assert "<svg" in svg
        assert "</svg>" in svg
        assert "a" in svg
