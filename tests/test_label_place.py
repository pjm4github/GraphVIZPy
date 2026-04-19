"""Tests for F+.1 / F+.2 label-placement functions in label_place.py."""
import math

import pytest

from gvpy.engines.layout.dot.edge_route import EdgeRoute
from gvpy.engines.layout.dot.label_place import (
    add_edge_labels,
    edge_midpoint,
    end_points,
    getsplinepoints,
    make_port_labels,
    place_portlabel,
    place_vnlabel,
    polyline_midpoint,
    PORT_LABEL_ANGLE,
    PORT_LABEL_DISTANCE,
)


# ═══════════════════════════════════════════════════════════════
#  end_points
# ═══════════════════════════════════════════════════════════════

class TestEndPoints:

    def test_polyline_no_flags_uses_first_and_last(self):
        r = EdgeRoute(points=[(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)],
                      spline_type="polyline")
        p, q = end_points(r)
        assert p == (0.0, 0.0)
        assert q == (20.0, 0.0)

    def test_sflag_overrides_start(self):
        r = EdgeRoute(points=[(0.0, 0.0), (20.0, 0.0)],
                      sflag=1, sp=(1.5, 2.5))
        p, q = end_points(r)
        assert p == (1.5, 2.5)
        assert q == (20.0, 0.0)

    def test_eflag_overrides_end(self):
        r = EdgeRoute(points=[(0.0, 0.0), (20.0, 0.0)],
                      eflag=1, ep=(19.0, 1.0))
        p, q = end_points(r)
        assert p == (0.0, 0.0)
        assert q == (19.0, 1.0)

    def test_empty_points_returns_origin(self):
        r = EdgeRoute(points=[])
        p, q = end_points(r)
        assert p == (0.0, 0.0)
        assert q == (0.0, 0.0)


# ═══════════════════════════════════════════════════════════════
#  polyline_midpoint
# ═══════════════════════════════════════════════════════════════

class TestPolylineMidpoint:

    def test_polyline_straight_two_points(self):
        r = EdgeRoute(points=[(0.0, 0.0), (10.0, 0.0)], spline_type="polyline")
        mid, pp, pq = polyline_midpoint(r)
        assert mid == (5.0, 0.0)
        assert pp == (0.0, 0.0) and pq == (10.0, 0.0)

    def test_polyline_three_points_midpoint_on_segment(self):
        # Two 10-unit segments; midpoint lands at the junction.
        r = EdgeRoute(points=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)],
                      spline_type="polyline")
        mid, pp, pq = polyline_midpoint(r)
        # Half-length = 10; first segment is 10 so midpoint is at its end.
        assert mid == (10.0, 0.0)

    def test_polyline_unequal_segments(self):
        # 4-unit then 8-unit segment; total 12, half 6. First segment
        # consumes 4, leaving 2 in second segment (length 8).
        r = EdgeRoute(points=[(0.0, 0.0), (4.0, 0.0), (12.0, 0.0)],
                      spline_type="polyline")
        mid, pp, pq = polyline_midpoint(r)
        assert mid == pytest.approx((6.0, 0.0))
        assert pp == (4.0, 0.0) and pq == (12.0, 0.0)

    def test_bezier_stride3_midpoint(self):
        # Two cubic segments: [P0, C1, C2, P1, C3, C4, P2]
        # Segment anchors are P0=(0,0), P1=(10,0), P2=(20,0).
        pts = [(0.0, 0.0), (2.0, 5.0), (4.0, 5.0),
               (10.0, 0.0),
               (12.0, -5.0), (14.0, -5.0),
               (20.0, 0.0)]
        r = EdgeRoute(points=pts, spline_type="bezier")
        mid, pp, pq = polyline_midpoint(r)
        # Straight-line anchor-to-anchor length = 20; midpoint is at x=10.
        assert mid == pytest.approx((10.0, 0.0))


# ═══════════════════════════════════════════════════════════════
#  edge_midpoint
# ═══════════════════════════════════════════════════════════════

class _FakeEdge:
    def __init__(self, route):
        self.route = route


class TestEdgeMidpoint:

    def test_empty_points(self):
        le = _FakeEdge(EdgeRoute(points=[]))
        assert edge_midpoint(None, le) == (0.0, 0.0)

    def test_degenerate_spline_returns_start(self):
        r = EdgeRoute(points=[(5.0, 5.0), (5.0, 5.0)],
                      spline_type="polyline")
        le = _FakeEdge(r)
        # Start == end → degenerate; returns the start point.
        assert edge_midpoint(None, le) == (5.0, 5.0)

    def test_polyline_midpoint(self):
        r = EdgeRoute(points=[(0.0, 0.0), (10.0, 0.0)],
                      spline_type="polyline")
        le = _FakeEdge(r)
        assert edge_midpoint(None, le) == (5.0, 0.0)


# ═══════════════════════════════════════════════════════════════
#  getsplinepoints — integration with a real layout
# ═══════════════════════════════════════════════════════════════

