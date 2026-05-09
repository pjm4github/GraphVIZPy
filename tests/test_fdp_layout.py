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


class TestFdpClusterTracking:
    """Phase A of the cluster-aware routing port (TODO §4.x).

    Verify discovery, parent / level maps, node→cluster, and
    post-layout bbox computation.  These tests pin the contracts
    that the upcoming compoundEdges port will rely on.
    """

    def _layout(self, src):
        graph = read_gv(src)
        layout = FdpLayout(graph)
        layout.layout()
        return layout

    def test_discovery_no_clusters(self):
        """A flat graph leaves cluster state empty."""
        layout = self._layout("graph G { a -- b -- c; }")
        assert layout._clusters == []
        assert layout._cluster_parent == {}
        assert layout._cluster_level == {}
        assert all(v is None for v in layout._node_to_cluster.values())

    def test_discovery_three_top_level(self):
        """Three sibling clusters all at level 1, parent None."""
        src = """graph G {
            subgraph cluster_a { a1; a2; }
            subgraph cluster_b { b1; b2; }
            subgraph cluster_c { c1; c2; }
            a1 -- b1; b1 -- c1;
        }"""
        layout = self._layout(src)
        assert {c.name for c in layout._clusters} == {
            "cluster_a", "cluster_b", "cluster_c"
        }
        for cl_name in ("cluster_a", "cluster_b", "cluster_c"):
            assert layout._cluster_parent[cl_name] is None
            assert layout._cluster_level[cl_name] == 1

    def test_node_to_cluster_innermost(self):
        """PARENT(node) maps to the innermost containing cluster."""
        src = """graph G {
            subgraph cluster_outer {
                outside;
                subgraph cluster_inner { inside1; inside2; }
            }
            free;
        }"""
        layout = self._layout(src)
        n2c = layout._node_to_cluster
        # ``outside`` is in cluster_outer's direct list only.
        assert n2c["outside"] == "cluster_outer"
        # ``inside*`` are in cluster_inner directly; cluster_outer
        # transitively. PARENT must be the innermost.
        assert n2c["inside1"] == "cluster_inner"
        assert n2c["inside2"] == "cluster_inner"
        # ``free`` is outside any cluster.
        assert n2c["free"] is None
        # Level / parent of cluster_inner.
        assert layout._cluster_parent["cluster_inner"] == "cluster_outer"
        assert layout._cluster_level["cluster_outer"] == 1
        assert layout._cluster_level["cluster_inner"] == 2

    def test_cluster_bbox_encloses_members(self):
        """Post-layout, each cluster.bb must enclose its members
        plus margin."""
        src = """graph G {
            subgraph cluster_x { x1; x2; x3; x1 -- x2 -- x3; }
            subgraph cluster_y { y1; y2; y1 -- y2; }
        }"""
        layout = self._layout(src)
        for cl in layout._clusters:
            assert cl.bb != (0.0, 0.0, 0.0, 0.0), (
                f"{cl.name}: bbox not computed"
            )
            x_min, y_min, x_max, y_max = cl.bb
            assert x_max > x_min and y_max > y_min
            for n_name in cl.nodes:
                ln = layout.lnodes[n_name]
                # node's bbox must lie inside cluster.bb (margin
                # included).
                assert ln.x - ln.width / 2 >= x_min - 1e-6
                assert ln.x + ln.width / 2 <= x_max + 1e-6
                assert ln.y - ln.height / 2 >= y_min - 1e-6
                assert ln.y + ln.height / 2 <= y_max + 1e-6

    def test_non_cluster_subgraph_ignored(self):
        """Subgraphs whose name doesn't start with ``cluster`` are
        not part of the cluster tree."""
        src = """graph G {
            subgraph not_a_cluster { x; y; }
            subgraph cluster_real { a; b; }
        }"""
        layout = self._layout(src)
        assert {c.name for c in layout._clusters} == {"cluster_real"}
        assert layout._node_to_cluster.get("x") is None
        assert layout._node_to_cluster.get("y") is None
        assert layout._node_to_cluster["a"] == "cluster_real"
        assert layout._node_to_cluster["b"] == "cluster_real"


