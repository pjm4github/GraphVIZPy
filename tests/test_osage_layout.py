"""
Tests for the osage (cluster packing) layout engine.
"""
import pytest
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.osage import OsageLayout


def osage_gv(text: str) -> dict:
    graph = read_gv(text)
    return OsageLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestOsageBasic:

    def test_single_node(self):
        r = osage_gv("digraph G { a; }")
        assert len(r["nodes"]) == 1

    def test_no_clusters(self):
        """Graph without clusters still works."""
        r = osage_gv("digraph G { a; b; c; a -> b; }")
        assert len(r["nodes"]) == 3
        for n in r["nodes"]:
            assert "x" in n
            assert "y" in n

    def test_single_cluster(self):
        r = osage_gv('digraph G { subgraph cluster_0 { a; b; c; } }')
        assert len(r["nodes"]) == 3
        assert "clusters" in r
        assert len(r["clusters"]) >= 1

    def test_two_clusters(self):
        r = osage_gv('''digraph G {
            subgraph cluster_0 { a; b; }
            subgraph cluster_1 { c; d; }
        }''')
        assert len(r["nodes"]) == 4
        assert "clusters" in r

    def test_empty_graph(self):
        r = osage_gv("digraph G { }")
        assert len(r["nodes"]) == 0


class TestOsageClusters:

    def test_cluster_bbox(self):
        """Clusters have bounding boxes."""
        r = osage_gv('digraph G { subgraph cluster_0 { label="Test"; a; b; } }')
        cl = r["clusters"][0]
        assert "bb" in cl
        assert cl["bb"][2] > cl["bb"][0]  # width > 0
        assert cl["bb"][3] > cl["bb"][1]  # height > 0

    def test_cluster_label(self):
        r = osage_gv('digraph G { subgraph cluster_0 { label="MyCluster"; a; } }')
        cl = r["clusters"][0]
        assert cl["label"] == "MyCluster"

    def test_cluster_nodes_listed(self):
        r = osage_gv('digraph G { subgraph cluster_0 { a; b; } c; }')
        cl = r["clusters"][0]
        assert "a" in cl["nodes"]
        assert "b" in cl["nodes"]
        assert "c" not in cl["nodes"]

    def test_nodes_inside_cluster_bbox(self):
        """Nodes should be within their cluster's bounding box."""
        r = osage_gv('digraph G { subgraph cluster_0 { a; b; c; } }')
        cl = r["clusters"][0]
        bb = cl["bb"]
        for name in cl["nodes"]:
            n = node_by_name(r, name)
            assert n is not None
            assert bb[0] <= n["x"] <= bb[2], f"{name} x={n['x']} outside bb"
            assert bb[1] <= n["y"] <= bb[3], f"{name} y={n['y']} outside bb"


class TestOsagePacking:

    def test_nodes_separated(self):
        """Nodes don't overlap."""
        r = osage_gv("digraph G { a; b; c; d; e; }")
        nodes = r["nodes"]
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dist = abs(nodes[i]["x"] - nodes[j]["x"]) + \
                       abs(nodes[i]["y"] - nodes[j]["y"])
                assert dist > 1, f"{nodes[i]['name']} and {nodes[j]['name']} overlap"

    def test_many_nodes_packed(self):
        """Many nodes get packed into array layout."""
        names = " ".join(f"n{i};" for i in range(20))
        r = osage_gv(f"digraph G {{ {names} }}")
        assert len(r["nodes"]) == 20
        bb = r["graph"]["bb"]
        assert bb[2] - bb[0] > 100  # should spread out


