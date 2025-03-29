import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack

class TestAgraphMethods3(unittest.TestCase):
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
        self.assertIn(extra_node_added_callback, self.graph.clos.callbacks['node_added'])

        # Initialize callbacks again
        # Create a new CallbackFunctions instance without the extra callback
        cb_funcs_graph = CallbackFunctions(graph_ins=lambda g, o, s: print(f"[New Graph Init] Graph '{o.name}' initialized."))
        cbstack_graph = Agcbstack(f=cb_funcs_graph, state="GraphStateReset", prev=None)
        self.graph.clos.set_callback_stack(cbstack_graph)

        self.graph.aginitcb(obj=self.graph, cbstack=self.graph.clos.cb)
        # After re-initialization, the extra callback should still exist since reset_callbacks was not called
        self.assertIn(extra_node_added_callback, self.graph.clos.callbacks['node_added'],
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

        # Create separate callback stacks for node and edge initialization
        cb_funcs_node_custom = CallbackFunctions(node_mod=self.graph.agupdcb)
        cb_funcs_edge_custom = CallbackFunctions(edge_mod=self.graph.agupdcb)
        cbstack_node = Agcbstack(f=cb_funcs_node_custom, state="NodeState1", prev=None)
        cbstack_edge = Agcbstack(f=cb_funcs_edge_custom, state="EdgeState1", prev=None)
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

        # Define and push a custom discipline
        def custom_node_mod_callback(graph_obj: Agraph, obj: Agnode, state, sym):
            print(f"[Custom Node Modify] Node '{obj.name}' modified with state '{state}' and symbol '{sym}'.")

        cb_funcs_custom = CallbackFunctions(node_mod=custom_node_mod_callback)
        custom_disc = Agcbdisc(name="CustomDiscipline", callback_functions=cb_funcs_custom)
        self.graph.push_discipline(custom_disc, state="CustomState")

        # Modify another node to trigger custom discipline
        node_c = subgraph.create_node_by_name("C")
        self.graph.agupdcb(obj=node_c, sym="shape", cbstack=Agcbstack(f=cb_funcs_custom, state="CustomState", prev=None))

        # Pop the custom discipline
        self.graph.pop_discipline(custom_disc)

        # Collapse the subgraph
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

        # Hide the subgraph using aghide
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
        self.assertNotIn(("Cluster1_Renamed", "Y", "C1->Y"), self.graph.edges, "Edge 'C1->Y' should have been deleted from the enclosed_node.")

    def tearDown(self):
        self.graph.agclose()


if __name__ == '__main__':
    unittest.main()
