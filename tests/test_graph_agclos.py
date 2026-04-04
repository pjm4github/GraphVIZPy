import pytest
from pycode.cgraph.graph import Graph
from pycode.cgraph.defines import GraphEvent


class TestGraphAgclos:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.events_triggered = {
            'node_added': False,
            'edge_added': False,
            'node_deleted': False,
            'edge_deleted': False
        }

        # Define callback functions
        def node_added_callback(node):
            self.events_triggered['node_added'] = True
            print(f"[Test Callback] node_added_callback Node '{node.name}' added.")

        def edge_added_callback(edge):
            self.events_triggered['edge_added'] = True
            print(f"[Test Callback] edge_added_callback Edge '{edge.key}' added.")

        def node_deleted_callback(node):
            self.events_triggered['node_deleted'] = True
            print(f"[Test Callback] node_deleted_callback Node '{node.name}' deleted.")

        def edge_deleted_callback(edge):
            self.events_triggered['edge_deleted'] = True
            print(f"[Test Callback] edge_deleted_callback Edge '{edge.key}' deleted.")

        # Register callbacks
        self.graph.method_update(GraphEvent.NODE_ADDED, node_added_callback, action='add')
        self.graph.method_update(GraphEvent.EDGE_ADDED, edge_added_callback, action='add')
        self.graph.method_update(GraphEvent.NODE_DELETED, node_deleted_callback, action='add')
        self.graph.method_update(GraphEvent.EDGE_DELETED, edge_deleted_callback, action='add')

        yield

        self.graph.agclose()

    def test_add_node_triggers_callback(self):
        """Verify that adding a node triggers the node_added callback."""
        node = self.graph.create_node_by_name("A")
        assert self.events_triggered['node_added'], "node_added callback should have been triggered."

    def test_add_edge_triggers_callback(self):
        """Verify that adding an edge triggers the edge_added callback."""
        edge = self.graph.add_edge("A", "B", edge_name="AB")
        assert self.events_triggered['edge_added'], "edge_added callback should have been triggered."

    def test_delete_node_triggers_callback(self):
        """Verify that deleting a node triggers the node_deleted callback."""
        node = self.graph.create_node_by_name("A")
        self.events_triggered['node_added'] = False  # Reset
        self.graph.method_delete(node)
        assert self.events_triggered['node_deleted'], "node_deleted callback should have been triggered."

    def test_delete_edge_triggers_callback(self):
        """Verify that deleting an edge triggers the edge_deleted callback."""
        edge = self.graph.add_edge("A", "B", edge_name="AB")
        self.events_triggered['edge_added'] = False  # Reset
        self.graph.method_delete(edge)
        assert self.events_triggered['edge_deleted'], "edge_deleted callback should have been triggered."

    def test_callbacks_disabled(self):
        """Verify that callbacks are not triggered when temporarily disabled."""
        node = self.graph.create_node_by_name("A")
        self.events_triggered['node_added'] = False  # Reset
        with self.graph.clos.temporary_callback_state(enable=False):
            self.graph.create_node_by_name("B")
        assert not self.events_triggered['node_added'], "Callback should not be triggered when disabled."

    def test_callbacks_reenabled(self):
        """Verify that callbacks fire again after being re-enabled."""
        node = self.graph.create_node_by_name("A")
        self.events_triggered['node_added'] = False  # Reset
        with self.graph.clos.temporary_callback_state(enable=False):
            self.graph.create_node_by_name("B")
        self.graph.clos.enable_callbacks()
        self.graph.create_node_by_name("C")
        assert self.events_triggered['node_added'], "Callback should be triggered after re-enabling."

    def test_unregister_callback(self):
        """Verify that unregistered callbacks are no longer triggered."""
        # Assuming we have access to the callback functions, otherwise this test needs to be adjusted
        # For demonstration, we'll unregister one callback and test
        self.events_triggered['node_added'] = False
        def dummy_callback(node):
            self.events_triggered['node_added'] = True
        self.graph.method_update(GraphEvent.NODE_ADDED, dummy_callback, action='remove-all')
        self.graph.method_update(GraphEvent.NODE_ADDED, dummy_callback, action='add')
        self.graph.method_update(GraphEvent.NODE_ADDED, dummy_callback, action='remove')
        node = self.graph.create_node_by_name("D")
        assert not self.events_triggered['node_added'], "Unregistered callback should not be triggered."
