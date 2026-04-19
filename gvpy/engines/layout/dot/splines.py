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


def _phase4_to_tb(layout):
    """Reverse ``position.apply_rankdir`` so phase-4 code sees TB coords.

    C keeps its internal layout in a fixed y-rank frame and only
    rotates at postproc; Python's ``apply_rankdir`` already rotated at
    the end of phase 3, so every phase-4 site that reads ``ln.y`` as
    the rank axis or uses ``sp.left_bound`` as the cross-rank bound is
    wrong for LR/RL/BT.  Un-swap here, let phase 4 run pure-TB, then
    re-apply the rotation in :func:`_phase4_from_tb` at exit — nodes,
    cluster bboxes, edge splines, and label anchors all get the
    reverse transform.
    """
    rankdir = layout.rankdir
    if rankdir == "TB":
        return None
    state = {"rankdir": rankdir}
    if rankdir == "BT":
        max_y = max((ln.y for ln in layout.lnodes.values()), default=0.0)
        state["max_y"] = max_y
        for ln in layout.lnodes.values():
            ln.y = max_y - ln.y
        for cl in layout._clusters:
            if cl.bb:
                x1, y1, x2, y2 = cl.bb
                cl.bb = (x1, max_y - y2, x2, max_y - y1)
    elif rankdir == "LR":
        for ln in layout.lnodes.values():
            ln.x, ln.y = ln.y, ln.x
            ln.width, ln.height = ln.height, ln.width
        for cl in layout._clusters:
            if cl.bb:
                x1, y1, x2, y2 = cl.bb
                cl.bb = (y1, x1, y2, x2)
    elif rankdir == "RL":
        # RL = LR + flip Y. Reverse: flip Y first, then swap x/y.
        max_x = max((ln.x for ln in layout.lnodes.values()), default=0.0)
        state["max_x"] = max_x
        for ln in layout.lnodes.values():
            ln.x = max_x - ln.x            # undo the final flip
            ln.x, ln.y = ln.y, ln.x        # undo the LR-swap
            ln.width, ln.height = ln.height, ln.width
        for cl in layout._clusters:
            if cl.bb:
                x1, y1, x2, y2 = cl.bb
                # apply the same two-step reverse
                x1, x2 = max_x - x2, max_x - x1
                cl.bb = (y1, x1, y2, x2)
    layout.rankdir = "TB"
    return state


def _phase4_from_tb(layout, state):
    """Reapply the saved rankdir transform, including to new edge output.

    Companion of :func:`_phase4_to_tb`.  Besides restoring node and
    cluster bboxes, this also transforms every :class:`EdgeRoute` the
    phase-4 body just computed — ``points``, ``sp``, ``ep``, and
    ``label_pos`` all live in the internal TB frame until now.
    """
    if state is None:
        return
    rankdir = state["rankdir"]
    layout.rankdir = rankdir

    def _xform(pt):
        x, y = pt
        if rankdir == "BT":
            return (x, state["max_y"] - y)
        if rankdir == "LR":
            return (y, x)
        if rankdir == "RL":
            return (state["max_x"] - y, x)
        return (x, y)

    if rankdir == "BT":
        max_y = state["max_y"]
        for ln in layout.lnodes.values():
            ln.y = max_y - ln.y
        for cl in layout._clusters:
            if cl.bb:
                x1, y1, x2, y2 = cl.bb
                cl.bb = (x1, max_y - y2, x2, max_y - y1)
    elif rankdir == "LR":
        for ln in layout.lnodes.values():
            ln.x, ln.y = ln.y, ln.x
            ln.width, ln.height = ln.height, ln.width
        for cl in layout._clusters:
            if cl.bb:
                x1, y1, x2, y2 = cl.bb
                cl.bb = (y1, x1, y2, x2)
    elif rankdir == "RL":
        # RL was produced from LR+flipY; redo LR swap then flip Y.
        max_x = state["max_x"]
        for ln in layout.lnodes.values():
            ln.x, ln.y = ln.y, ln.x
            ln.width, ln.height = ln.height, ln.width
            ln.x = max_x - ln.x
        for cl in layout._clusters:
            if cl.bb:
                x1, y1, x2, y2 = cl.bb
                # LR swap then flip x
                x1, y1, x2, y2 = y1, x1, y2, x2
                x1, x2 = max_x - x2, max_x - x1
                cl.bb = (x1, y1, x2, y2)

    # Transform edge output.
    all_edges = list(layout.ledges) + list(layout._chain_edges)
    for le in all_edges:
        if le.route.points:
            le.route.points = [_xform(p) for p in le.route.points]
        if le.route.sflag:
            le.route.sp = _xform(le.route.sp)
        if le.route.eflag:
            le.route.ep = _xform(le.route.ep)
        if le.label_pos:
            le.label_pos = _xform(le.label_pos)


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

    # Un-swap rankdir so the rest of phase 4 sees TB coords (matches C's
    # fixed y-rank internal frame).  :func:`_phase4_from_tb` reverses
    # this at the end, including transforming new edge splines.
    _rankdir_state = _phase4_to_tb(layout)
    try:
        _phase4_routing_body(layout)
    finally:
        _phase4_from_tb(layout, _rankdir_state)


