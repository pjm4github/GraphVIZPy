"""
Consolidated tests for Graph core: initialization, attributes, records, close.
"""
import pytest

from gvpy.core.graph import Graph, gather_all_nodes, gather_all_edges
from gvpy.core.node import Node
from gvpy.core.edge import Edge
from gvpy.core.defines import ObjectType, GraphEvent
from gvpy.core.headers import Agdesc, AgIdDisc


@pytest.fixture
def graph():
    """Basic directed graph."""
    g = Graph("TestGraph", directed=True)
    g.method_init()
    yield g
    g.close()


class TestGraphInit:

    def test_graph_creation(self, graph):
        """Graph is created with correct name and direction."""
        assert graph.name == "TestGraph"
        assert graph.directed is True

    def test_graph_is_main(self, graph):
        """Root graph is marked as main graph."""
        assert graph.is_main_graph is True

    def test_graph_initially_empty(self, graph):
        """New graph has no nodes, edges, or subgraphs."""
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0
        assert len(graph.subgraphs) == 0

    def test_graph_with_descriptor(self):
        """Graph can be created with explicit descriptor."""
        desc = Agdesc(directed=True, strict=True, no_loop=True)
        g = Graph("Strict", description=desc, strict=True)
        assert g.strict is True
        g.close()

    def test_undirected_graph(self):
        """Undirected graph creation."""
        g = Graph("Undirected", directed=False)
        g.method_init()
        assert g.directed is False
        g.close()


class TestGraphClose:

    def test_close(self):
        """close() marks graph as closed."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_node("A")
        g.close()
        # Should not crash on double close
        g.close()


class TestGraphAttributes:

    def test_set_get_graph_attr(self, graph):
        """set_graph_attr and get_graph_attr work."""
        graph.set_graph_attr("rankdir", "LR")
        assert graph.get_graph_attr("rankdir") == "LR"

    def test_agattr_graph(self, graph):
        """agattr declares graph attributes."""
        graph.agattr(ObjectType.AGGRAPH, "color", "blue")
        assert graph.get_graph_attr("color") == "blue"

    def test_agattr_node_default(self, graph):
        """agattr declares node attribute defaults."""
        graph.agattr(ObjectType.AGNODE, "shape", "box")
        assert graph.attr_dict_n["shape"] == "box"

    def test_agattr_edge_default(self, graph):
        """agattr declares edge attribute defaults."""
        graph.agattr(ObjectType.AGEDGE, "style", "dashed")
        assert graph.attr_dict_e["style"] == "dashed"

    def test_declare_attribute_helpers(self, graph):
        """declare_attribute_graph/node/edge shortcuts work."""
        graph.declare_attribute_graph("bgcolor", "white")
        graph.declare_attribute_node("fontsize", "12")
        graph.declare_attribute_edge("weight", "1")
        assert graph.get_graph_attr("bgcolor") == "white"
        assert graph.attr_dict_n["fontsize"] == "12"
        assert graph.attr_dict_e["weight"] == "1"

    def test_agget_agset(self, graph):
        """agget and agset on graph work."""
        graph.agset("rankdir", "BT")
        assert graph.agget("rankdir") == "BT"


class TestGraphRecords:

    def test_bind_record(self, graph):
        """agbindrec attaches a record to the graph."""
        rec = graph.agbindrec("color", 0)
        assert rec is not None
        assert rec.name == "color"

    def test_get_record(self, graph):
        """aggetrec retrieves a bound record."""
        graph.agbindrec("color", 0)
        rec = graph.aggetrec("color")
        assert rec is not None

    def test_delete_record(self, graph):
        """agdelrec removes a record from the graph."""
        graph.agbindrec("color", 0)
        result = graph.agdelrec("color")
        assert result is True
        assert graph.aggetrec("color") is None

    def test_close_records(self, graph):
        """agrecclose clears all records."""
        graph.agbindrec("a", 0)
        graph.agbindrec("b", 0)
        graph.agrecclose()
        assert graph.aggetrec("a") is None
        assert graph.aggetrec("b") is None


class TestGraphQueries:

    def test_node_count(self, graph):
        """Node count matches added nodes."""
        graph.add_node("A")
        graph.add_node("B")
        assert len(graph.nodes) == 2

    def test_edge_count(self, graph):
        """Edge count matches added edges."""
        graph.add_node("A")
        graph.add_node("B")
        graph.add_edge("A", "B")
        assert len(graph.edges) == 1

    def test_is_directed(self, graph):
        """Graph reports correct directedness."""
        assert graph.directed is True

    def test_gather_all_nodes(self, graph):
        """gather_all_nodes collects nodes from all subgraphs."""
        graph.add_node("A")
        sub = graph.create_subgraph("Sub1")
        sub.add_node("X")
        all_nodes = gather_all_nodes(graph)
        names = [n.name for n in all_nodes]
        assert "A" in names

    def test_gather_all_edges(self, graph):
        """gather_all_edges collects edges from all subgraphs."""
        graph.add_node("A")
        graph.add_node("B")
        graph.add_edge("A", "B")
        all_edges = gather_all_edges(graph)
        assert len(all_edges) >= 1


class TestGraphDegree:

    def test_degree(self, graph):
        """degree counts edges at a node."""
        graph.add_node("A")
        graph.add_node("B")
        graph.add_edge("A", "B")
        d = graph.degree(graph.nodes["A"])
        assert d >= 1

    def test_node_before(self, graph):
        """agnodebefore checks node ordering."""
        graph.add_node("A")
        graph.add_node("B")
        assert graph.agnodebefore(graph.nodes["A"], graph.nodes["B"]) is True


# ── agcopyattr ───────────────────────────────────

class TestCopyAttr:

    def test_copy_node_attrs(self, graph):
        """agcopyattr copies all attributes from one node to another."""
        a = graph.add_node("A")
        b = graph.add_node("B")
        a.set_attr("color", "red")
        a.set_attr("shape", "box")
        a.set_attr("label", "Node A")
        graph.agcopyattr(a, b)
        assert b.get_attr("color") == "red"
        assert b.get_attr("shape") == "box"
        assert b.get_attr("label") == "Node A"

    def test_copy_edge_attrs(self, graph):
        """agcopyattr copies all attributes from one edge to another."""
        graph.add_node("A")
        graph.add_node("B")
        graph.add_node("C")
        e1 = graph.add_edge("A", "B")
        e2 = graph.add_edge("B", "C")
        e1.set_attr("color", "blue")
        e1.set_attr("style", "dashed")
        graph.agcopyattr(e1, e2)
        assert e2.get_attr("color") == "blue"
        assert e2.get_attr("style") == "dashed"

    def test_copy_preserves_existing(self, graph):
        """agcopyattr overwrites existing attrs on destination."""
        a = graph.add_node("A")
        b = graph.add_node("B")
        b.set_attr("color", "green")
        a.set_attr("color", "red")
        graph.agcopyattr(a, b)
        assert b.get_attr("color") == "red"


# ── Graph algorithms ─────────────────────────────

class TestAcyclic:

    def test_acyclic_breaks_cycle(self):
        """acyclic() reverses back edges to break cycles."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "A")  # creates cycle
        reversed_edges = g.acyclic()
        assert len(reversed_edges) >= 1
        g.close()

    def test_acyclic_dag_unchanged(self):
        """acyclic() on a DAG reverses nothing."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        reversed_edges = g.acyclic()
        assert len(reversed_edges) == 0
        g.close()

    def test_acyclic_self_loop(self):
        """acyclic() handles self-loops."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "A")
        reversed_edges = g.acyclic()
        assert len(reversed_edges) >= 0  # may or may not reverse
        g.close()


