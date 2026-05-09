"""
Tests for the circo (circular) layout engine.
"""
import math
import pytest

from gvpy.core.graph import Graph
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.circo import CircoLayout


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

    def _make_layout_with_weights(self, adj):
        """Create a CircoLayout instance with edge weights for testing."""
        g = Graph("test", directed=True)
        g.method_init()
        for n in adj:
            g.add_node(n)
        layout = CircoLayout(g)
        layout._edge_weights = {}
        for u, nbrs in adj.items():
            for v in nbrs:
                pair = (min(u, v), max(u, v))
                layout._edge_weights[pair] = 1.0
        return layout

    def test_crossing_count_no_crossings(self):
        """Simple cycle has no crossings."""
        order = ["a", "b", "c", "d"]
        adj = {"a": ["b", "d"], "b": ["a", "c"],
               "c": ["b", "d"], "d": ["c", "a"]}
        layout = self._make_layout_with_weights(adj)
        assert layout._count_crossings(order, adj) == 0

    def test_crossing_count_with_crossings(self):
        """K4 on a circle has crossings."""
        order = ["a", "b", "c", "d"]
        adj = {"a": ["b", "c", "d"], "b": ["a", "c", "d"],
               "c": ["a", "b", "d"], "d": ["a", "b", "c"]}
        layout = self._make_layout_with_weights(adj)
        assert layout._count_crossings(order, adj) > 0

    def test_crossing_reduction_improves(self):
        """Crossing reduction should not increase crossings."""
        order = ["a", "c", "b", "d"]  # deliberately bad
        adj = {"a": ["b"], "b": ["a", "c"], "c": ["b", "d"], "d": ["c"]}
        layout = self._make_layout_with_weights(adj)
        c_before = layout._count_crossings(order, adj)
        improved = layout._reduce_crossings(order, adj)
        c_after = layout._count_crossings(improved, adj)
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


class TestCircoBlocktreeCAligned:
    """C-aligned port of ``lib/circogen/blocktree.c`` —
    biconnected component decomposition.
    """

    def test_triangle_single_block(self):
        from gvpy.engines.layout.circo.blocktree import (
            create_blocktree,
        )
        adj = {"a": ["b", "c"], "b": ["a", "c"], "c": ["a", "b"]}
        root = create_blocktree(adj, ["a", "b", "c"])
        assert root is not None
        assert sorted(root.sub_graph) == ["a", "b", "c"]
        assert len(root.children) == 0

    def test_two_triangles_share_cut_vertex(self):
        """Shared node is the articulation point.  C model:
        it lives in only ONE block (whichever DFS visits first)."""
        from gvpy.engines.layout.circo.blocktree import (
            create_blocktree,
        )
        adj = {
            "a": ["b", "c", "d", "e"],
            "b": ["a", "c"], "c": ["a", "b"],
            "d": ["a", "e"], "e": ["a", "d"],
        }
        root = create_blocktree(adj, ["a", "b", "c", "d", "e"])
        assert len(root.children) == 1
        a_in_root = "a" in root.sub_graph
        a_in_child = "a" in root.children[0].sub_graph
        assert a_in_root != a_in_child
        if "a" in root.sub_graph:
            assert root.children[0].parent_anchor == "a"

    def test_linear_chain_each_edge_is_block(self):
        from gvpy.engines.layout.circo.blocktree import (
            create_blocktree,
        )
        adj = {
            "a": ["b"], "b": ["a", "c"],
            "c": ["b", "d"], "d": ["c"],
        }
        root = create_blocktree(adj, ["a", "b", "c", "d"])
        assert root is not None
        blocks: list = []

        def walk(b):
            blocks.append(b)
            for ch in b.children:
                walk(ch)

        walk(root)
        for b in blocks:
            assert len(b.sub_graph) <= 2

    def test_bowtie_anchor_semantics(self):
        from gvpy.engines.layout.circo.blocktree import (
            create_blocktree,
        )
        adj = {
            "a": ["b", "c", "d", "e"],
            "b": ["a", "c"], "c": ["a", "b"],
            "d": ["a", "e"], "e": ["a", "d"],
        }
        root = create_blocktree(adj, ["a", "b", "c", "d", "e"])
        ch = root.children[0]
        assert ch.child in ch.sub_graph
        assert ch.parent_anchor in root.sub_graph

    def test_root_block_contains_root_node(self):
        from gvpy.engines.layout.circo.blocktree import (
            create_blocktree,
        )
        adj = {
            "x": ["a"],
            "a": ["x", "b", "c"],
            "b": ["a", "c"], "c": ["a", "b"],
        }
        root = create_blocktree(
            adj, ["x", "a", "b", "c"], root_name="x",
        )
        assert root is not None
        assert "x" in root.sub_graph

    def test_empty_input_returns_none(self):
        from gvpy.engines.layout.circo.blocktree import (
            create_blocktree,
        )
        assert create_blocktree({}, []) is None

    def test_single_node_singleton_block(self):
        from gvpy.engines.layout.circo.blocktree import (
            create_blocktree,
        )
        root = create_blocktree({"a": []}, ["a"])
        assert root is not None
        assert root.sub_graph == ["a"]

    def test_engine_dispatch_default_c(self):
        graph = read_gv(
            "digraph G { a -- b -- c -- a; b -- d; "
            "d -- e -- f -- d; }"
        )
        result = CircoLayout(graph).layout()
        names = {n["name"] for n in result["nodes"]}
        assert names == {"a", "b", "c", "d", "e", "f"}

    def test_engine_dispatch_legacy(self, monkeypatch):
        monkeypatch.setenv("GVPY_CIRCO_BLOCKTREE", "legacy")
        graph = read_gv("digraph G { a -- b -- c -- a; b -- d; }")
        result = CircoLayout(graph).layout()
        names = {n["name"] for n in result["nodes"]}
        assert names == {"a", "b", "c", "d"}


