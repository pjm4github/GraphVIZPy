import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphCreateSubgraph(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph")

    def test_create_regular_subgraph(self):
        subgraph = self.graph.create_subgraph("Subgraph1")
        self.assertIn("Subgraph1", self.graph.subgraphs)
        self.assertEqual(subgraph.name, "Subgraph1")
        self.assertEqual(subgraph.parent, self.graph)

    def test_create_compound_subgraph(self):
        node = self.graph.create_node_by_name("CompoundNode")
        subgraph = self.graph.create_subgraph("Subgraph_Compound", enclosed_node=node)
        self.assertIn("CompoundNode", self.graph.subgraphs)
        self.assertEqual(subgraph, self.graph.subgraphs["CompoundNode"])
        self.assertTrue(node.compound_node_data.is_compound)
        self.assertFalse(node.compound_node_data.collapsed)

    def test_duplicate_subgraph_creation(self):
        subgraph1 = self.graph.create_subgraph("Subgraph1")
        subgraph2 = self.graph.create_subgraph("Subgraph1")
        self.assertEqual(subgraph1, subgraph2)

    def test_duplicate_compound_subgraph_creation(self):
        node = self.graph.create_node_by_name("CompoundNode")
        subgraph1 = self.graph.create_subgraph("Subgraph_Compound", enclosed_node=node)
        subgraph2 = self.graph.create_subgraph("Subgraph_Compound_Duplicate", enclosed_node=node)
        self.assertEqual(subgraph1, subgraph2)


if __name__ == '__main__':
    unittest.main()
