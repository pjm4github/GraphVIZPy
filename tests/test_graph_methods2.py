import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphMethods2:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = Graph(name="TestGraph", directed=True)
        self.graph.method_init()

        # Register callbacks
        self.node_added_triggered = False
        self.subgraph_deleted_triggered = False

        def on_node_added(node):
            self.node_added_triggered = True
            print(f"[Test Callback] Node '{node.name}' has been added.")

        def on_subgraph_deleted(subgraph):
            self.subgraph_deleted_triggered = True
            print(f"[Test Callback] Subgraph '{subgraph.name}' has been deleted.")

        self.graph.method_update(GraphEvent.NODE_ADDED, on_node_added, action='add')
        self.graph.method_update(GraphEvent.SUBGRAPH_DELETED, on_subgraph_deleted, action='add')

        yield

        self.graph.agclose()

    def test_aginitcb_resets_callbacks(self):
        """Test that aginitcb preserves existing callbacks after re-initialization."""
        # Register an additional callback
        def extra_node_added_callback(node):
            print(f"[Extra Callback] Node '{node.name}' was added.")

        self.graph.method_update(GraphEvent.NODE_ADDED, extra_node_added_callback, action='add')
        assert extra_node_added_callback in self.graph.clos.callbacks[GraphEvent.NODE_ADDED]

        # Initialize callbacks again with a new callback stack
        cb_funcs_graph = CallbackFunctions(graph_ins=lambda g, o, s: print(f"[New Graph Init] Graph '{o.name}' initialized."))
        cbstack_graph = Agcbstack(f=cb_funcs_graph, state="GraphStateReset", prev=None)
        self.graph.clos.set_callback_stack(cbstack_graph)

        self.graph.aginitcb(obj=self.graph, cbstack=self.graph.clos.cb)

        # After re-initialization, the extra callback should still exist since reset_callbacks was not called
        assert extra_node_added_callback in self.graph.clos.callbacks[GraphEvent.NODE_ADDED]

    def test_aghide_invalid_node(self):
        """Test that aghide raises ValueError for a non-compound node."""
        node = self.graph.create_node_by_name("NonCompoundNode")
        node.collapsed = False
        node.subgraph = None

        with pytest.raises(ValueError):
            self.graph.aghide(node)

    def test_aghide_non_collapsed_node(self):
        """Test that aghide raises ValueError for a non-collapsed node."""
        node = self.graph.create_node_by_name("NonCollapsedNode")
        node.collapsed = False
        node.subgraph = None

        with pytest.raises(ValueError):
            self.graph.aghide(node)

    def test_aghide_successful(self):
        """Test successful hiding of a compound node with callback stacks and edge reconnection."""
        # Expose subgraph
        subgraph = self.graph.expose_subgraph("Cluster1")
        assert self.node_added_triggered
        self.node_added_triggered = False  # Reset flag

        # Add nodes and edges to subgraph
        node_a = subgraph.create_node_by_name("A")
        node_b = subgraph.create_node_by_name("B")
        edge_ab = subgraph.add_edge("A", "B", edge_name="AB")
        assert self.node_added_triggered
        self.node_added_triggered = False

        # Create and set up callback stacks
        cb_funcs_node = CallbackFunctions(
            node_mod=lambda g, obj, state, sym: print(f"[Test Node Mod] Node '{obj.name}' modified with symbol '{sym}'.")
        )
        cb_funcs_edge = CallbackFunctions(
            edge_mod=lambda g, obj, state, sym: print(f"[Test Edge Mod] Edge '{obj.key}' modified with symbol '{sym}'.")
        )

        cbstack_node = Agcbstack(f=cb_funcs_node, state="NodeState1", prev=None)
        cbstack_edge = Agcbstack(f=cb_funcs_edge, state="EdgeState1", prev=None)

        self.graph.clos.set_callback_stack(cbstack_node)
        self.graph.clos.set_callback_stack(cbstack_edge)

        self.graph.aginitcb(obj=node_a, cbstack=cbstack_node)
        self.graph.aginitcb(obj=node_b, cbstack=cbstack_node)
        self.graph.aginitcb(obj=edge_ab, cbstack=cbstack_edge)

        # Modify node 'A'
        self.graph.agupdcb(obj=node_a, sym="color=blue")

        # Modify edge 'AB'
        self.graph.agupdcb(obj=edge_ab, sym="style=dashed")

        # Collapse subgraph
        cmpnode = self.graph.create_node_by_name("Cluster1")
        cmpnode.collapsed = True
        cmpnode.subgraph = subgraph

        # Add and save connections
        node_x = self.graph.create_node_by_name("X")
        node_y = self.graph.create_node_by_name("Y")
        edge_xc = self.graph.add_edge("X", "Cluster1", edge_name="X->C1")
        edge_cy = self.graph.add_edge("Cluster1", "Y", edge_name="C1->Y")

        cmpnode.saved_connections.append((node_x, edge_xc))
        cmpnode.saved_connections.append((node_y, edge_cy))

        # Simulate collapsing by deleting edges
        self.graph.delete_edge(edge_xc)
        self.graph.delete_edge(edge_cy)

        # Hide the subgraph
        success = self.graph.aghide(cmpnode)
        assert success
        assert self.subgraph_deleted_triggered
        assert "Cluster1" not in self.graph.subgraphs
        assert not self.graph.has_cmpnd
        assert not cmpnode.collapsed

        # Check that subgraph nodes are deleted
        assert "A" not in self.graph.nodes
        assert "B" not in self.graph.nodes

        # Check that edges are reconnected
        assert ("X", "Y", "X->C1") in self.graph.edges
        assert ("Cluster1", "Y", "C1->Y") not in self.graph.edges