class TestCircoBlockNodelistCAligned:
    """C-aligned ports of ``block.h`` Blocklist + ``nodelist.c``."""

    def test_blocklist_append_and_insert(self):
        from gvpy.engines.layout.circo.block import (
            Blocklist, make_block,
        )
        bl = Blocklist()
        b1 = make_block(["a"])
        b2 = make_block(["b"])
        b3 = make_block(["c"])
        bl.append(b1)
        bl.append(b2)
        bl.insert(b3)  # front-insert
        assert bl.first is b3
        assert bl.last is b2

    def test_nodelist_append_at(self):
        from gvpy.engines.layout.circo.nodelist import append_at
        lst = ["a", "c", "d"]
        append_at(lst, 1, "b")
        assert lst == ["a", "b", "c", "d"]

    def test_nodelist_realign(self):
        from gvpy.engines.layout.circo.nodelist import realign
        lst = ["a", "b", "c", "d"]
        realign(lst, 2)
        assert lst == ["c", "d", "a", "b"]

    def test_nodelist_insert_relative_after(self):
        from gvpy.engines.layout.circo.nodelist import (
            insert_relative,
        )
        lst = ["a", "b", "c", "d"]
        insert_relative(lst, "d", "a", position=1)
        assert lst == ["a", "d", "b", "c"]

    def test_nodelist_insert_relative_before(self):
        from gvpy.engines.layout.circo.nodelist import (
            insert_relative,
        )
        lst = ["a", "b", "c", "d"]
        insert_relative(lst, "d", "b", position=0)
        assert lst == ["a", "d", "b", "c"]

    def test_nodelist_reverse_append(self):
        from gvpy.engines.layout.circo.nodelist import (
            reverse_append,
        )
        l1 = ["a", "b"]
        l2 = ["c", "d", "e"]
        reverse_append(l1, l2)
        assert l1 == ["a", "b", "e", "d", "c"]
        assert l2 == []

    def test_block_aliases_round_trip(self):
        from gvpy.engines.layout.circo.block import make_block
        b = make_block(["a", "b"])
        assert b.nodes == ["a", "b"]
        b.cut_node = "x"
        assert b.parent_anchor == "x"
        b.circle_order = ["b", "a"]
        assert b.circle_list == ["b", "a"]

    def test_block_coalesced_flag(self):
        from gvpy.engines.layout.circo.block import (
            make_block, is_coalesced, set_coalesced,
        )
        b = make_block(["a"])
        assert not is_coalesced(b)
        set_coalesced(b)
        assert is_coalesced(b)


