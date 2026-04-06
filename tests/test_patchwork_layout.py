"""
Tests for the patchwork (treemap) layout engine.
"""
import pytest
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.patchwork import PatchworkLayout


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
