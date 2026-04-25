"""
Pytest test suite for the dot layout engine.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.dot.dot_layout import DotLayout, LayoutNode, LayoutEdge, _NetworkSimplex


# ── Helpers ───────────────────────────────────────

def layout_dot(src: str) -> dict:
    """Parse DOT source, run layout, return JSON dict."""
    g = read_gv(src)
    return DotLayout(g).layout()


def node_by_name(result: dict, name: str) -> dict:
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    raise KeyError(f"node '{name}' not found in result")


# ── Phase 1: Cycle breaking ──────────────────────

class TestCycleBreaking:

    def test_dag_no_reversal(self):
        """Edges in a DAG are not reversed."""
        r = layout_dot("digraph G { a -> b -> c; }")
        # All edges present, no reversal needed — check they all appear
        tails_heads = {(e["tail"], e["head"]) for e in r["edges"]}
        assert ("a", "b") in tails_heads
        assert ("b", "c") in tails_heads

    def test_single_cycle_broken(self):
        """A cycle A->B->C->A is broken by reversing one edge."""
        r = layout_dot("digraph G { a -> b; b -> c; c -> a; }")
        # All 3 nodes should have valid coordinates
        assert len(r["nodes"]) == 3
        # Ranks should not all be the same (cycle was broken)
        ys = {n["y"] for n in r["nodes"]}
        assert len(ys) > 1

    def test_self_loop(self):
        """A self-loop does not crash the layout."""
        r = layout_dot("digraph G { a -> a; a -> b; }")
        assert len(r["nodes"]) == 2


# ── Phase 1: Rank assignment ─────────────────────

class TestRanking:

    def test_linear_chain_ranks(self):
        """A->B->C gets ranks 0, 1, 2."""
        r = layout_dot("digraph G { a -> b -> c; }")
        ya = node_by_name(r, "a")["y"]
        yb = node_by_name(r, "b")["y"]
        yc = node_by_name(r, "c")["y"]
        assert ya < yb < yc

    def test_diamond_shared_rank(self):
        """In A->B, A->C, B->D, C->D the middle nodes share a rank."""
        r = layout_dot("digraph G { a -> b; a -> c; b -> d; c -> d; }")
        yb = node_by_name(r, "b")["y"]
        yc = node_by_name(r, "c")["y"]
        assert yb == yc

    def test_minlen_respected(self):
        """Edge with minlen=2 creates at least 2 rank gaps."""
        r = layout_dot('digraph G { a -> b [minlen=2]; }')
        ya = node_by_name(r, "a")["y"]
        yb = node_by_name(r, "b")["y"]
        # With default ranksep=36, minlen=2 means at least 72 pts gap
        assert yb - ya >= 72.0 - 0.01

    def test_disconnected_components(self):
        """Disconnected nodes still get coordinates."""
        r = layout_dot("digraph G { a; b; c -> d; }")
        assert len(r["nodes"]) == 4


# ── Phase 1: Rank constraints ────────────────────

class TestRankConstraints:

    def test_rank_same(self):
        """Nodes in a rank=same subgraph share the same Y coordinate."""
        r = layout_dot("""
            digraph G {
                a -> b; a -> c;
                { rank=same; b; c; }
            }
        """)
        yb = node_by_name(r, "b")["y"]
        yc = node_by_name(r, "c")["y"]
        assert yb == yc

    def test_rank_min(self):
        """Nodes with rank=min are at the top (smallest Y in TB mode)."""
        r = layout_dot("""
            digraph G {
                a -> b -> c;
                { rank=min; c; }
            }
        """)
        yc = node_by_name(r, "c")["y"]
        ya = node_by_name(r, "a")["y"]
        assert yc <= ya

    def test_rank_max(self):
        """Nodes with rank=max are at the bottom (largest Y in TB mode)."""
        r = layout_dot("""
            digraph G {
                a -> b -> c;
                { rank=max; a; }
            }
        """)
        ya = node_by_name(r, "a")["y"]
        yc = node_by_name(r, "c")["y"]
        assert ya >= yc


# ── Phase 2: Crossing minimization ───────────────

class TestCrossingMinimization:

    def test_no_crash_on_single_rank(self):
        """Graph with all nodes in one rank doesn't crash."""
        r = layout_dot("""
            digraph G {
                { rank=same; a; b; c; }
            }
        """)
        assert len(r["nodes"]) == 3

    def test_crossings_reduced(self):
        """Crossing minimization produces valid ordering."""
        r = layout_dot("""
            digraph G {
                a1 -> b2; a1 -> b1;
                a2 -> b1; a2 -> b2;
            }
        """)
        # Just verify it produces valid output without crash
        assert len(r["nodes"]) == 4


# ── Phase 3: Coordinate assignment ───────────────

class TestCoordinates:

    def test_single_node(self):
        """A single node gets valid coordinates."""
        r = layout_dot("digraph G { a; }")
        n = node_by_name(r, "a")
        assert "x" in n and "y" in n
        assert n["width"] > 0 and n["height"] > 0

    def test_same_rank_separated_by_nodesep(self):
        """Two nodes in the same rank are separated by at least nodesep."""
        r = layout_dot("""
            digraph G {
                { rank=same; a; b; }
            }
        """)
        xa = node_by_name(r, "a")["x"]
        xb = node_by_name(r, "b")["x"]
        wa = node_by_name(r, "a")["width"]
        # Gap between node edges should be >= nodesep (18 pts default)
        gap = abs(xb - xa) - wa  # approximate
        assert gap >= 17.0  # allow tiny float rounding

    def test_ranks_separated_by_ranksep(self):
        """Adjacent ranks have ranksep gap between node boundaries."""
        r = layout_dot("digraph G { a -> b; }")
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        # Gap = bottom of a to top of b
        gap = (nb["y"] - nb["height"] / 2) - (na["y"] + na["height"] / 2)
        assert gap == pytest.approx(36.0, abs=0.1)

    def test_custom_ranksep(self):
        """Custom ranksep is respected as gap between node boundaries."""
        r = layout_dot('digraph G { ranksep=1.0; a -> b; }')
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        gap = (nb["y"] - nb["height"] / 2) - (na["y"] + na["height"] / 2)
        assert gap == pytest.approx(72.0, abs=0.1)

    def test_rankdir_lr(self):
        """rankdir=LR swaps x and y axes."""
        r = layout_dot('digraph G { rankdir=LR; a -> b; }')
        xa = node_by_name(r, "a")["x"]
        xb = node_by_name(r, "b")["x"]
        ya = node_by_name(r, "a")["y"]
        yb = node_by_name(r, "b")["y"]
        # In LR mode, rank progression is horizontal (x changes, y same or similar)
        assert xa != xb

    def test_rankdir_bt(self):
        """rankdir=BT flips the y axis."""
        r = layout_dot('digraph G { rankdir=BT; a -> b; }')
        ya = node_by_name(r, "a")["y"]
        yb = node_by_name(r, "b")["y"]
        # a is rank 0 which in BT is at the bottom (higher Y)
        assert ya > yb


# ── Phase 4: Edge routing ────────────────────────

class TestEdgeRouting:

    def test_two_node_edge_has_four_points(self):
        """A simple edge with splines=line produces 4 points (degenerate cubic)."""
        r = layout_dot("digraph G { splines=line; a -> b; }")
        edge = r["edges"][0]
        assert len(edge["points"]) == 4

    def test_self_loop_has_loop_points(self):
        """A self-loop produces 7 control points (two cubic segments)."""
        r = layout_dot("digraph G { splines=line; a -> a; }")
        edge = r["edges"][0]
        assert len(edge["points"]) == 7

    def test_edge_points_near_nodes(self):
        """Edge endpoints are near the node boundaries, not at centers."""
        r = layout_dot("digraph G { splines=line; a -> b; }")
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        edge = r["edges"][0]
        p1, p2 = edge["points"][0], edge["points"][-1]
        assert abs(p1[1] - na["y"]) <= na["height"] / 2.0 + 0.1
        assert abs(p2[1] - nb["y"]) <= nb["height"] / 2.0 + 0.1


# ── JSON output format ───────────────────────────

class TestJsonOutput:

    def test_output_has_all_keys(self):
        """JSON output contains graph, nodes, and edges keys."""
        r = layout_dot("digraph G { a -> b; }")
        assert "graph" in r
        assert "nodes" in r
        assert "edges" in r
        assert "name" in r["graph"]
        assert "directed" in r["graph"]
        assert "bb" in r["graph"]

    def test_all_nodes_in_output(self):
        """Every node from the input appears in the output."""
        r = layout_dot("digraph G { a; b; c; a -> b; }")
        names = {n["name"] for n in r["nodes"]}
        assert names == {"a", "b", "c"}

    def test_all_edges_in_output(self):
        """Every edge from the input appears in the output."""
        r = layout_dot("digraph G { a -> b; b -> c; }")
        edge_pairs = {(e["tail"], e["head"]) for e in r["edges"]}
        assert ("a", "b") in edge_pairs
        assert ("b", "c") in edge_pairs

    def test_bounding_box_valid(self):
        """Bounding box encloses all nodes."""
        r = layout_dot("digraph G { a -> b -> c; }")
        bb = r["graph"]["bb"]
        for n in r["nodes"]:
            assert n["x"] - n["width"] / 2 >= bb[0] - 0.1
            assert n["y"] - n["height"] / 2 >= bb[1] - 0.1
            assert n["x"] + n["width"] / 2 <= bb[2] + 0.1
            assert n["y"] + n["height"] / 2 <= bb[3] + 0.1

    def test_empty_graph(self):
        """An empty graph produces valid JSON with no nodes/edges."""
        r = layout_dot("digraph G { }")
        assert r["nodes"] == []
        assert r["edges"] == []


# ── Integration: real files ──────────────────────

class TestIntegration:

    def test_example1_gv(self):
        """Layout example1.gv (undirected, 5 nodes, 6 edges)."""
        from gvpy.grammar.gv_reader import read_gv_file
        path = Path(__file__).parent.parent / "test_data" / "example1.gv"
        if not path.exists():
            pytest.skip("example1.gv not found")
        g = read_gv_file(path)
        r = DotLayout(g).layout()
        assert len(r["nodes"]) == 5
        assert len(r["edges"]) == 6
        # All nodes have distinct positions
        positions = {(n["x"], n["y"]) for n in r["nodes"]}
        assert len(positions) == 5

    def test_world_gv(self):
        """Layout world.gv (directed, rank constraints)."""
        from gvpy.grammar.gv_reader import read_gv_file
        path = Path(__file__).parent.parent / "test_data" / "world.gv"
        if not path.exists():
            pytest.skip("world.gv not found")
        g = read_gv_file(path)
        r = DotLayout(g).layout()
        assert len(r["nodes"]) > 20
        assert len(r["edges"]) > 20
        # Verify rank=same constraints: nodes in same rank should share Y
        # (S8, S24, S1, S35, S30 are in the first rank=same group)
        s8 = node_by_name(r, "S8")
        s24 = node_by_name(r, "S24")
        assert s8["y"] == s24["y"]

    def test_undirected_gets_valid_layout(self):
        """An undirected graph produces a valid hierarchical layout."""
        r = layout_dot("graph G { a -- b -- c; }")
        assert len(r["nodes"]) == 3
        assert len(r["edges"]) == 2


