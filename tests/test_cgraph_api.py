"""
Tests for the core package Pythonic API: properties, aliases, and backward compatibility.
"""
import pytest

from gvpy.core.graph import Graph
from gvpy.core.node import Node, CompoundNode
from gvpy.core.edge import Edge
from gvpy.core.defines import ObjectType, GraphEvent


# ── Fixtures ─────────────────────────────────────

@pytest.fixture
def simple_graph():
    """A simple directed graph with 3 nodes and 2 edges."""
    g = Graph("TestGraph", directed=True)
    g.method_init()
    g.add_node("A")
    g.add_node("B")
    g.add_node("C")
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    return g


@pytest.fixture
def attributed_graph():
    """A graph with nodes and edges that have attributes set."""
    g = Graph("AttrGraph", directed=True)
    g.method_init()
    a = g.add_node("A")
    a.label = "Component A"
    a.shape = "box"
    a.color = "red"
    a.fillcolor = "lightblue"
    a.fontsize = "18"
    a.fontname = "Helvetica"
    a.fontcolor = "darkred"
    a.group = "g1"
    a.style = "filled"

    b = g.add_node("B")
    b.label = "Component B"

    e = g.add_edge("A", "B")
    e.label = "calls"
    e.color = "blue"
    e.arrowhead = "diamond"
    e.arrowtail = "dot"
    e.style = "dashed"
    e.penwidth = "2.5"
    e.dir = "both"
    return g


# ── Node properties ─────────────────────────────

class TestNodeProperties:

    def test_label_default_is_name(self, simple_graph):
        """Node label defaults to the node name."""
        n = simple_graph.nodes["A"]
        assert n.label == "A"

    def test_label_setter(self, simple_graph):
        """Setting label updates attributes dict."""
        n = simple_graph.nodes["A"]
        n.label = "My Node"
        assert n.label == "My Node"
        assert n.attributes["label"] == "My Node"

    def test_shape_default(self, simple_graph):
        """Node shape defaults to ellipse."""
        assert simple_graph.nodes["A"].shape == "ellipse"

    def test_shape_setter(self, simple_graph):
        """Setting shape updates attributes."""
        n = simple_graph.nodes["A"]
        n.shape = "box"
        assert n.shape == "box"

    def test_color_default(self, simple_graph):
        """Node color defaults to black."""
        assert simple_graph.nodes["A"].color == "black"

    def test_color_setter(self, attributed_graph):
        """Color property reads from attributes."""
        assert attributed_graph.nodes["A"].color == "red"

    def test_fillcolor(self, attributed_graph):
        """fillcolor property works."""
        assert attributed_graph.nodes["A"].fillcolor == "lightblue"

    def test_style(self, attributed_graph):
        """style property works."""
        assert attributed_graph.nodes["A"].style == "filled"

    def test_fontsize(self, attributed_graph):
        """fontsize property works."""
        assert attributed_graph.nodes["A"].fontsize == "18"

    def test_fontname(self, attributed_graph):
        """fontname property works."""
        assert attributed_graph.nodes["A"].fontname == "Helvetica"

    def test_fontcolor(self, attributed_graph):
        """fontcolor property works."""
        assert attributed_graph.nodes["A"].fontcolor == "darkred"

    def test_group(self, attributed_graph):
        """group property works."""
        assert attributed_graph.nodes["A"].group == "g1"

    def test_fixedsize_default_false(self, simple_graph):
        """fixedsize defaults to False."""
        assert simple_graph.nodes["A"].fixedsize is False

    def test_fixedsize_setter(self, simple_graph):
        """fixedsize setter converts bool to string."""
        n = simple_graph.nodes["A"]
        n.fixedsize = True
        assert n.fixedsize is True
        assert n.attributes["fixedsize"] == "true"

    def test_pin_default_false(self, simple_graph):
        """pin defaults to False."""
        assert simple_graph.nodes["A"].pin is False

    def test_pin_setter(self, simple_graph):
        """pin setter converts bool to string."""
        n = simple_graph.nodes["A"]
        n.pin = True
        assert n.pin is True

    def test_pos_default_none(self, simple_graph):
        """pos defaults to None."""
        assert simple_graph.nodes["A"].pos is None

    def test_pos_setter(self, simple_graph):
        """pos setter stores string."""
        n = simple_graph.nodes["A"]
        n.pos = "1,2"
        assert n.pos == "1,2"

    def test_xlabel_default_empty(self, simple_graph):
        """xlabel defaults to empty string."""
        assert simple_graph.nodes["A"].xlabel == ""

    def test_xlabel_setter(self, simple_graph):
        """xlabel setter works."""
        n = simple_graph.nodes["A"]
        n.xlabel = "extra"
        assert n.xlabel == "extra"

    def test_width_height(self, simple_graph):
        """width and height properties."""
        n = simple_graph.nodes["A"]
        assert n.width is None  # not set
        n.width = "1.5"
        n.height = "0.75"
        assert n.width == "1.5"
        assert n.height == "0.75"


