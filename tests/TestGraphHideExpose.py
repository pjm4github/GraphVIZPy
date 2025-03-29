import unittest

from refactored.CGGraph import Graph, agnextseq
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack
from tests.GraphPrint import ascii_print_graph


# If your classes are defined elsewhere, import them:
# from mygraphmodule import Graph, Node, Edge, Agdesc, AgIdDisc, ObjectType, ...

class TestGraphHideExpose(unittest.TestCase):

    def setUp(self):
        """
        Create a test Graph and a 'compound node' with a subgraph inside it.
        We'll use this scenario to test aghide and agexpose.
        """
        desc = Agdesc(directed=True, strict=False, no_loop=False)
        self.graph = Graph(name="MainGraph", description=desc)

        # Create a "compound node" in the main enclosed_node.
        # (One way is to create a Node, then create_subgraph_as_compound_node.)
        self.compound_node_name = "CompoundN"
        self.main_node = self.graph.add_node(self.compound_node_name)
        self.subgraph_name = "SubgInsideCompound"

        # Convert that node into a compound node with an internal subgraph
        # For example:
        self.subg = self.graph.create_subgraph_as_compound_node(
            name=self.subgraph_name,
            compound_node=self.main_node
        )

        # Add a couple of nodes inside the subgraph:
        self.inner_node1 = self.subg.add_node("Inner1")
        self.inner_node2 = self.subg.add_node("Inner2")
        # Create an edge inside the subgraph:
        self.subg.add_edge("Inner1", "Inner2", edge_name="In1->In2")

        # Also create an "external" node in the main enclosed_node, connected to the compound node:
        self.external_node = self.graph.add_node("ExternalA")
        self.ext_edge = self.graph.add_edge("ExternalA", self.compound_node_name, edge_name="Ext->Compound")

        # Confirm initial conditions
        self.assertIn(self.compound_node_name, self.graph.nodes)
        self.assertIn(self.subgraph_name, self.graph.subgraphs)
        self.assertIn("Inner1", self.subg.nodes)
        self.assertIn("Inner2", self.subg.nodes)
        self.assertIn("ExternalA", self.graph.nodes)

    def test_aghide(self):
        """
        Test that 'aghide' removes the subgraph from the graph enclosed_node and splices
        external edges so they connect only to the compound node.
        """
        cmpnode = self.main_node  # The compound node
        ascii_print_graph(self.graph)
        # Ensure subgraph is currently visible
        self.assertIn(self.subgraph_name, self.graph.subgraphs,
                      "Subgraph should be visible before hiding.")

        # Call aghide
        hide_result = self.graph.aghide(cmpnode)
        self.assertTrue(hide_result, "aghide should return True on success.")

        # After hiding:
        # 1) The subgraph should be removed from self.enclosed_node.subgraphs
        self.assertNotIn(self.subgraph_name, self.graph.subgraphs,
                         "Subgraph should no longer appear in the enclosed_node's subgraphs after hiding.")

        # 2) Nodes inside the subgraph may be “hidden” or removed from enclosed_node's node dictionary
        # (Depending on your implementation, they might be removed from .nodes or stored in .cmp_graph_data.hidden_node_set, etc.)
        # For a simple check:
        self.assertNotIn("Inner1", self.graph.nodes,
                         "Inner1 should be hidden/removed from the enclosed_node's node dictionary.")
        self.assertNotIn("Inner2", self.graph.nodes,
                         "Inner2 should be hidden/removed from the enclosed_node's node dictionary.")

        # 3) External edges that originally connected to nodes in the subgraph might be spliced
        # so they connect to the compound node. In this example, we had "Ext->Compound" directly
        # connecting to the compound node, so check it’s still present and not broken:
        ext_edge_key = ("ExternalA", self.compound_node_name, "Ext->Compound")
        self.assertIn(ext_edge_key, self.graph.edges,
                      "External edge Ext->Compound should still exist, spliced or not, depending on design.")

        ascii_print_graph(self.graph)
        # 4) The compound_node_data might be marked collapsed/hidden

    def test_agexpose(self):
        """
        Test that 'agexpose' re-inserts the subgraph into the graph enclosed_node and restores
        internal nodes/edges, reversing a previous 'aghide'.
        """
        cmpnode = self.main_node

        # First hide the subgraph
        hide_result = self.graph.aghide(cmpnode)
        self.assertTrue(hide_result, "aghide should succeed before we test agexpose.")

        # Now call agexpose
        expose_result = self.graph.agexpose(cmpnode)
        self.assertTrue(expose_result, "agexpose should return True on success.")

        # After exposing:
        # 1) The subgraph should reappear in the enclosed_node's subgraphs
        self.assertIn(self.subgraph_name, self.graph.subgraphs,
                      "Subgraph should reappear in the enclosed_node's subgraphs after agexpose.")

        # 2) The internal nodes of that subgraph should also be restored to the main enclosed_node's node dictionary
        # (depending on your design; if subgraph nodes are separated from main enclosed_node's .nodes, you might see them re-linked)
        self.assertIn("Inner1", self.subg.nodes,
                      "Inner1 should be restored to the subgraph nodes.")
        self.assertIn("Inner2", self.subg.nodes,
                      "Inner2 should be restored to the subgraph nodes.")

        # 3) Any external edges spliced to the compound node might be restored to their original connections
        # if the design does full re-splicing (your design may vary).
        # For instance, if you had edges from external nodes to 'Inner1', check if it's reconnected.
        # This depends on how 'aghide' and 'agexpose' handle the splicing logic.
        # Example placeholder check (only if you originally spliced external->Inner1):
        # ext_edge_key = ("ExternalA", "Inner1", "Ext->Inner1")
        # self.assertIn(ext_edge_key, self.enclosed_node.edges, "Edge from external to Inner1 should be restored.")

        # 4) The compound node data might no longer be hidden
        self.assertFalse(cmpnode.compound_node_data.collapsed,
                         "Compound node's data should be marked un-hidden after agexpose.")

if __name__ == "__main__":
    unittest.main()