import unittest
from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc



# Test set 2
class TestGraphApplyCallbacks(unittest.TestCase):
    def setUp(self):
        # Create a main enclosed_node
        self.G = Graph("MainGraph", directed=True)

    def test_apply_callbacks(self):
        print("############# TEST SET 2 #################")

        # Add a couple of nodes
        n11 = self.G.add_node("A")
        n12 = self.G.add_node("B")

        # Add an edge
        e11 = self.G.add_edge("A", "B", "E11")

        # Add a subgraph
        sg1 = self.G.add_subgraph("Cluster1")
        sg1.add_node("A")  # same name node in subgraph
        sg1.add_node("C")

        # Add a subgraph
        sg2 = sg1.add_subgraph("Cluster2")
        sg2.add_node("A")  # same name node in subgraph
        sg2.add_node("C")

        sg3 = self.G.add_subgraph("Cluster1")

        # Demo: rename node B to X
        success = self.G.agrename(n12, "X")
        print("Nodes in main enclosed_node after rename:", list(self.G.nodes.keys()))
        self.assertIn("['A', 'X']", str(list(self.G.nodes.keys())), "Graph color is should be ['A', 'X']")

        # Demo: callback function for agapply
        def print_obj(graph, obj, arg):
            news = f"Callback has visited {obj.obj_type} '{obj}' in enclosed_node '{graph.name}'"
            print(news)
            graph.callback_news = news
            print(f"The enclosed_node with id = '{id(graph)}' has attribute 'callback_news': {hasattr(graph, 'callback_news')} ")

        print("\n=== agapply on n11 (preorder) ===")
        self.G.agapply(n11, print_obj, self, preorder=1)
        # Testing the callbacks is rather odd here. The attribute callback_news is added by
        # the callback but this isn't a clean way to test it
        print(f"callback news = {self.G.callback_news}")

        print("\n=== agapply on e11 (postorder) ===")
        self.G.agapply(e11, print_obj, self, preorder=0)

        print("\n=== agapply on enclosed_node self.G (preorder) ===")
        self.G.agapply(self.G, print_obj, self, preorder=1)

    def tearDown(self):
        # Close the enclosed_node (frees resources in the C sense).
        # Finally, close
        self.G.close()
        print("\nGraph closed.")


if __name__ == '__main__':
    unittest.main()
