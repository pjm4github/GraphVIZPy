"""
Pytest test harness for the ANTLR4-based DOT parser.
"""
import pytest
from pathlib import Path

from gvpy.grammar.gv_reader import read_gv, read_gv_file, read_gv_all, GVParseError
from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.core.edge import Edge


# ── Simple graph types ────────────────────────────

class TestSimpleGraphs:

    def test_undirected_graph(self):
        g = read_gv("graph G { a -- b; }")
        assert isinstance(g, Graph)
        assert g.name == "G"
        assert g.directed is False
        assert "a" in g.nodes
        assert "b" in g.nodes
        assert len(g.edges) == 1

    def test_directed_graph(self):
        g = read_gv("digraph G { a -> b; }")
        assert g.directed is True
        assert len(g.edges) == 1

    def test_strict_graph(self):
        g = read_gv("strict digraph G { a -> b; a -> b; }")
        assert g.strict is True

    def test_anonymous_graph(self):
        g = read_gv("graph { a -- b; }")
        assert g.name == ""
        assert len(g.nodes) == 2

    def test_empty_graph(self):
        g = read_gv("graph G { }")
        assert len(g.nodes) == 0
        assert len(g.edges) == 0


# ── Node attributes ──────────────────────────────

class TestNodeAttributes:

    def test_node_with_attrs(self):
        g = read_gv('digraph G { a [label="Node A", shape=box]; }')
        node_a = g.nodes["a"]
        assert node_a.attributes.get("label") == "Node A"
        assert node_a.attributes.get("shape") == "box"

    def test_node_multiple_attr_lists(self):
        g = read_gv('digraph G { a [label="A"][color=red]; }')
        node_a = g.nodes["a"]
        assert node_a.attributes.get("label") == "A"
        assert node_a.attributes.get("color") == "red"

    def test_node_no_attrs(self):
        g = read_gv("digraph G { mynode; }")
        assert "mynode" in g.nodes


# ── Edge attributes ──────────────────────────────

class TestEdgeAttributes:

    def test_edge_with_attrs(self):
        g = read_gv('digraph G { a -> b [label="connects", color=blue]; }')
        edge = list(g.edges.values())[0]
        assert edge.attributes.get("label") == "connects"
        assert edge.attributes.get("color") == "blue"


# ── Edge chains ──────────────────────────────────

class TestEdgeChains:

    def test_edge_chain_creates_multiple_edges(self):
        g = read_gv("digraph G { A -> B -> C; }")
        assert len(g.edges) == 2
        assert ("A", "B", None) in g.edges
        assert ("B", "C", None) in g.edges

    def test_undirected_chain(self):
        g = read_gv("graph G { A -- B -- C -- D; }")
        assert len(g.edges) == 3

    def test_long_chain(self):
        g = read_gv("digraph G { a -> b -> c -> d -> e; }")
        assert len(g.edges) == 4
        assert len(g.nodes) == 5


# ── Subgraphs ────────────────────────────────────

class TestSubgraphs:

    def test_named_subgraph(self):
        g = read_gv("""
            digraph G {
                subgraph cluster_0 {
                    a; b;
                    a -> b;
                }
            }
        """)
        assert "cluster_0" in g.subgraphs
        sub = g.subgraphs["cluster_0"]
        assert isinstance(sub, Graph)
        assert "a" in sub.nodes
        assert "b" in sub.nodes

    def test_nested_subgraphs(self):
        g = read_gv("""
            digraph G {
                subgraph cluster_outer {
                    subgraph cluster_inner {
                        x; y;
                    }
                    z;
                }
            }
        """)
        outer = g.subgraphs["cluster_outer"]
        assert "cluster_inner" in outer.subgraphs
        inner = outer.subgraphs["cluster_inner"]
        assert "x" in inner.nodes

    def test_anonymous_subgraph(self):
        g = read_gv("digraph G { { a; b; } }")
        assert len(g.subgraphs) == 1

    def test_subgraph_as_edge_endpoint(self):
        g = read_gv("""
            digraph G {
                a -> { b; c; };
            }
        """)
        # Should create edges a->b and a->c
        assert "a" in g.nodes
        assert len(g.edges) == 2