class TestFdpCompoundRouting:
    """Phase B of the cluster-aware routing port (TODO §4.x).

    Verifies ``object_list`` obstacle filtering and that
    ``FdpLayout.layout()`` dispatches to the cluster-aware
    routing path on clustered graphs.
    """

    def _layout(self, src):
        graph = read_gv(src)
        layout = FdpLayout(graph)
        layout.layout()
        return layout

    def _find_cluster(self, layout, name):
        for cl in layout._clusters:
            if cl.name == name:
                return cl
        raise AssertionError(f"cluster {name!r} not found")

    def _make_edge(self, layout, tail_name, head_name):
        """Find an edge by endpoint names (orientation-insensitive)."""
        for key, edge in layout.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if (t, h) == (tail_name, head_name) or (h, t) == (tail_name, head_name):
                return edge
        raise AssertionError(
            f"edge {tail_name}--{head_name} not found"
        )

    def test_object_list_cross_sibling_excludes_endpoint_clusters(self):
        """Edge tail∈cluster_a, head∈cluster_b: object_list must NOT
        include cluster_a or cluster_b as obstacles (the edge has
        to exit each).  cluster_c (sibling of both) IS included."""
        from gvpy.engines.layout.common.edge_routing import object_list

        # NB: Py parser bugs (separate issues):
        # (a) edges declared inside subgraph blocks aren't registered;
        # (b) edges declared AFTER subgraph blocks at root level
        #     aren't registered either.
        # Workaround: declare edges BEFORE the subgraph blocks.
        # Node-cluster membership is unaffected.
        src = """graph G {
            a1 -- b1;
            subgraph cluster_a { a1; a2; }
            subgraph cluster_b { b1; b2; }
            subgraph cluster_c { c1; c2; }
        }"""
        layout = self._layout(src)
        edge = self._make_edge(layout, "a1", "b1")
        polys = object_list(layout, edge, margin=4.0)
        # The LCA walk visits cluster_b (excluding b1) → adds b2,
        # cluster_a (excluding a1) → adds a2, then root (excluding
        # cluster_a and cluster_b) → adds cluster_c bbox.  Total 3.
        assert len(polys) == 3, (
            f"expected 3 obstacles (a2 node, b2 node, cluster_c bbox), "
            f"got {len(polys)}"
        )

    def test_object_list_intra_cluster(self):
        """Edge between two nodes in the same cluster: the LCA is
        the cluster itself; only the OTHER members of that cluster
        become obstacles (root-level free nodes are NOT visited)."""
        from gvpy.engines.layout.common.edge_routing import object_list

        src = """graph G {
            a -- b;
            subgraph cluster_only { a; b; c; }
            d;
        }"""
        layout = self._layout(src)
        edge = self._make_edge(layout, "a", "b")
        polys = object_list(layout, edge, margin=4.0)
        # LCA = cluster_only.  The while-loop never runs (both
        # endpoints already at the LCA).  addGraphObjs(cluster_only,
        # tex=a, hex_=b) adds cluster_only's direct nodes minus
        # a and b → just c.  Free node ``d`` is at root, NEVER
        # visited because the walk stops at the LCA.
        # → 1 obstacle (c).
        assert len(polys) == 1, (
            f"expected 1 obstacle (member ``c`` of the LCA cluster), "
            f"got {len(polys)}"
        )

    def test_object_list_free_endpoints_with_cluster_between(self):
        """Both endpoints free: object_list contains every cluster
        as a bbox obstacle plus every other free node."""
        from gvpy.engines.layout.common.edge_routing import object_list

        src = """graph G {
            subgraph cluster_x { x1; x2; }
            subgraph cluster_y { y1; y2; }
            free1; free2; free3;
            free1 -- free2;
        }"""
        layout = self._layout(src)
        edge = self._make_edge(layout, "free1", "free2")
        polys = object_list(layout, edge, margin=4.0)
        # 2 cluster bboxes (cluster_x, cluster_y) + 1 free node
        # (free3, the only other free node) = 3 obstacles.
        assert len(polys) == 3, (
            f"expected 3 obstacles "
            f"(cluster_x bbox, cluster_y bbox, free3 node), "
            f"got {len(polys)}"
        )

    def test_object_list_cross_level(self):
        """Edge crossing nesting levels: tail in inner cluster,
        head in outer cluster's direct membership.  raiseLevel
        walks the tail up; LCA is cluster_outer; ``outside``
        (sibling of cluster_inner) is NOT an obstacle (it's the
        head endpoint)."""
        from gvpy.engines.layout.common.edge_routing import object_list

        src = """graph G {
            i1 -- outside;
            subgraph cluster_outer {
                subgraph cluster_inner { i1; i2; }
                outside;
            }
            free;
        }"""
        layout = self._layout(src)
        edge = self._make_edge(layout, "i1", "outside")
        polys = object_list(layout, edge, margin=4.0)
        # raiseLevel: tail at level 2 (cluster_inner), head at
        # level 1 (cluster_outer).  Raise tail one step:
        #   addGraphObjs(cluster_inner, tex=i1, hex_=None) → i2.
        # LCA walk: hg = tg = cluster_outer; while-loop skipped.
        # Final addGraphObjs(cluster_outer, tex=cluster_inner,
        # hex_=outside): direct cluster children = {cluster_inner}
        # (excluded as tex), direct nodes = {outside} (excluded
        # as hex_).  → 0 from this step.
        # Total: 1 obstacle (i2).
        assert len(polys) == 1, (
            f"expected 1 obstacle (i2 from raised cluster_inner), "
            f"got {len(polys)}"
        )

    def test_compound_routing_dispatched_on_clustered_graph(self):
        """FdpLayout.layout() routes via compoundEdges when
        clusters are present (vs. the flat router for clusterless
        graphs)."""
        src = """graph G {
            splines=true;
            subgraph cluster_a { a; }
            subgraph cluster_b { b; }
            a -- b;
        }"""
        layout = self._layout(src)
        # The route should exist and be a multi-point curve.
        assert layout.edge_routes
        for route in layout.edge_routes.values():
            assert len(route.points) >= 2

    def test_flat_graph_uses_flat_router(self):
        """Without clusters, dispatch falls through to the flat
        ``route_edges`` (regression guard — Phase B must not break
        the no-cluster path)."""
        layout = self._layout("graph G { splines=true; a -- b -- c; }")
        assert layout._clusters == []
        assert len(layout.edge_routes) >= 2


