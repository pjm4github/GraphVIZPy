import pytest

from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.graph import Graph, agnextseq
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc, AgIdDisc, CallbackFunctions, Agcbstack


class TestGraphCreateSubgraph:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = Graph(name="TestGraph")
        yield

    def test_create_regular_subgraph(self):
        """Test creating a regular subgraph and verifying its registration and parent."""
        subgraph = self.graph.create_subgraph("Subgraph1")
        assert "Subgraph1" in self.graph.subgraphs
        assert subgraph.name == "Subgraph1"
        assert subgraph.parent == self.graph

    def test_create_compound_subgraph(self):
        """Test creating a compound subgraph enclosed in a node."""
        node = self.graph.create_node_by_name("CompoundNode")
        subgraph = self.graph.create_subgraph("Subgraph_Compound", enclosed_node=node)
        assert "CompoundNode" in self.graph.subgraphs
        assert subgraph == self.graph.subgraphs["CompoundNode"]
        assert node.compound_node_data.is_compound
        assert not node.compound_node_data.collapsed

    def test_duplicate_subgraph_creation(self):
        """Test that creating a subgraph with the same name returns the existing one."""
        subgraph1 = self.graph.create_subgraph("Subgraph1")
        subgraph2 = self.graph.create_subgraph("Subgraph1")
        assert subgraph1 == subgraph2

    def test_duplicate_compound_subgraph_creation(self):
        """Test that creating a second compound subgraph for the same node returns the existing one."""
        node = self.graph.create_node_by_name("CompoundNode")
        subgraph1 = self.graph.create_subgraph("Subgraph_Compound", enclosed_node=node)
        subgraph2 = self.graph.create_subgraph("Subgraph_Compound_Duplicate", enclosed_node=node)
        assert subgraph1 == subgraph2
