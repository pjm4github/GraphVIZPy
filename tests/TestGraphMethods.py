import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphMethods(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()

        # Register callbacks
        self.node_added_triggered = False
        self.node_deleted_triggered = False
        self.edge_added_triggered = False
        self.edge_deleted_triggered = False
        self.subgraph_added_triggered = False
        self.subgraph_deleted_triggered = False

        def on_node_added(node):
            self.node_added_triggered = True
            print(f"[Test Callback] Node '{node.name}' has been added.")

        def on_node_deleted(node):
            self.node_deleted_triggered = True

        def on_edge_added(edge):
            self.edge_added_triggered = True

        def on_edge_deleted(edge):
            self.edge_deleted_triggered = True

        def on_subgraph_added(subgraph):
            self.subgraph_added_triggered = True

        def on_subgraph_deleted(subgraph):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' has been deleted.")

        self.graph.method_update(GraphEvent.NODE_ADDED, on_node_added, action='add')
        self.graph.method_update(GraphEvent.NODE_DELETED, on_node_deleted, action='add')
        self.graph.method_update(GraphEvent.EDGE_ADDED, on_edge_added, action='add')
        self.graph.method_update(GraphEvent.EDGE_DELETED, on_edge_deleted, action='add')
        self.graph.method_update(GraphEvent.SUBGRAPH_ADDED, on_subgraph_added, action='add')
        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, on_subgraph_deleted, action='add')

    def test_aghide_invalid_node(self):
        node = self.graph.create_node_by_name("NonCompoundNode")
        node.collapsed = False
        node.subgraph = None
        with self.assertLogs() as log:
            self.graph.aghide(node)
            self.assertIn("is not a compound node", log.output[-1])

    # def test_aghide_collapsed_node(self):
    #     node = self.enclosed_node.create_node_by_name("CollapsedNode")
    #     node.collapsed = False
    #     node.subgraph = Graph(name="DummyGraph", directed=True) # recursive enclosed_node is just a dummy here
    #     self.enclosed_node.aghide(node)
    #     with self.assertLogs() as log:
    #         self.enclosed_node.aghide(node)
    #         self.assertIn("already collapsed/ hidden", log.output[-1])
    #

    def test_aginitcb_resets_callbacks(self):
        # Register an additional callback
        def extra_node_added_callback(node):
            print(f"[Extra Callback] Node '{node.name}' was added.")

        self.graph.method_update(GraphEvent.NODE_ADDED, extra_node_added_callback, action='add')
        self.assertIn(extra_node_added_callback, self.graph.clos.callbacks[GraphEvent.NODE_ADDED])

        # Initialize callbacks again
        # Create a new CallbackFunctions instance without the extra callback
        cb_funcs_graph = CallbackFunctions(graph_ins=lambda g, o, s: print(f"[New Graph Init] Graph '{o.name}' initialized."))
        cbstack_graph = Agcbstack(f=cb_funcs_graph, state="GraphStateReset", prev=None)
        self.graph.clos.set_callback_stack(cbstack_graph)

        self.graph.aginitcb(obj=self.graph, cbstack=self.graph.clos.cb)
        # After re-initialization, the extra callback should still exist since reset_callbacks was not called
        self.assertIn(extra_node_added_callback, self.graph.clos.callbacks[GraphEvent.NODE_ADDED],
                      "Extra callback should still be registered after aginitcb.")

    def test_aghide_successful(self):
        # Expose subgraph
        subgraph = self.graph.expose_subgraph("Cluster1")
        self.assertTrue(self.subgraph_added_triggered, "subgraph_added callback should have been triggered.")

        # Add nodes and edges to subgraph
        node_a = subgraph.create_node_by_name("A")
        node_b = subgraph.create_node_by_name("B")
        edge_ab = subgraph.add_edge("A", "B", edge_name="AB")

        # Collapse subgraph
        cmpnode = self.graph.create_node_by_name("Cluster1")
        cmpnode.collapsed = True
        cmpnode.subgraph = subgraph

        # Add and save connections
        print("Add and save connections")
        node_x = self.graph.create_node_by_name("X")
        node_y = self.graph.create_node_by_name("Y")
        edge_xc = self.graph.add_edge("X", "Cluster1", edge_name="X->C1")
        edge_cy = self.graph.add_edge("Cluster1", "Y", edge_name="C1->Y")

        cmpnode.saved_connections.append((node_x, edge_xc))
        cmpnode.saved_connections.append((node_y, edge_cy))

        # Simulate collapsing by deleting edges
        print("Simulate collapsing by deleting edges")
        self.graph.delete_edge(edge_xc)
        self.graph.delete_edge(edge_cy)

        self.assertTrue(self.edge_deleted_triggered, "edge_deleted callback should have been triggered.")

        # Hide the subgraph
        print("Hide the subgraph")
        success = self.graph.aghide(cmpnode)
        self.assertTrue(success, "aghide should return True for successful hiding.")
        self.assertTrue(self.subgraph_deleted_triggered, "subgraph_deleted callback should have been triggered.")
        self.assertNotIn("Cluster1", self.graph.subgraphs, "Subgraph should be removed from the enclosed_node.")
        self.assertFalse(self.graph.has_cmpnd, "has_cmpnd should be False after hiding the only collapsed subgraph.")
        self.assertFalse(cmpnode.collapsed, "cmpnode should be marked as uncollapsed.")

        # Check that subgraph nodes are deleted
        print("Check that subgraph nodes are deleted")
        self.assertNotIn("A", self.graph.nodes, "Node 'A' should be deleted from the graph enclosed_node.")
        self.assertNotIn("B", self.graph.nodes, "Node 'B' should be deleted from the graph enclosed_node.")
        self.graph.expose_subgraph(cmpnode.name)
        # Check that edges are reconnected
        print(f"Check that subgraph nodes are deleted {self.graph.edges}")
        self.assertIn(("X", "Y", "X->C1"), self.graph.edges, "Edge 'X->C1' should be reconnected from 'X' to 'Y'.")
        self.assertIn(("X", "Y", "C1->Y"), self.graph.edges, "Edge 'C1->Y' should be reconnected from 'Y' to 'Y'.")


    def test_aghide_successful2(self):
        # Expose subgraph
        subgraph = self.graph.expose_subgraph("Cluster1")
        self.assertTrue(self.node_added_triggered, "node_added callback should have been triggered.")
        self.node_added_triggered = False  # Reset flag

        # Add nodes and edges to subgraph
        node_a = subgraph.create_node_by_name("A")
        node_b = subgraph.create_node_by_name("B")
        edge_ab = subgraph.add_edge("A", "B", edge_name="AB")
        self.assertTrue(self.node_added_triggered, "node_added callback should have been triggered for node 'A'.")
        self.node_added_triggered = False

        # Create and set up callback stacks
        def node_mod_callback(graph_obj: Graph, obj: Node, state, sym):
            print(f"[Test Node Mod] Node '{obj.name}' modified with state '{state}' and symbol '{sym}'.")

        def edge_mod_callback(graph_obj: Graph, obj: Edge, state, sym):
            print(f"[Test Edge Mod] Edge '{obj.key}' modified with state '{state}' and symbol '{sym}'.")

        cb_funcs_node = CallbackFunctions(node_mod=node_mod_callback)
        cb_funcs_edge = CallbackFunctions(edge_mod=edge_mod_callback)

        cbstack_node = Agcbstack(f=cb_funcs_node, state="NodeState1", prev=None)
        cbstack_edge = Agcbstack(f=cb_funcs_edge, state="EdgeState1", prev=None)

        self.graph.clos.set_callback_stack(cbstack_node)
        self.graph.clos.set_callback_stack(cbstack_edge)

        self.graph.agmethod_init(obj=node_a)
        self.graph.agmethod_init(obj=node_b)
        self.graph.agmethod_init(obj=edge_ab)

        # Modify node and edge
        self.graph.agupdcb(obj=node_a, sym="color", cbstack=cbstack_node)
        self.graph.agupdcb(obj=edge_ab, sym="style", cbstack=cbstack_edge)

        # Rename node and subgraph
        self.graph.rename(node_a, "A_Renamed")
        self.graph.rename(subgraph, "Cluster1_Renamed")

        # Collapse subgraph
        cmpnode = self.graph.create_node_by_name("Cluster1_Renamed")
        cmpnode.collapsed = True
        cmpnode.subgraph = subgraph

        # Add and save connections
        node_x = self.graph.create_node_by_name("X")
        node_y = self.graph.create_node_by_name("Y")
        edge_xc = self.graph.add_edge("X", "Cluster1_Renamed", edge_name="X->C1")
        edge_cy = self.graph.add_edge("Cluster1_Renamed", "Y", edge_name="C1->Y")

        cmpnode.saved_connections.append((node_x, edge_xc))
        cmpnode.saved_connections.append((node_y, edge_cy))

        # Simulate collapsing by deleting edges
        self.graph.delete_edge(edge_xc)
        self.graph.delete_edge(edge_cy)

        # Hide the subgraph
        success = self.graph.aghide(cmpnode)
        self.assertTrue(success, "aghide should return True for successful hiding.")
        self.assertTrue(self.subgraph_deleted_triggered, "subgraph_deleted callback should have been triggered.")
        self.assertNotIn("Cluster1_Renamed", self.graph.subgraphs, "Subgraph should be removed from the enclosed_node.")
        self.assertFalse(self.graph.has_cmpnd, "has_cmpnd should be False after hiding the only collapsed subgraph.")
        self.assertFalse(cmpnode.collapsed, "cmpnode should be marked as uncollapsed.")

        # Check that subgraph nodes are deleted
        self.assertNotIn("A_Renamed", self.graph.nodes, "Node 'A_Renamed' should be deleted from the graph enclosed_node.")
        self.assertNotIn("B", self.graph.nodes, "Node 'B' should be deleted from the graph enclosed_node.")

        # Check that edges are reconnected
        self.assertIn(("X", "Y", "X->C1"), self.graph.edges, "Edge 'X->C1' should be reconnected from 'X' to 'Y'.")
        self.assertNotIn(("Cluster1_Renamed", "Y", "C1->Y"), self.graph.edges,
                         "Edge 'C1->Y' should have been deleted from the enclosed_node.")


    def tearDown(self):
        self.graph.agclose()

if __name__ == '__main__':
    unittest.main()