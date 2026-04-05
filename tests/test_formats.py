"""
Tests for graph interchange formats: DOT writer, JSON reader/writer, GXL reader/writer.

Covers: serialization, deserialization, roundtrip, attributes, subgraphs,
directed/undirected, strict mode, edge cases.
"""
import json
import pytest
from pathlib import Path
from xml.etree import ElementTree as ET

from gvpy.core.graph import Graph
from gvpy.grammar.gv_writer import write_gv, write_gv_file
from gvpy.grammar.gv_reader import read_gv
from gvpy.render.json_io import (
    write_json, write_json0, read_json, read_json_file, write_json_file,
)
from gvpy.render.gxl_io import (
    write_gxl, read_gxl, read_gxl_all, read_gxl_file, write_gxl_file,
)

TEST_DATA = Path(__file__).parent.parent / "test_data"


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def simple_digraph():
    """A simple directed graph with attributes."""
    g = Graph("TestGraph", directed=True)
    g.method_init()
    g.set_graph_attr("rankdir", "LR")
    a = g.add_node("A")
    a.agset("label", "Node A")
    a.agset("shape", "box")
    a.agset("color", "red")
    b = g.add_node("B")
    b.agset("label", "Node B")
    b.agset("shape", "ellipse")
    e = g.add_edge("A", "B")
    e.agset("label", "connects")
    e.agset("style", "dashed")
    yield g
    g.close()


@pytest.fixture
def undirected_graph():
    """An undirected graph."""
    g = Graph("UndirGraph", directed=False)
    g.method_init()
    g.add_node("X")
    g.add_node("Y")
    g.add_node("Z")
    g.add_edge("X", "Y")
    g.add_edge("Y", "Z")
    yield g
    g.close()


@pytest.fixture
def graph_with_subgraphs():
    """A graph with clusters and subgraphs."""
    g = Graph("Clustered", directed=True)
    g.method_init()
    sub = g.create_subgraph("cluster_0")
    sub.attr_record["label"] = "Cluster 0"
    sub.add_node("a")
    sub.add_node("b")
    g.add_node("c")
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    yield g
    g.close()


@pytest.fixture
def strict_graph():
    """A strict graph (no duplicate edges)."""
    g = Graph("Strict", directed=True, strict=True)
    g.method_init()
    g.add_node("P")
    g.add_node("Q")
    g.add_edge("P", "Q")
    yield g
    g.close()


@pytest.fixture
def complex_graph():
    """A more complex graph with nested subgraphs and many attributes."""
    g = Graph("Complex", directed=True)
    g.method_init()
    g.set_graph_attr("rankdir", "TB")
    g.set_graph_attr("bgcolor", "white")

    # Nested subgraphs
    outer = g.create_subgraph("cluster_outer")
    outer.attr_record["label"] = "Outer"
    inner = outer.create_subgraph("cluster_inner")
    inner.attr_record["label"] = "Inner"

    n1 = inner.add_node("n1")
    n1.agset("shape", "diamond")
    n1.agset("fillcolor", "lightyellow")
    n1.agset("style", "filled")

    n2 = outer.add_node("n2")
    n2.agset("shape", "box")

    n3 = g.add_node("n3")
    n3.agset("shape", "ellipse")

    e1 = g.add_edge("n1", "n2")
    e1.agset("color", "blue")
    e1.agset("penwidth", "2")

    e2 = g.add_edge("n2", "n3")
    e2.agset("style", "dotted")

    yield g
    g.close()


# ═══════════════════════════════════════════════════════════════
#  DOT Writer
# ═══════════════════════════════════════════════════════════════