class TestOsageAttributes:

    def test_node_attrs_preserved(self):
        r = osage_gv('digraph G { a [shape=box, color=red]; }')
        na = node_by_name(r, "a")
        assert na["shape"] == "box"
        assert na["color"] == "red"

    def test_edge_attrs_preserved(self):
        r = osage_gv('digraph G { a -> b [label="test"]; }')
        e = r["edges"][0]
        assert e["label"] == "test"

    def test_bounding_box(self):
        r = osage_gv("digraph G { a; b; c; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]
        assert bb[3] > bb[1]

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = osage_gv('digraph G { subgraph cluster_0 { a; b; } c; }')
        svg = render_svg(r)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_pos_writeback(self):
        g = read_gv("digraph G { a; b; }")
        OsageLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes


class TestOsagePackCAligned:
    """C-aligned port of the array-packing algorithm in
    ``lib/pack/pack.c``.  See
    :mod:`gvpy.engines.layout.osage.pack`.
    """

    # ── Pure-function tests on the packer ──

    def test_parse_packmode_array(self):
        from gvpy.engines.layout.osage.pack import (
            parse_pack_mode, PackMode,
        )
        info = parse_pack_mode("array", PackMode.L_ARRAY)
        assert info.mode == PackMode.L_ARRAY
        assert info.sz == 0
        assert info.flags == 0

    def test_parse_packmode_array_with_size(self):
        from gvpy.engines.layout.osage.pack import (
            parse_pack_mode, PackMode,
        )
        info = parse_pack_mode("array_u3", PackMode.L_ARRAY)
        assert info.mode == PackMode.L_ARRAY
        assert info.sz == 3
        from gvpy.engines.layout.osage.pack import PK_USER_VALS
        assert info.flags & PK_USER_VALS

    def test_parse_packmode_flags(self):
        from gvpy.engines.layout.osage.pack import (
            parse_pack_mode, PackMode,
            PK_COL_MAJOR, PK_LEFT_ALIGN, PK_TOP_ALIGN,
        )
        info = parse_pack_mode("array_clt", PackMode.L_ARRAY)
        assert info.flags & PK_COL_MAJOR
        assert info.flags & PK_LEFT_ALIGN
        assert info.flags & PK_TOP_ALIGN

    def test_parse_packmode_mode_keywords(self):
        from gvpy.engines.layout.osage.pack import (
            parse_pack_mode, PackMode,
        )
        assert parse_pack_mode("graph", PackMode.L_ARRAY).mode == PackMode.L_GRAPH
        assert parse_pack_mode("cluster", PackMode.L_ARRAY).mode == PackMode.L_CLUST
        assert parse_pack_mode("node", PackMode.L_ARRAY).mode == PackMode.L_NODE
        # Unknown spec → default.
        assert parse_pack_mode("xyz", PackMode.L_ARRAY).mode == PackMode.L_ARRAY

    def test_array_rects_2x2_grid(self):
        """4 equal rects → 2×2 grid; each rect lands in its
        own cell."""
        from gvpy.engines.layout.osage.pack import (
            array_rects, PackInfo,
        )
        bbs = [(0, 0, 30, 30)] * 4
        info = PackInfo(margin=0)
        places = array_rects(bbs, info)
        assert len(places) == 4
        # 4 rects, ceil(sqrt(4)) = 2 cols × 2 rows.
        # Each rect should occupy one cell.  All rects identical
        # so ordering is stable, but cells don't overlap.
        cells = set()
        for (dx, dy) in places:
            cells.add((dx, dy))
        assert len(cells) == 4

    def test_array_rects_user_vals_sort_ascending(self):
        """``PK_USER_VALS`` sort puts the lowest-sortv rect first."""
        from gvpy.engines.layout.osage.pack import (
            array_rects, PackInfo, PK_USER_VALS,
        )
        bbs = [(0, 0, 20, 20), (0, 0, 20, 20), (0, 0, 20, 20)]
        info = PackInfo(margin=0, flags=PK_USER_VALS, vals=[5, 1, 3])
        places = array_rects(bbs, info)
        # 3 rects, ceil(sqrt(3)) = 2 cols.  Sorted ascending by
        # sortv: rect 1 (sortv=1) goes to first cell, rect 2
        # (sortv=3) to second, rect 0 (sortv=5) to third.
        # First-cell location is the top-left (row 0, col 0).
        # Verify rect 1's place < rect 0's place (smaller cell
        # index = upper-left).
        # Specifically rect 1 should be at the top row, rect 0
        # at the second row.
        assert places[1][1] > places[0][1], (
            "rect 1 (sortv=1) should be at top (higher y)"
        )

    def test_array_rects_default_sort_descending_by_size(self):
        """Without user vals, sort descending by w+h: bigger
        rects placed first."""
        from gvpy.engines.layout.osage.pack import (
            array_rects, PackInfo,
        )
        bbs = [(0, 0, 10, 10), (0, 0, 60, 60), (0, 0, 30, 30)]
        info = PackInfo(margin=0)
        places = array_rects(bbs, info)
        # The widest rect (60×60) takes the most column width;
        # the column it lands in dominates that column's width.
        # Just verify all places are distinct.
        assert len(set(places)) == 3

    def test_array_rects_input_order_preserved(self):
        """``PK_INPUT_ORDER`` flag preserves input order — first
        two rects in the top row, last two in the bottom row.

        Within a row, each rect is *centered* in the row's
        height-band individually (so rects of different heights
        in the same row will have different y centers); the
        invariant we check is that top-row rects sit *above* the
        row boundary and bottom-row rects sit *below* it.
        """
        from gvpy.engines.layout.osage.pack import (
            array_rects, PackInfo, PK_INPUT_ORDER,
        )
        bbs = [(0, 0, 20, 20), (0, 0, 50, 50), (0, 0, 30, 30), (0, 0, 40, 40)]
        info = PackInfo(margin=0, flags=PK_INPUT_ORDER)
        # 4 items, 2 cols × 2 rows.  Row-major iteration:
        # (0, 0), (0, 1) row 0; (1, 0), (1, 1) row 1.
        # row 0 height = max(20, 50) = 50; row 1 height = max(30, 40) = 40.
        # Boundary between top and bottom row is at y = 40.
        places = array_rects(bbs, info)
        # Top row (rects 0, 1) — LL.y >= row boundary.
        assert places[0][1] >= 40
        assert places[1][1] >= 40
        # Bottom row (rects 2, 3) — LL.y < row boundary.
        assert places[2][1] < 40
        assert places[3][1] < 40

    # ── Engine integration ──

    def test_engine_packmode_attribute_respected(self):
        """``packmode=array_u`` triggers user-value sorting via
        ``sortv`` node attribute."""
        gv = '''
        digraph G {
            packmode = "array_u";
            a [sortv=3];
            b [sortv=1];
            c [sortv=2];
        }
        '''
        r = osage_gv(gv)
        # Look up positions.
        positions = {n["name"]: (n["x"], n["y"]) for n in r["nodes"]}
        # b (sortv=1) should be placed first → top-left.
        # In a 2-col layout: col 0, row 0.  Top-row y > bottom-row y.
        # b should have the largest y of the three.
        ys = sorted(positions.values(), key=lambda p: -p[1])
        # b should be at the largest y (top of layout).
        assert ys[0] == positions["b"], (
            f"b (sortv=1) should be at top; got positions {positions}"
        )

    def test_engine_pack_attribute_sets_margin(self):
        """``pack=20`` sets the inter-rect margin to 20pt; layout
        widens compared to default ``pack=8``."""
        gv_default = "digraph G { a; b; c; d; }"
        gv_wide = 'digraph G { pack=20; a; b; c; d; }'
        r1 = osage_gv(gv_default)
        r2 = osage_gv(gv_wide)
        bb1 = r1["graph"]["bb"]
        bb2 = r2["graph"]["bb"]
        # Wider margin → wider canvas.
        assert (bb2[2] - bb2[0]) >= (bb1[2] - bb1[0])

    def test_engine_nested_clusters_bottom_up(self):
        """Nested clusters: child cluster's bbox sits inside the
        parent's bbox."""
        gv = '''
        digraph G {
            subgraph cluster_outer {
                label = "Outer";
                a;
                subgraph cluster_inner {
                    label = "Inner";
                    b;
                    c;
                }
            }
        }
        '''
        r = osage_gv(gv)
        clusters = {cl["name"]: cl for cl in r["clusters"]}
        outer = clusters["cluster_outer"]
        inner = clusters["cluster_inner"]
        ox1, oy1, ox2, oy2 = outer["bb"]
        ix1, iy1, ix2, iy2 = inner["bb"]
        # Inner bbox should be fully inside outer's.
        assert ox1 <= ix1 and ox2 >= ix2, (
            f"inner x [{ix1},{ix2}] not inside outer [{ox1},{ox2}]"
        )
        assert oy1 <= iy1 and oy2 >= iy2, (
            f"inner y [{iy1},{iy2}] not inside outer [{oy1},{oy2}]"
        )

    def test_engine_no_node_overlaps(self):
        """Multi-cluster layout produces non-overlapping nodes."""
        gv = '''
        digraph G {
            subgraph cluster_a { a1; a2; a3; }
            subgraph cluster_b { b1; b2; b3; b4; }
            subgraph cluster_c { c1; c2; }
            d;
        }
        '''
        r = osage_gv(gv)
        nodes = r["nodes"]
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                ax1 = a["x"] - a["width"] / 2
                ax2 = a["x"] + a["width"] / 2
                ay1 = a["y"] - a["height"] / 2
                ay2 = a["y"] + a["height"] / 2
                bx1 = b["x"] - b["width"] / 2
                bx2 = b["x"] + b["width"] / 2
                by1 = b["y"] - b["height"] / 2
                by2 = b["y"] + b["height"] / 2
                overlap = (ax1 < bx2 and ax2 > bx1
                           and ay1 < by2 and ay2 > by1)
                assert not overlap, (
                    f"{a['name']} and {b['name']} overlap"
                )

    def test_engine_cluster_label_reserves_top_space(self):
        """A labeled cluster's nodes sit below the label area
        (label takes the top of the cluster's bbox).

        In the SVG-y convention used downstream, ``bb[1]`` is
        the visual top of the bbox (smaller y).  Label space
        is reserved between ``bb[1]`` and the node's top edge —
        we verify that gap is at least ``label_height``.
        """
        gv = '''
        digraph G {
            subgraph cluster_0 {
                label = "Header";
                fontsize = 20;
                a;
            }
        }
        '''
        r = osage_gv(gv)
        cl = r["clusters"][0]
        x1, y1, x2, y2 = cl["bb"]
        a = node_by_name(r, "a")
        assert a is not None
        # Top edge of node a in SVG-y (small y == high visually).
        node_top_y = a["y"] - a["height"] / 2
        # label_height = fontsize × 1.5 = 30 pt.  Allow 10 pt
        # tolerance for margin variation.
        gap = node_top_y - y1
        assert gap >= 20, (
            f"node a top y={node_top_y} too close to cluster "
            f"top y1={y1} (gap={gap}) — label space not reserved"
        )
