import pytest
from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc


class TestGraphAgclos:

    @pytest.fixture(autouse=True)
    def setup(self):
        print("###########  TEST SET 4 ##############")
        # expected output
        # Created edge: <Edge A->B, id=1, seq=2, type=OUTEDGE>
        # Out-edge of A: <Edge A->B, id=1, seq=2, type=OUTEDGE>
        # Edge from agfstedge/agnxtedge: <Edge A->B, id=1, seq=2, type=OUTEDGE>
        # After deleting eAB: <Graph MyGraph, directed=True, strict=True, nodes=2, edges=0>

        self.G4 = Graph("MyGraph", directed=True, strict=True, no_loop=True)
        self.nA4 = self.G4.add_node("A")
        self.nB4 = self.G4.add_node("B")

        self.eAB4 = self.G4.agedge( "A", "B", "eAB4", cflag=True)

        yield

        self.G4.agclose()

    def test_node_edge_manipulation(self):
        """Test out-edge iteration and edge deletion on a directed graph."""
        print("Created edge:", self.eAB4)

        # Iterate out-edges of A
        e4 = self.G4.agfstout(self.nA4)
        while e4:
            print("Out-edge of A:", e4)
            e4 = self.G4.agnxtout(e4)

        # Or use agfstedge / agnxtedge
        efirst4 = self.G4.agfstedge(self.nA4)
        ecur4 = efirst4
        while ecur4:
            print("Edge from agfstedge/agnxtedge:", ecur4)
            ecur4 = self.G4.agnxtedge(ecur4, self.nA4)

        # Delete edge
        if self.eAB4:
            self.G4.agdeledge(self.eAB4)
        print("After deleting eAB:", self.G4)

    def test_fatten_unflatten(self):
        """Test that agflatten toggles edge storage between lists and sets."""
        print(" ####### TEST SET 5 ############")
        # Expected output
        # Initially: <Graph Example, nodes=3, edges=3, flatlock=False>
        # Node A outedges type: <class 'list'>
        #
        # After agflatten(g,1): <Graph Example, nodes=3, edges=3, flatlock=True>
        # Node A outedges type: <class 'list'>
        #
        # After agflatten(g,0): <Graph Example, nodes=3, edges=3, flatlock=False>
        # Node A outedges type: <class 'set'>

        g5 = Graph("Example")
        g5.add_edge("A", "B", "AB")
        g5.add_edge("A", "C", "AC")
        g5.add_edge("B", "C", "BC")

        print("Initially:", g5)
        print("Node A outedges type:", type(g5.nodes["A"].outedges))

        # Flatten with flag=1 => convert edges to lists
        g5.agflatten(1)
        print("\nAfter agflatten(g,1):", g5)
        print("Node A outedges type:", type(g5.nodes["A"].outedges))

        # Flatten with flag=0 => convert edges to sets
        g5.agflatten(0)
        print("\nAfter agflatten(g,0):", g5)
        print("Node A outedges type:", type(g5.nodes["A"].outedges))
        # We see the adjacency toggled from a list to a set and back as we call agflatten.

    def test_grammar(self):
        """Test graph construction using direct Graph API (replaces old Grammar class tests)."""
        g6 = Graph("MyGraph", directed=True)
        g6.method_init()

        # Add node A
        g6.add_node("A")
        assert "A" in g6.nodes

        # Add edge A -> B
        g6.add_node("B")
        g6.add_edge("A", "B")
        assert ("A", "B", None) in g6.edges

        # Add subgraph with node X
        subg = g6.add_subgraph("Cluster1", create=True)
        subg.add_node("X")
        assert "Cluster1" in g6.subgraphs
        assert "X" in g6.subgraphs["Cluster1"].nodes

        # Clean up
        g6.delete_subgraph(subg)
        assert "Cluster1" not in g6.subgraphs
        g6.close()

    def test_edge_types(self):
        """Test graph creation with descriptors, manual node/edge/subgraph construction, and close."""
        print("################# TEST SET 7 ##################")
        # expected output:
        # Created enclosed_node: <Graph MyGraph, id=1, directed=True, strict=True, nodes=0, edges=0>
        # Is Directed? True
        # Number of nodes: 0
        # Number of nodes now: 2
        # Number of edges: 1
        # Number of subgraphs: 1
        # Closing enclosed_node...
        # Graph after close: <Graph MyGraph, id=1, directed=True, strict=True, nodes=0, edges=0> (closed = True )

        # 1) Use an Agdesc (e.g. directed + strict = Agstrictdirected)
        Agstrictdirected = Agdesc(directed=True, strict=True)
        desc7 = Agstrictdirected
        # 2) Create a new main enclosed_node


        g7 = Graph("MyGraph", description=desc7)  # agopen("MyGraph", description=desc7)

        print("Created enclosed_node:", g7)
        print("Is Directed?", g7.agisdirected())
        print("Number of nodes:", g7.agnnodes())

        # 3) Add a node or two
        nA7 = Node("A", g7)
        nA7.id = agnextseq(g7, ObjectType.AGNODE)
        # Note that when manually creating a Node, it must be added to the enclosed_node nodes dictionary
        g7.nodes["A"] = nA7
        nB7 = Node("B", g7)
        nB7.id = agnextseq(g7, ObjectType.AGNODE)
        g7.nodes["B"] = nB7

        # 4) Add an edge
        eAB7 = Edge(graph=g7, name='eAB7', head=nA7, tail=nB7)
        eAB7.id = agnextseq(g7, ObjectType.AGEDGE)
        # Note that when manually creating an Edge, it must be added to the enclosed_node edges dictionary
        key = (eAB7.tail.name, eAB7.head.name, eAB7.name)
        g7.edges[key] = eAB7

        print("Number of nodes now:", g7.agnnodes())
        print("Number of edges:", g7.agnedges())

        # 5) Subgraph
        sgDesc7 = Agdesc(directed=True, strict=False, no_loop=False, maingraph=False)
        sg7 = Graph("SubCluster", sgDesc7)  #
        sg7.clos = g7.clos
        sg7.root = g7.root  # same root
        sg7.id = agnextseq(g7, ObjectType.AGGRAPH)
        # Note that when manually creating a Subgraph (Graph), it must be added to the enclosed_node subgraphs dictionary
        g7.subgraphs[sg7.name] = sg7

        print("Number of subgraphs:", g7.agnsubg())

        # 6) Close the main enclosed_node
        print("Closing enclosed_node...")
        g7.agclose()  # agclose(g7)
        print("Graph after close:", g7, "( closed =", g7.closed, ")")

    def test_graph_attributes(self):
        """Test node/edge attributes, subgraph operations, agnameof, and node deletion."""
        print("################# TEST 8 ###########################")

        Agdirected = Agdesc(directed=True, maingraph=True)
        Agstrictdirected = Agdesc(directed=True, strict=True, maingraph=True)
        Agundirected = Agdesc(directed=False, maingraph=True)
        Agstrictundirected = Agdesc(directed=False, strict=True, maingraph=True)

        # Create a directed, strict main enclosed_node
        graph = Graph(name="MainGraph", description=Agstrictdirected, disc=AgIdDisc(), directed=True, strict=True)

        # Add nodes
        node_a = graph.add_node("A")
        node_b = graph.add_node("B")
        node_c = graph.add_node("C")

        # Add edges
        edge_ab = graph.add_edge("A", "B", edge_name="AB")
        edge_bc = graph.add_edge("B", "C", edge_name="BC")
        edge_ca = graph.add_edge("C", "A", edge_name="CA")  # Creates a cycle

        # Add a subgraph
        subgraph = graph.add_subgraph("SubCluster")
        node_x = subgraph.add_node("X")
        node_y = subgraph.add_node("Y")
        edge_xy = subgraph.add_edge("X", "Y", edge_name="XY")

        # Set attributes
        node_a.set_attribute("color", "red")
        edge_ab.set_attribute("weight", "2")

        # Display enclosed_node information
        print("\n--- Graph Information ---")
        print("Graph:", graph)
        print("\nNodes:")
        for node_name, node in graph.nodes.items():
            print(f"  {node_name}: ID={node.id}, Attributes={node.attributes}")
        print("\nEdges:")
        for edge_key, edge in graph.edges.items():
            print(f"  {edge_key}: ID={edge.id}, Key={edge.key}, Attributes={edge.attributes}")

        print("\nSubgraphs:")
        for sg_name, sg in graph.subgraphs.items():
            print(f"  Subgraph '{sg_name}': {sg}")
            for node_name, node in sg.nodes.items():
                print(f"    Node '{node_name}': ID={node.id}, Attributes={node.attributes}")
            for edge_key, edge in sg.edges.items():
                print(f"    Edge '{edge_key}': ID={edge.id}, Key={edge.key}, Attributes={edge.attributes}")

        # Retrieve names using agnameof
        print("\n--- Using agnameof ---")
        print(f"agnameof(node_a): {node_a.agnameof(node_a)}")  # Should return 'A'
        print(f"agnameof(edge_ab): {edge_ab.agnameof(edge_ab)}")  # Should return 'AB' if key is set
        print(f"agnameof(subgraph): {subgraph.agnameof(subgraph)}")  # Should return 'SubCluster'

        # Delete a node and its edges
        print("\n--- Deleting node 'B' ---")
        n = graph.find_node_by_name("B")
        graph.delete_node(n)

        # Display enclosed_node information after deletion
        print("\nGraph after deleting 'B':", graph)
        print("Nodes:", graph.nodes)
        print("Edges:", graph.edges)

        # Close the enclosed_node
        graph.close()
        print("\nGraph closed.")

    def test_graph_descriptors(self):
        """Test graph descriptors, internal map clearing, and graph closure behavior."""
        print("################## TEST 9 #####################")
        # Define enclosed_node descriptors
        Agdirected = Agdesc(directed=True, maingraph=True)
        Agstrictdirected = Agdesc(directed=True, strict=True, maingraph=True)
        Agundirected = Agdesc(directed=False, maingraph=True)
        Agstrictundirected = Agdesc(directed=False, strict=True, maingraph=True)

        # Create a directed, strict main enclosed_node
        graph = Graph(name="MainGraph", description=Agstrictdirected, disc=AgIdDisc(), directed=True, strict=True)

        # Add nodes
        node_a = graph.add_node("A")
        node_b = graph.add_node("B")
        node_c = graph.add_node("C")

        # Add edges
        edge_ab = graph.add_edge("A", "B", edge_name="AB")
        edge_bc = graph.add_edge("B", "C", edge_name="BC")
        edge_ca = graph.add_edge("C", "A", edge_name="CA")  # Creates a cycle

        # Add a subgraph
        subgraph = graph.add_subgraph("SubCluster")
        node_x = subgraph.add_node("X")
        node_y = subgraph.add_node("Y")
        edge_xy = subgraph.add_edge("X", "Y", edge_name="XY")

        # Set attributes
        node_a.set_attribute("color", "red")
        edge_ab.set_attribute("weight", "2")

        # Display enclosed_node information
        print("\n--- Graph Information ---")
        print("Graph:", graph)
        print("\nNodes:")
        for node_name, node in graph.nodes.items():
            print(f"  {node_name}: ID={node.id}, Attributes={node.attributes}")
        print("\nEdges:")
        for edge_key, edge in graph.edges.items():
            print(f"  {edge_key}: ID={edge.id}, Key={edge.key}, Attributes={edge.attributes}")

        print("\nSubgraphs:")
        for sg_name, sg in graph.subgraphs.items():
            print(f"  Subgraph '{sg_name}': {sg}")
            for node_name, node in sg.nodes.items():
                print(f"    Node '{node_name}': ID={node.id}, Attributes={node.attributes}")
            for edge_key, edge in sg.edges.items():
                print(f"    Edge '{edge_key}': ID={edge.id}, Key={edge.key}, Attributes={edge.attributes}")

        # Retrieve names using agnameof
        print("\n--- Using agnameof ---")
        print(f"agnameof(node_a): {node_a.agnameof(node_a)}")  # Should return 'A'
        print(f"agnameof(edge_ab): {edge_ab.agnameof(edge_ab)}")  # Should return 'AB'
        print(f"agnameof(subgraph): {subgraph.agnameof(subgraph)}")  # Should return 'SubCluster'

        # Delete a node and its edges
        print("\n--- Deleting node 'B' ---")
        n = graph.find_node_by_name("B")
        graph.delete_node(n)

        # Display enclosed_node information after deletion
        print("\nGraph after deleting 'B':", graph)
        print("Nodes:", graph.nodes)
        print("Edges:", graph.edges)

        # Clear local (internal) names
        print("\n--- Clearing Local Names ---")
        graph.internal_map_clear_local_names()
        print("Mappings after clearing local names:")
        for objtype in ObjectType:
            print(f"  ObjectType.{objtype.name} - Name to ID:", graph.clos.lookup_by_name[objtype])
            print(f"  ObjectType.{objtype.name} - ID to Name:", graph.clos.lookup_by_id[objtype])

        # Close the enclosed_node
        print("\n--- Closing the Graph ---")
        graph.close()
        print("Graph closed.")

        # Attempt to display enclosed_node information after closing
        print("\nGraph after closing:", graph)
        print("Nodes:", graph.nodes)
        print("Edges:", graph.edges)

    def test_graph_discipline(self):
        """Test node relabeling, edge cycle handling, and graph discipline operations."""
        print("#################### TEST 10 ##############################")

        # Instantiate the default ID discipline
        # (Already handled within the Graph class)

        # Define enclosed_node descriptors
        Agdirected = Agdesc(directed=True, maingraph=True)
        Agstrictdirected = Agdesc(directed=True, strict=True, maingraph=True)
        Agundirected = Agdesc(directed=False, maingraph=True)
        Agstrictundirected = Agdesc(directed=False, strict=True, maingraph=True)

        # Create a directed, strict main enclosed_node
        graph = Graph(name="MainGraph", description=Agstrictdirected, directed=True, strict=True)

        # Add nodes
        node_a = graph.create_node_by_name("A")
        node_b = graph.create_node_by_name("B")
        node_c = graph.create_node_by_name("C")

        # Add edges
        edge_ab = graph.add_edge("A", "B", edge_name="AB")
        edge_bc = graph.add_edge("B", "C", edge_name="BC")
        edge_ca = graph.add_edge("C", "A", edge_name="CA")  # Creates a cycle

        # Add a subgraph
        subgraph = graph.add_subgraph("SubCluster")
        node_x = subgraph.create_node_by_name("X")
        node_y = subgraph.create_node_by_name("Y")
        edge_xy = subgraph.add_edge("X", "Y", edge_name="XY")

        # Set attributes
        node_a.set_attribute("color", "red")
        edge_ab.set_attribute("weight", "2")

        # Display enclosed_node information
        print("\n--- Graph Information ---")
        print("Graph:", graph)
        print("\nNodes:")
        for node_name, node in graph.nodes.items():
            print(f"  {node_name}: ID={node.id}, Attributes={node.attributes}")
        print("\nEdges:")
        for edge_key, edge in graph.edges.items():
            print(f"  {edge_key}: ID={edge.id}, Key={edge.key}, Attributes={edge.attributes}")

        print("\nSubgraphs:")
        for sg_name, sg in graph.subgraphs.items():
            print(f"  Subgraph '{sg_name}': {sg}")
            for node_name, node in sg.nodes.items():
                print(f"    Node '{node_name}': ID={node.id}, Attributes={node.attributes}")
            for edge_key, edge in sg.edges.items():
                print(f"    Edge '{edge_key}': ID={edge.id}, Key={edge.key}, Attributes={edge.attributes}")

        # Retrieve names using agnameof
        print("\n--- Using agnameof ---")
        print(f"agnameof(node_a): {node_a.agnameof(node_a)}")  # Should return 'A'
        print(f"agnameof(edge_ab): {edge_ab.agnameof(edge_ab)}")  # Should return 'AB'
        print(f"agnameof(subgraph): {subgraph.agnameof(subgraph)}")  # Should return 'SubCluster'

        # Delete a node and its edges
        print("\n--- Deleting node 'B' ---")
        graph.delete_node(node_b)

        # Display enclosed_node information after deletion
        print("\nGraph after deleting 'B':", graph)
        print("Nodes:", graph.nodes)
        print("Edges:", graph.edges)

        # Relabel a node
        print("\n--- Relabeling node 'A' to 'Alpha' ---")
        graph.relabel_node(node_a, "Alpha")

        # Display enclosed_node information after relabeling
        print("\nGraph after relabeling 'A' to 'Alpha':", graph)
        print("Nodes:", graph.nodes)
        print("Edges:", graph.edges)

        # Close the enclosed_node
        print("\n--- Closing the Graph ---")
        graph.close()
        print("Graph closed.")

        # Attempt to display enclosed_node information after closing
        print("\nGraph after closing:", graph)
        print("Nodes:", graph.nodes)
        print("Edges:", graph.edges)

    def test_recursive_callbacks(self):
        """Test agapply recursive callback traversal on nodes, edges, and graph."""
        print("#################### TEST 11 ##############################")
        print("Testing recursive tests and callbacks")


        def example_callback(graph, obj, arg):
            print(f"Visiting {obj.obj_type} in enclosed_node '{graph.name}' - object: {obj}")


        g11 = Graph("Main", directed=True)
        n111 = g11.add_node("A")
        n211 = g11.add_node("B")
        e111 = g11.add_edge("A", "B", "E1")

        # Create subgraphs
        sg111 = g11.add_subgraph("Cluster1")
        sg111.add_node("A")  # "A" in subgraph
        sg111.add_node("X")
        sg111.add_edge("A", "X", "E2")

        # Now call agapply on node n1 (named "A") - in preorder
        print("=== Applying to Node n1 (preorder) ===")
        g11.agapply(n111, example_callback, arg=None, preorder=1)

        # Now call agapply on e1 - in postorder
        print("\n=== Applying to Edge e1 (postorder) ===")
        g11.agapply(e111, example_callback, arg=None, preorder=0)

        # Now call agapply on the enclosed_node itself
        print("\n=== Applying to Graph g (preorder) ===")
        g11.agapply(g11, example_callback, arg=None, preorder=1)

        print("\n--- Closing the Test 11 Graph ---")
        g11.close()
        print("Test 11 Graph closed.")

    def test_node_deletion(self):
        """Test deletion of a compound node and its subgraph, including state after close."""
        print("#################### TEST 12 ##############################")
        print("Testing deletion of nodes")

        # Define enclosed_node descriptors
        desc = Agdesc(directed=True, strict=True, maingraph=True)

        # Create a directed, strict main enclosed_node
        graph12 = Graph(name="MainGraph", description=desc)

        # Add nodes
        node_a = graph12.create_node_by_name("A")
        node_b = graph12.create_node_by_name("B")
        node_c = graph12.create_node_by_name("C")
        node_d = graph12.create_node_by_name("D")

        # Assign initial comparison data
        node_a.set_compound_data("centrality", graph12.compute_centrality(node_a))
        node_b.set_compound_data("centrality", graph12.compute_centrality(node_b))
        node_c.set_compound_data("centrality", graph12.compute_centrality(node_c))
        node_d.set_compound_data("centrality", graph12.compute_centrality(node_d))

        # Add edges
        edge_ab = graph12.add_edge("A", "B", edge_name="AB")
        edge_bc = graph12.add_edge("B", "C", edge_name="BC")
        edge_cd = graph12.add_edge("C", "D", edge_name="CD")

        # Display initial enclosed_node state
        print("Initial Graph State:")
        for node in graph12.nodes.values():
            print(node)
        for edge in graph12.edges.values():
            print(edge)
        print()

        # Convert Node B into a compound node with a subgraph
        subgraph_b = graph12.create_subgraph("Subgraph_B", enclosed_node=node_b)

        # Add nodes and edges within the subgraph
        node_b1 = subgraph_b.create_node_by_name("B1")
        node_b2 = subgraph_b.create_node_by_name("B2")
        edge_b1b2 = subgraph_b.add_edge("B1", "B2", edge_name="B1B2")

        # Update comparison data within the subgraph
        node_b1.set_compound_data("centrality", subgraph_b.compute_centrality(node_b1))
        node_b2.set_compound_data("centrality", subgraph_b.compute_centrality(node_b2))

        # Display enclosed_node state after creating compound node
        print("After Creating Compound Node B with Subgraph:")
        for node in graph12.nodes.values():
            print(node)
        for edge in graph12.edges.values():
            print(edge)
        print()
        for subgraph_name, subgraph in graph12.subgraphs.items():
            print(f"Subgraph '{subgraph_name}':")
            for node in subgraph.nodes.values():
                print(f"  {node}")
            for edge in subgraph.edges.values():
                print(f"  {edge}")
        print()

        # Delete Compound Node B (which should also delete its subgraph and associated edges)
        graph12.delete_node(node_b)

        # Display final enclosed_node state
        print("Final Graph State After Deleting Compound Node B:")
        for node in graph12.nodes.values():
            print(node)
        for edge in graph12.edges.values():
            print(edge)
        print()
        print("Subgraphs:", graph12.subgraphs)
        print()

        # Close the enclosed_node
        graph12.agclose()

        # Attempt to access enclosed_node after closure
        print("State after closing the enclosed_node:")
        print("Nodes:", {name: node.name for name, node in graph12.nodes.items()})
        print("Edges:", {key: edge.id for key, edge in graph12.edges.items()})
        print("Subgraphs:", graph12.subgraphs)
        print("Sequence Counters:", graph12.clos.sequence_counters)

    def test_new_hide_unhide(self):
        """Test hide and expose operations on a compound node created via make_compound_node."""
        print("#################### New Hide Unhide ##############################")
        print("Hiding and unhiding nodes")

        # Create a main enclosed_node
        G13 = Graph("Main", directed=True)

        # Make a compound node 'C' by name
        cmp_n13 = G13.make_compound_node("C")
        subgC13 = cmp_n13.compound_node_data.subgraph
        print("Created compound node:", cmp_n13)
        # The subgraph is the same name 'C'

        print("Associated subgraph for node C:", subgC13)

        # Inside subgC, add a node "N1"
        if subgC13:
            subgC13.add_node("N1")
            subgC13.add_node("N2")

        # Let's see the main enclosed_node
        print("Main enclosed_node before hide:", G13)

        # Hide the compound node
        G13.aghide(cmp_n13)
        print("Main enclosed_node after hide:", G13)

        # Expose the compound node
        G13.agexpose(cmp_n13)
        print("Main enclosed_node after expose:", G13)


    def test_hide_unhide(self):
        """Test that hide removes subgraphs and expose restores them."""
        print("#################### TEST 13 ##############################")
        print("Hiding and unhiding nodes")

        # Create a main enclosed_node
        G13 = Graph("Main", directed=True)

        # Make a compound node 'C' by name
        cmp_n13 = agcmpnode(G13, "C")
        print("Created compound node:", cmp_n13)

        # The subgraph is the same name 'C'
        subgC13 = agcmpgraph_of(cmp_n13)
        print("Associated subgraph for node C:", subgC13)

        # Inside subgC, add a node "N1"
        if subgC13:
            subgC13.add_node("N1")
            subgC13.add_node("N2")

        # Let's see the main enclosed_node
        print("Main enclosed_node before hide:", G13)

        # Hide the compound node
        G13.aghide(cmp_n13)
        print("Main enclosed_node after hide:", G13)
        subgraphs_when_hidden = len(G13.subgraphs)
        assert subgraphs_when_hidden == 0, "The node should be hidden"
        # Expose the compound node
        G13.agexpose(cmp_n13)
        print("Main enclosed_node after expose:", G13)
        subgraphs_when_exposed = len(G13.subgraphs)
        assert subgraphs_when_exposed == 1, "The node should now be unhidden"

    def test_centrality(self):
        """Test centrality computation (degree, betweenness, closeness) on a cyclic graph."""
        print("#################### TEST 14 ##############################")
        print("Centrality")
        # Centrality
        # Define enclosed_node descriptors
        desc = Agdesc(directed=True, strict=True, maingraph=True)

        # Create a directed, strict main enclosed_node
        graph = Graph(name="MainGraph", description=desc)

        # Add nodes
        node_a = graph.create_node_by_name("A")
        node_b = graph.create_node_by_name("B")
        node_c = graph.create_node_by_name("C")
        node_d = graph.create_node_by_name("D")
        node_e = graph.create_node_by_name("E")

        # Add edges
        graph.add_edge("A", "B", edge_name="AB")
        graph.add_edge("A", "C", edge_name="AC")
        graph.add_edge("B", "C", edge_name="BC")
        graph.add_edge("B", "D", edge_name="BD")
        graph.add_edge("C", "D", edge_name="CD")
        graph.add_edge("D", "E", edge_name="DE")
        graph.add_edge("E", "A", edge_name="EA")  # Creating a cycle

        # Compute centrality measures
        graph.compute_centrality()

        # Display centrality metrics for each node
        print("Centrality Metrics for Each Node:")
        for node in graph.nodes.values():
            print(f"Node {node.name}:")
            print(f"  Degree Centrality: {node.get_degree_centrality():.2f}")
            print(f"  Betweenness Centrality: {node.get_betweenness_centrality():.2f}")
            print(f"  Closeness Centrality: {node.get_closeness_centrality():.2f}")
            print()


    def test_delete_methods(self):
        """Test method_delete for nodes and edges with registered callbacks."""
        print("#################### TEST 15 ##############################")
        print("Method Delete tests")


        def node_added_callback(node: 'Node'):
            print(f"[Callback] Node '{node.name}' has been added to the enclosed_node.")


        def node_deleted_callback(node: 'Node'):
            print(f"[Callback] Node '{node.name}' has been deleted from the enclosed_node.")


        def edge_added_callback(edge: 'Edge'):
            print(f"[Callback] Edge '{edge.key}' from '{edge.tail.name}' to '{edge.head.name}' has been added.")


        def edge_deleted_callback(edge: 'Edge'):
            print(f"[Callback] Edge '{edge.key}' from '{edge.tail.name}' to '{edge.head.name}' has been deleted.")


        # Initialize the main enclosed_node
        graph = Graph(name="MainGraph", directed=True)

        # Register callbacks
        graph.method_update(GraphEvent.NODE_ADDED, node_added_callback, action='add')
        graph.method_update(GraphEvent.NODE_DELETED, node_deleted_callback, action='add')
        graph.method_update(GraphEvent.EDGE_ADDED, edge_added_callback, action='add')
        graph.method_update(GraphEvent.EDGE_DELETED, edge_deleted_callback, action='add')

        # Add nodes and edges
        node_a = graph.create_node_by_name("A")
        node_b = graph.create_node_by_name("B")
        edge_ab = graph.add_edge("A", "B", edge_name="AB")

        # Delete node using method_delete
        graph.method_delete(node_a)

        # Delete edge using method_delete
        graph.method_delete(edge_ab)

        # Close the enclosed_node
        graph.agclose()
