import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose, CompoundNode
from refactored.CGGraph import Graph, agnextseq, Agcmpgraph
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc

# Now we define our test case.
class TestAghideMethod(unittest.TestCase):
    def setUp(self):
        # Create a main enclosed_node.
        self.graph = Graph("MainGraph", directed=True, strict=True, no_loop=True)

        # Create a compound node B.
        self.node_B = self.graph.add_node("B")
        # Ensure that node_B has its compound node data (an instance of CompoundNode).
        self.node_B.compound_node_data = CompoundNode()
        # Mark it as compound.
        self.node_B.compound_node_data.is_compound = True
        # Initially, it is not collapsed.
        self.node_B.compound_node_data.collapsed = False

        # Create an internal subgraph for node_B.
        # (The create_subgraph method should add the subgraph to the graph enclosed_node.)
        self.subgraph_B = self.graph.create_subgraph("SubCluster", enclosed_node=self.node_B)
        self.node_B.compound_node_data.subgraph = self.subgraph_B

        # For testing, add some nodes to the subgraph.
        self.sub_node1 = self.subgraph_B.add_node("B1")
        self.sub_node2 = self.subgraph_B.add_node("B2")

        # For this test, we simulate that the compound node has not yet been hidden.
        # Also, set up the enclosed_node's compound enclosed_node data (cmp_graph_data) if not already done.
        if not hasattr(self.graph, "cmp_graph_data"):
            # In your implementation, cmp_graph_data is likely created in Graph.__init__.
            # For testing, we add a dummy instance.

            self.graph.cmp_graph_data = Agcmpgraph()
        # Ensure that hidden_node_set is initially empty.
        self.graph.cmp_graph_data.hidden_node_set = {}

        # Also, simulate that the main enclosed_node is its own root.
        self.graph.root = self.graph

        # Finally, ensure that the compound node is in the main enclosed_node’s nodes dictionary.
        self.graph.nodes[self.node_B.name] = self.node_B

        # And register the subgraph in the enclosed_node's subgraphs and id_to_subgraph dictionaries.
        self.subgraph_B.id = 100  # simulate an ID
        self.graph.subgraphs[self.subgraph_B.name] = self.subgraph_B
        self.graph.id_to_subgraph = {self.subgraph_B.id: self.subgraph_B}

        # For this test, simulate that no edges exist to avoid interfering with edge re-splicing.
        self.graph.edges = {}

        # Also, simulate that cmpnode.saved_connections is an empty list.
        self.node_B.saved_connections = []

    def test_aghide_success(self):
        # Call the aghide method on the compound node.
        result = self.graph.aghide(self.node_B)
        self.assertTrue(result, "aghide should return True when hiding is successful.")

        # Check that the subgraph is removed from the enclosed_node's subgraphs dictionary.
        self.assertNotIn(self.subgraph_B.name, self.graph.subgraphs,
                         "After hiding, the subgraph should be removed from the enclosed_node's subgraphs.")

        # Check that the subgraph's nodes have been moved into the enclosed_node's hidden set.
        hidden_set = self.graph.cmp_graph_data.hidden_node_set
        for node_name in self.subgraph_B.nodes:
            self.assertIn(node_name, hidden_set,
                          f"Node '{node_name}' should be in the enclosed_node's hidden_node_set.")

        # Check that the compound node is marked as collapsed.
        self.assertTrue(self.node_B.compound_node_data.collapsed,
                        "The compound node should be marked as collapsed after hiding.")

    def test_aghide_invalid_node(self):
        # Test that calling aghide with an invalid type returns False.
        result = self.graph.aghide("NotANode")
        self.assertFalse(result, "aghide should return False when given an invalid node.")

    def test_aghide_not_compound(self):
        # Test that if the node is not a compound node (no subgraph), aghide returns False.
        self.node_B.compound_node_data = CompoundNode()  # reset to default (not compound)
        result = self.graph.aghide(self.node_B)
        self.assertFalse(result, "aghide should return False when the node is not compound.")

    def tearDown(self):
        # Clean up: close the enclosed_node.
        self.graph.agclose()


if __name__ == '__main__':
    unittest.main()
