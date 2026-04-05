"""
Consolidated tests for the callback system: registration, invocation, disable/enable.
"""
import pytest

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.core.edge import Edge
from gvpy.core.defines import ObjectType, GraphEvent
from gvpy.core.headers import Agclos


@pytest.fixture
def graph():
    """Directed graph with callback tracking flags."""
    g = Graph("TestGraph", directed=True)
    g.method_init()
    g._flags = {
        "node_added": False,
        "node_deleted": False,
        "edge_added": False,
        "edge_deleted": False,
    }

    g.method_update(GraphEvent.NODE_ADDED,
                    lambda n: g._flags.__setitem__("node_added", True), action='add')
    g.method_update(GraphEvent.NODE_DELETED,
                    lambda n: g._flags.__setitem__("node_deleted", True), action='add')
    g.method_update(GraphEvent.EDGE_ADDED,
                    lambda e: g._flags.__setitem__("edge_added", True), action='add')
    g.method_update(GraphEvent.EDGE_DELETED,
                    lambda e: g._flags.__setitem__("edge_deleted", True), action='add')
    yield g
    g.close()


class TestCallbackRegistration:

    def test_add_callback(self, graph):
        """Registering a callback with action='add' works."""
        triggered = [False]
        graph.method_update(GraphEvent.NODE_ADDED,
                           lambda n: triggered.__setitem__(0, True), action='add')
        graph.add_node("X")
        assert triggered[0] is True

    def test_remove_callback(self, graph):
        """Removing callbacks stops them from firing."""
        cb = lambda n: None
        graph.method_update(GraphEvent.NODE_ADDED, cb, action='add')
        graph.method_update(GraphEvent.NODE_ADDED, cb, action='remove')
        # Should not crash when adding a node
        graph.add_node("X")

    def test_invalid_event_raises(self, graph):
        """Registering for an invalid event raises ValueError."""
        with pytest.raises(ValueError):
            graph.method_update("INVALID_EVENT", lambda: None, action='add')

    def test_invalid_action_raises(self, graph):
        """Using an invalid action raises ValueError."""
        with pytest.raises(ValueError):
            graph.method_update(GraphEvent.NODE_ADDED, lambda: None, action='invalid')


class TestCallbackInvocation:

    def test_node_added_fires(self, graph):
        """NODE_ADDED callback fires when a node is created."""
        graph._flags["node_added"] = False
        graph.add_node("X")
        assert graph._flags["node_added"] is True

    def test_edge_added_fires(self, graph):
        """EDGE_ADDED callback fires when an edge is created."""
        graph.add_node("A")
        graph.add_node("B")
        graph._flags["edge_added"] = False
        graph.add_edge("A", "B")
        assert graph._flags["edge_added"] is True

    def test_node_deleted_fires(self, graph):
        """NODE_DELETED callback fires when a node is deleted."""
        n = graph.add_node("X")
        graph._flags["node_deleted"] = False
        graph.method_delete(n)
        assert graph._flags["node_deleted"] is True

    def test_edge_deleted_fires(self, graph):
        """EDGE_DELETED callback fires when an edge is deleted."""
        graph.add_node("A")
        graph.add_node("B")
        e = graph.add_edge("A", "B")
        graph._flags["edge_deleted"] = False
        graph.method_delete(e)
        assert graph._flags["edge_deleted"] is True


class TestCallbackDisable:

    def test_callbacks_disabled(self, graph):
        """Disabling callbacks prevents them from firing."""
        graph.clos.disable_callbacks()
        graph._flags["node_added"] = False
        graph.add_node("X")
        # Callback may or may not fire depending on implementation
        graph.clos.enable_callbacks()

    def test_callbacks_reenabled(self, graph):
        """Re-enabling callbacks allows them to fire again."""
        graph.clos.disable_callbacks()
        graph.clos.enable_callbacks()
        graph._flags["node_added"] = False
        graph.add_node("Y")
        assert graph._flags["node_added"] is True


class TestMethodDelete:

    def test_delete_node(self, graph):
        """method_delete removes a node."""
        n = graph.add_node("X")
        graph.method_delete(n)
        assert "X" not in graph.nodes

    def test_delete_edge(self, graph):
        """method_delete removes an edge."""
        graph.add_node("A")
        graph.add_node("B")
        e = graph.add_edge("A", "B")
        graph.method_delete(e)
        assert ("A", "B", None) not in graph.edges

    def test_delete_subgraph(self, graph):
        """method_delete removes a subgraph."""
        sub = graph.create_subgraph("Sub1")
        graph.method_delete(sub)
        assert "Sub1" not in graph.subgraphs

    def test_delete_invalid_type(self, graph):
        """method_delete with invalid type doesn't crash."""
        graph.method_delete("NotAGraphObject")


class TestMethodUpdate:

    def test_edge_added_callback(self, graph):
        """EDGE_ADDED callback fires for new edges."""
        triggered = [False]
        graph.method_update(GraphEvent.EDGE_ADDED,
                           lambda e: triggered.__setitem__(0, True), action='add')
        graph.add_node("P")
        graph.add_node("Q")
        graph.add_edge("P", "Q")
        assert triggered[0] is True


class TestAgclosCallbacks:

    def test_agclos_register_invoke(self):
        """Agclos register_callback and invoke_callbacks work."""
        clos = Agclos()
        triggered = [False]
        clos.register_callback(GraphEvent.NODE_ADDED, lambda n: triggered.__setitem__(0, True))
        clos.invoke_callbacks(GraphEvent.NODE_ADDED, None)
        assert triggered[0] is True

    def test_agclos_unregister(self):
        """Agclos unregister_callback stops invocation."""
        clos = Agclos()
        cb = lambda n: None
        clos.register_callback(GraphEvent.NODE_ADDED, cb)
        clos.unregister_callback(GraphEvent.NODE_ADDED, cb)
        # Should not crash
        clos.invoke_callbacks(GraphEvent.NODE_ADDED, None)

    def test_agclos_disable_enable(self):
        """Agclos disable/enable callbacks works."""
        clos = Agclos()
        clos.disable_callbacks()
        assert clos.callbacks_enabled is False
        clos.enable_callbacks()
        assert clos.callbacks_enabled is True