class TestDotWriter:

    def test_simple_digraph(self, simple_digraph):
        """DOT output contains digraph header and nodes."""
        dot = write_gv(simple_digraph)
        assert "digraph" in dot
        assert "TestGraph" in dot
        assert "A" in dot
        assert "B" in dot
        assert "->" in dot

    def test_undirected(self, undirected_graph):
        """Undirected graph uses 'graph' keyword and '--' edges."""
        dot = write_gv(undirected_graph)
        assert dot.startswith("graph ")
        assert "--" in dot
        assert "->" not in dot

    def test_strict_keyword(self, strict_graph):
        """Strict graph includes 'strict' keyword."""
        dot = write_gv(strict_graph)
        assert dot.startswith("strict digraph")

    def test_node_attributes(self, simple_digraph):
        """Node attributes appear in DOT output."""
        dot = write_gv(simple_digraph)
        assert 'shape=box' in dot
        assert 'color=red' in dot
        assert '"Node A"' in dot

    def test_edge_attributes(self, simple_digraph):
        """Edge attributes appear in DOT output."""
        dot = write_gv(simple_digraph)
        assert "dashed" in dot
        assert "connects" in dot

    def test_graph_attributes(self, simple_digraph):
        """Graph-level attributes appear in DOT output."""
        dot = write_gv(simple_digraph)
        assert "rankdir" in dot
        assert "LR" in dot

    def test_subgraphs(self, graph_with_subgraphs):
        """Subgraphs appear as nested blocks."""
        dot = write_gv(graph_with_subgraphs)
        assert "subgraph" in dot
        assert "cluster_0" in dot
        assert '"Cluster 0"' in dot

    def test_nested_subgraphs(self, complex_graph):
        """Nested subgraphs are written correctly."""
        dot = write_gv(complex_graph)
        assert "cluster_outer" in dot
        assert "cluster_inner" in dot
        assert "Outer" in dot
        assert "Inner" in dot

    def test_quoting_keywords(self):
        """Node names that are DOT keywords get quoted."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_node("node")
        g.add_node("edge")
        dot = write_gv(g)
        assert '"node"' in dot
        assert '"edge"' in dot
        g.close()

    def test_quoting_special_chars(self):
        """Node names with spaces or special chars get quoted."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_node("my node")
        g.add_node("hello world")
        dot = write_gv(g)
        assert '"my node"' in dot
        assert '"hello world"' in dot
        g.close()

    def test_write_gv_file(self, simple_digraph, tmp_path):
        """write_dot_file writes to disk."""
        path = tmp_path / "test.dot"
        write_gv_file(simple_digraph, str(path))
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "digraph" in content

    def test_empty_graph(self):
        """Empty graph produces minimal DOT."""
        g = Graph("Empty", directed=True)
        g.method_init()
        dot = write_gv(g)
        assert "digraph Empty" in dot
        assert "{" in dot
        assert "}" in dot
        g.close()


class TestDotRoundtrip:

    def test_roundtrip_simple(self, simple_digraph):
        """DOT write → read preserves graph structure."""
        dot = write_gv(simple_digraph)
        g2 = read_gv(dot)
        assert g2.name == "TestGraph"
        assert g2.directed is True
        assert "A" in g2.nodes
        assert "B" in g2.nodes
        assert len(g2.edges) == 1
        g2.close()

    def test_roundtrip_attributes(self, simple_digraph):
        """DOT roundtrip preserves node attributes."""
        dot = write_gv(simple_digraph)
        g2 = read_gv(dot)
        assert g2.nodes["A"].attributes.get("shape") == "box"
        assert g2.nodes["A"].attributes.get("color") == "red"
        g2.close()

    def test_roundtrip_undirected(self, undirected_graph):
        """DOT roundtrip preserves undirected mode."""
        dot = write_gv(undirected_graph)
        g2 = read_gv(dot)
        assert g2.directed is False
        assert "X" in g2.nodes
        assert "Y" in g2.nodes
        g2.close()

    def test_roundtrip_subgraphs(self, graph_with_subgraphs):
        """DOT roundtrip preserves subgraph structure."""
        dot = write_gv(graph_with_subgraphs)
        g2 = read_gv(dot)
        assert "cluster_0" in g2.subgraphs
        assert "a" in g2.subgraphs["cluster_0"].nodes
        g2.close()

    def test_roundtrip_strict(self, strict_graph):
        """DOT roundtrip preserves strict flag."""
        dot = write_gv(strict_graph)
        g2 = read_gv(dot)
        assert g2.strict is True
        g2.close()

    def test_roundtrip_complex(self, complex_graph):
        """DOT roundtrip preserves complex nested structures."""
        from gvpy.core.graph import gather_all_edges
        dot = write_gv(complex_graph)
        g2 = read_gv(dot)
        assert "n1" in g2.nodes
        assert "n2" in g2.nodes
        assert "n3" in g2.nodes
        all_edges = gather_all_edges(g2)
        assert len(all_edges) == 2
        g2.close()


