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

    # Log edge routing results
    all_routed = [le for le in layout.ledges if not le.virtual] + layout._chain_edges
    for le in all_routed:
        if le.points:
            pts_str = " ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in le.points[:4])
            print(f"[TRACE spline] edge {le.tail_name}->{le.head_name}: npts={len(le.points)} type={le.spline_type} pts={pts_str}{'...' if len(le.points)>4 else ''}", file=sys.stderr)


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
    # Look up port fraction from Node.record_fields (source of truth)
    port_name = port.split(":")[0] if ":" in port else port
    ln_obj = layout.lnodes.get(node_name)
    if not ln_obj or not ln_obj.node or ln_obj.node.record_fields is None:
        return None
    frac = ln_obj.node.record_fields.port_fraction(
        port_name, rankdir=layout._rankdir_int())
    if frac is None:
        return None

    if layout.rankdir in ("LR", "RL"):
        # LR/RL: port fraction → Y position, boundary on X
        y = ln.y - ln.height / 2.0 + frac * ln.height
        if is_tail:
            x = ln.x + ln.width / 2.0   # right edge (toward next rank)
        else:
            x = ln.x - ln.width / 2.0   # left edge (from prev rank)
    else:
        # TB/BT: port fraction → X position, boundary on Y
        x = ln.x - ln.width / 2.0 + frac * ln.width
        if is_tail:
            y = ln.y + ln.height / 2.0   # bottom edge (toward next rank)
        else:
            y = ln.y - ln.height / 2.0   # top edge (from prev rank)

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

