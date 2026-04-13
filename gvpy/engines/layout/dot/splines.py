"""Phase 4: spline routing / edge routing.

C analogue: ``lib/dotgen/dotsplines.c`` + ``lib/common/splines.c``.
Implements the edge-routing step that follows Phase 3 (position
assignment).  Given node coordinates and rank structure, compute
spline (or orthogonal, polyline, straight-line) routes for each
edge between its endpoints, clipping to node boundaries and
avoiding rank obstacles where applicable.

Responsibilities
----------------
- **Regular edges** routed via ``route_regular_edge`` using
  obstacle-aware polyline segments, then optionally converted to
  Bezier control points via ``to_bezier``.
- **Chain edges** (long edges that span multiple ranks via virtual
  nodes) routed via ``route_through_chain``.
- **Flat edges** (same-rank edges) routed via ``flat_edge_route``
  which dispatches to one of ``flat_adjacent``, ``flat_labeled``,
  or ``flat_arc`` depending on edge classification.
- **Self-loops** routed via ``self_loop_points`` with a small arc.
- **Compound edges** (``lhead``/``ltail``) clipped to target cluster
  bounding boxes via ``clip_compound_edges``.
- **Samehead/sametail** merging via ``apply_sameport`` which points
  grouped edges at a shared port.
- **Splines mode** (``spline``/``curved``/``ortho``/``polyline``/
  ``line``) determines the final representation.

Extracted functions
-------------------
All 23 Phase 4 methods moved from ``DotGraphInfo`` in ``dot_layout.py``
as free functions taking ``layout`` as the first argument:

- :func:`phase4_routing`       — entry point (``_phase4_routing``)
- :func:`clip_compound_edges`  — lhead/ltail clipping
- :func:`clip_to_bb`           — line-segment-to-bbox clip (static)
- :func:`to_bezier`            — polyline → cubic Bezier conversion
- :func:`edge_start_point`     — tail-side boundary/port point
- :func:`edge_end_point`       — head-side boundary/port point
- :func:`record_port_point`    — record port coordinate lookup
- :func:`port_point`           — compass port lookup (static)
- :func:`compute_label_pos`    — edge label anchor
- :func:`apply_sameport`       — samehead/sametail endpoint merge
- :func:`ortho_route`          — orthogonal routing
- :func:`route_through_chain`  — virtual-node-chain polyline
- :func:`boundary_point`       — line-to-node boundary clip
- :func:`self_loop_points`     — small arc for self-loops
- :func:`maximal_bbox`         — obstacle avoidance bbox helper
- :func:`rank_box`             — rank bounding box helper
- :func:`route_regular_edge`   — generic polyline router
- :func:`classify_flat_edge`   — flat edge classifier (adjacent/
                                  labeled/arc)
- :func:`count_flat_edge_index`— per-node flat edge index for offset
- :func:`flat_edge_route`      — dispatch for flat edges
- :func:`flat_adjacent`        — short flat edge between neighbours
- :func:`flat_labeled`         — flat edge with label anchor
- :func:`flat_arc`             — long flat arc

Each ``DotGraphInfo._xxx`` method is now a 3-line delegating wrapper.

Related modules
---------------
- :mod:`gvpy.engines.layout.dot.mincross` — Phase 2.  Assigns rank orders.
- :mod:`gvpy.engines.layout.dot.position` — Phase 3.  Assigns node coords.
- :mod:`gvpy.engines.layout.dot.dot_layout` — holds ``DotGraphInfo`` (state
  container) plus Phase 1 rank assignment, cluster geometry helpers,
  and write-back.  Splines functions here take ``layout: DotGraphInfo``
  as the first argument and read ``layout.lnodes``, ``layout.ledges``,
  ``layout._clusters``, ``layout.splines``, ``layout._chain_edges``,
  ``layout._vnode_chains``, etc.
"""
from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import DotGraphInfo, LayoutEdge, LayoutNode


def phase4_routing(layout):
    """phase4_routing.

    C analogue: lib/dotgen/dotsplines.c:dot_splines() — the top-level
    edge routing driver.  Pre-computes per-rank obstacle bounds, then
    dispatches each edge to the appropriate router (regular polyline /
    chain / flat / self-loop / ortho), merges samehead/sametail ports,
    clips compound edges, and optionally converts polylines to Bezier
    control points.
    """
    print(f"[TRACE spline] phase4 begin: splines={layout.splines} compound={layout.compound}", file=sys.stderr)
    # Pre-compute rank bounding info for obstacle-aware routing.
    # ``_rank_ht1`` / ``_rank_ht2`` are declared on DotGraphInfo so
    # PyCharm and mypy see them as proper instance attributes;
    # clear here to reset any state from a previous layout call.
    layout._rank_ht1.clear()
    layout._rank_ht2.clear()
    for ln in layout.lnodes.values():
        r = ln.rank
        hh = ln.height / 2.0
        layout._rank_ht1[r] = max(layout._rank_ht1.get(r, 0), hh)
        layout._rank_ht2[r] = max(layout._rank_ht2.get(r, 0), hh)

    # Compute graph-wide left/right bounds with padding
    if layout.lnodes:
        all_x = [ln.x for ln in layout.lnodes.values()]
        all_hw = [ln.width / 2 for ln in layout.lnodes.values()]
        layout._left_bound = min(x - w for x, w in zip(all_x, all_hw)) - 16
        layout._right_bound = max(x + w for x, w in zip(all_x, all_hw)) + 16
    else:
        layout._left_bound = -16
        layout._right_bound = 16

    use_channel = getattr(layout, "_use_channel_routing", False)

    # Route regular (non-virtual, non-chain) edges
    for le in layout.ledges:
        if le.virtual:
            continue
        tail = layout.lnodes.get(le.tail_name)
        head = layout.lnodes.get(le.head_name)
        if tail is None or head is None:
            continue
        if le.tail_name == le.head_name:
            le.points = layout._self_loop_points(tail)
        elif tail.rank == head.rank and not le.virtual:
            le.points = layout._flat_edge_route(le, tail, head)
        elif layout.splines == "ortho":
            le.points = layout._ortho_route(le, tail, head)
        elif layout.splines == "line":
            p1 = layout._edge_start_point(le, tail, head)
            p2 = layout._edge_end_point(le, head, tail)
            le.points = [p1, p2]
        elif use_channel:
            # New cluster-aware channel router (step 6 of the
            # routespl.c port).  Builds per-node channel boxes
            # clipped to foreign-cluster boundaries, then routes
            # a polyline through the boxes with bridge waypoints
            # around any intervening obstacle clusters.
            le.points = channel_route_edge(layout, le, tail, head)
        else:
            le.points = layout._route_regular_edge(le, tail, head)
        layout._compute_label_pos(le)

    # Route chain edges through virtual nodes
    for le in layout._chain_edges:
        tail = layout.lnodes.get(le.tail_name)
        head = layout.lnodes.get(le.head_name)
        if layout.splines == "line" and tail and head:
            # Line mode: direct start-to-end, ignore virtual nodes
            p1 = layout._edge_start_point(le, tail, head)
            p2 = layout._edge_end_point(le, head, tail)
            le.points = [p1, p2]
        elif layout.splines == "ortho" and tail and head:
            le.points = layout._ortho_route(le, tail, head)
        elif use_channel and tail and head:
            # New channel router for multi-rank chain edges too.
            le.points = channel_route_edge(layout, le, tail, head)
        else:
            key = (le.tail_name, le.head_name)
            chain = layout._vnode_chains.get(key, [])
            le.points = layout._route_through_chain(le.tail_name, chain, le.head_name)
        layout._compute_label_pos(le)

    # Apply samehead/sametail: merge endpoints for grouped edges
    layout._apply_sameport()

    # Compound edge clipping: clip to cluster bounding boxes
    if layout.compound:
        layout._clip_compound_edges()

    # Convert to Bezier curves if splines mode requests it.
    # Skip edges already marked as bezier (e.g. from _flat_edge_route).
    use_bezier = layout.splines in ("", "spline", "curved", "true")
    if use_bezier:
        all_edges = [le for le in layout.ledges if not le.virtual] + layout._chain_edges
        for le in all_edges:
            if le.points and len(le.points) >= 2 and le.spline_type != "bezier":
                le.points = layout._to_bezier(le.points)
                le.spline_type = "bezier"

    # Parallel-edge separation: shift overlapping parallel edges
    # perpendicular to their axis so they do not draw over each other.
    _apply_parallel_offsets(layout)

    # Log edge routing results
    all_routed = [le for le in layout.ledges if not le.virtual] + layout._chain_edges
    for le in all_routed:
        if le.points:
            pts_str = " ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in le.points[:4])
            print(f"[TRACE spline] edge {le.tail_name}->{le.head_name}: npts={len(le.points)} type={le.spline_type} pts={pts_str}{'...' if len(le.points)>4 else ''}", file=sys.stderr)


def _apply_parallel_offsets(layout):
    """Offset overlapping parallel edges perpendicular to their axis.

    After routing, any two edges that share the same ``(tail, head)``
    node pair follow identical paths and therefore draw over each
    other.  This pass groups edges by that pair and shifts each
    edge's points by ``(i - (n - 1) / 2) * sep`` along the axis
    perpendicular to the straight tail→head direction, where ``i``
    is the edge's 0-based index in its group and ``n`` is the
    group size.

    Endpoints stay fixed so the shifted curves still touch the node
    boundaries for arrowhead attachment.  The offset magnitude at
    each interior point is tapered by ``sin(π · t)`` — zero at
    ``t = 0`` / ``t = 1`` and maximum at the midpoint — producing
    a symmetric bulge.  Because a Bezier curve is affine-invariant,
    applying the taper directly to the control-point list (which
    is what ``le.points`` stores after bezier conversion) produces
    the same curve translated by the sin-taper displacement field.

    The minimum routing separation is ``layout._CL_OFFSET`` (8pt by
    default) — the same gap the cluster-layout phase uses between a
    cluster's enclosure bbox and its enclosed nodes.  Matching these
    two separations keeps the visual "breathing room" consistent
    between inside-cluster layout and between-parallel-edge routing.
    """
    import math
    from collections import defaultdict

    groups: dict[tuple[str, str], list] = defaultdict(list)
    all_edges = [le for le in layout.ledges if not le.virtual] + list(layout._chain_edges)
    for le in all_edges:
        if not le.points or len(le.points) < 2:
            continue
        # Skip flat (same-rank) edges: flat_edge_route already has
        # its own fanning logic (adjacent-node straight line vs.
        # outer-arc variants per flat_edge_classify) and parallel
        # red/black variants are visually distinguished by colour
        # and port attributes rather than positional offset.  Adding
        # a sin-taper on top pushes straight directed flats into a
        # visible arc and breaks test_241_directed_edges_straight.
        tail_ln = layout.lnodes.get(le.tail_name)
        head_ln = layout.lnodes.get(le.head_name)
        if tail_ln is not None and head_ln is not None \
                and tail_ln.rank == head_ln.rank:
            continue
        groups[(le.tail_name, le.head_name)].append(le)

    sep = float(getattr(layout, "_CL_OFFSET", 8.0))

    for (tail_name, head_name), edges in groups.items():
        if len(edges) < 2 or tail_name == head_name:
            continue
        # Axis = straight line between the first edge's first and
        # last points.  For bridged polylines the endpoint anchors
        # are the node boundary exits; this still gives a sensible
        # "overall direction" vector.
        le0 = edges[0]
        p_start = le0.points[0]
        p_end = le0.points[-1]
        dx = p_end[0] - p_start[0]
        dy = p_end[1] - p_start[1]
        axis_len = math.hypot(dx, dy)
        if axis_len < 1e-9:
            continue
        # Perpendicular unit vector (rotate +90°).
        nx = -dy / axis_len
        ny = dx / axis_len
        n = len(edges)
        for idx, le in enumerate(edges):
            offset = (idx - (n - 1) / 2.0) * sep
            if offset == 0:
                continue
            ox = nx * offset
            oy = ny * offset
            m = len(le.points)
            if m < 2:
                continue
            # Bezier detection: ``[P0, C1, C2, P1, C3, C4, P2, ...]``
            # has length ``3k + 1`` with k cubic segments.  Anchors
            # sit at indices ``3k``; control ``C_{k,1}`` (index 3k+1)
            # shifts with anchor ``P_k`` and control ``C_{k,2}``
            # (index 3k+2) shifts with anchor ``P_{k+1}``.  Grouping
            # each control with its nearest anchor preserves the
            # tangent direction at every anchor, so the perpendicular
            # stubs at each end still produce a right-angle exit.
            is_bezier = (le.spline_type == "bezier"
                         and m >= 4 and (m - 1) % 3 == 0)
            if is_bezier:
                num_anchors = (m - 1) // 3 + 1
                denom = max(num_anchors - 1, 1)
                shifted: list[tuple[float, float]] = []
                for i, p in enumerate(le.points):
                    # Map point index to the anchor index whose
                    # offset governs this point.
                    anchor_idx = (i + 1) // 3
                    t = anchor_idx / denom
                    factor = math.sin(math.pi * t)
                    shifted.append((p[0] + ox * factor,
                                    p[1] + oy * factor))
                le.points = shifted
            else:
                # Raw polyline: per-point sin-taper.
                shifted = []
                for j, p in enumerate(le.points):
                    t = j / (m - 1)
                    factor = math.sin(math.pi * t)
                    shifted.append((p[0] + ox * factor,
                                    p[1] + oy * factor))
                le.points = shifted


