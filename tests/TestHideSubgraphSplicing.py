import unittest

from refactored.CGGraph import Graph
from refactored.CGNode import Node
from tests.GraphPrint import ascii_print_graph

class TestHideSubgraphSplicing(unittest.TestCase):

    def setUp(self):
        """
        Create a 'graph' with:
          - cmpnode (the compound node)
          - A, B (inside cmpnode's subgraph)
          - X (external node)
        Then add edges crossing boundaries and an internal edge.
        """
        # 1) Create the main graph
        self.graph = Graph(name="MainGraph")

        # 2) Add the compound node but not hidden yet
        self.cmpnode = self.graph.add_node("CmpNode")

        # 3) Create a subgraph for cmpnode
        self.subg_name = "SubgraphS"
        subg = self.graph.create_subgraph(self.subg_name, enclosed_node=self.cmpnode)

        # 4) Add subgraph-internal nodes: A, B
        # self.nodeA = Node(name="A", graph=self.subg)
        subg.add_node("A")  # nodes["A"] = self.nodeA
        # self.nodeB = Node(name="B", graph=self.subg)
        subg.add_node("B")  # nodes["B"] = self.nodeB

        # 5) Add an external node X in the main graph
        nodeX = self.graph.add_node('X')

        # 6) Add crossing edges: X->A, B->X
        edge_XA = self.graph.add_edge("X", "A", edge_name="X->A")
        edge_BX = self.graph.add_edge("B", "X", edge_name="B->X")

        # 7) Add an internal edge: A->B
        edge_AB = self.graph.add_edge("A", "B", edge_name="A->B")

        # At this point, "A, B" are subgraph nodes, "X" is top-level,
        # "X->A" and "B->X" cross the boundary, and "A->B" is internal.

        print(f"Graph structure after graph created")
        ascii_print_graph(self.graph)

    def test_hide_subgraph_splicing(self):
        """
        Hide the subgraph owned by cmpnode.
        Expect:
          - Edges X->A and B->X get spliced to X->cmpnode and cmpnode->X.
          - Internal edge A->B removed from the enclosed_node.
          - A, B removed or hidden from the top-level.
          - SubgraphS removed from graph.subgraphs.
        """

        # 1) Perform the hide operation
        #    This is where you call your 'aghide' or 'hide_subgraph' function.
        #    For example:
        success = self.graph.aghide(self.cmpnode)
        self.assertTrue(success, "Hiding the cmpnode subgraph should succeed.")

        # 2) Check that subgraph is removed
        self.assertNotIn(self.subg_name, self.graph.subgraphs,
                         f"Subgraph '{self.subg_name}' should be removed from the main graph.")

        # 3) The subgraph nodes A, B should no longer be in top-level graph.nodes
        self.assertNotIn("A", self.graph.nodes,
                         "Node A (internal to subgraph) should be hidden from the main graph.")
        self.assertNotIn("B", self.graph.nodes,
                         "Node B (internal to subgraph) should be hidden from the main graph.")

        # 4) The internal edge (A->B) should be gone from graph.edges
        #    (assuming it's either removed or placed in a hidden set)
        for (tail, head, ename), eobj in self.graph.edges.items():
            self.assertFalse(
                (tail == "A" and head == "B") or (tail == "B" and head == "A"),
                "Internal edge A->B should no longer appear in the enclosed_node graph's edges."
            )

        # 5) The boundary edges X->A and B->X should now be spliced to X->cmpnode and cmpnode->X
        #    So we expect them to appear as edges X->CmpNode and CmpNode->X in the main graph.
        #    Let's check we find those keys in graph.edges.
        splice_x_cmp = ("X", "CmpNode", "X->A")   # Possibly the old edge_name "X->A" is reused
        splice_cmp_x = ("CmpNode", "X", "B->X")   # Possibly the old edge_name "B->X"
        # or if your code modifies the edge name, adapt accordingly

        # Check if the spliced edges exist
        self.assertIn(splice_x_cmp, self.graph.edges,
                      "Edge crossing from X->A should be spliced to X->CmpNode.")
        self.assertIn(splice_cmp_x, self.graph.edges,
                      "Edge crossing from B->X should be spliced to CmpNode->X.")

        # 6) Optionally confirm the compound node is marked as collapsed
        self.assertTrue(self.cmpnode.compound_node_data.collapsed,
                        "cmpnode should be flagged as collapsed after hiding.")

        print("Hide subgraph splicing test passed. Final edges:")
        for ek, eobj in self.graph.edges.items():
            print(f"  {ek} => {eobj}")


if __name__ == "__main__":
    unittest.main()
