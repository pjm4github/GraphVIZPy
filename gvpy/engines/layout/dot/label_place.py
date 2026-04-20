"""Label placement for edges.

See: /lib/common/splines.c @ 1205

F+ bucket of the splines port.  Replaces the heuristic
``compute_label_pos`` in ``dotsplines.py`` with a C-matching
implementation.

F+.1 (this commit) ports the spline geometry primitives:
:func:`end_points`, :func:`getsplinepoints`, :func:`polyline_midpoint`,
and :func:`edge_midpoint`.  They are the foundation F+.2 builds on.

F+.2 (this commit) adds the label-positioning functions
(:func:`place_portlabel`, :func:`make_port_labels`,
:func:`add_edge_labels`, :func:`place_vnlabel`) and rewires
``splines.compute_label_pos`` to delegate to
:func:`place_vnlabel`.

Representation note
-------------------
Python's :class:`EdgeRoute` holds a single bezier — the C ``splines``
list always has exactly one element here (see ``edge_route.py``).
For ``spline_type == "bezier"`` the point list follows Graphviz's
cubic convention ``[P0, C1, C2, P1, C3, C4, P2, ...]`` and segment
stride is 3.  For ``spline_type == "polyline"`` the list is
anchor-only and segment stride is 1.  The segment iterators below
pick the stride from ``spline_type``.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import LayoutEdge
    from gvpy.engines.layout.dot.edge_route import EdgeRoute


MILLIPOINT = 0.001


def end_points(route: "EdgeRoute") -> tuple[tuple[float, float],
                                              tuple[float, float]]:
    """Extract the actual spline endpoints.

    See: /lib/common/splines.c @ 1223

    Returns ``(p, q)`` where ``p`` is the spline's start at the tail
    node and ``q`` is its end at the head node.  Uses the arrow-clip
    override (``route.sp`` / ``route.ep``) when the corresponding flag
    is set, otherwise falls back to the first / last control point.
    """
    pts = route.points
    if not pts:
        return (0.0, 0.0), (0.0, 0.0)
    p = tuple(route.sp) if route.sflag else (pts[0][0], pts[0][1])
    q = tuple(route.ep) if route.eflag else (pts[-1][0], pts[-1][1])
    return p, q


def getsplinepoints(layout, le: "LayoutEdge") -> "EdgeRoute | None":
    """Return the :class:`EdgeRoute` carrying this edge's spline.

    See: /lib/common/splines.c @ 1363

    C walks ``ED_to_orig`` until it finds an edge with ``ED_spl`` set
    or reaches the real edge.  Python stores splines directly on the
    real edge, so: if ``le`` already has points, return its route;
    otherwise resolve to the main edge via :func:`splines.getmainedge`
    and return that edge's route.  Returns ``None`` if no spline has
    been computed.
    """
    if le.route.points:
        return le.route
    from gvpy.engines.layout.dot.dotsplines import getmainedge
    main = getmainedge(layout, le)
    if main is not le and main.route.points:
        return main.route
    return None


def _segment_stride(route: "EdgeRoute") -> int:
    """Stride between consecutive polyline anchors in ``route.points``.

    ``"bezier"``-typed routes store ``[anchor, cp1, cp2, anchor, ...]``
    (stride 3).  ``"polyline"``-typed routes store anchors only
    (stride 1).
    """
    return 3 if route.spline_type == "bezier" else 1


def polyline_midpoint(route: "EdgeRoute") -> tuple[tuple[float, float],
                                                     tuple[float, float],
                                                     tuple[float, float]]:
    """Length-parametric midpoint of the spline treated as a polyline.

    See: /lib/common/splines.c @ 1247

    Thin adapter that picks the correct stride from ``route.spline_type``
    and delegates to :func:`common.splines.polyline_midpoint_raw`.
    """
    from gvpy.engines.layout.common.splines import polyline_midpoint_raw
    return polyline_midpoint_raw(route.points, _segment_stride(route))


def edge_midpoint(layout, le: "LayoutEdge") -> tuple[float, float]:
    """Midpoint of an edge's spline.

    See: /lib/common/splines.c @ 1283

    For a degenerate spline (start ≈ end) returns the start point.
    Otherwise delegates to :func:`polyline_midpoint`.

    The C version additionally uses ``dotneato_closest`` on the bezier
    control polygon for ``EDGETYPE_SPLINE`` / ``EDGETYPE_CURVED`` to
    find the point on the *curve* nearest the straight-line midpoint.
    That function is not yet ported; for Python we use the polyline
    midpoint for all edge types.  The approximation is exact for
    polylines and within ~1% for typical beziers.
    """
    if not le.route.points:
        return 0.0, 0.0
    p, q = end_points(le.route)
    if abs(p[0] - q[0]) < MILLIPOINT and abs(p[1] - q[1]) < MILLIPOINT:
        return p
    mid, _pp, _pq = polyline_midpoint(le.route)
    return mid


# ═══════════════════════════════════════════════════════════════
#  F+.2 — label positioning
# ═══════════════════════════════════════════════════════════════

# C ``lib/common/const.h`` — defaults/scales for port-label placement.
PORT_LABEL_ANGLE = -25.0     # degrees; positive is CCW
PORT_LABEL_DISTANCE = 10.0   # point scale for labeldistance multiplier


# Canonical implementation in :mod:`common.labels` as ``late_double``;
# the leading-underscore alias is preserved here for in-module use.
from gvpy.engines.layout.common.labels import late_double as _late_double  # noqa: F401


def _near_endpoint(route: "EdgeRoute", head_p: bool) -> tuple[
        tuple[float, float], tuple[float, float]]:
    """Return ``(pe, pf)``: endpoint at the node and the adjacent sample point.

    See: /lib/common/splines.c @ 1331

    ``pe`` is the point where
    the spline meets the node (arrow-clip overridden via sflag/eflag);
    ``pf`` is a short way "inward" along the spline, used to compute
    the tangent.  For cubic beziers without arrow clip, ``pf`` is
    sampled via de Casteljau at ``t=0.1`` (tail) or ``t=0.9`` (head).
    """
    # Lazy import to keep label_place.py's top-level cheap.
    from gvpy.engines.layout.dot.clip import bezier_point
    from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint

    pts = route.points
    stride = _segment_stride(route)

    if not head_p:
        if route.sflag:
            pe = tuple(route.sp)
            pf = (pts[0][0], pts[0][1])
        else:
            pe = (pts[0][0], pts[0][1])
            if stride == 3 and len(pts) >= 4:
                cv = [Ppoint(pts[i][0], pts[i][1]) for i in range(4)]
                sample = bezier_point(cv, 0.1)
                pf = (sample.x, sample.y)
            elif len(pts) >= 2:
                pf = (pts[1][0], pts[1][1])
            else:
                pf = pe
    else:
        if route.eflag:
            pe = tuple(route.ep)
            pf = (pts[-1][0], pts[-1][1])
        else:
            pe = (pts[-1][0], pts[-1][1])
            if stride == 3 and len(pts) >= 4:
                cv = [Ppoint(pts[-4 + i][0], pts[-4 + i][1]) for i in range(4)]
                sample = bezier_point(cv, 0.9)
                pf = (sample.x, sample.y)
            elif len(pts) >= 2:
                pf = (pts[-2][0], pts[-2][1])
            else:
                pf = pe
    return pe, pf


def place_portlabel(layout, le: "LayoutEdge", head_p: bool) -> bool:
    """Position a ``headlabel`` or ``taillabel`` by angle + distance.

    See: /lib/common/splines.c @ 1316

    Fires only if the edge has ``labelangle`` or ``labeldistance``
    explicitly set (matching C's early-return gate); otherwise returns
    ``False`` and the caller falls back to external label placement.

    The label position is ``pe + dist * (cos(θ), sin(θ))`` where ``θ``
    is the spline tangent at the endpoint plus ``labelangle``
    (degrees → radians, default −25°, min −180°) and ``dist`` is
    ``PORT_LABEL_DISTANCE * labeldistance`` (default multiplier 1.0,
    min 0.0).

    Writes ``_headlabel_pos_x`` / ``_headlabel_pos_y`` (or tail
    equivalents) on ``le.edge.attributes`` — same slots the SVG
    renderer already reads.
    """
    if le.edge is None:
        return False
    attrs = le.edge.attributes
    angle_str = attrs.get("labelangle", "")
    dist_str = attrs.get("labeldistance", "")
    if not angle_str and not dist_str:
        return False

    label_key = "headlabel" if head_p else "taillabel"
    if not attrs.get(label_key, ""):
        return False

    route = getsplinepoints(layout, le)
    if route is None or not route.points:
        return False

    pe, pf = _near_endpoint(route, head_p)
    labelangle_deg = _late_double(angle_str, PORT_LABEL_ANGLE, -180.0)
    labeldistance = _late_double(dist_str, 1.0, 0.0)

    angle = math.atan2(pf[1] - pe[1], pf[0] - pe[0]) \
          + math.radians(labelangle_deg)
    dist = PORT_LABEL_DISTANCE * labeldistance

    lx = pe[0] + dist * math.cos(angle)
    ly = pe[1] + dist * math.sin(angle)

    prefix = "_headlabel_pos" if head_p else "_taillabel_pos"
    attrs[f"{prefix}_x"] = str(round(lx, 2))
    attrs[f"{prefix}_y"] = str(round(ly, 2))
    return True


def make_port_labels(layout, le: "LayoutEdge") -> None:
    """Place both head and tail port labels.

    See: /lib/common/splines.c @ 1205

    Thin wrapper that short-circuits on missing labelangle *and*
    labeldistance, then calls :func:`place_portlabel` for the tail and
    then the head label.
    """
    if le.edge is None:
        return
    attrs = le.edge.attributes
    if not attrs.get("labelangle", "") and not attrs.get("labeldistance", ""):
        return
    place_portlabel(layout, le, head_p=False)
    place_portlabel(layout, le, head_p=True)


def add_edge_labels(layout, le: "LayoutEdge") -> None:
    """Apply all angle-based edge label placement.

    See: /lib/common/splines.c @ 1307

    Currently just a wrapper around :func:`make_port_labels`; the main
    edge label is placed by :func:`place_vnlabel` instead, called by
    the phase-4 driver.
    """
    make_port_labels(layout, le)


def place_vnlabel(layout, le: "LayoutEdge") -> None:
    """Position the main edge label.

    See: /lib/dotgen/dotsplines.c @ 508

    C picks the *one* label-bearing virtual node in the edge's chain
    and anchors the label at its coordinate with an ``x`` offset of
    ``dimen.x / 2`` (for non-HTML labels) or ``0`` (for HTML).  Python
    doesn't tag virtuals as label-bearing, so we use
    :func:`edge_midpoint` — the polyline midpoint of the real edge,
    which passes through the chain's middle virtual by construction.

    When the edge has ``labelangle`` / ``labeldistance`` set, those
    offsets are applied on top of the midpoint.  This is a
    Python-specific extension — C only applies angle/distance to port
    labels — kept for backward compatibility with the previous
    ``compute_label_pos`` heuristic.
    """
    if not le.label or not le.points:
        return
    if le.label_pos:
        # Already positioned — e.g. by E+.1 make_simple_flat_labels for
        # stacked adjacent flat edges, or an upstream caller.  Don't
        # clobber a deliberately-placed anchor.
        return

    mx, my = edge_midpoint(layout, le)

    if le.edge is not None:
        attrs = le.edge.attributes
        angle_str = attrs.get("labelangle", "")
        dist_str = attrs.get("labeldistance", "")
        if angle_str or dist_str:
            try:
                angle = math.radians(float(angle_str)) if angle_str else 0.0
            except ValueError:
                angle = 0.0
            try:
                # Existing heuristic used fontsize=14 as the scale.
                dist = float(dist_str) * 14.0 if dist_str else 0.0
            except ValueError:
                dist = 0.0
            mx += dist * math.cos(angle)
            my += dist * math.sin(angle)

    le.label_pos = (round(mx, 2), round(my, 2))
