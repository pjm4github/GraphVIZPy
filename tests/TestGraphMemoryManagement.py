import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestAgraphMemoryManagement(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()
        self.graph.agdtopen_subgraph_dict()

    def test_agdtopen_and_agdtclose(self):
        # Ensure dictionary is open
        self.assertIsNotNone(self.graph.dict, "Dictionary should be initialized.")
        # Close the dictionary
        closed = self.graph.agdtclose()
        self.assertTrue(closed, "Dictionary should close successfully.")
        self.assertIsNone(self.graph.dict, "Dictionary should be set to None after closing.")

    def test_agdtdelete_without_dict(self):
        # Close the dictionary first
        self.graph.agdtclose()
        # Attempt to delete from a closed dictionary
        result = self.graph.agdtdelete("NonExistentObject")
        self.assertFalse(result, "Deletion should fail when dictionary is not initialized.")

    def test_agdtdelete_with_existing_object(self):
        # Add an object to the dictionary
        obj = "TestObject"
        self.graph.dict.add(obj, "Value")
        # Delete the object
        result = self.graph.agdtdelete(obj)
        self.assertTrue(result, "Deletion should succeed for existing objects.")
        # Ensure the object is deleted
        self.assertNotIn(obj, self.graph.dict.store, "Object should no longer exist in the dictionary.")

    def test_agdtdisc(self):
        # Create a new discipline
        new_disc = AgIdDisc()  # Use the default ID discipline
        self.graph.agdtdisc(new_disc)
        self.assertEqual(self.graph.disc, new_disc, "Discipline should be updated to the new discipline.")
        if self.graph.dict:
            self.assertEqual(self.graph.dict.discipline, new_disc, "Dictionary's discipline should be updated.")

class TestAgraphSubgraphManagement(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()
        self.graph.agdtopen_subgraph_dict()

    def test_create_subgraph_by_name(self):
        subg = self.graph.get_or_create_subgraph_by_name(name="Cluster1", create_if_missing=True)
        self.assertIsNotNone(subg, "Subgraph should be created.")
        self.assertIn("Cluster1", self.graph.subgraphs, "Subgraph should exist in subgraphs.")
        self.assertIn(subg.id, self.graph.id_to_subgraph.keys(), "Subgraph should exist in id_to_subgraph.")

    def test_create_subgraph_by_id(self):
        subg_id = 4
        self.graph.agallocid(subg_id)
        subg = self.graph.get_or_create_subgraph_by_id(subg_id=subg_id, create_if_missing=True)
        self.assertIsNotNone(subg, "Subgraph should be created.")
        self.assertEqual(subg.id, subg_id, "Subgraph ID should match allocated ID.")
        self.assertIn(subg_id, self.graph.id_to_subgraph.keys(), "Subgraph should exist in id_to_subgraph.")

    def test_delete_subgraph_by_name(self):
        subg = self.graph.get_or_create_subgraph_by_name(name="Cluster1", create_if_missing=True)
        result = self.graph.agdtdelete_subgraph_by_name("Cluster1")
        self.assertTrue(result, "Subgraph deletion should succeed.")
        self.assertNotIn("Cluster1", self.graph.subgraphs, "Subgraph should be removed from subgraphs.")
        self.assertNotIn(subg.id, self.graph.id_to_subgraph.keys(), "Subgraph should be removed from id_to_subgraph.")

    def test_delete_nonexistent_subgraph(self):
        result = self.graph.agdtdelete_subgraph_by_name("NonExistentCluster")
        self.assertFalse(result, "Deletion should fail for non-existent subgraphs.")

    def tearDown(self):
        self.graph.agdtclose()


if __name__ == '__main__':
    unittest.main()
