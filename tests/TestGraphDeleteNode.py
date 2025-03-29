import unittest
# from refactored.cgraph_mapped import *
from refactored.CGNode import Node
from refactored.CGGraph import Graph

class TestGraphDeleteNode(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph")
        self.node_a = self.graph.create_node_by_name("A")
        self.node_b = self.graph.create_node_by_name("B")
        self.node_c = self.graph.create_node_by_name("C")
        self.edge_ab = self.graph.add_edge("A", "B", edge_name="AB")
        self.edge_bc = self.graph.add_edge("B", "C", edge_name="BC")

    def test_delete_nonexistent_node(self):
        node_d = Node(name="D", graph=self.graph, id_=10, seq=10, root=self.graph.get_root())
        with self.assertLogs(level='WARNING') as log:
            self.graph.delete_node(node_d)
            self.assertIn("Node 'Node(name=D, id=10, seq=10, degree=0, centrality=0.0, attributes={})' does not exist in enclosed_node 'TestGraph'.", log.output[0])

    def test_delete_node_with_edges(self):
        self.graph.delete_node(self.node_b)
        self.assertNotIn("B", self.graph.nodes)
        self.assertNotIn(("A", "B", "AB"), self.graph.edges)
        self.assertNotIn(("B", "C", "BC"), self.graph.edges)

    def test_delete_compound_node(self):
        # Convert node B into a compound node.
        # The make_compound_node method creates an internal subgraph and marks the node as compound.
        self.subgraph_b = self.graph.make_compound_node("SubCluster", self.node_b)

        # For extra verification, add a child node to the new subgraph.
        self.child_b = self.subgraph_b.add_node("B_child")

        self.assertTrue( self.node_b.compound_node_data.is_compound,
                         "Node B should be marked as compound after make_compound_node is called.")

        self.assertIsNotNone(self.node_b.compound_node_data.subgraph,"Node B should have a subgraph linked to it.")
        # Verify that the main enclosed_node has registered the subgraph.
        self.assertIn(
            "SubCluster",
            self.graph.subgraphs,
            "The subgraph 'SubCluster' should be registered in the main enclosed_node."
        )
        # Now delete node B (the compound node).
        result = self.graph.delete_node(self.node_b)
        self.assertTrue(result, "delete_node should return True upon successful deletion.")

        # After deletion, node B should no longer be in the enclosed_node's node dictionary.
        self.assertNotIn("B", self.graph.nodes, "Node B should have been removed from the enclosed_node's nodes.")
        # Also, its associated subgraph should have been removed.
        self.assertNotIn("SubCluster", self.graph.subgraphs,
                         "The subgraph 'SubCluster' should have been removed from the enclosed_node's subgraphs.")


        #
        # subgraph_b = self.enclosed_node.create_subgraph("Subgraph_B", enclosed_node=self.node_b)
        # node_b1 = subgraph_b.create_node_by_name("B1")
        # edge_b1b2 = subgraph_b.add_edge("B1", "B2", edge_name="B1B2")
        # self.enclosed_node.delete_node(self.node_b)
        # self.assertNotIn("B", self.enclosed_node.nodes)
        # self.assertNotIn("Subgraph_B", self.enclosed_node.subgraphs)
        # self.assertNotIn(("B1", "B2", "B1B2"), subgraph_b.edges)

    def test_delete_node_updates_metrics(self):
        self.graph.delete_node(self.node_b)
        self.assertEqual(self.node_a.compound_node_data.degree, 0)
        self.assertEqual(self.node_c.compound_node_data.degree, 0)


if __name__ == '__main__':
    unittest.main()