def clip_compound_edges(layout):
    """Clip edges with lhead/ltail to their target cluster bounding box.
    C analogue: lib/dotgen/dotsplines.c compound edge handling. For each
    edge with lhead or ltail set, clip the route to the target cluster
    bounding box so the visible endpoint sits at the cluster boundary.
    """
    cluster_map = {cl.name: cl for cl in layout._clusters}
    all_edges = [le for le in layout.ledges if not le.virtual] + layout._chain_edges
    for le in all_edges:
        if not le.points or len(le.points) < 2:
            continue
        if le.ltail and le.ltail in cluster_map:
            cl = cluster_map[le.ltail]
            if len(le.points) >= 2:
                clipped = layout._clip_to_bb(le.points[0], le.points[1], cl.bb)
                if clipped:
                    le.points[0] = clipped
        if le.lhead and le.lhead in cluster_map:
            cl = cluster_map[le.lhead]
            if len(le.points) >= 2:
                clipped = layout._clip_to_bb(le.points[-1], le.points[-2], cl.bb)
                if clipped:
                    le.points[-1] = clipped


def clip_to_bb(inside: tuple, outside: tuple, bb: tuple) -> tuple | None:
    """Find intersection of line segment (outside->inside) with rectangle bb.

    bb = (min_x, min_y, max_x, max_y). Returns the intersection point,
    or None if no intersection found.
    
    C analogue: utility — line-segment to axis-aligned box clip. Used by
    :func: for cluster boundary intersection.
    """
    x1, y1 = outside
    x2, y2 = inside
    bx1, by1, bx2, by2 = bb
    dx, dy = x2 - x1, y2 - y1
    best_t = None
    # Check each of the 4 edges of the rectangle
    for edge_val, is_x in [(bx1, True), (bx2, True), (by1, False), (by2, False)]:
        if is_x:
            if abs(dx) < 1e-9:
                continue
            t = (edge_val - x1) / dx
            y_at_t = y1 + t * dy
            if 0 <= t <= 1 and by1 <= y_at_t <= by2:
                if best_t is None or t > best_t:
                    best_t = t
        else:
            if abs(dy) < 1e-9:
                continue
            t = (edge_val - y1) / dy
            x_at_t = x1 + t * dx
            if 0 <= t <= 1 and bx1 <= x_at_t <= bx2:
                if best_t is None or t > best_t:
                    best_t = t
    if best_t is not None:
        return (x1 + best_t * dx, y1 + best_t * dy)
    return None


