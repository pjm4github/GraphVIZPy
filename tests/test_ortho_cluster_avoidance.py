"""Regression tests for ortho router's cluster-avoidance heuristic
(option B2) and the audit-tool fix that was masking its effect.

Ortho output is a right-angle polyline.  Before:
  - ``splines.ortho_route`` always emitted ``p_start → (p_start.x,
    mid_y) → (p_end.x, mid_y) → p_end`` regardless of whether the
    horizontal leg at ``mid_y`` crossed foreign clusters.
  - ``filters/count_cluster_crossings`` mistakenly classified 4-point
    polylines as cubic beziers and sampled a curve through the
    control polygon, flagging phantom crossings.

Both fixed here.
"""
from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
from gvpy.grammar.gv_reader import read_dot


def test_ortho_detours_around_nonmember_cluster():
    # a and c are endpoints; b sits in its own cluster between them on
    # the rank axis.  With the naive Z the horizontal leg would pass
    # through cluster_b's bbox.  After B2 the mid_y shifts so the leg
    # runs above or below cluster_b.
    src = """
        digraph {
            splines=ortho
            a -> c
            subgraph cluster_b { b }
            a -> b
            b -> c
        }
    """
    g = read_dot(src)
    layout = DotGraphInfo(g)
    layout.layout()
    le = next(e for e in (layout.ledges + layout._chain_edges)
              if not e.virtual and e.tail_name == "a" and e.head_name == "c")
    assert le.route.points, "edge lost its route"
    # Every turn point must either be outside cluster_b.bb in x or y.
    cl = next(c for c in layout._clusters if c.name == "cluster_b")
    x1, y1, x2, y2 = cl.bb
    for px, py in le.route.points:
        inside = x1 < px < x2 and y1 < py < y2
        assert not inside, (
            f"ortho Z waypoint {(px, py)} sits inside cluster_b bb {cl.bb}")


def test_polyline_not_misinterpreted_as_bezier_by_audit():
    # Four-point right-angle Z — count_cluster_crossings used to
    # classify any 4-point list as a cubic bezier and sample a curve
    # through the control polygon.  With spline_type='polyline' the
    # audit must interpret as a polyline and use linear segment
    # checks.  The bbox below sits inside the "notch" of the Z — the
    # polyline never enters it, but the cubic bezier through the
    # same 4 control points bulges into it.
    from porting_scripts.count_cluster_crossings import _segments_cross_bbox

    pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    # bbox in the center of the Z's open side — no polyline segment
    # crosses it, but a cubic with those control points does.
    bb = (30.0, 30.0, 70.0, 70.0)
    assert not _segments_cross_bbox(pts, bb, is_bezier=False), (
        "polyline must not be reported as crossing an interior bbox")
    assert _segments_cross_bbox(pts, bb, is_bezier=True), (
        "bezier interpretation should hit the interior bbox — if this "
        "also returns False the test bbox is the wrong shape, not a real "
        "regression")