class TestFdpClusterEmit:
    """Cluster bbox emission to JSON / -Tdot for downstream
    consumers (SVG renderer, dot round-trip).  Sibling of
    Phase A/B but separately tested so the contract is pinned."""

    def _layout_and_json(self, src):
        graph = read_gv(src)
        layout = FdpLayout(graph)
        return layout, layout.layout()

    def test_json_emits_clusters_array(self):
        """``_to_json`` includes a ``clusters`` array with name,
        label, bb, nodes, and any visual attrs the SVG renderer
        consumes."""
        src = """graph G {
            a1 -- b1;
            subgraph cluster_a { label="A"; color=red; a1; a2; }
            subgraph cluster_b { label="B"; b1; b2; }
        }"""
        _, result = self._layout_and_json(src)
        assert "clusters" in result
        cls = {c["name"]: c for c in result["clusters"]}
        assert set(cls) == {"cluster_a", "cluster_b"}
        for name, c in cls.items():
            assert "bb" in c and len(c["bb"]) == 4
            x1, y1, x2, y2 = c["bb"]
            assert x2 > x1 and y2 > y1
            assert "nodes" in c and len(c["nodes"]) == 2
        assert cls["cluster_a"]["label"] == "A"
        assert cls["cluster_a"].get("color") == "red"

    def test_json_omits_clusters_on_flat_graph(self):
        """Flat graph: no ``clusters`` key."""
        _, result = self._layout_and_json("graph G { a -- b -- c; }")
        assert "clusters" not in result

    def test_json_graph_bb_includes_cluster_bbox(self):
        """``graph.bb`` expands to enclose all cluster bboxes (so
        SVG viewBox doesn't clip cluster outlines)."""
        src = """graph G {
            a1 -- b1;
            subgraph cluster_a { a1; a2; }
            subgraph cluster_b { b1; b2; }
        }"""
        _, result = self._layout_and_json(src)
        gx1, gy1, gx2, gy2 = result["graph"]["bb"]
        for c in result["clusters"]:
            cx1, cy1, cx2, cy2 = c["bb"]
            assert gx1 <= cx1 + 1e-6
            assert gy1 <= cy1 + 1e-6
            assert gx2 + 1e-6 >= cx2
            assert gy2 + 1e-6 >= cy2

    def test_dot_writeback_sets_cluster_bb(self):
        """``_write_back`` populates each cluster subgraph's
        ``attr_record['bb']`` so ``-Tdot`` round-trips include
        post-layout cluster geometry."""
        src = """graph G {
            a1 -- b1;
            subgraph cluster_a { a1; a2; }
            subgraph cluster_b { b1; b2; }
        }"""
        layout, _ = self._layout_and_json(src)
        for sub_name, sub in layout.graph.subgraphs.items():
            if sub_name.startswith("cluster"):
                bb_val = sub.attr_record.get("bb", "")
                assert bb_val, f"{sub_name}: bb attr not set"
                parts = [p.strip() for p in bb_val.split(",")]
                assert len(parts) == 4
                x1, y1, x2, y2 = (float(p) for p in parts)
                assert x2 > x1 and y2 > y1

    def test_cluster_overlap_removal(self):
        """Top-level cluster bboxes must not overlap after
        ``remove_cluster_overlap``.  Without this pass fdp's flat
        force model produces visually overlapping cluster boxes
        even after node-level overlap removal.

        Substitute for the C ``deriveGraph`` two-level pipeline
        (TODO §4.x Phase D).
        """
        # Three clusters with cross-cluster edges that would
        # naturally pull the clusters together; without overlap
        # removal their bboxes overlap.
        src = """graph G {
            a1 -- b1;
            l1 -- r1;
            subgraph cluster_a { a1; a2; }
            subgraph cluster_b { b1; b2; }
            subgraph cluster_l { l1; l2; }
            subgraph cluster_r { r1; r2; }
        }"""
        layout, _ = self._layout_and_json(src)
        cls = [c for c in layout._clusters
               if layout._cluster_parent[c.name] is None]
        # All pairs must be non-overlapping (or touching with
        # ≤ 1 pt slack from float rounding).
        for i in range(len(cls)):
            for j in range(i + 1, len(cls)):
                a, b = cls[i], cls[j]
                ax1, ay1, ax2, ay2 = a.bb
                bx1, by1, bx2, by2 = b.bb
                ox = min(ax2, bx2) - max(ax1, bx1)
                oy = min(ay2, by2) - max(ay1, by1)
                # Overlap means BOTH axes have positive overlap;
                # one axis ≤ 0 means they're separated.
                assert ox <= 1.0 or oy <= 1.0, (
                    f"{a.name} bb={a.bb} overlaps {b.name} bb={b.bb}: "
                    f"ox={ox:.2f} oy={oy:.2f}"
                )

    def test_derive_graph_nested_clusters(self):
        """deriveGraph two-level layout handles nested clusters
        (depth > 1).  ``cluster_inner`` sits inside
        ``cluster_outer``; both must end up with non-overlapping
        bboxes that respect the nesting (inner ⊂ outer).
        """
        src = """graph G {
            free -- outside;
            outside -- inside1;
            inside1 -- inside2;
            subgraph cluster_outer {
                outside;
                subgraph cluster_inner { inside1; inside2; }
            }
        }"""
        layout, _ = self._layout_and_json(src)
        cl_outer = next(c for c in layout._clusters
                        if c.name == "cluster_outer")
        cl_inner = next(c for c in layout._clusters
                        if c.name == "cluster_inner")
        assert layout._cluster_parent["cluster_inner"] == "cluster_outer"
        assert layout._cluster_level["cluster_outer"] == 1
        assert layout._cluster_level["cluster_inner"] == 2
        # Both bboxes computed.
        assert cl_outer.bb != (0.0, 0.0, 0.0, 0.0)
        assert cl_inner.bb != (0.0, 0.0, 0.0, 0.0)
        # cluster_inner must be enclosed by cluster_outer
        # (after deriveGraph translates inner → outer-local).
        ox1, oy1, ox2, oy2 = cl_outer.bb
        ix1, iy1, ix2, iy2 = cl_inner.bb
        margin = 1.0  # rounding tolerance
        assert ox1 - margin <= ix1
        assert oy1 - margin <= iy1
        assert ix2 <= ox2 + margin
        assert iy2 <= oy2 + margin
        # All inner members live inside inner bbox.
        for n in ("inside1", "inside2"):
            ln = layout.lnodes[n]
            assert ix1 - margin <= ln.x <= ix2 + margin
            assert iy1 - margin <= ln.y <= iy2 + margin

    def test_coordinated_escape_does_not_stack_overlapping_nodes(self):
        """When two intruders escape in the same direction (e.g.
        both pushed DOWN), they share a y-coordinate at the
        cluster boundary.  The pass must spread them along the
        perpendicular axis so they don't overlap each other.
        """
        src = """graph G {
            a -- b;
            a -- m1;
            b -- m2;
            subgraph cluster_middle { m1; m2; m1 -- m2; }
        }"""
        layout, _ = self._layout_and_json(src)
        a_ln = layout.lnodes["a"]
        b_ln = layout.lnodes["b"]
        # Combined half-widths plus a small clearance — assert
        # nodes don't physically overlap.
        dx = abs(a_ln.x - b_ln.x)
        dy = abs(a_ln.y - b_ln.y)
        req_x = (a_ln.width + b_ln.width) / 2.0
        req_y = (a_ln.height + b_ln.height) / 2.0
        # Either they're far enough apart in x OR in y.
        assert dx >= req_x - 0.5 or dy >= req_y - 0.5, (
            f"a and b overlap: ({a_ln.x:.1f},{a_ln.y:.1f}) vs "
            f"({b_ln.x:.1f},{b_ln.y:.1f}); dx={dx:.1f} "
            f"req_x={req_x:.1f} dy={dy:.1f} req_y={req_y:.1f}"
        )

    def test_connected_intruders_not_split_across_cluster(self):
        """When two free nodes are connected by an edge and both
        also connect to members of the same cluster, they must
        end up on the SAME side of that cluster — not opposite
        sides — so the edge between them doesn't traverse the
        cluster's interior.

        Regression for the visual bug where ``a--b`` ended up
        spanning the height of cluster_middle because ``a``
        escaped via +y and ``b`` via -y.  Both the simple-fix
        coordinated escape (replaced 2026-05-08) and the
        deriveGraph two-level layout enforce this property.
        """
        src = """graph G {
            a -- b;
            a -- m1;
            b -- m2;
            subgraph cluster_middle { m1; m2; m1 -- m2; }
        }"""
        layout, _ = self._layout_and_json(src)
        a_ln = layout.lnodes["a"]
        b_ln = layout.lnodes["b"]
        cl_middle = next(c for c in layout._clusters
                         if c.name == "cluster_middle")
        x1, y1, x2, y2 = cl_middle.bb
        assert not (x1 <= a_ln.x <= x2 and y1 <= a_ln.y <= y2), (
            f"a sits inside cluster_middle bb"
        )
        assert not (x1 <= b_ln.x <= x2 and y1 <= b_ln.y <= y2), (
            f"b sits inside cluster_middle bb"
        )
        # The straight line a→b must NOT cross the interior of
        # the cluster bbox.  If it does, a and b are on opposite
        # sides — the bug we're guarding against.  Use a simple
        # segment-vs-axis-aligned-bbox test: both endpoints must
        # be on the same side of at least one bbox edge.
        same_side_x = (a_ln.x < x1 and b_ln.x < x1) or (
            a_ln.x > x2 and b_ln.x > x2
        )
        same_side_y = (a_ln.y < y1 and b_ln.y < y1) or (
            a_ln.y > y2 and b_ln.y > y2
        )
        assert same_side_x or same_side_y, (
            f"line a→b crosses cluster_middle: "
            f"a=({a_ln.x:.1f},{a_ln.y:.1f}) "
            f"b=({b_ln.x:.1f},{b_ln.y:.1f}) "
            f"cluster_bb=({x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f})"
        )

    def test_nonmember_node_outside_cluster_bbox(self):
        """Free nodes (not in any cluster) must NOT sit visually
        inside another cluster's bbox after layout, even when
        they have edges into that cluster pulling them toward it.

        Regression for the cluster-rendering bug where ``a`` and
        ``b`` (free) appeared inside ``cluster_middle``'s rect
        because they were edge-connected to ``m1``/``m2``.
        """
        src = """graph G {
            a -- b;
            a -- m1;
            b -- m2;
            subgraph cluster_middle { m1; m2; m1 -- m2; }
        }"""
        layout, _ = self._layout_and_json(src)
        cl_middle = next(c for c in layout._clusters
                         if c.name == "cluster_middle")
        x1, y1, x2, y2 = cl_middle.bb

        for free_name in ("a", "b"):
            ln = layout.lnodes[free_name]
            # Node centre must be outside the cluster bbox.
            inside = (x1 <= ln.x <= x2) and (y1 <= ln.y <= y2)
            assert not inside, (
                f"free node {free_name!r} at ({ln.x:.1f},{ln.y:.1f}) "
                f"sits inside cluster_middle bb=({x1:.1f},{y1:.1f},"
                f"{x2:.1f},{y2:.1f})"
            )

    def test_edges_inside_subgraphs_drive_cohesion(self):
        """Edges declared inside a cluster subgraph must
        contribute to the force model.  Regression for the
        cluster-cohesion bug fixed by walking
        ``gather_all_subgraphs`` in fdp's edge enumeration."""
        src = """graph G {
            x -- y;
            subgraph cluster_chain {
                c1; c2; c3; c4; c5;
                c1 -- c2 -- c3 -- c4 -- c5;
            }
        }"""
        layout, _ = self._layout_and_json(src)
        # Each chain link should pull adjacent chain nodes near
        # each other.  Verify no chain pair is more than ~5 K
        # apart (K = default 21.6 pt → upper bound 108 pt).
        chain_pairs = [("c1", "c2"), ("c2", "c3"),
                       ("c3", "c4"), ("c4", "c5")]
        for t, h in chain_pairs:
            t_ln = layout.lnodes[t]
            h_ln = layout.lnodes[h]
            d2 = (t_ln.x - h_ln.x) ** 2 + (t_ln.y - h_ln.y) ** 2
            assert d2 < (5 * layout.K) ** 2, (
                f"{t}-{h} distance {d2 ** 0.5:.1f} > 5K "
                f"({5 * layout.K:.1f}) — internal cluster edges "
                f"likely not contributing to force model"
            )
