from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of  # , aghide, agexpose
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc
from pycode.cgraph.graph_print import ascii_print_graph

import pytest


class TestGraphAghide:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.subgraph_deleted_triggered = False

        def subgraph_deleted_callback(subgraph):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' deleted.")

        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, subgraph_deleted_callback, action='add')
        print("Done with setup")

        yield

        self.graph.agclose()
        print("Graph after teardown")
        ascii_print_graph(self.graph)

    def test_aghide_triggers_callback(self):
        """Test that aghide triggers the subgraph_deleted callback and agexpose restores the subgraph."""
        print("Starting test_aghide_triggers_callback tests")
        #subgraph = self.graph.expose_subgraph("Cluster1")
        regular_node = self.graph.create_node_by_name("R1")
        print(f"Graph structure after 'R1' added")
        ascii_print_graph(self.graph)
        # make the cmpnode a real compound node

        # cmpnode.collapsed = True
        # cmpnode.subgraph = subgraph

        node_x = self.graph.create_node_by_name("X")
        node_y = self.graph.create_node_by_name("Y")
        edge_xr = self.graph.add_edge("X", "R1", edge_name="X->R1")
        edge_ry = self.graph.add_edge("R1", "Y", edge_name="R1->Y")
        edge_xy = self.graph.add_edge("Y", "X", edge_name="X->Y")
        print(f"Graph structure after adding Nodes, X, Y and Edges added")
        ascii_print_graph(self.graph)

        # Save connections
        # cmpnode.saved_connections.append((node_x, edge_xc))
        # cmpnode.saved_connections.append((node_y, edge_cy))

        cmpnode = self.graph.make_compound_node("Cluster1", regular_node)
        print(f"Graph structure after changing the 'R-Node' Node into a compound node named 'Compound Subgraph'")
        ascii_print_graph(self.graph)
        # Delete edges to simulate collapse
        #  self.graph.delete_edge(edge_xc)
        #  self.graph.delete_edge(edge_cy)

        # print(f"Graph structure after setup")
        # ascii_print_graph(self.graph)

        # Hide the subgraph
        success = self.graph.aghide(cmpnode)
        assert success, "aghide should return True for successful hiding."
        print(f"Graph structure after hide")
        ascii_print_graph(self.graph)

        assert self.subgraph_deleted_triggered, "subgraph_deleted callback should have been triggered."
        assert "Cluster1" not in self.graph.subgraphs, "Subgraph should be removed from the enclosed_node."
        assert "X" in self.graph.nodes, "Node 'X' should still be in the main enclosed_node."
        assert "Y" in self.graph.nodes, "Node 'Y' should still be in the main enclosed_node."

        success = self.graph.agexpose(cmpnode)
        assert success, "aghide should return True for successful exposing."
        print(f"Graph structure after expose")
        ascii_print_graph(self.graph)


    def test_aghide_invalid_node(self):
        """Test that aghide returns False for a non-compound node."""
        print("Starting test_aghide_invalid_node tests")
        node = self.graph.create_node_by_name("NonCompoundNode")
        node.collapsed = False
        node.subgraph = None

        success = self.graph.aghide(node)
        assert not success, "aghide should return False for non-collapsed nodes."
