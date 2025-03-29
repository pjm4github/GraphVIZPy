import unittest
from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq, gather_all_nodes, gather_all_edges
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc
from tests.GraphPrint import ascii_print_graph


# Test set 2
class TestGraphAttribute(unittest.TestCase):
    def setUp(self):
        # Create a root enclosed_node
        self.G = Graph("Root", directed=True)

    def test_attribute_declaration(self):
        # expected output:
        # Declared enclosed_node attribute: <AgSym name=color, id=0, defval=blue>

        color_sym = self.G.agattr(ObjectType.AGGRAPH, "color", "blue")
        print("Declared enclosed_node attribute:", color_sym)

        # Check it
        print("Root enclosed_node color:", self.G.agget("color"))
        # Root enclosed_node color: blue


        self.assertIn("blue", self.G.agget("color"), "Graph color is should be 'blue'")
        # Make a subgraph
        sg_test = self.G.add_subgraph("Cluster1")
        print("Subgraph color (inherits from root):", sg_test.agget( "color"))
        # Subgraph color (inherits from root): blue
        self.assertIn("blue", sg_test.agget("color"), "Subgraph color is should be 'blue'")

        # Declare a node attribute at the root
        label_sym = self.G.agattr(ObjectType.AGNODE, "label", "defaultLabel")
        print("Declared node attribute:", label_sym)
        # Declared node attribute: <AgSym name=label, id=0, defval=defaultLabel>

        self.assertIn("defaultLabel", str(label_sym), "Node attribute label should be 'defaultLabel'")

        # Add some nodes
        nA = self.G.add_node("A")
        nB = self.G.add_node("B")
        print("Node A label:", nA.agget("label"))
        # Node A label: defaultLabel
        self.assertIn("defaultLabel", nA.agget("label"), "Node attribute 'label' should be 'defaultLabel'")

        nA.agset("label", "HELLO_A")
        print("Node A label updated:", nA.agget("label"))
        # Node A label updated: HELLO_A
        self.assertIn("HELLO_A", nA.agget("label"), "Node attribute label should be 'HELLO_A'")

        # Declare an edge attribute and add some edges
        style_sym = self.G.agattr(ObjectType.AGEDGE, "style", "dashed")
        # Declared edge attribute: <AgSym name=style, id=0, defval=dashed>

        e1 = self.G.add_edge("A", "B", "edge1")
        print("Edge e1 style:", e1.agget("style"))
        # Edge e1 style: dashed
        self.assertIn("dashed", str(e1.agget("style")), "Edge e1 style should be 'dashed'")

        # Safely set an attribute that doesn't exist yet
        nB.agsafeset("color", "red", "black")
        print("Node B color:", nB.agget("color"))

        # Node B color: red
        self.assertIn("red", nB.agget("color"), "Node B color should be 'red'")

        # Summaries
        print("All nodes in G:", gather_all_nodes(self.G))
        n = gather_all_nodes(self.G)
        number=len(n)
        names = [item.name for item in n]
        # All nodes in G: [<Node A>, <Node B>]
        print(f"number of Nodes = {number}, names of Nodes = {names}")
        self.assertIn("2, ['A', 'B']", f"{number}, {names}", "All nodes in G should be '2, ['A', 'B']'")
        e = gather_all_edges(self.G)
        print("All edges in G:", e)
        points = [f"{ee.tail.name}->{ee.head.name}" for ee in e]
        s = f"{len(e)}, {','.join(points)}"
        # All edges in G: [<Edge A->B [name=edge1]>]
        self.assertIn("1, A->B", s, "All edges in G should be '1, A->B'")
        ascii_print_graph(self.G)

    def tearDown(self):
        # Close the enclosed_node (frees resources in the C sense).
        self.G.close()


if __name__ == '__main__':
    unittest.main()
