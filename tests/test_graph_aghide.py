import pytest

from pycode.cgraph.graph import Graph
from pycode.cgraph.defines import GraphEvent
from pycode.cgraph.headers import Agdesc
from pycode.cgraph.graph_print import ascii_print_graph


class TestGraphAghide:

    @pytest.fixture(autouse=True)
    def setup(self):
        desc = Agdesc(directed=True, strict=False, no_loop=False)
        self.graph = Graph(name="TestGraph", directed=True, description=desc)
        # print(f"Starting graph structure:")
        # ascii_print_graph(self.graph)

        self.subgraph_deleted_triggered = False
        self.cmpnode = self.graph.add_node("CompoundNode")
        # print(f"Graph structure after adding CompoundNode:")
        # ascii_print_graph(self.graph)
        self.node_A = self.graph.add_node("A")

        def subgraph_deleted_callback(subgraph):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' deleted.")

        # Convert this node into a compound node by creating a subgraph
        # that it owns. (In your code, you might do create_subgraph_as_compound_node
        # or similar.)

        self.subg_name = "FirstSubgraph"
        self.subg = self.graph.create_subgraph_as_compound_node(
            name=self.subg_name,
            compound_node=self.cmpnode
        )
        # print(f"Graph structure after adding SubgraphInsideCompound:")
        # ascii_print_graph(self.graph)

        # Add some nodes to the subgraph
        self.inner_node1 = self.subg.add_node("Inner1")
        self.inner_node2 = self.subg.add_node("Inner2")
        # Maybe add an edge inside the subgraph
        self.subg.add_edge("Inner1", "Inner2", "In1->In2")
        print(f"Graph structure after setup")
        ascii_print_graph(self.graph)
        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, subgraph_deleted_callback, action='add')

        yield

        self.graph.agclose()

    def test_a1_subgraph_create_hide(self):
        """Verify subgraph and its inner nodes exist after creation."""
        print(">>>> Testing subgraph creation")
        assert self.subg_name in self.graph.subgraphs, \
            "Subgraph should be in enclosed_node graph before hiding."
        # Confirm the subgraph nodes are recognized
        assert "Inner1" in self.subg.nodes
        assert "Inner2" in self.subg.nodes

    def test_a2_aghide_and_validate_hidden(self):
        """Test that aghide hides subgraph nodes and agexpose restores them."""
        # Call aghide on the compound node
        print(">>>> Testing aghide and validate hidden subgraph")
        result = self.graph.aghide(self.cmpnode)
        print(f"Graph structure after hiding {self.cmpnode.name}, inner nodes and an inner edge:")
        ascii_print_graph(self.graph)
        assert result, "aghide should return True upon success."

        # 1) The subgraph should no longer appear in main_graph.subgraphs
        assert self.subg_name not in self.graph.subgraphs, \
            "Subgraph should be removed from enclosed_node's subgraphs after hiding."

        # 2) The subgraph's internal nodes should be hidden.
        hidden_nodes = self.graph.cmp_graph_data.hidden_node_set
        assert "Inner1" in hidden_nodes, \
            "Inner1 should be in the main graph's hidden_node_set after aghide."
        assert "Inner2" in hidden_nodes, \
            "Inner2 should be in the main graph's hidden_node_set after aghide."

        # 3) The compound node record might be marked as collapsed/hidden
        assert self.cmpnode.compound_node_data.collapsed, \
            "cmpnode should be flagged as collapsed after aghide."

        expose_ok = self.graph.agexpose(self.cmpnode)
        print(f"Graph structure after exposing hidden node {self.cmpnode.name}, inner nodes and an inner edge:")
        ascii_print_graph(self.graph)

        assert expose_ok, "agexpose/unhide should return True on success."

        # Verify the subgraph is restored to enclosed_node's subgraphs
        assert self.subg_name in self.graph.subgraphs, \
            "Subgraph should be restored after agexpose/unhide."
        # Verify the previously hidden nodes are now visible again
        hidden_nodes = self.graph.cmp_graph_data.hidden_node_set
        assert "Inner1" not in hidden_nodes, \
            "Inner1 should be removed from hidden set after unhide."
        assert "Inner2" not in hidden_nodes, \
            "Inner2 should be removed from hidden set after unhide."

        # The compound node should no longer be flagged as collapsed
        assert not self.cmpnode.compound_node_data.collapsed, \
            "cmpnode should no longer be collapsed after unhide/expose."

    def test_a3_aghide_and_unhide(self):
        """Test hide then expose round-trip restores subgraph and node visibility."""
        print(">>>> Testing aghide and validate hidden subgraph")
        print(f"Compound graph structure after setup")
        ascii_print_graph(self.graph)
        # First hide
        hide_ok = self.graph.aghide(self.cmpnode)
        assert hide_ok, "aghide should succeed."
        print(f"Compound graph structure after aghide")
        ascii_print_graph(self.graph)
        # (Optional) Now 'unhide' or 'agexpose' if your code supports it
        expose_ok = self.graph.agexpose(self.cmpnode)
        assert expose_ok, "agexpose/unhide should return True on success."

        # Verify the subgraph is restored to enclosed_node's subgraphs
        assert self.subg_name in self.graph.subgraphs, \
            "Subgraph should be restored after agexpose/unhide."
        # Verify the previously hidden nodes are now visible again
        hidden_nodes = self.graph.cmp_graph_data.hidden_node_set
        assert "Inner1" not in hidden_nodes, \
            "Inner1 should be removed from hidden set after unhide."
        assert "Inner2" not in hidden_nodes, \
            "Inner2 should be removed from hidden set after unhide."

        # The compound node should no longer be flagged as hidden
        assert not self.cmpnode.compound_node_data.collapsed, \
            "cmpnode should no longer be colapsed after unhide/expose."

    def test_a4_aghide_triggers_callback(self):
        """Test that aghide triggers the subgraph_deleted callback and preserves other nodes."""
        print(">>>> Testing aghide and triggers callbacks")
        # This creates a compound enclosed_node and makes node B a subgraph
        # Either method will create the same structure
        method_one = True
        # Version 1
        if method_one:
            print("Method 1, Create Subgraph and add Node X")
            second_subgraph = self.graph.create_subgraph('SecondSubgraph')
            node_x = second_subgraph.create_node_by_name("X")
            print("node x created")
        # Version 2
        else:
            print("Method 2, Create Node X and make it a Subgraph")
            node_x = self.graph.create_node_by_name("X")
            second_subgraph = self.graph.create_subgraph_as_compound_node(name='SecondSubgraph',
                compound_node=node_x
            )
            print("node x created")

        #ascii_print_graph(self.graph)
        node_y = second_subgraph.create_node_by_name("Y")
        edge_xc = second_subgraph.add_edge("X", "Y", edge_name="X->Y")
        edge_cy = second_subgraph.add_edge("Y", "X", edge_name="Y->X")
        #
        # # Save connections
        # cmpnode.saved_connections.append((node_x, edge_xc))
        # cmpnode.saved_connections.append((node_y, edge_cy))
        print(f"Compound graph structure:")
        ascii_print_graph(self.graph)
        # # Delete edges to simulate collapse
        second_subgraph.delete_edge(edge_xc)
        second_subgraph.delete_edge(edge_cy)
        #
        # # Hide the subgraph
        print(f"Compound graph structure after deletion of subgraph nodes:")
        ascii_print_graph(self.graph)

        success = self.graph.aghide(node_x)
        print(f"Compound graph structure after hiding node X (which is not a compound node) subgraph nodes:")
        ascii_print_graph(self.graph)
        assert success, "aghide should return False for non successful hiding."
        assert self.subgraph_deleted_triggered, "subgraph_deleted callback should not have been triggered."
        assert "FirstSubgraph" in self.graph.subgraphs, "FirstSubgraph should remain in the graph."
        assert "A" in self.graph.nodes, "Node 'A' should be in the main enclosed_node."

    def test_a5_aghide_invalid_node(self):
        """Test that aghide returns False for a non-compound, non-collapsed node."""
        print(">>>> Testing aghide of invalid nodes")
        node = self.graph.create_node_by_name("NonCompoundNode")
        node.collapsed = False
        node.subgraph = None

        success = self.graph.aghide(node)
        print(f"success = {success}")
        assert not success, "aghide should return False for non-collapsed nodes."
