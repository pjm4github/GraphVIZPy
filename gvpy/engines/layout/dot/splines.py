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

from gvpy.engines.layout.dot.path import (
    Box,
    BWDEDGE,
    EDGETYPEMASK,
    FLATEDGE,
    FUDGE,
    FWDEDGE,
    GRAPHTYPEMASK,
    MINW,
    Port,
    REGULAREDGE,
    SELFNPEDGE,
    SELFWPEDGE,
    SplineInfo,
    edge_type_from_splines,
)
from gvpy.engines.layout.dot.trace import trace, trace_on

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import DotGraphInfo, LayoutEdge, LayoutNode


def phase4_routing(layout):
    """phase4_routing — top-level edge routing driver.

    C analogue: ``lib/dotgen/dotsplines.c:dot_splines_()`` lines 228–475.

    Driver shape mirrors C's ``dot_splines_``:

    1. Pre-compute per-rank obstacle bounds (`ht1`/`ht2`) and graph-
       wide `left_bound`/`right_bound` with per-rank MINW padding.
    2. Allocate :class:`SplineInfo` (``sd`` in C).
    3. Call :func:`resetRW` to restore pre-inflation ``rw`` on
       self-loop nodes (Phase A step 5; no-op under current data flow).
    4. Classify every real edge with :func:`setflags` tagging
       REGULAR / FLAT / SELFWP / SELFNP + FWD / BWD + MAINGRAPH, and
       sort with :func:`edgecmp` to group parallel edges into
       equivalence classes.  C analogue: the per-rank per-node loop
       at ``dotsplines.c:273-321`` plus ``LIST_SORT(&edges, edgecmp)``
       at ``dotsplines.c:331``.  Python does one pass over
       ``layout.ledges`` instead of the per-rank walk — the AGSEQ tie-
       break in ``edgecmp`` ensures the final sorted order is
       deterministic regardless of pre-sort iteration order.
    5. Dispatch each edge in sorted order to the appropriate per-edge
       router (regular polyline / flat / self-loop / ortho / line /
       channel).  Equivalence-class batching (multi-edge stagger) is
       still handled by the post-pass :func:`_apply_parallel_offsets`;
       true batch dispatch lands when Phase D ports ``make_regular_edge``.
    6. Route chain (multi-rank virtual) edges through their own
       separate loop — Python stores them in ``layout._chain_edges``
       rather than as virtual segments in ``ND_out``.
    7. Apply post-routing passes: samehead/sametail merge, compound
       edge clipping, bezier conversion, parallel-edge offsets.
    8. Call :func:`edge_normalize` to reverse any back-edge splines
       (Phase A step 5; no-op under current data flow because
       ``break_cycles`` in phase 1 pre-reverses back-edges).

    Phase A step 6 completed 2026-04-15: the driver shape now mirrors
    C's ``dot_splines_`` and the four Phase A helpers (``resetRW``,
    ``setflags``, ``edgecmp``, ``edge_normalize``) are wired into the
    live path.  Routing output is unchanged — the per-edge dispatch
    branches still call the existing Python routers.
    """
    # Emit the ``phase4 begin`` line in C's format: ``et=<int> normalize=<int>``.
    # C analogue: dotsplines.c:236.  ``et`` is the EDGE_TYPE enum value;
    # ``normalize`` is 1 unless we're being called recursively from
    # ``make_flat_adj_edges`` (which passes 0 to suppress the final
    # edge_normalize step).  Python has no recursive case today so it's
    # always 1.
    trace("spline",
          f"phase4 begin: et={edge_type_from_splines(layout.splines)} normalize=1")
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

    # Compute graph-wide left/right bounds with padding.
    # C analogue: the outer for loop in ``dot_splines_`` at
    # ``dotsplines.c:273-305``.  The ``-= MINW`` / ``+= MINW`` is
    # *inside* the rank loop in C, so it runs once per rank — a
    # graph with N ranks subtracts MINW from LeftBound N times.  The
    # per-rank ``MIN(sd.LeftBound, rank_min_x)`` ratchets the value
    # down monotonically.  Replicated literally here.
    left_bound = 0.0
    right_bound = 0.0
    if layout.ranks:
        for r in sorted(layout.ranks.keys()):
            rank_names = layout.ranks[r]
            if rank_names:
                first = layout.lnodes[rank_names[0]]
                left_bound = min(left_bound,
                                 first.x - first.width / 2.0)
                last = layout.lnodes[rank_names[-1]]
                right_bound = max(right_bound,
                                  last.x + last.width / 2.0)
            left_bound -= MINW
            right_bound += MINW
    else:
        left_bound = -float(MINW)
        right_bound = float(MINW)
    layout._left_bound = left_bound
    layout._right_bound = right_bound

    # Allocate the phase-4 routing context.  C analogue: the ``sd``
    # local in dot_splines_ at dotsplines.c:268-270.
    #
    # Match C integer truncation: ``GD_nodesep`` in
    # ``lib/common/types.h:334`` is declared ``int nodesep``, so
    # ``GD_nodesep(g) / 4`` is integer division.  A user-supplied
    # fractional ``nodesep`` (e.g. 18.5) is truncated to the floor
    # before the splinesep/multisep computation.
    nodesep_i = int(layout.nodesep)
    layout._spline_info = SplineInfo(
        left_bound=layout._left_bound,
        right_bound=layout._right_bound,
        splinesep=float(nodesep_i // 4),
        multisep=float(nodesep_i),
    )

    # Phase A step 5: restore pre-inflation rw on self-loop nodes.
    # C analogue: resetRW(g) call at dot_splines_() start.
    # No-op today (guarded on mval > 0); activates when Phase F lands.
    resetRW(layout)

    # Phase A step 6: classify all real edges with setflags + sort with
    # edgecmp to build the routing batch order.  C analogue: the per-
    # rank per-node loop at dotsplines.c:273-321 that gathers edges into
    # ``LIST(edge_t *) edges`` with setflags tagging, followed by
    # ``LIST_SORT(&edges, edgecmp)`` at dotsplines.c:331.
    #
    # Python iterates ``layout.ledges`` in insertion order instead of
    # the per-rank walk — AGSEQ (via _edge_seq_map) already preserves
    # creation order as the final edgecmp tie-break, so the sorted
    # output is deterministic regardless of pre-sort order.
    #
    # All real edges currently get MAINGRAPH — Python doesn't track
    # ND_flat_out / ND_other as separate lists yet.  Once those land
    # (Phase B or via a mincross classification pass), flat edges will
    # switch to AUXGRAPH with FLATEDGE hint and self-loops to AUXGRAPH
    # with no hint (matching C's setflags calls at dotsplines.c:298,
    # 303, 316).
    import functools as _ft
    layout._edge_seq_cache = None
    real_edges = [le for le in layout.ledges if not le.virtual]
    for le in real_edges:
        setflags(layout, le, 0, 0, 64)  # MAINGRAPH=64, auto-detect type/dir
    sorted_real_edges = sorted(
        real_edges,
        key=_ft.cmp_to_key(lambda a, b: edgecmp(layout, a, b)),
    )

    # Phase A step 6 diagnostic emissions — now always produce output
    # matching the sort above (previously the [TRACE spline] sweep did
    # its own classify+sort; now it just reports the live state).
    if trace_on("spline"):
        for le in sorted_real_edges:
            et_bits = le.tree_index & 15   # EDGETYPEMASK
            dir_bits = le.tree_index & 48  # FWDEDGE|BWDEDGE
            et_name = {1: "REGULAR", 2: "FLAT",
                       4: "SELFWP", 8: "SELFNP"}.get(et_bits, f"?{et_bits}")
            dir_name = "FWD" if (dir_bits & 16) else "BWD"
            trace("spline",
                  f"setflags: {le.tail_name}->{le.head_name} "
                  f"type={et_name} dir={dir_name} "
                  f"tree_index={le.tree_index}")
        order_str = " ".join(
            f"{le.tail_name}->{le.head_name}" for le in sorted_real_edges
        )
        trace("spline", f"edgecmp_sorted: [{order_str}]")

    # Diagnostic sweep for the cluster-aware bbox family (Phase A step 3).
    # ``maximal_bbox`` has no live caller on the Python side yet — the
    # existing route_regular_edge heuristic doesn't use it, and the
    # ported-C make_regular_edge lands in Phase D.  To give the
    # ``spline_path`` channel observable output for ``tools/diff_phases.py``,
    # walk every real node and call maximal_bbox with ``ie=oe=None``.
    # The equivalent C emission lives inside maximal_bbox itself, so on
    # the C side each (ie, oe) combination fires once per
    # make_regular_edge invocation — Python's sweep is one pass per node.
    # Expected divergence is documented in TODO_dot_splines_port.md.
    if trace_on("spline_path"):
        trace("spline_path",
              f"spline_info: left_bound={layout._left_bound:.1f} "
              f"right_bound={layout._right_bound:.1f} "
              f"splinesep={layout._spline_info.splinesep:.1f} "
              f"multisep={layout._spline_info.multisep:.1f}")
        for name in sorted(layout.lnodes.keys()):
            ln = layout.lnodes[name]
            if ln.virtual:
                continue
            box = maximal_bbox(layout, layout._spline_info, ln, None, None)
            trace("spline_path",
                  f"maximal_bbox: vn={name} "
                  f"ll=({box.ll_x:.1f},{box.ll_y:.1f}) "
                  f"ur=({box.ur_x:.1f},{box.ur_y:.1f})")

    # Route real edges in edgecmp-sorted order (Phase A step 6).
    # C analogue: the main routing loop at dotsplines.c:344-421 that
    # walks ``edges`` in sorted order and dispatches to
    # make_regular_edge / make_flat_edge / makeSelfEdge based on
    # tail/head rank + port status.
    from gvpy.engines.layout.dot.regular_edge import make_regular_edge
    from gvpy.engines.layout.dot.flat_edge import make_flat_edge
    from gvpy.engines.layout.dot.self_edge import make_self_edge
    from gvpy.engines.layout.dot.straight_edge import make_straight_edges
    from gvpy.engines.layout.dot.path import Path, EDGETYPE_SPLINE, EDGETYPE_LINE, EDGETYPE_CURVED

    et = edge_type_from_splines(layout.splines)
    P = Path()

    for le in sorted_real_edges:
        tail = layout.lnodes.get(le.tail_name)
        head = layout.lnodes.get(le.head_name)
        if tail is None or head is None:
            continue
        if le.tail_name == le.head_name:
            make_self_edge(layout, le, tail)
        elif tail.rank == head.rank and not le.virtual:
            make_flat_edge(layout, layout._spline_info, P, [le], et)
        elif layout.splines == "ortho":
            le.points = layout._ortho_route(le, tail, head)
        elif et in (EDGETYPE_LINE, EDGETYPE_CURVED):
            make_straight_edges(layout, [le], et)
        else:
            make_regular_edge(layout, layout._spline_info, P, [le], et)
        layout._compute_label_pos(le)

    # Route chain edges through virtual nodes.
    # C analogue: multi-rank edges are dispatched via make_regular_edge
    # with the original edge; the function walks the virtual chain
    # internally.
    for le in layout._chain_edges:
        tail = layout.lnodes.get(le.tail_name)
        head = layout.lnodes.get(le.head_name)
        if tail is None or head is None:
            continue
        if et in (EDGETYPE_LINE, EDGETYPE_CURVED):
            make_straight_edges(layout, [le], et)
        elif layout.splines == "ortho":
            le.points = layout._ortho_route(le, tail, head)
        else:
            make_regular_edge(layout, layout._spline_info, P, [le], et)
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

    # Phase A step 5: reverse back-edge spline control points so that
    # every emitted edge goes tail-to-head.  C analogue: edge_normalize
    # call at dot_splines_ line 434.  No-op under Python's current data
    # flow (break_cycles pre-reverses back-edges in phase 1); activates
    # when the driver stops pre-reversing.
    edge_normalize(layout)

    trace("spline", f"phase4 end: edges_routed={len(sorted_real_edges) + len(layout._chain_edges)}")

    # Per-edge routing detail goes on ``spline_detail`` rather than
    # ``spline`` — the top-level ``spline`` channel is reserved for
    # phase markers + classification so the diff harness can compare
    # driver shape against C without being swamped by control-point
    # dumps.
    if trace_on("spline_detail"):
        all_routed = sorted_real_edges + layout._chain_edges
        for le in all_routed:
            if le.points:
                pts_str = " ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in le.points[:4])
                trace("spline_detail", f"edge {le.tail_name}->{le.head_name}: npts={len(le.points)} type={le.spline_type} pts={pts_str}{'...' if len(le.points)>4 else ''}")


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

    The minimum routing separation is ``layout._routing_channel``
    (defaulting to ``_CL_OFFSET`` = 8pt).  This is the same settable
    knob the channel router uses for stub length, bridge column
    margin, and row-detour margin — changing it dials every routing
    clearance in one place.
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

    sep = float(getattr(layout, "_routing_channel",
                         getattr(layout, "_CL_OFFSET", 8.0)))

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
    """Set ``label_pos`` for the edge's main label.

    Delegates to :func:`label_place.place_vnlabel`, the F+.2 port of
    Graphviz's ``place_vnlabel()``.  Uses the length-parametric
    polyline midpoint (via ``edge_midpoint``) instead of the old
    naive index-based midpoint, so unequal-length segments pick a
    visually centered anchor.
    """
    from gvpy.engines.layout.dot.label_place import place_vnlabel
    place_vnlabel(None, le)


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


# ── Cluster-aware obstacle bbox family ──────────────────────────────────
# C analogues in lib/dotgen/dotsplines.c lines 2120–2294:
#   cl_vninside, cl_bound, maximal_bbox, neighbor, pathscross.
#
# These five static helpers form the obstacle-avoidance bbox set used
# by make_regular_edge to decide how much horizontal space an edge can
# claim on each rank while routing, accounting for:
#   - same-rank neighbours,
#   - non-member clusters the edge's path would otherwise cross,
#   - parallel-path neighbours whose chains would overlap.
# They are ported as one group because each depends on the others.
#
# None of them are wired into a live caller yet — they are prerequisites
# for the make_regular_edge port in Phase D.  They can be exercised
# directly from tests and from tools/diff_phases.py with GV_TRACE=spline_path.


def _node_out_edges(layout, ln: "LayoutNode") -> list["LayoutEdge"]:
    """Outgoing LayoutEdges of ``ln``.

    C analogue: ``ND_out(n).list``.  Walks ``layout.ledges`` +
    ``layout._chain_edges`` and filters by ``le.tail_name == ln.name``.
    Preserves Python iteration order, which is insertion order and
    therefore stable across calls.
    """
    name = ln.name
    out = [le for le in layout.ledges if le.tail_name == name]
    out.extend(le for le in layout._chain_edges if le.tail_name == name)
    return out


def _node_in_edges(layout, ln: "LayoutNode") -> list["LayoutEdge"]:
    """Incoming LayoutEdges of ``ln``.

    C analogue: ``ND_in(n).list``.
    """
    name = ln.name
    out = [le for le in layout.ledges if le.head_name == name]
    out.extend(le for le in layout._chain_edges if le.head_name == name)
    return out


def _clust(layout, ln: "LayoutNode"):
    """Return the innermost cluster containing ``ln``, or None.

    C analogue: ``ND_clust(n)`` followed by the ``REAL_CLUSTER(n)``
    macro which returns NULL when the cluster *is* the root graph.
    Python's :func:`_innermost_cluster` already returns None for
    root-level nodes, so this wrapper is just a rename for clarity
    at port call sites.
    """
    return _innermost_cluster(layout, ln.name)


def _virtual_orig_endpoints(layout, ln: "LayoutNode") -> "tuple[str, str] | None":
    """For a virtual node, return the original edge's ``(tail, head)``.

    C analogue: ``ED_to_orig(ND_out(n).list[0])`` followed by
    ``agtail(orig)`` / ``aghead(orig)`` at :func:`cl_bound` lines
    2142–2144.  Python chain virtuals carry ``orig_tail`` /
    ``orig_head`` on their LayoutEdge, so we pick the first outgoing
    edge and read those fields.  Returns None if ``ln`` has no
    outgoing edge or isn't part of a chain (e.g. skeleton virtual).
    """
    out = _node_out_edges(layout, ln)
    if not out:
        return None
    e = out[0]
    if e.orig_tail and e.orig_head:
        return (e.orig_tail, e.orig_head)
    return None


def cl_vninside(cl, ln: "LayoutNode") -> bool:
    """Return True if ``ln``'s center is inside ``cl``'s bounding box.

    C analogue: ``lib/dotgen/dotsplines.c:cl_vninside()`` lines 2120–2123::

        static bool cl_vninside(graph_t *cl, node_t *n) {
          return BETWEEN(GD_bb(cl).LL.x, ND_coord(n).x, GD_bb(cl).UR.x) &&
                 BETWEEN(GD_bb(cl).LL.y, ND_coord(n).y, GD_bb(cl).UR.y);
        }

    Pure containment test (closed interval).  Used by :func:`cl_bound`
    to verify that a virtual adjacent node is actually inside the
    candidate interfering cluster.
    """
    ll_x, ll_y, ur_x, ur_y = cl.bb
    return (ll_x <= ln.x <= ur_x) and (ll_y <= ln.y <= ur_y)


def cl_bound(layout, n_ln: "LayoutNode", adj_ln: "LayoutNode"):
    """Return the cluster of ``adj`` that interferes with ``n``'s routing.

    C analogue: ``lib/dotgen/dotsplines.c:cl_bound()`` lines 2134–2162.
    Walks ``n``'s tail/head-cluster context and returns the first
    cluster on ``adj`` that is not ``n``'s tail or head cluster,
    subject to a virtual-containment check via :func:`cl_vninside`.

    Returns None if ``adj`` is in the same cluster hierarchy as
    ``n``'s edge, or if ``adj`` is at the root level.
    """
    # Set up n's tail/head cluster context (C lines 2139–2145).
    if not n_ln.virtual:
        tcl = hcl = _clust(layout, n_ln)
    else:
        eps = _virtual_orig_endpoints(layout, n_ln)
        if eps is None:
            tcl = hcl = _clust(layout, n_ln)
        else:
            t_ln = layout.lnodes.get(eps[0])
            h_ln = layout.lnodes.get(eps[1])
            tcl = _clust(layout, t_ln) if t_ln is not None else None
            hcl = _clust(layout, h_ln) if h_ln is not None else None

    # Check adj's cluster membership (C lines 2146–2160).
    rv = None
    if not adj_ln.virtual:
        cl = _clust(layout, adj_ln)
        if cl is not None and cl is not tcl and cl is not hcl:
            rv = cl
    else:
        eps = _virtual_orig_endpoints(layout, adj_ln)
        if eps is not None:
            t_ln = layout.lnodes.get(eps[0])
            h_ln = layout.lnodes.get(eps[1])
            if t_ln is not None:
                cl = _clust(layout, t_ln)
                if (cl is not None and cl is not tcl and cl is not hcl
                        and cl_vninside(cl, adj_ln)):
                    rv = cl
            if rv is None and h_ln is not None:
                cl = _clust(layout, h_ln)
                if (cl is not None and cl is not tcl and cl is not hcl
                        and cl_vninside(cl, adj_ln)):
                    rv = cl
    return rv


def pathscross(layout, n0_ln: "LayoutNode", n1_ln: "LayoutNode",
                ie1: "LayoutEdge | None", oe1: "LayoutEdge | None") -> bool:
    """Return True if ``n0``'s chain crosses ``n1``'s chain.

    C analogue: ``lib/dotgen/dotsplines.c:pathscross()`` lines 2256–2294.
    Walks the forward and backward single-edge chains of ``n0`` (up to
    two hops each) and checks whether the relative order of ``n0`` and
    ``n1`` ever flips.  A flip means the chains would cross in
    cross-rank space, so ``n1`` is "on the same side of our path".

    Used by :func:`neighbor` to decide whether a virtual neighbour is
    a meaningful bbox stopper.
    """
    # C: ``order = ND_order(n0) > ND_order(n1);`` — bool stored as int.
    order = n0_ln.order > n1_ln.order
    n0_out_list = _node_out_edges(layout, n0_ln)
    n1_out_list = _node_out_edges(layout, n1_ln)
    if len(n0_out_list) != 1 and len(n1_out_list) != 1:
        return False

    # Forward walk (out-chain)
    e1 = oe1
    if len(n0_out_list) == 1 and e1 is not None:
        e0 = n0_out_list[0]
        for _ in range(2):
            na_name = e0.head_name
            nb_name = e1.head_name
            if na_name == nb_name:
                break
            na = layout.lnodes.get(na_name)
            nb = layout.lnodes.get(nb_name)
            if na is None or nb is None:
                break
            if order != (na.order > nb.order):
                return True
            na_out = _node_out_edges(layout, na)
            if len(na_out) != 1 or not na.virtual:
                break
            e0 = na_out[0]
            nb_out = _node_out_edges(layout, nb)
            if len(nb_out) != 1 or not nb.virtual:
                break
            e1 = nb_out[0]

    # Backward walk (in-chain)
    n0_in_list = _node_in_edges(layout, n0_ln)
    e1 = ie1
    if len(n0_in_list) == 1 and e1 is not None:
        e0 = n0_in_list[0]
        for _ in range(2):
            na_name = e0.tail_name
            nb_name = e1.tail_name
            if na_name == nb_name:
                break
            na = layout.lnodes.get(na_name)
            nb = layout.lnodes.get(nb_name)
            if na is None or nb is None:
                break
            if order != (na.order > nb.order):
                return True
            na_in = _node_in_edges(layout, na)
            if len(na_in) != 1 or not na.virtual:
                break
            e0 = na_in[0]
            nb_in = _node_in_edges(layout, nb)
            if len(nb_in) != 1 or not nb.virtual:
                break
            e1 = nb_in[0]

    return False


def neighbor(layout, vn_ln: "LayoutNode",
              ie: "LayoutEdge | None", oe: "LayoutEdge | None",
              direction: int) -> "LayoutNode | None":
    """Find the nearest rank neighbour that bounds ``vn``'s bbox.

    C analogue: ``lib/dotgen/dotsplines.c:neighbor()`` lines 2232–2254.
    Walks the rank outward from ``vn`` in ``direction`` (+1 right,
    -1 left) and returns the first node that (a) is NORMAL, (b) is a
    virtual with a label, or (c) is a virtual whose chain does not
    cross ``vn``'s chain per :func:`pathscross`.

    ``ie`` and ``oe`` are the in- and out-edges of the currently
    routing edge.  They travel through :func:`pathscross` unchanged.

    Python divergence: ``ND_label(n)`` is not tracked on the dot
    ``LayoutNode`` today, so the "virtual with label" branch is
    skipped — only the NORMAL and ``pathscross`` branches fire.
    Flat-edge label virtuals will need a :class:`LayoutNode` label
    field in a future port pass.
    """
    rank_names = layout.ranks.get(vn_ln.rank, [])
    n_in_rank = len(rank_names)
    i = vn_ln.order + direction
    while 0 <= i < n_in_rank:
        n = layout.lnodes.get(rank_names[i])
        if n is None:
            i += direction
            continue
        # C: ``if (ND_node_type(n) == VIRTUAL && ND_label(n)) break;``
        # — omitted (see docstring).
        if not n.virtual:
            return n
        if not pathscross(layout, n, vn_ln, ie, oe):
            return n
        i += direction
    return None


def maximal_bbox(layout, sp: SplineInfo, vn_ln: "LayoutNode",
                  ie: "LayoutEdge | None", oe: "LayoutEdge | None") -> Box:
    """Compute the maximum bbox ``vn`` can claim on its rank for routing.

    C analogue: ``lib/dotgen/dotsplines.c:maximal_bbox()`` lines 2173–2230.
    C literal::

        static boxf maximal_bbox(graph_t *g, const spline_info_t sp,
                                 node_t *vn, edge_t *ie, edge_t *oe) {
          double b, nb;
          graph_t *left_cl, *right_cl;
          node_t *left, *right;
          boxf rv;

          left_cl = right_cl = NULL;
          b = (double)(ND_coord(vn).x - ND_lw(vn) - FUDGE);
          if ((left = neighbor(g, vn, ie, oe, -1))) {
            if ((left_cl = cl_bound(g, vn, left)))
              nb = GD_bb(left_cl).UR.x + sp.Splinesep;
            else {
              nb = (double)(ND_coord(left).x + ND_mval(left));
              if (ND_node_type(left) == NORMAL)
                nb += GD_nodesep(g) / 2.;
              else
                nb += sp.Splinesep;
            }
            if (nb < b) b = nb;
            rv.LL.x = round(b);
          } else
            rv.LL.x = fmin(round(b), sp.LeftBound);
          ...
          rv.LL.y = ND_coord(vn).y - GD_rank(g)[ND_rank(vn)].ht1;
          rv.UR.y = ND_coord(vn).y + GD_rank(g)[ND_rank(vn)].ht2;
          return rv;
        }

    Y-axis: C y-up has ``LL.y = vn.y - ht1`` (visual bottom) and
    ``UR.y = vn.y + ht2`` (visual top).  Python y-down flips both
    terms so ``ll_y < ur_y`` still holds::

        ll_y (smaller y, visual top    ) = vn.y - ht2
        ur_y (larger  y, visual bottom ) = vn.y + ht1

    Python divergences (documented, to be revisited):
    - ``ND_label(vn)`` is not tracked on Python :class:`LayoutNode`,
      so the two "virtual with label" branches (leaves 10pt on the
      right side, then shrinks ``UR.x`` after the fact) are elided.
    - ``ND_mval(left)`` is approximated as ``left.width / 2`` (right
      half-width), ignoring self-loop inflation.  Becomes accurate
      once :func:`makeSelfEdge` lands in Phase F.
    """
    # ── X extent, left side ─────────────────────────────────────────
    b = float(vn_ln.x - vn_ln.width / 2.0 - FUDGE)
    left = neighbor(layout, vn_ln, ie, oe, -1)
    if left is not None:
        left_cl = cl_bound(layout, vn_ln, left)
        if left_cl is not None:
            nb = left_cl.bb[2] + sp.splinesep  # bb.UR.x + Splinesep
        else:
            nb = float(left.x + left.width / 2.0)  # approx ND_mval(left)
            if not left.virtual:
                nb += layout.nodesep / 2.0
            else:
                nb += sp.splinesep
        if nb < b:
            b = nb
        ll_x = float(round(b))
    else:
        ll_x = min(float(round(b)), sp.left_bound)

    # ── X extent, right side ────────────────────────────────────────
    # C's ``virtual with label`` branch is elided (see docstring).
    b = float(vn_ln.x + vn_ln.width / 2.0 + FUDGE)
    right = neighbor(layout, vn_ln, ie, oe, 1)
    if right is not None:
        right_cl = cl_bound(layout, vn_ln, right)
        if right_cl is not None:
            nb = right_cl.bb[0] - sp.splinesep  # bb.LL.x - Splinesep
        else:
            nb = float(right.x - right.width / 2.0)
            if not right.virtual:
                nb -= layout.nodesep / 2.0
            else:
                nb -= sp.splinesep
        if nb > b:
            b = nb
        ur_x = float(round(b))
    else:
        ur_x = max(float(round(b)), sp.right_bound)

    # ── Y extent, y-down flip of C's ht1/ht2 ────────────────────────
    fallback_hh = vn_ln.height / 2.0
    ll_y = vn_ln.y - layout._rank_ht2.get(vn_ln.rank, fallback_hh)
    ur_y = vn_ln.y + layout._rank_ht1.get(vn_ln.rank, fallback_hh)

    return Box(ll_x=ll_x, ll_y=ll_y, ur_x=ur_x, ur_y=ur_y)


# ── Edge classification and driver sort (Phase A step 4) ────────────────
# C analogues in lib/dotgen/dotsplines.c:
#   makefwdedge       lines 48–63
#   getmainedge       lines 100–107
#   spline_merge      lines 109–112
#   swap_ends_p       lines 114–124
#   portcmp           lines 129–143
#   setflags          lines 507–533
#   edgecmp           lines 545–636
#
# Together these seven helpers form the equivalence-class grouping
# infrastructure used by ``dot_splines_`` to batch parallel edges
# before routing.  Landing this group is the last Phase A prerequisite
# before the Phase D ``make_regular_edge`` port can start.
#
# None of them are wired into the live driver yet — they are exercised
# by a gated sweep in ``phase4_routing`` under ``GV_TRACE=spline``.


def _get_edge_port(le: "LayoutEdge", side: str) -> Port:
    """Build a :class:`Port` from ``le.tailport`` or ``le.headport``.

    ``side`` is ``"tail"`` or ``"head"``.  An empty port string yields
    an **undefined** port at the origin — matching C's zero-initialised
    ``port`` struct when no explicit port was given.  A non-empty port
    string yields a **defined** port whose aiming point ``p`` is
    currently ``(0, 0)`` — a placeholder until the record-port /
    compass-direction aiming-point computation lands alongside the
    ``beginpath`` / ``endpath`` port ports in Phase B.

    For now this placeholder is sufficient for :func:`portcmp` to
    correctly group edges that all share undefined ports (the
    overwhelming common case), and to separate defined-port edges
    from undefined-port edges.  Edges with different compass ports
    will group together when they shouldn't until the aiming point
    is real — documented divergence.
    """
    port_str = le.tailport if side == "tail" else le.headport
    if not port_str:
        return Port(defined=False, p=(0.0, 0.0))
    return Port(defined=True, p=(0.0, 0.0))


def portcmp(p0: Port, p1: Port) -> int:
    """Lexicographic comparison of two :class:`Port` structs.

    C analogue: ``lib/dotgen/dotsplines.c:portcmp()`` lines 129–143.
    C literal::

        int portcmp(port p0, port p1) {
          if (!p1.defined) return p0.defined ? 1 : 0;
          if (!p0.defined) return -1;
          if (p0.p.x < p1.p.x) return -1;
          if (p0.p.x > p1.p.x) return 1;
          if (p0.p.y < p1.p.y) return -1;
          if (p0.p.y > p1.p.y) return 1;
          return 0;
        }

    Order: undefined < defined; within defined, by aiming-point x, then y.
    """
    if not p1.defined:
        return 1 if p0.defined else 0
    if not p0.defined:
        return -1
    if p0.p[0] < p1.p[0]:
        return -1
    if p0.p[0] > p1.p[0]:
        return 1
    if p0.p[1] < p1.p[1]:
        return -1
    if p0.p[1] > p1.p[1]:
        return 1
    return 0


def getmainedge(layout, le: "LayoutEdge") -> "LayoutEdge":
    """Walk to the canonical edge backing ``le``.

    C analogue: ``lib/dotgen/dotsplines.c:getmainedge()`` lines 100–107.
    C literal::

        static edge_t *getmainedge(edge_t *e) {
          edge_t *le = e;
          while (ED_to_virt(le)) le = ED_to_virt(le);
          while (ED_to_orig(le)) le = ED_to_orig(le);
          return le;
        }

    C walks forward through the virtual chain (``ED_to_virt``), then
    backward to the original real edge (``ED_to_orig``).  Python
    chain virtuals have ``orig_tail`` / ``orig_head`` naming the
    original real edge's endpoints; we look up the real
    :class:`LayoutEdge` by those names.  Non-chain virtuals (e.g.
    cluster skeleton edges) have no ``orig_tail`` so return self.
    """
    if le.orig_tail and le.orig_head:
        for real in layout.ledges:
            if (not real.virtual
                    and real.tail_name == le.orig_tail
                    and real.head_name == le.orig_head):
                return real
    return le


def spline_merge(layout, ln: "LayoutNode") -> bool:
    """Return True iff ``ln`` is a virtual node that merges multiple edges.

    C analogue: ``lib/dotgen/dotsplines.c:spline_merge()`` lines 109–112::

        static bool spline_merge(node_t *n) {
          return ND_node_type(n) == VIRTUAL &&
                 (ND_in(n).size > 1 || ND_out(n).size > 1);
        }

    Used by the driver to detect merged virtuals that need special
    spline handling (they carry more than one edge and therefore
    cannot be simply spanned by a single cubic segment).
    """
    if not ln.virtual:
        return False
    return len(_node_in_edges(layout, ln)) > 1 or len(_node_out_edges(layout, ln)) > 1


def swap_ends_p(layout, le: "LayoutEdge") -> bool:
    """Return True iff ``le``'s control points should be reversed.

    C analogue: ``lib/dotgen/dotsplines.c:swap_ends_p()`` lines 114–124::

        static bool swap_ends_p(edge_t *e) {
          while (ED_to_orig(e)) e = ED_to_orig(e);
          if (ND_rank(aghead(e)) > ND_rank(agtail(e))) return false;
          if (ND_rank(aghead(e)) < ND_rank(agtail(e))) return true;
          if (ND_order(aghead(e)) >= ND_order(agtail(e))) return false;
          return true;
        }

    Walks back to the canonical edge, then decides: normally emitted
    tail-to-head, unless the edge is a back-edge that was reversed
    during ranking — then the stored control points need to be
    reversed at the output stage.
    """
    main = getmainedge(layout, le)
    tail = layout.lnodes.get(main.tail_name)
    head = layout.lnodes.get(main.head_name)
    if tail is None or head is None:
        return False
    if head.rank > tail.rank:
        return False
    if head.rank < tail.rank:
        return True
    if head.order >= tail.order:
        return False
    return True


def makefwdedge(old: "LayoutEdge") -> "LayoutEdge":
    """Return a forward-direction shallow copy of a back-edge.

    C analogue: ``lib/dotgen/dotsplines.c:makefwdedge()`` lines 48–63.
    C constructs a temporary ``edge_t`` on the caller's stack whose
    tail/head and tail_port/head_port are swapped relative to ``old``,
    ``edge_type`` is set to ``VIRTUAL``, and ``to_orig`` points back
    at ``old``.  Python returns a fresh :class:`LayoutEdge`; the
    caller is responsible for discarding it after use (the new edge
    is **not** appended to any list).

    Used by ``edgecmp`` and ``make_regular_edge`` whenever the driver
    needs to treat a back-edge as if it ran forward for purposes of
    port comparison and box-corridor construction.
    """
    # Late import to avoid a circular reference at module load time.
    from gvpy.engines.layout.dot.dot_layout import LayoutEdge

    fwd = LayoutEdge(
        edge=old.edge,
        tail_name=old.head_name,  # swapped
        head_name=old.tail_name,  # swapped
        minlen=old.minlen,
        weight=old.weight,
        reversed=old.reversed,
        virtual=True,             # C: ED_edge_type(new) = VIRTUAL
        orig_tail=old.tail_name,  # remember the original direction
        orig_head=old.head_name,
        constraint=old.constraint,
        label=old.label,
        tailport=old.headport,    # swapped
        headport=old.tailport,    # swapped
        lhead=old.ltail,          # swapped
        ltail=old.lhead,
        headclip=old.tailclip,
        tailclip=old.headclip,
        samehead=old.sametail,
        sametail=old.samehead,
        edge_type=old.edge_type,
        tree_index=old.tree_index,
    )
    return fwd


def setflags(layout, le: "LayoutEdge",
             hint1: int, hint2: int, f3: int) -> None:
    """Populate ``le.tree_index`` with edge-type + direction + graph bits.

    C analogue: ``lib/dotgen/dotsplines.c:setflags()`` lines 507–533.
    C literal::

        static void setflags(edge_t *e, int hint1, int hint2, int f3) {
          int f1, f2;
          if (hint1 != 0) f1 = hint1;
          else {
            if (agtail(e) == aghead(e))
              if (ED_tail_port(e).defined || ED_head_port(e).defined)
                f1 = SELFWPEDGE;
              else
                f1 = SELFNPEDGE;
            else if (ND_rank(agtail(e)) == ND_rank(aghead(e)))
              f1 = FLATEDGE;
            else
              f1 = REGULAREDGE;
          }
          if (hint2 != 0) f2 = hint2;
          else {
            if (f1 == REGULAREDGE)
              f2 = ND_rank(agtail(e)) < ND_rank(aghead(e)) ? FWDEDGE : BWDEDGE;
            else if (f1 == FLATEDGE)
              f2 = ND_order(agtail(e)) < ND_order(aghead(e)) ? FWDEDGE : BWDEDGE;
            else  /* f1 == SELF*EDGE */
              f2 = FWDEDGE;
          }
          ED_tree_index(e) = f1 | f2 | f3;
        }

    Pass ``0`` for ``hint1`` / ``hint2`` to auto-detect edge type and
    direction from the tail/head rank and order.
    """
    # f1: edge type bits (bits 0-3)
    if hint1 != 0:
        f1 = hint1
    else:
        if le.tail_name == le.head_name:
            if le.tailport or le.headport:
                f1 = SELFWPEDGE
            else:
                f1 = SELFNPEDGE
        else:
            tail = layout.lnodes.get(le.tail_name)
            head = layout.lnodes.get(le.head_name)
            if tail is not None and head is not None and tail.rank == head.rank:
                f1 = FLATEDGE
            else:
                f1 = REGULAREDGE

    # f2: direction bits (bits 4-5)
    if hint2 != 0:
        f2 = hint2
    else:
        tail = layout.lnodes.get(le.tail_name)
        head = layout.lnodes.get(le.head_name)
        if f1 == REGULAREDGE:
            if tail is not None and head is not None and tail.rank < head.rank:
                f2 = FWDEDGE
            else:
                f2 = BWDEDGE
        elif f1 == FLATEDGE:
            if tail is not None and head is not None and tail.order < head.order:
                f2 = FWDEDGE
            else:
                f2 = BWDEDGE
        else:  # self-loop variants
            f2 = FWDEDGE

    le.tree_index = f1 | f2 | f3


def _edge_seq_map(layout) -> dict:
    """Return a cached ``id(le) -> int`` map giving each edge a stable seq.

    C analogue: ``AGSEQ(e)`` — the cgraph sequence number assigned at
    edge creation time.  Python doesn't have a built-in edge sequence,
    so we cache the index of each edge in ``layout.ledges`` +
    ``layout._chain_edges`` on first access within a phase 4 pass.
    The cache is cleared by :func:`phase4_routing` at the start of
    every pass via ``layout._edge_seq_cache = None``.
    """
    seq = getattr(layout, "_edge_seq_cache", None)
    if seq is not None:
        return seq
    seq = {}
    n = 0
    for le in layout.ledges:
        seq[id(le)] = n
        n += 1
    for le in layout._chain_edges:
        seq[id(le)] = n
        n += 1
    layout._edge_seq_cache = seq
    return seq


def edgecmp(layout, e0: "LayoutEdge", e1: "LayoutEdge") -> int:
    """Lexicographic comparator used to group equivalent edges.

    C analogue: ``lib/dotgen/dotsplines.c:edgecmp()`` lines 545–636.
    Lex order documented in C:
      1. edge type        — NOTE: C returns inverted (``et0 < et1`` → 1)
                            so higher-numbered edge types sort first.
      2. |rank difference of main edge's endpoints|
      3. |x difference of main edge's endpoints|
      4. AGSEQ of main edge (cheap test for "same endpoints")
      5. tail port (after optional makefwdedge swap on BWDEDGE)
      6. head port (same)
      7. graph type (MAINGRAPH vs AUXGRAPH, via GRAPHTYPEMASK)
      8. label pointer comparison (only for FLATEDGE, used as a
         stable group-by-label tiebreak)
      9. AGSEQ of the edge itself

    Callers that need it for ``sorted()`` should wrap with
    ``functools.cmp_to_key(lambda a, b: edgecmp(layout, a, b))``.
    """
    # Step 1: edge type (inverted comparison, per C)
    et0 = e0.tree_index & EDGETYPEMASK
    et1 = e1.tree_index & EDGETYPEMASK
    if et0 < et1:
        return 1
    if et0 > et1:
        return -1

    # Resolve the main (original real) edge for each side.
    le0 = getmainedge(layout, e0)
    le1 = getmainedge(layout, e1)

    # Step 2: absolute rank difference of the main edges.
    tail0 = layout.lnodes.get(le0.tail_name)
    head0 = layout.lnodes.get(le0.head_name)
    tail1 = layout.lnodes.get(le1.tail_name)
    head1 = layout.lnodes.get(le1.head_name)
    if tail0 is not None and head0 is not None and tail1 is not None and head1 is not None:
        rd0 = abs(tail0.rank - head0.rank)
        rd1 = abs(tail1.rank - head1.rank)
        if rd0 < rd1:
            return -1
        if rd0 > rd1:
            return 1

        # Step 3: absolute x difference of the main edges.
        xd0 = abs(tail0.x - head0.x)
        xd1 = abs(tail1.x - head1.x)
        if xd0 < xd1:
            return -1
        if xd0 > xd1:
            return 1

    # Step 4: AGSEQ of the main edge — cheap "same endpoints" test.
    seq = _edge_seq_map(layout)
    seq_le0 = seq.get(id(le0), -1)
    seq_le1 = seq.get(id(le1), -1)
    if seq_le0 < seq_le1:
        return -1
    if seq_le0 > seq_le1:
        return 1

    # Step 5 + 6: port comparison, with optional makefwdedge for back-edges.
    # C chooses between ``e0`` itself (if it has a defined port) or
    # ``le0`` (the main edge) — Python mirrors the same decision.
    ea = e0 if (e0.tailport or e0.headport) else le0
    if ea.tree_index & BWDEDGE:
        ea = makefwdedge(ea)
    eb = e1 if (e1.tailport or e1.headport) else le1
    if eb.tree_index & BWDEDGE:
        eb = makefwdedge(eb)
    rv = portcmp(_get_edge_port(ea, "tail"), _get_edge_port(eb, "tail"))
    if rv:
        return rv
    rv = portcmp(_get_edge_port(ea, "head"), _get_edge_port(eb, "head"))
    if rv:
        return rv

    # Step 7: graph type (MAINGRAPH vs AUXGRAPH).
    # Note C reuses ``et0``/``et1`` here; we recompute to stay explicit.
    gt0 = e0.tree_index & GRAPHTYPEMASK
    gt1 = e1.tree_index & GRAPHTYPEMASK
    if gt0 < gt1:
        return -1
    if gt0 > gt1:
        return 1

    # Step 8: label comparison (FLATEDGE only).
    # C tests ``et0 == FLATEDGE`` using the recomputed ``et0``, which at
    # that point holds ``gt0`` — that's a known quirk of the C source;
    # we faithfully reproduce it rather than "fixing" it, since changing
    # the order would desynchronise from C's sort.
    if gt0 == FLATEDGE:
        lbl0 = e0.label or ""
        lbl1 = e1.label or ""
        if lbl0 < lbl1:
            return -1
        if lbl0 > lbl1:
            return 1

    # Step 9: final AGSEQ tiebreak (on the original edges, not le0/le1).
    seq_e0 = seq.get(id(e0), -1)
    seq_e1 = seq.get(id(e1), -1)
    if seq_e0 < seq_e1:
        return -1
    if seq_e0 > seq_e1:
        return 1
    return 0


# ── Back-edge control-point normalisation (Phase A step 5) ──────────────
# C analogues in lib/dotgen/dotsplines.c:
#   swap_bezier      lines 145-153
#   swap_spline      lines 155-167
#   edge_normalize   lines 174-181
#   resetRW          lines 188-194
#
# These four functions cooperate to (a) reverse the control points of
# back-edges so that the emitted spline always runs tail-to-head, and
# (b) restore node rw values that were inflated during position for
# self-loops.  They are called once at the very end of
# ``dot_splines_`` (edge_normalize) and once near the top (resetRW).
#
# Python single-bezier note: :class:`EdgeRoute` currently holds exactly
# one bezier per edge, so ``swap_spline`` collapses into a single
# ``swap_bezier`` call.  The two functions remain distinct for naming
# symmetry with C — when compound-edge routing lands (Phase E) and
# ``EdgeRoute`` gains a ``beziers: list[Bezier]`` field, ``swap_spline``
# will start reversing a real list.


def swap_bezier(route: "EdgeRoute") -> None:
    """Reverse a bezier's points and swap its start/end metadata in place.

    C analogue: ``lib/dotgen/dotsplines.c:swap_bezier()`` lines 145-153::

        static void swap_bezier(bezier *b) {
          const size_t sz = b->size;
          for (size_t i = 0; i < sz / 2; ++i)
            SWAP(&b->list[i], &b->list[sz - 1 - i]);
          SWAP(&b->sflag, &b->eflag);
          SWAP(&b->sp, &b->ep);
        }

    Operates on an :class:`EdgeRoute` since Python currently has one
    bezier per edge.  Mutates ``points``, swaps ``sflag`` ↔ ``eflag``,
    swaps ``sp`` ↔ ``ep``.
    """
    route.points.reverse()
    route.sflag, route.eflag = route.eflag, route.sflag
    route.sp, route.ep = route.ep, route.sp


def swap_spline(route: "EdgeRoute") -> None:
    """Reverse a splines container and each bezier inside it.

    C analogue: ``lib/dotgen/dotsplines.c:swap_spline()`` lines 155-167::

        static void swap_spline(splines *s) {
          const size_t sz = s->size;
          for (size_t i = 0; i < sz / 2; ++i)
            SWAP(&s->list[i], &s->list[sz - 1 - i]);
          for (size_t i = 0; i < sz; ++i)
            swap_bezier(&s->list[i]);
        }

    For Python's one-bezier-per-edge model this collapses into a
    single :func:`swap_bezier` call — the outer list has exactly one
    element so the reverse loop is a no-op.
    """
    # Outer list reverse: degenerate for a single-element list.
    # Each bezier swap: one call.
    swap_bezier(route)


def edge_normalize(layout) -> None:
    """Reverse control points of back-edges so output goes tail-to-head.

    C analogue: ``lib/dotgen/dotsplines.c:edge_normalize()`` lines 174-181::

        static void edge_normalize(graph_t *g) {
          for (node_t *n = agfstnode(g); n; n = agnxtnode(g, n)) {
            for (edge_t *e = agfstout(g, n); e; e = agnxtout(g, e)) {
              if (sinfo.swapEnds(e) && ED_spl(e))
                swap_spline(ED_spl(e));
            }
          }
        }

    Called once at the end of ``dot_splines_`` as the final output
    normalisation pass.  Iterates every edge, checks
    :func:`swap_ends_p`, and reverses the spline if needed.

    Python note: the current driver physically reverses back-edges in
    ``break_cycles`` (phase 1), so by the time this runs every edge's
    tail/head already points forward and :func:`swap_ends_p` returns
    False.  The function is effectively a no-op under the current
    data flow, but the walk is here so the Phase A step 6 driver
    rewrite has a ready hook — once that rewrite stops pre-reversing
    back-edges, this function will start actually swapping.
    """
    for le in layout.ledges:
        if not le.route.points:
            continue
        if swap_ends_p(layout, le):
            swap_spline(le.route)
    for le in layout._chain_edges:
        if not le.route.points:
            continue
        if swap_ends_p(layout, le):
            swap_spline(le.route)


def resetRW(layout) -> None:
    """Restore each node's pre-inflation right half-width.

    C analogue: ``lib/dotgen/dotsplines.c:resetRW()`` lines 188-194::

        static void resetRW(graph_t *g) {
          for (node_t *n = agfstnode(g); n; n = agnxtnode(g, n)) {
            if (ND_other(n).list) {
              SWAP(&ND_rw(n), &ND_mval(n));
            }
          }
        }

    C uses ``ND_other(n).list`` as the "has at least one self-loop or
    multi-edge" predicate: if present, the position phase inflated
    ``ND_rw`` (pushing the right neighbour further away to make room
    for the loop) and stashed the original value in ``ND_mval``.
    resetRW swaps them back so splines routing sees the un-inflated rw.

    Python no-op for now: the position phase doesn't inflate rw for
    self-loops yet (Phase F territory).  ``LayoutNode.mval`` defaults
    to 0.0, meaning "no stashed original value".  When self-loop
    inflation lands, this shell becomes active without further
    changes — the body is a literal port of C, the math just happens
    to swap two equal values today.
    """
    for ln in layout.lnodes.values():
        # C: ``if (ND_other(n).list)`` — has at least one self-loop.
        # Python equivalent: any edge with tail == head == this node.
        has_selfloop = any(
            le.tail_name == ln.name and le.head_name == ln.name
            for le in layout.ledges
        )
        if not has_selfloop:
            continue
        # C: SWAP(&ND_rw(n), &ND_mval(n)).  C relies on position.c
        # having stashed the pre-inflation rw in mval; swapping is
        # safe because both values are non-zero.  Python's position
        # phase doesn't inflate rw for self-loops yet (Phase F), so
        # mval defaults to 0.0 — swapping unguarded would zero the
        # width.  Gate on ``mval > 0`` as a Python-specific safety
        # check; becomes a pure swap once Phase F populates mval.
        if ln.mval > 0.0:
            old_rw = ln.width / 2.0
            ln.width = ln.mval * 2.0
            ln.mval = old_rw


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


def _row_crossings(layout, p1, p2, skip_names: set[str]) -> list:
    """Return real nodes whose bbox the segment *passes through*.

    A node counts as a crossing when **both** endpoints of the
    segment lie strictly outside the node's bbox and the segment
    still enters the bbox.  If either endpoint is inside the bbox
    the segment is merely *touching* the node at an attach point
    (e.g. a stub segment whose near-end sits just past the face)
    and is not counted — we don't want to route around a node we
    legitimately connect to.

    ``skip_names`` still applies — e.g. the segment's own virtual-
    node endpoints are excluded so they can be touched at either
    end.  But the edge's tail and head are no longer
    unconditionally skipped: if a bridge leg runs straight through
    the head's interior to reach a stub on the far side, that's
    a through-crossing and must be detoured around.
    """
    crossing: list = []
    for node_name, ln in layout.lnodes.items():
        if ln.virtual:
            continue
        if node_name in skip_names:
            continue
        bb = (ln.x - ln.width / 2.0, ln.y - ln.height / 2.0,
              ln.x + ln.width / 2.0, ln.y + ln.height / 2.0)
        # Skip nodes whose bbox *contains* either endpoint — those
        # are legitimate attach points, not obstacles.
        p1_inside = (bb[0] <= p1[0] <= bb[2]
                     and bb[1] <= p1[1] <= bb[3])
        p2_inside = (bb[0] <= p2[0] <= bb[2]
                     and bb[1] <= p2[1] <= bb[3])
        if p1_inside or p2_inside:
            continue
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
                        tcl, hcl, skip_names: set[str] | None = None) -> list:
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
    margin = float(getattr(layout, "_routing_channel",
                            getattr(layout, "_CL_OFFSET", 8.0)))
    skip = set(skip_names) if skip_names else set()

    top_crossing = _row_crossings(layout, waypt_i, b1, skip)
    mid_crossing = _row_crossings(layout, b1, b2, skip)
    bot_crossing = _row_crossings(layout, b2, waypt_j, skip)
    if not top_crossing and not mid_crossing and not bot_crossing:
        return None

    # Vertical-leg detour.  When the b1 -> b2 column passes through
    # a node's rank-axis range, we shift the column to just outside
    # the node's rank-axis bbox so the column runs in free space.
    # This also forces the top and bottom legs to extend to the new
    # column, so a shifted column propagates into their row-detour
    # inputs naturally.
    shifted_b1 = b1
    shifted_b2 = b2
    if mid_crossing:
        # Pick the outermost (largest rank-axis extent) node to
        # dodge around.  The bridge's current rank-axis coordinate
        # is ``b1[0]`` (LR) or ``b1[1]`` (TB) — same for b2 since
        # both share the column.
        if is_lr:
            mid_crossing.sort(key=lambda n: -n.width)
            nd = mid_crossing[0]
            nl = nd.x - nd.width / 2.0
            nr = nd.x + nd.width / 2.0
            orig_r = b1[0]
            if abs(orig_r - (nl - margin)) <= abs(orig_r - (nr + margin)):
                safe_r = nl - margin
            else:
                safe_r = nr + margin
            shifted_b1 = (safe_r, b1[1])
            shifted_b2 = (safe_r, b2[1])
        else:
            mid_crossing.sort(key=lambda n: -n.height)
            nd = mid_crossing[0]
            nt = nd.y - nd.height / 2.0
            nb = nd.y + nd.height / 2.0
            orig_r = b1[1]
            if abs(orig_r - (nt - margin)) <= abs(orig_r - (nb + margin)):
                safe_r = nt - margin
            else:
                safe_r = nb + margin
            shifted_b1 = (b1[0], safe_r)
            shifted_b2 = (b2[0], safe_r)
        # Re-check top / bottom legs against the shifted column —
        # the shift changes both legs' endpoints so their crossings
        # may have changed too.
        top_crossing = _row_crossings(layout, waypt_i, shifted_b1, skip)
        bot_crossing = _row_crossings(layout, shifted_b2, waypt_j, skip)

    b1 = shifted_b1
    b2 = shifted_b2

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
    # cluster-shaped obstacle with its own bbox.  Only the segment's
    # actual endpoints (``name_i`` / ``name_j``) are exempt.  Sibling
    # nodes in the same wrapping cluster as the edge's tail / head
    # are NOT exempt: the edge still has to avoid them even though
    # they live in the same cluster as its endpoints (e.g. c5373
    # sitting between c5372 and c5374 under cluster_5376).
    for node_name, ln in layout.lnodes.items():
        if ln.virtual:
            continue
        if node_name == name_i or node_name == name_j:
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
    # offender the cluster-only scoring missed.  Only the edge's
    # actual tail and head are exempt; sibling cluster members are
    # still valid obstacles the route has to avoid.
    for node_name, ln in layout.lnodes.items():
        if ln.virtual:
            continue
        if node_name == edge_tail_name or node_name == edge_head_name:
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
                                 head_ln=None, head_face_pt=None,
                                 skip_names: set[str] | None = None):
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

    # The bridge column must sit at least ``_routing_channel`` away
    # from the obstacle's rank-axis face so the channel between the
    # column and the obstacle can hold an edge without overlap.
    # Using max(_routing_channel, nodesep/2+4) keeps backward
    # compatibility for old default setups where nodesep/2+4 > 8,
    # and lets the user dial the bridge margin up via
    # ``layout._routing_channel``.
    _rc = float(getattr(layout, "_routing_channel",
                        getattr(layout, "_CL_OFFSET", 8.0)))
    margin = max(_rc, layout.nodesep / 2.0 + 4.0)
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
                                   waypt_i, waypt_j, tcl, hcl,
                                   skip_names=skip_names)
    if detoured is not None:
        return detoured
    return chosen


