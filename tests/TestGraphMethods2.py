import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphMethods2(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()

        # Register callbacks
        self.node_added_triggered = False
        self.subgraph_deleted_triggered = False

        def on_node_added(node):
            self.node_added_triggered = True
            print(f"[Test Callback] Node '{node.name}' has been added.")

        def on_subgraph_deleted(subgraph):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' has been deleted.")

        self.graph.method_update(GraphEvent.NODE_ADDED, on_node_added, action='add')
        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, on_subgraph_deleted, action='add')

    def test_aginitcb_resets_callbacks(self):
        # Register an additional callback
        def extra_node_added_callback(node):
            print(f"[Extra Callback] Node '{node.name}' was added.")

        self.graph.method_update(GraphEvent.NODE_ADDED, extra_node_added_callback, action='add')
        self.assertIn(extra_node_added_callback, self.graph.clos.callbacks[GraphEvent.NODE_ADDED])

        # Initialize callbacks again with a new callback stack
        cb_funcs_graph = CallbackFunctions(graph_ins=lambda g, o, s: print(f"[New Graph Init] Graph '{o.name}' initialized."))
        cbstack_graph = Agcbstack(f=cb_funcs_graph, state="GraphStateReset", prev=None)
        self.graph.clos.set_callback_stack(cbstack_graph)

        self.graph.aginitcb(obj=self.graph, cbstack=self.graph.clos.cb)

        # After re-initialization, the extra callback should still exist since reset_callbacks was not called
        self.assertIn(extra_node_added_callback, self.graph.clos.callbacks[GraphEvent.NODE_ADDED],
                      "Extra callback should still be registered after aginitcb.")

    def test_aghide_invalid_node(self):
        node = self.graph.create_node_by_name("NonCompoundNode")
        node.collapsed = False
        node.subgraph = None

        with self.assertRaises(ValueError):
            self.graph.aghide(node)

    def test_aghide_non_collapsed_node(self):
        node = self.graph.create_node_by_name("NonCollapsedNode")
        node.collapsed = False
        node.subgraph = None

        with self.assertRaises(ValueError):
            self.graph.aghide(node)

    def test_aghide_successful(self):
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
        cb_funcs_node = CallbackFunctions(
            node_mod=lambda g, obj, state, sym: print(f"[Test Node Mod] Node '{obj.name}' modified with symbol '{sym}'.")
        )
        cb_funcs_edge = CallbackFunctions(
            edge_mod=lambda g, obj, state, sym: print(f"[Test Edge Mod] Edge '{obj.key}' modified with symbol '{sym}'.")
        )

        cbstack_node = Agcbstack(f=cb_funcs_node, state="NodeState1", prev=None)
        cbstack_edge = Agcbstack(f=cb_funcs_edge, state="EdgeState1", prev=None)

        self.graph.clos.set_callback_stack(cbstack_node)
        self.graph.clos.set_callback_stack(cbstack_edge)

        self.graph.aginitcb(obj=node_a, cbstack=cbstack_node)
        self.graph.aginitcb(obj=node_b, cbstack=cbstack_node)
        self.graph.aginitcb(obj=edge_ab, cbstack=cbstack_edge)

        # Modify node 'A'
        self.graph.agupdcb(obj=node_a, sym="color=blue")

        # Modify edge 'AB'
        self.graph.agupdcb(obj=edge_ab, sym="style=dashed")

        # Collapse subgraph
        cmpnode = self.graph.create_node_by_name("Cluster1")
        cmpnode.collapsed = True
        cmpnode.subgraph = subgraph

        # Add and save connections
        node_x = self.graph.create_node_by_name("X")
        node_y = self.graph.create_node_by_name("Y")
        edge_xc = self.graph.add_edge("X", "Cluster1", edge_name="X->C1")
        edge_cy = self.graph.add_edge("Cluster1", "Y", edge_name="C1->Y")

        cmpnode.saved_connections.append((node_x, edge_xc))
        cmpnode.saved_connections.append((node_y, edge_cy))

        # Simulate collapsing by deleting edges
        self.graph.delete_edge(edge_xc)
        self.graph.delete_edge(edge_cy)

        # Hide the subgraph
        success = self.graph.aghide(cmpnode)
        self.assertTrue(success, "aghide should return True for successful hiding.")
        self.assertTrue(self.subgraph_deleted_triggered, "subgraph_deleted callback should have been triggered.")
        self.assertNotIn("Cluster1", self.graph.subgraphs, "Subgraph should be removed from the enclosed_node.")
        self.assertFalse(self.graph.has_cmpnd, "has_cmpnd should be False after hiding the only collapsed subgraph.")
        self.assertFalse(cmpnode.collapsed, "cmpnode should be marked as uncollapsed.")

        # Check that subgraph nodes are deleted
        self.assertNotIn("A", self.graph.nodes, "Node 'A' should be deleted from the graph enclosed_node.")
        self.assertNotIn("B", self.graph.nodes, "Node 'B' should be deleted from the graph enclosed_node.")

        # Check that edges are reconnected
        self.assertIn(("X", "Y", "X->C1"), self.graph.edges, "Edge 'X->C1' should be reconnected from 'X' to 'Y'.")
        self.assertNotIn(("Cluster1", "Y", "C1->Y"), self.graph.edges, "Edge 'C1->Y' should have been deleted from the enclosed_node.")

    def tearDown(self):
        self.graph.agclose()

if __name__ == '__main__':
    unittest.main()
