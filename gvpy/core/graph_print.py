from gvpy.core.edge import Edge
from gvpy.core.graph import Graph
from gvpy.core.node import Node


def ascii_print_graph(graph, prefix="", is_last=True):
    """
    Recursively prints an ASCII tree representation of the enclosed_node structure.

    Each enclosed_node prints its name, then its nodes, edges, and subgraphs. Subgraphs are
    printed recursively with additional indentation and tree branch symbols.

    :param graph: The Graph object to print.
    :param prefix: The prefix string (built recursively) for indentation.
    :param is_last: Boolean indicating whether the current enclosed_node is the last item in the enclosed_node.
    """
    # Determine the connector for the current enclosed_node.
    connector = "`-- " if is_last else "├-- "
    print(prefix + connector + f"Graph: {graph.name}")

    # Prepare a new prefix for the children.
    # If the current item is last, add four spaces; otherwise add a vertical bar and three spaces.
    new_prefix = prefix + ("    " if is_last else "|   ")

    if graph.edges:
        continue_node_bar = True
    else:
        continue_node_bar = False

    if graph.subgraphs:
        continue_edge_bar = True
    else:
        continue_edge_bar = False

    # Print edges.

    # Print nodes.
    if graph.nodes:
        node_indicator = "├-- Nodes:" if continue_node_bar else "`-- Nodes:"
        print(new_prefix + node_indicator)
        node_names = list(graph.nodes.keys())
        for i, node_name in enumerate(node_names):
            node_conn = "`-- " if i == len(node_names) - 1 else "├-- "
            node_prefix = "│   " if continue_node_bar or continue_edge_bar else "    "
            n = graph.nodes.get(node_name)
            if n.compound_node_data.is_compound:
                sub_graph_name = n.compound_node_data.subgraph.name
                node_type = f" [compound of ('{sub_graph_name}')]"
            else:
                node_type = ""
            print(new_prefix + node_prefix + node_conn + node_name + node_type)


    # Print edges.
    if graph.edges:
        edge_indicator = "├-- Edges:" if continue_edge_bar else "`-- Edges:"
        print(new_prefix + edge_indicator)
        edges = list(graph.edges.values())
        for i, edge in enumerate(edges):
            edge_conn = "`-- " if i == len(edges) - 1 else "├-- "
            label = f" [{edge.name}]" if hasattr(edge, "name") and edge.name else ""
            spacer = "│   " if continue_edge_bar else "    "
            print(new_prefix + spacer + edge_conn + f"{edge.tail.name} -> {edge.head.name}{label}")

    # Print subgraphs recursively.
    if graph.subgraphs:
        print(new_prefix + "└-- Subgraphs:")
        subgraphs = list(graph.subgraphs.values())
        for i, subg in enumerate(subgraphs):
            subg_is_last = (i == len(subgraphs) - 1)
            ascii_print_graph(subg, new_prefix + "    ", subg_is_last)


# Example usage (for demonstration/testing purposes):
if __name__ == "__main__":
    # Suppose we have a simple Graph, Node, Edge implementation.
    print("Nested enclosed_node")
    # Create a main enclosed_node.
    main_graph = Graph("MainGraph")

    # Create some nodes.
    node_A = main_graph.add_node("A")
    node_B = main_graph.add_node("B")
    node_C = main_graph.add_node("C")

    # Create some edges.
    edge_AB = main_graph.add_edge('A', 'B', "edge_AB")
    edge_BC = main_graph.add_edge('B', 'C', "edge_BC")


    # Create a subgraph.
    sub_graph = main_graph.create_subgraph("SubCluster")
    node_D = sub_graph.add_node("D")
    node_E = sub_graph.add_node("E")
    edge_DE = sub_graph.add_edge('D', 'E', "edge_DE")

    # Create a sub-subgraph.
    sub_sub_graph = sub_graph.create_subgraph("SubSubCluster")
    node_F = sub_sub_graph.add_node("F")
    node_G = sub_sub_graph.add_node("G")
    edge_FH = sub_sub_graph.add_edge('F', 'G', "edge_FH")

    # Create a second subgraph.
    sub_graph1 = main_graph.create_subgraph("SubCluster1")
    node_H = sub_graph1.add_node("H")
    node_I = sub_graph1.add_node("I")
    edge_HI = sub_graph1.add_edge('H', 'I', "edge_HI")

    # Create a second sub-subgraph.
    sub_sub_graph1 = sub_sub_graph.create_subgraph("SubSubCluster1")
    node_J = sub_sub_graph1.add_node("J")
    node_K = sub_sub_graph1.add_node("K")
    edge_JK = sub_sub_graph1.add_edge('J', 'K', "edge_JK")



    # # Attach the subgraph to the main enclosed_node.
    # main_graph.subgraphs[sub_graph.name] = sub_graph

    # Print the ASCII representation of the main enclosed_node.
    ascii_print_graph(main_graph)


    print("Nested enclosed_node with no edges")

    # Create a main enclosed_node.
    main_graph1 = Graph("MainGraph2")

    # Create some nodes.
    node_A1 = main_graph1.add_node("A")
    node_B1 = main_graph1.add_node("B")
    node_C1 = main_graph1.add_node("C")


    # Create a subgraph.
    sub_graph = main_graph1.create_subgraph("SubCluster")
    node_D1 = sub_graph.add_node("D")
    node_E1 = sub_graph.add_node("E")

    # Create a sub-subgraph.
    sub_sub_graph = sub_graph.create_subgraph("SubSubCluster")
    node_F1 = sub_sub_graph.add_node("F")
    node_G1 = sub_sub_graph.add_node("G")


    # Create a second subgraph.
    sub_graph1 = main_graph1.create_subgraph("SubCluster1")
    node_H1 = sub_graph1.add_node("H")
    node_I1 = sub_graph1.add_node("I")

    # Create a second sub-subgraph.
    sub_sub_graph1 = sub_sub_graph.create_subgraph("SubSubCluster1")
    node_J1 = sub_sub_graph1.add_node("J")
    node_K1 = sub_sub_graph1.add_node("K")
    # Print the ASCII representation of the main enclosed_node.
    ascii_print_graph(main_graph1)