def to_bezier(pts: list[tuple]) -> list[tuple]:
    """Convert a polyline to smooth cubic Bezier control points.

    Uses Schneider's recursive curve-fitting algorithm:
    1. Parameterize points by chord-length fraction.
    2. Estimate end tangents from neighboring points.
    3. Fit a cubic Bezier via least-squares tangent scaling.
    4. If max deviation > tolerance, split at worst point and recurse.

    Mirrors Graphviz ``routespl.c:mkspline()`` / ``reallyroutespline()``.

    Input:  [P0, P1, ..., Pn]  (polyline waypoints)
    Output: [P0, C1, C2, P1, C3, C4, P2, ...]  (cubic Bezier segments)
    """
    import math

    n = len(pts)
    if n <= 1:
        return list(pts)
    if n == 2:
        p0, p1 = pts
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        return [p0, (p0[0] + dx / 3, p0[1] + dy / 3),
                (p0[0] + 2 * dx / 3, p0[1] + 2 * dy / 3), p1]

    def _dist(a, b):
        return math.hypot(b[0] - a[0], b[1] - a[1])

    def _normalize(v):
        d = math.hypot(v[0], v[1])
        return (v[0] / d, v[1] / d) if d > 1e-9 else (0.0, 0.0)

    def _bezier_pt(p0, p1, p2, p3, t):
        s = 1 - t
        return (s*s*s*p0[0] + 3*s*s*t*p1[0] + 3*s*t*t*p2[0] + t*t*t*p3[0],
                s*s*s*p0[1] + 3*s*s*t*p1[1] + 3*s*t*t*p2[1] + t*t*t*p3[1])

    def _fit_cubic(points, t_params, ev0, ev1):
        """Schneider least-squares cubic fit with fixed tangent dirs."""
        p0 = points[0]
        p3 = points[-1]
        n = len(points)

        # Build normal equations for tangent scale factors
        c00 = c01 = c10 = c11 = 0.0
        x0 = x1 = 0.0
        for i in range(n):
            t = t_params[i]
            s = 1 - t
            b1 = 3 * s * s * t
            b2 = 3 * s * t * t
            a1 = (ev0[0] * b1, ev0[1] * b1)
            a2 = (ev1[0] * b2, ev1[1] * b2)
            c00 += a1[0]*a1[0] + a1[1]*a1[1]
            c01 += a1[0]*a2[0] + a1[1]*a2[1]
            c11 += a2[0]*a2[0] + a2[1]*a2[1]
            b0 = s*s*s
            b3 = t*t*t
            tmp = (points[i][0] - b0*p0[0] - b3*p3[0],
                   points[i][1] - b0*p0[1] - b3*p3[1])
            x0 += a1[0]*tmp[0] + a1[1]*tmp[1]
            x1 += a2[0]*tmp[0] + a2[1]*tmp[1]
        c10 = c01

        det = c00*c11 - c01*c10
        if abs(det) < 1e-12:
            d = _dist(p0, p3) / 3.0
            return (p0, (p0[0]+ev0[0]*d, p0[1]+ev0[1]*d),
                    (p3[0]+ev1[0]*d, p3[1]+ev1[1]*d), p3)

        alpha0 = (x0*c11 - x1*c01) / det
        alpha1 = (c00*x1 - c10*x0) / det

        # Sanity bounds.  ``alpha`` is the tangent-vector scale factor;
        # geometrically reasonable values are roughly chord/3 to a small
        # multiple of the chord length.  Below ``eps`` the system was
        # near-degenerate (recover with chord/3); above ``max_alpha``
        # the matrix was technically non-singular but ill-conditioned
        # enough that the solution extrapolates wildly off-canvas.
        # Both fall back to the chord/3 heuristic — matches Graphviz
        # routespl.c:mkspline() which clamps via the same path.
        d = _dist(p0, p3)
        eps = d * 1e-6
        max_alpha = 2.0 * d if d > 0 else 0.0
        if (alpha0 < eps or alpha1 < eps
                or alpha0 > max_alpha or alpha1 > max_alpha):
            alpha0 = alpha1 = d / 3.0

        return (p0,
                (p0[0]+ev0[0]*alpha0, p0[1]+ev0[1]*alpha0),
                (p3[0]+ev1[0]*alpha1, p3[1]+ev1[1]*alpha1),
                p3)

    def _max_error(points, t_params, bezier):
        """Return (max_dist, index_of_worst)."""
        worst_d = 0.0
        worst_i = 0
        for i in range(len(points)):
            bp = _bezier_pt(*bezier, t_params[i])
            d = _dist(points[i], bp)
            if d > worst_d:
                worst_d = d
                worst_i = i
        return worst_d, worst_i

    def _fit_recursive(points, ev0, ev1, depth=0):
        """Recursively fit cubics, splitting at worst-fit point."""
        n = len(points)
        if n <= 2:
            p0, p1 = points[0], points[-1]
            dx, dy = p1[0]-p0[0], p1[1]-p0[1]
            return [p0, (p0[0]+dx/3, p0[1]+dy/3),
                    (p0[0]+2*dx/3, p0[1]+2*dy/3), p1]
        if n == 3:
            # Only one interior sample point — the 2x2 normal-equations
            # system in _fit_cubic is underdetermined and can produce
            # wildly extrapolated alpha values when the basis vectors
            # become near-collinear.  Skip the least-squares fit and
            # use the standard chord/3 tangent-length heuristic
            # (matches Graphviz routespl.c:mkspline()'s short-polyline
            # fallback path).
            p0, p3 = points[0], points[-1]
            d = _dist(p0, p3) / 3.0
            return [p0,
                    (p0[0] + ev0[0]*d, p0[1] + ev0[1]*d),
                    (p3[0] + ev1[0]*d, p3[1] + ev1[1]*d),
                    p3]

        # Chord-length parameterization
        dists = [0.0]
        for i in range(1, n):
            dists.append(dists[-1] + _dist(points[i-1], points[i]))
        total = dists[-1]
        if total < 1e-9:
            return [points[0], points[0], points[-1], points[-1]]
        t_params = [d / total for d in dists]

        bezier = _fit_cubic(points, t_params, ev0, ev1)
        err, split_i = _max_error(points, t_params, bezier)

        tolerance = 4.0  # 4pt tolerance
        if err <= tolerance or depth > 8 or n <= 3:
            return list(bezier)

        # Split at worst point and recurse
        split_i = max(1, min(split_i, n - 2))
        sp = points[split_i]
        # Tangent at split point: direction between neighbors
        if split_i > 0 and split_i < n - 1:
            mid_tan = _normalize((points[split_i+1][0] - points[split_i-1][0],
                                  points[split_i+1][1] - points[split_i-1][1]))
        else:
            mid_tan = _normalize((points[-1][0] - points[0][0],
                                  points[-1][1] - points[0][1]))
        neg_tan = (-mid_tan[0], -mid_tan[1])

        left = _fit_recursive(points[:split_i+1], ev0, neg_tan, depth+1)
        right = _fit_recursive(points[split_i:], mid_tan, ev1, depth+1)
        return left + right[1:]  # skip duplicate split point

    # Estimate end tangents
    ev0 = _normalize((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
    ev1 = _normalize((pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1]))

    return _fit_recursive(list(pts), ev0, ev1)


def edge_start_point(layout, le: LayoutEdge, tail: LayoutNode,
                      head: LayoutNode) -> tuple[float, float]:
    """Get edge start point — uses tailport if set, else boundary intersection.
    C analogue: lib/common/splines.c:place_portbox() and shapes.c port
    resolution.  Returns the tail-side endpoint of an edge — either the
    explicit port position from the record fields or the boundary
    intersection if no port.
    """
    if le.tailport:
        # Check record port first, then compass
        pt = layout._record_port_point(le.tail_name, le.tailport, tail,
                                     is_tail=True)
        if pt is not None:
            return pt
        compass = le.tailport.split(":")[-1] if ":" in le.tailport else le.tailport
        pt = layout._port_point(tail, compass)
        if pt is not None:
            return pt
    if not le.tailclip:
        return (tail.x, tail.y)
    return layout._boundary_point(tail, head.x, head.y)


def edge_end_point(layout, le: LayoutEdge, head: LayoutNode,
                    tail: LayoutNode) -> tuple[float, float]:
    """Get edge end point — uses headport if set, else boundary intersection.
    C analogue: lib/common/splines.c:place_portbox() and shapes.c port
    resolution — head-side counterpart of :func:.
    """
    if le.headport:
        pt = layout._record_port_point(le.head_name, le.headport, head,
                                     is_tail=False)
        if pt is not None:
            return pt
        compass = le.headport.split(":")[-1] if ":" in le.headport else le.headport
        pt = layout._port_point(head, compass)
        if pt is not None:
            return pt
    if not le.headclip:
        return (head.x, head.y)
    return layout._boundary_point(head, tail.x, tail.y)


def record_port_point(layout, node_name: str, port: str,
                       ln: LayoutNode,
                       is_tail: bool = True) -> tuple[float, float] | None:
    """Get attachment point for a record port on the node boundary.

    For TB/BT mode the port fraction runs along the X axis (fields
    left-to-right) and the edge attaches at the top or bottom boundary.
    For LR/RL mode the port fraction runs along the Y axis (fields
    top-to-bottom) and the edge attaches at the left or right boundary.

    ``is_tail`` determines which boundary: tails attach at the
    bottom/right edge (toward the next rank), heads at the top/left.
    
    C analogue: lib/common/shapes.c:record_port() and compassPort().
    Looks up a record-shape port by name in the parsed
    Node.record_fields tree, returns the port center in node-local
    coordinates.
    """
    port_name = port.split(":")[0] if ":" in port else port
    ln_obj = layout.lnodes.get(node_name)
    if not ln_obj or not ln_obj.node or ln_obj.node.record_fields is None:
        return None
    rf = ln_obj.node.record_fields
    pp = rf.port_position(port_name)
    if pp is None:
        return None
    px_rec, py_rec = pp

    # Linear fraction along the record's cross-rank axis is what
    # determines where on the rank-facing face the edge attaches.  We
    # deliberately ignore ``port_fraction`` (an angle-based compass
    # order derived from C's compassPort — correct for mincross port
    # ordering but wrong for physical attach-point placement because
    # it returns 0 for dead-centre ports and collapses all of a
    # column's ports to the top of the node face).
    #
    # For an N-port vertical column in a 100pt-tall node, the user-
    # facing expectation is centres at ``10, 30, 50, 70, 90`` — i.e.
    # each port's centre sits at ``(i + 0.5) / N`` of the face range.
    # That mapping falls out naturally from
    # ``port_position.cr / record.cr_extent``: each field's local
    # centre is already at that fraction of its parent column.
    if layout.rankdir in ("LR", "RL"):
        # LR/RL: attach face is east (tail) or west (head), and the
        # cross-rank axis is the node's Y.  The record tree is in
        # the pre-rotation frame where the rank direction is still
        # record.x — so the port's "cross-rank fraction" is its
        # local Y divided by the record's Y extent.
        rec_extent = max(rf.height, 1e-9)
        frac = max(0.0, min(1.0, py_rec / rec_extent))
        y = ln.y - ln.height / 2.0 + frac * ln.height
        if is_tail:
            x = ln.x + ln.width / 2.0   # east face
        else:
            x = ln.x - ln.width / 2.0   # west face
    else:
        # TB/BT: attach face is north (head) or south (tail), and
        # the cross-rank axis is the node's X.  In TB the record is
        # already in the final frame so the cross-rank fraction is
        # just port_position.x / record.width.
        rec_extent = max(rf.width, 1e-9)
        frac = max(0.0, min(1.0, px_rec / rec_extent))
        x = ln.x - ln.width / 2.0 + frac * ln.width
        if is_tail:
            y = ln.y + ln.height / 2.0   # south face
        else:
            y = ln.y - ln.height / 2.0   # north face

    return (x, y)


def port_point(ln: "LayoutNode", compass: str):
    """Return point on node boundary for a compass direction, or None.
    C analogue: lib/common/shapes.c:compassPort() for the compass-
    direction case.  Returns the boundary point at the requested compass
    direction (n/ne/e/se/s/sw/w/nw/c) on a rectangular node.
    """
    # Lazy import — module-level constant in dot_layout.py.
    from gvpy.engines.layout.dot.dot_layout import _COMPASS
    offsets = _COMPASS.get(compass)
    if offsets is None:
        return None
    dx, dy = offsets
    return (ln.x + dx * ln.width / 2.0, ln.y + dy * ln.height / 2.0)


def compute_label_pos(le: LayoutEdge):
    """Set label_pos at the midpoint of the edge polyline, offset by labelangle/labeldistance.
    C analogue: lib/dotgen/dotsplines.c edge label placement. Computes
    the anchor for an edge label by interpolating along the edge route
    at the configured labeldistance and labelangle.
    """
    if not le.label or not le.points:
        return
    n = len(le.points)
    mid = n // 2
    if n % 2 == 0 and n >= 2:
        x = (le.points[mid - 1][0] + le.points[mid][0]) / 2.0
        y = (le.points[mid - 1][1] + le.points[mid][1]) / 2.0
    else:
        x, y = le.points[mid]

    # Apply labelangle and labeldistance if set on the edge
    if le.edge:
        import math
        angle_str = le.edge.attributes.get("labelangle", "")
        dist_str = le.edge.attributes.get("labeldistance", "")
        if angle_str or dist_str:
            angle = math.radians(float(angle_str)) if angle_str else 0.0
            dist = float(dist_str) * 14.0 if dist_str else 0.0  # scale by font size
            x += dist * math.cos(angle)
            y += dist * math.sin(angle)

    le.label_pos = (round(x, 2), round(y, 2))


def apply_sameport(layout):
    """Merge endpoints for edges with samehead or sametail attributes.
    C analogue: lib/dotgen/sameport.c:dot_sameports().  Merges edges
    that share a samehead or sametail group so they all attach at a
    single port location on the shared node.
    """
    all_edges = [le for le in layout.ledges if not le.virtual] + layout._chain_edges

    # samehead: edges arriving at the same node with same samehead value share endpoint
    head_groups: dict[tuple[str, str], tuple] = {}  # (head_name, samehead) -> point
    for le in all_edges:
        if le.samehead and le.points:
            key = (le.head_name, le.samehead)
            if key not in head_groups:
                head_groups[key] = le.points[-1]
            else:
                le.points[-1] = head_groups[key]

    # sametail: edges leaving the same node with same sametail value share startpoint
    tail_groups: dict[tuple[str, str], tuple] = {}
    for le in all_edges:
        if le.sametail and le.points:
            key = (le.tail_name, le.sametail)
            if key not in tail_groups:
                tail_groups[key] = le.points[0]
            else:
                le.points[0] = tail_groups[key]


def ortho_route(layout, le: LayoutEdge, tail: LayoutNode,
                 head: LayoutNode) -> list[tuple[float, float]]:
    """Route with right-angle bends only (Z-shaped or L-shaped path).
    C analogue: lib/ortho/ortho.c orthogonal routing.  Produces a
    90-degree polyline route between tail and head, used when
    splines=ortho.  Currently a simplified version that does NOT do the
    full ortho channel routing — just places one or two right-angle
    turns based on rank distance.
    """
    # Exit point from tail
    p_start = layout._edge_start_point(le, tail, head)
    # Entry point into head
    p_end = layout._edge_end_point(le, head, tail)

    mid_y = (p_start[1] + p_end[1]) / 2.0

    if abs(p_start[0] - p_end[0]) < 0.5:
        # Vertically aligned — straight vertical line
        return [p_start, p_end]

    # Z-shaped: vertical from tail, horizontal, vertical into head
    return [
        p_start,
        (p_start[0], mid_y),
        (p_end[0], mid_y),
        p_end,
    ]


def route_through_chain(layout, tail_name: str, chain: list[str],
                         head_name: str) -> list[tuple[float, float]]:
    """Route an edge through a chain of virtual nodes.
    C analogue: lib/dotgen/dotsplines.c chain edge routing. For long
    edges that were split by :func: into a chain of virtual nodes, route
    the polyline through each virtual node's position in turn.
    """
    tail = layout.lnodes[tail_name]
    head = layout.lnodes[head_name]

    if not chain:
        p1 = layout._boundary_point(tail, head.x, head.y)
        p2 = layout._boundary_point(head, tail.x, tail.y)
        return [p1, p2]

    # First virtual node
    first_v = layout.lnodes[chain[0]]
    points = [layout._boundary_point(tail, first_v.x, first_v.y)]

    # Intermediate virtual nodes
    for vname in chain:
        vn = layout.lnodes[vname]
        points.append((vn.x, vn.y))

    # Last point: boundary of head node
    last_v = layout.lnodes[chain[-1]]
    points.append(layout._boundary_point(head, last_v.x, last_v.y))

    return points


def boundary_point(ln: LayoutNode, tx: float, ty: float) -> tuple[float, float]:
    """boundary_point.

    C analogue: lib/common/splines.c boundary clip helper. Returns the
    intersection of the line from the node center toward (tx, ty) with
    the node's bounding rectangle.
    """
    cx, cy = ln.x, ln.y
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return (cx, cy - ln.height / 2.0)
    hw, hh = ln.width / 2.0, ln.height / 2.0
    adx, ady = abs(dx), abs(dy)
    if adx * hh > ady * hw:
        scale = hw / adx if adx != 0 else 1.0
    else:
        scale = hh / ady if ady != 0 else 1.0
    return (cx + dx * scale, cy + dy * scale)


def self_loop_points(ln: LayoutNode) -> list[tuple[float, float]]:
    """self_loop_points.

    C analogue: lib/dotgen/dotsplines.c self-loop handling. Returns a
    small arc of control points that loops back to the same node,
    anchored just above the node.
    """
    hw = ln.width / 2.0
    loop = 20.0
    return [
        (ln.x + hw, ln.y),
        (ln.x + hw + loop, ln.y - loop),
        (ln.x + hw + loop, ln.y + loop),
        (ln.x + hw, ln.y),
    ]


def maximal_bbox(layout, ln: LayoutNode) -> tuple[float, float, float, float]:
    """Compute the available bounding box around a node for edge routing.

    X extent: halfway to each neighbor in the same rank (or to graph
    bounds if no neighbor).  Y extent: the rank's height band.
    Mirrors Graphviz ``dotsplines.c:maximal_bbox()``.
    """
    r = ln.rank
    rank_nodes = layout.ranks.get(r, [])
    idx = ln.order

    # X extent: halfway to neighbors
    left_x = layout._left_bound
    right_x = layout._right_bound
    if idx > 0:
        left_ln = layout.lnodes[rank_nodes[idx - 1]]
        left_x = (left_ln.x + left_ln.width / 2 + ln.x - ln.width / 2) / 2
    if idx < len(rank_nodes) - 1:
        right_ln = layout.lnodes[rank_nodes[idx + 1]]
        right_x = (ln.x + ln.width / 2 + right_ln.x - right_ln.width / 2) / 2

    # Y extent: rank band
    top_y = ln.y - layout._rank_ht2.get(r, ln.height / 2)
    bot_y = ln.y + layout._rank_ht1.get(r, ln.height / 2)

    return (left_x, top_y, right_x, bot_y)


# ── Channel routing helpers (port of Graphviz lib/dotgen/dotsplines.c)
# These functions are the building blocks for cluster-aware edge
# routing — the replacement for ``route_regular_edge`` /
# ``route_through_chain``.  They're introduced in stages so each
# commit is reviewable; the final ``channel_route_edge`` that uses
# them is added later.

def _innermost_cluster(layout, node_name: str):
    """Return the smallest cluster containing ``node_name`` or None.

    The "smallest" cluster by ``len(cl.nodes)`` is the innermost in
    the cluster hierarchy (after dedup): ``cl.nodes`` includes all
    transitively-contained nodes, so a cluster with fewer members
    is nested deeper in the tree.
    """
    best = None
    best_size = None
    for cl in layout._clusters:
        if node_name in cl.nodes:
            size = len(cl.nodes)
            if best is None or size < best_size:
                best = cl
                best_size = size
    return best


def _edge_clusters_for_le(layout, le: "LayoutEdge"):
    """Return ``(tail_cluster, head_cluster)`` for an edge.

    For a real edge this is the tail's and head's innermost clusters.
    For a virtual chain edge, look up the *original* edge's tail/head
    via ``orig_tail`` / ``orig_head`` so every edge in the chain
    shares the same cluster context.

    Mirrors the ``tcl``/``hcl`` setup inside Graphviz
    ``dotsplines.c:cl_bound()``::

        if (ND_node_type(n) == NORMAL)
            tcl = hcl = ND_clust(n);
        else {
            orig = ED_to_orig(ND_out(n).list[0]);
            tcl = ND_clust(agtail(orig));
            hcl = ND_clust(aghead(orig));
        }
    """
    if le.orig_tail and le.orig_head:
        t_name, h_name = le.orig_tail, le.orig_head
    else:
        t_name, h_name = le.tail_name, le.head_name
    return (_innermost_cluster(layout, t_name),
            _innermost_cluster(layout, h_name))


def _cl_bound(layout, adj_name: str, tcl, hcl):
    """Return the cluster that bounds a channel box at ``adj_name``.

    C analogue: ``lib/dotgen/dotsplines.c:cl_bound()``.  The C
    version only checks the single ``REAL_CLUSTER(adj)`` value,
    but it relies on C's hierarchical routing where
    ``mark_clusters`` relabels ``ND_clust`` per routing level —
    at the root level every node inside cluster_6754 gets
    ``ND_clust = cluster_6754``, so a foreign-cluster check at
    the root sees only the top-level cluster.

    Python runs routing in a single pass at the root level, so we
    have to do the level walk ourselves: walk ``adj``'s cluster
    chain from **outermost to innermost** and return the outermost
    cluster that is NOT an ancestor of either ``tcl`` or ``hcl``.
    That outermost non-member cluster is the correct "wall" — its
    bounding box is the furthest the edge can extend toward the
    neighbour without crossing into foreign territory.

    Returns None if no wall is found (``adj`` is in the same
    cluster hierarchy as the edge, or not in any cluster).
    """
    tcl_nodes = set(tcl.nodes) if tcl else set()
    hcl_nodes = set(hcl.nodes) if hcl else set()

    # adj's cluster chain, outermost (largest) first.
    adj_clusters = sorted(
        [cl for cl in layout._clusters if adj_name in cl.nodes],
        key=lambda c: -len(c.nodes),
    )
    for cl in adj_clusters:
        cl_nodes = set(cl.nodes)
        # If cl contains tcl or hcl's endpoints, it's an ancestor
        # of the edge's home cluster — the edge is legitimately
        # inside cl, so cl is not a wall.
        if tcl is not None and tcl_nodes <= cl_nodes:
            continue
        if hcl is not None and hcl_nodes <= cl_nodes:
            continue
        # cl contains neither endpoint — it's a foreign cluster
        # that the edge must stay out of.  Since we iterated
        # outermost first, this is the outermost valid wall.
        return cl
    return None


def _rank_neighbor_at(layout, node_name: str, direction: int):
    """Return the immediate rank neighbour at ``order±direction``.

    C analogue: ``lib/dotgen/dotsplines.c:neighbor()``, simplified.
    C's version recurses past virtuals that belong to the same edge
    (via ``pathscross``) so those virtuals don't block the box from
    extending.  For this first port we just take the immediate
    neighbour; the ``pathscross`` refinement can come later.
    """
    ln = layout.lnodes.get(node_name)
    if ln is None:
        return None
    rank_nodes = layout.ranks.get(ln.rank, [])
    target_idx = ln.order + direction
    if 0 <= target_idx < len(rank_nodes):
        return rank_nodes[target_idx]
    return None


def _channel_bbox_for_node(layout, ln: "LayoutNode", le: "LayoutEdge"):
    """Compute the channel bbox around ``ln`` for edge ``le``.

    C analogue: ``lib/dotgen/dotsplines.c:maximal_bbox()``.

    Returns a rectangle ``(min_cr, min_r, max_cr, max_r)`` in the
    *cross-rank / rank* axis frame (not raw x/y — see below).  The
    bbox is the node's "slot" — a rectangle of free space the edge
    can occupy while passing through ``ln``'s rank.  It's bounded:

    - On the cross-rank axis: by the rank neighbours on either
      side, clipped at any non-member cluster's bounding box
      (cluster = wall).
    - On the rank axis: by the rank's own height band.

    Axis frame (Python runs phase 4 *after* ``apply_rankdir``, so
    coordinates are already in LR-final / TB-final frame):

    - TB/BT: cross-rank = X, rank = Y.
    - LR/RL: cross-rank = Y, rank = X.

    The function returns a tuple in **cross-rank / rank** order
    regardless of rankdir — callers must remap to ``(x, y)`` when
    storing the bbox.
    """
    # Extract axis-aware coordinates.
    is_lr = layout.rankdir in ("LR", "RL")
    if is_lr:
        # LR-final: cross-rank axis is Y, rank axis is X.
        cr = ln.y
        cr_half = ln.height / 2.0
        r = ln.x
        r_half = ln.width / 2.0
    else:
        # TB-final: cross-rank axis is X, rank axis is Y.
        cr = ln.x
        cr_half = ln.width / 2.0
        r = ln.y
        r_half = ln.height / 2.0

    # Initial cross-rank extent: the node's own footprint.
    min_cr = cr - cr_half
    max_cr = cr + cr_half

    # Edge's tail/head clusters — used to identify foreign clusters
    # that should act as walls.
    tcl, hcl = _edge_clusters_for_le(layout, le)

    # Extend ``min_cr`` toward the "low" (order-1) rank neighbour.
    # The neighbour's order is lower → its cross-rank value is
    # smaller (visually higher on screen in LR).  We want the box
    # to reach as far as possible toward the neighbour without
    # crossing into it or into a foreign cluster that sits between
    # us and it.
    rank_nodes = layout.ranks.get(ln.rank, [])
    low_name = rank_nodes[ln.order - 1] if ln.order > 0 else None
    if low_name is not None:
        wall = _cl_bound(layout, low_name, tcl, hcl)
        if wall is not None and wall.bb:
            # Foreign cluster on the low side — stop at the edge
            # of the cluster nearer to us (its larger-cr edge).
            cx1, cy1, cx2, cy2 = wall.bb
            wall_near = cy2 if is_lr else cx2
            candidate = wall_near + layout.nodesep / 2.0
        else:
            low_ln = layout.lnodes[low_name]
            if is_lr:
                candidate = low_ln.y + low_ln.height / 2.0 + layout.nodesep / 2.0
            else:
                candidate = low_ln.x + low_ln.width / 2.0 + layout.nodesep / 2.0
        # candidate is the largest cr value the obstacle occupies
        # +nodesep/2 — it's the lower bound of our free space.
        # Since obstacle is below us, candidate < cr-cr_half in a
        # well-formed layout, so this always extends (shrinks) min_cr.
        if candidate < min_cr:
            min_cr = candidate

    # Symmetric extension on the "high" (order+1) side.
    high_name = (rank_nodes[ln.order + 1]
                 if ln.order < len(rank_nodes) - 1 else None)
    if high_name is not None:
        wall = _cl_bound(layout, high_name, tcl, hcl)
        if wall is not None and wall.bb:
            cx1, cy1, cx2, cy2 = wall.bb
            wall_near = cy1 if is_lr else cx1
            candidate = wall_near - layout.nodesep / 2.0
        else:
            high_ln = layout.lnodes[high_name]
            if is_lr:
                candidate = high_ln.y - high_ln.height / 2.0 - layout.nodesep / 2.0
            else:
                candidate = high_ln.x - high_ln.width / 2.0 - layout.nodesep / 2.0
        if candidate > max_cr:
            max_cr = candidate

    # Rank extent: the rank's own height band.
    min_r = r - layout._rank_ht2.get(ln.rank, r_half)
    max_r = r + layout._rank_ht1.get(ln.rank, r_half)

    return (min_cr, min_r, max_cr, max_r)


def _edge_node_path(layout, le: "LayoutEdge") -> list[str]:
    """Return the ordered list of node names an edge traverses.

    - For a regular single-rank edge: ``[tail, head]``.
    - For a multi-rank edge that was split by ``add_virtual_nodes``:
      ``[tail, v1, v2, ..., vn, head]`` using the chain recorded
      in ``layout._vnode_chains[(tail, head)]``.
    - For a flat (same-rank) or self-loop edge: ``[tail, head]``.
      Flat/self-loop routing is handled by their specialised
      routers, not by the channel path; callers should filter
      those out before calling this.
    """
    tail = le.tail_name
    head = le.head_name

    # Chain edges live on layout._chain_edges and have their
    # virtual chain recorded separately.  ``le.virtual`` is set on
    # both the chain bridge edges in ``layout.ledges`` and on the
    # original edge sitting in ``layout._chain_edges``.  We look up
    # the chain by the (orig_tail, orig_head) key that
    # ``add_virtual_nodes`` registered.
    chain_key = (le.orig_tail or tail, le.orig_head or head)
    chain = layout._vnode_chains.get(chain_key)
    if chain:
        return [chain_key[0], *chain, chain_key[1]]
    return [tail, head]


def build_edge_path(layout, le: "LayoutEdge") -> list[tuple[float, float, float, float]]:
    """Assemble the channel-box sequence for an edge.

    C analogue: the per-edge box list built in
    ``lib/dotgen/dotsplines.c:make_regular_edge()`` before handing
    off to ``lib/common/routespl.c:routesplines()``.  Each element
    of the returned list is a box ``(min_cr, min_r, max_cr, max_r)``
    in **cross-rank / rank** axis order as returned by
    :func:`_channel_bbox_for_node` — callers that need raw (x, y)
    must remap based on ``layout.rankdir``.

    The sequence runs from tail to head, with one box per node
    (or virtual node) the edge touches.  For a regular single-rank
    edge the list has two entries: ``[tail_box, head_box]``.  For
    a split multi-rank edge it has ``2 + len(chain)`` entries.

    Only regular (directed, multi-rank) and chain edges belong
    here.  Flat edges, self-loops, ortho, and compound edges have
    their own routers upstream.

    This function is a building block for the channel-based
    replacement of ``route_regular_edge`` / ``route_through_chain``;
    it is not yet wired into ``phase4_routing``.
    """
    path_names = _edge_node_path(layout, le)
    boxes: list[tuple[float, float, float, float]] = []
    for name in path_names:
        ln = layout.lnodes.get(name)
        if ln is None:
            continue
        boxes.append(_channel_bbox_for_node(layout, ln, le))
    return boxes


def _find_gap_obstacles(layout, box_i, box_j, tcl, hcl):
    """Return non-member clusters that sit in the gap between two boxes.

    Helper for :func:`route_through_channel_boxes`'s disjoint-box
    bridging logic.  A cluster counts as an obstacle when:

    - It overlaps the cross-rank gap between ``box_i`` and ``box_j``.
    - It overlaps the rank-axis range spanning the two boxes.
    - It is NOT an ancestor of either ``tcl`` or ``hcl`` (those
      clusters legitimately contain the edge).

    Returned in order of decreasing cross-rank extent — the
    outermost / most-constraining cluster first.
    """
    cr_i_min, _, cr_i_max, _ = box_i
    cr_j_min, _, cr_j_max, _ = box_j
    if cr_i_max < cr_j_min:
        gap_cr = (cr_i_max, cr_j_min)
    elif cr_j_max < cr_i_min:
        gap_cr = (cr_j_max, cr_i_min)
    else:
        return []  # boxes overlap, no gap

    _, r_i_min, _, r_i_max = box_i
    _, r_j_min, _, r_j_max = box_j
    transit_r = (min(r_i_min, r_j_min), max(r_i_max, r_j_max))

    is_lr = layout.rankdir in ("LR", "RL")
    tcl_nodes = set(tcl.nodes) if tcl else set()
    hcl_nodes = set(hcl.nodes) if hcl else set()

    obstacles: list = []
    for cl in layout._clusters:
        if not cl.bb:
            continue
        cx1, cy1, cx2, cy2 = cl.bb
        if is_lr:
            cl_cr = (cy1, cy2)  # LR: cross-rank axis = y
            cl_r = (cx1, cx2)   # LR: rank axis = x
        else:
            cl_cr = (cx1, cx2)  # TB: cross-rank axis = x
            cl_r = (cy1, cy2)   # TB: rank axis = y

        # Skip if cluster doesn't overlap the gap in cross-rank.
        if max(cl_cr[0], gap_cr[0]) >= min(cl_cr[1], gap_cr[1]):
            continue
        # Skip if cluster doesn't overlap the transition rank range.
        if max(cl_r[0], transit_r[0]) >= min(cl_r[1], transit_r[1]):
            continue
        # Skip if cluster is an ancestor of tcl or hcl (edge is
        # legitimately inside it).
        cl_nodes = set(cl.nodes)
        if tcl is not None and tcl_nodes <= cl_nodes:
            continue
        if hcl is not None and hcl_nodes <= cl_nodes:
            continue
        obstacles.append(cl)

    # Sort by cross-rank extent so the widest (outermost) blocker
    # comes first.
    if is_lr:
        obstacles.sort(key=lambda c: -(c.bb[3] - c.bb[1]))
    else:
        obstacles.sort(key=lambda c: -(c.bb[2] - c.bb[0]))
    return obstacles


def _row_crossings(layout, p1, p2, tcl_nodes, hcl_nodes) -> list:
    """Return non-member real nodes whose bbox the segment crosses."""
    crossing: list = []
    for node_name, ln in layout.lnodes.items():
        if ln.virtual:
            continue
        if node_name in tcl_nodes or node_name in hcl_nodes:
            continue
        bb = (ln.x - ln.width / 2.0, ln.y - ln.height / 2.0,
              ln.x + ln.width / 2.0, ln.y + ln.height / 2.0)
        if _seg_hits_bbox(p1, p2, bb):
            crossing.append(ln)
    return crossing


def _row_safe_cr(crossing: list, orig_cr: float, is_lr: bool,
                  margin: float) -> float:
    """Pick a safe cross-rank value just outside a row of node bboxes.

    Returns the side (above or below the combined row bbox) that is
    closer to ``orig_cr``, offset by ``margin``.
    """
    if is_lr:
        row_min = min(ln.y - ln.height / 2.0 for ln in crossing)
        row_max = max(ln.y + ln.height / 2.0 for ln in crossing)
    else:
        row_min = min(ln.x - ln.width / 2.0 for ln in crossing)
        row_max = max(ln.x + ln.width / 2.0 for ln in crossing)
    safe_above = row_min - margin
    safe_below = row_max + margin
    if abs(orig_cr - safe_above) <= abs(orig_cr - safe_below):
        return safe_above
    return safe_below


def _bridge_row_detour(layout, b1, b2, waypt_i, waypt_j,
                        tcl, hcl) -> list:
    """Augment a two-point bridge with detours around any row of nodes.

    After ``_bridge_points_for_obstacle`` picks a side and returns
    ``[b1, b2]``, either the *top* leg (``waypt_i -> b1``) or the
    *bottom* leg (``b2 -> waypt_j``) can run straight through a
    row of real nodes — whenever the bridge column's row lines
    happen to coincide with a cluster of neighbour nodes on other
    ranks.  For each leg that crosses nodes we move its cross-rank
    endpoint to just outside the row's combined bbox and add a
    short finishing segment back to the original endpoint.

    The result is a variable-length bridge with up to four waypoints
    arranged as a staircase:

        [b1_adjusted, b2_adjusted, b3 (optional), b4 (optional)]

    Concrete cases on ``aa1332.dot``:

    - ``c0 -> c5359`` bottom leg at y=674.4 crossed c4045/c4046/
      c4253/c4254 (all at y≈686).  The detour drops to y=655 before
      running east across the corridor, then rises back to 674.4 at
      the head column.
    - ``c6378 -> c6383`` top leg at y=479.2 crossed c6411 (at
      y≈482).  The detour raises b1 past c6411's top edge before
      going east, then rises back to 479.2 at the bridge column.

    Returns ``None`` when neither leg needs a detour, leaving the
    original two-point bridge in place.
    """
    is_lr = layout.rankdir in ("LR", "RL")
    tcl_nodes = set(tcl.nodes) if tcl is not None else set()
    hcl_nodes = set(hcl.nodes) if hcl is not None else set()
    margin = float(getattr(layout, "_CL_OFFSET", 8.0))

    top_crossing = _row_crossings(layout, waypt_i, b1, tcl_nodes, hcl_nodes)
    bot_crossing = _row_crossings(layout, b2, waypt_j, tcl_nodes, hcl_nodes)
    if not top_crossing and not bot_crossing:
        return None

    # Staircase points.  We may insert a detour on each leg.
    points: list = []

    if top_crossing:
        # Move b1 into the safe cross-rank band, then add a
        # finishing waypoint at the original b1 cross-rank so the
        # vertical leg to b2 remains at the chosen bridge column.
        safe_cr = _row_safe_cr(top_crossing, waypt_i[1] if is_lr else waypt_i[0],
                                is_lr, margin)
        if is_lr:
            new_b1_entry = (waypt_i[0], safe_cr)
            new_b1_col = (b1[0], safe_cr)
        else:
            new_b1_entry = (safe_cr, waypt_i[1])
            new_b1_col = (safe_cr, b1[1])
        points.extend([new_b1_entry, new_b1_col, b1])
    else:
        points.append(b1)

    if bot_crossing:
        safe_cr = _row_safe_cr(bot_crossing, b2[1] if is_lr else b2[0],
                                is_lr, margin)
        if is_lr:
            new_b2_col = (b2[0], safe_cr)
            new_b2_exit = (waypt_j[0], safe_cr)
        else:
            new_b2_col = (safe_cr, b2[1])
            new_b2_exit = (safe_cr, waypt_j[1])
        points.extend([new_b2_col, new_b2_exit])
    else:
        points.append(b2)

    return points


class _NodeObstacle:
    """Adapter exposing a layout node as a cluster-like obstacle.

    ``_find_segment_obstacles`` and ``_bridge_foreign_hits`` iterate
    cluster-like objects that expose ``.bb``, ``.name``, and
    ``.nodes``.  This tiny wrapper lets us mix individual node
    bboxes into the same pipeline without changing the callers' shape.

    The underlying motivation: channel routing used to treat cluster
    bboxes as obstacles but ignored individual nodes.  A bridge
    segment that avoided every cluster could still run straight
    through a row of nodes (e.g. on ``aa1332.dot`` the
    ``c0 -> c5359`` bridge bottom at y=674.4 ran through the
    interiors of c4045, c4046, c4253, c4254 because none of their
    wrapping clusters were flagged as an obstacle on the bridge's
    own segments).  Including nodes in the obstacle list lets the
    bridge-side scoring penalise those crossings so the router
    picks a column that misses the row.
    """
    __slots__ = ("name", "bb", "nodes")

    def __init__(self, name: str, ln: "LayoutNode"):
        self.name = name
        self.bb = (ln.x - ln.width / 2.0,
                   ln.y - ln.height / 2.0,
                   ln.x + ln.width / 2.0,
                   ln.y + ln.height / 2.0)
        self.nodes = {name}


def _find_segment_obstacles(layout, p1, p2, name_i, name_j, tcl, hcl):
    """Return the obstacles the segment ``p1→p2`` actually crosses.

    Obstacles are any combination of:

    - **Non-member clusters** whose bbox the segment enters.  Skipped:
      clusters with no bb; ``tcl`` / ``hcl`` and their ancestors
      (``tcl.nodes ⊆ cl.nodes``); clusters that contain the segment's
      own endpoint node (the edge naturally exits that cluster's
      wall on the way past).

    - **Non-endpoint real nodes** whose bbox the segment enters,
      wrapped in :class:`_NodeObstacle`.  This catches cases where a
      long bridge segment runs along a cross-rank corridor populated
      by a row of real nodes — the bridge column then gets penalised
      via :func:`_bridge_foreign_hits` and the opposite side wins.
      Skipped: virtual nodes; the segment's own endpoints
      (``name_i`` / ``name_j``); the edge's tail / head (they may be
      touched at the stub points).

    Returned sorted by decreasing cross-rank extent, so the most
    constraining blocker comes first and the bridge logic wraps
    around it preferentially.
    """
    is_lr = layout.rankdir in ("LR", "RL")
    tcl_nodes = set(tcl.nodes) if tcl is not None else set()
    hcl_nodes = set(hcl.nodes) if hcl is not None else set()
    hits: list = []

    # Cluster obstacles.
    for cl in layout._clusters:
        if not cl.bb:
            continue
        cl_nodes = set(cl.nodes)
        if tcl is not None and tcl_nodes <= cl_nodes:
            continue
        if hcl is not None and hcl_nodes <= cl_nodes:
            continue
        if name_i in cl_nodes or name_j in cl_nodes:
            continue
        if _seg_hits_bbox(p1, p2, cl.bb):
            hits.append(cl)

    # Node obstacles — treat each non-endpoint real node as a
    # cluster-shaped obstacle with its own bbox.
    for node_name, ln in layout.lnodes.items():
        if ln.virtual:
            continue
        if node_name == name_i or node_name == name_j:
            continue
        if node_name in tcl_nodes or node_name in hcl_nodes:
            continue
        obs = _NodeObstacle(node_name, ln)
        if _seg_hits_bbox(p1, p2, obs.bb):
            hits.append(obs)

    if is_lr:
        hits.sort(key=lambda c: -(c.bb[3] - c.bb[1]))
    else:
        hits.sort(key=lambda c: -(c.bb[2] - c.bb[0]))
    return hits


def _seg_hits_bbox(p1, p2, bb) -> bool:
    """Liang-Barsky segment-vs-AABB intersection test.

    Returns True if the segment from ``p1`` to ``p2`` enters the
    rectangle ``bb = (x1, y1, x2, y2)`` (inclusive).  Handles
    axis-aligned segments via the ``p == 0`` half-plane check.
    """
    x1, y1, x2, y2 = bb
    ax, ay = p1
    bx, by = p2
    dx, dy = bx - ax, by - ay
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax - x1), (dx, x2 - ax),
                 (-dy, ay - y1), (dy, y2 - ay)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            if t > t0:
                t0 = t
        else:
            if t < t0:
                return False
            if t < t1:
                t1 = t
    return t0 <= t1


