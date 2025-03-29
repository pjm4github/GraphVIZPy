import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphExposeSubgraph1(unittest.TestCase):
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

    def test_expose_subgraph_triggers_callback(self):
        subgraph = self.graph.expose_subgraph("Cluster1")
        self.assertIsNotNone(subgraph, "Subgraph should be created successfully.")
        self.assertTrue(self.subgraph_added_triggered, "subgraph_added callback should have been triggered.")

    def test_delete_subgraph_triggers_callback(self):
        subgraph = self.graph.expose_subgraph("Cluster1")
        self.subgraph_added_triggered = False  # Reset
        self.graph.method_delete(subgraph)
        self.assertTrue(self.subgraph_deleted_triggered, "subgraph_deleted callback should have been triggered.")
        self.assertNotIn("Cluster1", self.graph.subgraphs, "Subgraph should be removed from the enclosed_node.")

    def test_expose_existing_subgraph(self):
        subgraph1 = self.graph.expose_subgraph("Cluster1")
        self.subgraph_added_triggered = False  # Reset
        subgraph2 = self.graph.expose_subgraph("Cluster1")
        self.assertEqual(subgraph1, subgraph2, "Exposing an existing subgraph should return the same instance.")
        self.assertFalse(self.subgraph_added_triggered, "subgraph_added callback should not be triggered for existing subgraph.")

    def tearDown(self):
        self.graph.agclose()

if __name__ == '__main__':
    unittest.main()