class TestGetSplinePoints:

    def test_real_edge_returns_own_route(self):
        from gvpy.grammar.gv_reader import read_dot
        from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
        g = read_dot("digraph { a -> b }")
        layout = DotGraphInfo(g)
        layout.layout()
        le = next(e for e in layout.ledges
                  if e.tail_name == "a" and e.head_name == "b"
                  and not e.virtual)
        assert le.route.points
        assert getsplinepoints(layout, le) is le.route

    def test_no_spline_returns_none(self):
        from gvpy.engines.layout.dot.dot_layout import DotGraphInfo, LayoutEdge
        from gvpy.grammar.gv_reader import read_dot
        g = read_dot("digraph { a -> b }")
        layout = DotGraphInfo(g)
        layout.layout()
        # Synthetic edge with no points and no orig_* links: returns None.
        real = next(e for e in layout.ledges if not e.virtual)
        stub = LayoutEdge(tail_name="x", head_name="y", edge=real.edge)
        assert getsplinepoints(layout, stub) is None


# ═══════════════════════════════════════════════════════════════
#  F+.2 — place_portlabel, make_port_labels, place_vnlabel
# ═══════════════════════════════════════════════════════════════

class _FakeEdgeObj:
    def __init__(self, attrs=None):
        self.attributes = dict(attrs or {})


def _edge_with(route_pts, attrs, spline_type="polyline"):
    from gvpy.engines.layout.dot.dot_layout import LayoutEdge
    le = LayoutEdge(tail_name="t", head_name="h", edge=_FakeEdgeObj(attrs))
    le.route = EdgeRoute(points=list(route_pts), spline_type=spline_type)
    return le


class TestPlacePortLabel:

    def test_gate_returns_false_without_angle_or_distance(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)], {"headlabel": "H"})
        assert place_portlabel(None, le, head_p=True) is False
        # No attributes written.
        assert "_headlabel_pos_x" not in le.edge.attributes

    def test_labeldistance_alone_enables_placement(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)],
                        {"headlabel": "H", "labeldistance": "2"})
        assert place_portlabel(None, le, head_p=True) is True
        x = float(le.edge.attributes["_headlabel_pos_x"])
        y = float(le.edge.attributes["_headlabel_pos_y"])
        # pe=(10,0), pf=pts[-2]=(0,0) → tangent points inward (π).
        # Default labelangle = -25°; dist = 10 * 2 = 20.
        angle = math.pi + math.radians(PORT_LABEL_ANGLE)
        expected_x = 10.0 + 20.0 * math.cos(angle)
        expected_y = 0.0 + 20.0 * math.sin(angle)
        assert x == pytest.approx(expected_x, abs=0.01)
        assert y == pytest.approx(expected_y, abs=0.01)

    def test_labelangle_zero_no_offset(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)],
                        {"taillabel": "T", "labelangle": "0",
                         "labeldistance": "1"})
        assert place_portlabel(None, le, head_p=False) is True
        x = float(le.edge.attributes["_taillabel_pos_x"])
        y = float(le.edge.attributes["_taillabel_pos_y"])
        # pe=(0,0), pf=pts[1]=(10,0) → tangent +x.  labelangle 0, dist 10.
        assert x == pytest.approx(10.0, abs=0.01)
        assert y == pytest.approx(0.0, abs=0.01)

    def test_missing_label_returns_false(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)], {"labelangle": "0"})
        # No headlabel attr → skipped.
        assert place_portlabel(None, le, head_p=True) is False

    def test_labelangle_90_is_perpendicular(self):
        # pe=(10,0), pf=(0,0) → tangent π.  labelangle +90° → angle 270°.
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)],
                        {"headlabel": "H", "labelangle": "90",
                         "labeldistance": "1"})
        assert place_portlabel(None, le, head_p=True) is True
        x = float(le.edge.attributes["_headlabel_pos_x"])
        y = float(le.edge.attributes["_headlabel_pos_y"])
        # cos(270°)=0, sin(270°)=-1 → offset (0, -10) from (10, 0).
        assert x == pytest.approx(10.0, abs=0.01)
        assert y == pytest.approx(-10.0, abs=0.01)


class TestMakePortLabels:

    def test_no_gate_early_return(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)],
                        {"headlabel": "H", "taillabel": "T"})
        make_port_labels(None, le)
        assert "_headlabel_pos_x" not in le.edge.attributes
        assert "_taillabel_pos_x" not in le.edge.attributes

    def test_places_both_when_gated(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)],
                        {"headlabel": "H", "taillabel": "T",
                         "labelangle": "0", "labeldistance": "1"})
        make_port_labels(None, le)
        assert "_headlabel_pos_x" in le.edge.attributes
        assert "_taillabel_pos_x" in le.edge.attributes


class TestAddEdgeLabels:

    def test_delegates_to_make_port_labels(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)],
                        {"headlabel": "H", "labelangle": "0",
                         "labeldistance": "1"})
        add_edge_labels(None, le)
        assert "_headlabel_pos_x" in le.edge.attributes


class TestPlaceVnLabel:

    def test_sets_label_pos_at_polyline_midpoint(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)], {})
        le.label = "hi"
        place_vnlabel(None, le)
        assert le.label_pos == (5.0, 0.0)

    def test_no_label_skips(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)], {})
        le.label = ""
        place_vnlabel(None, le)
        # Default was (), not mutated.
        assert le.label_pos == ()

    def test_labelangle_distance_on_main_label(self):
        le = _edge_with([(0.0, 0.0), (10.0, 0.0)],
                        {"labelangle": "90", "labeldistance": "1"})
        le.label = "hi"
        place_vnlabel(None, le)
        # Midpoint (5,0); angle 90°, dist = 1 * 14 = 14 (legacy scale).
        assert le.label_pos == (pytest.approx(5.0, abs=0.01),
                                 pytest.approx(14.0, abs=0.01))