def _bridge_foreign_hits(layout, waypt_i, waypt_j, bridges,
                          obstacle, tcl, hcl) -> int:
    """Count non-member clusters AND non-endpoint nodes the bridge
    segments would cross.

    The bridge consists of three segments:

    1. ``waypt_i`` → ``bridges[0]``  (rank-axis lateral leg)
    2. ``bridges[0]`` → ``bridges[1]`` (cross-rank column at side_r)
    3. ``bridges[1]`` → ``waypt_j``   (rank-axis lateral leg)

    Each cluster or node counts as one hit when *any* of the three
    segments enters its bbox, **excluding**:

    - the primary ``obstacle`` being bridged around (bridges wrap
      around it by design);
    - ``tcl``/``hcl`` and their ancestor clusters (those legitimately
      contain the edge);
    - clusters that contain ``obstacle`` itself (wrapping clusters
      that the bridge path is already grazing).
    - virtual nodes and the edge's tail / head (they sit at the
      segment's endpoints).

    Including nodes in the count is what makes the scoring prefer
    a bridge column that *misses* a row of aligned nodes; without
    it the bridge could run straight through e.g. c4045/c4046/
    c4253/c4254 on aa1332.dot without any penalty.
    """
    segs = (
        (waypt_i, bridges[0]),
        (bridges[0], bridges[1]),
        (bridges[1], waypt_j),
    )
    tcl_nodes = set(tcl.nodes) if tcl is not None else set()
    hcl_nodes = set(hcl.nodes) if hcl is not None else set()
    # Identify the edge's own tail / head names so node-scoring
    # doesn't double-count them as hits.
    edge_tail_name = next(iter(tcl_nodes)) if len(tcl_nodes) == 1 else None
    edge_head_name = next(iter(hcl_nodes)) if len(hcl_nodes) == 1 else None
    hits = 0
    # Cluster hits.
    for cl in layout._clusters:
        if cl is obstacle or not cl.bb:
            continue
        if cl is tcl or cl is hcl:
            continue
        cl_nodes = set(cl.nodes)
        if tcl is not None and tcl_nodes <= cl_nodes:
            continue
        if hcl is not None and hcl_nodes <= cl_nodes:
            continue
        for s1, s2 in segs:
            if _seg_hits_bbox(s1, s2, cl.bb):
                hits += 1
                break
    # Node hits — a row of aligned nodes in a corridor is the main
    # offender the cluster-only scoring missed.
    for node_name, ln in layout.lnodes.items():
        if ln.virtual:
            continue
        if node_name == edge_tail_name or node_name == edge_head_name:
            continue
        if node_name in tcl_nodes or node_name in hcl_nodes:
            continue
        bb = (ln.x - ln.width / 2.0, ln.y - ln.height / 2.0,
              ln.x + ln.width / 2.0, ln.y + ln.height / 2.0)
        for s1, s2 in segs:
            if _seg_hits_bbox(s1, s2, bb):
                hits += 1
                break
    return hits


