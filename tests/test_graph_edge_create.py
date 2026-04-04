import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack



def example_callback(graph, obj, arg):
    print(f"Visiting {obj.obj_type} in enclosed_node '{graph.name}' - object: {obj}, with arg: {arg}")

class TestGraphEdgeCreate:
    @pytest.fixture(autouse=True)
    def setup(self):
        # Create a enclosed_node
        self.g = Graph("Main", directed=True)
        self.n1 = self.g.add_node("A")
        self.n2 = self.g.add_node("B")
        self.e1 = self.g.add_edge("A", "B", "E1")
        yield
        # Reset the callbacks after each test
        self.g.close()

    def test_node_added(self):
        """Test that two nodes were added to the graph."""
        print(len(self.g.nodes))
        assert len(self.g.nodes) == 2, "There should be 2 nodes"

    def test_add_subgraphs(self):
        """Test that a subgraph with nodes and edges can be added."""
        # Create subgraphs
        sg1 = self.g.add_subgraph("Cluster1")
        sg1.add_node("A")  # "A" in subgraph
        sg1.add_node("X")
        sg1.add_edge("A", "X", "E2")
        assert len(self.g.subgraphs) == 1, "There should be 1 subgraph"

    def test_agapply(self):
        """Test agapply traversal on nodes, edges, and the graph itself."""
        # Simulate node deletion
        # Now call agapply on node n1 (named "A") - in preorder
        print("=== Applying to Node n1 (preorder) ===")
        assert self.g.agapply(self.n1, example_callback, arg=None, preorder=1), \
            "agapply to a node failed"

        # Now call agapply on e1 - in postorder
        print("\n=== Applying to Edge e1 (postorder) ===")
        assert self.g.agapply(self.e1, example_callback, arg=None, preorder=0), \
            "agapply to an edge failed"

        # Now call agapply on the enclosed_node itself
        print("\n=== Applying to Graph g (preorder) ===")
        assert self.g.agapply( self.g, example_callback, arg=None, preorder=1), \
            "agapply to a enclosed_node failed"