def _remove_polyline_spikes(pts: list) -> list:
    """Drop per-axis overshoot spikes from a polyline.

    Iteratively scans every triplet ``(p0, p1, p2)`` and removes
    ``p1`` whenever it is an *overshoot* on either axis, i.e. the
    route walks past ``p2``'s rank-axis (or cross-rank-axis) value
    at ``p1`` and then backtracks to ``p2``.  The formal test on
    each axis ``a`` is:

        sign(p1_a - p0_a) != sign(p2_a - p1_a)     # direction reverses
        sign(p1_a - p0_a) == sign(p2_a - p0_a)     # but the overall
                                                  # net displacement
                                                  # still points the
                                                  # same way as the
                                                  # first segment

    i.e. going ``p0 -> p1`` overshoots ``p2_a`` on axis ``a`` and
    the second segment ``p1 -> p2`` corrects that overshoot.  This
    strictly generalises the collinear-backtrack case (where both
    axes satisfy the test) to off-axis detours like
    ``stub_out (1670.8, 42.7) -> v1 (1802.5, 31) -> bridge1
    (1730, 31)``: the virtual ``v1`` overshoots ``bridge1``'s x by
    72.5 units even though the three points aren't strictly
    collinear.

    Each removal restarts the scan so multi-point spikes collapse
    step by step: a run like ``A -> east -> east -> east -> east
    -> west to B`` peels off one east-going point per pass until
    only ``[A, B]`` remains.  Removal is safe because ``p2`` is
    still reachable from ``p0`` directly — we're just dropping the
    out-of-way detour that the channel router produced when a
    bridge column landed behind the chain virtuals.

    Why this is needed: when the channel router inserts a bridge
    whose column lies on the opposite side of the chain virtuals
    — e.g. ``c0 -> c5359`` with virtuals at x=1802..2348 and a
    bridge column at x=1730 — the pre-bezier polyline threads
    through the virtuals first and then U-turns back to the
    bridge.  After bezier smoothing this shows up as a visible
    stub that "goes nowhere": an eastward excursion spiking out
    from the bridge column with no connection on the other end.
    Dropping the east-side virtuals collapses the U-turn to a
    clean ``stub_out -> bridge1 -> bridge2 -> ...`` path.

    Safe to run on any polyline: if no triplet is an overshoot
    the input is returned unchanged.
    """
    if len(pts) < 3:
        return list(pts)
    result = list(pts)
    eps = 1e-6
    # 5% slack on the projection test.  A point whose scalar
    # projection onto the ``p0 -> p2`` line is in ``[-tol, 1+tol]``
    # is considered on-route — this prevents us from peeling off
    # legitimate bridge corners whose projection lands just barely
    # outside [0, 1] due to a small cross-rank misalignment (e.g.
    # ``bridge1`` at (1730, 31) projects to t = -0.0096 on the
    # segment stub_out(1670.8, 42.7) -> bridge2(1730, 701) because
    # the tail stub is 11.7pt below the bridge column's top row).
    # Only real overshoots (t well outside [0, 1]) get removed.
    proj_tol = 0.05
    changed = True
    while changed:
        changed = False
        i = 1
        while i < len(result) - 1:
            p0 = result[i - 1]
            p1 = result[i]
            p2 = result[i + 1]
            # Scalar projection of p1 onto the straight line from
            # p0 to p2.  If ``t`` falls well outside [0, 1] then
            # ``p1`` is *off-route* — it lies before p0 or after
            # p2 along the direction from p0 to p2 — which is the
            # signature of a backtrack detour.  A t in [0, 1]
            # means p1 sits on the segment and is a legitimate
            # interior waypoint.
            v02x = p2[0] - p0[0]
            v02y = p2[1] - p0[1]
            seg_len_sq = v02x * v02x + v02y * v02y
            is_spike = False
            if seg_len_sq < eps:
                # p0 and p2 coincide — p1 is a zero-length detour
                # unless it's also at the same point.
                v01x = p1[0] - p0[0]
                v01y = p1[1] - p0[1]
                if (v01x * v01x + v01y * v01y) > eps:
                    is_spike = True
            else:
                v01x = p1[0] - p0[0]
                v01y = p1[1] - p0[1]
                t = (v01x * v02x + v01y * v02y) / seg_len_sq
                if t < -proj_tol or t > 1.0 + proj_tol:
                    is_spike = True
            if is_spike:
                # Removing p1 shortcuts to the straight line from
                # p0 to p2, dropping the out-of-way detour.  Back
                # up one index so multi-point U-turns peel off
                # head-to-tail.
                del result[i]
                changed = True
                if i > 1:
                    i -= 1
                continue
            i += 1
    return result


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
        # Stub length = routing channel + arrow head length, so the
        # arrow fits in the outer half of the stub and the inner
        # half is free routing clearance.  Without the arrow budget
        # the default 8pt arrow (from svg_renderer._ARROW_SIZE) fills
        # the entire stub, which leaves no room for the tangent-
        # pinning segment the bezier fit needs.
        _rc_len = float(getattr(layout, "_routing_channel",
                                 getattr(layout, "_CL_OFFSET", 8.0)))
        _arrow_len = float(getattr(layout, "_arrow_len", 8.0))
        stub_len = _rc_len + _arrow_len
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
            # Detour skip-names: intentionally empty.  The new
            # endpoint-based check in _row_crossings already
            # excludes nodes whose bbox contains either segment
            # endpoint (i.e. legitimate attach-point touches), so
            # we don't need a name-based filter.  Leaving tail and
            # head in the candidate set is what lets the detour
            # route *around* them when a bridge leg would
            # otherwise pass straight through their interior.
            skip: set[str] = set()
            bridges = _bridge_points_for_obstacle(
                layout, p_i, p_j, obstacles[0],
                tcl=tcl, hcl=hcl,
                tail_ln=b_tail_ln, tail_face_pt=b_tail_pt,
                head_ln=b_head_ln, head_face_pt=b_head_pt,
                skip_names=skip)
            waypoints.extend(bridges)
        waypoints.append(p_j)

    # Step 6e — spike removal.  If a bridge column landed on the
    # opposite side of the chain virtuals, the polyline now
    # contains an axis-aligned U-turn where the route walks east
    # through the virtuals, reverses course at the last virtual,
    # and heads back west to the bridge column.  The resulting
    # bezier draws as a visible stub spiking out from the bridge
    # column with no connection on the other end.  Collapse any
    # such backtrack before returning.
    return _remove_polyline_spikes(waypoints)


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


