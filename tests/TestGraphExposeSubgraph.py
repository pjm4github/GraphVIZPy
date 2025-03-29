import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphExposeSubgraph(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.subgraph_added_triggered = False
        self.subgraph_deleted_triggered = False

        def subgraph_added_callback(subgraph):
            self.subgraph_added_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' added.")

        def subgraph_deleted_callback(subgraph):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' deleted.")

        self.graph.method_update(GraphEvent.SUBGRAPH_ADDED, subgraph_added_callback, action='add')
        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, subgraph_deleted_callback, action='add')

    def test_agexpose_triggers_callback(self):
        subgraph = self.graph.expose_subgraph("Cluster1")
        self.assertTrue(self.subgraph_added_triggered, "subgraph_added callback should have been triggered.")

    def test_agexpose_integrates_subgraph(self):
        # Collapse a subgraph first
        subgraph = self.graph.expose_subgraph("Cluster1")
        cmpnode = self.graph.create_node_by_name("Cluster1")
        cmpnode.collapsed = True
        cmpnode.subgraph = subgraph

        # Add and save connections
        node_x = self.graph.create_node_by_name("X")
        node_y = self.graph.create_node_by_name("Y")
        edge_xc = self.graph.add_edge("X", "Cluster1", edge_name="X->C1")
        edge_cy = self.graph.add_edge("Cluster1", "Y", edge_name="C1->Y")
        edge_xc.saved_from = node_x
        edge_cy.saved_to = node_y
        cmpnode.saved_connections.append((node_x, edge_xc))
        cmpnode.saved_connections.append((node_y, edge_cy))

        # Delete edges connected to cmpnode (simulate collapse)
        self.graph.delete_edge(edge_xc)
        self.graph.delete_edge(edge_cy)

        # Reset callback flags
        self.subgraph_added_triggered = False

        # Expose the subgraph
        success = self.graph.agexpose(cmpnode)
        self.assertTrue(success, "agexpose should return True for successful exposure.")
        self.assertFalse(cmpnode.collapsed, "cmpnode should be marked as uncollapsed after exposure.")

    def tearDown(self):
        self.graph.agclose()

if __name__ == '__main__':
    unittest.main()