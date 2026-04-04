"""
Consolidated tests for Edge operations: creation, deletion, traversal, attributes.
"""
import pytest

from pycode.cgraph.graph import Graph
from pycode.cgraph.node import Node
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent


@pytest.fixture
def graph():
    """Directed graph with nodes and edges for edge testing."""
    g = Graph("TestGraph", directed=True)
    g.method_init()
    g.add_node("A")
    g.add_node("B")
    g.add_node("C")
    g.add_edge("A", "B", edge_name="e1")
    g.add_edge("B", "C", edge_name="e2")
    yield g
    g.close()


class TestEdgeCreation:

    def test_add_edge(self, graph):
        """Adding an edge registers it in the graph."""
        assert ("A", "B", "e1") in graph.edges
        assert len(graph.edges) == 2

    def test_edge_has_tail_head(self, graph):
        """Edge has correct tail and head references."""
        e = graph.edges[("A", "B", "e1")]
        assert e.tail.name == "A"
        assert e.head.name == "B"

    def test_edge_in_adjacency(self, graph):
        """Edge appears in node adjacency lists."""
        n_a = graph.nodes["A"]
        n_b = graph.nodes["B"]
        assert len(n_a.outedges) >= 1
        assert len(n_b.inedges) >= 1

    def test_add_edge_creates_nodes(self):
        """add_edge auto-creates nodes if they don't exist."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("X", "Y")
        assert "X" in g.nodes
        assert "Y" in g.nodes
        g.close()


class TestEdgeDeletion:

    def test_delete_edge(self, graph):
        """Deleting an edge removes it from the graph."""
        e = graph.edges[("A", "B", "e1")]
        graph.delete_edge(e)
        assert ("A", "B", "e1") not in graph.edges

    def test_delete_edge_preserves_nodes(self, graph):
        """Deleting an edge doesn't remove the connected nodes."""
        e = graph.edges[("A", "B", "e1")]
        graph.delete_edge(e)
        assert "A" in graph.nodes
        assert "B" in graph.nodes


class TestEdgeTraversal:

    def test_first_out_edge(self, graph):
        """first_out_edge returns an outgoing edge."""
        n = graph.nodes["A"]
        e = graph.first_out_edge(n)
        assert e is not None
        assert e.tail.name == "A"

    def test_first_in_edge(self, graph):
        """first_in_edge returns an incoming edge."""
        n = graph.nodes["B"]
        e = graph.first_in_edge(n)
        assert e is not None
        assert e.head.name == "B"

    def test_first_edge(self, graph):
        """first_edge returns any edge connected to node."""
        n = graph.nodes["B"]
        e = graph.first_edge(n)
        assert e is not None

    def test_leaf_node_no_out_edges(self, graph):
        """Leaf node has no outgoing edges."""
        n = graph.nodes["C"]
        e = graph.first_out_edge(n)
        assert e is None


class TestEdgeFlatten:

    def test_flatten_edges_to_set(self, graph):
        """flatten_edges converts adjacency to set."""
        n = graph.nodes["B"]
        n.flatten_edges(to_list=False)
        assert isinstance(n.outedges, set)
        assert isinstance(n.inedges, set)

    def test_flatten_edges_to_list(self, graph):
        """flatten_edges converts adjacency back to list."""
        n = graph.nodes["B"]
        n.flatten_edges(to_list=False)
        n.flatten_edges(to_list=True)
        assert isinstance(n.outedges, list)
        assert isinstance(n.inedges, list)
