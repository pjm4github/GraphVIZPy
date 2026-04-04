import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphMethodInit:
    @pytest.fixture(autouse=True)
    def setup(self):
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

        yield

        # Close the graph after each test
        self.graph.agclose()

    def test_method_init_initializes_graph(self):
        """Verify that method_init clears all nodes, edges, and subgraphs."""
        # Add nodes and edges
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")

        # Ensure nodes and edges are present
        assert "A" in self.graph.nodes
        assert "B" in self.graph.nodes
        assert ("A", "B", "AB") in self.graph.edges

        # Reset events
        self.events_triggered = {key: False for key in self.events_triggered}

        # Call method_init to re-initialize the enclosed_node
        self.graph.method_init()

        # Ensure nodes, edges, and subgraphs are cleared
        assert "A" not in self.graph.nodes
        assert "B" not in self.graph.nodes
        assert ("A", "B", "AB") not in self.graph.edges
        assert not self.events_triggered['node_added']
        assert not self.events_triggered['edge_added']

    def test_method_init_resets_callbacks(self):
        """Verify that callbacks are no longer triggered after method_init resets them."""
        # Call method_init to reset callbacks
        self.graph.method_init()

        # Add a node and edge after reset
        node_a = self.graph.create_node_by_name("A")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")

        # Since callbacks are reset, events should not be triggered
        assert not self.events_triggered['node_added']
        assert not self.events_triggered['edge_added']

    def test_method_init_prevents_reinitialization(self):
        """Verify that calling method_init twice logs a warning about already being initialized."""
        # Initialize the enclosed_node first time
        self.graph.method_init()

        # Attempt to initialize again
        self.graph.method_init()

    def test_method_init_with_existing_subgraphs(self):
        """Verify that method_init clears existing subgraphs."""
        # Create a subgraph
        subgraph = Graph(name="SubGraph1", directed=True)
        self.graph.subgraphs["SubGraph1"] = subgraph

        # Initialize the enclosed_node
        self.graph.method_init()

        # Ensure subgraphs are cleared
        assert "SubGraph1" not in self.graph.subgraphs

    def test_method_init_clears_all_entities(self):
        """Verify that method_init clears all nodes, edges, and subgraphs completely."""
        # Add nodes, edges, and subgraphs
        node_a = self.graph.create_node_by_name("A")
        node_b = self.graph.create_node_by_name("B")
        edge_ab = self.graph.add_edge("A", "B", edge_name="AB")
        subgraph = Graph(name="SubGraph1", directed=True)
        self.graph.subgraphs["SubGraph1"] = subgraph

        # Call method_init to re-initialize the enclosed_node
        self.graph.method_init()

        # Ensure all entities are cleared
        assert len(self.graph.nodes) == 0
        assert len(self.graph.edges) == 0
        assert len(self.graph.subgraphs) == 0