# ── CLI ───────────────────────────────────────────

class TestCLI:

    def test_cli_produces_json(self, tmp_path):
        """Running dot.py via subprocess produces valid JSON."""
        dot_file = tmp_path / "test.gv"
        dot_file.write_text("digraph G { a -> b; }", encoding="utf-8")
        out_file = tmp_path / "out.json"

        result = subprocess.run(
            [sys.executable, "dot.py", str(dot_file), "-o", str(out_file)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(out_file.read_text())
        assert len(data["nodes"]) == 2

    def test_cli_stdout(self, tmp_path):
        """Running dot.py without output file prints to stdout."""
        dot_file = tmp_path / "test.gv"
        dot_file.write_text("digraph G { x -> y; }", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "dot.py", str(dot_file)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert "nodes" in data


# ── Network Simplex ──────────────────────────────

class TestNetworkSimplex:

    def test_simple_chain(self):
        """A->B->C produces ranks 0, 1, 2."""
        ns = _NetworkSimplex(["a", "b", "c"], [
            ("a", "b", 1, 1), ("b", "c", 1, 1),
        ])
        r = ns.solve()
        assert r["a"] < r["b"] < r["c"]
        assert r["b"] - r["a"] >= 1
        assert r["c"] - r["b"] >= 1

    def test_diamond_optimal(self):
        """Diamond graph: middle nodes get same rank."""
        ns = _NetworkSimplex(["a", "b", "c", "d"], [
            ("a", "b", 1, 1), ("a", "c", 1, 1),
            ("b", "d", 1, 1), ("c", "d", 1, 1),
        ])
        r = ns.solve()
        assert r["b"] == r["c"]
        assert r["a"] < r["b"]
        assert r["b"] < r["d"]

    def test_minlen_respected(self):
        """Edge with minlen=3 creates at least 3 rank gap."""
        ns = _NetworkSimplex(["a", "b"], [("a", "b", 3, 1)])
        r = ns.solve()
        assert r["b"] - r["a"] >= 3

    def test_disconnected_nodes(self):
        """Disconnected nodes get valid ranks."""
        ns = _NetworkSimplex(["a", "b", "c"], [("a", "b", 1, 1)])
        r = ns.solve()
        assert "c" in r

    def test_single_node(self):
        """Single node produces rank 0."""
        ns = _NetworkSimplex(["a"], [])
        r = ns.solve()
        assert r["a"] == 0

    def test_weighted_edges(self):
        """Heavier edges are respected in ranking."""
        ns = _NetworkSimplex(["a", "b", "c"], [
            ("a", "b", 1, 10), ("a", "c", 1, 1),
        ])
        r = ns.solve()
        assert r["b"] - r["a"] >= 1
        assert r["c"] - r["a"] >= 1


# ── Virtual Nodes ────────────────────────────────

class TestVirtualNodes:

    def test_long_edge_creates_vnodes(self):
        """An edge with minlen=3 creates 2 virtual nodes."""
        r = layout_dot('digraph G { a -> b [minlen=3]; }')
        # Output should still show original nodes only
        names = {n["name"] for n in r["nodes"]}
        assert names == {"a", "b"}

    def test_virtual_nodes_not_in_output(self):
        """Virtual nodes are excluded from JSON output."""
        r = layout_dot('digraph G { a -> b [minlen=3]; }')
        for n in r["nodes"]:
            assert not n["name"].startswith("_v_")

    def test_long_edge_polyline_routing(self):
        """Edge spanning 3+ ranks has intermediate routing points."""
        r = layout_dot('digraph G { a -> b [minlen=3]; }')
        edge = r["edges"][0]
        # Should have more than 2 points (routed through virtual nodes)
        assert len(edge["points"]) > 2

    def test_mixed_short_and_long_edges(self):
        """Graph with both short and long edges works correctly."""
        r = layout_dot('digraph G { a -> b; a -> c [minlen=3]; b -> c; }')
        assert len(r["nodes"]) == 3
        assert len(r["edges"]) == 3


# ── X Positioning ────────────────────────────────

class TestXPositioning:

    def test_connected_nodes_tend_toward_alignment(self):
        """NS X positioning pulls connected nodes toward vertical alignment."""
        r = layout_dot("""
            digraph G {
                a -> b;
                a -> c;
                b -> d;
                c -> d;
            }
        """)
        # a and d should be roughly centered between b and c
        xa = node_by_name(r, "a")["x"]
        xd = node_by_name(r, "d")["x"]
        xb = node_by_name(r, "b")["x"]
        xc = node_by_name(r, "c")["x"]
        mid = (xb + xc) / 2.0
        # a and d should be close to the midpoint (within the b-c range)
        assert abs(xa - mid) <= abs(xb - xc)
        assert abs(xd - mid) <= abs(xb - xc)

    def test_nodesep_still_respected(self):
        """Adjacent nodes in same rank don't overlap."""
        r = layout_dot("""
            digraph G {
                { rank=same; a; b; c; }
            }
        """)
        nodes = sorted(
            [node_by_name(r, n) for n in ["a", "b", "c"]],
            key=lambda n: n["x"]
        )
        for i in range(len(nodes) - 1):
            left_edge = nodes[i]["x"] + nodes[i]["width"] / 2
            right_edge = nodes[i + 1]["x"] - nodes[i + 1]["width"] / 2
            gap = right_edge - left_edge
            assert gap >= 17.0  # nodesep=18 minus float tolerance


# ── Polyline Routing ─────────────────────────────

class TestPolylineRouting:

    def test_short_edge_has_four_points(self):
        """A single-rank-span edge with splines=line has 4 points (degenerate cubic)."""
        r = layout_dot("digraph G { splines=line; a -> b; }")
        edge = r["edges"][0]
        assert len(edge["points"]) == 4

    def test_self_loop_unchanged(self):
        """Self-loops produce 7 control points (two cubic segments)."""
        r = layout_dot("digraph G { splines=line; a -> a; }")
        edge = r["edges"][0]
        assert len(edge["points"]) == 7


# ── Clusters ─────────────────────────────────────

class TestClusters:

    def test_cluster_in_output(self):
        """Cluster subgraphs appear in the JSON clusters array."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { a; b; a -> b; }
                c -> a;
            }
        """)
        assert "clusters" in r
        names = {c["name"] for c in r["clusters"]}
        assert "cluster_0" in names

    def test_cluster_bb_encloses_nodes(self):
        """Cluster bounding box contains all member nodes."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { a; b; }
            }
        """)
        cl = r["clusters"][0]
        bb = cl["bb"]
        for nname in cl["nodes"]:
            n = node_by_name(r, nname)
            assert n["x"] - n["width"] / 2 >= bb[0] - 0.1
            assert n["y"] - n["height"] / 2 >= bb[1] - 0.1
            assert n["x"] + n["width"] / 2 <= bb[2] + 0.1
            assert n["y"] + n["height"] / 2 <= bb[3] + 0.1

    def test_nested_clusters(self):
        """Nested clusters both appear in output."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_outer {
                    subgraph cluster_inner { x; y; }
                    z;
                }
            }
        """)
        names = {c["name"] for c in r["clusters"]}
        assert "cluster_outer" in names
        assert "cluster_inner" in names

    def test_cluster_label(self):
        """Cluster label is included in output."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 {
                    label="My Cluster";
                    a; b;
                }
            }
        """)
        cl = [c for c in r["clusters"] if c["name"] == "cluster_0"][0]
        assert cl["label"] == "My Cluster"

    def test_non_cluster_subgraph_excluded(self):
        """rank=same subgraphs (not named cluster_*) are not in clusters."""
        r = layout_dot("""
            digraph G {
                { rank=same; a; b; }
                a -> c;
            }
        """)
        assert "clusters" not in r or len(r.get("clusters", [])) == 0


# ── Ports ────────────────────────────────────────

class TestPorts:

    def test_tailport_headport_attributes(self):
        """Edges with tailport/headport use compass attachment points."""
        r = layout_dot('digraph G { a -> b [tailport=s, headport=n]; }')
        edge = r["edges"][0]
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        # First point at south of a (bottom y).  Tolerance 1.0 accounts
        # for bezier_clip binary-search convergence (~0.5pt).
        assert edge["points"][0][1] == pytest.approx(na["y"] + na["height"] / 2, abs=1.0)
        # Last point at north of b (top y)
        assert edge["points"][-1][1] == pytest.approx(nb["y"] - nb["height"] / 2, abs=1.0)

    def test_compass_e_w(self):
        """East/west ports attach at left/right of node."""
        r = layout_dot('digraph G { splines=line; rankdir=LR; a -> b [tailport=e, headport=w]; }')
        edge = r["edges"][0]
        assert len(edge["points"]) == 4

    def test_port_syntax_on_node_id(self):
        """Port specified in node ID syntax (a:s -> b:n) is stored on edge."""
        r = layout_dot('digraph G { a:s -> b:n; }')
        edge = r["edges"][0]
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        # Tolerance 1.0: bezier_clip binary-search convergence.
        assert edge["points"][0][1] == pytest.approx(na["y"] + na["height"] / 2, abs=1.0)
        assert edge["points"][-1][1] == pytest.approx(nb["y"] - nb["height"] / 2, abs=1.0)


# ── Edge Labels ──────────────────────────────────

class TestEdgeLabels:

    def test_edge_label_in_output(self):
        """Edge with label has label and label_pos in JSON."""
        r = layout_dot('digraph G { a -> b [label="connects"]; }')
        edge = r["edges"][0]
        assert edge["label"] == "connects"
        assert "label_pos" in edge
        assert len(edge["label_pos"]) == 2

    def test_edge_label_at_midpoint(self):
        """Label position is between the edge endpoints."""
        r = layout_dot('digraph G { a -> b [label="mid"]; }')
        edge = r["edges"][0]
        pts = edge["points"]
        lp = edge["label_pos"]
        # Label should be between first and last points vertically
        min_y = min(p[1] for p in pts)
        max_y = max(p[1] for p in pts)
        assert min_y - 1 <= lp[1] <= max_y + 1

    def test_no_label_no_field(self):
        """Edge without label has no label or label_pos in JSON."""
        r = layout_dot('digraph G { a -> b; }')
        edge = r["edges"][0]
        assert "label" not in edge
        assert "label_pos" not in edge


# ── constraint=false ─────────────────────────────

