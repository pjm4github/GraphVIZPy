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

from gvpy.engines.layout.pathplan import Ppoint

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import DotGraphInfo, LayoutEdge


# Tuning knobs — small enough to keep runtime negligible on the full
# corpus (re-fitting a 3-anchor polyline is cheap), large enough to
# cover the worst observed case (2796.dot: 6 clusters crossed by a
# single edge).
_MAX_ITERATIONS = 8
_SAMPLES_PER_SEG = 16

# Minimum corner-arc radius for detour polylines.  Graphviz's default
# rounded-rectangle node outline uses ``1/8 × min(width, height)`` —
# for 54×36 default box nodes that's 4.5 pt.  We pick 8 so detour
# corners are visibly more rounded than the node outline.  Per-corner
# radius is clamped to half the shorter adjacent segment in
# :func:`_compute_corner_arc` so adjacent arcs can never overlap.
_CORNER_RADIUS = 8.0

# Detour offset from the cluster wall.  Must be > 2×:data:`_CORNER_RADIUS`
# so the rounded arc stays outside the cluster: for a 90° corner with
# tangent distance ``t = _CORNER_RADIUS``, the arc's closest approach
# to the cluster is at ``margin - 2·_CORNER_RADIUS`` — we want that
# positive with headroom so floating-point wobble doesn't trip the
# sampler.  20 pt gives 4 pt clearance after rounding.
_DETOUR_MARGIN = 20.0

# Standard cubic-Bezier approximation of a quarter-circle arc.  The
# control points sit at ``k × r`` along the tangent direction from
# each endpoint; for a 90° arc ``k = 4·(√2 − 1)/3 ≈ 0.5523``.  The
# approximation stays within ~0.027 % of a true circle at radius r,
# which is imperceptible for typical graph rendering.
_ARC_K = 4.0 * (2.0 ** 0.5 - 1.0) / 3.0  # ≈ 0.5523


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

    # Convert the detoured polyline to a bezier control-point list
    # using rounded corners (see :func:`_make_rounded_bezier`).  The
    # alternative :func:`make_polyline` produces sharp right-angles
    # that look inconsistent with rounded-rect node outlines — pick
    # the arc radius so each corner reads as "more rounded than the
    # node".  :func:`to_bezier`'s Schneider fit is ruled out because
    # it re-smooths the corners and re-bulges into the very cluster
    # we just steered around.
    return _make_rounded_bezier(poly, _CORNER_RADIUS)


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


# --- rounded-corner bezier ---------------------------------------------


def _make_rounded_bezier(poly, radius: float) -> list[Ppoint]:
    """Convert a polyline to a cubic-bezier control-point list with
    rounded corners of the requested ``radius``.

    Each interior vertex is replaced by a cubic-bezier approximation
    of a circular arc tangent to both adjacent segments.  Straight
    segments connect the arc endpoints.  The effective radius at
    each corner is clamped to half the shorter adjacent segment so
    neighbouring arcs cannot overlap (otherwise the renderer would
    draw a malformed self-intersecting curve).

    The approximation uses :data:`_ARC_K` — the standard 4·(√2−1)/3
    cubic-bezier quarter-arc constant — which stays within ~0.03 %
    of a true circle for arcs up to 90°.  Detour corners are almost
    always right angles by construction, so the approximation is
    visually exact.
    """
    n = len(poly)
    if n == 0:
        return []
    if n == 1:
        p = poly[0]
        return [Ppoint(p[0], p[1])]
    if n == 2:
        return _straight_cubic(poly[0], poly[1])

    # Arc geometry for each interior vertex (may be None if degenerate).
    corner_data = [_compute_corner_arc(poly[i - 1], poly[i], poly[i + 1],
                                       radius)
                   for i in range(1, n - 1)]

    # Assemble the bezier control-point list.  We emit 1 starting
    # anchor plus 3 points per cubic segment; each corner contributes
    # 2 cubic segments (straight-to-arc + arc) and the very last
    # segment goes straight to ``poly[-1]``.
    result: list[tuple[float, float]] = [tuple(poly[0])]
    prev_end = poly[0]

    for i, cd in enumerate(corner_data):
        if cd is None:
            # Degenerate corner — skip the arc, go straight through.
            target = poly[i + 1]
            result.extend(_cubic_between(prev_end, target))
            prev_end = target
            continue
        a1, c1, c2, a2 = cd
        result.extend(_cubic_between(prev_end, a1))
        result.extend([c1, c2, a2])
        prev_end = a2

    # Final straight segment from the last arc end to the polyline's
    # terminal point.
    result.extend(_cubic_between(prev_end, poly[-1]))
    return [Ppoint(x, y) for (x, y) in result]


def _straight_cubic(a, b) -> list[Ppoint]:
    """Full bezier ``[a, C1, C2, b]`` for a straight cubic from
    ``a`` to ``b``."""
    out = [Ppoint(a[0], a[1])]
    out.extend(Ppoint(x, y) for (x, y) in _cubic_between(a, b))
    return out


def _cubic_between(a, b) -> list[tuple[float, float]]:
    """Return ``[C1, C2, b]`` — the non-starting control points for a
    straight cubic from ``a`` to ``b``.  Appended to a result list
    that already contains ``a``."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return [
        (a[0] + dx / 3.0, a[1] + dy / 3.0),
        (a[0] + 2.0 * dx / 3.0, a[1] + 2.0 * dy / 3.0),
        (b[0], b[1]),
    ]


def _compute_corner_arc(prev, corner, nxt, radius: float):
    """Return ``(a1, c1, c2, a2)`` — arc endpoints and cubic-bezier
    controls for rounding ``corner`` with the requested ``radius``.

    Returns ``None`` when the corner is degenerate: zero-length
    adjacent segment, colinear points (no turn), or a turn so sharp
    that the arc would collapse to a point.
    """
    import math as _m

    in_dx = corner[0] - prev[0]
    in_dy = corner[1] - prev[1]
    in_len = _m.hypot(in_dx, in_dy)
    if in_len < 1e-9:
        return None
    u_in = (in_dx / in_len, in_dy / in_len)

    out_dx = nxt[0] - corner[0]
    out_dy = nxt[1] - corner[1]
    out_len = _m.hypot(out_dx, out_dy)
    if out_len < 1e-9:
        return None
    u_out = (out_dx / out_len, out_dy / out_len)

    # Turn angle: 0 = straight, π = full reverse.
    cos_psi = u_in[0] * u_out[0] + u_in[1] * u_out[1]
    cos_psi = max(-1.0, min(1.0, cos_psi))
    psi = _m.acos(cos_psi)
    if psi < 1e-6:
        return None  # essentially colinear

    tan_half = _m.tan(psi / 2.0)
    if tan_half < 1e-6:
        return None

    # Tangent distance t: arc tangent meets the leg at this distance
    # from the corner.  Clamp so adjacent arcs don't overlap.
    max_t = 0.5 * min(in_len, out_len)
    t = min(radius * tan_half, max_t)
    if t < 1e-6:
        return None

    a1 = (corner[0] - t * u_in[0], corner[1] - t * u_in[1])
    a2 = (corner[0] + t * u_out[0], corner[1] + t * u_out[1])
    # Cubic bezier approximation of the arc: control points offset
    # ``_ARC_K × t`` along the in/out tangents from each arc endpoint.
    c1 = (a1[0] + _ARC_K * t * u_in[0],
          a1[1] + _ARC_K * t * u_in[1])
    c2 = (a2[0] - _ARC_K * t * u_out[0],
          a2[1] - _ARC_K * t * u_out[1])
    return (a1, c1, c2, a2)


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