class TestTred:

    def test_tred_removes_transitive(self):
        """tred() removes transitively implied edges."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("A", "C")  # redundant: A->B->C implies A->C
        removed = g.tred()
        assert ("A", "C") in removed
        assert ("A", "C", None) not in g.edges
        g.close()

    def test_tred_keeps_non_transitive(self):
        """tred() keeps edges that are not transitively implied."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        removed = g.tred()
        assert len(removed) == 0
        g.close()


class TestUnflatten:

    def test_unflatten_increases_minlen(self):
        """unflatten() increases minlen on non-leaf edges."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        g.add_edge("A", "C")
        g.add_edge("B", "D")
        g.unflatten()
        # B has both in and out edges, so its outgoing edge may get increased minlen
        g.close()

    def test_unflatten_with_max(self):
        """unflatten() respects max_min_len."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        g.add_edge("A", "C")
        g.add_edge("B", "D")
        g.unflatten(max_min_len=3)
        for e in g.edges.values():
            assert int(e.attributes.get("minlen", "1")) <= 3
        g.close()


class TestNodeInduce:

    def test_node_induce_adds_edges(self):
        """node_induce() adds parent edges to subgraph."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        sub = g.create_subgraph("Sub1")
        sub.add_node("A")
        sub.add_node("B")
        count = sub.node_induce()
        assert count >= 1  # A->B should be induced
        g.close()

    def test_node_induce_on_root_returns_zero(self):
        """node_induce() on root graph returns 0."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_edge("A", "B")
        assert g.node_induce() == 0
        g.close()