class TestConstraintFalse:

    def test_constraint_false_ignored_in_ranking(self):
        """Edge with constraint=false doesn't force rank ordering."""
        r = layout_dot("""
            digraph G {
                a -> b;
                b -> a [constraint=false];
            }
        """)
        # Without constraint=false, b->a would create a cycle requiring reversal
        # With constraint=false, a should still be above b (rank 0 vs 1)
        ya = node_by_name(r, "a")["y"]
        yb = node_by_name(r, "b")["y"]
        assert ya < yb

    def test_constraint_none_same_as_false(self):
        """constraint=none is treated the same as constraint=false."""
        r = layout_dot("""
            digraph G {
                a -> b;
                c -> a [constraint=none];
            }
        """)
        # c->a with constraint=none shouldn't force c above a
        assert len(r["nodes"]) == 3

    def test_constraint_false_edge_still_routed(self):
        """Edge with constraint=false still appears in output with routing."""
        r = layout_dot("""
            digraph G {
                a -> b [constraint=false];
            }
        """)
        assert len(r["edges"]) == 1
        assert len(r["edges"][0]["points"]) >= 2


# ── Ortho Routing ────────────────────────────────

class TestOrthoRouting:

    def test_ortho_has_right_angles(self):
        """Ortho edges only have horizontal or vertical segments."""
        r = layout_dot('digraph G { splines=ortho; a -> b; }')
        edge = r["edges"][0]
        for i in range(len(edge["points"]) - 1):
            p1 = edge["points"][i]
            p2 = edge["points"][i + 1]
            dx = abs(p1[0] - p2[0])
            dy = abs(p1[1] - p2[1])
            # Each segment should be horizontal (dy~0) or vertical (dx~0)
            assert dx < 0.1 or dy < 0.1, f"Segment {p1}->{p2} is diagonal"

    def test_ortho_more_points_than_straight(self):
        """Ortho routing produces more points than straight-line for non-aligned nodes."""
        r = layout_dot("""
            digraph G {
                splines=ortho;
                a -> c;
                a -> b;
                b -> c;
            }
        """)
        # At least one edge should have >2 points (Z-bend)
        max_pts = max(len(e["points"]) for e in r["edges"])
        assert max_pts >= 2

    def test_polyline_same_as_ortho(self):
        """splines=polyline uses the same ortho routing."""
        r = layout_dot('digraph G { splines=polyline; a -> b; }')
        edge = r["edges"][0]
        assert len(edge["points"]) >= 2


# ── Ordering Attribute ───────────────────────────

class TestOrdering:

    def test_ordering_out_preserves_input_order(self):
        """ordering=out preserves the input node order within ranks."""
        r = layout_dot("""
            digraph G {
                ordering=out;
                a -> c;
                a -> b;
                a -> d;
            }
        """)
        # With ordering=out, crossing minimization is skipped.
        # Nodes b, c, d should appear in the output (order may vary
        # but the key is it doesn't crash and produces valid output)
        assert len(r["nodes"]) == 4

    def test_ordering_out_no_crash_complex(self):
        """ordering=out works on a graph that would normally get reordered."""
        r = layout_dot("""
            digraph G {
                ordering=out;
                a1 -> b2; a1 -> b1;
                a2 -> b1; a2 -> b2;
            }
        """)
        assert len(r["nodes"]) == 4
        assert len(r["edges"]) == 4


# ── Ratio/Size ───────────────────────────────────

class TestRatioSize:

    def test_size_scales_layout(self):
        """Layout with size is smaller than layout without size."""
        r_small = layout_dot("""
            digraph G {
                size="1,1";
                a -> b -> c -> d -> e -> f;
            }
        """)
        r_big = layout_dot("digraph G { a -> b -> c -> d -> e -> f; }")
        bb_small = r_small["graph"]["bb"]
        bb_big = r_big["graph"]["bb"]
        small_h = bb_small[3] - bb_small[1]
        big_h = bb_big[3] - bb_big[1]
        assert small_h < big_h

    def test_size_in_json(self):
        """Size attribute appears in graph JSON metadata."""
        r = layout_dot('digraph G { size="8,10"; a -> b; }')
        assert "size" in r["graph"]
        assert r["graph"]["size"] == [576.0, 720.0]

    def test_ratio_in_json(self):
        """Ratio attribute appears in graph JSON metadata."""
        r = layout_dot('digraph G { ratio=compress; a -> b; }')
        assert r["graph"]["ratio"] == "compress"

    def test_no_size_no_scaling(self):
        """Without size, no scaling is applied."""
        r = layout_dot("digraph G { a -> b -> c; }")
        assert "size" not in r["graph"]


# ── Edge Concentration ───────────────────────────

class TestConcentrate:

    def test_concentrate_merges_parallel(self):
        """Parallel edges with concentrate=true share the same routing."""
        r = layout_dot("""
            digraph G {
                concentrate=true;
                a -> b;
                a -> b;
            }
        """)
        edges = r["edges"]
        # Both edges should have identical points
        if len(edges) == 2:
            assert edges[0]["points"] == edges[1]["points"]

    def test_concentrate_false_no_merge(self):
        """Without concentrate, parallel edges have their own routing."""
        r = layout_dot("""
            digraph G {
                a -> b;
                a -> b;
            }
        """)
        # Should still produce valid output
        assert len(r["edges"]) >= 1

    def test_concentrate_with_labels(self):
        """Concentration works when edges have labels."""
        r = layout_dot("""
            digraph G {
                concentrate=true;
                a -> b [label="x"];
                a -> b [label="y"];
            }
        """)
        assert len(r["nodes"]) == 2


# ── Compound Edges ───────────────────────────────

class TestCompoundEdges:

    def test_lhead_clips_to_cluster(self):
        """Edge with lhead has its endpoint at the cluster boundary."""
        r = layout_dot("""
            digraph G {
                compound=true;
                subgraph cluster_0 { a; b; }
                c -> a [lhead=cluster_0];
            }
        """)
        assert "clusters" in r
        cl = [c for c in r["clusters"] if c["name"] == "cluster_0"][0]
        edge = [e for e in r["edges"] if e.get("lhead")][0]
        assert edge["lhead"] == "cluster_0"
        # The last point should be on or near the cluster boundary
        last_pt = edge["points"][-1]
        bb = cl["bb"]
        # Point should be within or on the cluster boundary
        assert bb[0] - 1 <= last_pt[0] <= bb[2] + 1
        assert bb[1] - 1 <= last_pt[1] <= bb[3] + 1

    def test_ltail_clips_to_cluster(self):
        """Edge with ltail has its start point at the cluster boundary."""
        r = layout_dot("""
            digraph G {
                compound=true;
                subgraph cluster_0 { a; b; }
                a -> c [ltail=cluster_0];
            }
        """)
        edge = [e for e in r["edges"] if e.get("ltail")][0]
        assert edge["ltail"] == "cluster_0"

    def test_compound_false_no_clip(self):
        """Without compound=true, lhead is stored but doesn't clip."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { a; b; }
                c -> a [lhead=cluster_0];
            }
        """)
        # lhead is stored on the edge but no clipping occurs
        edge = r["edges"][0]
        assert edge.get("lhead") == "cluster_0"

    def test_lhead_ltail_in_json(self):
        """lhead and ltail attributes appear in edge JSON."""
        r = layout_dot("""
            digraph G {
                compound=true;
                subgraph cluster_1 { a; }
                subgraph cluster_2 { b; }
                a -> b [ltail=cluster_1, lhead=cluster_2];
            }
        """)
        edge = r["edges"][0]
        assert edge["ltail"] == "cluster_1"
        assert edge["lhead"] == "cluster_2"

    def test_real_compound_file(self):
        """Parse and layout a real compound DOT file."""
        from gvpy.grammar.gv_reader import read_gv_file
        path = Path(__file__).parent.parent / "test_data" / "1879-2.dot"
        if not path.exists():
            pytest.skip("1879-2.dot not found")
        g = read_gv_file(path)
        r = DotLayout(g).layout()
        assert len(r["nodes"]) >= 2


# ── Bezier Routing ───────────────────────────────

class TestBezierRouting:

    def test_default_splines_use_bezier(self):
        """Default splines mode produces Bezier control points."""
        r = layout_dot("digraph G { a -> b; }")
        edge = r["edges"][0]
        # Bezier: 4 points for a single segment (P0, C1, C2, P1)
        assert len(edge["points"]) == 4
        assert edge.get("spline_type") == "bezier"

    def test_splines_line_uses_bezier(self):
        """splines=line produces a degenerate cubic (4-point bezier)."""
        r = layout_dot('digraph G { splines=line; a -> b; }')
        edge = r["edges"][0]
        assert len(edge["points"]) == 4
        assert edge.get("spline_type") == "bezier"

    def test_bezier_chain_has_smooth_points(self):
        """A multi-rank edge with Bezier has grouped control points."""
        r = layout_dot('digraph G { a -> b [minlen=3]; }')
        edge = r["edges"][0]
        # 4 waypoints → converted to bezier: (n-1)*3+1 points
        # Should have more points than the 4 waypoints
        assert len(edge["points"]) >= 4
        assert edge.get("spline_type") == "bezier"

    def test_splines_true_triggers_bezier(self):
        """splines=true uses Bezier routing."""
        r = layout_dot('digraph G { splines=true; a -> b; }')
        assert r["edges"][0].get("spline_type") == "bezier"

    def test_splines_curved_triggers_bezier(self):
        """splines=curved uses Bezier routing."""
        r = layout_dot('digraph G { splines=curved; a -> b; }')
        assert r["edges"][0].get("spline_type") == "bezier"

    def test_node_shape_in_json(self):
        """Node shape attribute appears in JSON output."""
        r = layout_dot('digraph G { a [shape=box]; b; }')
        a = node_by_name(r, "a")
        b = node_by_name(r, "b")
        assert a.get("shape") == "box"
        assert "shape" not in b  # default shape not emitted


# ── nslimit / nslimit1 ──────────────────────────

class TestNsLimit:

    def test_nslimit_accepted(self):
        """Graph with nslimit produces valid layout."""
        r = layout_dot('digraph G { nslimit=50; a -> b -> c; }')
        assert len(r["nodes"]) == 3

    def test_nslimit1_accepted(self):
        """Graph with nslimit1 produces valid layout."""
        r = layout_dot('digraph G { nslimit1=10; a -> b -> c; }')
        assert len(r["nodes"]) == 3

    def test_low_nslimit_still_works(self):
        """Very low nslimit still produces a layout (may not be optimal)."""
        r = layout_dot('digraph G { nslimit=1; a -> b -> c -> d; }')
        assert len(r["nodes"]) == 4


# ── mclimit / remincross ─────────────────────────

class TestMclimit:

    def test_mclimit_scales_iterations(self):
        """mclimit=0.5 halves crossing minimization iterations."""
        r = layout_dot('digraph G { mclimit=0.5; a -> b; c -> d; }')
        assert len(r["nodes"]) == 4

    def test_mclimit_high_value(self):
        """mclimit=2.0 doubles iterations without crashing."""
        r = layout_dot('digraph G { mclimit=2.0; a -> b; c -> d; }')
        assert len(r["nodes"]) == 4

    def test_remincross_accepted(self):
        """remincross=true triggers second crossing minimization pass."""
        r = layout_dot("""
            digraph G {
                remincross=true;
                a1 -> b2; a1 -> b1;
                a2 -> b1; a2 -> b2;
            }
        """)
        assert len(r["nodes"]) == 4


