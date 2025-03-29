import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack

# Test set 2
class TestGraphApplyCallbacks(unittest.TestCase):
    def setUp(self):
        # Create a main enclosed_node
        self.G = Graph("Main", directed=True)

    def test_hide_expose(self):
        print(" ###########   TEST 3 ##############")

        # Make a compound node 'C' by name
        cmp_n3 = agcmpnode(self.G, "C3")
        print("Created compound node:", cmp_n3)
        # Created compound node: Node(name=C3, id=2, seq=4, degree=0, centrality=0.0, attributes={})

        # The subgraph is the same name 'C'
        # Get the compound enclosed_node of a node if it exists
        subgC = agcmpgraph_of(cmp_n3)
        print("Associated subgraph for node C:", subgC)
        # Associated subgraph for node C: <Graph C3, directed=None, strict=None, nodes=0, edges=0, subgraphs=0, flatlock=True>
        self.assertIn("C3", subgC.name, "The subgraph of node C3 should be C3")
        # Inside subgC, add a node "N1"
        if subgC:
            subgC.add_node("N13")
            subgC.add_node("N23")
        
        # Let's see the main enclosed_node
        print("Main enclosed_node before hide:", self.G)
        # Main enclosed_node before hide: <Graph Main, directed=None, strict=None, nodes=1, edges=0, subgraphs=1, flatlock=True>
        first_key = next(iter(self.G.subgraphs))
        msg = f"{len(self.G.subgraphs)}, {first_key}"
        # Hide the compound node
        self.assertIn("1, C3", msg, "There should be 1 subgraph named C3")
        # aghide(cmp_n3)
        self.G.aghide(cmp_n3)
        print("Main enclosed_node after hide:", self.G)
        # Main enclosed_node after hide: <Graph Main, directed=None, strict=None, nodes=1, edges=0, subgraphs=0, flatlock=True>
        msg = f"{len(self.G.subgraphs)}"
        self.assertIn("0", msg, "There should be 0 subgraphs in the enclosed_node")
        # Expose the compound node
        #agexpose(cmp_n3)
        self.G.agexpose(cmp_n3)
        print("Main enclosed_node after expose:", self.G)
        # Main enclosed_node after expose: <Graph Main, directed=None, strict=None, nodes=3, edges=0, subgraphs=1, flatlock=True>
        first_key = next(iter(self.G.subgraphs))
        msg = f"{len(self.G.subgraphs)}, {first_key}"
        # Hide the compound node
        self.assertIn("1, C3", msg, "There should be 1 subgraph named C3")


    def tearDown(self):
        # Close the enclosed_node (frees resources in the C sense).
        # Finally, close
        self.G.close()
        print("\nGraph closed.")


if __name__ == '__main__':
    unittest.main()
