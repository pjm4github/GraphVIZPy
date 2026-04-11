"""
Consolidated tests for Node operations: creation, deletion, compound nodes, metrics.
"""
import pytest

from gvpy.core.graph import Graph
from gvpy.core.node import Node, CompoundNode, agcmpnode, agcmpgraph_of
from gvpy.core.edge import Edge
from gvpy.core.defines import ObjectType, GraphEvent


@pytest.fixture
def graph():
    """Directed graph with 3 nodes and 2 edges."""
    g = Graph("TestGraph", directed=True)
    g.method_init()
    g.add_node("A")
    g.add_node("B")
    g.add_node("C")
    g.add_edge("A", "B", edge_name="e_ab")
    g.add_edge("B", "C", edge_name="e_bc")
    yield g
    g.close()


class TestNodeCreation:

    def test_add_node(self, graph):
        """Adding a node registers it in the graph."""
        assert "A" in graph.nodes
        assert "B" in graph.nodes
        assert "C" in graph.nodes
        assert len(graph.nodes) == 3

    def test_add_node_returns_node(self, graph):
        """add_node returns a Node instance."""
        n = graph.add_node("D")
        assert isinstance(n, Node)
        assert n.name == "D"

    def test_add_duplicate_returns_existing(self, graph):
        """Adding a node that already exists returns the existing one."""
        n1 = graph.nodes["A"]
        n2 = graph.add_node("A")
        assert n1 is n2

    def test_node_has_parent(self, graph):
        """Node's parent is the graph that owns it."""
        n = graph.nodes["A"]
        assert n.parent is graph


class TestNodeDeletion:

    def test_delete_node_removes_it(self, graph):
        """Deleting a node removes it from the graph."""
        graph.delete_node(graph.nodes["B"])
        assert "B" not in graph.nodes

    def test_delete_node_removes_edges(self, graph):
        """Deleting a node removes its connected edges."""
        graph.delete_node(graph.nodes["B"])
        assert ("A", "B", "e_ab") not in graph.edges
        assert ("B", "C", "e_bc") not in graph.edges

    def test_delete_node_updates_degree(self, graph):
        """Deleting a node leaves remaining nodes with updated degree."""
        graph.delete_node(graph.nodes["B"])
        assert len(graph.nodes["A"].outedges) == 0
        assert len(graph.nodes["C"].inedges) == 0

    def test_delete_nonexistent_node(self, graph):
        """Deleting a node not in the graph doesn't crash."""
        fake = Node("Fake", graph=graph, id_=999, seq=999)
        graph.delete_node(fake)  # should not raise


class TestCompoundNode:

    def test_compound_node_default(self, graph):
        """CompoundNode defaults to not compound, not collapsed."""
        cn = CompoundNode()
        assert cn.is_compound is False
        assert cn.subgraph is None
        assert cn.collapsed is False

    def test_degree_update(self):
        """CompoundNode degree updates correctly."""
        cn = CompoundNode()
        cn.update_degree(outedges=3, inedges=2)
        assert cn.degree == 5

    def test_make_compound_node(self, graph):
        """make_compound converts a node to compound with a subgraph."""
        n = graph.nodes["A"]
        n.make_compound("Sub_A")
        assert n.compound_node_data.is_compound is True
        assert n.compound_node_data.subgraph is not None
        assert "Sub_A" in graph.subgraphs

    def test_hide_expose_contents(self, graph):
        """hide_contents sets collapsed, expose_contents clears it."""
        n = graph.nodes["A"]
        n.make_compound("Sub_A")
        n.hide_contents()
        assert n.compound_node_data.collapsed is True
        n.expose_contents()
        assert n.compound_node_data.collapsed is False

    def test_compare_degree(self, graph):
        """compare_degree returns 0 for equal-degree nodes."""
        n_a = graph.nodes["A"]
        n_c = graph.nodes["C"]
        result = n_a.compare_degree(n_c)
        assert result == 0

    def test_compound_node_repr(self):
        """CompoundNode repr is concise."""
        cn = CompoundNode()
        r = repr(cn)
        assert "CompoundNode" in r
        assert len(r) < 120