def _face_constraint_side(ln: "LayoutNode",
                           face_pt: tuple[float, float],
                           is_lr: bool) -> float | None:
    """Return the rank-axis value the bridge column must respect.

    If ``face_pt`` (an attach / stub point) sits on a specific face
    of ``ln``, returns the rank-axis coordinate the bridge column
    must stay on the *outside* of so that the final segment from
    the bridge to ``face_pt`` approaches from outside the node
    rather than crossing its interior.

    The sign convention returned is:
      - ``(+1, threshold)`` → bridge.r must be ``>= threshold``
      - ``(-1, threshold)`` → bridge.r must be ``<= threshold``
      - ``None``            → ``face_pt`` is not clearly on any
                              face (diagonal corner, not a port)

    For a west-face attach (``face_pt`` on ln's west face in LR),
    the bridge column must sit at ``x <= ln.x - ln.width/2`` so the
    final segment runs east into the face from outside the node.
    Symmetric for east (``x >= east``), north (``y <= north``), and
    south (``y >= south``).

    In LR mode ``is_lr=True`` the rank axis is X, so west/east
    faces yield rank-axis constraints.  In TB mode the rank axis
    is Y, so north/south faces yield the constraints.  A face
    whose normal points along the *cross-rank* axis (e.g. north/
    south in LR) can't be avoided by adjusting the rank-axis
    bridge column and returns ``None``.
    """
    hw = ln.width / 2.0
    hh = ln.height / 2.0
    tol = 1e-3
    on_east = abs(face_pt[0] - (ln.x + hw)) < tol
    on_west = abs(face_pt[0] - (ln.x - hw)) < tol
    on_north = abs(face_pt[1] - (ln.y - hh)) < tol
    on_south = abs(face_pt[1] - (ln.y + hh)) < tol
    if is_lr:
        if on_east:
            return (+1, ln.x + hw)
        if on_west:
            return (-1, ln.x - hw)
        return None
    else:
        if on_south:
            return (+1, ln.y + hh)
        if on_north:
            return (-1, ln.y - hh)
        return None