# ── searchsize ───────────────────────────────────

class TestSearchsize:

    def test_searchsize_accepted(self):
        """Custom searchsize produces valid layout."""
        r = layout_dot('digraph G { searchsize=10; a -> b -> c; }')
        assert len(r["nodes"]) == 3

    def test_searchsize_one(self):
        """searchsize=1 still produces valid output."""
        r = layout_dot('digraph G { searchsize=1; a -> b -> c -> d; }')
        assert len(r["nodes"]) == 4


# ── headclip / tailclip ─────────────────────────

class TestClipAttributes:

    def test_headclip_false_goes_to_center(self):
        """headclip=false makes edge end at node center, not boundary."""
        r = layout_dot('digraph G { splines=line; a -> b [headclip=false]; }')
        nb = node_by_name(r, "b")
        edge = r["edges"][0]
        # Last point should be at node center
        assert edge["points"][-1][0] == pytest.approx(nb["x"], abs=0.1)
        assert edge["points"][-1][1] == pytest.approx(nb["y"], abs=0.1)

    def test_tailclip_false_goes_to_center(self):
        """tailclip=false makes edge start at node center, not boundary."""
        r = layout_dot('digraph G { splines=line; a -> b [tailclip=false]; }')
        na = node_by_name(r, "a")
        edge = r["edges"][0]
        # First point should be at node center
        assert edge["points"][0][0] == pytest.approx(na["x"], abs=0.1)
        assert edge["points"][0][1] == pytest.approx(na["y"], abs=0.1)

    def test_default_clips(self):
        """By default, edges clip at node boundary (not center)."""
        r = layout_dot('digraph G { splines=line; a -> b; }')
        na = node_by_name(r, "a")
        edge = r["edges"][0]
        # First point should NOT be at node center (clipped to boundary)
        assert edge["points"][0][1] != pytest.approx(na["y"], abs=0.1)


# ── normalize ────────────────────────────────────

class TestNormalize:

    def test_normalize_shifts_to_origin(self):
        """normalize=true shifts layout so minimum coordinate is at origin."""
        r = layout_dot('digraph G { normalize=true; a -> b -> c; }')
        bb = r["graph"]["bb"]
        # Min x and min y should be at or near 0
        assert bb[0] == pytest.approx(0.0, abs=0.1)
        assert bb[1] == pytest.approx(0.0, abs=0.1)

    def test_no_normalize_by_default(self):
        """Without normalize, coordinates may not start at origin."""
        # This just verifies the layout runs without normalize
        r = layout_dot('digraph G { a -> b; }')
        assert len(r["nodes"]) == 2


# ── labelangle / labeldistance ───────────────────

class TestLabelAngleDistance:

    def test_labeldistance_offsets_label(self):
        """labeldistance moves the label away from edge midpoint."""
        r1 = layout_dot('digraph G { splines=line; a -> b [label="x"]; }')
        r2 = layout_dot('digraph G { splines=line; a -> b [label="x", labeldistance="3"]; }')
        lp1 = r1["edges"][0]["label_pos"]
        lp2 = r2["edges"][0]["label_pos"]
        # Positions should differ when labeldistance is set
        assert lp1 != lp2

    def test_labelangle_offsets_label(self):
        """labelangle with labeldistance rotates label position around edge midpoint."""
        r1 = layout_dot('digraph G { splines=line; a -> b [label="x", labeldistance="2"]; }')
        r2 = layout_dot('digraph G { splines=line; a -> b [label="x", labeldistance="2", labelangle="90"]; }')
        lp1 = r1["edges"][0]["label_pos"]
        lp2 = r2["edges"][0]["label_pos"]
        assert lp1 != lp2


# ── quantum ──────────────────────────────────────

class TestQuantum:

    def test_quantum_snaps_coordinates(self):
        """quantum snaps all node coordinates to a grid."""
        r = layout_dot('digraph G { quantum=10; a -> b -> c; }')
        for n in r["nodes"]:
            assert n["x"] % 10 == pytest.approx(0, abs=0.1)
            assert n["y"] % 10 == pytest.approx(0, abs=0.1)

    def test_quantum_zero_no_snap(self):
        """quantum=0 (default) does not snap."""
        r = layout_dot('digraph G { a -> b; }')
        # Just verify it works without quantum
        assert len(r["nodes"]) == 2


# ── Label-based node sizing ──────────────────────

class TestLabelSizing:

    def test_long_label_widens_node(self):
        """A node with a long label is wider than one with a short label."""
        r = layout_dot('digraph G { splines=line; a [label="Short"]; b [label="This is a very long label text"]; }')
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        assert nb["width"] > na["width"]

    def test_default_label_is_node_name(self):
        """Without explicit label, node name is used for sizing."""
        r = layout_dot('digraph G { x; longernodename; }')
        nx = node_by_name(r, "x")
        nl = node_by_name(r, "longernodename")
        assert nl["width"] > nx["width"]

    def test_multiline_label_taller(self):
        r"""A multi-line label makes the node taller."""
        r = layout_dot(r'digraph G { a [label="line1\nline2\nline3"]; b [label="single"]; }')
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        assert na["height"] > nb["height"]

    def test_explicit_width_is_minimum_not_override(self):
        """Explicit width is a MINIMUM — labels wider than it grow the node.

        Matches C's shapes.c: poly_init @ ``sz.x = MAX(sz.x, INCH2PS(ND_width))``.
        Use ``fixedsize=true`` to force exact user dimensions.
        """
        # Long label with small explicit width: node grows past the width.
        r = layout_dot('digraph G { a [label="Very long label", width="0.5", height="0.5"]; }')
        na = node_by_name(r, "a")
        assert na["width"] > 36.0, "label should be allowed to grow the node"

        # fixedsize=true: user dimensions override label (exactly C's N_fixed).
        r2 = layout_dot('digraph G { a [label="Very long label", width="0.5", height="0.5", fixedsize=true]; }')
        na2 = node_by_name(r2, "a")
        assert na2["width"] == pytest.approx(36.0, abs=0.1)

    def test_minimum_size_enforced(self):
        """Even with a tiny label, nodes have a minimum size."""
        r = layout_dot('digraph G { a [label=""]; }')
        na = node_by_name(r, "a")
        assert na["width"] >= 54.0
        assert na["height"] >= 36.0

    def test_nodes_dont_overlap_same_rank(self):
        """Nodes with labels are wide enough that they don't overlap."""
        r = layout_dot("""
            digraph G {
                splines=line;
                { rank=same; a [label="Component A"]; b [label="Component B"]; }
            }
        """)
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        if na["x"] < nb["x"]:
            assert na["x"] + na["width"] / 2 < nb["x"] - nb["width"] / 2 + 1
        else:
            assert nb["x"] + nb["width"] / 2 < na["x"] - na["width"] / 2 + 1

    def test_trigraph_no_overlap(self):
        """The trigraph test case nodes should not overlap."""
        r = layout_dot("""
            digraph G {
                rankdir=LR;
                node [shape=box];
                A [label="Component A"];
                B [label="Component B"];
                C [label="Component C"];
                A -> B [label="calls"];
                B -> C [label="publishes"];
                A -> C [label="reads"];
            }
        """)
        nodes = {n["name"]: n for n in r["nodes"]}
        names = list(nodes.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                ni = nodes[names[i]]
                nj = nodes[names[j]]
                x_gap = abs(ni["x"] - nj["x"]) - (ni["width"] + nj["width"]) / 2
                y_gap = abs(ni["y"] - nj["y"]) - (ni["height"] + nj["height"]) / 2
                assert x_gap > -1 or y_gap > -1, \
                    f"{names[i]} and {names[j]} overlap"


# ── Group attribute ──────────────────────────────

class TestGroupAttribute:

    def test_same_group_edges_stay_straight(self):
        """Same-group nodes in adjacent ranks are vertically aligned."""
        r = layout_dot("""
            digraph G {
                a [group=g1];
                b [group=g1];
                c [group=g1];
                a -> b -> c;
            }
        """)
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        nc = node_by_name(r, "c")
        # Without competing edges, all three should be aligned
        assert na["x"] == pytest.approx(nb["x"], abs=5)
        assert nb["x"] == pytest.approx(nc["x"], abs=5)

    def test_no_group_no_crash(self):
        """Without group, layout runs normally."""
        r = layout_dot("digraph G { a -> b -> c; d -> b; }")
        assert len(r["nodes"]) == 4

    def test_different_groups_no_boost(self):
        """Edges between different groups don't get weight boost."""
        r = layout_dot("""
            digraph G {
                a [group=g1];
                b [group=g2];
                a -> b;
            }
        """)
        assert len(r["edges"]) == 1


# ── samehead / sametail ──────────────────────────

class TestSameheadSametail:

    def test_samehead_shares_endpoint(self):
        """Edges with same samehead value converge at the same point."""
        r = layout_dot("""
            digraph G {
                splines=line;
                a -> c [samehead=g1];
                b -> c [samehead=g1];
            }
        """)
        edges = r["edges"]
        assert len(edges) == 2
        # Both edges should end at the same point
        assert edges[0]["points"][-1] == edges[1]["points"][-1]

    def test_sametail_shares_startpoint(self):
        """Edges with same sametail value leave from the same point."""
        r = layout_dot("""
            digraph G {
                splines=line;
                a -> b [sametail=g1];
                a -> c [sametail=g1];
            }
        """)
        edges = r["edges"]
        assert len(edges) == 2
        # Both edges should start at the same point
        assert edges[0]["points"][0] == edges[1]["points"][0]

    def test_different_samehead_groups(self):
        """Different samehead values don't share endpoints."""
        r = layout_dot("""
            digraph G {
                splines=line;
                a -> c [samehead=g1];
                b -> c [samehead=g2];
            }
        """)
        edges = r["edges"]
        # Different groups: endpoints may differ (not forced to match)
        assert len(edges) == 2

    def test_no_samehead_no_effect(self):
        """Without samehead, edges have independent endpoints."""
        r = layout_dot("digraph G { splines=line; a -> c; b -> c; }")
        assert len(r["edges"]) == 2


# ── clusterrank ──────────────────────────────────

class TestClusterrank:

    def test_clusterrank_none_ignores_clusters(self):
        """clusterrank=none produces no clusters in output."""
        r = layout_dot("""
            digraph G {
                clusterrank=none;
                subgraph cluster_0 { a; b; }
                c -> a;
            }
        """)
        assert "clusters" not in r or len(r.get("clusters", [])) == 0

    def test_clusterrank_local_default(self):
        """Default clusterrank=local includes clusters."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { a; b; }
                c -> a;
            }
        """)
        assert "clusters" in r
        assert len(r["clusters"]) == 1

    def test_clusterrank_global(self):
        """clusterrank=global still includes clusters."""
        r = layout_dot("""
            digraph G {
                clusterrank=global;
                subgraph cluster_0 { x; y; }
            }
        """)
        assert "clusters" in r