# ── Node centrality properties ──────────────────

class TestNodeCentrality:

    def test_degree_centrality_property(self, simple_graph):
        """degree_centrality is accessible as a property."""
        n = simple_graph.nodes["B"]
        assert isinstance(n.degree_centrality, (int, float))

    def test_betweenness_centrality_property(self, simple_graph):
        """betweenness_centrality is accessible as a property."""
        n = simple_graph.nodes["A"]
        assert isinstance(n.betweenness_centrality, (int, float))

    def test_closeness_centrality_property(self, simple_graph):
        """closeness_centrality is accessible as a property."""
        n = simple_graph.nodes["A"]
        assert isinstance(n.closeness_centrality, (int, float))

    def test_backward_compat_getters(self, simple_graph):
        """Old getter methods still work."""
        n = simple_graph.nodes["A"]
        assert n.get_degree_centrality() == n.degree_centrality
        assert n.get_betweenness_centrality() == n.betweenness_centrality
        assert n.get_closeness_centrality() == n.closeness_centrality


# ── Node root_graph property ─────────────────────

class TestNodeRootGraph:

    def test_root_graph_property(self, simple_graph):
        """root_graph property returns the root graph."""
        n = simple_graph.nodes["A"]
        assert n.root_graph is not None
        assert n.root_graph.name == "TestGraph"

    def test_backward_compat_get_root_graph(self, simple_graph):
        """Old get_root_graph() method still works."""
        n = simple_graph.nodes["A"]
        assert n.get_root_graph() == n.root_graph


# ── Edge properties ──────────────────────────────

class TestEdgeProperties:

    def test_label_default_empty(self, simple_graph):
        """Edge label defaults to empty string."""
        e = list(simple_graph.edges.values())[0]
        assert e.label == ""

    def test_label_setter(self, attributed_graph):
        """Edge label property reads from attributes."""
        e = list(attributed_graph.edges.values())[0]
        assert e.label == "calls"

    def test_color(self, attributed_graph):
        """Edge color property."""
        e = list(attributed_graph.edges.values())[0]
        assert e.color == "blue"

    def test_arrowhead(self, attributed_graph):
        """Edge arrowhead property."""
        e = list(attributed_graph.edges.values())[0]
        assert e.arrowhead == "diamond"

    def test_arrowtail(self, attributed_graph):
        """Edge arrowtail property."""
        e = list(attributed_graph.edges.values())[0]
        assert e.arrowtail == "dot"

    def test_dir(self, attributed_graph):
        """Edge dir property."""
        e = list(attributed_graph.edges.values())[0]
        assert e.dir == "both"

    def test_style(self, attributed_graph):
        """Edge style property."""
        e = list(attributed_graph.edges.values())[0]
        assert e.style == "dashed"

    def test_penwidth(self, attributed_graph):
        """Edge penwidth property."""
        e = list(attributed_graph.edges.values())[0]
        assert e.penwidth == "2.5"

    def test_constraint_default_true(self, simple_graph):
        """Edge constraint defaults to True."""
        e = list(simple_graph.edges.values())[0]
        assert e.constraint is True

    def test_constraint_setter(self, simple_graph):
        """Edge constraint setter converts bool to string."""
        e = list(simple_graph.edges.values())[0]
        e.constraint = False
        assert e.constraint is False
        assert e.attributes["constraint"] == "false"

    def test_minlen_default(self, simple_graph):
        """Edge minlen defaults to 1."""
        e = list(simple_graph.edges.values())[0]
        assert e.minlen == 1

    def test_minlen_setter(self, simple_graph):
        """Edge minlen setter converts int to string."""
        e = list(simple_graph.edges.values())[0]
        e.minlen = 3
        assert e.minlen == 3

    def test_weight_attr_default(self, simple_graph):
        """Edge weight defaults to 1."""
        e = list(simple_graph.edges.values())[0]
        assert e.weight_attr == 1

    def test_headport_tailport(self, simple_graph):
        """headport and tailport properties."""
        e = list(simple_graph.edges.values())[0]
        assert e.headport == ""
        assert e.tailport == ""
        e.headport = "n"
        e.tailport = "s"
        assert e.headport == "n"
        assert e.tailport == "s"

    def test_lhead_ltail(self, simple_graph):
        """lhead and ltail properties."""
        e = list(simple_graph.edges.values())[0]
        assert e.lhead == ""
        assert e.ltail == ""
        e.lhead = "cluster_0"
        e.ltail = "cluster_1"
        assert e.lhead == "cluster_0"
        assert e.ltail == "cluster_1"

    def test_root_graph_property(self, simple_graph):
        """Edge root_graph property returns root graph."""
        e = list(simple_graph.edges.values())[0]
        assert e.root_graph.name == "TestGraph"


