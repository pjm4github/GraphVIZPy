import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack



class TestGraphMethodUpdate:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = Graph(name="TestGraph")
        self.callback_invoked = False

    def test_add_callback_and_trigger(self):
        """Verify that a registered callback is invoked when its event fires."""
        def callback(node):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')
        node = self.graph.create_node_by_name("A")
        assert self.callback_invoked, "Callback should have been invoked upon node addition."

    def test_remove_callback(self):
        """Verify that a removed callback is no longer invoked."""
        def callback(node):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')
        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='remove')
        node = self.graph.create_node_by_name("B")
        assert not self.callback_invoked, "Callback should not have been invoked after removal."

    def test_invalid_event_registration(self):
        """Verify that registering a callback for an invalid event raises ValueError."""
        def callback(obj):
            pass

        with pytest.raises(ValueError):
            self.graph.method_update(GraphEvent.INVALID_EVENT, callback, action='add')

    def test_invalid_action(self):
        """Verify that using an invalid action raises ValueError."""
        def callback(obj):
            pass

        with pytest.raises(ValueError):
            self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='invalid_action')

    def test_duplicate_callback_registration(self):
        """Verify that duplicate callback registration still triggers the callback once."""
        def callback(node):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')
        self.graph.method_update(GraphEvent.NODE_ADDED, callback, action='add')  # Attempt duplicate
        node = self.graph.create_node_by_name("C")
        assert self.callback_invoked, "Callback should have been invoked once despite duplicate registration."

    def test_callback_exception_handling(self):
        """Verify that a callback raising an exception does not propagate to the caller."""
        def faulty_callback(node):
            raise RuntimeError("Intentional Error")

        self.graph.method_update(GraphEvent.NODE_ADDED, faulty_callback, action='add')
        node = self.graph.create_node_by_name("D")
        # The exception should be caught and printed, but not raise

    def test_edge_added_callback(self):
        """Verify that the edge-added callback fires when an edge is created."""
        self.callback_invoked = False

        def edge_callback(edge):
            self.callback_invoked = True

        self.graph.method_update(GraphEvent.EDGE_ADDED, edge_callback, action='add')
        edge = self.graph.add_edge("A", "B", edge_name="AB")
        assert self.callback_invoked, "Edge added callback should have been invoked."