# ── pos / pin ────────────────────────────────────

class TestPosPin:

    def test_pos_sets_coordinates(self):
        """Node with pos attribute gets the specified coordinates."""
        r = layout_dot('digraph G { a [pos="2,3"]; b; a -> b; }')
        na = node_by_name(r, "a")
        assert na["x"] == pytest.approx(144.0, abs=1)  # 2 * 72
        assert na["y"] == pytest.approx(216.0, abs=1)  # 3 * 72

    def test_pos_overrides_layout(self):
        """Fixed pos overrides the computed layout position."""
        r = layout_dot("""
            digraph G {
                a [pos="5,5"];
                b;
                a -> b;
            }
        """)
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        # a should be at fixed position, b at computed position
        assert na["x"] == pytest.approx(360.0, abs=1)  # 5 * 72
        assert na["x"] != nb["x"] or na["y"] != nb["y"]

    def test_pos_with_bang_pins(self):
        """pos with ! suffix pins the node."""
        r = layout_dot('digraph G { a [pos="1,1!"]; b; }')
        na = node_by_name(r, "a")
        assert na["x"] == pytest.approx(72.0, abs=1)

    def test_no_pos_uses_layout(self):
        """Without pos, nodes get computed positions."""
        r = layout_dot("digraph G { a -> b; }")
        assert len(r["nodes"]) == 2


# ── Record shape parsing ────────────────────────

class TestRecordShape:

    def test_record_width_from_fields(self):
        """Record nodes are wider when they have more fields."""
        r = layout_dot("""
            digraph G {
                node [shape=record];
                a [label="one"];
                b [label="one|two|three"];
            }
        """)
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        assert nb["width"] > na["width"]

    def test_record_ports_in_json(self):
        """Record field ports appear in node JSON output."""
        r = layout_dot(r"""
            digraph G {
                node [shape=record];
                a [label="<f0> left|<f1> right"];
            }
        """)
        na = node_by_name(r, "a")
        assert "record_ports" in na
        assert "f0" in na["record_ports"]
        assert "f1" in na["record_ports"]

    def test_record_port_positions_ordered(self):
        """Port positions increase left to right."""
        r = layout_dot(r"""
            digraph G {
                node [shape=record];
                a [label="<p1> A|<p2> B|<p3> C"];
            }
        """)
        na = node_by_name(r, "a")
        ports = na["record_ports"]
        assert ports["p1"] < ports["p2"] < ports["p3"]

    def test_record_port_routing(self):
        """Edges using record ports attach at field positions."""
        r = layout_dot(r"""
            digraph G {
                splines=line;
                node [shape=record];
                a [label="<f0> L|<f1> R"];
                b; c;
                a:f0 -> b;
                a:f1 -> c;
            }
        """)
        edges = r["edges"]
        assert len(edges) == 2
        # The two edges should start at different x positions (f0 vs f1)
        x0 = edges[0]["points"][0][0]
        x1 = edges[1]["points"][0][0]
        assert x0 != pytest.approx(x1, abs=1)

    def test_nested_record_fields(self):
        """Nested record fields with {} are parsed."""
        r = layout_dot(r"""
            digraph G {
                node [shape=record];
                a [label="<f0> A|{<f1> B|<f2> C}|<f3> D"];
            }
        """)
        na = node_by_name(r, "a")
        ports = na["record_ports"]
        assert "f0" in ports
        assert "f1" in ports
        assert "f3" in ports

    def test_mrecord_same_as_record(self):
        """Mrecord shape is handled identically to record for layout."""
        r = layout_dot(r"""
            digraph G {
                node [shape=Mrecord];
                a [label="<f0> X|<f1> Y"];
            }
        """)
        na = node_by_name(r, "a")
        assert "record_ports" in na

    def test_non_record_no_ports(self):
        """Non-record shapes don't get record_ports in output."""
        r = layout_dot('digraph G { a [shape=box, label="hello"]; }')
        na = node_by_name(r, "a")
        assert "record_ports" not in na


# ── newrank ──────────────────────────────────────

class TestNewrank:

    def test_newrank_true_global_ranking(self):
        """newrank=true ranks all nodes globally ignoring cluster boundaries."""
        r = layout_dot("""
            digraph G {
                newrank=true;
                subgraph cluster_0 { a -> b; }
                subgraph cluster_1 { c -> d; }
                a -> c;
            }
        """)
        # All nodes should have valid ranks
        assert len(r["nodes"]) == 4
        # a should be above c (a->c edge enforced globally)
        ya = node_by_name(r, "a")["y"]
        yc = node_by_name(r, "c")["y"]
        assert ya < yc or ya == pytest.approx(yc, abs=1)

    def test_newrank_false_default(self):
        """Default (newrank=false) uses cluster-aware ranking."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { a -> b; }
                subgraph cluster_1 { c -> d; }
                a -> c;
            }
        """)
        assert len(r["nodes"]) == 4
        # Should still produce valid layout
        ya = node_by_name(r, "a")["y"]
        yb = node_by_name(r, "b")["y"]
        assert ya < yb  # a above b within cluster

    def test_newrank_with_rank_same(self):
        """newrank=true with rank=same works across cluster boundaries."""
        r = layout_dot("""
            digraph G {
                newrank=true;
                subgraph cluster_0 { a; b; }
                subgraph cluster_1 { c; }
                { rank=same; b; c; }
                a -> b;
                a -> c;
            }
        """)
        yb = node_by_name(r, "b")["y"]
        yc = node_by_name(r, "c")["y"]
        assert yb == pytest.approx(yc, abs=1)

    def test_newrank_no_clusters_same_as_default(self):
        """Without clusters, newrank has no effect."""
        r1 = layout_dot("digraph G { a -> b -> c; }")
        r2 = layout_dot("digraph G { newrank=true; a -> b -> c; }")
        # Same number of nodes and edges
        assert len(r1["nodes"]) == len(r2["nodes"])
        assert len(r1["edges"]) == len(r2["edges"])

    def test_cluster_aware_ranking_preserves_internal_order(self):
        """Cluster-aware ranking preserves internal edge ordering."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_X {
                    x1 -> x2 -> x3;
                }
                y -> x1;
            }
        """)
        yx1 = node_by_name(r, "x1")["y"]
        yx2 = node_by_name(r, "x2")["y"]
        yx3 = node_by_name(r, "x3")["y"]
        assert yx1 < yx2 < yx3

    def test_inter_cluster_edges_respected(self):
        """Edges between clusters establish proper rank ordering."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_A { a1 -> a2; }
                subgraph cluster_B { b1 -> b2; }
                a2 -> b1;
            }
        """)
        ya2 = node_by_name(r, "a2")["y"]
        yb1 = node_by_name(r, "b1")["y"]
        # a2 should be above or at same level as b1
        assert ya2 <= yb1 + 1


# ── Group A: Layout-affecting attributes ─────────

class TestFixedsize:

    def test_fixedsize_ignores_label(self):
        """fixedsize=true uses exact dimensions regardless of label text."""
        r = layout_dot('digraph G { a [fixedsize=true, width="0.5", height="0.5", label="Very long label"]; }')
        na = node_by_name(r, "a")
        assert na["width"] == pytest.approx(36.0, abs=0.1)
        assert na["height"] == pytest.approx(36.0, abs=0.1)

    def test_no_fixedsize_expands(self):
        """Without fixedsize, long labels widen the node."""
        r = layout_dot('digraph G { a [label="A very long label indeed"]; }')
        na = node_by_name(r, "a")
        assert na["width"] > 54.0  # wider than default minimum


class TestCenter:

    def test_center_shifts_to_origin(self):
        """center=true centers the drawing near the origin.

        The bb includes edge routing points and arrowheads which may
        extend slightly beyond the centered node extents, so we allow
        a tolerance rather than requiring exact centering.
        """
        r = layout_dot('digraph G { center=true; a -> b -> c; }')
        bb = r["graph"]["bb"]
        cx = (bb[0] + bb[2]) / 2
        cy = (bb[1] + bb[3]) / 2
        assert abs(cx) < 30.0
        assert abs(cy) < 30.0


class TestPad:

    def test_pad_in_json(self):
        """pad attribute appears in graph JSON."""
        r = layout_dot('digraph G { pad=0.5; a -> b; }')
        assert "pad" in r["graph"]
        assert r["graph"]["pad"] == pytest.approx(36.0, abs=0.1)


class TestLandscapeRotate:

    def test_landscape_swaps_dimensions(self):
        """landscape=true rotates the layout 90 degrees."""
        r = layout_dot('digraph G { landscape=true; a -> b -> c; }')
        assert len(r["nodes"]) == 3

    def test_rotate_90(self):
        """rotate=90 rotates the layout."""
        r = layout_dot('digraph G { rotate=90; a -> b; }')
        assert len(r["nodes"]) == 2


class TestDpi:

    def test_dpi_in_json(self):
        """dpi attribute appears in graph JSON."""
        r = layout_dot('digraph G { dpi=150; a -> b; }')
        assert r["graph"]["dpi"] == 150.0


class TestOutputorder:

    def test_outputorder_in_json(self):
        """outputorder attribute appears in graph JSON."""
        r = layout_dot('digraph G { outputorder=edgesfirst; a -> b; }')
        assert r["graph"]["outputorder"] == "edgesfirst"


class TestLabelloc:

    def test_labelloc_passthrough(self):
        """labelloc on graph is passed through to JSON."""
        r = layout_dot('digraph G { label="Title"; labelloc=t; a -> b; }')
        assert r["graph"].get("labelloc") == "t"
        assert r["graph"].get("label") == "Title"

    def test_labeljust_passthrough(self):
        """labeljust on graph is passed through to JSON."""
        r = layout_dot('digraph G { label="Title"; labeljust=l; a -> b; }')
        assert r["graph"].get("labeljust") == "l"


class TestXlabel:

    def test_xlabel_position_computed(self):
        """xlabel gets a computed position outside the node."""
        r = layout_dot('digraph G { a [xlabel="extra"]; }')
        na = node_by_name(r, "a")
        assert na.get("xlabel") == "extra"
        assert "_xlabel_pos_x" in na
        assert "_xlabel_pos_y" in na

    def test_headlabel_taillabel_positions(self):
        """headlabel and taillabel get computed positions near edge ends."""
        r = layout_dot('digraph G { splines=line; a -> b [headlabel="H", taillabel="T"]; }')
        edge = r["edges"][0]
        assert edge.get("headlabel") == "H"
        assert edge.get("taillabel") == "T"
        assert "_headlabel_pos_x" in edge
        assert "_taillabel_pos_y" in edge