# ═══════════════════════════════════════════════════════════════
#  JSON Writer
# ═══════════════════════════════════════════════════════════════


class TestJsonWriter:

    def test_json0_structure(self, simple_digraph):
        """json0 output has correct top-level structure."""
        text = write_json0(simple_digraph)
        data = json.loads(text)
        assert data["name"] == "TestGraph"
        assert data["directed"] is True
        assert data["strict"] is False
        assert "nodes" in data
        assert "edges" in data
        assert "objects" in data

    def test_json0_nodes(self, simple_digraph):
        """json0 output includes all nodes with attributes."""
        text = write_json0(simple_digraph)
        data = json.loads(text)
        nodes = data["nodes"]
        assert len(nodes) == 2
        names = [n["name"] for n in nodes]
        assert "A" in names
        assert "B" in names
        node_a = next(n for n in nodes if n["name"] == "A")
        assert node_a["shape"] == "box"
        assert node_a["color"] == "red"

    def test_json0_edges(self, simple_digraph):
        """json0 output includes edges with _gvid indices."""
        text = write_json0(simple_digraph)
        data = json.loads(text)
        edges = data["edges"]
        assert len(edges) == 1
        e = edges[0]
        assert "tail" in e
        assert "head" in e
        assert isinstance(e["tail"], int)
        assert isinstance(e["head"], int)

    def test_json0_edge_attrs(self, simple_digraph):
        """json0 output includes edge attributes."""
        text = write_json0(simple_digraph)
        data = json.loads(text)
        e = data["edges"][0]
        assert e.get("label") == "connects"
        assert e.get("style") == "dashed"

    def test_json0_subgraphs(self, graph_with_subgraphs):
        """json0 output includes subgraphs in objects array."""
        text = write_json0(graph_with_subgraphs)
        data = json.loads(text)
        assert len(data["objects"]) >= 1
        obj = data["objects"][0]
        assert obj["name"] == "cluster_0"
        assert "nodes" in obj

    def test_json0_no_layout(self, simple_digraph):
        """json0 output has no pos/width/height fields."""
        text = write_json0(simple_digraph)
        data = json.loads(text)
        for n in data["nodes"]:
            assert "pos" not in n
            assert "width" not in n
            assert "height" not in n

    def test_json_with_layout(self, simple_digraph):
        """json output includes layout data when provided."""
        from gvpy.engines.dot import DotLayout
        result = DotLayout(simple_digraph).layout()
        text = write_json(simple_digraph, layout_result=result)
        data = json.loads(text)
        # At least some nodes should have pos
        nodes_with_pos = [n for n in data["nodes"] if "pos" in n]
        assert len(nodes_with_pos) > 0
        assert "bb" in data

    def test_json_graph_attrs(self, simple_digraph):
        """json output includes graph-level attributes."""
        text = write_json0(simple_digraph)
        data = json.loads(text)
        assert data.get("rankdir") == "LR"

    def test_json_file_write(self, simple_digraph, tmp_path):
        """write_json_file writes valid JSON to disk."""
        path = tmp_path / "test.json"
        write_json_file(simple_digraph, str(path))
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["name"] == "TestGraph"

    def test_json_strict(self, strict_graph):
        """Strict flag is preserved in JSON output."""
        text = write_json0(strict_graph)
        data = json.loads(text)
        assert data["strict"] is True

    def test_json_undirected(self, undirected_graph):
        """Undirected graph has directed=false in JSON."""
        text = write_json0(undirected_graph)
        data = json.loads(text)
        assert data["directed"] is False

    def test_json_nested_subgraphs(self, complex_graph):
        """Nested subgraphs appear in objects array."""
        text = write_json0(complex_graph)
        data = json.loads(text)
        names = [obj["name"] for obj in data["objects"]]
        assert "cluster_outer" in names
        assert "cluster_inner" in names


