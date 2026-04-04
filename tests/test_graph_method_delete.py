import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack



class TestGraphMethodDelete:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.node_added_invoked = False
        self.node_deleted_invoked = False
        self.edge_added_invoked = False
        self.edge_deleted_invoked = False

        # Define callbacks
        def node_added_callback(node):
            self.node_added_invoked = True
            print(f"[Test Callback] Node '{node.name}' added.")

        def node_deleted_callback(node):
            self.node_deleted_invoked = True
            print(f"[Test Callback] Node '{node.name}' deleted.")

        def edge_added_callback(edge):
            self.edge_added_invoked = True
            print(f"[Test Callback] Edge '{edge.key}' added.")

        def edge_deleted_callback(edge):
            self.edge_deleted_invoked = True
            print(f"[Test Callback] Edge '{edge.key}' deleted.")

        # Register callbacks
        self.graph.method_update(GraphEvent.NODE_ADDED, node_added_callback, action='add')
        self.graph.method_update(GraphEvent.NODE_DELETED, node_deleted_callback, action='add')
        self.graph.method_update(GraphEvent.EDGE_ADDED, edge_added_callback, action='add')
        self.graph.method_update(GraphEvent.EDGE_DELETED, edge_deleted_callback, action='add')

    def test_delete_node(self):
        """Verify that deleting a node invokes the callback and removes it from the graph."""
        node = self.graph.create_node_by_name("A")
        assert self.node_added_invoked, "node_added_callback should have been invoked."
        self.node_added_invoked = False

        self.graph.method_delete(node)
        assert self.node_deleted_invoked, "node_deleted_callback should have been invoked."
        assert "A" not in self.graph.nodes, "Node 'A' should have been deleted."

    def test_delete_edge(self):
        """Verify that deleting an edge invokes the callback and removes it from the graph."""
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge = self.graph.add_edge("A", "B", edge_name="AB")
        assert self.edge_added_invoked, "edge_added_callback should have been invoked."
        self.edge_added_invoked = False

        self.graph.method_delete(edge)
        assert self.edge_deleted_invoked, "edge_deleted_callback should have been invoked."
        assert ("A", "B", "AB") not in self.graph.edges, "Edge 'AB' should have been deleted."

    def test_delete_subgraph(self):
        """Verify that deleting a subgraph removes it from the graph."""
        node_a = self.graph.create_node_by_name("A")
        subgraph = self.graph.create_subgraph("SubGraph1", enclosed_node=node_a)
        assert subgraph is not None, "Subgraph should have been created."
        assert "SubGraph1" in self.graph.subgraphs, "SubGraph1 should be in subgraphs."

        # Delete the subgraph
        self.graph.method_delete(subgraph)
        assert "SubGraph1" not in self.graph.subgraphs, "SubGraph1 should have been deleted."

    def test_invalid_deletion(self):
        """Verify that deleting an invalid object type is handled gracefully."""
        self.graph.method_delete("InvalidObject")  # Passing a string instead of a node object

    def test_delete_nonexistent_node(self):
        """Verify that deleting a node not in the graph is handled gracefully."""
        node = Node(name="NonExistent", graph=self.graph, id_=999, seq=1, root=self.graph.get_root())
        self.graph.method_delete(node)

    def test_delete_nonexistent_edge(self):
        """Verify that deleting an edge not in the graph is handled gracefully."""
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge = Edge(tail=node_a, head=node_b, id_=999, name='AB', graph=self.graph, key="NonExistent", directed=True)
        self.graph.method_delete(edge)

    def test_delete_multiple_objects(self):
        """Verify that deleting multiple objects at once removes them all."""
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")

        # Delete multiple objects
        self.graph.method_delete([node_a, edge_ab])

        assert "A" not in self.graph.nodes, "Node 'A' should have been deleted."
        assert ("A", "B", "AB") not in self.graph.edges, "Edge 'AB' should have been deleted."

    def test_delete_compound_node_with_subgraph(self):
        """Verify that deleting a compound node also deletes its associated subgraph."""
        node_a = self.graph.create_node_by_name("A")
        subgraph = self.graph.create_subgraph("SubGraph1", enclosed_node=node_a)
        assert node_a.compound_node_data.is_compound, "Node 'A' should be marked as compound."
        assert node_a.compound_node_data.subgraph is not None, "Node 'A' should have an associated subgraph."

        # Delete the node, which should also delete the subgraph
        self.graph.method_delete(node_a)
        assert "A" not in self.graph.nodes, "Node 'A' should have been deleted."
        assert "SubGraph1" not in self.graph.subgraphs, "SubGraph1 should have been deleted."