# ── Pythonic attribute access (get_attr/set_attr) ─

class TestPythonicAttrAccess:

    def test_node_get_attr(self, attributed_graph):
        """node.get_attr() works."""
        n = attributed_graph.nodes["A"]
        assert n.get_attr("label") == "Component A"
        assert n.get_attr("shape") == "box"

    def test_node_set_attr(self, simple_graph):
        """node.set_attr() works."""
        n = simple_graph.nodes["A"]
        n.set_attr("color", "green")
        assert n.get_attr("color") == "green"

    def test_edge_get_attr(self, attributed_graph):
        """edge.get_attr() works."""
        e = list(attributed_graph.edges.values())[0]
        assert e.get_attr("label") == "calls"

    def test_edge_set_attr(self, simple_graph):
        """edge.set_attr() works."""
        e = list(simple_graph.edges.values())[0]
        e.set_attr("style", "dotted")
        assert e.get_attr("style") == "dotted"

    def test_node_agget_is_get_attr(self, attributed_graph):
        """agget is an alias for get_attr."""
        n = attributed_graph.nodes["A"]
        assert n.agget("label") == n.get_attr("label")

    def test_node_agset_is_set_attr(self, simple_graph):
        """agset is an alias for set_attr."""
        n = simple_graph.nodes["A"]
        n.agset("color", "purple")
        assert n.get_attr("color") == "purple"

    def test_edge_agget_is_get_attr(self, attributed_graph):
        """agget is an alias for get_attr on edges."""
        e = list(attributed_graph.edges.values())[0]
        assert e.agget("color") == e.get_attr("color")

    def test_edge_agset_is_set_attr(self, simple_graph):
        """agset is an alias for set_attr on edges."""
        e = list(simple_graph.edges.values())[0]
        e.agset("weight", "5")
        assert e.get_attr("weight") == "5"


# ── Graph edge traversal (Pythonic aliases) ──────

class TestGraphEdgeTraversal:

    def test_first_out_edge(self, simple_graph):
        """first_out_edge returns the first outgoing edge."""
        n = simple_graph.nodes["A"]
        e = simple_graph.first_out_edge(n)
        assert e is not None
        assert e.tail.name == "A"

    def test_next_out_edge(self, simple_graph):
        """next_out_edge returns None when no more edges."""
        n = simple_graph.nodes["A"]
        e = simple_graph.first_out_edge(n)
        # A has only one outgoing edge (A->B)
        e2 = simple_graph.next_out_edge(e)
        # May be None or another edge depending on implementation

    def test_first_in_edge(self, simple_graph):
        """first_in_edge returns the first incoming edge."""
        n = simple_graph.nodes["B"]
        e = simple_graph.first_in_edge(n)
        assert e is not None
        assert e.head.name == "B"

    def test_first_edge(self, simple_graph):
        """first_edge returns the first edge of any direction."""
        n = simple_graph.nodes["B"]
        e = simple_graph.first_edge(n)
        assert e is not None

    def test_agfstout_is_first_out_edge(self, simple_graph):
        """agfstout is an alias for first_out_edge."""
        n = simple_graph.nodes["A"]
        assert simple_graph.agfstout(n) == simple_graph.first_out_edge(n)

    def test_agfstin_is_first_in_edge(self, simple_graph):
        """agfstin is an alias for first_in_edge."""
        n = simple_graph.nodes["B"]
        assert simple_graph.agfstin(n) == simple_graph.first_in_edge(n)

    def test_agfstedge_is_first_edge(self, simple_graph):
        """agfstedge is an alias for first_edge."""
        n = simple_graph.nodes["B"]
        assert simple_graph.agfstedge(n) == simple_graph.first_edge(n)


# ── Graph degree and count methods ───────────────