def _phase4_routing_body(layout):
    """Phase-4 body — always runs in TB frame (see :func:`phase4_routing`)."""
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

    # E+.1 — bundle parallel flat edges between adjacent same-rank
    # nodes when at least one has a label; the bundle is handed to
    # make_flat_edge once so make_simple_flat_labels can alternate
    # labels up/down.  Any other flat-edge case (mixed ports,
    # non-adjacent, heterogeneous) stays in the per-edge path below —
    # bundling those regresses routing that already works edge-by-edge.
    flat_bundles: dict = {}
    for le in sorted_real_edges:
        tail = layout.lnodes.get(le.tail_name)
        head = layout.lnodes.get(le.head_name)
        if (tail is None or head is None or le.virtual
                or le.tail_name == le.head_name
                or tail.rank != head.rank
                or abs(tail.order - head.order) != 1
                or le.tailport or le.headport):
            continue
        key = frozenset((le.tail_name, le.head_name))
        flat_bundles.setdefault(key, []).append(le)

    flat_ids: set = set()
    for key, bundle in list(flat_bundles.items()):
        if len(bundle) <= 1 or not any(le.label for le in bundle):
            del flat_bundles[key]
            continue
        for le in bundle:
            flat_ids.add(id(le))

    for bundle in flat_bundles.values():
        make_flat_edge(layout, layout._spline_info, P, bundle, et)
        for le in bundle:
            layout._compute_label_pos(le)

    for le in sorted_real_edges:
        if id(le) in flat_ids:
            continue
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

    C analogue: ``lib/ortho/ortho.c`` — full orthogonal channel router
    with obstacle-avoidance.  Python implements a simplified Z-shape
    placeholder: vertical → horizontal → vertical polyline with one
    adjustable mid-y.

    Cluster avoidance (pragmatic, non-faithful-to-C): if the candidate
    horizontal leg would cross a non-member cluster's bbox, shift
    ``mid_y`` above or below the blocking cluster(s).  Handles simple
    obstacle stacks; complex cases (obstacles on both sides, nested
    cluster edges leaving through a foreign cluster's wall) still fall
    through to whichever side has less deviation.  This closes the
    visible gap on graphs like ``test_data/2620.dot`` without
    committing to a full ``lib/ortho`` port.

    Callers: :func:`phase4_routing` when ``splines=ortho``.  Runs
    inside the TB frame set up by :func:`_phase4_to_tb`, so x is the
    cross-rank axis and y is the rank axis regardless of output
    rankdir.
    """
    # Exit point from tail
    p_start = layout._edge_start_point(le, tail, head)
    # Entry point into head
    p_end = layout._edge_end_point(le, head, tail)

    if abs(p_start[0] - p_end[0]) < 0.5:
        # Vertically aligned — straight vertical line
        return [p_start, p_end]

    mid_y = _ortho_safe_midy(
        layout, le,
        p_start, p_end,
        default_mid_y=(p_start[1] + p_end[1]) / 2.0,
    )

    return [
        p_start,
        (p_start[0], mid_y),
        (p_end[0], mid_y),
        p_end,
    ]


def _ortho_safe_midy(layout, le, p_start, p_end, default_mid_y: float) -> float:
    """Pick a ``mid_y`` for the Z-shape's horizontal leg that clears
    non-member cluster bboxes.

    Heuristic: compute the edge's member-cluster set (clusters
    containing either endpoint).  Any other cluster whose bbox (a)
    straddles the candidate ``mid_y`` vertically *and* (b) overlaps
    the [p_start.x, p_end.x] range horizontally is an obstacle.  If
    obstacles exist, try shifting ``mid_y`` just above the highest
    obstacle top or just below the lowest obstacle bottom; pick
    whichever deviates less from ``default_mid_y`` and has no
    remaining obstacles at the new height.  If neither side clears,
    return the smaller-deviation side as a best effort.
    """
    members = _ortho_member_clusters(layout, le.tail_name, le.head_name)
    xlo, xhi = sorted((p_start[0], p_end[0]))
    margin = max(layout.nodesep / 2.0, 8.0)

    # Gather obstacles at the default mid_y.
    obstacles = []
    for cl in layout._clusters:
        if not cl.bb or cl.name in members:
            continue
        cx1, cy1, cx2, cy2 = cl.bb
        # Horizontal overlap with the candidate leg.
        if cx2 < xlo or cx1 > xhi:
            continue
        # Vertical straddle of default_mid_y.
        if cy1 <= default_mid_y <= cy2:
            obstacles.append((cy1, cy2))
    if not obstacles:
        return default_mid_y

    # Candidate shifts: above (y < all obstacle tops) or below (y > all
    # obstacle bottoms).  Node y-down convention: "above" = smaller y.
    top_of_stack = min(o[0] for o in obstacles)
    bot_of_stack = max(o[1] for o in obstacles)
    above_y = top_of_stack - margin
    below_y = bot_of_stack + margin

    # Don't push past the edge's own endpoints (routing above tail
    # y_min or below head y_max would loop the edge backwards).
    y_lo_bound = min(p_start[1], p_end[1]) - margin * 4
    y_hi_bound = max(p_start[1], p_end[1]) + margin * 4

    above_ok = above_y >= y_lo_bound
    below_ok = below_y <= y_hi_bound

    above_valid = above_ok and not _ortho_any_obstacle_at(
        layout, members, above_y, xlo, xhi)
    below_valid = below_ok and not _ortho_any_obstacle_at(
        layout, members, below_y, xlo, xhi)

    if above_valid and below_valid:
        return (above_y if abs(above_y - default_mid_y)
                <= abs(below_y - default_mid_y) else below_y)
    if above_valid:
        return above_y
    if below_valid:
        return below_y
    # Neither side clears everything — pick the smaller-deviation
    # partial detour; at least reduces crossings versus the naïve Z.
    if not above_ok and not below_ok:
        return default_mid_y
    if above_ok and not below_ok:
        return above_y
    if below_ok and not above_ok:
        return below_y
    return (above_y if abs(above_y - default_mid_y)
            <= abs(below_y - default_mid_y) else below_y)


def _ortho_member_clusters(layout, tail_name: str, head_name: str) -> set:
    """Cluster names containing either endpoint."""
    members = set()
    for cl in layout._clusters:
        nset = set(cl.nodes)
        if tail_name in nset or head_name in nset:
            members.add(cl.name)
    return members


def _ortho_any_obstacle_at(layout, members, y: float,
                            xlo: float, xhi: float) -> bool:
    """True if any non-member cluster overlaps the horizontal strip at *y*."""
    for cl in layout._clusters:
        if not cl.bb or cl.name in members:
            continue
        cx1, cy1, cx2, cy2 = cl.bb
        if cx2 < xlo or cx1 > xhi:
            continue
        if cy1 <= y <= cy2:
            return True
    return False


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
        # Must return a fresh copy: ``routespl.routesplines_`` mutates
        # box x-extents in place (to ``±inf`` after routing) so shared
        # references would poison every subsequent fetch of the same
        # rank.  C is immune because ``GD_rank(g)[r].rank_box`` is a
        # value type; Python :class:`Box` is a mutable dataclass.
        return Box(ll_x=cached.ll_x, ll_y=cached.ll_y,
                   ur_x=cached.ur_x, ur_y=cached.ur_y)

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
    # Return a copy so the caller can own / mutate independently of
    # the cache (same reason as the cached branch above).
    return Box(ll_x=b.ll_x, ll_y=b.ll_y, ur_x=b.ur_x, ur_y=b.ur_y)


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

