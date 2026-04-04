import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphExposeSubgraph1:
    @pytest.fixture(autouse=True)
    def setup(self):
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
        yield
        self.graph.agclose()

    def test_expose_subgraph_triggers_callback(self):
        """Verify that exposing a new subgraph triggers the subgraph_added callback."""
        subgraph = self.graph.expose_subgraph("Cluster1")
        assert subgraph is not None, "Subgraph should be created successfully."
        assert self.subgraph_added_triggered, "subgraph_added callback should have been triggered."

    def test_delete_subgraph_triggers_callback(self):
        """Verify that deleting a subgraph triggers the subgraph_deleted callback."""
        subgraph = self.graph.expose_subgraph("Cluster1")
        self.subgraph_added_triggered = False  # Reset
        self.graph.method_delete(subgraph)
        assert self.subgraph_deleted_triggered, "subgraph_deleted callback should have been triggered."
        assert "Cluster1" not in self.graph.subgraphs, "Subgraph should be removed from the enclosed_node."

    def test_expose_existing_subgraph(self):
        """Verify that exposing an already-existing subgraph returns the same instance without re-triggering the callback."""
        subgraph1 = self.graph.expose_subgraph("Cluster1")
        self.subgraph_added_triggered = False  # Reset
        subgraph2 = self.graph.expose_subgraph("Cluster1")
        assert subgraph1 == subgraph2, "Exposing an existing subgraph should return the same instance."
        assert not self.subgraph_added_triggered, "subgraph_added callback should not be triggered for existing subgraph."
