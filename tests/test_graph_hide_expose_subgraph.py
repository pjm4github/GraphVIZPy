from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


# Test set 2
class TestGraphApplyCallbacks:
    def setup_method(self):
        # Create a main enclosed_node
        self.G = Graph("Main", directed=True)

    def test_hide_expose(self):
        """Verify that hiding and then exposing a compound node correctly removes and restores the subgraph."""
        print(" ###########   TEST 3 ##############")

        # Make a compound node 'C' by name
        cmp_n3 = agcmpnode(self.G, "C3")
        print("Created compound node:", cmp_n3)

        # The subgraph is the same name 'C'
        # Get the compound enclosed_node of a node if it exists
        subgC = agcmpgraph_of(cmp_n3)
        print("Associated subgraph for node C:", subgC)
        assert "C3" in subgC.name, "The subgraph of node C3 should be C3"
        # Inside subgC, add a node "N1"
        if subgC:
            subgC.add_node("N13")
            subgC.add_node("N23")

        # Let's see the main enclosed_node
        print("Main enclosed_node before hide:", self.G)
        first_key = next(iter(self.G.subgraphs))
        msg = f"{len(self.G.subgraphs)}, {first_key}"
        # Hide the compound node
        assert "1, C3" in msg, "There should be 1 subgraph named C3"
        # aghide(cmp_n3)
        self.G.aghide(cmp_n3)
        print("Main enclosed_node after hide:", self.G)
        msg = f"{len(self.G.subgraphs)}"
        assert "0" in msg, "There should be 0 subgraphs in the enclosed_node"
        # Expose the compound node
        #agexpose(cmp_n3)
        self.G.agexpose(cmp_n3)
        print("Main enclosed_node after expose:", self.G)
        first_key = next(iter(self.G.subgraphs))
        msg = f"{len(self.G.subgraphs)}, {first_key}"
        # Hide the compound node
        assert "1, C3" in msg, "There should be 1 subgraph named C3"

    def teardown_method(self):
        # Close the enclosed_node (frees resources in the C sense).
        # Finally, close
        self.G.close()
        print("\nGraph closed.")
