"""Regression: phase 4 must see TB-frame coords regardless of rankdir.

``position.apply_rankdir`` used to run at the end of phase 3, so phase 4
received LR/RL/BT-rotated coordinates but its internal code was written
assuming y is the rank axis (``rank_box`` / ``makeregularend`` /
``maximal_bbox``).  That mismatch made the box corridor pathplan
received degenerate — on ``test_data/2239.dot`` it lost 45/86 edges,
on ``test_data/2796.dot`` 144/213.

The fix wraps ``phase4_routing`` with ``_phase4_to_tb`` at entry and
``_phase4_from_tb`` at exit: the former reverses apply_rankdir (node
coords + cluster bboxes), phase 4 runs pure-TB, then the latter
re-applies and transforms every new edge spline / label anchor back
to the output frame.
"""
from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
from gvpy.grammar.gv_reader import read_dot


def _routed_fraction(layout):
    edges = [le for le in (layout.ledges + layout._chain_edges)
             if not le.virtual]
    if not edges:
        return 1.0
    return sum(1 for le in edges if le.route.points) / len(edges)


def test_lr_simple_chain_fully_routed():
    g = read_dot("digraph { rankdir=LR; a -> b -> c -> d; a -> d; a -> c }")
    layout = DotGraphInfo(g)
    layout.layout()
    assert _routed_fraction(layout) == 1.0


def test_lr_cluster_edges_routed():
    g = read_dot("""
        digraph { rankdir=LR
          subgraph cluster_0 { a; b; a -> b }
          subgraph cluster_1 { c; d; c -> d }
          b -> c
          a -> d
        }
    """)
    layout = DotGraphInfo(g)
    layout.layout()
    assert _routed_fraction(layout) == 1.0


def test_bt_simple_chain_fully_routed():
    g = read_dot("digraph { rankdir=BT; a -> b -> c -> d; a -> d }")
    layout = DotGraphInfo(g)
    layout.layout()
    assert _routed_fraction(layout) == 1.0


def test_rl_simple_chain_fully_routed():
    g = read_dot("digraph { rankdir=RL; a -> b -> c -> d; a -> d }")
    layout = DotGraphInfo(g)
    layout.layout()
    assert _routed_fraction(layout) == 1.0


def test_lr_splines_rotate_to_output_frame():
    # After phase 4, edge splines must live in LR output frame: for a
    # left-to-right chain, points should be monotonic(ish) in x.
    g = read_dot("digraph { rankdir=LR; a -> b -> c }")
    layout = DotGraphInfo(g)
    layout.layout()
    a = layout.lnodes["a"]
    c = layout.lnodes["c"]
    # Nodes must be in LR (a leftmost, c rightmost).
    assert a.x < c.x
    # The a -> b edge must start near a.x and end near b.x; if the
    # spline were left in TB frame this check would fail because x
    # values would be cross-rank, not rank-axis.
    ab = next(le for le in (layout.ledges + layout._chain_edges)
              if not le.virtual and le.tail_name == "a"
              and le.head_name == "b")
    assert ab.route.points
    x0, _ = ab.route.points[0]
    xn, _ = ab.route.points[-1]
    b = layout.lnodes["b"]
    assert abs(x0 - a.x) < a.width  # starts on a's boundary, not far away
    assert abs(xn - b.x) < b.width