# ═══════════════════════════════════════════════════════════════
#  JSON Reader
# ═══════════════════════════════════════════════════════════════


class TestJsonReader:

    def test_read_json_basic(self):
        """read_json creates graph from JSON text."""
        text = json.dumps({
            "name": "G",
            "directed": True,
            "strict": False,
            "_subgraph_cnt": 0,
            "objects": [],
            "nodes": [
                {"_gvid": 0, "name": "A", "label": "A"},
                {"_gvid": 1, "name": "B", "label": "B"},
            ],
            "edges": [
                {"_gvid": 0, "tail": 0, "head": 1},
            ],
        })
        g = read_json(text)
        assert g.name == "G"
        assert g.directed is True
        assert "A" in g.nodes
        assert "B" in g.nodes
        assert len(g.edges) == 1
        g.close()

    def test_read_json_attrs(self):
        """read_json preserves node and edge attributes."""
        text = json.dumps({
            "name": "G",
            "directed": True,
            "strict": False,
            "_subgraph_cnt": 0,
            "objects": [],
            "nodes": [
                {"_gvid": 0, "name": "A", "shape": "box", "color": "red"},
                {"_gvid": 1, "name": "B"},
            ],
            "edges": [
                {"_gvid": 0, "tail": 0, "head": 1, "style": "dashed"},
            ],
        })
        g = read_json(text)
        assert g.nodes["A"].attributes.get("shape") == "box"
        assert g.nodes["A"].attributes.get("color") == "red"
        edge = list(g.edges.values())[0]
        assert edge.attributes.get("style") == "dashed"
        g.close()

    def test_read_json_subgraphs(self):
        """read_json creates subgraphs from objects array."""
        text = json.dumps({
            "name": "G",
            "directed": True,
            "strict": False,
            "_subgraph_cnt": 1,
            "objects": [
                {"_gvid": 0, "name": "cluster_0", "label": "C0",
                 "nodes": [0, 1], "edges": []},
            ],
            "nodes": [
                {"_gvid": 0, "name": "A"},
                {"_gvid": 1, "name": "B"},
                {"_gvid": 2, "name": "C"},
            ],
            "edges": [],
        })
        g = read_json(text)
        assert "cluster_0" in g.subgraphs
        sub = g.subgraphs["cluster_0"]
        assert "A" in sub.nodes
        assert "B" in sub.nodes
        g.close()

    def test_read_json_file(self):
        """read_json_file reads from test_data/sample.json."""
        from gvpy.core.graph import gather_all_edges
        g = read_json_file(TEST_DATA / "sample.json")
        assert g.name == "SampleJSON"
        assert g.directed is True
        assert "start" in g.nodes
        assert "process" in g.nodes
        assert "decide" in g.nodes
        assert "end" in g.nodes
        # Edges may be distributed across root and subgraphs
        all_edges = gather_all_edges(g)
        assert len(all_edges) == 4
        # Check subgraph
        assert "cluster_0" in g.subgraphs
        g.close()

    def test_read_json_graph_attrs(self):
        """read_json preserves graph-level attributes."""
        text = json.dumps({
            "name": "G",
            "directed": True,
            "strict": False,
            "rankdir": "LR",
            "bgcolor": "white",
            "_subgraph_cnt": 0,
            "objects": [],
            "nodes": [],
            "edges": [],
        })
        g = read_json(text)
        assert g.get_graph_attr("rankdir") == "LR"
        assert g.get_graph_attr("bgcolor") == "white"
        g.close()

    def test_read_json_undirected(self):
        """read_json handles undirected graphs."""
        text = json.dumps({
            "name": "G",
            "directed": False,
            "strict": False,
            "_subgraph_cnt": 0,
            "objects": [],
            "nodes": [
                {"_gvid": 0, "name": "A"},
                {"_gvid": 1, "name": "B"},
            ],
            "edges": [
                {"_gvid": 0, "tail": 0, "head": 1},
            ],
        })
        g = read_json(text)
        assert g.directed is False
        g.close()