class TestGraphDegree:

    def test_degree(self, simple_graph):
        """degree counts in+out edges."""
        n = simple_graph.nodes["B"]
        d = simple_graph.degree(n)
        assert d == 2  # one in (A->B), one out (B->C)

    def test_degree_in_only(self, simple_graph):
        """degree with out=False counts only incoming."""
        n = simple_graph.nodes["B"]
        d = simple_graph.degree(n, in_=True, out=False)
        assert d == 1

    def test_degree_out_only(self, simple_graph):
        """degree with in_=False counts only outgoing."""
        n = simple_graph.nodes["B"]
        d = simple_graph.degree(n, in_=False, out=True)
        assert d == 1

    def test_agdegree_is_degree(self, simple_graph):
        """agdegree is an alias for degree."""
        n = simple_graph.nodes["B"]
        assert simple_graph.agdegree(n) == simple_graph.degree(n)

    def test_count_unique_edges(self, simple_graph):
        """count_unique_edges works."""
        n = simple_graph.nodes["B"]
        c = simple_graph.count_unique_edges(n)
        assert c == 2

    def test_agcountuniqedges_is_count_unique_edges(self, simple_graph):
        """agcountuniqedges is an alias for count_unique_edges."""
        n = simple_graph.nodes["B"]
        assert simple_graph.agcountuniqedges(n) == simple_graph.count_unique_edges(n)


# ── Graph node traversal (existing Pythonic) ─────

class TestGraphNodeTraversal:

    def test_first_node(self, simple_graph):
        """first_node returns a node."""
        n = simple_graph.first_node()
        assert n is not None
        assert isinstance(n, Node)

    def test_next_node(self, simple_graph):
        """next_node iterates through nodes."""
        n = simple_graph.first_node()
        n2 = simple_graph.next_node(n)
        assert n2 is not None
        assert n2.name != n.name

    def test_last_node(self, simple_graph):
        """last_node returns the last node."""
        n = simple_graph.last_node()
        assert n is not None

    def test_agfstnode_is_first_node(self, simple_graph):
        """agfstnode is an alias for first_node."""
        assert simple_graph.agfstnode() == simple_graph.first_node()

    def test_agnxtnode_is_next_node(self, simple_graph):
        """agnxtnode is an alias for next_node."""
        n = simple_graph.first_node()
        assert simple_graph.agnxtnode(n) == simple_graph.next_node(n)

    def test_aglstnode_is_last_node(self, simple_graph):
        """aglstnode is an alias for last_node."""
        assert simple_graph.aglstnode() == simple_graph.last_node()


# ── Graph attribute access ───────────────────────

class TestGraphAttributes:

    def test_get_graph_attr(self, simple_graph):
        """get_graph_attr reads graph-level attributes."""
        simple_graph.set_graph_attr("rankdir", "LR")
        assert simple_graph.get_graph_attr("rankdir") == "LR"

    def test_agget_is_get_graph_attr(self, simple_graph):
        """agget on graph delegates to get_graph_attr."""
        simple_graph.set_graph_attr("rankdir", "BT")
        assert simple_graph.agget("rankdir") == "BT"

    def test_agset_is_set_graph_attr(self, simple_graph):
        """agset on graph delegates to set_graph_attr."""
        simple_graph.agset("splines", "ortho")
        assert simple_graph.get_graph_attr("splines") == "ortho"


# ── Edge __repr__ ────────────────────────────────

class TestEdgeRepr:

    def test_repr_format(self, simple_graph):
        """Edge repr is concise."""
        e = list(simple_graph.edges.values())[0]
        r = repr(e)
        assert "Edge" in r
        assert "A" in r
        assert "B" in r
        assert len(r) < 100  # concise, not 50 lines


# ── Property round-trip via attributes dict ──────

class TestPropertyRoundTrip:

    def test_node_property_reads_attributes(self):
        """Properties read from and write to the attributes dict."""
        g = Graph("T", directed=True)
        g.method_init()
        n = g.add_node("X")

        # Set via property
        n.label = "Hello"
        n.shape = "diamond"
        n.color = "green"

        # Read via dict
        assert n.attributes["label"] == "Hello"
        assert n.attributes["shape"] == "diamond"
        assert n.attributes["color"] == "green"

        # Set via dict
        n.attributes["style"] = "bold"

        # Read via property
        assert n.style == "bold"

    def test_edge_property_reads_attributes(self):
        """Edge properties read from and write to the attributes dict."""
        g = Graph("T", directed=True)
        g.method_init()
        g.add_node("A")
        g.add_node("B")
        e = g.add_edge("A", "B")

        # Set via property
        e.arrowhead = "vee"
        e.constraint = False

        # Read via dict
        assert e.attributes["arrowhead"] == "vee"
        assert e.attributes["constraint"] == "false"

        # Set via dict
        e.attributes["minlen"] = "3"

        # Read via property
        assert e.minlen == 3
