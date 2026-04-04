from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestAgraphMemoryManagement:
    def setup_method(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()
        self.graph.agdtopen_subgraph_dict()

    def test_agdtopen_and_agdtclose(self):
        """Verify that the dictionary can be opened and then closed successfully."""
        # Ensure dictionary is open
        assert self.graph.dict is not None, "Dictionary should be initialized."
        # Close the dictionary
        closed = self.graph.agdtclose()
        assert closed, "Dictionary should close successfully."
        assert self.graph.dict is None, "Dictionary should be set to None after closing."

    def test_agdtdelete_without_dict(self):
        """Verify that deletion fails gracefully when the dictionary is not initialized."""
        # Close the dictionary first
        self.graph.agdtclose()
        # Attempt to delete from a closed dictionary
        result = self.graph.agdtdelete("NonExistentObject")
        assert not result, "Deletion should fail when dictionary is not initialized."

    def test_agdtdelete_with_existing_object(self):
        """Verify that an existing object can be deleted from the dictionary."""
        # Add an object to the dictionary
        obj = "TestObject"
        self.graph.dict.add(obj, "Value")
        # Delete the object
        result = self.graph.agdtdelete(obj)
        assert result, "Deletion should succeed for existing objects."
        # Ensure the object is deleted
        assert obj not in self.graph.dict.store, "Object should no longer exist in the dictionary."

    def test_agdtdisc(self):
        """Verify that the discipline can be updated on both the graph and its dictionary."""
        # Create a new discipline
        new_disc = AgIdDisc()  # Use the default ID discipline
        self.graph.agdtdisc(new_disc)
        assert self.graph.disc == new_disc, "Discipline should be updated to the new discipline."
        if self.graph.dict:
            assert self.graph.dict.discipline == new_disc, "Dictionary's discipline should be updated."

class TestAgraphSubgraphManagement:
    def setup_method(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()
        self.graph.agdtopen_subgraph_dict()

    def test_create_subgraph_by_name(self):
        """Verify that a subgraph can be created and found by name."""
        subg = self.graph.get_or_create_subgraph_by_name(name="Cluster1", create_if_missing=True)
        assert subg is not None, "Subgraph should be created."
        assert "Cluster1" in self.graph.subgraphs, "Subgraph should exist in subgraphs."
        assert subg.id in self.graph.id_to_subgraph.keys(), "Subgraph should exist in id_to_subgraph."

    def test_create_subgraph_by_id(self):
        """Verify that a subgraph can be created and found by ID."""
        subg_id = 4
        self.graph.agallocid(subg_id)
        subg = self.graph.get_or_create_subgraph_by_id(subg_id=subg_id, create_if_missing=True)
        assert subg is not None, "Subgraph should be created."
        assert subg.id == subg_id, "Subgraph ID should match allocated ID."
        assert subg_id in self.graph.id_to_subgraph.keys(), "Subgraph should exist in id_to_subgraph."

    def test_delete_subgraph_by_name(self):
        """Verify that a subgraph can be deleted by name."""
        subg = self.graph.get_or_create_subgraph_by_name(name="Cluster1", create_if_missing=True)
        result = self.graph.agdtdelete_subgraph_by_name("Cluster1")
        assert result, "Subgraph deletion should succeed."
        assert "Cluster1" not in self.graph.subgraphs, "Subgraph should be removed from subgraphs."
        assert subg.id not in self.graph.id_to_subgraph.keys(), "Subgraph should be removed from id_to_subgraph."

    def test_delete_nonexistent_subgraph(self):
        """Verify that deleting a non-existent subgraph returns False."""
        result = self.graph.agdtdelete_subgraph_by_name("NonExistentCluster")
        assert not result, "Deletion should fail for non-existent subgraphs."

    def teardown_method(self):
        self.graph.agdtclose()