class TestJsonRoundtrip:

    def test_roundtrip_simple(self, simple_digraph):
        """JSON write → read preserves structure."""
        text = write_json0(simple_digraph)
        g2 = read_json(text)
        assert g2.name == simple_digraph.name
        assert g2.directed == simple_digraph.directed
        assert set(g2.nodes.keys()) == set(simple_digraph.nodes.keys())
        assert len(g2.edges) == len(simple_digraph.edges)
        g2.close()

    def test_roundtrip_attributes(self, simple_digraph):
        """JSON roundtrip preserves attributes."""
        text = write_json0(simple_digraph)
        g2 = read_json(text)
        assert g2.nodes["A"].attributes.get("shape") == "box"
        assert g2.nodes["A"].attributes.get("color") == "red"
        g2.close()

    def test_roundtrip_subgraphs(self, graph_with_subgraphs):
        """JSON roundtrip preserves subgraphs."""
        text = write_json0(graph_with_subgraphs)
        g2 = read_json(text)
        assert "cluster_0" in g2.subgraphs
        g2.close()

    def test_roundtrip_complex(self, complex_graph):
        """JSON roundtrip preserves complex graph."""
        text = write_json0(complex_graph)
        g2 = read_json(text)
        assert len(g2.nodes) == len(complex_graph.nodes)
        assert len(g2.edges) == len(complex_graph.edges)
        g2.close()


# ═══════════════════════════════════════════════════════════════
#  GXL Writer
# ═══════════════════════════════════════════════════════════════


