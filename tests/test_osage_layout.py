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