def _bridge_points_for_obstacle(layout, waypt_i, waypt_j, obstacle,
                                 tcl=None, hcl=None,
                                 tail_ln=None, tail_face_pt=None,
                                 head_ln=None, head_face_pt=None):
    """Return the two bridge waypoints routing around ``obstacle``.

    Step 6a — obstacle-aware side selection
    ---------------------------------------
    The bridge can go around ``obstacle`` on either of two sides of
    its rank-axis range (left/right in TB; below/above in LR).  The
    old step-5b heuristic picked the side closer to the midpoint of
    ``waypt_i`` and ``waypt_j``, which can land inside *another*
    cluster that wasn't considered when selecting the side (e.g.
    ``c0->c5359`` avoids ``cluster_5378`` but lands inside
    ``cluster_6382``).

    We now build candidate waypoints for **both** sides, score each
    candidate by the number of non-member clusters its three bridge
    segments would cross (via :func:`_bridge_foreign_hits`), and
    pick the side with fewer hits.  Ties fall back to the midpoint
    heuristic so behaviour is unchanged when neither side conflicts.

    Step 6c — head/tail face constraint
    -----------------------------------
    When this segment's ``waypt_i`` / ``waypt_j`` sits on a node
    face (identified via the optional ``tail_face_pt`` / ``head_
    face_pt`` hints the caller passes in), a *hard* face-side
    preference applies: the bridge column must lie on the face's
    outside so the final bridge leg approaches the attach point
    from outside the node rather than crossing its interior.  Both
    sides are tested against the constraint; only compliant sides
    are scored by :func:`_bridge_foreign_hits`.  If both sides
    satisfy (or both fail), we fall through to the scoring +
    midpoint fallback as before.

    Concrete case: ``c0->c5359`` chain with the head port In0 on
    c5359's west face at ``x=2466.8``.  Without the constraint the
    scoring picked the right side (``x=2608``, east of c5359) and
    the final bridge leg crossed c5359's interior before hitting
    the west face — producing a visible 8pt stub overshooting the
    west edge of the node.  With the constraint the head-face
    bias forces the left side (``x=1730``, west of c5359) so the
    bridge leg approaches from outside the node.
    """
    is_lr = layout.rankdir in ("LR", "RL")
    ox1, oy1, ox2, oy2 = obstacle.bb
    if is_lr:
        # LR: rank axis = x, cross-rank axis = y.
        # waypt tuple is (x, y) i.e. (rank, cross-rank).
        o_r_min, o_r_max = ox1, ox2
        r_i, cr_i = waypt_i[0], waypt_i[1]
        r_j, cr_j = waypt_j[0], waypt_j[1]
    else:
        # TB: rank axis = y, cross-rank axis = x.
        # waypt tuple is (x, y) i.e. (cross-rank, rank).
        o_r_min, o_r_max = oy1, oy2
        r_i, cr_i = waypt_i[1], waypt_i[0]
        r_j, cr_j = waypt_j[1], waypt_j[0]

    margin = layout.nodesep / 2.0 + 4.0
    left_side_r = o_r_min - margin
    right_side_r = o_r_max + margin

    if is_lr:
        left_pts = [(left_side_r, cr_i), (left_side_r, cr_j)]
        right_pts = [(right_side_r, cr_i), (right_side_r, cr_j)]
    else:
        left_pts = [(cr_i, left_side_r), (cr_j, left_side_r)]
        right_pts = [(cr_i, right_side_r), (cr_j, right_side_r)]

    # Step 6c — face-side constraint.  Compute per-side compliance
    # with any head/tail attach-face hints the caller provided.  A
    # non-compliant side would cause the final bridge leg to cross
    # the head or tail node's interior before reaching the stub, so
    # we treat compliance as a hard preference over cluster hits.
    def _side_complies(side_r: float) -> bool:
        for ln, pt in ((tail_ln, tail_face_pt), (head_ln, head_face_pt)):
            if ln is None or pt is None:
                continue
            constraint = _face_constraint_side(ln, pt, is_lr)
            if constraint is None:
                continue
            sign, threshold = constraint
            if sign > 0 and side_r < threshold:
                return False
            if sign < 0 and side_r > threshold:
                return False
        return True

    left_ok = _side_complies(left_side_r)
    right_ok = _side_complies(right_side_r)

    left_hits = _bridge_foreign_hits(
        layout, waypt_i, waypt_j, left_pts, obstacle, tcl, hcl)
    right_hits = _bridge_foreign_hits(
        layout, waypt_i, waypt_j, right_pts, obstacle, tcl, hcl)

    # Midpoint-distance fallback mirrors the original step-5b
    # heuristic and is only consulted on a tie.
    r_mid = (r_i + r_j) / 2.0
    left_closer = (r_mid - o_r_min) <= (o_r_max - r_mid)
    fallback = left_pts if left_closer else right_pts

    # Hard face-side preference: if exactly one side complies, use it.
    if left_ok and not right_ok:
        chosen = left_pts
    elif right_ok and not left_ok:
        chosen = right_pts
    # Both comply (or both fail) — fall through to scoring.
    elif left_hits < right_hits:
        chosen = left_pts
    elif right_hits < left_hits:
        chosen = right_pts
    else:
        chosen = fallback

    # Step 6d — row detour.  If the chosen bridge's bottom leg
    # ``chosen[1] -> waypt_j`` runs straight through a row of
    # real nodes (happens when the head's rank y-band contains
    # other nodes on adjacent ranks — cf. c0->c5359 crossing
    # c4045/c4046/c4253/c4254), augment the bridge with a
    # staircase detour around the row.
    detoured = _bridge_row_detour(layout, chosen[0], chosen[1],
                                   waypt_i, waypt_j, tcl, hcl)
    if detoured is not None:
        return detoured
    return chosen


def _perp_stub(ln: "LayoutNode", boundary_pt: tuple[float, float],
               stub_len: float) -> tuple[float, float]:
    """Return a stub point just outside ``boundary_pt`` on ``ln``.

    Determines which face of ``ln`` (east/west/north/south) the
    attach point lies on and offsets the stub along the *axis-aligned*
    outward normal of that face by ``stub_len``.  Face detection is
    signed-distance-based: the face whose plane is closest to
    ``boundary_pt`` wins, and ties fall through east/west before
    north/south.

    Using the axis-aligned face normal rather than a centre-to-point
    direction matters for record-shape ports that sit off-centre on
    a rank face — the geometric normal is still pure east/west/etc,
    but a centre-to-point vector would pick up a spurious cross-rank
    component (e.g. (0.987, 0.157) instead of (1, 0) for an Out1
    port one third down the east face).  That spurious component
    leaked into ``to_bezier``'s ``ev0`` and made the fitted curve
    start at an angle instead of perpendicular to the face.

    Inserting this stub point right after (or right before) the
    boundary point in the edge polyline forces the first (or last)
    polyline segment to be parallel to the face normal, which becomes
    ``to_bezier``'s tangent estimate so the fitted Bezier curve
    leaves / enters the node face at a right angle.
    """
    hw = ln.width / 2.0
    hh = ln.height / 2.0
    east = ln.x + hw
    west = ln.x - hw
    north = ln.y - hh
    south = ln.y + hh
    # Signed distance of the attach point to each face plane.  The
    # smallest absolute value identifies the face the point sits on.
    d_east = abs(east - boundary_pt[0])
    d_west = abs(boundary_pt[0] - west)
    d_north = abs(boundary_pt[1] - north)
    d_south = abs(south - boundary_pt[1])
    best = min(d_east, d_west, d_north, d_south)
    if best == d_east:
        return (boundary_pt[0] + stub_len, boundary_pt[1])
    if best == d_west:
        return (boundary_pt[0] - stub_len, boundary_pt[1])
    if best == d_north:
        return (boundary_pt[0], boundary_pt[1] - stub_len)
    return (boundary_pt[0], boundary_pt[1] + stub_len)