class TestGxlWriter:

    def test_gxl_valid_xml(self, simple_digraph):
        """GXL output is valid XML."""
        gxl = write_gxl(simple_digraph)
        root = ET.fromstring(gxl)
        assert root.tag == "gxl"

    def test_gxl_graph_element(self, simple_digraph):
        """GXL has <graph> element with correct edgemode."""
        gxl = write_gxl(simple_digraph)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        assert graph_el is not None
        assert graph_el.get("id") == "TestGraph"
        assert graph_el.get("edgemode") == "directed"

    def test_gxl_undirected(self, undirected_graph):
        """Undirected graph has edgemode=undirected."""
        gxl = write_gxl(undirected_graph)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        assert graph_el.get("edgemode") == "undirected"

    def test_gxl_nodes(self, simple_digraph):
        """GXL output contains <node> elements."""
        gxl = write_gxl(simple_digraph)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        nodes = graph_el.findall("node")
        node_ids = [n.get("id") for n in nodes]
        assert "A" in node_ids
        assert "B" in node_ids

    def test_gxl_edges(self, simple_digraph):
        """GXL output contains <edge> elements."""
        gxl = write_gxl(simple_digraph)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        edges = graph_el.findall("edge")
        assert len(edges) == 1
        assert edges[0].get("from") == "A"
        assert edges[0].get("to") == "B"

    def test_gxl_node_attrs(self, simple_digraph):
        """GXL node attributes use typed value elements."""
        gxl = write_gxl(simple_digraph)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        node_a = None
        for n in graph_el.findall("node"):
            if n.get("id") == "A":
                node_a = n
                break
        assert node_a is not None
        # Find shape attribute
        shape_attr = None
        for attr in node_a.findall("attr"):
            if attr.get("name") == "shape":
                shape_attr = attr
                break
        assert shape_attr is not None
        string_el = shape_attr.find("string")
        assert string_el is not None
        assert string_el.text == "box"

    def test_gxl_edge_attrs(self, simple_digraph):
        """GXL edge attributes are written correctly."""
        gxl = write_gxl(simple_digraph)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        edge = graph_el.findall("edge")[0]
        attr_names = [a.get("name") for a in edge.findall("attr")]
        assert "style" in attr_names
        assert "label" in attr_names

    def test_gxl_graph_attrs(self, simple_digraph):
        """GXL graph-level attributes are written."""
        gxl = write_gxl(simple_digraph)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        attr_names = [a.get("name") for a in graph_el.findall("attr")]
        assert "rankdir" in attr_names

    def test_gxl_subgraphs(self, graph_with_subgraphs):
        """GXL subgraphs appear as nested <graph> elements."""
        gxl = write_gxl(graph_with_subgraphs)
        root = ET.fromstring(gxl)
        top_graph = root.find("graph")
        nested = top_graph.findall("graph")
        assert len(nested) >= 1
        assert nested[0].get("id") == "cluster_0"

    def test_gxl_typed_values(self):
        """GXL type inference works for bool, int, float, string."""
        g = Graph("T", directed=True)
        g.method_init()
        n = g.add_node("A")
        n.agset("pin", "true")
        n.agset("sides", "4")
        n.agset("width", "1.5")
        n.agset("label", "hello world")
        gxl = write_gxl(g)
        root = ET.fromstring(gxl)
        graph_el = root.find("graph")
        node = graph_el.find("node")
        types_found = {}
        for attr in node.findall("attr"):
            name = attr.get("name")
            child = list(attr)[0]
            types_found[name] = child.tag
        assert types_found["pin"] == "bool"
        assert types_found["sides"] == "int"
        assert types_found["width"] == "float"
        assert types_found["label"] == "string"
        g.close()

    def test_gxl_file_write(self, simple_digraph, tmp_path):
        """write_gxl_file writes to disk."""
        path = tmp_path / "test.gxl"
        write_gxl_file(simple_digraph, str(path))
        assert path.exists()
        content = path.read_text()
        assert "<gxl" in content


# ═══════════════════════════════════════════════════════════════
#  GXL Reader
# ═══════════════════════════════════════════════════════════════