# ── Default attributes ───────────────────────────

class TestDefaultAttributes:

    def test_default_node_attrs(self):
        g = read_gv("""
            digraph G {
                node [shape=circle, color=red];
                a; b;
            }
        """)
        assert g.nodes["a"].attributes.get("shape") == "circle"
        assert g.nodes["b"].attributes.get("color") == "red"

    def test_default_edge_attrs(self):
        g = read_gv("""
            digraph G {
                edge [style=dashed];
                a -> b;
            }
        """)
        edge = list(g.edges.values())[0]
        assert edge.attributes.get("style") == "dashed"

    def test_graph_attrs_via_keyword(self):
        g = read_gv("""
            digraph G {
                graph [rankdir=LR];
                a -> b;
            }
        """)
        assert g.get_graph_attr("rankdir") == "LR"

    def test_graph_attr_shorthand(self):
        g = read_gv("""
            digraph G {
                rankdir = LR;
                a -> b;
            }
        """)
        assert g.get_graph_attr("rankdir") == "LR"


# ── String types ─────────────────────────────────

class TestStringTypes:

    def test_html_label(self):
        g = read_gv("""
            digraph G {
                a [label=<Hello<BR/>World>];
            }
        """)
        label = g.nodes["a"].attributes.get("label")
        assert "Hello" in label
        assert "BR" in label
        assert label.startswith("<")
        assert label.endswith(">")

    def test_quoted_string_with_escapes(self):
        g = read_gv(r'''
            digraph G {
                a [label="line1\nline2"];
            }
        ''')
        label = g.nodes["a"].attributes.get("label")
        assert "\n" in label

    def test_numeric_id(self):
        g = read_gv("digraph G { 1 -> 2; }")
        assert "1" in g.nodes
        assert "2" in g.nodes

    def test_bare_id(self):
        g = read_gv("digraph G { hello_world -> foo123; }")
        assert "hello_world" in g.nodes
        assert "foo123" in g.nodes

    def test_quoted_node_name(self):
        g = read_gv('digraph G { "node with spaces" -> b; }')
        assert "node with spaces" in g.nodes


# ── Ports ─────────────────────────────────────────

class TestPorts:

    def test_node_with_port(self):
        """Ports from node ID syntax are stored on the edge as tailport/headport."""
        g = read_gv("digraph G { a:p1 -> b:p2; }")
        assert "a" in g.nodes
        assert "b" in g.nodes
        edge = list(g.edges.values())[0]
        assert edge.attributes.get("tailport") == "p1"
        assert edge.attributes.get("headport") == "p2"

    def test_port_with_compass(self):
        """Port:compass syntax is stored on the edge."""
        g = read_gv("digraph G { a:p1:n -> b:p2:s; }")
        assert "a" in g.nodes
        edge = list(g.edges.values())[0]
        assert edge.attributes.get("tailport") == "p1:n"
        assert edge.attributes.get("headport") == "p2:s"


# ── Real files ────────────────────────────────────

class TestRealFiles:

    def test_example1_gv(self):
        example_path = Path(__file__).parent.parent / "test_data" / "example1.gv"
        if not example_path.exists():
            pytest.skip("example1.gv not found")
        g = read_gv_file(example_path)
        assert isinstance(g, Graph)
        assert g.directed is False
        assert len(g.nodes) == 5
        assert len(g.edges) == 6


# ── Error handling ────────────────────────────────

class TestErrorHandling:

    def test_malformed_input_raises(self):
        with pytest.raises(GVParseError):
            read_gv("not a valid dot file }{}{")

    def test_completely_empty_raises(self):
        with pytest.raises(GVParseError):
            read_gv("")


