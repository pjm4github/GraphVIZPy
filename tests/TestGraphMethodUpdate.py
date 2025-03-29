import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack



class TestGraphMethodUpdate(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph")
        self.callback_invoked = False

    def test_add_callback_and_trigger(self):
        def callback(node):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')
        node = self.graph.create_node_by_name("A")
        self.assertTrue(self.callback_invoked, "Callback should have been invoked upon node addition.")

    def test_remove_callback(self):
        def callback(node):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')
        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='remove')
        node = self.graph.create_node_by_name("B")
        self.assertFalse(self.callback_invoked, "Callback should not have been invoked after removal.")

    def test_invalid_event_registration(self):
        def callback(obj):
            pass

        with self.assertRaises(ValueError):
            self.graph.method_update(GraphEvent.INVALID_EVENT, callback, action='add')

    def test_invalid_action(self):
        def callback(obj):
            pass

        with self.assertRaises(ValueError):
            self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='invalid_action')

    def test_duplicate_callback_registration(self):
        def callback(node):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')
        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')  # Attempt duplicate
        node = self.graph.create_node_by_name("C")
        self.assertTrue(self.callback_invoked, "Callback should have been invoked once despite duplicate registration.")

    def test_callback_exception_handling(self):
        def faulty_callback(node):
            raise RuntimeError("Intentional Error")

        self.graph.method_update(GraphEvent.NODE_ADDED, faulty_callback, action='add')
        node = self.graph.create_node_by_name("D")
        # The exception should be caught and printed, but not raise

    def test_edge_added_callback(self):
        self.callback_invoked = False

        def edge_callback(edge):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.EDGE_ADDED, edge_callback, action='add')
        edge = self.graph.add_edge("A", "B", edge_name="AB")
        self.assertTrue(self.callback_invoked, "Edge added callback should have been invoked.")

if __name__ == '__main__':
    unittest.main()
