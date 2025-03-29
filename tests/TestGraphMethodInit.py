import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphMethodInit(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.events_triggered = {
            'node_added': False,
            'edge_added': False,
            'node_deleted': False,
            'edge_deleted': False
        }

        # Define callback functions
        def node_added_callback(node):
            self.events_triggered['node_added'] = True
            print(f"[Test Callback] Node '{node.name}' added.")

        def edge_added_callback(edge):
            self.events_triggered['edge_added'] = True
            print(f"[Test Callback] Edge '{edge.key}' added.")

        def node_deleted_callback(node):
            self.events_triggered['node_deleted'] = True
            print(f"[Test Callback] Node '{node.name}' deleted.")

        def edge_deleted_callback(edge):
            self.events_triggered['edge_deleted'] = True
            print(f"[Test Callback] Edge '{edge.key}' deleted.")

        # Register callbacks
        self.graph.method_update(GraphEvent.NODE_ADDED, node_added_callback, action='add')
        self.graph.method_update(GraphEvent.EDGE_ADDED, edge_added_callback, action='add')
        self.graph.method_update(GraphEvent.NODE_DELETED, node_deleted_callback, action='add')
        self.graph.method_update(GraphEvent.EDGE_DELETED, edge_deleted_callback, action='add')

    def test_method_init_initializes_graph(self):
        # Add nodes and edges
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")

        # Ensure nodes and edges are present
        self.assertIn("A", self.graph.nodes)
        self.assertIn("B", self.graph.nodes)
        self.assertIn(("A", "B", "AB"), self.graph.edges)

        # Reset events
        self.events_triggered = {key: False for key in self.events_triggered}

        # Call method_init to re-initialize the enclosed_node
        self.graph.method_init()

        # Ensure nodes, edges, and subgraphs are cleared
        self.assertNotIn("A", self.graph.nodes)
        self.assertNotIn("B", self.graph.nodes)
        self.assertNotIn(("A", "B", "AB"), self.graph.edges)
        self.assertFalse(self.events_triggered['node_added'])
        self.assertFalse(self.events_triggered['edge_added'])

    def test_method_init_resets_callbacks(self):
        # Call method_init to reset callbacks
        self.graph.method_init()

        # Add a node and edge after reset
        node_a = self.graph.create_node_by_name("A")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")

        # Since callbacks are reset, events should not be triggered
        self.assertFalse(self.events_triggered['node_added'])
        self.assertFalse(self.events_triggered['edge_added'])

    def test_method_init_prevents_reinitialization(self):
        # Initialize the enclosed_node first time
        self.graph.method_init()

        # Attempt to initialize again
        with self.assertLogs() as log:
            self.graph.method_init()
            self.assertIn("Graph 'TestGraph' is already initialized.", log.output[-1])

    def test_method_init_with_existing_subgraphs(self):
        # Create a subgraph
        subgraph = Graph(name="SubGraph1", directed=True)
        self.graph.subgraphs["SubGraph1"] = subgraph

        # Initialize the enclosed_node
        self.graph.method_init()

        # Ensure subgraphs are cleared
        self.assertNotIn("SubGraph1", self.graph.subgraphs)

    def test_method_init_clears_all_entities(self):
        # Add nodes, edges, and subgraphs
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")
        subgraph = Graph(name="SubGraph1", directed=True)
        self.graph.subgraphs["SubGraph1"] = subgraph

        # Call method_init to re-initialize the enclosed_node
        self.graph.method_init()

        # Ensure all entities are cleared
        self.assertEqual(len(self.graph.nodes), 0)
        self.assertEqual(len(self.graph.edges), 0)
        self.assertEqual(len(self.graph.subgraphs), 0)

    def tearDown(self):
        # Close the enclosed_node after each test
        self.graph.agclose()

if __name__ == '__main__':
    unittest.main()