class TestNodeEdgeManagement:

    def test_add_outedge(self, graph):
        """add_outedge adds to outedges list."""
        from gvpy.core.edge import Edge
        n = graph.nodes["A"]
        initial = len(n.outedges)
        e = Edge(tail=n, head=graph.nodes["C"], name="test", graph=graph)
        n.add_outedge(e)
        assert len(n.outedges) == initial + 1

    def test_remove_outedge(self, graph):
        """remove_outedge removes from outedges list."""
        n = graph.nodes["A"]
        e = n.outedges[0]
        n.remove_outedge(e)
        assert e not in n.outedges

    def test_add_inedge(self, graph):
        """add_inedge adds to inedges list."""
        from gvpy.core.edge import Edge
        n = graph.nodes["C"]
        initial = len(n.inedges)
        e = Edge(tail=graph.nodes["A"], head=n, name="test", graph=graph)
        n.add_inedge(e)
        assert len(n.inedges) == initial + 1

    def test_remove_inedge(self, graph):
        """remove_inedge removes from inedges list."""
        n = graph.nodes["C"]
        if n.inedges:
            e = n.inedges[0]
            n.remove_inedge(e)
            assert e not in n.inedges


class TestNodeSpliceEdge:

    def test_splice_edge_new_head(self, graph):
        """splice_edge moves edge head to a different node."""
        n_a = graph.nodes["A"]
        n_b = graph.nodes["B"]
        n_c = graph.nodes["C"]
        e = n_a.outedges[0]  # A->B
        n_a.splice_edge(e, new_head=n_c)
        assert e.head is n_c
        assert e in n_c.inedges

    def test_splice_edge_new_tail(self, graph):
        """splice_edge moves edge tail to a different node."""
        n_a = graph.nodes["A"]
        n_c = graph.nodes["C"]
        e = n_a.outedges[0]  # A->B
        n_a.splice_edge(e, new_tail=n_c)
        assert e.tail is n_c
        assert e in n_c.outedges


class TestNodeFlatten:

    def test_flatten_to_set(self, graph):
        """flatten_edges keeps adjacency as list (no set conversion)."""
        n = graph.nodes["B"]
        n.flatten_edges(to_list=False)
        # Always list — set conversion removed for deterministic ordering
        assert isinstance(n.outedges, list)
        assert isinstance(n.inedges, list)

    def test_flatten_to_list(self, graph):
        """flatten_edges converts adjacency back to list."""
        n = graph.nodes["B"]
        n.flatten_edges(to_list=False)
        n.flatten_edges(to_list=True)
        assert isinstance(n.outedges, list)
        assert isinstance(n.inedges, list)

    def test_agflatten_elist_out(self, graph):
        """agflatten_elist keeps outedges as list."""
        n = graph.nodes["A"]
        n.agflatten_elist(outedge=True, to_list=False)
        assert isinstance(n.outedges, list)  # always list now
        n.agflatten_elist(outedge=True, to_list=True)
        assert isinstance(n.outedges, list)

    def test_agflatten_elist_in(self, graph):
        """agflatten_elist keeps inedges as list."""
        n = graph.nodes["C"]
        n.agflatten_elist(outedge=False, to_list=False)
        assert isinstance(n.inedges, list)  # always list now
        n.agflatten_elist(outedge=False, to_list=True)
        assert isinstance(n.inedges, list)


class TestCompoundNodeData:

    def test_set_get_compound_data(self, graph):
        """set_compound_data and get_compound_data work."""
        n = graph.nodes["A"]
        n.set_compound_data("rank", 5)
        assert n.get_compound_data("rank") == 5

    def test_set_compound_data_centrality(self, graph):
        """set_compound_data updates centrality metrics."""
        n = graph.nodes["A"]
        n.set_compound_data("degree_centrality", 0.75)
        assert n.compound_node_data.degree_centrality == 0.75


class TestModuleLevelFunctions:

    def test_agcmpnode(self):
        """agcmpnode creates a compound node with subgraph."""
        g = Graph("T", directed=True)
        g.method_init()
        cn = agcmpnode(g, "Compound")
        assert cn is not None
        assert cn.compound_node_data.subgraph is not None
        g.close()

    def test_agcmpgraph_of(self):
        """agcmpgraph_of returns the subgraph of a compound node."""
        g = Graph("T", directed=True)
        g.method_init()
        cn = agcmpnode(g, "Compound")
        subg = agcmpgraph_of(cn)
        assert subg is not None
        g.close()

    def test_agcmpgraph_of_non_compound(self):
        """agcmpgraph_of returns None for non-compound node."""
        g = Graph("T", directed=True)
        g.method_init()
        n = g.add_node("Simple")
        result = agcmpgraph_of(n)
        assert result is None
        g.close()


class TestNodeRepr:

    def test_repr_concise(self, graph):
        """Node repr is concise."""
        n = graph.nodes["A"]
        r = repr(n)
        assert "Node A" in r
        assert len(r) < 60

    def test_repr_shows_edges(self, graph):
        """Node repr shows edge counts."""
        n = graph.nodes["B"]
        r = repr(n)
        assert "out=" in r
        assert "in=" in r
