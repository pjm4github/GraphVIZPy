"""
Consolidated tests for Subgraph operations: creation, iteration, deletion.
"""
import pytest

from pycode.cgraph.graph import Graph
from pycode.cgraph.node import Node
from pycode.cgraph.defines import ObjectType, GraphEvent


@pytest.fixture
def graph():
    """Directed graph with callback tracking for subgraph events."""
    g = Graph("TestGraph", directed=True)
    g.method_init()
    g._test_subgraph_added = False
    g._test_subgraph_deleted = False

    def on_added(subg):
        g._test_subgraph_added = True

    def on_deleted(subg):
        g._test_subgraph_deleted = True

    g.method_update(GraphEvent.SUBGRAPH_ADDED, on_added, action='add')
    g.method_update(GraphEvent.SUBGRAPH_DELETED, on_deleted, action='add')
    yield g
    g.close()


class TestSubgraphCreation:

    def test_create_regular_subgraph(self, graph):
        """create_subgraph creates a subgraph registered in the graph."""
        sub = graph.create_subgraph("Cluster1")
        assert "Cluster1" in graph.subgraphs
        assert sub.name == "Cluster1"

    def test_create_subgraph_by_name(self, graph):
        """agsubg creates subgraph by name."""
        sub = graph.agsubg("Cluster1", cflag=True)
        assert sub is not None
        assert "Cluster1" in graph.subgraphs

    def test_retrieve_existing_subgraph(self, graph):
        """agsubg with cflag=False retrieves existing subgraph."""
        sub1 = graph.agsubg("Cluster1", cflag=True)
        sub2 = graph.agsubg("Cluster1", cflag=False)
        assert sub1 is sub2

    def test_retrieve_nonexistent_returns_none(self, graph):
        """agsubg with cflag=False for nonexistent returns None."""
        sub = graph.agsubg("NoSuch", cflag=False)
        assert sub is None

    def test_duplicate_creation_returns_existing(self, graph):
        """Creating the same subgraph twice returns the same object."""
        sub1 = graph.create_subgraph("Sub1")
        sub2 = graph.create_subgraph("Sub1")
        assert sub1 is sub2

    def test_compound_subgraph(self, graph):
        """create_subgraph with enclosed_node creates compound subgraph."""
        node = graph.add_node("CompoundNode")
        sub = graph.create_subgraph("CompSub", enclosed_node=node)
        if sub is not None:
            assert node.compound_node_data.is_compound is True

    def test_subgraph_has_parent(self, graph):
        """Subgraph's parent is the graph that owns it."""
        sub = graph.create_subgraph("Sub1")
        assert sub.parent is graph

    def test_add_node_to_subgraph(self, graph):
        """Nodes can be added to subgraphs."""
        sub = graph.create_subgraph("Cluster1")
        sub.add_node("X")
        assert "X" in sub.nodes


class TestSubgraphIteration:

    def test_iterate_subgraphs(self, graph):
        """agfstsubg and agnxtsubg iterate through subgraphs."""
        graph.agsubg("Cluster1", cflag=True)
        graph.agsubg("Cluster2", cflag=True)
        graph.agsubg("Cluster3", cflag=True)

        names = []
        sub = graph.agfstsubg()
        while sub is not None:
            names.append(sub.name)
            sub = graph.agnxtsubg(sub)
        assert len(names) == 3


class TestSubgraphDeletion:

    def test_delete_subgraph(self, graph):
        """agdelsubg removes the subgraph."""
        sub = graph.agsubg("Cluster1", cflag=True)
        graph._test_subgraph_deleted = False
        result = graph.agdelsubg(sub)
        assert result is True
        assert graph.agsubg("Cluster1", cflag=False) is None

    def test_delete_nonexistent_subgraph(self, graph):
        """Deleting a nonexistent subgraph returns False."""
        fake = Graph("Fake", directed=True)
        fake.id = 999
        result = graph.agdelsubg(fake)
        assert result is False
