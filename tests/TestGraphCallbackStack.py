import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


# Define callback functions
def graph_init_callback(graph_obj: Graph, obj: Graph, state):
    print(f"[Graph Init Callback] Initializing graph '{obj.name}' with state '{state}'.")


def node_init_callback(graph_obj: Graph, obj: Node, state):
    print(f"[Node Init Callback] Initializing node '{obj.name}' in graph '{graph_obj.name}' with state '{state}'.")


def edge_init_callback(graph_obj: Graph, obj: Edge, state):
    print(
        f"[Edge Init Callback] Initializing edge '{obj.key}' from '{obj.tail.name}' to '{obj.head.name}' with state '{state}'.")


class TestGraphCallbackStack(unittest.TestCase):
    def setUp(self):
        # Create a enclosed_node

        self.graph = Graph(name="MainGraph", directed=True)
        self.graph.method_init()


    def test_graph_init_callback(self):
        # Create CallbackFunctions instances for different object types
        cb_funcs_graph = CallbackFunctions(graph_ins=graph_init_callback)
        cb_funcs_node = CallbackFunctions(node_ins=node_init_callback)
        cb_funcs_edge = CallbackFunctions(edge_ins=edge_init_callback)

        # Create a callback stack for the enclosed_node
        cbstack_graph = Agcbstack(f=cb_funcs_graph, state="GraphState1", prev=None)

        # Initialize callbacks for the main enclosed_node using aginitcb
        self.graph.aginitcb(obj=self.graph, cbstack=cbstack_graph)

        # Expose a subgraph
        subgraph = self.graph.expose_subgraph("Cluster1")

        # Initialize callbacks for the subgraph
        self.graph.aginitcb(obj=subgraph, cbstack=cbstack_graph)

        # Add nodes and edges to the subgraph
        node_a = subgraph.create_node_by_name("A")
        node_b = subgraph.create_node_by_name("B")
        edge_ab = subgraph.add_edge("A", "B", edge_name="AB")

        # Initialize callbacks for nodes and edges
        # Create separate callback stacks for node and edge initialization
        cbstack_node = Agcbstack(f=cb_funcs_node, state="NodeState1", prev=None)
        cbstack_edge = Agcbstack(f=cb_funcs_edge, state="EdgeState1", prev=None)

        self.graph.aginitcb(obj=node_a, cbstack=cbstack_node)
        self.graph.aginitcb(obj=node_b, cbstack=cbstack_node)
        self.graph.aginitcb(obj=edge_ab, cbstack=cbstack_edge)

        # Collapse the subgraph
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

        # Hide the subgraph using aghide
        success = self.graph.aghide(cmpnode)
        self.assertTrue(success, f"\n[Main] Failed to hide subgraph '{subgraph.name}'.")
        if success:
            print(f"\n[Main] Successfully hid subgraph '{subgraph.name}'.")
        else:
            print(f"\n[Main] Failed to hide subgraph '{subgraph.name}'.")

    def tearDown(self):
        # Close the enclosed_node
        self.graph.agclose()


if __name__ == '__main__':
    unittest.main()
