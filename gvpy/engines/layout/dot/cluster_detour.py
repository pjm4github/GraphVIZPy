"""Post-hoc bezier reshape for non-member cluster avoidance (D4 fix).

The spline corridor built by :mod:`regular_edge` is constructed from
per-node ``maximal_bbox`` rectangles that already respect cluster
walls on each rank.  But for edges between adjacent ranks whose
endpoints sit on **opposite sides** of a non-member cluster, the
interrank ``rank_box`` spans the full graph width and leaves no room
to steer the spline around the cluster — ``routesplines`` produces a
direct cubic whose control points can land deep inside the cluster
bbox even though both anchors are cleanly outside it.

The canonical C fix for this lives in dot's mincross / position
phases (divergences D5 / D6 in ``TODO.md``): C keeps same-cluster
nodes tightly grouped so the "straddle" geometry never arises.  We
don't yet match that behaviour, so ship a splines-level guard as
divergence D4's interim cover:

1. Sample the spline output from :func:`routesplines` /
   :func:`routepolylines`.
2. If any sample lands inside a non-member cluster bbox, insert a
   detour "via" point on the closest outside edge of the cluster,
   rebuild the polyline, and re-fit with Schneider's
   :func:`common.splines.to_bezier`.
3. Iterate capped at :data:`_MAX_ITERATIONS` to handle edges that
   need multiple detours (observed on 2796.dot where a single edge
   skewers six clusters).

The reshape is advisory — if it can't eliminate a crossing in the
cap, it returns its best effort and logs one trace line.  The
routing is monotonically better than the pre-patch behaviour:
sampling is the same geometry the crossings counter uses, so any
fix measured there is also a win for the :mod:`tools.visual_audit`
baseline.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from gvpy.engines.layout.common.geom import Ppolyline
from gvpy.engines.layout.common.splines import make_polyline, to_bezier
from gvpy.engines.layout.pathplan import Ppoint

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import DotGraphInfo, LayoutEdge


# Tuning knobs — small enough to keep runtime negligible on the full
# corpus (re-fitting a 3-anchor polyline is cheap), large enough to
# cover the worst observed case (2796.dot: 6 clusters crossed by a
# single edge).
_MAX_ITERATIONS = 8
_SAMPLES_PER_SEG = 16
_DETOUR_MARGIN = 6.0  # points; roughly 1.5 × typical splinesep


def reshape_around_clusters(
    ps: list[Ppoint],
    le: "LayoutEdge",
    layout: "DotGraphInfo",
) -> list[Ppoint]:
    """Return a bezier control-point list that avoids non-member clusters.

    Input ``ps`` is Graphviz's cubic-Bezier format
    ``[P0, C1, C2, P1, C3, C4, P2, ...]`` as emitted by
    :func:`routesplines`.  Length is ``1 + 3*segments``.  The anchors
    are at indices ``0, 3, 6, ...``; control points are the pairs
    between them.

    When the edge doesn't cross any non-member cluster, ``ps`` is
    returned unchanged.  Otherwise the anchor polyline is extended
    with detour waypoints and re-fitted to a (longer) bezier chain.
    """
    if len(ps) < 4:
        return ps

    clusters = getattr(layout, "_clusters", None) or []
    if not clusters:
        return ps

    member_names = _member_cluster_names(le, clusters)
    offenders = [cl for cl in clusters
                 if cl.bb and cl.name not in member_names]
    if not offenders:
        return ps

    # Start from the anchor polyline extracted from the bezier.
    poly: list[tuple[float, float]] = _anchors(ps)

    for _ in range(_MAX_ITERATIONS):
        crossing = _find_first_crossing(poly, offenders)
        if crossing is None:
            break
        seg_idx, cl_bb = crossing
        vias = _pick_detour_waypoints(poly[seg_idx],
                                      poly[seg_idx + 1],
                                      cl_bb, offenders)
        if not vias:
            # No good detour — skip this crossing; otherwise we'd loop.
            break
        poly = poly[: seg_idx + 1] + list(vias) + poly[seg_idx + 1:]

    if len(poly) <= len(_anchors(ps)):
        # Never inserted a via-point — return original spline.
        return ps

    # Convert the detoured polyline to the bezier control-point format
    # using :func:`make_polyline` (zero-tangent controls → straight
    # segments between anchors).  ``to_bezier``'s Schneider fit
    # smooths the corners, which re-introduces cluster bulges on the
    # very crossings we just steered around; the sharp polyline form
    # keeps the detour guarantee.  Visual trade-off: detoured edges
    # render as right-angle polylines rather than smooth curves.
    poly_pts = [Ppoint(x, y) for (x, y) in poly]
    poly_obj = Ppolyline(ps=poly_pts)
    ispline = make_polyline(poly_obj)
    return list(ispline.ps)


# --- member clusters ---------------------------------------------------


def _member_cluster_names(le: "LayoutEdge", clusters) -> set[str]:
    """Cluster names containing either endpoint.  Matches
    :func:`dotsplines._ortho_member_clusters` semantics.
    """
    members: set[str] = set()
    tail, head = le.tail_name, le.head_name
    for cl in clusters:
        nset = cl.nodes  # already a list; ``in`` is fine
        if tail in nset or head in nset:
            members.add(cl.name)
    return members


# --- anchor extraction + bezier sampling ------------------------------


def _anchors(ps: list[Ppoint]) -> list[tuple[float, float]]:
    """Anchor points of a cubic-Bezier control list.

    For ``[P0, C1, C2, P1, C3, C4, P2, ...]`` this returns
    ``[P0, P1, P2, ...]`` — the polyline through segment endpoints.
    """
    out: list[tuple[float, float]] = []
    i = 0
    while i < len(ps):
        p = ps[i]
        out.append((p.x, p.y))
        i += 3
    # If the list didn't land exactly on a 3-step boundary, pick up the tail.
    last = ps[-1]
    if out[-1] != (last.x, last.y):
        out.append((last.x, last.y))
    return out


def _sample_segment(p0, c1, c2, p3, n: int = _SAMPLES_PER_SEG):
    """Sample a cubic bezier at ``n`` evenly spaced t values, skipping
    the endpoints (which are always "outside" by construction of the
    routing corridor — sampling them would miss the bulge).
    """
    pts: list[tuple[float, float]] = []
    for k in range(1, n):
        t = k / n
        s = 1.0 - t
        x = (s*s*s*p0[0] + 3*s*s*t*c1[0]
             + 3*s*t*t*c2[0] + t*t*t*p3[0])
        y = (s*s*s*p0[1] + 3*s*s*t*c1[1]
             + 3*s*t*t*c2[1] + t*t*t*p3[1])
        pts.append((x, y))
    return pts


# --- crossing detection ------------------------------------------------


def _find_first_crossing(poly, offenders):
    """Iterate segments of the anchor polyline, build a cubic bezier
    per segment (linear-interp control points, matches ``to_bezier``'s
    n==2 path), sample it, and return the (segment_idx, cluster_bb)
    of the first cluster pierced.

    Returns ``None`` if no crossing is detected.
    """
    for i in range(len(poly) - 1):
        p0 = poly[i]
        p3 = poly[i + 1]
        # Controls at 1/3 and 2/3 along the segment — matches
        # to_bezier's straight-line default for n==2.
        dx, dy = p3[0] - p0[0], p3[1] - p0[1]
        c1 = (p0[0] + dx / 3.0, p0[1] + dy / 3.0)
        c2 = (p0[0] + 2 * dx / 3.0, p0[1] + 2 * dy / 3.0)
        samples = _sample_segment(p0, c1, c2, p3)
        for cl in offenders:
            bb = cl.bb
            for (sx, sy) in samples:
                if bb[0] < sx < bb[2] and bb[1] < sy < bb[3]:
                    return (i, bb)
    return None


# --- detour selection --------------------------------------------------


def _pick_detour_waypoints(p_prev, p_next, cl_bb, offenders):
    """Return a list of waypoints to insert between ``p_prev`` and
    ``p_next`` so the polyline threads around ``cl_bb`` rather than
    through it.

    Strategy: try, in increasing order of detour cost, either a
    single midline via-point or a U-shape with two waypoints
    (aligned with each anchor's perpendicular).  A candidate is
    accepted only if every new segment clears ``cl_bb`` **and**
    every other already-known offender cluster.

    Returns an empty tuple when no candidate is valid — the caller
    then bails out of the iterative loop for this crossing.
    """
    x1, y1, x2, y2 = cl_bb
    mx = (p_prev[0] + p_next[0]) / 2.0
    my = (p_prev[1] + p_next[1]) / 2.0

    # Four "side" candidates: each encodes both the single-via form
    # (useful when anchors are already outside the cluster's
    # perpendicular range) and the U-shape fallback (needed when
    # anchors straddle the cluster through its interior).
    single_candidates: list[tuple[float, tuple]] = []
    ushape_candidates: list[tuple[float, tuple]] = []

    # For each side, ``line_coord`` is the outward-offset axis value;
    # ``axis`` picks which coordinate to pin for the U-shape corners.
    sides = [
        # (side_name, via_mid, u_corner_a, u_corner_b)
        ("top", (mx, y1 - _DETOUR_MARGIN),
         (p_prev[0], y1 - _DETOUR_MARGIN),
         (p_next[0], y1 - _DETOUR_MARGIN)),
        ("bot", (mx, y2 + _DETOUR_MARGIN),
         (p_prev[0], y2 + _DETOUR_MARGIN),
         (p_next[0], y2 + _DETOUR_MARGIN)),
        ("left", (x1 - _DETOUR_MARGIN, my),
         (x1 - _DETOUR_MARGIN, p_prev[1]),
         (x1 - _DETOUR_MARGIN, p_next[1])),
        ("right", (x2 + _DETOUR_MARGIN, my),
         (x2 + _DETOUR_MARGIN, p_prev[1]),
         (x2 + _DETOUR_MARGIN, p_next[1])),
    ]

    # Tier 1: strict — new segments must clear every known offender
    # cluster, not just the one we're detouring.  Prevents oscillation
    # where a detour for A lands in B and the next iteration detours
    # for B back into A.
    for _, via_mid, u_a, u_b in sides:
        if (_segment_clears_all(p_prev, via_mid, cl_bb, offenders)
                and _segment_clears_all(via_mid, p_next, cl_bb, offenders)):
            cost = _detour_cost(p_prev, via_mid, p_next)
            single_candidates.append((cost, (via_mid,)))

        if (_segment_clears_all(p_prev, u_a, cl_bb, offenders)
                and _segment_clears_all(u_a, u_b, cl_bb, offenders)
                and _segment_clears_all(u_b, p_next, cl_bb, offenders)):
            cost = (_dist(p_prev, u_a) + _dist(u_a, u_b)
                    + _dist(u_b, p_next) - _dist(p_prev, p_next))
            ushape_candidates.append((cost, (u_a, u_b)))

    if single_candidates:
        single_candidates.sort(key=lambda kv: kv[0])
        return single_candidates[0][1]
    if ushape_candidates:
        ushape_candidates.sort(key=lambda kv: kv[0])
        return ushape_candidates[0][1]

    # Tier 2: permissive — only check the primary cluster.  Accepts
    # detours that create a new crossing elsewhere; the iterative
    # caller will detour that too.  Bounded by ``_MAX_ITERATIONS``.
    for _, via_mid, u_a, u_b in sides:
        if (_segment_clears(p_prev, via_mid, cl_bb)
                and _segment_clears(via_mid, p_next, cl_bb)):
            cost = _detour_cost(p_prev, via_mid, p_next)
            single_candidates.append((cost, (via_mid,)))

        if (_segment_clears(p_prev, u_a, cl_bb)
                and _segment_clears(u_a, u_b, cl_bb)
                and _segment_clears(u_b, p_next, cl_bb)):
            cost = (_dist(p_prev, u_a) + _dist(u_a, u_b)
                    + _dist(u_b, p_next) - _dist(p_prev, p_next))
            ushape_candidates.append((cost, (u_a, u_b)))

    if single_candidates:
        single_candidates.sort(key=lambda kv: kv[0])
        return single_candidates[0][1]
    if ushape_candidates:
        ushape_candidates.sort(key=lambda kv: kv[0])
        return ushape_candidates[0][1]

    print(
        f"[TRACE d4-reshape] no clean detour around "
        f"bb=({x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f}) "
        f"for anchors {p_prev} -> {p_next}",
        file=sys.stderr,
    )
    return ()


def _dist(a, b) -> float:
    import math as _m
    return _m.hypot(b[0] - a[0], b[1] - a[1])


def _segment_clears_all(a, b, primary_bb, offenders) -> bool:
    """Segment ``a → b`` must clear ``primary_bb`` (the cluster we're
    detouring) AND every other non-member cluster.  Prevents a
    "fix one crossing, create another" ping-pong on corridor-heavy
    graphs like 2796.dot.
    """
    if not _segment_clears(a, b, primary_bb):
        return False
    for cl in offenders:
        bb = cl.bb
        if bb is primary_bb:
            continue
        if not _segment_clears(a, b, bb):
            return False
    return True


def _detour_cost(a, v, b) -> float:
    """Path length of ``a → v → b`` minus direct distance ``a → b``.

    Zero would mean no detour (colinear).  Larger means costlier.
    """
    import math as _m
    direct = _m.hypot(b[0] - a[0], b[1] - a[1])
    detoured = (_m.hypot(v[0] - a[0], v[1] - a[1])
                + _m.hypot(b[0] - v[0], b[1] - v[1]))
    return detoured - direct


def _segment_clears(a, b, bb) -> bool:
    """True iff the straight segment ``a → b`` doesn't enter ``bb``.

    Uses sampling — same approach as :func:`_find_first_crossing` but
    for a linear segment.  Samples excluding the endpoints (they are
    the two candidate via-point neighbours, already expected to sit
    outside ``bb``).
    """
    x1, y1, x2, y2 = bb
    for k in range(1, _SAMPLES_PER_SEG):
        t = k / _SAMPLES_PER_SEG
        sx = a[0] + t * (b[0] - a[0])
        sy = a[1] + t * (b[1] - a[1])
        if x1 < sx < x2 and y1 < sy < y2:
            return False
    return True
