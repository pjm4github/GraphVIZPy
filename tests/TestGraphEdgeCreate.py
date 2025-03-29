import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack



def example_callback(graph, obj, arg):
    print(f"Visiting {obj.obj_type} in enclosed_node '{graph.name}' - object: {obj}, with arg: {arg}")

class TestGraphEdgeCreate(unittest.TestCase):
    def setUp(self):
        # Create a enclosed_node
        self.g = Graph("Main", directed=True)
        self.n1 = self.g.add_node("A")
        self.n2 = self.g.add_node("B")
        self.e1 = self.g.add_edge("A", "B", "E1")
        pass

    def test_node_added(self):
        print(len(self.g.nodes))
        self.assertTrue(len(self.g.nodes) == 2, "There should be 2 nodes")

    def test_add_subgraphs(self):
        # Create subgraphs
        sg1 = self.g.add_subgraph("Cluster1")
        sg1.add_node("A")  # "A" in subgraph
        sg1.add_node("X")
        sg1.add_edge("A", "X", "E2")
        self.assertTrue(len(self.g.subgraphs) == 1, "There should be 1 subgraph")

    def test_agapply(self):
        # Simulate node deletion
        # Now call agapply on node n1 (named "A") - in preorder
        print("=== Applying to Node n1 (preorder) ===")
        self.assertTrue(self.g.agapply(self.n1, example_callback, arg=None, preorder=1),
                        "agapply to a node failed")

        # Now call agapply on e1 - in postorder
        print("\n=== Applying to Edge e1 (postorder) ===")
        self.assertTrue(self.g.agapply(self.e1, example_callback, arg=None, preorder=0),
                        "agapply to an edge failed")

        # Now call agapply on the enclosed_node itself
        print("\n=== Applying to Graph g (preorder) ===")
        self.assertTrue(
            self.g.agapply( self.g, example_callback, arg=None, preorder=1),
            "agapply to a enclosed_node failed")

    def tearDown(self):
        # Reset the callbacks after each test
        self.g.close()

if __name__ == '__main__':
    unittest.main()