class TestCircoBlockpathCAligned:
    """C-aligned port of ``lib/circogen/blockpath.c``."""

    def test_4cycle_circle_radius(self):
        """A 4-cycle a-b-c-d-a lays out as a 4-node circle.
        Radius = N · (mindist + largest_node) / (2π).
        """
        import math
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.blockpath import layout_block
        b = make_block(["a", "b", "c", "d"])
        b.edges = [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")]
        adj = {
            "a": ["b", "d"], "b": ["a", "c"],
            "c": ["b", "d"], "d": ["c", "a"],
        }
        widths = {n: 54.0 for n in b.sub_graph}
        heights = {n: 36.0 for n in b.sub_graph}
        order = layout_block(b, adj, widths, heights, min_dist=72.0)
        assert len(order) == 4
        expected_radius = 4 * (72.0 + 54.0) / (2 * math.pi)
        assert abs(b.radius - expected_radius) < 0.5

    def test_4cycle_nodes_equispaced(self):
        """Nodes equispaced at 90° intervals on a 4-cycle."""
        import math
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.blockpath import layout_block
        b = make_block(["a", "b", "c", "d"])
        b.edges = [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")]
        adj = {
            "a": ["b", "d"], "b": ["a", "c"],
            "c": ["b", "d"], "d": ["c", "a"],
        }
        widths = {n: 54.0 for n in b.sub_graph}
        heights = {n: 36.0 for n in b.sub_graph}
        layout_block(b, adj, widths, heights, min_dist=72.0)
        # Compute angles of all 4 nodes.
        angles = sorted(
            math.atan2(p[1], p[0]) for p in b.node_pos.values()
        )
        # Adjacent angles should differ by ≈ π/2.
        for i in range(len(angles) - 1):
            assert abs(angles[i + 1] - angles[i] - math.pi / 2) < 0.05

    def test_single_node_block(self):
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.blockpath import layout_block
        b = make_block(["only"])
        b.edges = []
        adj = {"only": []}
        widths = {"only": 50.0}
        heights = {"only": 30.0}
        order = layout_block(b, adj, widths, heights, min_dist=72.0)
        assert order == ["only"]
        assert b.node_pos["only"] == (0.0, 0.0)
        # radius = max(w, h) / 2.
        assert b.radius == 25.0

    def test_two_node_block(self):
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.blockpath import layout_block
        b = make_block(["x", "y"])
        b.edges = [("x", "y")]
        adj = {"x": ["y"], "y": ["x"]}
        widths = {"x": 50.0, "y": 50.0}
        heights = {"x": 30.0, "y": 30.0}
        layout_block(b, adj, widths, heights, min_dist=72.0)
        # Two nodes placed at (±radius, 0).
        positions = list(b.node_pos.values())
        assert len(positions) == 2
        x_coords = sorted(p[0] for p in positions)
        assert abs(x_coords[0] + b.radius) < 0.5
        assert abs(x_coords[1] - b.radius) < 0.5

    def test_count_crossings_no_crossings(self):
        """Path layout of a 4-cycle in adjacent order has 0
        crossings."""
        from gvpy.engines.layout.circo.blockpath import (
            _count_all_crossings,
        )
        path = ["a", "b", "c", "d"]
        edges = [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")]
        adj = {
            "a": ["b", "d"], "b": ["a", "c"],
            "c": ["b", "d"], "d": ["c", "a"],
        }
        n = _count_all_crossings(path, list(path), edges, adj)
        assert n == 0

    def test_count_crossings_K4_complete(self):
        """K4 (complete graph on 4 nodes) has crossings unless
        carefully ordered.  For path order [a, b, c, d] the
        diagonals a-c and b-d cross."""
        from gvpy.engines.layout.circo.blockpath import (
            _count_all_crossings,
        )
        path = ["a", "b", "c", "d"]
        edges = [
            ("a", "b"), ("a", "c"), ("a", "d"),
            ("b", "c"), ("b", "d"), ("c", "d"),
        ]
        adj = {
            "a": ["b", "c", "d"], "b": ["a", "c", "d"],
            "c": ["a", "b", "d"], "d": ["a", "b", "c"],
        }
        n = _count_all_crossings(path, list(path), edges, adj)
        # K4 has exactly 1 crossing in any 4-node ordering.
        assert n >= 1

    def test_engine_dispatch_default(self):
        """Default engine path uses C-aligned blockpath."""
        graph = read_gv("digraph G { a -- b -- c -- a; b -- d; }")
        result = CircoLayout(graph).layout()
        names = {n["name"] for n in result["nodes"]}
        assert names == {"a", "b", "c", "d"}

    def test_engine_dispatch_legacy_blockpath(self, monkeypatch):
        """``GVPY_CIRCO_BLOCKPATH=legacy`` reverts to homegrown
        layout."""
        monkeypatch.setenv("GVPY_CIRCO_BLOCKPATH", "legacy")
        graph = read_gv("digraph G { a -- b -- c -- a; b -- d; }")
        result = CircoLayout(graph).layout()
        names = {n["name"] for n in result["nodes"]}
        assert names == {"a", "b", "c", "d"}


class TestCircoCircposCAligned:
    """C-aligned port of ``lib/circogen/circpos.c``."""

    def test_apply_delta_translates(self):
        """``apply_delta`` translates every node in a block."""
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.circpos import apply_delta
        b = make_block(["a", "b"])
        b.node_pos = {"a": (0.0, 0.0), "b": (10.0, 0.0)}
        apply_delta(b, 100.0, 50.0, 0.0)  # no rotation
        assert b.node_pos["a"] == (100.0, 50.0)
        assert b.node_pos["b"] == (110.0, 50.0)

    def test_apply_delta_rotates(self):
        """``apply_delta`` with rotate=π/2 swaps x↔y axes."""
        import math
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.circpos import apply_delta
        b = make_block(["a"])
        b.node_pos = {"a": (10.0, 0.0)}
        apply_delta(b, 0.0, 0.0, math.pi / 2)
        ax, ay = b.node_pos["a"]
        # (10, 0) rotated by 90° should be (~0, 10).
        assert abs(ax) < 1e-9
        assert abs(ay - 10.0) < 1e-9

    def test_get_rotation_2node_block(self):
        """``get_rotation`` for a 2-node block returns
        theta - π/2 (mirrors C circpos.c:69)."""
        import math
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.circpos import get_rotation
        b = make_block(["a", "b"])
        b.circle_list = ["a", "b"]
        b.node_pos = {"a": (10.0, 0.0), "b": (-10.0, 0.0)}
        b.parent_pos = -1.0  # not the parent_pos branch
        b.child = "a"
        rot = get_rotation(b, 5.0, 5.0, math.pi / 4)
        assert abs(rot - (math.pi / 4 - math.pi / 2)) < 1e-9

    def test_get_rotation_parent_pos_branch(self):
        """If ``parent_pos`` is set (1-node block), get_rotation
        uses the closed-form ``theta + π - parent_pos``."""
        import math
        from gvpy.engines.layout.circo.block import make_block
        from gvpy.engines.layout.circo.circpos import get_rotation
        b = make_block(["only"])
        b.circle_list = ["only"]
        b.node_pos = {"only": (0.0, 0.0)}
        b.parent_pos = math.pi / 4  # 45° offset
        rot = get_rotation(b, 0.0, 1.0, math.pi / 2)
        # theta + π - parent_pos = π/2 + π - π/4 = 5π/4.
        expected = math.pi / 2 + math.pi - math.pi / 4
        assert abs(rot - expected) < 1e-9

    def test_engine_dispatch_legacy_circpos(self, monkeypatch):
        """``GVPY_CIRCO_CIRCPOS=legacy`` reverts to homegrown
        positioning."""
        monkeypatch.setenv("GVPY_CIRCO_CIRCPOS", "legacy")
        graph = read_gv("digraph G { a -- b -- c -- a; b -- d -- e; }")
        result = CircoLayout(graph).layout()
        names = {n["name"] for n in result["nodes"]}
        assert names == {"a", "b", "c", "d", "e"}

    def test_engine_block_tree_with_three_blocks(self):
        """Triangle a-b-c-a + edge b-d + triangle d-e-f-d:
        three biconnected blocks linked by articulation points
        b and d.  All 6 nodes laid out without errors."""
        graph = read_gv(
            "digraph G { a -- b -- c -- a; b -- d; "
            "d -- e -- f -- d; }"
        )
        result = CircoLayout(graph).layout()
        names = {n["name"] for n in result["nodes"]}
        assert names == {"a", "b", "c", "d", "e", "f"}
        # No node at origin (everything got placed).
        for n in result["nodes"]:
            assert not (n["x"] == 0 and n["y"] == 0) or n["name"] == "a"
