import unittest

from refactored.CGGraph import Graph
from refactored.Defines import GraphEvent
from refactored.Headers import Agdesc
from tests.GraphPrint import ascii_print_graph


class TestGraphAghide(unittest.TestCase):
    def setUp(self):
        desc = Agdesc(directed=True, strict=False, no_loop=False)
        self.graph = Graph(name="TestGraph", directed=True, description=desc)
        # print(f"Starting graph structure:")
        # ascii_print_graph(self.graph)

        self.subgraph_deleted_triggered = False
        self.cmpnode = self.graph.add_node("CompoundNode")
        # print(f"Graph structure after adding CompoundNode:")
        # ascii_print_graph(self.graph)
        self.node_A = self.graph.add_node("A")

        def subgraph_deleted_callback(subgraph):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' deleted.")

        # Convert this node into a compound node by creating a subgraph
        # that it owns. (In your code, you might do create_subgraph_as_compound_node
        # or similar.)

        self.subg_name = "FirstSubgraph"
        self.subg = self.graph.create_subgraph_as_compound_node(
            name=self.subg_name,
            compound_node=self.cmpnode
        )
        # print(f"Graph structure after adding SubgraphInsideCompound:")
        # ascii_print_graph(self.graph)

        # Add some nodes to the subgraph
        self.inner_node1 = self.subg.add_node("Inner1")
        self.inner_node2 = self.subg.add_node("Inner2")
        # Maybe add an edge inside the subgraph
        self.subg.add_edge("Inner1", "Inner2", "In1->In2")
        print(f"Graph structure after setup")
        ascii_print_graph(self.graph)
        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, subgraph_deleted_callback, action='add')

    def test_a1_subgraph_create_hide(self):
        print(">>>> Testing subgraph creation")
        self.assertIn(self.subg_name, self.graph.subgraphs,
                      "Subgraph should be in enclosed_node graph before hiding.")
        # Confirm the subgraph nodes are recognized
        self.assertIn("Inner1", self.subg.nodes)
        self.assertIn("Inner2", self.subg.nodes)

    def test_a2_aghide_and_validate_hidden(self):
        """
        Test the aghide method to ensure that the subgraph becomes hidden
        and its nodes become invisible to the main graph.
        """
        # Call aghide on the compound node
        print(">>>> Testing aghide and validate hidden subgraph")
        result = self.graph.aghide(self.cmpnode)
        print(f"Graph structure after hiding {self.cmpnode.name}, inner nodes and an inner edge:")
        ascii_print_graph(self.graph)
        self.assertTrue(result, "aghide should return True upon success.")

        # 1) The subgraph should no longer appear in main_graph.subgraphs
        self.assertNotIn(self.subg_name, self.graph.subgraphs,
                         "Subgraph should be removed from enclosed_node's subgraphs after hiding.")

        # 2) The subgraph's internal nodes should be hidden.
        #    Typically, your code removes them from main_graph.nodes or
        #    places them in a hidden set. For instance, if you store them
        #    in g.cmp_graph_data.hidden_node_set, you can check that:
        hidden_nodes = self.graph.cmp_graph_data.hidden_node_set
        self.assertIn("Inner1", hidden_nodes,
                      "Inner1 should be in the main graph's hidden_node_set after aghide.")
        self.assertIn("Inner2", hidden_nodes,
                      "Inner2 should be in the main graph's hidden_node_set after aghide.")

        # 3) The compound node record might be marked as collapsed/hidden
        self.assertTrue(self.cmpnode.compound_node_data.collapsed,
                        "cmpnode should be flagged as collapsed after aghide.")

        expose_ok = self.graph.agexpose(self.cmpnode)
        print(f"Graph structure after exposing hidden node {self.cmpnode.name}, inner nodes and an inner edge:")
        ascii_print_graph(self.graph)

        self.assertTrue(expose_ok, "agexpose/unhide should return True on success.")

        # Verify the subgraph is restored to enclosed_node's subgraphs
        self.assertIn(self.subg_name, self.graph.subgraphs,
                      "Subgraph should be restored after agexpose/unhide.")
        # Verify the previously hidden nodes are now visible again
        hidden_nodes = self.graph.cmp_graph_data.hidden_node_set
        self.assertNotIn("Inner1", hidden_nodes,
                         "Inner1 should be removed from hidden set after unhide.")
        self.assertNotIn("Inner2", hidden_nodes,
                         "Inner2 should be removed from hidden set after unhide.")

        # The compound node should no longer be flagged as collapsed
        self.assertFalse(self.cmpnode.compound_node_data.collapsed,
                         "cmpnode should no longer be collapsed after unhide/expose.")

    def test_a3_aghide_and_unhide(self):
        """
        If you also have a method (like agexpose or unhide), test that
        we can hide the subgraph and then restore it again.
        """
        print(">>>> Testing aghide and validate hidden subgraph")
        print(f"Compound graph structure after setup")
        ascii_print_graph(self.graph)
        # First hide
        hide_ok = self.graph.aghide(self.cmpnode)
        self.assertTrue(hide_ok, "aghide should succeed.")
        print(f"Compound graph structure after aghide")
        ascii_print_graph(self.graph)
        # (Optional) Now 'unhide' or 'agexpose' if your code supports it
        # For example, if your method is named agexpose:
        expose_ok = self.graph.agexpose(self.cmpnode)
        self.assertTrue(expose_ok, "agexpose/unhide should return True on success.")

        # Verify the subgraph is restored to enclosed_node's subgraphs
        self.assertIn(self.subg_name, self.graph.subgraphs,
                      "Subgraph should be restored after agexpose/unhide.")
        # Verify the previously hidden nodes are now visible again
        hidden_nodes = self.graph.cmp_graph_data.hidden_node_set
        self.assertNotIn("Inner1", hidden_nodes,
                         "Inner1 should be removed from hidden set after unhide.")
        self.assertNotIn("Inner2", hidden_nodes,
                         "Inner2 should be removed from hidden set after unhide.")

        # The compound node should no longer be flagged as hidden
        self.assertFalse(self.cmpnode.compound_node_data.collapsed,
                         "cmpnode should no longer be colapsed after unhide/expose.")

    def test_a4_aghide_triggers_callback(self):
        # self.enclosed_node.expose_subgraph("Cluster1")
        # cmpnode = self.enclosed_node.create_node_by_name("Cluster1")
        # cmpnode.make_compound("Cluster1")
        # # cmpnode.collapsed = True
        # # cmpnode.subgraph = subgraph
        #
        print(">>>> Testing aghide and triggers callbacks")
        # This creates a compound enclosed_node and makes node B a subgraph
        # Either method will create the same structure
        method_one = True
        # Version 1
        if method_one:
            print("Method 1, Create Subgraph and add Node X")
            second_subgraph = self.graph.create_subgraph('SecondSubgraph')
            node_x = second_subgraph.create_node_by_name("X")
            print("node x created")
        # Version 2
        else:
            print("Method 2, Create Node X and make it a Subgraph")
            node_x = self.graph.create_node_by_name("X")
            second_subgraph = self.graph.create_subgraph_as_compound_node(name='SecondSubgraph',
                compound_node=node_x
            )
            print("node x created")

        #ascii_print_graph(self.graph)
        node_y = second_subgraph.create_node_by_name("Y")
        edge_xc = second_subgraph.add_edge("X", "Y", edge_name="X->Y")
        edge_cy = second_subgraph.add_edge("Y", "X", edge_name="Y->X")
        #
        # # Save connections
        # cmpnode.saved_connections.append((node_x, edge_xc))
        # cmpnode.saved_connections.append((node_y, edge_cy))
        print(f"Compound graph structure:")
        ascii_print_graph(self.graph)
        # # Delete edges to simulate collapse
        second_subgraph.delete_edge(edge_xc)
        second_subgraph.delete_edge(edge_cy)
        #
        # # Hide the subgraph
        print(f"Compound graph structure after deletion of subgraph nodes:")
        ascii_print_graph(self.graph)

        success = self.graph.aghide(node_x)
        print(f"Compound graph structure after hiding node X (which is not a compound node) subgraph nodes:")
        ascii_print_graph(self.graph)
        self.assertTrue(success, "aghide should return False for non successful hiding.")
        self.assertTrue(self.subgraph_deleted_triggered, "subgraph_deleted callback should not have been triggered.")
        self.assertIn("FirstSubgraph", self.graph.subgraphs, "FirstSubgraph should remain in the graph.")
        self.assertIn("A", self.graph.nodes, "Node 'A' should be in the main enclosed_node.")

    def test_a5_aghide_invalid_node(self):
        print(">>>> Testing aghide of invalid nodes")
        node = self.graph.create_node_by_name("NonCompoundNode")
        node.collapsed = False
        node.subgraph = None

        success = self.graph.aghide(node)
        print(f"success = {success}")
        self.assertFalse(success, "aghide should return False for non-collapsed nodes.")

    def tearDown(self):
        self.graph.agclose()

if __name__ == '__main__':
    unittest.main()