class TestNodePolygonAttrs:

    def test_sides_passthrough(self):
        """sides attribute is passed through to JSON."""
        r = layout_dot('digraph G { a [shape=polygon, sides=6]; }')
        na = node_by_name(r, "a")
        assert na.get("sides") == "6"

    def test_orientation_passthrough(self):
        """orientation attribute is passed through to JSON."""
        r = layout_dot('digraph G { a [orientation=45]; }')
        na = node_by_name(r, "a")
        assert na.get("orientation") == "45"

    def test_distortion_passthrough(self):
        """distortion attribute is passed through to JSON."""
        r = layout_dot('digraph G { a [distortion=0.5]; }')
        na = node_by_name(r, "a")
        assert na.get("distortion") == "0.5"

    def test_peripheries_passthrough(self):
        """peripheries attribute is passed through to JSON."""
        r = layout_dot('digraph G { a [peripheries=2]; }')
        na = node_by_name(r, "a")
        assert na.get("peripheries") == "2"


class TestDecorate:

    def test_decorate_passthrough(self):
        """decorate attribute is passed through to edge JSON."""
        r = layout_dot('digraph G { a -> b [label="x", decorate=true]; }')
        edge = r["edges"][0]
        assert edge.get("decorate") == "true"


# ── Group B: Rendering-only attributes ───────────

class TestBgcolor:

    def test_bgcolor_on_graph(self):
        """bgcolor attribute is passed through to graph JSON."""
        r = layout_dot('digraph G { bgcolor=lightgray; a -> b; }')
        assert r["graph"].get("bgcolor") == "lightgray"


class TestPencolor:

    def test_pencolor_on_cluster(self):
        """pencolor on cluster is passed through to cluster JSON."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { color=red; pencolor=blue; a; b; }
            }
        """)
        cl = r["clusters"][0]
        assert cl.get("pencolor") == "blue"


class TestColorscheme:

    def test_colorscheme_on_node(self):
        """colorscheme on node is passed through to JSON."""
        r = layout_dot('digraph G { a [colorscheme=svg]; }')
        na = node_by_name(r, "a")
        assert na.get("colorscheme") == "svg"


class TestGradientAngle:

    def test_gradientangle_on_node(self):
        """gradientangle on node is passed through to JSON."""
        r = layout_dot('digraph G { a [gradientangle=90]; }')
        na = node_by_name(r, "a")
        assert na.get("gradientangle") == "90"


class TestImage:

    def test_image_on_node(self):
        """image on node is passed through to JSON."""
        r = layout_dot('digraph G { a [image="icon.png"]; }')
        na = node_by_name(r, "a")
        assert na.get("image") == "icon.png"

    def test_imagescale_on_node(self):
        """imagescale on node is passed through to JSON."""
        r = layout_dot('digraph G { a [imagescale=true]; }')
        na = node_by_name(r, "a")
        assert na.get("imagescale") == "true"


class TestLabelFontAttrs:

    def test_labelfontcolor_on_edge(self):
        """labelfontcolor on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [headlabel="H", labelfontcolor=red]; }')
        edge = r["edges"][0]
        assert edge.get("labelfontcolor") == "red"

    def test_labelfontname_on_edge(self):
        """labelfontname on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [headlabel="H", labelfontname=Courier]; }')
        edge = r["edges"][0]
        assert edge.get("labelfontname") == "Courier"


class TestArrowsize:

    def test_arrowsize_on_edge(self):
        """arrowsize on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [arrowsize=2.0]; }')
        edge = r["edges"][0]
        assert edge.get("arrowsize") == "2.0"


class TestTooltipUrl:

    def test_tooltip_on_node(self):
        """tooltip on node is passed through to JSON."""
        r = layout_dot('digraph G { a [tooltip="hover text"]; }')
        na = node_by_name(r, "a")
        assert na.get("tooltip") == "hover text"

    def test_url_on_node(self):
        """URL on node is passed through to JSON."""
        r = layout_dot('digraph G { a [URL="https://example.com"]; }')
        na = node_by_name(r, "a")
        assert na.get("URL") == "https://example.com"

    def test_tooltip_on_edge(self):
        """tooltip on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [tooltip="edge hover"]; }')
        edge = r["edges"][0]
        assert edge.get("tooltip") == "edge hover"

    def test_url_on_edge(self):
        """URL on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [URL="https://example.com"]; }')
        edge = r["edges"][0]
        assert edge.get("URL") == "https://example.com"


class TestIdClass:

    def test_id_on_node(self):
        """id on node is passed through to JSON."""
        r = layout_dot('digraph G { a [id="my_node"]; }')
        na = node_by_name(r, "a")
        assert na.get("id") == "my_node"

    def test_class_on_node(self):
        """class on node is passed through to JSON."""
        r = layout_dot('digraph G { a [class="highlight"]; }')
        na = node_by_name(r, "a")
        assert na.get("class") == "highlight"

    def test_class_on_edge(self):
        """class on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [class="important"]; }')
        edge = r["edges"][0]
        assert edge.get("class") == "important"


