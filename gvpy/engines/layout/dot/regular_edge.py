"""Regular-edge routing via box corridors.

C analogue: ``lib/dotgen/dotsplines.c`` — ``make_regular_edge`` and
its helpers ``makeregularend``, ``adjustregularpath``,
``completeregularpath``.

Phase D of the splines port.  Replaces the heuristic
``route_regular_edge`` with a C-matching implementation:
``beginpath`` / ``rank_box`` / ``endpath`` / ``completeregularpath``
/ ``routesplines`` / ``clip_and_install``.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from gvpy.engines.layout.dot.clip import clip_and_install
from gvpy.engines.layout.dot.path import (
    Box, Path, PathEnd, SplineInfo,
    BOTTOM, TOP, REGULAREDGE,
    MINW, HALFMINW,
    add_box, beginpath, endpath,
)
from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint
from gvpy.engines.layout.dot.routespl import routesplines, routepolylines

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.edge_route import EdgeRoute

# Avoid importing these at module level to prevent circular deps.
# They are accessed via the ``layout`` object or late-imported.

EDGETYPE_SPLINE = 5 << 1
EDGETYPE_LINE = 1 << 1
EDGETYPE_PLINE = 3 << 1


# ── makeregularend ─────────────────────────────────────────────────

def makeregularend(b: Box, side: int, y: float) -> Box:
    """Create a box between a node box and interrank space.

    C analogue: ``dotsplines.c:makeregularend`` lines 1988-1994.
    """
    if side == BOTTOM:
        return Box(ll_x=b.ll_x, ll_y=y, ur_x=b.ur_x, ur_y=b.ll_y)
    return Box(ll_x=b.ll_x, ll_y=b.ur_y, ur_x=b.ur_x, ur_y=y)


# ── adjustregularpath ──────────────────────────────────────────────

def adjustregularpath(P: Path, fb: int, lb: int) -> None:
    """Widen narrow boxes to MINW and ensure minimum overlap.

    C analogue: ``dotsplines.c:adjustregularpath`` lines 2010-2043.
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


# ── completeregularpath ────────────────────────────────────────────

def completeregularpath(P: Path, tendp: PathEnd, hendp: PathEnd,
                        boxes: list[Box]) -> None:
    """Assemble the full box corridor from tail end + path + head end.

    C analogue: ``dotsplines.c:completeregularpath`` lines 1950-1982.

    Simplified: ``top_bound``/``bot_bound`` neighbor checks are
    skipped — they guard against corrupted parallel-edge state and
    are an optimization, not required for correctness.
    """
    P.boxes.clear()
    P.nbox = 0
    for i in range(tendp.boxn):
        add_box(P, tendp.boxes[i])
    fb = P.nbox + 1
    lb = fb + len(boxes) - 3
    for b in boxes:
        add_box(P, b)
    for i in range(hendp.boxn - 1, -1, -1):
        add_box(P, hendp.boxes[i])
    adjustregularpath(P, fb, lb)


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

    C analogue: ``dotsplines.c:make_regular_edge`` lines 1736-1946.

    Takes a list of parallel ``LayoutEdge`` objects sharing the same
    tail→head path through ranks.  For each edge, builds the box
    corridor (``beginpath`` → ``rank_box`` → ``maximal_bbox`` →
    ``endpath``), routes a spline through it
    (``routesplines``/``routepolylines``), clips to node boundaries
    (``clip_and_install``), and stores the result on the edge's
    ``EdgeRoute``.

    Multi-edge offset (``Multisep``) is applied when ``len(edges) > 1``.
    """
    from gvpy.engines.layout.dot.splines import (
        maximal_bbox, rank_box, spline_merge,
        _node_out_edges, _node_in_edges,
    )
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
    completeregularpath(P, tend, hend, corridor_boxes)

    if is_spline:
        ps = routesplines(P)
    else:
        ps = routepolylines(P)
        if ps and et == EDGETYPE_LINE and len(ps) > 4:
            ps[1] = Ppoint(ps[0].x, ps[0].y)
            ps[3] = Ppoint(ps[-1].x, ps[-1].y)
            ps[2] = Ppoint(ps[-1].x, ps[-1].y)
            ps = ps[:4]

    if not ps:
        return

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