class TestGxlReader:

    def test_read_gxl_basic(self):
        """read_gxl creates graph from GXL text."""
        gxl = """<?xml version="1.0"?>
        <gxl><graph id="G" edgemode="directed">
          <node id="A"/><node id="B"/>
          <edge from="A" to="B"/>
        </graph></gxl>"""
        g = read_gxl(gxl)
        assert g.name == "G"
        assert g.directed is True
        assert "A" in g.nodes
        assert "B" in g.nodes
        assert len(g.edges) == 1
        g.close()

    def test_read_gxl_undirected(self):
        """read_gxl handles undirected graphs."""
        gxl = """<?xml version="1.0"?>
        <gxl><graph id="U" edgemode="undirected">
          <node id="X"/><node id="Y"/>
          <edge from="X" to="Y"/>
        </graph></gxl>"""
        g = read_gxl(gxl)
        assert g.directed is False
        g.close()

    def test_read_gxl_node_attrs(self):
        """read_gxl parses node attributes."""
        gxl = """<?xml version="1.0"?>
        <gxl><graph id="G" edgemode="directed">
          <node id="A">
            <attr name="shape"><string>box</string></attr>
            <attr name="color"><string>red</string></attr>
          </node>
        </graph></gxl>"""
        g = read_gxl(gxl)
        assert g.nodes["A"].attributes.get("shape") == "box"
        assert g.nodes["A"].attributes.get("color") == "red"
        g.close()

    def test_read_gxl_edge_attrs(self):
        """read_gxl parses edge attributes."""
        gxl = """<?xml version="1.0"?>
        <gxl><graph id="G" edgemode="directed">
          <node id="A"/><node id="B"/>
          <edge from="A" to="B">
            <attr name="style"><string>dashed</string></attr>
            <attr name="weight"><int>3</int></attr>
          </edge>
        </graph></gxl>"""
        g = read_gxl(gxl)
        edge = list(g.edges.values())[0]
        assert edge.attributes.get("style") == "dashed"
        assert edge.attributes.get("weight") == "3"
        g.close()

    def test_read_gxl_graph_attrs(self):
        """read_gxl parses graph-level attributes."""
        gxl = """<?xml version="1.0"?>
        <gxl><graph id="G" edgemode="directed">
          <attr name="rankdir"><string>LR</string></attr>
        </graph></gxl>"""
        g = read_gxl(gxl)
        assert g.get_graph_attr("rankdir") == "LR"
        g.close()

    def test_read_gxl_subgraphs(self):
        """read_gxl creates subgraphs from nested <graph> elements."""
        gxl = """<?xml version="1.0"?>
        <gxl><graph id="G" edgemode="directed">
          <graph id="cluster_0" edgemode="directed">
            <attr name="label"><string>Sub</string></attr>
            <node id="A"/>
          </graph>
          <node id="B"/>
          <edge from="A" to="B"/>
        </graph></gxl>"""
        g = read_gxl(gxl)
        assert "cluster_0" in g.subgraphs
        assert "A" in g.subgraphs["cluster_0"].nodes
        assert "B" in g.nodes
        g.close()

    def test_read_gxl_typed_values(self):
        """read_gxl handles bool, int, float types."""
        gxl = """<?xml version="1.0"?>
        <gxl><graph id="G" edgemode="directed">
          <node id="A">
            <attr name="pin"><bool>true</bool></attr>
            <attr name="sides"><int>6</int></attr>
            <attr name="width"><float>2.5</float></attr>
          </node>
        </graph></gxl>"""
        g = read_gxl(gxl)
        assert g.nodes["A"].attributes.get("pin") == "true"
        assert g.nodes["A"].attributes.get("sides") == "6"
        assert g.nodes["A"].attributes.get("width") == "2.5"
        g.close()

    def test_read_gxl_file(self):
        """read_gxl_file reads from test_data/sample.gxl."""
        g = read_gxl_file(TEST_DATA / "sample.gxl")
        assert g.name == "SampleGXL"
        assert g.directed is True
        assert "parse" in g.nodes
        assert "transform" in g.nodes
        assert "validate" in g.nodes
        assert len(g.edges) == 5
        g.close()

    def test_read_gxl_file_undirected(self):
        """read_gxl_file reads undirected GXL."""
        g = read_gxl_file(TEST_DATA / "sample_undirected.gxl")
        assert g.directed is False
        assert "A" in g.nodes
        assert "B" in g.nodes
        assert "C" in g.nodes
        g.close()

    def test_read_gxl_all(self):
        """read_gxl_all reads multiple graphs from one GXL file."""
        text = (TEST_DATA / "multi_graph.gxl").read_text()
        graphs = read_gxl_all(text)
        assert len(graphs) == 2
        assert graphs[0].name == "Graph1"
        assert graphs[0].directed is True
        assert graphs[1].name == "Graph2"
        assert graphs[1].directed is False
        for g in graphs:
            g.close()


