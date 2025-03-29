import unittest

from refactored.CGGrammar import Grammar
from refactored.CGNode import Node, agcmpnode, agcmpgraph_of, aghide, agexpose
from refactored.CGGraph import Graph, agnextseq
from refactored.CGEdge import Edge
from refactored.Defines import ObjectType, GraphEvent
from refactored.Headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack

# Test set 2
class TestGraphRec(unittest.TestCase):
    """
    [Agraph] Graph 'MainGraph' has been initialized.
    [Agobj] Record 'color' bound to Agraph with mtf=False.
    [Agobj] Record 'size' bound to Agraph with mtf=True.
    [Agraph] Record 'color' bound to enclosed_node 'MainGraph' with mtf=False.
    [Agraph] Record 'size' bound to enclosed_node 'MainGraph' with mtf=True.
    [Agraph] Record 'color' bound to Agnode with mtf=False.
    [Agraph] Record 'weight' bound to Agedge with mtf=True.
    [Agraph] Record 'color' bound to Agnode with mtf=False.
    [Agraph] Record 'weight' bound to Agedge with mtf=True.
    [Agraph] Record 'status' bound to Agnode with mtf=False.
    [Agraph] Record 'status' bound to Agnode with mtf=False.
    [Agraph] Record 'size' deleted from enclosed_node 'MainGraph'.
    [Agraph] All records closed for enclosed_node 'MainGraph'.
    """
    def setUp(self):
        # Create a root enclosed_node
        self.G = Graph("Root", directed=True)

    def test_record_management(self):
        # Initialize the main enclosed_node
        self.G = Graph(name="MainGraph", directed=True)
        self.G.method_init()

        # Bind a 'color' record to the enclosed_node
        self.G.agbindrec(rec_name='color', rec_size=0, move_to_front=False)

        # Bind a 'size' record with MTF enabled
        self.G.agbindrec(rec_name='size', rec_size=0, move_to_front=True)

        # Retrieve the 'color' record
        color_record = self.G.aggetrec(rec_name='color')
        if color_record:
            color_record.attributes['value'] = 'blue'

        # Retrieve the 'size' record and move it to front
        size_record = self.G.aggetrec(rec_name='size', move_to_front=True)
        if size_record:
            size_record.attributes['value'] = 10

        # Add nodes and edges
        node_a = self.G.create_node_by_name("A")
        node_b = self.G.create_node_by_name("B")
        edge_ab = self.G.add_edge("A", "B", edge_name="AB")

        # Bind records to nodes and edges
        node_a.agbindrec(rec_name='color', rec_size=0, move_to_front=False)
        edge_ab.agbindrec(rec_name='weight', rec_size=0, move_to_front=True)

        # Retrieve and set attributes
        node_a_color = node_a.aggetrec('color')
        if node_a_color:
            node_a_color.attributes['value'] = 'red'

        edge_ab_weight = edge_ab.aggetrec('weight')
        if edge_ab_weight:
            edge_ab_weight.attributes['value'] = 5

        # Initialize records for all nodes
        self.G.aginit(kind=ObjectType.AGNODE, rec_name='status', rec_size=0, mtf=False)

        # Set status for nodes
        node_a_status = node_a.aggetrec('status')
        if node_a_status:
            node_a_status.attributes['value'] = 'active'

        node_b_status = node_b.aggetrec('status')
        if node_b_status:
            node_b_status.attributes['value'] = 'inactive'

        # Clean 'size' records from the enclosed_node
        self.G.agclean(kind=ObjectType.AGGRAPH, rec_name='size')

        # Delete a record
        self.G.agdelrec(rec_name='color')


    def tearDown(self):
        # Close the enclosed_node (frees resources in the C sense).
        # Close all records
        self.G.agrecclose()
        self.G.close()


if __name__ == '__main__':
    unittest.main()