def route_through_channel_boxes(
    layout,
    le: "LayoutEdge",
    path_names: list[str],
    boxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float]]:
    """Produce polyline waypoints from a channel box sequence.

    C analogue: the final output of
    ``lib/dotgen/dotsplines.c:make_regular_edge()`` after
    ``completeregularpath`` and ``adjustregularpath`` have walked
    the box list.

    Step 5a — box clamping
    ----------------------
    For each node in the edge's path, the base waypoint is the
    node's current ``(x, y)`` with the cross-rank coordinate
    clamped to the channel box's cross-rank range.  This keeps
    every waypoint inside its box so it respects the cluster
    walls computed in :func:`_channel_bbox_for_node`.

    Step 5b — disjoint-box bridging
    -------------------------------
    When two consecutive boxes have **disjoint cross-rank ranges**
    (an obstacle cluster sits between them), a straight segment
    between the clamped waypoints would still cross the obstacle.
    We detect the disjoint case, find the outermost obstacle
    cluster in the gap via :func:`_find_gap_obstacles`, and insert
    two bridge waypoints via :func:`_bridge_points_for_obstacle`
    that route laterally around the obstacle's nearest rank-axis
    edge.

    Step 6a — obstacle-aware bridge side selection
    -----------------------------------------------
    :func:`_bridge_points_for_obstacle` now scores both candidate
    sides of the obstacle by how many non-member clusters the
    resulting bridge segments would cross and picks the lower-hit
    side.  The old midpoint-distance heuristic is retained only as
    a tiebreak.  See the function docstring for the rationale.

    The first and last waypoints are replaced by proper tail/head
    boundary/port points via ``edge_start_point`` /
    ``edge_end_point`` to match the existing routers' endpoint
    handling.

    Not yet wired into ``phase4_routing`` — still dead code.
    """
    is_lr = layout.rankdir in ("LR", "RL")
    tcl, hcl = _edge_clusters_for_le(layout, le)

    # Step 5a: base waypoint per node, clamped to its box.
    base: list[tuple[float, float]] = []
    for name, box in zip(path_names, boxes):
        ln = layout.lnodes.get(name)
        if ln is None:
            continue
        min_cr, _, max_cr, _ = box
        if is_lr:
            cr_clamped = max(min_cr, min(max_cr, ln.y))
            base.append((ln.x, cr_clamped))
        else:
            cr_clamped = max(min_cr, min(max_cr, ln.x))
            base.append((cr_clamped, ln.y))

    if len(base) < 2:
        return base

    # Build the perpendicular-stub skeleton *first*: replace the tail
    # and head base waypoints with proper boundary / port attach
    # points, and add a short rank-axis stub just past each.  The
    # stubs pin the eventual Bezier tangent to the face normal, but
    # they also pull the endpoints in toward the node along the rank
    # axis — so the effective routing polyline is usually narrower
    # on the cross-rank axis than a raw center-to-center line would
    # be.  Obstacle detection runs on *this* skeleton (step 6b'), so
    # an edge whose stubbed path already misses every cluster does
    # not trigger a bridge detour at all — the curve stays a simple
    # near-straight spline.  The user-visible payoff: parallel edges
    # like c3378->c4045 that only *seemed* to cross cluster_5378 on
    # the center-to-center diagonal now route as plain splines
    # because the stub-pulled polyline never enters the cluster.
    tail = layout.lnodes.get(path_names[0]) if path_names else None
    head = layout.lnodes.get(path_names[-1]) if path_names else None
    if tail is not None and head is not None:
        exit_pt = layout._edge_start_point(le, tail, head)
        entry_pt = layout._edge_end_point(le, head, tail)
        stub_len = float(getattr(layout, "_CL_OFFSET", 8.0))
        stub_out = _perp_stub(tail, exit_pt, stub_len)
        stub_in = _perp_stub(head, entry_pt, stub_len)
    else:
        exit_pt = base[0]
        entry_pt = base[-1]
        stub_out = base[0]
        stub_in = base[-1]

    # Starting skeleton: [exit, stub_out, mid-base..., stub_in, entry].
    # ``mid_base`` is the base waypoints that lie strictly between the
    # two endpoints; for a 2-node edge it's empty, for a chain it's
    # the virtual nodes' centers.
    mid_base = base[1:-1]
    skeleton: list[tuple[float, float]] = (
        [exit_pt, stub_out] + list(mid_base) + [stub_in, entry_pt])

    # Step 5b / 6b': walk adjacent pairs of the stub skeleton and
    # insert bridge waypoints whenever a segment actually crosses a
    # non-member cluster bbox.  ``_find_segment_obstacles`` sees the
    # stub-pulled coordinates so it only reports real crossings.
    #
    # For each segment we also compute whether either endpoint is
    # "near" the tail or head attach face, so :func:`_bridge_points_
    # for_obstacle` can apply its face-side constraint (step 6c):
    # the bridge column must sit on the outside of the head / tail
    # face so the final bridge leg doesn't cross the node interior
    # before reaching the stub.  The "near" test is just index-based
    # because ``skeleton`` is always built as
    # ``[exit, stub_out, mid..., stub_in, entry]``.
    last = len(skeleton) - 1
    waypoints: list[tuple[float, float]] = [skeleton[0]]
    for i in range(last):
        p_i = skeleton[i]
        p_j = skeleton[i + 1]
        # Segment owner node names for the keepout filter (skip
        # clusters that contain the segment's own endpoint node).
        # Stub segments (index 0->1 and last-1->last) belong to the
        # tail / head; everything in between uses path_names for the
        # corresponding base index.
        if i == 0:
            ni, nj = path_names[0], path_names[0]
        elif i == last - 1:
            ni, nj = path_names[-1], path_names[-1]
        else:
            ni = path_names[i - 1] if i - 1 < len(path_names) else path_names[0]
            nj = path_names[i] if i < len(path_names) else path_names[-1]
        obstacles = _find_segment_obstacles(
            layout, p_i, p_j, ni, nj, tcl, hcl)
        if obstacles:
            # Pass face hints: p_i touches the tail face iff it's
            # the first skeleton point (``exit_pt``) or the stub_out
            # that sits one stub_len outside the face.  Similarly
            # for p_j at the head end.  We pass the actual attach
            # point (``exit_pt`` / ``entry_pt``) as the face hint,
            # not the stub, because the face-side check projects
            # onto the node's face planes.
            # The tail face hint applies when the segment's start
            # point (p_i) is the exit or the stub_out just past it
            # — segment indices 0 and 1.  The head hint applies
            # when the segment's end point (p_j) is the stub_in
            # (at skeleton index last-1) or the entry (at last) —
            # segment indices last-2 and last-1.  Without this the
            # bridge inserted on the ``v4 -> stub_in`` segment
            # wouldn't see any face constraint and would pick the
            # wrong side of the obstacle.
            b_tail_ln = tail if i <= 1 else None
            b_tail_pt = exit_pt if i <= 1 else None
            b_head_ln = head if i >= last - 2 else None
            b_head_pt = entry_pt if i >= last - 2 else None
            bridges = _bridge_points_for_obstacle(
                layout, p_i, p_j, obstacles[0],
                tcl=tcl, hcl=hcl,
                tail_ln=b_tail_ln, tail_face_pt=b_tail_pt,
                head_ln=b_head_ln, head_face_pt=b_head_pt)
            waypoints.extend(bridges)
        waypoints.append(p_j)

    return waypoints


def _split_at_sharp_corners(pts, cos_threshold: float = 0.8):
    """Split a polyline into smooth runs at vertices with sharp turns.

    A sharp turn is a vertex where the cosine of the angle between the
    incoming and outgoing segment unit vectors is below ``cos_threshold``
    (default 0.8 ≈ bend greater than 37°).  Returns a list of
    sub-polylines where each successive run shares its first point with
    the previous run's last point (so concatenation after bezier fitting
    drops one duplicate).

    The default is deliberately strict: channel-routed polylines have
    mostly straight segments with hard 90° bridge corners and a minor
    angular jog at the edge-boundary snap (≈40° where the boundary
    exit point meets the first bridge column).  The stricter threshold
    classifies that jog as a corner too, so the Schneider fit never
    sees a near-degenerate 3-point run whose tangent extrapolation
    would swing the curve into a neighbouring cluster.

    Used by :func:`_bezier_split_at_corners` to prevent
    :func:`to_bezier`'s Schneider fit from smearing hard 90° bridge
    corners into wildly-extrapolated control points.
    """
    import math
    if len(pts) < 3:
        return [list(pts)]
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = [pts[0]]
    for i in range(1, len(pts) - 1):
        p0 = pts[i - 1]
        p1 = pts[i]
        p2 = pts[i + 1]
        v1x, v1y = p1[0] - p0[0], p1[1] - p0[1]
        v2x, v2y = p2[0] - p1[0], p2[1] - p1[1]
        len1 = math.hypot(v1x, v1y)
        len2 = math.hypot(v2x, v2y)
        if len1 < 1e-9 or len2 < 1e-9:
            current.append(p1)
            continue
        cos_t = (v1x * v2x + v1y * v2y) / (len1 * len2)
        current.append(p1)
        if cos_t < cos_threshold:
            # Sharp corner — close this run, start a new one from p1.
            runs.append(current)
            current = [p1]
    current.append(pts[-1])
    runs.append(current)
    return runs


def _rounded_corner_bezier(pts, radius: float = 8.0,
                            cos_threshold: float = 0.8):
    """Convert a polyline to cubic Bezier with rounded sharp corners.

    At each interior vertex ``V`` whose turn angle exceeds the
    threshold (``cos < cos_threshold``), the hard corner is replaced
    by a cubic *fillet*:

    - Let ``A = V + r * unit(P_prev - V)`` and
      ``B = V + r * unit(P_next - V)`` be points on the incoming and
      outgoing segments at distance ``r`` from the corner.
    - The straight segments terminate at ``A`` and start from ``B``.
    - A cubic Bezier ``[A, V, V, B]`` bridges the two — placing both
      control points exactly at the corner makes the curve tangent
      to each straight segment at ``A`` and ``B`` (G1 continuous),
      giving the rounded-corner appearance.

    The radius is clamped per corner to
    ``0.5 * min(len_incoming, len_outgoing)`` so a fillet never
    consumes more than half of either adjacent segment.

    Straight runs between corners and straight-through segments are
    emitted as straight cubics (chord/3 controls).  This function
    replaces the earlier ``_bezier_split_at_corners`` — it serves
    the same purpose (preventing sharp-corner overshoot) while
    producing visibly smoother curves.
    """
    import math
    n = len(pts)
    if n < 2:
        return list(pts)
    if n == 2:
        p0, p1 = pts
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        return [p0, (p0[0] + dx / 3, p0[1] + dy / 3),
                (p0[0] + 2 * dx / 3, p0[1] + 2 * dy / 3), p1]

    # Step 1: classify each interior vertex as corner or smooth.
    corner = [False] * n
    for i in range(1, n - 1):
        v1x = pts[i][0] - pts[i - 1][0]
        v1y = pts[i][1] - pts[i - 1][1]
        v2x = pts[i + 1][0] - pts[i][0]
        v2y = pts[i + 1][1] - pts[i][1]
        len1 = math.hypot(v1x, v1y)
        len2 = math.hypot(v2x, v2y)
        if len1 < 1e-9 or len2 < 1e-9:
            continue
        cos_t = (v1x * v2x + v1y * v2y) / (len1 * len2)
        if cos_t < cos_threshold:
            corner[i] = True

    if not any(corner):
        return to_bezier(pts)

    # Step 2: pre-compute fillet anchor points A[i], B[i] at each corner.
    A: list = [None] * n  # anchor on incoming segment
    B: list = [None] * n  # anchor on outgoing segment
    for i in range(n):
        if not corner[i]:
            continue
        V = pts[i]
        Pp = pts[i - 1]
        Pn = pts[i + 1]
        in_x, in_y = Pp[0] - V[0], Pp[1] - V[1]
        out_x, out_y = Pn[0] - V[0], Pn[1] - V[1]
        d_in = math.hypot(in_x, in_y)
        d_out = math.hypot(out_x, out_y)
        r = min(radius, 0.5 * d_in, 0.5 * d_out)
        if r < 1e-6:
            A[i] = V
            B[i] = V
            corner[i] = False
            continue
        u_in = (in_x / d_in, in_y / d_in)
        u_out = (out_x / d_out, out_y / d_out)
        A[i] = (V[0] + u_in[0] * r, V[1] + u_in[1] * r)
        B[i] = (V[0] + u_out[0] * r, V[1] + u_out[1] * r)

    # Step 3: walk segments, emitting a straight cubic for each
    # (possibly truncated) segment plus a fillet cubic at each corner.
    out: list[tuple[float, float]] = [pts[0]]
    for i in range(n - 1):
        start = B[i] if corner[i] else pts[i]
        end = A[i + 1] if corner[i + 1] else pts[i + 1]
        # Straight cubic from start to end (chord/3 controls).
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if not out or out[-1] != start:
            # Carry the anchor forward if the bookkeeping drifted
            # (e.g. tiny numerical mismatch between last B[i] and
            # this iteration's start).
            out.append(start)
        out.append((start[0] + dx / 3, start[1] + dy / 3))
        out.append((start[0] + 2 * dx / 3, start[1] + 2 * dy / 3))
        out.append(end)
        # Fillet cubic at the corner at pts[i+1].
        if corner[i + 1]:
            V = pts[i + 1]
            out.append(V)
            out.append(V)
            out.append(B[i + 1])
    return out


def channel_route_edge(layout, le: "LayoutEdge",
                        tail: "LayoutNode",
                        head: "LayoutNode") -> list[tuple[float, float]]:
    """Unified cluster-aware router for regular and chain edges.

    Drop-in replacement for ``route_regular_edge`` (single-rank
    edges) and ``route_through_chain`` (multi-rank edges split by
    virtual nodes).  Internally:

    1. :func:`_edge_node_path` builds the ordered node sequence
       the edge traverses — ``[tail, head]`` for a regular edge,
       ``[tail, v1, ..., vn, head]`` for a chain edge.
    2. :func:`build_edge_path` turns that into a list of
       cluster-aware channel boxes (one per node), using
       :func:`_channel_bbox_for_node` which clips each box
       against foreign-cluster boundaries.
    3. :func:`route_through_channel_boxes` produces polyline
       waypoints — one per box (clamped to the box's cross-rank
       range) plus bridge waypoints when adjacent boxes have
       disjoint cross-rank ranges (an obstacle cluster sits
       between them).

    Step 6b also pre-applies corner-preserving Bezier smoothing via
    :func:`_bezier_split_at_corners` when the edge polyline has any
    sharp turns (typically from bridge waypoints).  This prevents
    :func:`to_bezier`'s Schneider fit from extrapolating control
    points through non-member clusters adjacent to the bridge.  The
    edge's ``spline_type`` is set to ``"bezier"`` so the global
    bezier pass in :func:`phase4_routing` leaves the curve alone.

    C analogue: ``lib/dotgen/dotsplines.c:make_regular_edge()``
    for multi-rank edges (with box list + channel routing) and
    the adjacent-rank path in the same function for single-rank
    edges.
    """
    path_names = _edge_node_path(layout, le)
    boxes = build_edge_path(layout, le)
    if not boxes:
        # Fallback: degenerate edge (no path).  Emit a straight
        # line from tail boundary to head boundary.
        p1 = layout._edge_start_point(le, tail, head)
        p2 = layout._edge_end_point(le, head, tail)
        return [p1, p2]
    polyline = route_through_channel_boxes(layout, le, path_names, boxes)

    # Step 6b finishing: pre-apply rounded-corner Bezier smoothing
    # when the splines mode would otherwise do a single-run bezier.
    # Only act when the polyline actually has a sharp turn — simple
    # regular edges stay on the global pipeline to keep behaviour
    # identical for the non-bridged path.
    #
    # The rounded-corner pass uses :func:`_rounded_corner_bezier`,
    # which replaces each hard turn with a cubic fillet so the
    # visible edge has smooth curves instead of 90° kinks.
    bezier_modes = ("", "spline", "curved", "true")
    if layout.splines in bezier_modes and len(polyline) >= 3:
        runs = _split_at_sharp_corners(polyline)
        if len(runs) > 1:
            le.points = _rounded_corner_bezier(polyline)
            le.spline_type = "bezier"
            return le.points
    return polyline


