from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack
from pycode.cgraph.graph_print import ascii_print_graph


class TestGraphHideExpose:

    def setup_method(self):
        """Create a test graph with a compound node containing an internal subgraph."""
        desc = Agdesc(directed=True, strict=False, no_loop=False)
        self.graph = Graph(name="MainGraph", description=desc)

        # Create a "compound node" in the main enclosed_node.
        self.compound_node_name = "CompoundN"
        self.main_node = self.graph.add_node(self.compound_node_name)
        self.subgraph_name = "SubgInsideCompound"

        # Convert that node into a compound node with an internal subgraph
        self.subg = self.graph.create_subgraph_as_compound_node(
            name=self.subgraph_name,
            compound_node=self.main_node
        )

        # Add a couple of nodes inside the subgraph:
        self.inner_node1 = self.subg.add_node("Inner1")
        self.inner_node2 = self.subg.add_node("Inner2")
        # Create an edge inside the subgraph:
        self.subg.add_edge("Inner1", "Inner2", edge_name="In1->In2")

        # Also create an "external" node in the main enclosed_node, connected to the compound node:
        self.external_node = self.graph.add_node("ExternalA")
        self.ext_edge = self.graph.add_edge("ExternalA", self.compound_node_name, edge_name="Ext->Compound")

        # Confirm initial conditions
        assert self.compound_node_name in self.graph.nodes
        assert self.subgraph_name in self.graph.subgraphs
        assert "Inner1" in self.subg.nodes
        assert "Inner2" in self.subg.nodes
        assert "ExternalA" in self.graph.nodes

    def test_aghide(self):
        """Verify that aghide removes the subgraph and hides internal nodes while preserving external edges."""
        cmpnode = self.main_node  # The compound node
        ascii_print_graph(self.graph)
        # Ensure subgraph is currently visible
        assert self.subgraph_name in self.graph.subgraphs, \
            "Subgraph should be visible before hiding."

        # Call aghide
        hide_result = self.graph.aghide(cmpnode)
        assert hide_result, "aghide should return True on success."

        # After hiding:
        # 1) The subgraph should be removed from self.enclosed_node.subgraphs
        assert self.subgraph_name not in self.graph.subgraphs, \
            "Subgraph should no longer appear in the enclosed_node's subgraphs after hiding."

        # 2) Nodes inside the subgraph may be "hidden" or removed from enclosed_node's node dictionary
        assert "Inner1" not in self.graph.nodes, \
            "Inner1 should be hidden/removed from the enclosed_node's node dictionary."
        assert "Inner2" not in self.graph.nodes, \
            "Inner2 should be hidden/removed from the enclosed_node's node dictionary."

        # 3) External edges that originally connected to nodes in the subgraph might be spliced
        ext_edge_key = ("ExternalA", self.compound_node_name, "Ext->Compound")
        assert ext_edge_key in self.graph.edges, \
            "External edge Ext->Compound should still exist, spliced or not, depending on design."

        ascii_print_graph(self.graph)
        # 4) The compound_node_data might be marked collapsed/hidden

    def test_agexpose(self):
        """Verify that agexpose restores a hidden subgraph and its internal nodes after aghide."""
        cmpnode = self.main_node

        # First hide the subgraph
        hide_result = self.graph.aghide(cmpnode)
        assert hide_result, "aghide should succeed before we test agexpose."

        # Now call agexpose
        expose_result = self.graph.agexpose(cmpnode)
        assert expose_result, "agexpose should return True on success."

        # After exposing:
        # 1) The subgraph should reappear in the enclosed_node's subgraphs
        assert self.subgraph_name in self.graph.subgraphs, \
            "Subgraph should reappear in the enclosed_node's subgraphs after agexpose."

        # 2) The internal nodes of that subgraph should also be restored
        assert "Inner1" in self.subg.nodes, \
            "Inner1 should be restored to the subgraph nodes."
        assert "Inner2" in self.subg.nodes, \
            "Inner2 should be restored to the subgraph nodes."

        # 3) Any external edges spliced to the compound node might be restored to their original connections

        # 4) The compound node data might no longer be hidden
        assert not cmpnode.compound_node_data.collapsed, \
            "Compound node's data should be marked un-hidden after agexpose."
