import unittest
# from refactored.cgraph_mapped import *
from refactored.CGNode import Node, CompoundNode
from refactored.CGGraph import Graph

class TestAgcmpnode(unittest.TestCase):
    def setUp(self):
        pass

    def test_degree_update(self):
        cmp_node = CompoundNode()
        cmp_node.update_degree(outedges=3, inedges=2)
        self.assertEqual(cmp_node.degree, 5)

    def test_compound_node_initialization(self):
        cmp_node = CompoundNode()
        self.assertFalse(cmp_node.is_compound)
        self.assertIsNone(cmp_node.subgraph)
        self.assertFalse(cmp_node.collapsed)


class TestAgnode(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph")
        self.node_a = self.graph.create_node_by_name("A")
        self.node_b = self.graph.create_node_by_name("B")
        self.node_c = self.graph.create_node_by_name("C")
        self.node1 = self.graph.create_node_by_name("Node1")
        self.node2 = self.graph.create_node_by_name("Node2")
        self.node3 = self.graph.create_node_by_name("Node3")

    def test_make_compound_node(self):
        node = self.graph.make_compound_node("Subgraph_A")
        self.assertTrue(node.compound_node_data.is_compound)
        self.assertIsNotNone(node.compound_node_data.subgraph)
        self.assertIn("Subgraph_A", self.graph.subgraphs)

    def test_splice_edge(self):
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")
        node_c = self.graph.create_node_by_name("C")
        self.graph.splice_edge(edge_ab, new_head=node_c)
        self.assertIn(edge_ab, self.node_c.inedges)
        self.assertNotIn(edge_ab, self.node_b.outedges)
        self.assertEqual(edge_ab.head, node_c)

    def test_hide_expose_contents(self):
        node = self.graph.make_compound_node("Subgraph_A")
        node.hide_contents()
        self.assertTrue(node.compound_node_data.collapsed)
        node.expose_contents()
        self.assertFalse(node.compound_node_data.collapsed)

    def test_add_edge_updates_degree(self):
        edge = self.graph.add_edge("Node1", "Node2", edge_name="Edge1")
        self.assertEqual(self.node1.compound_node_data.degree, 1)
        self.assertEqual(self.node2.compound_node_data.degree, 1)

    def test_delete_node_resets_compound_node_data(self):
        edge = self.graph.add_edge("Node1", "Node2", edge_name="Edge1")
        self.graph.delete_node(self.node1)
        self.assertNotIn("Node1", self.graph.nodes)
        self.assertEqual(self.node1.compound_node_data.degree, 0)

    def test_compare_degree(self):
        node3 = self.graph.create_node_by_name("Node3")
        self.graph.add_edge("Node1", "Node2", edge_name="Edge1")
        self.graph.add_edge("Node1", "Node3", edge_name="Edge2")
        comparison = self.node2.compare_degree(self.node3)
        self.assertEqual(comparison, 0)  # Both have degree 1


class TestAgraph(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph")
        self.node_a = self.graph.create_node_by_name("A")
        self.node_b = self.graph.create_node_by_name("B")

    def test_delete_compound_node(self):
        node = self.graph.make_compound_node("Subgraph_A")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")
        self.graph.delete_node(node)
        # Verify that the node created by the edge is still in the node list
        self.assertIn("A", self.graph.nodes)
        self.assertNotIn("Subgraph_A", self.graph.subgraphs)
        # Verify that the edge is still in the list
        self.assertIn(edge_ab, self.graph.edges.values())

if __name__ == '__main__':
    unittest.main()