def rank_box(layout, sp: SplineInfo, r: int) -> Box:
    """Inter-rank corridor between rank ``r`` and rank ``r+1``.

    C analogue: ``rank_box`` in ``lib/dotgen/dotsplines.c`` lines
    2014–2026 (static, 13 lines).  Full graph width, from the bottom
    of rank r's nodes to the top of rank r+1's nodes, cached in
    ``sp.rank_box[r]`` so repeated calls during a routing pass skip
    the recompute.

    C literal::

        static boxf rank_box(spline_info_t *sp, graph_t *g, int r) {
          boxf b = sp->Rank_box[r];
          if (b.LL.x == b.UR.x) {
            node_t *const left0 = GD_rank(g)[r].v[0];
            node_t *const left1 = GD_rank(g)[r + 1].v[0];
            b.LL.x = sp->LeftBound;
            b.LL.y = ND_coord(left1).y + GD_rank(g)[r + 1].ht2;
            b.UR.x = sp->RightBound;
            b.UR.y = ND_coord(left0).y - GD_rank(g)[r].ht1;
            sp->Rank_box[r] = b;
          }
          return b;
        }

    C uses an uninitialised-sentinel check (``b.LL.x == b.UR.x``);
    we use dict membership which expresses the same intent cleanly.

    C uses ``GD_rank(g)[r].v[0]`` — the first node in the rank's
    node array (index 0), which is the leftmost by mincross order.
    The ``left0`` / ``left1`` names are preserved from C.

    Y-axis note: C uses math convention (y-up) so rank r+1 is at
    smaller y than rank r, and ``LL.y = left1.y + ht2[r+1]`` is the
    visual *bottom* of the corridor.  Python uses y-down so rank r+1
    is at larger y; the y-flip also swaps which rank is referenced on
    each side.  In Python::

        ll_y (smaller y, visual top    of corridor) = left0.y + ht1[r]
        ur_y (larger  y, visual bottom of corridor) = left1.y - ht2[r+1]

    Defensive fallbacks for ranks with no non-virtual node at index 0
    are not present in C — C callers always pass ``r < GD_maxrank(g)``
    and assume v[0] exists.  Kept here because existing Python callers
    invoke ``rank_box`` more liberally.
    """
    cached = sp.rank_box.get(r)
    if cached is not None:
        return cached

    r_nodes = layout.ranks.get(r, [])
    r1_nodes = layout.ranks.get(r + 1, [])
    if r_nodes:
        left0_y = layout.lnodes[r_nodes[0]].y
    else:
        left0_y = r * layout.ranksep
    if r1_nodes:
        left1_y = layout.lnodes[r1_nodes[0]].y
    else:
        left1_y = (r + 1) * layout.ranksep

    b = Box(
        ll_x=sp.left_bound,
        ll_y=left0_y + layout._rank_ht1.get(r, 18),
        ur_x=sp.right_bound,
        ur_y=left1_y - layout._rank_ht2.get(r + 1, 18),
    )
    sp.rank_box[r] = b
    return b


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
            iy = (rbox.ll_y + rbox.ur_y) / 2.0
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