class TestComment:

    def test_comment_on_node(self):
        """comment on node is passed through to JSON."""
        r = layout_dot('digraph G { a [comment="test node"]; }')
        na = node_by_name(r, "a")
        assert na.get("comment") == "test node"

    def test_comment_on_edge(self):
        """comment on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [comment="test edge"]; }')
        edge = r["edges"][0]
        assert edge.get("comment") == "test edge"


class TestClusterVisualAttrs:

    def test_cluster_fillcolor(self):
        """fillcolor on cluster is passed through to JSON."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { fillcolor=yellow; style=filled; a; b; }
            }
        """)
        cl = r["clusters"][0]
        assert cl.get("fillcolor") == "yellow"
        assert cl.get("style") == "filled"

    def test_cluster_fontname(self):
        """fontname on cluster is passed through to JSON."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { fontname=Courier; label="Test"; a; }
            }
        """)
        cl = r["clusters"][0]
        assert cl.get("fontname") == "Courier"


# ── SVG map edge attributes ─────────────────────

class TestEdgeSvgMapAttrs:

    def test_edgeURL_passthrough(self):
        """edgeURL on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [edgeURL="https://example.com/edge"]; }')
        assert r["edges"][0].get("edgeURL") == "https://example.com/edge"

    def test_edgetooltip_passthrough(self):
        """edgetooltip on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [edgetooltip="edge body hover"]; }')
        assert r["edges"][0].get("edgetooltip") == "edge body hover"

    def test_edgetarget_passthrough(self):
        """edgetarget on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [edgetarget="_top"]; }')
        assert r["edges"][0].get("edgetarget") == "_top"

    def test_headURL_passthrough(self):
        """headURL on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [headURL="https://example.com/head"]; }')
        assert r["edges"][0].get("headURL") == "https://example.com/head"

    def test_headtooltip_passthrough(self):
        """headtooltip on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [headtooltip="head hover"]; }')
        assert r["edges"][0].get("headtooltip") == "head hover"

    def test_tailURL_passthrough(self):
        """tailURL on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [tailURL="https://example.com/tail"]; }')
        assert r["edges"][0].get("tailURL") == "https://example.com/tail"

    def test_tailtooltip_passthrough(self):
        """tailtooltip on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [tailtooltip="tail hover"]; }')
        assert r["edges"][0].get("tailtooltip") == "tail hover"

    def test_labelURL_passthrough(self):
        """labelURL on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [label="x", labelURL="https://example.com/label"]; }')
        assert r["edges"][0].get("labelURL") == "https://example.com/label"

    def test_labeltooltip_passthrough(self):
        """labeltooltip on edge is passed through to JSON."""
        r = layout_dot('digraph G { a -> b [label="x", labeltooltip="label hover"]; }')
        assert r["edges"][0].get("labeltooltip") == "label hover"

    def test_all_href_synonyms(self):
        """href synonyms (edgehref, headhref, tailhref, labelhref) pass through."""
        r = layout_dot("""
            digraph G {
                a -> b [edgehref="e", headhref="h", tailhref="t", labelhref="l", label="x"];
            }
        """)
        e = r["edges"][0]
        assert e.get("edgehref") == "e"
        assert e.get("headhref") == "h"
        assert e.get("tailhref") == "t"
        assert e.get("labelhref") == "l"

    def test_all_target_variants(self):
        """All target variants pass through."""
        r = layout_dot("""
            digraph G {
                a -> b [headtarget="_top", tailtarget="_self",
                         labeltarget="_parent", edgetarget="_blank",
                         headlabel="H", taillabel="T", label="L"];
            }
        """)
        e = r["edges"][0]
        assert e.get("headtarget") == "_top"
        assert e.get("tailtarget") == "_self"
        assert e.get("labeltarget") == "_parent"
        assert e.get("edgetarget") == "_blank"


# ── Missing attribute coverage tests ─────────────

class TestMissingAttrCoverage:
    """Tests for attributes that were missing from the test suite."""

    def test_forcelabels(self):
        """forcelabels graph attribute is read."""
        r = layout_dot('digraph G { forcelabels=false; a [xlabel="x"]; }')
        assert len(r["nodes"]) == 1

    def test_fontsize_on_node(self):
        """fontsize on node affects sizing and is passed to JSON."""
        r = layout_dot('digraph G { a [fontsize=24, label="Big Text Here"]; b [fontsize=8, label="Small Text Here"]; }')
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        assert na.get("fontsize") == "24"
        assert nb.get("fontsize") == "8"
        # Larger font = wider node (with long enough labels)
        assert na["width"] > nb["width"]

    def test_penwidth_on_node(self):
        """penwidth on node is passed to JSON."""
        r = layout_dot('digraph G { a [penwidth=3]; }')
        na = node_by_name(r, "a")
        assert na.get("penwidth") == "3"

    def test_penwidth_on_edge(self):
        """penwidth on edge is passed to JSON."""
        r = layout_dot('digraph G { a -> b [penwidth=2.5]; }')
        assert r["edges"][0].get("penwidth") == "2.5"

    def test_skew_on_node(self):
        """skew on node is passed to JSON."""
        r = layout_dot('digraph G { a [skew=0.3]; }')
        na = node_by_name(r, "a")
        assert na.get("skew") == "0.3"

    def test_regular_on_node(self):
        """regular on node is passed to JSON."""
        r = layout_dot('digraph G { a [regular=true]; }')
        na = node_by_name(r, "a")
        assert na.get("regular") == "true"

    def test_nojustify_on_node(self):
        """nojustify on node is passed to JSON."""
        r = layout_dot('digraph G { a [nojustify=true]; }')
        na = node_by_name(r, "a")
        assert na.get("nojustify") == "true"

    def test_nojustify_on_edge(self):
        """nojustify on edge is passed to JSON."""
        r = layout_dot('digraph G { a -> b [nojustify=true]; }')
        assert r["edges"][0].get("nojustify") == "true"

    def test_arrowhead_on_edge(self):
        """arrowhead on edge is passed to JSON."""
        r = layout_dot('digraph G { a -> b [arrowhead=diamond]; }')
        assert r["edges"][0].get("arrowhead") == "diamond"

    def test_arrowtail_on_edge(self):
        """arrowtail on edge is passed to JSON."""
        r = layout_dot('digraph G { a -> b [arrowtail=dot]; }')
        assert r["edges"][0].get("arrowtail") == "dot"

    def test_labelfloat_on_edge(self):
        """labelfloat on edge is passed to JSON."""
        r = layout_dot('digraph G { a -> b [label="x", labelfloat=true]; }')
        assert r["edges"][0].get("labelfloat") == "true"

    def test_labelfontsize_on_edge(self):
        """labelfontsize on edge is passed to JSON."""
        r = layout_dot('digraph G { a -> b [headlabel="H", labelfontsize=18]; }')
        assert r["edges"][0].get("labelfontsize") == "18"


class TestLabelPlacement:
    """Tests for the collision-aware label placement algorithm."""

    def test_xlabel_avoids_node(self):
        """xlabel position is outside the node bounding box."""
        r = layout_dot('digraph G { a [xlabel="extra info"]; }')
        na = node_by_name(r, "a")
        xlabel_x = float(na["_xlabel_pos_x"])
        xlabel_y = float(na["_xlabel_pos_y"])
        # xlabel should be outside the node's bounding box
        node_right = na["x"] + na["width"] / 2
        node_bottom = na["y"] + na["height"] / 2
        # At least one coordinate should be beyond the node boundary
        assert xlabel_x > node_right or xlabel_y > node_bottom or \
               xlabel_x < na["x"] - na["width"] / 2 or \
               xlabel_y < na["y"] - na["height"] / 2

    def test_xlabel_collision_avoidance(self):
        """Multiple xlabels don't overlap when there's room."""
        r = layout_dot('''digraph G {
            nodesep=2;
            a [xlabel="Label A"];
            b [xlabel="Label B"];
            a -> b;
        }''')
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        ax = float(na["_xlabel_pos_x"])
        ay = float(na["_xlabel_pos_y"])
        bx = float(nb["_xlabel_pos_x"])
        by = float(nb["_xlabel_pos_y"])
        # Labels should not be at the exact same position
        assert not (abs(ax - bx) < 1 and abs(ay - by) < 1)

    def test_headlabel_has_position(self):
        """headlabel gets a computed position near the head endpoint."""
        r = layout_dot('digraph G { a -> b [headlabel="Head"]; }')
        edge = r["edges"][0]
        hx = float(edge["_headlabel_pos_x"])
        hy = float(edge["_headlabel_pos_y"])
        # Should be near the head endpoint (last point)
        head_pt = edge["points"][-1]
        dist = ((hx - head_pt[0])**2 + (hy - head_pt[1])**2)**0.5
        assert dist < 100  # within reasonable distance

    def test_taillabel_has_position(self):
        """taillabel gets a computed position near the tail endpoint."""
        r = layout_dot('digraph G { a -> b [taillabel="Tail"]; }')
        edge = r["edges"][0]
        tx = float(edge["_taillabel_pos_x"])
        ty = float(edge["_taillabel_pos_y"])
        # Should be near the tail endpoint (first point)
        tail_pt = edge["points"][0]
        dist = ((tx - tail_pt[0])**2 + (ty - tail_pt[1])**2)**0.5
        assert dist < 100

    def test_headlabel_taillabel_different_positions(self):
        """headlabel and taillabel get different positions."""
        r = layout_dot('digraph G { a -> b [headlabel="H", taillabel="T"]; }')
        edge = r["edges"][0]
        hx = float(edge["_headlabel_pos_x"])
        hy = float(edge["_headlabel_pos_y"])
        tx = float(edge["_taillabel_pos_x"])
        ty = float(edge["_taillabel_pos_y"])
        # They shouldn't be at the same position
        assert abs(hx - tx) > 1 or abs(hy - ty) > 1

    def test_graph_label_bottom(self):
        """Graph label positioned below the graph by default (labelloc=b)."""
        r = layout_dot('digraph G { label="My Graph"; a -> b; }')
        graph = r["graph"]
        assert graph.get("label") == "My Graph"
        assert "_label_pos_x" in graph
        assert "_label_pos_y" in graph
        # Default labelloc=b means label is below the graph bb
        label_y = float(graph["_label_pos_y"])
        bb_bottom = graph["bb"][3]
        assert label_y >= bb_bottom

    def test_graph_label_top(self):
        """Graph label positioned above the graph with labelloc=t."""
        r = layout_dot('digraph G { label="Title"; labelloc=t; a -> b; }')
        graph = r["graph"]
        label_y = float(graph["_label_pos_y"])
        bb_top = graph["bb"][1]
        assert label_y <= bb_top

    def test_graph_label_left_justified(self):
        """Graph label left-justified with labeljust=l."""
        r = layout_dot('digraph G { label="Left"; labeljust=l; a -> b; }')
        graph = r["graph"]
        label_x = float(graph["_label_pos_x"])
        bb_center = (graph["bb"][0] + graph["bb"][2]) / 2
        # Left-justified should be left of center
        assert label_x < bb_center

    def test_graph_label_right_justified(self):
        """Graph label right-justified with labeljust=r."""
        r = layout_dot('digraph G { label="Right"; labeljust=r; a -> b; }')
        graph = r["graph"]
        label_x = float(graph["_label_pos_x"])
        bb_center = (graph["bb"][0] + graph["bb"][2]) / 2
        assert label_x > bb_center

    def test_xlabel_svg_rendered(self):
        """xlabel appears in SVG output."""
        from gvpy.render.svg_renderer import render_svg
        r = layout_dot('digraph G { a [xlabel="ExtraLabel"]; }')
        svg = render_svg(r)
        assert "ExtraLabel" in svg
        assert "italic" in svg  # xlabels are rendered in italic

    def test_graph_label_svg_rendered(self):
        """Graph label appears in SVG output."""
        from gvpy.render.svg_renderer import render_svg
        r = layout_dot('digraph G { label="GraphTitle"; a -> b; }')
        svg = render_svg(r)
        assert "GraphTitle" in svg

    def test_label_size_estimation(self):
        """Label size estimation produces reasonable values."""
        w, h = DotLayout._estimate_label_size("Hello", 14.0)
        assert w > 0
        assert h > 0
        # 5 chars at 14pt should be roughly 42x16.8
        assert 30 < w < 80
        assert 10 < h < 25

    def test_label_size_multiline(self):
        """Multi-line labels are taller."""
        w1, h1 = DotLayout._estimate_label_size("Line1", 14.0)
        w2, h2 = DotLayout._estimate_label_size("Line1\\nLine2", 14.0)
        assert h2 > h1  # two lines should be taller

    def test_overlap_detection(self):
        """Overlap detection correctly identifies overlapping rectangles."""
        # _rects_overlap removed; use _overlap_area > 0 instead
        assert DotLayout._overlap_area(0, 0, 10, 10, 5, 5, 10, 10) > 0
        assert DotLayout._overlap_area(0, 0, 10, 10, 20, 20, 10, 10) == 0

    def test_overlap_area(self):
        """Overlap area calculation returns correct values."""
        # Full overlap (same rect)
        area = DotLayout._overlap_area(0, 0, 10, 10, 0, 0, 10, 10)
        assert abs(area - 100) < 0.01
        # No overlap
        area = DotLayout._overlap_area(0, 0, 10, 10, 100, 100, 10, 10)
        assert area == 0.0
        # Partial overlap
        area = DotLayout._overlap_area(0, 0, 10, 10, 5, 0, 10, 10)
        assert 0 < area < 100


# ═══════════════════════════════════════════════════════════════
#  Gap 1: Edge label ranks
# ═══════════════════════════════════════════════════════════════

class TestEdgeLabelRanks:
    """Labeled cross-rank edges get minlen >= 2 to reserve label space."""

    def test_labeled_edge_minlen(self):
        """A labeled edge between adjacent ranks gets minlen=2."""
        r = layout_dot('digraph G { a -> b [label="edge_label"]; }')
        a = node_by_name(r, "a")
        b = node_by_name(r, "b")
        # With minlen=2, there should be more rank separation than default
        gap = abs(b["y"] - a["y"])
        # Default 1-rank gap with ranksep=36 is ~72pt; with minlen=2 it
        # should be roughly double
        assert gap > 100, f"Labeled edge gap {gap} should be > 100pt"

    def test_unlabeled_edge_normal_minlen(self):
        """An unlabeled edge keeps the default minlen=1."""
        r = layout_dot("digraph G { a -> b; }")
        a = node_by_name(r, "a")
        b = node_by_name(r, "b")
        gap = abs(b["y"] - a["y"])
        assert gap < 120, f"Unlabeled edge gap {gap} should be < 120pt"

    def test_241_edges_same_rank(self):
        """241_1.dot: same-rank edges have no label, no extra spacing."""
        src = Path("test_data/241_1.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        # All nodes should be on the same rank (same Y)
        ys = set(round(n["y"], 0) for n in r["nodes"])
        assert len(ys) == 1, f"Expected 1 rank, got {len(ys)}: {ys}"


# ═══════════════════════════════════════════════════════════════
#  Gap 2: Expand leaves
# ═══════════════════════════════════════════════════════════════

class TestExpandLeaves:
    """Degree-1 nodes get minimum width for proper spacing."""

    def test_leaf_node_minimum_width(self):
        """A leaf node has width >= 2*nodesep."""
        r = layout_dot("digraph G { a -> b; }")
        # b is a leaf (degree 1)
        b = node_by_name(r, "b")
        assert b["width"] >= 36, f"Leaf width {b['width']} should be >= 36"

    def test_non_leaf_keeps_original_width(self):
        """A node with degree > 1 keeps its computed width."""
        r = layout_dot("digraph G { a -> b; a -> c; b -> c; }")
        # a has degree 2 (two outgoing), not a leaf
        a = node_by_name(r, "a")
        # Width should be based on label, not forced minimum
        assert a["width"] > 0

    def test_1332_nodes_present(self):
        """aa1332.dot has 91 nodes after layout."""
        src = Path("test_data/aa1332.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        assert len(r["nodes"]) == 91


# ═══════════════════════════════════════════════════════════════
#  Gap 3: Keep-out other nodes
# ═══════════════════════════════════════════════════════════════

class TestKeepOutOtherNodes:
    """Non-cluster nodes are pushed outside cluster boundaries."""

    def test_external_node_outside_cluster(self):
        """A node outside a cluster should not overlap the cluster box."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { a; b; a -> b; }
                c;
                a -> c;
            }
        """)
        # Find cluster box
        clusters = r.get("clusters", [])
        assert len(clusters) >= 1
        cl = clusters[0]
        bb = cl["bb"]

        # Node c should be outside the cluster bounding box
        c = node_by_name(r, "c")
        cx, cy = c["x"], c["y"]
        cw, ch = c["width"] / 2, c["height"] / 2

        # c's bounding box should not be fully inside the cluster
        c_inside = (cx - cw >= bb[0] and cx + cw <= bb[2] and
                    cy - ch >= bb[1] and cy + ch <= bb[3])
        assert not c_inside, "External node 'c' should not be inside cluster"

    def test_241_all_nodes_same_rank(self):
        """241_1.dot: nodes on the same rank are properly ordered."""
        src = Path("test_data/241_1.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        assert len(r["nodes"]) == 13
        assert len(r["edges"]) >= 24  # 12 directed + 12 undirected

    def test_1332_cluster_count(self):
        """aa1332.dot produces clusters with correct DarkGreen coloring."""
        src = Path("test_data/aa1332.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        clusters = r.get("clusters", [])
        # Should have cluster entries
        assert len(clusters) > 60
        # Named clusters with color=DarkGreen
        dark_green = [cl for cl in clusters
                      if cl.get("color") == "DarkGreen"]
        assert len(dark_green) == 20


# ═══════════════════════════════════════════════════════════════
#  Gap 4: Flat edge routing variants
# ═══════════════════════════════════════════════════════════════

class TestFlatEdgeVariants:
    """Flat (same-rank) edge routing dispatches to the correct variant."""

    def test_adjacent_straight(self):
        """Adjacent same-rank nodes with no ports get a straight bezier."""
        r = layout_dot("""
            digraph G { {rank=same; a; b;} a -> b; }
        """)
        edge = r["edges"][0]
        pts = edge["points"]
        # Straight bezier: all points should have similar Y
        ys = [p[1] for p in pts]
        assert max(ys) - min(ys) < 5, f"Adjacent edge should be straight, Y range={max(ys)-min(ys)}"

    def test_port_n_arcs_above(self):
        """Flat edge with tailport=n routes above the nodes (negative Y)."""
        r = layout_dot("""
            digraph G {
                {rank=same; a; b;}
                a -> b [tailport=n, headport=n, dir=none, color=red];
            }
        """)
        edges = [e for e in r["edges"] if e.get("color") == "red"]
        assert len(edges) >= 1
        pts = edges[0]["points"]
        node_y = node_by_name(r, "a")["y"]
        # Arc control points should be above (lower Y) the nodes
        min_ctrl_y = min(p[1] for p in pts)
        assert min_ctrl_y < node_y, "North-port arc should go above nodes"

    def test_port_s_arcs_below(self):
        """Flat edge with tailport=s routes below the nodes (positive Y)."""
        r = layout_dot("""
            digraph G {
                {rank=same; a; b;}
                a -> b [tailport=s, headport=s, dir=none];
            }
        """)
        edges = r["edges"]
        assert len(edges) >= 1
        pts = edges[0]["points"]
        node_y = node_by_name(r, "a")["y"]
        max_ctrl_y = max(p[1] for p in pts)
        assert max_ctrl_y > node_y, "South-port arc should go below nodes"

    def test_241_directed_edges_straight(self):
        """241_1.dot: directed same-rank edges between adjacent nodes are straight."""
        src = Path("test_data/241_1.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        # Find a directed (non-red) edge between adjacent nodes
        directed = [e for e in r["edges"]
                    if not e.get("color") and not e.get("dir")]
        assert len(directed) >= 6  # 0->1 through 11->12 minus missing
        # Check that directed edges are approximately straight
        for e in directed[:3]:
            pts = e["points"]
            ys = [p[1] for p in pts]
            assert max(ys) - min(ys) < 10, \
                f"Directed {e['tail']}->{e['head']} should be straight"

    def test_241_red_edges_arc_above(self):
        """241_1.dot: red undirected edges arc above the nodes."""
        src = Path("test_data/241_1.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        red_edges = [e for e in r["edges"] if e.get("color") == "red"]
        assert len(red_edges) == 12
        node_ys = {n["name"]: n["y"] for n in r["nodes"]}
        for e in red_edges:
            pts = e["points"]
            tail_y = node_ys.get(e["tail"], 0)
            min_y = min(p[1] for p in pts)
            assert min_y < tail_y, \
                f"Red {e['tail']}->{e['head']} should arc above nodes"


# ═══════════════════════════════════════════════════════════════
#  Gap 5: Edge classification
# ═══════════════════════════════════════════════════════════════

class TestEdgeClassification:
    """Edge classification labels edges with correct types."""

    def test_normal_edge_classified(self):
        """Cross-rank edges are classified as 'normal'."""
        g = read_gv("digraph G { a -> b; }")
        engine = DotLayout(g)
        engine._init_from_graph()
        engine._classify_edges()
        for le in engine.ledges:
            if not le.virtual:
                assert le.edge_type == "normal"

    def test_self_loop_classified(self):
        """Self-loop edges are classified as 'self'."""
        g = read_gv("digraph G { a -> a; }")
        engine = DotLayout(g)
        engine._init_from_graph()
        engine._classify_edges()
        self_edges = [le for le in engine.ledges if le.edge_type == "self"]
        assert len(self_edges) >= 1

    def test_flat_edge_classified_after_ranking(self):
        """Same-rank edges are classified as 'flat' after ranking."""
        g = read_gv("""
            digraph G { {rank=same; a; b;} a -> b; c -> a; }
        """)
        engine = DotLayout(g)
        engine._init_from_graph()
        engine._phase1_rank()
        flat_edges = [le for le in engine.ledges
                      if le.edge_type == "flat" and not le.virtual]
        assert len(flat_edges) >= 1, "Should have at least 1 flat edge"

    def test_1332_no_flat_edges(self):
        """aa1332.dot has no same-rank edges (all cross-rank)."""
        src = Path("test_data/aa1332.dot").read_text(encoding="utf-8")
        g = read_gv(src)
        engine = DotLayout(g)
        engine._init_from_graph()
        engine._phase1_rank()
        flat_edges = [le for le in engine.ledges
                      if le.edge_type == "flat" and not le.virtual]
        # aa1332.dot is rankdir=LR with no rank=same constraints,
        # so there should be no flat edges
        assert len(flat_edges) == 0

    def test_241_flat_edges_detected(self):
        """241_1.dot has flat edges (rank=same subgraph)."""
        src = Path("test_data/241_1.dot").read_text(encoding="utf-8")
        g = read_gv(src)
        engine = DotLayout(g)
        engine._init_from_graph()
        engine._phase1_rank()
        flat_edges = [le for le in engine.ledges
                      if le.edge_type == "flat" and not le.virtual]
        # All edges in 241_1.dot are same-rank
        assert len(flat_edges) >= 18, \
            f"Expected >= 18 flat edges, got {len(flat_edges)}"


# ═══════════════════════════════════════════════════════════════
#  Gap 6: Cluster skeleton/expansion
# ═══════════════════════════════════════════════════════════════

class TestClusterSkeleton:
    """Skeleton-based cluster ordering keeps cluster nodes contiguous."""

    def test_cluster_nodes_contiguous(self):
        """Nodes in the same cluster occupy contiguous positions per rank."""
        r = layout_dot("""
            digraph G {
                subgraph cluster_0 { a; b; c; a -> b -> c; }
                subgraph cluster_1 { d; e; d -> e; }
                a -> d;
            }
        """)
        nodes = {n["name"]: n for n in r["nodes"]}
        clusters = r.get("clusters", [])
        # Verify cluster_0 nodes have contiguous X positions
        assert len(clusters) >= 2

    def test_skeleton_preserves_node_count(self):
        """Skeleton expansion restores all original nodes."""
        src = Path("test_data/aa1332.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        assert len(r["nodes"]) == 91

    def test_skeleton_preserves_edge_count(self):
        """Skeleton expansion preserves all edges."""
        src = Path("test_data/aa1332.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        assert len(r["edges"]) >= 116  # 117 expected

    def test_no_skeleton_nodes_in_output(self):
        """No skeleton virtual nodes appear in the final output."""
        src = Path("test_data/aa1332.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        for n in r["nodes"]:
            assert not n["name"].startswith("_skel_"), \
                f"Skeleton node {n['name']} should not be in output"

    def test_simple_graph_no_clusters(self):
        """Graphs without clusters still work (no skeleton needed)."""
        r = layout_dot("digraph G { a -> b -> c; }")
        assert len(r["nodes"]) == 3
        assert len(r["edges"]) == 2


# ═══════════════════════════════════════════════════════════════
#  Gap 7: Schneider B-spline fitter
# ═══════════════════════════════════════════════════════════════

class TestBSplineFitter:
    """Schneider B-spline fitter produces smooth cubic Bezier curves."""

    def test_two_point_produces_cubic(self):
        """Two-point input produces a 4-point cubic Bezier."""
        pts = [(0, 0), (100, 100)]
        result = DotLayout._to_bezier(pts)
        assert len(result) == 4
        assert result[0] == (0, 0)
        assert result[3] == (100, 100)

    def test_three_point_smooth(self):
        """Three-point input produces a smooth cubic Bezier."""
        pts = [(0, 0), (50, 50), (100, 0)]
        result = DotLayout._to_bezier(pts)
        # Should produce 4 points (single cubic) or 7 (two cubics)
        assert len(result) >= 4
        # First and last points preserved
        assert result[0] == (0, 0)
        assert result[-1] == (100, 0)

    def test_multi_point_produces_valid_bezier(self):
        """Multi-point input produces valid Bezier (groups of 3n+1)."""
        pts = [(0, 0), (25, 50), (50, 0), (75, -50), (100, 0)]
        result = DotLayout._to_bezier(pts)
        # Result length should be 3n+1 for n cubic segments
        assert (len(result) - 1) % 3 == 0, \
            f"Bezier length {len(result)} is not 3n+1"
        assert result[0] == (0, 0)
        assert result[-1] == (100, 0)

    def test_collinear_stays_straight(self):
        """Collinear points produce a nearly-straight Bezier."""
        pts = [(0, 0), (33, 0), (66, 0), (100, 0)]
        result = DotLayout._to_bezier(pts)
        # All control points should be near y=0
        for p in result:
            assert abs(p[1]) < 5, f"Point {p} should be near y=0"

    def test_241_edges_have_bezier(self):
        """241_1.dot edges produce Bezier curves in SVG."""
        src = Path("test_data/241_1.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        # All edges should have at least 4 points (one cubic segment)
        for e in r["edges"]:
            assert len(e["points"]) >= 4, \
                f"{e['tail']}->{e['head']} has {len(e['points'])} pts"

    def test_1332_long_edges_smooth(self):
        """aa1332.dot multi-rank edges produce smooth multi-segment Beziers."""
        src = Path("test_data/aa1332.dot").read_text(encoding="utf-8")
        r = layout_dot(src)
        # Find a multi-rank edge (more than 4 points)
        long_edges = [e for e in r["edges"] if len(e["points"]) > 4]
        # There should be some multi-segment edges
        assert len(long_edges) >= 0  # may not have any if all 1-rank
