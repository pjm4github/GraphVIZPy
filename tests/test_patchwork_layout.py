"""
Tests for the patchwork (treemap) layout engine.
"""
import pytest
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.patchwork import PatchworkLayout


def pw_gv(text: str) -> dict:
    graph = read_gv(text)
    return PatchworkLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestPatchworkBasic:

    def test_single_node(self):
        r = pw_gv("digraph G { a; }")
        assert len(r["nodes"]) == 1

    def test_multiple_nodes(self):
        r = pw_gv("digraph G { a; b; c; d; }")
        assert len(r["nodes"]) == 4
        for n in r["nodes"]:
            assert n["width"] > 0
            assert n["height"] > 0

    def test_empty(self):
        r = pw_gv("digraph G { }")
        assert len(r["nodes"]) == 0

    def test_with_cluster(self):
        r = pw_gv('digraph G { subgraph cluster_0 { a; b; } c; }')
        assert len(r["nodes"]) == 3
        assert "clusters" in r


class TestPatchworkAreas:

    def test_area_attribute(self):
        """Nodes with larger area get larger rectangles."""
        r = pw_gv('digraph G { a[area=4]; b[area=1]; }')
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        area_a = na["width"] * na["height"]
        area_b = nb["width"] * nb["height"]
        assert area_a > area_b * 2  # 4x area should be much bigger

    def test_equal_areas(self):
        """Equal-area nodes get similar rectangles."""
        r = pw_gv("digraph G { a; b; c; d; }")
        areas = [node_by_name(r, n)["width"] * node_by_name(r, n)["height"]
                 for n in "abcd"]
        avg = sum(areas) / 4
        for a in areas:
            assert a == pytest.approx(avg, rel=0.3)

    def test_default_area(self):
        """Default area is 1.0."""
        r = pw_gv("digraph G { a; }")
        na = node_by_name(r, "a")
        assert na["width"] > 0
        assert na["height"] > 0


class TestPatchworkClusters:

    def test_cluster_bbox(self):
        r = pw_gv('digraph G { subgraph cluster_0 { a; b; } }')
        cl = r["clusters"][0]
        assert cl["bb"][2] > cl["bb"][0]
        assert cl["bb"][3] > cl["bb"][1]

    def test_cluster_label(self):
        r = pw_gv('digraph G { subgraph cluster_0 { label="Test"; a; } }')
        cl = r["clusters"][0]
        assert cl["label"] == "Test"

    def test_nested_clusters(self):
        r = pw_gv('''digraph G {
            subgraph cluster_outer {
                subgraph cluster_inner { a; b; }
                c;
            }
        }''')
        assert len(r["nodes"]) == 3
        names = {cl["name"] for cl in r["clusters"]}
        assert "cluster_outer" in names
        assert "cluster_inner" in names

    def test_nodes_in_cluster(self):
        r = pw_gv('digraph G { subgraph cluster_0 { a; b; } c; }')
        cl = r["clusters"][0]
        assert "a" in cl["nodes"]
        assert "b" in cl["nodes"]
        assert "c" not in cl["nodes"]