# ── read_dot_file ─────────────────────────────────

class TestReadDotFile:

    def test_read_dot_file_function(self, tmp_path):
        dot_file = tmp_path / "test.dot"
        dot_file.write_text("digraph Test { x -> y; }", encoding="utf-8")
        g = read_gv_file(dot_file)
        assert g.name == "Test"
        assert "x" in g.nodes
        assert "y" in g.nodes


# ── Type verification ────────────────────────────

class TestObjectTypes:

    def test_graph_is_correct_type(self):
        g = read_gv("graph G { a; }")
        assert isinstance(g, Graph)

    def test_nodes_are_correct_type(self):
        g = read_gv("graph G { a; b; }")
        for node in g.nodes.values():
            assert isinstance(node, Node)

    def test_edges_are_correct_type(self):
        g = read_gv("graph G { a -- b; }")
        for edge in g.edges.values():
            assert isinstance(edge, Edge)


# ── Comments ──────────────────────────────────────

class TestComments:

    def test_line_comments(self):
        g = read_gv("""
            // This is a comment
            digraph G {
                a -> b; // inline comment
            }
        """)
        assert len(g.nodes) == 2

    def test_block_comments(self):
        g = read_gv("""
            /* Block comment */
            digraph G {
                a -> b;
            }
        """)
        assert len(g.nodes) == 2

    def test_preprocessor_lines(self):
        g = read_gv("""
            #line 1
            digraph G {
                a -> b;
            }
        """)
        assert len(g.nodes) == 2


# ── Multiple statements ──────────────────────────

class TestMultipleStatements:

    def test_semicolons_optional(self):
        g = read_gv("""
            digraph G {
                a -> b
                c -> d
            }
        """)
        assert len(g.edges) == 2

    def test_mixed_statements(self):
        g = read_gv("""
            digraph G {
                node [shape=box];
                a [label="A"];
                b [label="B"];
                a -> b [color=red];
                subgraph cluster_0 {
                    c; d;
                }
            }
        """)
        assert len(g.nodes) >= 2
        assert "cluster_0" in g.subgraphs


# ── Multi-graph files ────────────────────────────

class TestMultiGraph:

    def test_read_dot_all_two_graphs(self):
        """A file with two graph blocks returns a list of 2."""
        text = """
            digraph G1 { a -> b; }
            digraph G2 { c -> d; }
        """
        graphs = read_gv_all(text)
        assert len(graphs) == 2
        assert graphs[0].name == "G1"
        assert graphs[1].name == "G2"

    def test_read_dot_all_single_graph(self):
        """A single graph block returns a list of 1."""
        graphs = read_gv_all("digraph G { a -> b; }")
        assert len(graphs) == 1
        assert graphs[0].name == "G"

    def test_read_dot_all_mixed_types(self):
        """Mixed directed and undirected graphs are both parsed."""
        text = """
            graph G1 { a -- b; }
            digraph G2 { c -> d; }
        """
        graphs = read_gv_all(text)
        assert len(graphs) == 2
        assert graphs[0].directed is False
        assert graphs[1].directed is True


# ── Encoding fallback ────────────────────────────

class TestEncodingFallback:

    def test_latin1_file_parsed(self, tmp_path):
        """A latin-1 encoded file is parsed without error."""
        dot_file = tmp_path / "latin1.dot"
        # Write a DOT file with a latin-1 character (e.g. \xe9 = e-acute)
        content = 'digraph G { a [label="caf\xe9"]; a -> b; }'
        dot_file.write_bytes(content.encode("latin-1"))
        g = read_gv_file(dot_file)
        assert "a" in g.nodes
        assert "b" in g.nodes

    def test_utf8_still_works(self, tmp_path):
        """UTF-8 files still work normally."""
        dot_file = tmp_path / "utf8.dot"
        dot_file.write_text('digraph G { a -> b; }', encoding="utf-8")
        g = read_gv_file(dot_file)
        assert len(g.nodes) == 2
