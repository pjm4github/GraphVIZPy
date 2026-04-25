"""Regular-edge routing via box corridors.

See: /lib/dotgen/dotsplines.c @ 1736

Phase D of the splines port.  Replaces the heuristic
``route_regular_edge`` with a C-matching implementation:
``beginpath`` / ``rank_box`` / ``endpath`` / ``completeregularpath``
/ ``routesplines`` / ``clip_and_install``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from gvpy.engines.layout.dot.clip import clip_and_install
from gvpy.engines.layout.dot.cluster_detour import reshape_around_clusters
from gvpy.engines.layout.dot.path import (
    Box, Path, PathEnd, SplineInfo,
    BOTTOM, TOP, REGULAREDGE,
    MINW, HALFMINW,
    add_box, beginpath, endpath,
)
from gvpy.engines.layout.pathplan import Ppoint
from gvpy.engines.layout.dot.routespl import routesplines, routepolylines

if TYPE_CHECKING:
    pass

# Avoid importing these at module level to prevent circular deps.
# They are accessed via the ``layout`` object or late-imported.

EDGETYPE_SPLINE = 5 << 1
EDGETYPE_LINE = 1 << 1
EDGETYPE_PLINE = 3 << 1


# ── makeregularend ─────────────────────────────────────────────────

def makeregularend(b: Box, side: int, y: float) -> Box:
    """Create a box between a node box and interrank space.

    See: /lib/dotgen/dotsplines.c @ 1988
    """
    if side == BOTTOM:
        return Box(ll_x=b.ll_x, ll_y=y, ur_x=b.ur_x, ur_y=b.ll_y)
    return Box(ll_x=b.ll_x, ll_y=b.ur_y, ur_x=b.ur_x, ur_y=y)


# ── adjustregularpath ──────────────────────────────────────────────

def adjustregularpath(P: Path, fb: int, lb: int) -> None:
    """Widen narrow boxes to MINW and ensure minimum overlap.

    See: /lib/dotgen/dotsplines.c @ 2010
    """
    for i in range(max(0, fb - 1), min(lb + 1, P.nbox)):
        bp = P.boxes[i]
        if (i - fb) % 2 == 0:
            if bp.ll_x >= bp.ur_x:
                x = (bp.ll_x + bp.ur_x) / 2
                bp.ll_x = x - HALFMINW
                bp.ur_x = x + HALFMINW
        else:
            if bp.ll_x + MINW > bp.ur_x:
                x = (bp.ll_x + bp.ur_x) / 2
                bp.ll_x = x - HALFMINW
                bp.ur_x = x + HALFMINW

    for i in range(P.nbox - 1):
        bp1 = P.boxes[i]
        bp2 = P.boxes[i + 1]
        if fb <= i <= lb and (i - fb) % 2 == 0:
            if bp1.ll_x + MINW > bp2.ur_x:
                bp2.ur_x = bp1.ll_x + MINW
            if bp1.ur_x - MINW < bp2.ll_x:
                bp2.ll_x = bp1.ur_x - MINW
        elif i + 1 >= fb and i < lb and (i + 1 - fb) % 2 == 0:
            if bp1.ll_x + MINW > bp2.ur_x:
                bp1.ll_x = bp2.ur_x - MINW
            if bp1.ur_x - MINW < bp2.ll_x:
                bp1.ur_x = bp2.ll_x + MINW


# ── D+.2 — straight_len / straight_path / resize_vn / recover_slack ───

_ALIGN_EPS = 0.01   # points; tolerance for "same x" comparison


def straight_len(layout, start_ln) -> int:
    """Count vertically aligned virtual nodes following ``start_ln``.

    See: /lib/dotgen/dotsplines.c @ 2060

    Walks the first outgoing edge of each virtual, counting virtuals
    whose x-coordinate matches ``start_ln``'s within :data:`_ALIGN_EPS`
    and that are **single-pass** (exactly one in-edge and one
    out-edge).  Stops at the first real node or any fan-in/out
    virtual.  Returns the count (not including ``start_ln``).

    Used to detect long straight runs in a virtual chain where a
    spline fit would be wasteful compared to a polyline segment.
    """
    from gvpy.engines.layout.dot.dotsplines import _node_out_edges, _node_in_edges

    cnt = 0
    v = start_ln
    while True:
        out_edges = _node_out_edges(layout, v)
        if not out_edges:
            break
        nxt = layout.lnodes.get(out_edges[0].head_name)
        if nxt is None or not nxt.virtual:
            break
        if (len(_node_out_edges(layout, nxt)) != 1
                or len(_node_in_edges(layout, nxt)) != 1):
            break
        if abs(nxt.x - start_ln.x) > _ALIGN_EPS:
            break
        cnt += 1
        v = nxt
    return cnt


def straight_path(layout, start_le, cnt: int, plist: list):
    """Advance ``cnt`` steps along the virtual chain, doubling the tail anchor.

    See: /lib/dotgen/dotsplines.c @ 2078

    Walks ``cnt`` successive out-edges starting from ``start_le`` and
    returns the final :class:`LayoutEdge`.  Mirrors C's point-list
    manipulation by appending the last point of ``plist`` twice (so a
    cubic-bezier consumer sees a straight segment to the next anchor).
    """
    from gvpy.engines.layout.dot.dotsplines import _node_out_edges

    f = start_le
    for _ in range(cnt):
        head_ln = layout.lnodes.get(f.head_name)
        if head_ln is None:
            break
        out_edges = _node_out_edges(layout, head_ln)
        if not out_edges:
            break
        f = out_edges[0]
    if plist:
        last = plist[-1]
        plist.append(last)
        plist.append(last)
    return f


def _has_edge_labels(layout) -> bool:
    """Rough analogue of C's ``GD_has_labels(g->root) & EDGE_LABEL`` —
    whether any non-virtual edge carries a label (affects the smode
    threshold because labelled edges need a longer straight run to
    warrant the break).
    """
    for le in getattr(layout, "ledges", ()):
        if getattr(le, "virtual", False):
            continue
        if getattr(le, "label", ""):
            return True
    return False


def flatten_straight_runs(ps: list[Ppoint], le, layout) -> list[Ppoint]:
    """D+.2b cosmetic pass — straighten x-aligned bezier runs.

    C's ``make_regular_edge`` detects a run of ``>= 3`` vertically
    aligned virtual nodes in the edge's chain (``>= 5`` when the
    graph carries edge labels) and breaks the corridor at the start
    of that run, routing the middle as an explicit straight polyline
    instead of fitting a single smooth bezier over the whole chain.
    See ``lib/dotgen/dotsplines.c:1807`` (``smode = true`` branch)
    and :func:`straight_len` / :func:`straight_path`.

    We ship the cosmetic effect as a post-hoc pass rather than a
    full restructure of the corridor-build loop: scan the bezier
    output for consecutive anchors that share an x-coordinate (to
    :data:`_ALIGN_EPS`), and in any run of ``>= threshold``
    consecutive aligned segments, replace the control points with
    linear interpolation so that run renders as straight instead of
    a subtly-curving bezier.  Visually identical to C's smode output
    without the accompanying corridor-restructure work; byte output
    differs from C on the control-point coordinates.

    **Cluster-safety check.**  The original wobbly controls
    sometimes curved the bezier around a non-member cluster that a
    straight chord would cut through.  Before flattening any run we
    sample the candidate chord against every non-member cluster
    bbox; if it crosses, we skip that run so the D4 guarantee isn't
    silently undone.
    """
    if len(ps) < 4:
        return ps

    stride = 3  # cubic bezier: 1 + 3·segments control points
    n_anchors = (len(ps) - 1) // stride + 1
    if n_anchors < 2:
        return ps

    # Originally ``threshold = 3 (resp. 5 with edge labels)`` per C's
    # ``straight_len >= 3`` virtual-count check.  But ``routesplines``
    # performs aggressive curve-fitting that collapses many virtuals
    # into a single bezier segment — a 10-rank straight chain often
    # emerges as one cubic with control points dramatically offset
    # from the anchor-to-anchor line.  So at the output-bezier level
    # we use threshold 1: any single segment whose two anchors share
    # an x is supposed to render as a vertical straight line, and
    # flattening its controls to linear interpolation removes the
    # wobble even when the underlying virtual chain was short.  Safe
    # for chains the router already drew straight (controls already
    # on the chord — no visual change).  ``_has_edge_labels`` is
    # retained only to keep the C parallel readable.
    _ = _has_edge_labels(layout)
    threshold = 1

    # Collect x-aligned runs of consecutive anchors.
    anchors = [ps[i * stride] for i in range(n_anchors)]
    runs: list[tuple[int, int]] = []  # (first_segment_idx, run_length)
    i = 0
    while i < n_anchors - 1:
        j = i + 1
        while (j < n_anchors
               and abs(anchors[j].x - anchors[i].x) < _ALIGN_EPS):
            j += 1
        run_length = j - i - 1
        if run_length >= threshold:
            runs.append((i, run_length))
        i = j if j > i + 1 else i + 1

    if not runs:
        return ps

    # Cluster-safety: if the straight chord across a run crosses a
    # non-member cluster bbox, skip flattening that run.  Without
    # this guard the original wobbly controls sometimes curved the
    # bezier around a cluster that a straight segment would intersect.
    clusters = getattr(layout, "_clusters", None) or []
    member_names: set[str] = set()
    if clusters and le is not None:
        tail, head = le.tail_name, le.head_name
        for cl in clusters:
            if tail in cl.nodes or head in cl.nodes:
                member_names.add(cl.name)
    offenders = [cl for cl in clusters
                 if cl.bb and cl.name not in member_names]

    def _chord_crosses_offender(p0: Ppoint, p1: Ppoint) -> bool:
        for cl in offenders:
            x1, y1, x2, y2 = cl.bb
            for k in range(1, 16):
                t = k / 16.0
                sx = p0.x + t * (p1.x - p0.x)
                sy = p0.y + t * (p1.y - p0.y)
                if x1 < sx < x2 and y1 < sy < y2:
                    return True
        return False

    # Replace controls in each run's segments with linear interpolation
    # so the cubic degenerates to a straight line between anchors.
    out = list(ps)
    for start, length in runs:
        run_p0 = anchors[start]
        run_p1 = anchors[start + length]
        if offenders and _chord_crosses_offender(run_p0, run_p1):
            continue
        for seg_idx in range(start, start + length):
            p0 = out[seg_idx * stride]
            p1 = out[(seg_idx + 1) * stride]
            dx = p1.x - p0.x
            dy = p1.y - p0.y
            out[seg_idx * stride + 1] = Ppoint(
                p0.x + dx / 3.0, p0.y + dy / 3.0)
            out[seg_idx * stride + 2] = Ppoint(
                p0.x + 2.0 * dx / 3.0, p0.y + 2.0 * dy / 3.0)
    return out


def resize_vn(vn, lx: float, cx: float, rx: float) -> None:
    """Set a virtual node's x-coord and half-widths.

    See: /lib/dotgen/dotsplines.c @ 2111

    C stores left/right widths separately (``ND_lw`` / ``ND_rw``) so
    asymmetric expansion is possible.  Python's :class:`LayoutNode`
    carries a single ``width`` — we set ``width = rx - lx`` and store
    the split on ad-hoc ``_lw`` / ``_rw`` attributes for downstream
    consumers that want the C-accurate asymmetry (e.g. a label-bearing
    virtual pushed right by :func:`recover_slack`).
    """
    vn.x = cx
    vn.width = rx - lx
    vn._lw = cx - lx
    vn._rw = rx - cx


def recover_slack(layout, vchain_names: list, P) -> None:
    """Snap virtual-chain nodes onto the routed corridor.

    See: /lib/dotgen/dotsplines.c @ 2090

    After the box-corridor router has laid down the path, walk the
    virtual chain tail→head and for each virtual find the path box
    whose rank-axis extent (``ll_y..ur_y`` in y-down) contains the
    virtual's y.  If found, :func:`resize_vn` snaps the virtual's x
    and width to the box's x-extent:

    - **No label**: center the virtual, expand to full box width.
    - **Has label**: push virtual to the box's right edge, preserving
      the original right half-width (matches C's one-sided expansion
      for label-bearing virtuals).

    Walks boxes in order, advancing past any entirely above the
    current virtual (``box.ur_y < vn.y``) and skipping the virtual if
    the current box is entirely below it (``box.ll_y > vn.y``).
    """
    from gvpy.engines.layout.dot.dotsplines import spline_merge

    boxes = P.boxes
    if not boxes or not vchain_names:
        return

    b = 0
    for vname in vchain_names:
        vn = layout.lnodes.get(vname)
        if vn is None or not vn.virtual:
            continue
        if spline_merge(layout, vn):
            break
        while b < len(boxes) and boxes[b].ur_y < vn.y:
            b += 1
        if b >= len(boxes):
            break
        if boxes[b].ll_y > vn.y:
            continue
        box = boxes[b]
        has_label = bool(getattr(vn, "label", "")) or bool(
            getattr(getattr(vn, "node", None), "attributes", {}).get("label", "")
        )
        if has_label:
            original_rw = vn.width / 2
            resize_vn(vn, box.ll_x, box.ur_x, box.ur_x + original_rw)
        else:
            cx = (box.ll_x + box.ur_x) / 2
            resize_vn(vn, box.ll_x, cx, box.ur_x)


# ── top_bound / bot_bound ──────────────────────────────────────────

def top_bound(layout, tail_ln, ref_head_order: int, side: int):
    """Find a sibling out-edge of ``tail_ln`` routed farther in ``side``.

    See: /lib/dotgen/dotsplines.c @ 2117

    Scans every out-edge ``f`` of ``tail_ln``; keeps only those whose
    head's order lies strictly on ``side`` (``+1`` = right, ``-1`` =
    left) of ``ref_head_order`` and that already have a computed
    spline (checked via :func:`label_place.getsplinepoints`, which
    walks the to_orig chain).  Returns the sibling with the closest
    head order to the reference, or ``None`` if there is no such edge.

    C passes a single ``edge_t *e`` and derives ``agtail(e)`` /
    ``ND_order(aghead(e))``.  Python's bundle model and virtual chains
    don't map cleanly to a single edge_t, so these two inputs are
    passed explicitly — same semantics, different spelling.
    """
    from gvpy.engines.layout.dot.dotsplines import _node_out_edges
    from gvpy.engines.layout.dot.label_place import getsplinepoints

    ans = None
    ans_order = None
    for f in _node_out_edges(layout, tail_ln):
        f_head = layout.lnodes.get(f.head_name)
        if f_head is None:
            continue
        f_order = f_head.order
        # Equivalent to C: side*(ND_order(aghead(f)) - ND_order(aghead(e))) <= 0
        if side * (f_order - ref_head_order) <= 0:
            continue
        if getsplinepoints(layout, f) is None:
            continue
        if ans is None or side * (ans_order - f_order) > 0:
            ans = f
            ans_order = f_order
    return ans


def bot_bound(layout, head_ln, ref_tail_order: int, side: int):
    """Mirror of :func:`top_bound` for the head side.

    See: /lib/dotgen/dotsplines.c @ 2133
    """
    from gvpy.engines.layout.dot.dotsplines import _node_in_edges
    from gvpy.engines.layout.dot.label_place import getsplinepoints

    ans = None
    ans_order = None
    for f in _node_in_edges(layout, head_ln):
        f_tail = layout.lnodes.get(f.tail_name)
        if f_tail is None:
            continue
        f_order = f_tail.order
        if side * (f_order - ref_tail_order) <= 0:
            continue
        if getsplinepoints(layout, f) is None:
            continue
        if ans is None or side * (ans_order - f_order) > 0:
            ans = f
            ans_order = f_order
    return ans


# ── completeregularpath ────────────────────────────────────────────

def completeregularpath(P: Path, tendp: PathEnd, hendp: PathEnd,
                        boxes: list[Box],
                        *,
                        layout=None,
                        tail_ln=None, first_hop_order: int = 0,
                        head_ln=None, last_hop_order: int = 0) -> bool:
    """Assemble the full box corridor from tail end + path + head end.

    See: /lib/dotgen/dotsplines.c @ 1950

    When ``layout`` / ``tail_ln`` / ``head_ln`` are supplied, runs the
    C-matching ``top_bound``/``bot_bound`` neighbor checks: if any
    parallel sibling on the left/right of either end is found but
    :func:`label_place.getsplinepoints` returns ``None`` on it, abort
    — leave ``P.boxes`` empty so downstream
    ``routesplines``/``routepolylines`` no-ops and
    :func:`make_regular_edge` bails cleanly.  Returns ``True`` on
    normal completion, ``False`` on abort.

    Without the keyword-only params the neighbor check is skipped
    (backward-compatible with call sites that don't need it).

    Note on defensiveness
    ---------------------
    Because ``top_bound`` / ``bot_bound`` already filters siblings by
    ``getsplinepoints != None``, the post-check below is unreachable
    under well-formed state — it mirrors the C source's own redundant
    safety net, which defends against corrupted spline lists.
    """
    from gvpy.engines.layout.dot.label_place import getsplinepoints

    P.boxes.clear()
    P.nbox = 0

    if layout is not None and tail_ln is not None and head_ln is not None:
        for side in (-1, 1):
            n = top_bound(layout, tail_ln, first_hop_order, side)
            if n is not None and getsplinepoints(layout, n) is None:
                return False
        for side in (-1, 1):
            n = bot_bound(layout, head_ln, last_hop_order, side)
            if n is not None and getsplinepoints(layout, n) is None:
                return False

    for i in range(tendp.boxn):
        add_box(P, tendp.boxes[i])
    fb = P.nbox + 1
    lb = fb + len(boxes) - 3
    for b in boxes:
        add_box(P, b)
    for i in range(hendp.boxn - 1, -1, -1):
        add_box(P, hendp.boxes[i])
    adjustregularpath(P, fb, lb)
    return True


# ── Node geometry helper ──────────────────────────────────────────

def _node_geom(ln) -> dict:
    """Extract node geometry for beginpath/endpath calls."""
    hw = ln.width / 2
    hh = ln.height / 2
    return dict(
        node_x=ln.x, node_y=ln.y,
        node_lw=hw, node_rw=hw, node_ht2=hh,
        is_normal=not ln.virtual,
    )


# ── make_regular_edge ─────────────────────────────────────────────

def make_regular_edge(layout, sp: SplineInfo, P: Path,
                      edges: list, et: int) -> None:
    """Route regular edges through the box corridor and install on the edge.

    See: /lib/dotgen/dotsplines.c @ 1736

    Takes a list of parallel ``LayoutEdge`` objects sharing the same
    tail→head path through ranks.  For each edge, builds the box
    corridor (``beginpath`` → ``rank_box`` → ``maximal_bbox`` →
    ``endpath``), routes a spline through it
    (``routesplines``/``routepolylines``), clips to node boundaries
    (``clip_and_install``), and stores the result on the edge's
    ``EdgeRoute``.

    Multi-edge offset (``Multisep``) is applied when ``len(edges) > 1``.
    """
    from gvpy.engines.layout.dot.dotsplines import (
        maximal_bbox, rank_box, spline_merge,
        _node_out_edges, )
    from gvpy.engines.layout.dot.path import BWDEDGE

    if not edges:
        return
    le0 = edges[0]

    # Resolve real tail and head.  For chain edges (multi-rank),
    # tail_name/head_name point to the real endpoints.  For single-
    # rank real edges, they are the same as the edge endpoints.
    tail_name = le0.orig_tail if le0.orig_tail else le0.tail_name
    head_final_name = le0.orig_head if le0.orig_head else le0.head_name

    # Handle backward edges: swap tail/head.
    if le0.tree_index & BWDEDGE:
        tail_name, head_final_name = head_final_name, tail_name

    tail = layout.lnodes.get(tail_name)
    real_head = layout.lnodes.get(head_final_name)
    if tail is None or real_head is None:
        return

    # Discover the virtual node chain (if any).
    chain_key = (tail_name, head_final_name)
    vchain = layout._vnode_chains.get(chain_key, [])

    # First hop: tail → first virtual (or direct to head).
    if vchain:
        first_hn = layout.lnodes.get(vchain[0])
        if first_hn is None:
            first_hn = real_head
    else:
        first_hn = real_head

    # Start building the box corridor.
    is_spline = et == EDGETYPE_SPLINE
    tn = tail
    hn = first_hn

    tend = PathEnd(nb=maximal_bbox(layout, sp, tn, None, None))
    geom = _node_geom(tn)
    geom["ranksep"] = layout.ranksep
    beginpath(P, REGULAREDGE, tend, spline_merge(layout, tn), **geom)

    # Add transition box between node and interrank space.
    b = _copy_box(tend.boxes[tend.boxn - 1])
    ht1 = layout._rank_ht1.get(tn.rank, tn.height / 2)
    b = makeregularend(b, BOTTOM, tn.y + ht1)
    if b.ll_x < b.ur_x and b.ll_y < b.ur_y:
        tend.boxes.append(b)
        tend.boxn += 1

    # Walk through virtual nodes, collecting interrank corridor boxes.
    corridor_boxes: list[Box] = []
    cur_rank_node = tn

    while hn.virtual and not spline_merge(layout, hn):
        corridor_boxes.append(rank_box(layout, sp, cur_rank_node.rank))

        out_edges = _node_out_edges(layout, hn)
        if not out_edges:
            break
        next_le = out_edges[0]
        next_hn = layout.lnodes.get(next_le.head_name)
        if next_hn is None:
            break

        corridor_boxes.append(maximal_bbox(layout, sp, hn, None, next_le))
        cur_rank_node = hn
        hn = next_hn

    # Final rank box.
    corridor_boxes.append(rank_box(layout, sp, cur_rank_node.rank))

    # End path at the real head node.
    hend = PathEnd(nb=maximal_bbox(layout, sp, real_head, None, None))
    geom_h = _node_geom(real_head)
    geom_h["ranksep"] = layout.ranksep
    endpath(P, REGULAREDGE, hend, spline_merge(layout, real_head), **geom_h)

    # Add transition box at head.
    b = _copy_box(hend.boxes[hend.boxn - 1])
    ht2 = layout._rank_ht2.get(real_head.rank, real_head.height / 2)
    b = makeregularend(b, TOP, real_head.y - ht2)
    if b.ll_x < b.ur_x and b.ll_y < b.ur_y:
        hend.boxes.append(b)
        hend.boxn += 1

    # Assemble corridor and route.
    # ``first_hn`` / ``cur_rank_node`` bracket the chain: the first is
    # the tail's first out-hop (order used by top_bound); the last is
    # the node feeding ``real_head`` (order used by bot_bound).  For
    # direct (no-vchain) edges ``cur_rank_node`` is still ``tail``.
    first_hop_order = first_hn.order if first_hn is not None else 0
    last_hop_order = cur_rank_node.order if cur_rank_node is not None else 0
    completeregularpath(P, tend, hend, corridor_boxes,
                        layout=layout,
                        tail_ln=tail, first_hop_order=first_hop_order,
                        head_ln=real_head, last_hop_order=last_hop_order)

    # [TRACE spline] — emit box corridor + endpoints per edge, matching
    # the C-side trace in ``lib/common/routespl.c``.  Gated on
    # ``GV_TRACE=spline``.
    from gvpy.engines.layout.dot.trace import trace_on as _sp_on, trace as _sp_tr
    if _sp_on("spline"):
        _boxes = P.boxes
        _bs = "".join(f"[{b.ll_x:.1f},{b.ll_y:.1f},{b.ur_x:.1f},{b.ur_y:.1f}]"
                      for b in _boxes)
        _sx, _sy = P.start.np
        _ex, _ey = P.end.np
        _sp_tr("spline", f"edge={tail_name}->{head_final_name} "
                         f"n_boxes={len(_boxes)} boxes={_bs} "
                         f"eps=({_sx:.1f},{_sy:.1f})->({_ex:.1f},{_ey:.1f})")

    _edge_label = f"{tail_name}->{head_final_name}"
    if is_spline:
        ps = routesplines(P, edge_name=_edge_label)
    else:
        ps = routepolylines(P, edge_name=_edge_label)
        if ps and et == EDGETYPE_LINE and len(ps) > 4:
            ps[1] = Ppoint(ps[0].x, ps[0].y)
            ps[3] = Ppoint(ps[-1].x, ps[-1].y)
            ps[2] = Ppoint(ps[-1].x, ps[-1].y)
            ps = ps[:4]

    if not ps:
        return

    # D4 post-hoc guard — reshape the bezier around any non-member
    # cluster whose interior the spline still pierces.  No-op for
    # edges that route cleanly (the overwhelming common case); adds
    # a detour via-point when the interrank corridor gave
    # ``routesplines`` no room to steer around a cluster that sits
    # between tail and head on opposite sides.  See
    # ``cluster_detour.py`` for the strategy.
    ps = reshape_around_clusters(ps, edges[0], layout)

    # D+.2b — flatten x-aligned runs of bezier anchors to straight
    # lines (cosmetic; matches C's smode dispatch effect on long
    # vertical chains).  Runs AFTER the D4 reshape so any detour
    # the reshape inserted is preserved; the flattening itself
    # guards against newly introducing a cluster crossing (see
    # :func:`flatten_straight_runs`).
    ps = flatten_straight_runs(ps, edges[0], layout)

    # D+.2 — snap virtual-chain nodes to the routed corridor.
    # Safe to call with P.boxes intact (clip_and_install below doesn't
    # touch them).  Only runs for real chain walks (not direct edges).
    if vchain:
        recover_slack(layout, vchain, P)

    # Clip and install for single or multi-edge.
    tail_hw = tail.width / 2
    tail_hh = tail.height / 2
    head_hw = real_head.width / 2
    head_hh = real_head.height / 2
    tail_shape = _node_shape(tail)
    head_shape = _node_shape(real_head)

    cnt = len(edges)
    if cnt == 1:
        clipped = clip_and_install(
            ps,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail_hw, tail_hh=tail_hh, tail_shape=tail_shape,
            head_x=real_head.x, head_y=real_head.y,
            head_hw=head_hw, head_hh=head_hh, head_shape=head_shape,
        )
        _install_points(edges[0], clipped)
        return

    # Multi-edge: offset each copy by Multisep.
    dx = sp.multisep * (cnt - 1) / 2
    for k in range(1, len(ps) - 1):
        ps[k] = Ppoint(ps[k].x - dx, ps[k].y)

    for j in range(cnt):
        le = edges[j]
        pts = [Ppoint(p.x, p.y) for p in ps]
        clipped = clip_and_install(
            pts,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail_hw, tail_hh=tail_hh, tail_shape=tail_shape,
            head_x=real_head.x, head_y=real_head.y,
            head_hw=head_hw, head_hh=head_hh, head_shape=head_shape,
        )
        _install_points(le, clipped)
        if j < cnt - 1:
            for k in range(1, len(ps) - 1):
                ps[k] = Ppoint(ps[k].x + sp.multisep, ps[k].y)


def _copy_box(b: Box) -> Box:
    return Box(b.ll_x, b.ll_y, b.ur_x, b.ur_y)


def _install_points(le, clipped: list[Ppoint]) -> None:
    """Store clipped control points on the edge's route."""
    le.route.points = [(p.x, p.y) for p in clipped]
    le.route.spline_type = "bezier"


def _node_shape(ln) -> str:
    """Get the shape name for a LayoutNode."""
    if ln.virtual:
        return "box"
    if ln.node is not None:
        return ln.node.attributes.get("shape", "ellipse")
    return "ellipse"