class TestPatchworkAttributes:

    def test_node_attrs(self):
        r = pw_gv('digraph G { a [color=red]; }')
        na = node_by_name(r, "a")
        assert na["color"] == "red"

    def test_bounding_box(self):
        r = pw_gv("digraph G { a; b; c; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]
        assert bb[3] > bb[1]

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = pw_gv('digraph G { subgraph cluster_0 { a; b; } c; }')
        svg = render_svg(r)
        assert "<svg" in svg

    def test_pos_writeback(self):
        g = read_gv("digraph G { a; b; }")
        PatchworkLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes


class TestPatchworkSquarification:

    def test_aspect_ratio_reasonable(self):
        """Squarified treemap should produce reasonable aspect ratios."""
        r = pw_gv("digraph G { a; b; c; d; e; f; g; h; }")
        for n in r["nodes"]:
            ratio = max(n["width"], n["height"]) / max(min(n["width"], n["height"]), 0.1)
            assert ratio < 10, f"Node {n['name']} has bad aspect ratio {ratio}"

    def test_no_overlap(self):
        """Treemap rectangles should not overlap."""
        r = pw_gv("digraph G { a; b; c; d; }")
        nodes = r["nodes"]
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                # Check for overlap using rectangle intersection
                ax1 = a["x"] - a["width"] / 2
                ax2 = a["x"] + a["width"] / 2
                ay1 = a["y"] - a["height"] / 2
                ay2 = a["y"] + a["height"] / 2
                bx1 = b["x"] - b["width"] / 2
                bx2 = b["x"] + b["width"] / 2
                by1 = b["y"] - b["height"] / 2
                by2 = b["y"] + b["height"] / 2
                overlap_x = max(0, min(ax2, bx2) - max(ax1, bx1))
                overlap_y = max(0, min(ay2, by2) - max(ay1, by1))
                overlap_area = overlap_x * overlap_y
                assert overlap_area < 1, \
                    f"{a['name']} and {b['name']} overlap by {overlap_area}"


class TestPatchworkTreeMapCAligned:
    """C-aligned port of ``lib/patchwork/tree_map.c`` —
    see :mod:`gvpy.engines.layout.patchwork.tree_map`.
    """

    def test_4_equal_rects_2x2_grid(self):
        """4 equal areas → 2×2 grid filling the whole rectangle."""
        from gvpy.engines.layout.patchwork.tree_map import (
            tree_map, Rectangle,
        )
        fill = Rectangle(cx=50, cy=50, sw=100, sh=100)
        recs = tree_map([2500.0] * 4, fill)
        assert recs is not None
        assert len(recs) == 4
        for r in recs:
            assert abs(r.sw - 50) < 0.01
            assert abs(r.sh - 50) < 0.01
        # All 4 cells should be at one of the corners (centers
        # 25 or 75 in x, 25 or 75 in y).
        centers = sorted([(round(r.cx), round(r.cy)) for r in recs])
        assert centers == [(25, 25), (25, 75), (75, 25), (75, 75)]

    def test_total_area_preserved(self):
        """Sum of output rect areas == sum of input areas."""
        from gvpy.engines.layout.patchwork.tree_map import (
            tree_map, Rectangle,
        )
        areas = [5000.0, 2000.0, 1500.0, 1500.0]
        fill = Rectangle(cx=50, cy=50, sw=100, sh=100)
        recs = tree_map(areas, fill)
        total = sum(r.sw * r.sh for r in recs)
        assert abs(total - sum(areas)) < 1.0

    def test_overflow_returns_none(self):
        """Areas summing more than fillrec area → returns None."""
        from gvpy.engines.layout.patchwork.tree_map import (
            tree_map, Rectangle,
        )
        fill = Rectangle(cx=10, cy=10, sw=20, sh=20)  # area 400
        recs = tree_map([500.0], fill)
        assert recs is None

    def test_aspect_ratio_squarified(self):
        """Rectangles should have aspect ratios closer to 1 than
        a naive horizontal strip layout would give."""
        from gvpy.engines.layout.patchwork.tree_map import (
            tree_map, Rectangle,
        )
        # 16 identical areas in a 16×1 strip: naive would give
        # 16:1 aspect.  Squarified should be closer to 1:1.
        # Use a fill of side 4 (area 16) with 16 unit areas.
        fill = Rectangle(cx=2, cy=2, sw=4, sh=4)
        recs = tree_map([1.0] * 16, fill)
        assert recs is not None
        worst = max(max(r.sw / r.sh, r.sh / r.sw) for r in recs)
        assert worst < 2.0, (
            f"worst aspect ratio {worst:.2f} too elongated"
        )

    def test_single_rect_fills(self):
        """1 area → 1 rect equal to fillrec."""
        from gvpy.engines.layout.patchwork.tree_map import (
            tree_map, Rectangle,
        )
        fill = Rectangle(cx=10, cy=10, sw=20, sh=15)
        recs = tree_map([300.0], fill)
        assert recs is not None
        r = recs[0]
        assert abs(r.cx - 10) < 0.5
        assert abs(r.cy - 10) < 0.5
        assert abs(r.sw - 20) < 0.5
        assert abs(r.sh - 15) < 0.5

    def test_empty_input(self):
        from gvpy.engines.layout.patchwork.tree_map import (
            tree_map, Rectangle,
        )
        fill = Rectangle(cx=10, cy=10, sw=20, sh=20)
        recs = tree_map([], fill)
        assert recs == []


class TestPatchworkCAligned:
    """C-aligned engine integration."""

    def test_node_area_proportional(self):
        """Nodes with area=4 should occupy ~4× the area of
        nodes with area=1."""
        gv = '''
        digraph G {
            a [area=4];
            b [area=1];
            c [area=1];
            d [area=1];
            e [area=1];
        }
        '''
        r = pw_gv(gv)
        nodes = {n["name"]: n for n in r["nodes"]}
        area_a = nodes["a"]["width"] * nodes["a"]["height"]
        area_b = nodes["b"]["width"] * nodes["b"]["height"]
        # Allow ±50% slop for squarification rounding.
        ratio = area_a / area_b
        assert 2.5 < ratio < 5.5, f"area ratio {ratio:.2f}"

    def test_nested_clusters_contain_children(self):
        """Cluster bbox encloses every direct-member node."""
        gv = '''
        digraph G {
            subgraph cluster_outer {
                a; b; c;
                subgraph cluster_inner {
                    x; y;
                }
            }
        }
        '''
        r = pw_gv(gv)
        clusters = {cl["name"]: cl for cl in r["clusters"]}
        nodes_d = {n["name"]: n for n in r["nodes"]}
        outer = clusters["cluster_outer"]
        inner = clusters["cluster_inner"]
        ox1, oy1, ox2, oy2 = outer["bb"]
        ix1, iy1, ix2, iy2 = inner["bb"]
        # Inner inside outer.
        assert ox1 - 1 <= ix1 and ix2 <= ox2 + 1
        assert oy1 - 1 <= iy1 and iy2 <= oy2 + 1
        # x and y nodes are inside inner.
        for nm in ("x", "y"):
            n = nodes_d[nm]
            assert ix1 <= n["x"] <= ix2
            assert iy1 <= n["y"] <= iy2

    def test_no_overlap_squarified(self):
        """Squarified treemap should have non-overlapping leaf
        rectangles."""
        gv = '''
        digraph G {
            a [area=5];
            b [area=3];
            c [area=2];
            d [area=2];
            e [area=1];
            f [area=1];
        }
        '''
        r = pw_gv(gv)
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
                overlap = (
                    ax1 < bx2 - 1 and ax2 > bx1 + 1
                    and ay1 < by2 - 1 and ay2 > by1 + 1
                )
                assert not overlap, (
                    f"{a['name']} overlaps {b['name']}"
                )

    def test_single_node_works(self):
        r = pw_gv("digraph G { a; }")
        assert len(r["nodes"]) == 1
        n = r["nodes"][0]
        assert n["width"] > 0
        assert n["height"] > 0

    def test_empty_graph(self):
        r = pw_gv("digraph G { }")
        assert len(r["nodes"]) == 0
