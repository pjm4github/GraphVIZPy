import pytest
from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, Agclos


class TestAgclosCallbacks:
    @pytest.fixture(autouse=True)
    def setup(self):
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

        yield

        # Reset the callbacks after each test
        self.clos.reset()

    def test_invoke_node_added_callbacks(self):
        """Test that node_added callbacks are invoked on node addition."""
        # Simulate node addition
        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("TestNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node)
        assert self.events_triggered['node_added']

    def test_invoke_edge_added_callbacks(self):
        """Test that edge_added callbacks are invoked on edge addition."""
        # Simulate edge addition
        class MockEdge:
            def __init__(self, key, tail, head):
                self.key = key
                self.tail = tail
                self.head = head

        edge = MockEdge("TestEdge", "A", "B")
        self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, edge)
        assert self.events_triggered['edge_added']

    def test_invoke_node_deleted_callbacks(self):
        """Test that node_deleted callbacks are invoked on node deletion."""
        # Simulate node deletion
        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("TestNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_DELETED, node)
        assert self.events_triggered['node_deleted']

    def test_invoke_edge_deleted_callbacks(self):
        """Test that edge_deleted callbacks are invoked on edge deletion."""
        # Simulate edge deletion
        class MockEdge:
            def __init__(self, key, tail, head):
                self.key = key
                self.tail = tail
                self.head = head

        edge = MockEdge("TestEdge", "A", "B")
        self.clos.invoke_callbacks(GraphEvent.EDGE_DELETED, edge)
        assert self.events_triggered['edge_deleted']

    def test_unregister_callback(self):
        """Test that an unregistered callback is not invoked."""
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
        assert not self.events_triggered['node_added']

    def test_disable_callbacks(self):
        """Test that disabled callbacks are not invoked."""
        # Disable callbacks and ensure no callbacks are invoked
        self.clos.disable_callbacks()

        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("DisabledCallbackNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node)
        assert not self.events_triggered['node_added']

    def test_enable_callbacks(self):
        """Test that re-enabled callbacks are invoked after being disabled."""
        # Disable and then enable callbacks, ensuring they are invoked
        self.clos.disable_callbacks()
        self.clos.enable_callbacks()

        class MockNode:
            def __init__(self, name):
                self.name = name

        node = MockNode("EnabledCallbackNode")
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node)
        assert self.events_triggered['node_added']

    def test_unknown_event_registration(self):
        """Test that registering a callback for an unknown event raises ValueError."""
        # Attempt to register a callback for an unknown event
        def unknown_callback(obj):
            pass

        with pytest.raises(ValueError):
            self.clos.register_callback(GraphEvent.UNKNOWN_EVENT, unknown_callback)

    def test_unknown_event_invocation(self):
        """Test that invoking callbacks for an unknown event raises ValueError."""
        # Attempt to invoke callbacks for an unknown event
        with pytest.raises(ValueError):
            self.clos.register_callback(GraphEvent.UNKNOWN_EVENT, lambda x: x)
            self.clos.invoke_callbacks(GraphEvent.UNKNOWN_EVENT, None)

    def test_node_added_callback(self):
        """Test that a registered node_added callback is invoked via invoke_node_added."""
        def callback(node):
            self.callback_invoked = True

        self.clos.register_node_added_callback(callback)
        node = Node(name="TestNode", graph=None, id_=1, seq=1, root=None)
        self.clos.invoke_node_added(node)
        assert self.callback_invoked

    def test_callbacks_disabled(self):
        """Test that node_added callback is not invoked when callbacks are disabled."""
        def callback(node):
            self.callback_invoked = True

        self.clos.register_node_added_callback(callback)
        self.clos.disable_callbacks()
        node = Node(name="TestNode", graph=None, id_=1, seq=1, root=None)
        self.clos.invoke_node_added(node)
        assert not self.callback_invoked