class TestGxlRoundtrip:

    def test_roundtrip_simple(self, simple_digraph):
        """GXL write → read preserves graph structure."""
        gxl = write_gxl(simple_digraph)
        g2 = read_gxl(gxl)
        assert g2.name == simple_digraph.name
        assert g2.directed == simple_digraph.directed
        assert set(g2.nodes.keys()) == set(simple_digraph.nodes.keys())
        assert len(g2.edges) == len(simple_digraph.edges)
        g2.close()

    def test_roundtrip_attributes(self, simple_digraph):
        """GXL roundtrip preserves attributes."""
        gxl = write_gxl(simple_digraph)
        g2 = read_gxl(gxl)
        assert g2.nodes["A"].attributes.get("shape") == "box"
        assert g2.nodes["A"].attributes.get("color") == "red"
        edge = list(g2.edges.values())[0]
        assert edge.attributes.get("style") == "dashed"
        g2.close()

    def test_roundtrip_undirected(self, undirected_graph):
        """GXL roundtrip preserves undirected mode."""
        gxl = write_gxl(undirected_graph)
        g2 = read_gxl(gxl)
        assert g2.directed is False
        assert set(g2.nodes.keys()) == set(undirected_graph.nodes.keys())
        g2.close()

    def test_roundtrip_subgraphs(self, graph_with_subgraphs):
        """GXL roundtrip preserves subgraphs."""
        gxl = write_gxl(graph_with_subgraphs)
        g2 = read_gxl(gxl)
        assert "cluster_0" in g2.subgraphs
        g2.close()

    def test_roundtrip_complex(self, complex_graph):
        """GXL roundtrip preserves complex nested structures."""
        gxl = write_gxl(complex_graph)
        g2 = read_gxl(gxl)
        assert len(g2.nodes) == len(complex_graph.nodes)
        assert len(g2.edges) == len(complex_graph.edges)
        g2.close()


# ═══════════════════════════════════════════════════════════════
#  Cross-format roundtrip
# ═══════════════════════════════════════════════════════════════


class TestCrossFormatRoundtrip:

    def test_dot_to_json_to_dot(self, simple_digraph):
        """DOT → JSON → Graph → DOT preserves structure."""
        json_text = write_json0(simple_digraph)
        g2 = read_json(json_text)
        dot_text = write_gv(g2)
        g3 = read_gv(dot_text)
        assert set(g3.nodes.keys()) == set(simple_digraph.nodes.keys())
        assert len(g3.edges) == len(simple_digraph.edges)
        g2.close()
        g3.close()

    def test_dot_to_gxl_to_dot(self, simple_digraph):
        """DOT → GXL → Graph → DOT preserves structure."""
        gxl_text = write_gxl(simple_digraph)
        g2 = read_gxl(gxl_text)
        dot_text = write_gv(g2)
        g3 = read_gv(dot_text)
        assert set(g3.nodes.keys()) == set(simple_digraph.nodes.keys())
        assert len(g3.edges) == len(simple_digraph.edges)
        g2.close()
        g3.close()

    def test_json_to_gxl_to_json(self, simple_digraph):
        """JSON → GXL → JSON preserves structure."""
        json_text = write_json0(simple_digraph)
        g2 = read_json(json_text)
        gxl_text = write_gxl(g2)
        g3 = read_gxl(gxl_text)
        json_text2 = write_json0(g3)
        data1 = json.loads(json_text)
        data2 = json.loads(json_text2)
        assert len(data1["nodes"]) == len(data2["nodes"])
        assert len(data1["edges"]) == len(data2["edges"])
        g2.close()
        g3.close()

    def test_gxl_file_to_dot(self):
        """GXL file → DOT roundtrip."""
        g = read_gxl_file(TEST_DATA / "sample.gxl")
        dot = write_gv(g)
        g2 = read_gv(dot)
        assert len(g2.nodes) == len(g.nodes)
        assert len(g2.edges) == len(g.edges)
        g.close()
        g2.close()

    def test_json_file_to_gxl(self):
        """JSON file → GXL roundtrip."""
        g = read_json_file(TEST_DATA / "sample.json")
        gxl = write_gxl(g)
        g2 = read_gxl(gxl)
        assert len(g2.nodes) == len(g.nodes)
        assert len(g2.edges) == len(g.edges)
        g.close()
        g2.close()
