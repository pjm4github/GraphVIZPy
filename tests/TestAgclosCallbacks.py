import unittest
from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, Agclos


class TestAgclosCallbacks(unittest.TestCase):
    def setUp(self):
        self.clos = Agclos()
        self.events_triggered = {
            'node_added': False,
            'edge_added': False,
            'node_deleted': False,
            'edge_deleted': False
        }
        self.callback_invoked = False

        # Define callbacks
        def node_added_callback(node):
            self.events_triggered['node_added'] = True
            print(f"[Test Callback] Node '{node.name}' added.")

        def edge_added_callback(edge):
            self.events_triggered['edge_added'] = True
            print(f"[Test Callback] Edge '{edge.key}' added.")

        def node_deleted_callback(node):
            self.events_triggered['node_deleted'] = True
            print(f"[Test Callback] Node '{node.name}' deleted.")

        def edge_deleted_callback(edge):
            self.events_triggered['edge_deleted'] = True
            print(f"[Test Callback] Edge '{edge.key}' deleted.")

        # Register callbacks
        self.clos.register_callback(GraphEvent.NODE_ADDED, node_added_callback)
        self.clos.register_callback(GraphEvent.EDGE_ADDED, edge_added_callback)
        self.clos.register_callback(GraphEvent.NODE_DELETED, node_deleted_callback)
        self.clos.register_callback(GraphEvent.EDGE_DELETED, edge_deleted_callback)

    def test_invoke_node_added_callbacks(self):
        # Simulate node addition
        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("TestNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node)
        self.assertTrue(self.events_triggered['node_added'], "node_added_callback should have been invoked.")

    def test_invoke_edge_added_callbacks(self):
        # Simulate edge addition
        class MockEdge:
            def __init__(self, key, tail, head):
                self.key = key
                self.tail = tail
                self.head = head

        edge = MockEdge("TestEdge", "A", "B")
        self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, edge)
        self.assertTrue(self.events_triggered['edge_added'], "edge_added_callback should have been invoked.")

    def test_invoke_node_deleted_callbacks(self):
        # Simulate node deletion
        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("TestNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_DELETED, node)
        self.assertTrue(self.events_triggered['node_deleted'], "node_deleted_callback should have been invoked.")

    def test_invoke_edge_deleted_callbacks(self):
        # Simulate edge deletion
        class MockEdge:
            def __init__(self, key, tail, head):
                self.key = key
                self.tail = tail
                self.head = head

        edge = MockEdge("TestEdge", "A", "B")
        self.clos.invoke_callbacks(GraphEvent.EDGE_DELETED, edge)
        self.assertTrue(self.events_triggered['edge_deleted'], "edge_deleted_callback should have been invoked.")

    def test_unregister_callback(self):
        # Unregister a callback and ensure it's not invoked

        def dummy_callback(obj):
            print("This should not be printed.")
        self.events_triggered['node_added'] = False
        self.clos.reset_callbacks()  # Reset all callbacks
        self.clos.register_callback(GraphEvent.NODE_ADDED, dummy_callback)
        self.clos.unregister_callback(GraphEvent.NODE_ADDED, dummy_callback)

        node = Node("AnotherTestNode", None)
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node)
        # The dummy_callback should not affect the events_triggered
        self.assertFalse(self.events_triggered['node_added'], "dummy_callback should have been unregistered.")

    def test_disable_callbacks(self):
        # Disable callbacks and ensure no callbacks are invoked
        self.clos.disable_callbacks()

        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("DisabledCallbackNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node)
        self.assertFalse(self.events_triggered['node_added'], "Callbacks should be disabled and not invoked.")

    def test_enable_callbacks(self):
        # Disable and then enable callbacks, ensuring they are invoked
        self.clos.disable_callbacks()
        self.clos.enable_callbacks()

        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("EnabledCallbackNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node)
        self.assertTrue(self.events_triggered['node_added'], "Callbacks should be enabled and invoked.")

    def test_unknown_event_registration(self):
        # Attempt to register a callback for an unknown event
        def unknown_callback(obj):
            pass

        with self.assertRaises(ValueError):
            self.clos.register_callback(GraphEvent.UNKNOWN_EVENT, unknown_callback)

    def test_unknown_event_invocation(self):
        # Attempt to invoke callbacks for an unknown event
        with self.assertRaises(ValueError):
            self.clos.register_callback(GraphEvent.UNKNOWN_EVENT, lambda x: x)
            self.clos.invoke_callbacks(GraphEvent.UNKNOWN_EVENT, None)

    def test_node_added_callback(self):
        def callback(node):
            self.callback_invoked = True

        self.clos.register_node_added_callback(callback)
        node = Node(name="TestNode", graph=None, id_=1, seq=1, root=None)
        self.clos.invoke_node_added(node)
        self.assertTrue(self.callback_invoked)

    def test_callbacks_disabled(self):
        def callback(node):
            self.callback_invoked = True

        self.clos.register_node_added_callback(callback)
        self.clos.disable_callbacks()
        node = Node(name="TestNode", graph=None, id_=1, seq=1, root=None)
        self.clos.invoke_node_added(node)
        self.assertFalse(self.callback_invoked)

    def tearDown(self):
        # Reset the callbacks after each test
        self.clos.reset()

if __name__ == '__main__':
    unittest.main()
