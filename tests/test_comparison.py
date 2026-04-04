# from pycode.cgraph_mapped import *
from pycode.cgraph.node import Node, CompoundNode
from pycode.cgraph.graph import Graph


class TestAgcmpnode:
    def test_degree_update(self):
        """Test that update_degree correctly sums outedges and inedges."""
        cmp_node = CompoundNode()
        cmp_node.update_degree(outedges=3, inedges=2)
        assert cmp_node.degree == 5

    def test_compound_node_initialization(self):
        """Test that a new CompoundNode has default values."""
        cmp_node = CompoundNode()
        assert not cmp_node.is_compound
        assert cmp_node.subgraph is None
        assert not cmp_node.collapsed


class TestAgnode:
    def setup_method(self):
        self.graph = Graph(name="TestGraph")
        self.node_a = self.graph.create_node_by_name("A")
        self.node_b = self.graph.create_node_by_name("B")
        self.node_c = self.graph.create_node_by_name("C")
        self.node1 = self.graph.create_node_by_name("Node1")
        self.node2 = self.graph.create_node_by_name("Node2")
        self.node3 = self.graph.create_node_by_name("Node3")

    def test_make_compound_node(self):
        """Test that make_compound_node creates a compound node with a subgraph."""
        node = self.graph.make_compound_node("Subgraph_A")
        assert node.compound_node_data.is_compound
        assert node.compound_node_data.subgraph is not None
        assert "Subgraph_A" in self.graph.subgraphs

    def test_splice_edge(self):
        """Test that splice_edge redirects an edge to a new head node."""
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")
        node_c = self.graph.create_node_by_name("C")
        self.graph.splice_edge(edge_ab, new_head=node_c)
        assert edge_ab in self.node_c.inedges
        assert edge_ab not in self.node_b.outedges
        assert edge_ab.head == node_c

    def test_hide_expose_contents(self):
        """Test that hide_contents collapses and expose_contents expands a compound node."""
        node = self.graph.make_compound_node("Subgraph_A")
        node.hide_contents()
        assert node.compound_node_data.collapsed
        node.expose_contents()
        assert not node.compound_node_data.collapsed

    def test_add_edge_updates_degree(self):
        """Test that adding an edge increments the degree of both endpoint nodes."""
        edge = self.graph.add_edge("Node1", "Node2", edge_name="Edge1")
        assert self.node1.compound_node_data.degree == 1
        assert self.node2.compound_node_data.degree == 1

    def test_delete_node_resets_compound_node_data(self):
        """Test that deleting a node removes it and resets its degree to zero."""
        edge = self.graph.add_edge("Node1", "Node2", edge_name="Edge1")
        self.graph.delete_node(self.node1)
        assert "Node1" not in self.graph.nodes
        assert self.node1.compound_node_data.degree == 0

    def test_compare_degree(self):
        """Test that compare_degree returns 0 for nodes with equal degree."""
        node3 = self.graph.create_node_by_name("Node3")
        self.graph.add_edge("Node1", "Node2", edge_name="Edge1")
        self.graph.add_edge("Node1", "Node3", edge_name="Edge2")
        comparison = self.node2.compare_degree(self.node3)
        assert comparison == 0  # Both have degree 1


class TestAgraph:
    def setup_method(self):
        self.graph = Graph(name="TestGraph")
        self.node_a = self.graph.create_node_by_name("A")
        self.node_b = self.graph.create_node_by_name("B")

    def test_delete_compound_node(self):
        """Test that deleting a compound node removes its subgraph but preserves other nodes and edges."""
        node = self.graph.make_compound_node("Subgraph_A")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")
        self.graph.delete_node(node)
        # Verify that the node created by the edge is still in the node list
        assert "A" in self.graph.nodes
        assert "Subgraph_A" not in self.graph.subgraphs
        # Verify that the edge is still in the list
        assert edge_ab in self.graph.edges.values()
