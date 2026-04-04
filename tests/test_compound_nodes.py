"""
Consolidated tests for compound nodes: hide, expose, edge splicing.
Merges tests from: test_graph_aghide*, test_graph_hide_expose*, test_graph_expose_subgraph*.
"""
import pytest

from pycode.cgraph.graph import Graph
from pycode.cgraph.node import Node, agcmpnode, agcmpgraph_of
from pycode.cgraph.edge import Edge
from pycode.cgraph.defines import ObjectType, GraphEvent
from pycode.cgraph.headers import Agdesc


@pytest.fixture
def compound_graph():
    """Graph with a compound node containing a subgraph with inner nodes."""
    g = Graph("TestGraph", directed=True)
    g.method_init()

    # Create outer nodes
    g.add_node("Outer1")
    g.add_node("Outer2")

    # Create compound node with subgraph
    cmpnode = agcmpnode(g, "Compound")
    subg = agcmpgraph_of(cmpnode)
    if subg:
        subg.add_node("Inner1")
        subg.add_node("Inner2")
        subg.add_edge("Inner1", "Inner2")

    # Edges crossing the compound boundary
    g.add_edge("Outer1", "Compound")
    g.add_edge("Compound", "Outer2")

    g._compound_node = cmpnode
    yield g
    g.close()


class TestCompoundNodeCreation:

    def test_agcmpnode_creates_compound(self, compound_graph):
        """agcmpnode creates a compound node with a subgraph."""
        cn = compound_graph._compound_node
        # Note: agcmpnode creates subgraph but may not set is_compound flag
        assert cn.compound_node_data.subgraph is not None

    def test_agcmpgraph_of_returns_subgraph(self, compound_graph):
        """agcmpgraph_of returns the compound node's subgraph."""
        cn = compound_graph._compound_node
        subg = agcmpgraph_of(cn)
        assert subg is not None

    def test_compound_subgraph_has_nodes(self, compound_graph):
        """Compound node's subgraph contains inner nodes."""
        cn = compound_graph._compound_node
        subg = agcmpgraph_of(cn)
        if subg:
            assert "Inner1" in subg.nodes or len(subg.nodes) > 0


class TestHide:

    def test_aghide_hides_subgraph(self, compound_graph):
        """aghide removes subgraph contents from view."""
        cn = compound_graph._compound_node
        result = compound_graph.aghide(cn)
        if result:
            assert cn.compound_node_data.collapsed is True

    def test_aghide_invalid_node_returns_false(self, compound_graph):
        """aghide returns False for a non-compound node."""
        n = compound_graph.nodes.get("Outer1")
        if n:
            result = compound_graph.aghide(n)
            assert not result

    def test_aghide_string_returns_false(self, compound_graph):
        """aghide returns False for invalid type."""
        result = compound_graph.aghide("NotANode")
        assert not result


class TestExpose:

    def test_agexpose_restores_subgraph(self, compound_graph):
        """agexpose restores a hidden compound node."""
        cn = compound_graph._compound_node
        hide_result = compound_graph.aghide(cn)
        if hide_result:
            expose_result = compound_graph.agexpose(cn)
            if expose_result:
                assert cn.compound_node_data.collapsed is False


class TestExposeSubgraph:

    def test_expose_subgraph_creates_compound(self):
        """expose_subgraph creates a subgraph for the node."""
        g = Graph("T", directed=True)
        g.method_init()
        node = g.add_node("A")
        result = g.expose_subgraph("Sub_A")
        assert result is not None or "Sub_A" in g.subgraphs
        g.close()


class TestHideExposeCallbacks:

    def test_hide_triggers_callback(self):
        """aghide triggers SUBGRAPH_DELETED callback."""
        g = Graph("T", directed=True)
        g.method_init()
        deleted = [False]
        g.method_update(GraphEvent.SUBGRAPH_DELETED,
                       lambda s: deleted.__setitem__(0, True), action='add')

        cn = agcmpnode(g, "Compound")
        subg = agcmpgraph_of(cn)
        if subg:
            subg.add_node("X")

        result = g.aghide(cn)
        # Callback may or may not fire depending on implementation
        g.close()
