import pytest

from pycode.cgraph.graph import Graph
from pycode.cgraph.node import Node
from pycode.cgraph.graph_print import ascii_print_graph

class TestHideSubgraphSplicing:

    @pytest.fixture(autouse=True)
    def setup(self):
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
        subg.add_node("A")
        subg.add_node("B")

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
        """Verify that hiding a subgraph splices boundary edges and removes internal nodes and edges."""

        # 1) Perform the hide operation
        success = self.graph.aghide(self.cmpnode)
        assert success, "Hiding the cmpnode subgraph should succeed."

        # 2) Check that subgraph is removed
        assert self.subg_name not in self.graph.subgraphs, \
            f"Subgraph '{self.subg_name}' should be removed from the main graph."

        # 3) The subgraph nodes A, B should no longer be in top-level graph.nodes
        assert "A" not in self.graph.nodes, \
            "Node A (internal to subgraph) should be hidden from the main graph."
        assert "B" not in self.graph.nodes, \
            "Node B (internal to subgraph) should be hidden from the main graph."

        # 4) The internal edge (A->B) should be gone from graph.edges
        for (tail, head, ename), eobj in self.graph.edges.items():
            assert not ((tail == "A" and head == "B") or (tail == "B" and head == "A")), \
                "Internal edge A->B should no longer appear in the enclosed_node graph's edges."

        # 5) The boundary edges X->A and B->X should now be spliced to X->cmpnode and cmpnode->X
        splice_x_cmp = ("X", "CmpNode", "X->A")
        splice_cmp_x = ("CmpNode", "X", "B->X")

        # Check if the spliced edges exist
        assert splice_x_cmp in self.graph.edges, \
            "Edge crossing from X->A should be spliced to X->CmpNode."
        assert splice_cmp_x in self.graph.edges, \
            "Edge crossing from B->X should be spliced to CmpNode->X."

        # 6) Optionally confirm the compound node is marked as collapsed
        assert self.cmpnode.compound_node_data.collapsed, \
            "cmpnode should be flagged as collapsed after hiding."

        print("Hide subgraph splicing test passed. Final edges:")
        for ek, eobj in self.graph.edges.items():
            print(f"  {ek} => {eobj}")
