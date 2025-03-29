import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack



class TestGraphMethodDelete(unittest.TestCase):
    def setUp(self):
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
        node = self.graph.create_node_by_name("A")
        self.assertTrue(self.node_added_invoked, "node_added_callback should have been invoked.")
        self.node_added_invoked = False

        self.graph.method_delete(node)
        self.assertTrue(self.node_deleted_invoked, "node_deleted_callback should have been invoked.")
        self.assertNotIn("A", self.graph.nodes, "Node 'A' should have been deleted.")

    def test_delete_edge(self):
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge = self.graph.add_edge("A", "B", edge_name="AB")
        self.assertTrue(self.edge_added_invoked, "edge_added_callback should have been invoked.")
        self.edge_added_invoked = False

        self.graph.method_delete(edge)
        self.assertTrue(self.edge_deleted_invoked, "edge_deleted_callback should have been invoked.")
        self.assertNotIn(("A", "B", "AB"), self.graph.edges, "Edge 'AB' should have been deleted.")

    def test_delete_subgraph(self):
        node_a = self.graph.create_node_by_name("A")
        subgraph = self.graph.create_subgraph("SubGraph1", enclosed_node=node_a)
        self.assertIsNotNone(subgraph, "Subgraph should have been created.")
        self.assertIn("SubGraph1", self.graph.subgraphs, "SubGraph1 should be in subgraphs.")

        # Delete the subgraph
        self.graph.method_delete(subgraph)
        self.assertNotIn("SubGraph1", self.graph.subgraphs, "SubGraph1 should have been deleted.")

    def test_invalid_deletion(self):
        # with self.assertRaises(TypeError):
        #     self.enclosed_node.method_delete("InvalidObject")  # Passing a string instead of a enclosed_node object
        with self.assertLogs() as log:
            self.graph.method_delete("InvalidObject")  # Passing a string instead of a enclosed_node object
            self.assertIn("not found for deletion", log.output[-1])

    def test_delete_nonexistent_node(self):
        node = Node(name="NonExistent", graph=self.graph, id_=999, seq=1, root=self.graph.get_root())
        with self.assertLogs() as log:
            self.graph.method_delete(node)
            self.assertIn("does not exist in enclosed_node", log.output[-1])

    def test_delete_nonexistent_edge(self):
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge = Edge(tail=node_a, head=node_b, id_=999, name='AB', graph=self.graph, key="NonExistent", directed=True)
        with self.assertLogs() as log:
            self.graph.method_delete(edge)
            self.assertIn("does not exist in enclosed_node", log.output[-1])

    def test_delete_multiple_objects(self):
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")

        # Delete multiple objects
        self.graph.method_delete([node_a, edge_ab])

        self.assertNotIn("A", self.graph.nodes, "Node 'A' should have been deleted.")
        self.assertNotIn(("A", "B", "AB"), self.graph.edges, "Edge 'AB' should have been deleted.")

    def test_delete_compound_node_with_subgraph(self):
        node_a = self.graph.create_node_by_name("A")
        subgraph = self.graph.create_subgraph("SubGraph1", enclosed_node=node_a)
        self.assertTrue(node_a.compound_node_data.is_compound, "Node 'A' should be marked as compound.")
        self.assertIsNotNone(node_a.compound_node_data.subgraph, "Node 'A' should have an associated subgraph.")

        # Delete the node, which should also delete the subgraph
        self.graph.method_delete(node_a)
        self.assertNotIn("A", self.graph.nodes, "Node 'A' should have been deleted.")
        self.assertNotIn("SubGraph1", self.graph.subgraphs, "SubGraph1 should have been deleted.")

if __name__ == '__main__':
    unittest.main()
