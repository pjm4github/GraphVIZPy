import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestSubgraphMethods:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()

        # Register callbacks
        self.subgraph_added_triggered = False
        self.subgraph_deleted_triggered = False

        def on_subgraph_added(subg):
            self.subgraph_added_triggered = True
            print(f"[Test Callback] Subgraph '{subg.name}' has been added.")

        def on_subgraph_deleted(subg):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subg.name}' has been deleted.")

        self.graph.method_update(GraphEvent.SUBGRAPH_ADDED, on_subgraph_added, action='add')
        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, on_subgraph_deleted, action='add')

        yield

        self.graph.agclose()

    def test_create_and_retrieve_subgraph_by_name(self):
        """Verify creating a subgraph by name and retrieving it returns the same object."""
        # Create a subgraph by name with cflag=True
        subg = self.graph.agsubg(name="Cluster1", cflag=True)
        assert subg is not None, "Failed to create subgraph 'Cluster1'."
        assert subg.name == "Cluster1", "Subgraph name mismatch."
        assert self.subgraph_added_triggered, "subgraph_added callback was not triggered."
        self.subgraph_added_triggered = False  # Reset flag

        # Retrieve the same subgraph by name
        retrieved_subg = self.graph.agsubg(name="Cluster1", cflag=False)
        assert subg == retrieved_subg, "Retrieved subgraph does not match the created one."

    def test_create_subgraph_by_id(self):
        """Verify creating a subgraph by ID and retrieving it by ID returns the same object."""
        # Create a subgraph by ID with cflag=True
        subg = self.graph.agidsubg(id_=2, cflag=True)
        assert subg is not None, "Failed to create subgraph with ID 2."
        assert subg.id == 2, "Subgraph ID mismatch."
        assert self.subgraph_added_triggered, "subgraph_added callback was not triggered."
        self.subgraph_added_triggered = False  # Reset flag

        # Retrieve the same subgraph by ID
        retrieved_subg = self.graph.agfindsubg_by_id(2)
        assert subg == retrieved_subg, "Retrieved subgraph does not match the created one."

    def test_retrieve_nonexistent_subgraph_without_creation(self):
        """Verify that retrieving a non-existent subgraph without cflag returns None."""
        # Attempt to retrieve a non-existing subgraph without creation
        subg = self.graph.agidsubg(id_=3, cflag=False)
        assert subg is None, "Non-existent subgraph should return None."

    def test_retrieve_nonexistent_subgraph_with_creation(self):
        """Verify that retrieving a non-existent subgraph with cflag creates it."""
        # Attempt to retrieve a non-existing subgraph with creation
        subg = self.graph.agidsubg(id_=3, cflag=True)
        assert subg is not None, "Failed to create subgraph with ID 3."
        assert subg.id == 3, "Subgraph ID mismatch."
        assert self.subgraph_added_triggered, "subgraph_added callback was not triggered."
        self.subgraph_added_triggered = False  # Reset flag

    def test_iterate_subgraphs(self):
        """Verify that iterating over subgraphs returns them in creation order."""
        # Create multiple subgraphs
        self.graph.agsubg(name="Cluster1", cflag=True)
        self.graph.agsubg(name="Cluster2", cflag=True)
        self.graph.agsubg(name="Cluster3", cflag=True)

        # Iterate over subgraphs
        first_subg = self.graph.agfstsubg()
        assert first_subg is not None, "No subgraphs found during iteration."

        subg_names = []
        current_subg = first_subg
        while current_subg:
            subg_names.append(current_subg.name)
            current_subg = self.graph.agnxtsubg(current_subg)

        expected_names = ["Cluster1", "Cluster2", "Cluster3"]
        assert subg_names == expected_names, "Subgraph iteration order mismatch."

    def test_delete_subgraph(self):
        """Verify that deleting a subgraph removes it and triggers the callback."""
        # Create a subgraph
        subg = self.graph.agsubg(name="Cluster1", cflag=True)
        assert subg is not None, "Failed to create subgraph 'Cluster1'."

        # Delete the subgraph
        success = self.graph.agdelsubg(subg)
        assert success, "Failed to delete subgraph 'Cluster1'."
        assert self.subgraph_deleted_triggered, "subgraph_deleted callback was not triggered."

        # Ensure the subgraph is no longer retrievable
        retrieved_subg = self.graph.agfindsubg_by_id(subg.id)
        assert retrieved_subg is None, "Deleted subgraph should not be retrievable."

    def test_delete_nonexistent_subgraph(self):
        """Verify that deleting a non-existent subgraph returns False without triggering callbacks."""
        # Create a fake subgraph (not registered)
        fake_subg = Graph(name="FakeSubgraph")
        fake_subg.id = 999  # Assign an ID that hasn't been used
        fake_subg.parent = None

        # Attempt to delete the fake subgraph
        success = self.graph.agdelsubg(fake_subg)
        assert not success, "Deleting a non-existent subgraph should return False."
        assert not self.subgraph_deleted_triggered, "subgraph_deleted callback should not be triggered."