def rank_box(layout, r: int) -> tuple[float, float, float, float]:
    """Inter-rank corridor between rank r and rank r+1.

    Full graph width, from bottom of rank r nodes to top of rank r+1.
    Mirrors Graphviz ``dotsplines.c:rank_box()``.
    """
    # rank r nodes' Y center
    r_nodes = layout.ranks.get(r, [])
    r1_nodes = layout.ranks.get(r + 1, [])
    if r_nodes:
        r_y = layout.lnodes[r_nodes[0]].y
    else:
        r_y = r * layout.ranksep
    if r1_nodes:
        r1_y = layout.lnodes[r1_nodes[0]].y
    else:
        r1_y = (r + 1) * layout.ranksep

    top_y = r_y + layout._rank_ht1.get(r, 18)     # bottom edge of rank r
    bot_y = r1_y - layout._rank_ht2.get(r + 1, 18) # top edge of rank r+1

    return (layout._left_bound, top_y, layout._right_bound, bot_y)


def route_regular_edge(layout, le: LayoutEdge, tail: LayoutNode,
                         head: LayoutNode) -> list[tuple[float, float]]:
    """Route an edge between nodes on different ranks using corridor boxes.

    Builds a sequence of bounding boxes (tail node → inter-rank
    corridors → head node) and fits a cubic Bezier through the
    corridor center line.  Mirrors the box-corridor approach of
    Graphviz ``dotsplines.c:make_regular_edge()``.
    """
    p1 = layout._edge_start_point(le, tail, head)
    p2 = layout._edge_end_point(le, head, tail)

    rank_diff = abs(head.rank - tail.rank)
    is_lr = layout.rankdir in ("LR", "RL")

    # Compute the perpendicular extension distance for control points.
    # This makes the edge leave and enter the node at 90 degrees.
    if is_lr:
        gap = abs(p2[0] - p1[0])
    else:
        gap = abs(p2[1] - p1[1])
    ext = max(gap * 0.3, 20.0)  # at least 20pt extension

    if rank_diff <= 1:
        # Simple 4-point cubic Bezier with perpendicular tangents.
        le.spline_type = "bezier"
        if is_lr:
            # LR: edges flow left-to-right (increasing X).
            # Control points extend horizontally from each endpoint.
            return [
                p1,
                (p1[0] + ext, p1[1]),
                (p2[0] - ext, p2[1]),
                p2,
            ]
        else:
            # TB: edges flow top-to-bottom (increasing Y).
            # Control points extend vertically from each endpoint.
            return [
                p1,
                (p1[0], p1[1] + ext),
                (p2[0], p2[1] - ext),
                p2,
            ]

    # Multi-rank: build waypoints at inter-rank crossings,
    # then fit a Bezier through them.
    waypoints = [p1]
    lower_r = min(tail.rank, head.rank)
    upper_r = max(tail.rank, head.rank)

    for r in range(lower_r, upper_r):
        t = (r - lower_r + 0.5) / rank_diff
        if is_lr:
            ix = p1[0] + t * (p2[0] - p1[0])
            iy = p1[1] + t * (p2[1] - p1[1])
        else:
            ix = p1[0] + t * (p2[0] - p1[0])
            rbox = layout._rank_box(r)
            iy = (rbox[1] + rbox[3]) / 2.0
        waypoints.append((ix, iy))

    waypoints.append(p2)

    # For multi-rank, _to_bezier will convert to smooth cubics.
    # Override first and last control points for perpendicular entry/exit.
    if len(waypoints) >= 4:
        le.spline_type = "bezier"
        if is_lr:
            # Force perpendicular tangents at endpoints
            waypoints[1] = (p1[0] + ext, waypoints[1][1])
            waypoints[-2] = (p2[0] - ext, waypoints[-2][1])
        else:
            waypoints[1] = (waypoints[1][0], p1[1] + ext)
            waypoints[-2] = (waypoints[-2][0], p2[1] - ext)

    return waypoints


def classify_flat_edge(layout, le: LayoutEdge, tail: LayoutNode,
                        head: LayoutNode) -> str:
    """Classify a flat edge into a routing variant.

    Returns one of: 'adjacent', 'labeled', 'bottom', 'top' (default).
    Mirrors Graphviz ``dotsplines.c:make_flat_edge()`` dispatch.
    """
    is_adjacent = abs(tail.order - head.order) == 1

    if is_adjacent and not le.tailport and not le.headport:
        return "adjacent"

    if le.label and hasattr(le, '_flat_label_vnode'):
        return "labeled"

    # Check port sides for bottom routing
    for port in (le.tailport, le.headport):
        if port:
            compass = port.split(":")[-1] if ":" in port else port
            if compass in ("s", "sw", "se"):
                return "bottom"

    return "top"


def count_flat_edge_index(layout, le: LayoutEdge) -> int:
    """Count how many flat edges between the same pair come before this one.
    C analogue: lib/dotgen/dotsplines.c flat edge ordering. Returns the
    per-tail-node index of this flat edge among all flat edges from the
    same tail, used to compute a vertical offset so multiple flat edges
    from one node don't overlap.
    """
    idx = 0
    for other in layout.ledges:
        if other is le:
            return idx
        if other.virtual:
            continue
        t = layout.lnodes.get(other.tail_name)
        h = layout.lnodes.get(other.head_name)
        if t and h and t.rank == h.rank:
            if ((other.tail_name == le.tail_name and
                 other.head_name == le.head_name) or
                (other.tail_name == le.head_name and
                 other.head_name == le.tail_name)):
                idx += 1
    return idx


def flat_edge_route(layout, le: LayoutEdge, tail: LayoutNode,
                     head: LayoutNode) -> list[tuple[float, float]]:
    """Route a same-rank edge using the appropriate variant.

    Dispatches to one of four routing strategies matching Graphviz
    ``dotsplines.c:make_flat_edge()``:

    1. **adjacent** — straight bezier for nodes next to each other
    2. **labeled** — route through the label dummy node
    3. **bottom** — arc below the rank (south ports)
    4. **top** (default) — arc above the rank with multi-edge staggering
    """
    variant = layout._classify_flat_edge(le, tail, head)
    p1 = layout._edge_start_point(le, tail, head)
    p2 = layout._edge_end_point(le, head, tail)
    le.spline_type = "bezier"

    if variant == "adjacent":
        return layout._flat_adjacent(le, p1, p2, tail, head)
    elif variant == "labeled":
        return layout._flat_labeled(le, p1, p2, tail, head)
    elif variant == "bottom":
        return layout._flat_arc(le, p1, p2, tail, head, direction=1)
    else:  # "top"
        return layout._flat_arc(le, p1, p2, tail, head, direction=-1)


def flat_adjacent(layout, le: LayoutEdge, p1, p2,
                   tail: LayoutNode, head: LayoutNode):
    """Route a flat edge between adjacent nodes as a straight bezier.

    For multi-edges between the same pair, distributes y-offsets
    across the node height (Graphviz ``makeSimpleFlat``).
    """
    idx = layout._count_flat_edge_index(le)
    if idx == 0:
        # Single or first edge: straight line
        return [
            p1,
            ((2 * p1[0] + p2[0]) / 3, p1[1]),
            ((p1[0] + 2 * p2[0]) / 3, p2[1]),
            p2,
        ]
    # Multi-edge: offset y by distributing across node height
    max_h = min(tail.height, head.height) / 2
    dy = max_h * (idx / (idx + 1)) * (-1 if idx % 2 == 0 else 1)
    return [
        (p1[0], p1[1] + dy),
        ((2 * p1[0] + p2[0]) / 3, p1[1] + dy),
        ((p1[0] + 2 * p2[0]) / 3, p2[1] + dy),
        (p2[0], p2[1] + dy),
    ]


def flat_labeled(layout, le: LayoutEdge, p1, p2,
                  tail: LayoutNode, head: LayoutNode):
    """Route a flat edge through its label dummy node.

    The label node was inserted in the rank above by
    ``_insert_flat_label_nodes``.  The edge routes up to the label
    node's Y, across, and back down.
    
    C analogue: lib/dotgen/dotsplines.c flat edge with label. Routes a
    same-rank edge that has a label by computing a polyline that loops
    above (or below) the rank to give the label clearance.
    """
    vn_name = getattr(le, '_flat_label_vnode', None)
    if not vn_name or vn_name not in layout.lnodes:
        # Fallback to top arc
        return layout._flat_arc(le, p1, p2, tail, head, direction=-1)

    vn = layout.lnodes[vn_name]
    label_y = vn.y
    return [
        p1,
        (p1[0], label_y),
        (p2[0], label_y),
        p2,
    ]


def flat_arc(layout, le: LayoutEdge, p1, p2,
              tail: LayoutNode, head: LayoutNode,
              direction: int):
    """Route a flat edge as an arc above (direction=-1) or below (+1).

    Multi-edge staggering uses ``stepx`` and ``stepy`` proportional
    to ``Multisep`` (= nodesep) and available vertical space.
    Mirrors Graphviz 3-box corridor approach.
    """
    dx = abs(p2[0] - p1[0])
    r = tail.rank

    # Compute available vertical space to the adjacent rank
    if direction < 0:
        # Above: space to rank r-1
        prev_r = r - 1
        if prev_r in layout.ranks and layout.ranks[prev_r]:
            prev_y = layout.lnodes[layout.ranks[prev_r][0]].y
            vspace = abs(tail.y - prev_y) - layout._rank_ht1.get(prev_r, 18)
        else:
            vspace = layout.ranksep
    else:
        # Below: space to rank r+1
        next_r = r + 1
        if next_r in layout.ranks and layout.ranks[next_r]:
            next_y = layout.lnodes[layout.ranks[next_r][0]].y
            vspace = abs(next_y - tail.y) - layout._rank_ht2.get(next_r, 18)
        else:
            vspace = layout.ranksep

    vspace = max(vspace, 20.0)

    # Multi-edge staggering
    idx = layout._count_flat_edge_index(le)
    # Count total parallel flat edges for this pair
    total = idx + 1
    for other in layout.ledges:
        if other is le or other.virtual:
            continue
        if ((other.tail_name == le.tail_name and
             other.head_name == le.head_name) or
            (other.tail_name == le.head_name and
             other.head_name == le.tail_name)):
            ot = layout.lnodes.get(other.tail_name)
            oh = layout.lnodes.get(other.head_name)
            if ot and oh and ot.rank == oh.rank:
                total += 1

    multisep = layout.nodesep
    stepx = multisep / (total + 1)
    stepy = vspace / (total + 1)

    # Arc height based on index and available space
    arc_height = max(dx * 0.22, 20.0) + (idx + 1) * stepy
    arc_height = min(arc_height, vspace * 0.8)

    arc_y = p1[1] + direction * arc_height

    return [
        p1,
        (p1[0] + direction * (idx + 1) * stepx * 0.5, arc_y),
        (p2[0] - direction * (idx + 1) * stepx * 0.5, arc_y),
        p2,
    ]

