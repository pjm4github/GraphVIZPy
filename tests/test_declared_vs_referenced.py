"""Regression tests for the declared-vs-referenced cluster
membership fix (task #148).

The DOT parser used to call ``Graph.add_node`` with the default
``declared=True`` flag for both node statements AND edge endpoint
resolutions.  Result: any edge like ``a -> b`` written inside
``subgraph cluster_X { ... }`` added both ``a`` and ``b`` to
``cluster_X.nodes`` — even if they were declared elsewhere.

The fix: ``_resolve_node_id`` and ``Graph.add_edge`` now use
``declared=False`` when resolving edge endpoints, matching C
cgraph's agedge + agnode semantics.  See
``Docs/declared_vs_referenced_proposal.md``.
"""
from gvpy.grammar.gv_reader import read_dot


def test_edge_references_dont_add_to_subgraph():
    """A node declared in cluster_A and referenced from an edge
    inside cluster_B's body must NOT become a cluster_B member."""
    src = """digraph {
      subgraph cluster_A {
        a;
      }
      subgraph cluster_B {
        b;
        b -> a;
      }
    }"""
    g = read_dot(src)
    cluster_a = g.subgraphs["cluster_A"]
    cluster_b = g.subgraphs["cluster_B"]
    assert "a" in cluster_a.nodes, "a should be a member of cluster_A (declared there)"
    assert "b" in cluster_b.nodes, "b should be a member of cluster_B (declared there)"
    assert "a" not in cluster_b.nodes, (
        "a was only *referenced* in cluster_B's body via an edge; it "
        "should NOT be a cluster_B member.  See "
        "Docs/declared_vs_referenced_proposal.md."
    )
    assert "b" not in cluster_a.nodes, (
        "b is not referenced or declared in cluster_A; it should not "
        "be a cluster_A member."
    )


def test_singleton_wrapper_owns_its_node():
    """The DOT convention ``subgraph clusterc<NNNN> { cXXXX; }``
    uses singleton wrappers for non-cluster nodes.  When such a
    wrapper is a sibling of another cluster that merely references
    the node via an edge, the node belongs to the wrapper — not
    the sibling.

    (Observed on aa1332.dot: cluster_4250 referenced c4051 in an
    edge while clusterc4051 actually declared c4051.  c4051 was
    being mis-attributed to cluster_4250.)
    """
    src = """digraph {
      subgraph cluster_parent {
        subgraph cluster_uses_it {
          c1;
          c1 -> c99;
        }
        subgraph cluster_c99 {
          c99;
        }
      }
    }"""
    g = read_dot(src)
    parent = g.subgraphs["cluster_parent"]
    uses = parent.subgraphs["cluster_uses_it"]
    owner = parent.subgraphs["cluster_c99"]
    assert "c99" in owner.nodes, "c99's declared home is cluster_c99"
    assert "c99" not in uses.nodes, (
        "c99 was only referenced by the edge c1 -> c99 inside "
        "cluster_uses_it; it should not be a member there."
    )


def test_forward_reference_resolves_to_declaration_home():
    """An edge can reference a node before the node_stmt appears
    in the source.  The later declaration must establish the home,
    not the earlier reference."""
    src = """digraph {
      subgraph cluster_A {
        a -> b;
      }
      subgraph cluster_B {
        b;
      }
    }"""
    g = read_dot(src)
    cluster_a = g.subgraphs["cluster_A"]
    cluster_b = g.subgraphs["cluster_B"]
    assert "b" in cluster_b.nodes, "b is declared in cluster_B"
    assert "b" not in cluster_a.nodes, (
        "The earlier edge reference to b in cluster_A should not "
        "make it a cluster_A member — the later declaration in "
        "cluster_B owns it."
    )


def test_node_stmt_still_registers_membership():
    """Belt-and-suspenders: ensure the declared=True default path
    still works — node_stmt inside a subgraph body adds the node
    as a member.  Regression guard against a future typo that
    flips the default."""
    src = """digraph {
      subgraph cluster_X {
        x1;
        x2 [label="two"];
      }
    }"""
    g = read_dot(src)
    cluster_x = g.subgraphs["cluster_X"]
    assert "x1" in cluster_x.nodes
    assert "x2" in cluster_x.nodes
