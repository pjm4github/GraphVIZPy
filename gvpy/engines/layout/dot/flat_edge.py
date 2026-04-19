"""Flat (same-rank) edge routing via box corridors.

C analogue: ``lib/dotgen/dotsplines.c`` — ``make_flat_edge`` and
its helpers ``makeFlatEnd``, ``makeBottomFlatEnd``,
``makeSimpleFlat``, ``make_flat_labeled_edge``,
``make_flat_bottom_edges``.

Phase E of the splines port.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from gvpy.engines.layout.dot.clip import clip_and_install
from gvpy.engines.layout.dot.path import (
    Box, Path, PathEnd, SplineInfo,
    BOTTOM, TOP, FLATEDGE,
    add_box, beginpath, endpath,
)
from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint
from gvpy.engines.layout.dot.regular_edge import makeregularend, _node_geom, _node_shape, _install_points
from gvpy.engines.layout.dot.routespl import routesplines, routepolylines

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import LayoutEdge, LayoutNode

EDGETYPE_SPLINE = 5 << 1
EDGETYPE_LINE = 1 << 1
EDGETYPE_PLINE = 3 << 1


def _compass_to_side(port_str: str) -> int:
    """Map a compass port string to a side bitmask."""
    if not port_str:
        return 0
    c = port_str.split(":")[-1] if ":" in port_str else port_str
    c = c.strip().lower()
    if c in ("s", "sw", "se"):
        return BOTTOM
    if c in ("n", "nw", "ne"):
        return TOP
    return 0


# ── makeFlatEnd / makeBottomFlatEnd ────────────────────────────────

def _make_flat_end(layout, sp: SplineInfo, P: Path, ln, le,
                   endp: PathEnd, is_begin: bool, side: int) -> None:
    """Set up path endpoint for a flat edge.

    C analogue: ``makeFlatEnd`` (lines 1319-1332) when side=TOP,
    ``makeBottomFlatEnd`` (lines 1334-1348) when side=BOTTOM.
    """
    from gvpy.engines.layout.dot.splines import maximal_bbox

    endp.nb = maximal_bbox(layout, sp, ln, None, None)
    endp.sidemask = side

    geom = _node_geom(ln)
    geom["ranksep"] = layout.ranksep

    if is_begin:
        beginpath(P, FLATEDGE, endp, False, **geom)
    else:
        endpath(P, FLATEDGE, endp, False, **geom)

    b = Box(endp.boxes[endp.boxn - 1].ll_x, endp.boxes[endp.boxn - 1].ll_y,
            endp.boxes[endp.boxn - 1].ur_x, endp.boxes[endp.boxn - 1].ur_y)

    if side == TOP:
        ht2 = layout._rank_ht2.get(ln.rank, ln.height / 2)
        b = makeregularend(b, TOP, ln.y - ht2)
    else:
        ht1 = layout._rank_ht1.get(ln.rank, ln.height / 2)
        b = makeregularend(b, BOTTOM, ln.y + ht1)

    if b.ll_x < b.ur_x and b.ll_y < b.ur_y:
        endp.boxes.append(b)
        endp.boxn += 1


# ── edgelblcmpfn / makeSimpleFlatLabels (E+.1) ─────────────────────

LBL_SPACE = 6.0  # C ``dotsplines.c:973`` — gap in points between stacked labels.


def _flat_label_size(layout, le) -> tuple[float, float]:
    """Return the (width, height) of an edge label using the layout's estimator."""
    if not le.label:
        return 0.0, 0.0
    fs = 14.0
    if le.edge is not None:
        try:
            fs = float(le.edge.attributes.get("labelfontsize",
                       le.edge.attributes.get("fontsize", "14")))
        except ValueError:
            fs = 14.0
    return layout._estimate_label_size(le.label, fs)


def edge_label_key(layout, le) -> tuple:
    """Sort key mirroring C ``edgelblcmpfn`` lines 943-971.

    Lexicographic order:
      1. labeled edges before unlabeled
      2. wider labels first
      3. taller labels first

    Python uses a key function rather than a cmp — the tuple
    ``(has_label_flag, -width, -height)`` sorts ascending to match C's
    descending-by-size-then-has-label semantics.
    """
    if not le.label:
        return (1, 0.0, 0.0)
    w, h = _flat_label_size(layout, le)
    return (0, -w, -h)


def make_simple_flat_labels(layout, edges: list, tail, head, et: int) -> None:
    """Route adjacent flat edges with labels using alternating up/down detours.

    C analogue: ``lib/dotgen/dotsplines.c:makeSimpleFlatLabels`` lines 980-1108.

    Called from :func:`make_flat_edge` when two nodes on the same rank
    have multiple parallel edges and at least one carries a label.  The
    algorithm:

    1. Sort edges by :func:`edge_label_key` (labeled first, biggest first).
    2. First edge (``i=0``) routes as a centered straight bezier; its
       label sits directly above the edge line.
    3. Subsequent labeled edges alternate:

       - odd ``i`` → detour below the line, label below
       - even ``i`` → detour above the line, label above (wrapping
         around the first edge's label)

    4. Unlabeled edges fill any remaining slots using the same
       alternating detour shape with a wider default corridor.

    Coordinate convention
    ---------------------
    C is y-up, Python dot-layout is y-down.  Variable ``miny`` in C
    (smallest y = farthest below in y-up) becomes Python ``maxy``
    (largest y = farthest below in y-down), and vice versa.  Point
    offsets on the detour polygon flip sign accordingly.  The polygon
    is passed to :func:`simple_spline_route` for shortest-path
    routing; pathplan tolerates either orientation since it
    triangulates the polygon interior.
    """
    from gvpy.engines.layout.dot.routespl import simple_spline_route
    from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoly

    if not edges:
        return

    earray = sorted(edges, key=lambda e: edge_label_key(layout, e))
    n_lbls = sum(1 for le in earray if le.label)
    cnt = len(earray)
    if n_lbls == 0:
        make_simple_flat(layout, edges, tail, head, et)
        return

    tp = (tail.x, tail.y)
    hp = (head.x, head.y)
    tail_hw = tail.width / 2
    tail_hh = tail.height / 2
    head_hw = head.width / 2
    head_hh = head.height / 2
    tail_shape = _node_shape(tail)
    head_shape = _node_shape(head)

    leftend = tp[0] + tail_hw
    rightend = hp[0] - head_hw
    ctrx = (leftend + rightend) / 2.0

    def _clip_install(le, pts):
        pts_pp = [p if isinstance(p, Ppoint) else Ppoint(p[0], p[1]) for p in pts]
        clipped = clip_and_install(
            pts_pp,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail_hw, tail_hh=tail_hh, tail_shape=tail_shape,
            head_x=head.x, head_y=head.y,
            head_hw=head_hw, head_hh=head_hh, head_shape=head_shape,
        )
        _install_points(le, clipped)

    # ── First edge: straight bezier, label centered above. ──
    e0 = earray[0]
    w0, h0 = _flat_label_size(layout, e0)
    _clip_install(e0, [tp, tp, hp, hp])
    # Label above edge line (y-down: smaller y = above).
    e0.label_pos = (round(ctrx, 2), round(tp[1] - (h0 + LBL_SPACE) / 2.0, 2))

    # Stacking state (Python y-down):
    #   maxy = farthest-below y of below-stack (initially "just above
    #          edge" as a staging value, matches C miny initialization)
    #   miny = farthest-above y of above-stack (consumed by the first
    #          edge's label)
    maxy = tp[1] - LBL_SPACE / 2.0   # C: miny = tp.y + LBL_SPACE/2
    miny = maxy - h0                 # C: maxy = miny + dimen.y

    uminx = ctrx - w0 / 2.0
    umaxx = ctrx + w0 / 2.0
    lminx = 0.0
    lmaxx = 0.0

    def _route_and_install(e, points, polyline):
        poly = Ppoly(ps=[Ppoint(p[0], p[1]) for p in points])
        ps = simple_spline_route((tp[0], tp[1]), (hp[0], hp[1]),
                                 poly, polyline=polyline)
        if not ps:
            return False
        _clip_install(e, ps)
        return True

    polyline = (et == EDGETYPE_PLINE)

    # ── Labeled alternating loop (i=1..n_lbls-1). ──
    last_i = 0
    for i in range(1, n_lbls):
        e = earray[i]
        w, h = _flat_label_size(layout, e)
        if i % 2 == 1:  # down (below edge line)
            if i == 1:
                lminx = ctrx - w / 2.0
                lmaxx = ctrx + w / 2.0
            maxy += LBL_SPACE + h    # C: miny -= LBL_SPACE + dimen.y
            points = [
                tp,
                (tp[0], maxy + LBL_SPACE),
                (hp[0], maxy + LBL_SPACE),
                hp,
                (lmaxx, hp[1]),
                (lmaxx, maxy),
                (lminx, maxy),
                (lminx, tp[1]),
            ]
            ctry = maxy - h / 2.0    # C: miny + dimen.y/2
        else:           # up (above edge line)
            points = [
                tp,
                (uminx, tp[1]),
                (uminx, miny),
                (umaxx, miny),
                (umaxx, hp[1]),
                hp,
                (hp[0], miny - LBL_SPACE),
                (tp[0], miny - LBL_SPACE),
            ]
            ctry = miny - h / 2.0 - LBL_SPACE  # C: maxy + h/2 + LBL_SPACE
            miny -= h + LBL_SPACE              # C: maxy += h + LBL_SPACE
        if not _route_and_install(e, points, polyline):
            return
        e.label_pos = (round(ctrx, 2), round(ctry, 2))
        last_i = i

    # ── Unlabeled edges (i=n_lbls..cnt-1). ──
    for i in range(n_lbls, cnt):
        e = earray[i]
        if i % 2 == 1:
            if i == 1:
                lminx = (2 * leftend + rightend) / 3.0
                lmaxx = (leftend + 2 * rightend) / 3.0
            maxy += LBL_SPACE
            points = [
                tp,
                (tp[0], maxy + LBL_SPACE),
                (hp[0], maxy + LBL_SPACE),
                hp,
                (lmaxx, hp[1]),
                (lmaxx, maxy),
                (lminx, maxy),
                (lminx, tp[1]),
            ]
        else:
            points = [
                tp,
                (uminx, tp[1]),
                (uminx, miny),
                (umaxx, miny),
                (umaxx, hp[1]),
                hp,
                (hp[0], miny - LBL_SPACE),
                (tp[0], miny - LBL_SPACE),
            ]
            miny -= LBL_SPACE
        if not _route_and_install(e, points, polyline):
            return


# ── makeSimpleFlat ─────────────────────────────────────────────────

def make_simple_flat(layout, edges: list, tail, head, et: int) -> None:
    """Route flat edges between adjacent nodes as straight beziers.

    C analogue: ``makeSimpleFlat`` lines 1111-1146.
    """
    if not edges:
        return
    le0 = edges[0]
    tp = (tail.x, tail.y)
    hp = (head.x, head.y)

    cnt = len(edges)
    stepy = tail.height / (cnt - 1) if cnt > 1 else 0.0
    dy = tp[1] - (tail.height / 2.0 if cnt > 1 else 0.0)

    for i, le in enumerate(edges):
        if et == EDGETYPE_SPLINE or et == EDGETYPE_LINE:
            ps = [
                Ppoint(tp[0], tp[1]),
                Ppoint((2 * tp[0] + hp[0]) / 3, dy),
                Ppoint((2 * hp[0] + tp[0]) / 3, dy),
                Ppoint(hp[0], hp[1]),
            ]
        else:
            ps = [
                Ppoint(tp[0], tp[1]),
                Ppoint(tp[0], tp[1]),
                Ppoint((2 * tp[0] + hp[0]) / 3, dy),
                Ppoint((2 * tp[0] + hp[0]) / 3, dy),
                Ppoint((2 * tp[0] + hp[0]) / 3, dy),
                Ppoint((2 * hp[0] + tp[0]) / 3, dy),
                Ppoint((2 * hp[0] + tp[0]) / 3, dy),
                Ppoint((2 * hp[0] + tp[0]) / 3, dy),
                Ppoint(hp[0], hp[1]),
                Ppoint(hp[0], hp[1]),
            ]
        dy += stepy
        clipped = clip_and_install(
            ps,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail.width / 2, tail_hh=tail.height / 2,
            tail_shape=_node_shape(tail),
            head_x=head.x, head_y=head.y,
            head_hw=head.width / 2, head_hh=head.height / 2,
            head_shape=_node_shape(head),
        )
        _install_points(le, clipped)


# ── make_flat_labeled_edge ─────────────────────────────────────────

def make_flat_labeled_edge(layout, sp: SplineInfo, P: Path,
                           le, et: int) -> None:
    """Route a single flat edge with a label via a 3-box corridor above.

    C analogue: ``make_flat_labeled_edge`` lines 1350-1452.
    """
    tail = layout.lnodes.get(le.tail_name)
    head = layout.lnodes.get(le.head_name)
    if tail is None or head is None:
        return

    # Find the label virtual node (if any).
    ln_name = getattr(le, '_flat_label_vnode', None)
    ln_node = layout.lnodes.get(ln_name) if ln_name else None

    if et == EDGETYPE_LINE or ln_node is None:
        # Line mode or no label node: simple polyline through label position.
        tp = Ppoint(tail.x, tail.y)
        hp = Ppoint(head.x, head.y)
        if ln_node:
            lp_y = ln_node.y + ln_node.height / 2
        else:
            lp_y = tail.y - layout.ranksep / 2
        ps = [
            tp, Ppoint(tp.x, tp.y),
            Ppoint(tp.x, lp_y), Ppoint((tp.x + hp.x) / 2, lp_y),
            Ppoint(hp.x, lp_y), Ppoint(hp.x, hp.y), hp,
        ]
        clipped = clip_and_install(
            ps,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail.width / 2, tail_hh=tail.height / 2,
            tail_shape=_node_shape(tail),
            head_x=head.x, head_y=head.y,
            head_hw=head.width / 2, head_hh=head.height / 2,
            head_shape=_node_shape(head),
        )
        _install_points(le, clipped)
        return

    # Spline mode: build a 3-box corridor above the rank through the
    # label node's bounding box.
    lb = Box(
        ll_x=ln_node.x - ln_node.width / 2,
        ll_y=ln_node.y - ln_node.height / 2,
        ur_x=ln_node.x + ln_node.width / 2,
        ur_y=ln_node.y + ln_node.height / 2,
    )
    ht1 = layout._rank_ht1.get(tail.rank, tail.height / 2)
    ydelta = (ln_node.y - ht1 - tail.y + layout._rank_ht2.get(tail.rank, tail.height / 2))
    ydelta /= 6
    lb.ll_y = lb.ur_y - max(5, ydelta)

    tend = PathEnd()
    hend = PathEnd()
    _make_flat_end(layout, sp, P, tail, le, tend, True, TOP)
    _make_flat_end(layout, sp, P, head, le, hend, False, TOP)

    boxes = [
        Box(
            ll_x=tend.boxes[tend.boxn - 1].ll_x,
            ll_y=tend.boxes[tend.boxn - 1].ur_y,
            ur_x=lb.ll_x,
            ur_y=lb.ll_y,
        ),
        Box(
            ll_x=tend.boxes[tend.boxn - 1].ll_x,
            ll_y=lb.ll_y,
            ur_x=hend.boxes[hend.boxn - 1].ur_x,
            ur_y=lb.ur_y,
        ),
        Box(
            ll_x=lb.ur_x,
            ll_y=hend.boxes[hend.boxn - 1].ur_y,
            ur_x=hend.boxes[hend.boxn - 1].ur_x,
            ur_y=lb.ll_y,
        ),
    ]

    P.boxes.clear()
    P.nbox = 0
    for i in range(tend.boxn):
        add_box(P, tend.boxes[i])
    for b in boxes:
        add_box(P, b)
    for i in range(hend.boxn - 1, -1, -1):
        add_box(P, hend.boxes[i])

    if et == EDGETYPE_SPLINE:
        ps = routesplines(P)
    else:
        ps = routepolylines(P)
    if not ps:
        return

    clipped = clip_and_install(
        ps,
        tail_x=tail.x, tail_y=tail.y,
        tail_hw=tail.width / 2, tail_hh=tail.height / 2,
        tail_shape=_node_shape(tail),
        head_x=head.x, head_y=head.y,
        head_hw=head.width / 2, head_hh=head.height / 2,
        head_shape=_node_shape(head),
    )
    _install_points(le, clipped)


# ── make_flat_bottom_edges ─────────────────────────────────────────

def make_flat_bottom_edges(layout, sp: SplineInfo, P: Path,
                           edges: list, et: int) -> None:
    """Route flat edges with south-side ports via a corridor below.

    C analogue: ``make_flat_bottom_edges`` lines 1454-1526.
    """
    if not edges:
        return
    le0 = edges[0]
    tail = layout.lnodes.get(le0.tail_name)
    head = layout.lnodes.get(le0.head_name)
    if tail is None or head is None:
        return

    # In y-down, "below" = larger y.
    r = tail.rank
    node_bot = tail.y + tail.height / 2  # visual bottom of node
    next_r = r + 1
    if next_r in layout.ranks and layout.ranks[next_r]:
        next_y = layout.lnodes[layout.ranks[next_r][0]].y
        next_top = next_y - layout._rank_ht2.get(next_r, 18)
        vspace = next_top - node_bot
    else:
        vspace = layout.ranksep

    vspace = max(vspace, 10.0)
    cnt = len(edges)
    stepx = sp.multisep / (cnt + 1)
    stepy = vspace / (cnt + 1)

    left_x = min(tail.x - tail.width / 2, head.x - head.width / 2)
    right_x = max(tail.x + tail.width / 2, head.x + head.width / 2)

    for i, le in enumerate(edges):
        arc_base = node_bot
        arc_step = (i + 1) * stepy
        arc_bot = arc_base + arc_step + stepy

        P.boxes.clear()
        P.nbox = 0

        add_box(P, Box(
            ll_x=tail.x - tail.width / 2,
            ll_y=tail.y - tail.height / 2,
            ur_x=tail.x + tail.width / 2,
            ur_y=arc_base + arc_step,
        ))
        add_box(P, Box(
            ll_x=left_x - (i + 1) * stepx,
            ll_y=arc_base + arc_step,
            ur_x=tail.x + tail.width / 2 + (i + 1) * stepx,
            ur_y=arc_bot,
        ))
        add_box(P, Box(
            ll_x=left_x - (i + 1) * stepx,
            ll_y=arc_bot,
            ur_x=right_x + (i + 1) * stepx,
            ur_y=arc_bot + stepy,
        ))
        add_box(P, Box(
            ll_x=head.x - head.width / 2 - (i + 1) * stepx,
            ll_y=arc_base + arc_step,
            ur_x=right_x + (i + 1) * stepx,
            ur_y=arc_bot,
        ))
        add_box(P, Box(
            ll_x=head.x - head.width / 2,
            ll_y=head.y - head.height / 2,
            ur_x=head.x + head.width / 2,
            ur_y=arc_base + arc_step,
        ))

        is_spline = et == EDGETYPE_SPLINE
        ps = routesplines(P) if is_spline else routepolylines(P)
        if not ps:
            return

        clipped = clip_and_install(
            ps,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail.width / 2, tail_hh=tail.height / 2,
            tail_shape=_node_shape(tail),
            head_x=head.x, head_y=head.y,
            head_hw=head.width / 2, head_hh=head.height / 2,
            head_shape=_node_shape(head),
        )
        _install_points(le, clipped)


# ── make_flat_edge (dispatcher) ────────────────────────────────────

def make_flat_edge(layout, sp: SplineInfo, P: Path,
                   edges: list, et: int) -> None:
    """Route flat (same-rank) edges.

    C analogue: ``make_flat_edge`` lines 1538-1651.

    Dispatches to one of:
    - ``make_simple_flat`` — adjacent nodes, no labels (C ``makeSimpleFlat``)
    - ``make_flat_labeled_edge`` — single edge with label
    - ``make_flat_bottom_edges`` — south-port edges
    - top-arc corridor (the main body of ``make_flat_edge``)

    ``make_flat_adj_edges`` (the recursive case for adjacent nodes
    with ports/labels) is deferred — falls back to ``make_simple_flat``.
    """
    from gvpy.engines.layout.dot.path import BWDEDGE
    from gvpy.engines.layout.dot.splines import maximal_bbox

    if not edges:
        return
    le0 = edges[0]

    # Normalize to left-to-right.
    tail_name = le0.tail_name
    head_name = le0.head_name
    if le0.tree_index & BWDEDGE:
        tail_name, head_name = head_name, tail_name

    tail = layout.lnodes.get(tail_name)
    head = layout.lnodes.get(head_name)
    if tail is None or head is None:
        return

    # Check adjacency.  C uses the pre-computed ED_adjacent flag
    # (set by flat.c when no real nodes exist between the endpoints).
    # Python approximates: adjacent = order diff 1, no ports.
    any_label = any(le.label for le in edges)
    any_ports = any(le.tailport or le.headport for le in edges)
    is_adjacent_no_labels = (abs(tail.order - head.order) == 1
                             and not any_ports and not any_label)
    is_adjacent_with_labels = (abs(tail.order - head.order) == 1
                                and not any_ports and any_label
                                and len(edges) > 1)

    if is_adjacent_no_labels:
        make_simple_flat(layout, edges, tail, head, et)
        return

    if is_adjacent_with_labels:
        # E+.1 — alternating up/down stacking for labeled adjacent edges.
        make_simple_flat_labels(layout, edges, tail, head, et)
        return

    if le0.label:
        make_flat_labeled_edge(layout, sp, P, le0, et)
        return

    if et == EDGETYPE_LINE:
        make_simple_flat(layout, edges, tail, head, et)
        return

    # Check for bottom-port routing by inspecting port compass strings.
    tside = _compass_to_side(le0.tailport)
    hside = _compass_to_side(le0.headport)

    if (tside == BOTTOM and hside != TOP) or (hside == BOTTOM and tside != TOP):
        make_flat_bottom_edges(layout, sp, P, edges, et)
        return

    # Default: 3-box corridor above the rank.
    # In y-down, "above" = smaller y.
    cnt = len(edges)
    r = tail.rank

    # Compute vertical space above the rank (y-down: toward smaller y).
    node_top = tail.y - tail.height / 2  # visual top of node
    prev_r = r - 1
    if prev_r in layout.ranks and layout.ranks[prev_r]:
        prev_y = layout.lnodes[layout.ranks[prev_r][0]].y
        prev_bot = prev_y + layout._rank_ht1.get(prev_r, 18)
        vspace = node_top - prev_bot
    else:
        vspace = layout.ranksep

    vspace = max(vspace, 10.0)
    stepx = sp.multisep / (cnt + 1)
    stepy = vspace / (cnt + 1)

    # Compute corridor positions directly from node geometry.
    # Left/right x extents from the two nodes.
    left_x = min(tail.x - tail.width / 2, head.x - head.width / 2)
    right_x = max(tail.x + tail.width / 2, head.x + head.width / 2)

    for i, le in enumerate(edges):
        arc_base = node_top  # start from visual top of nodes
        arc_step = (i + 1) * stepy
        arc_top = arc_base - arc_step - stepy  # highest point of corridor

        P.boxes.clear()
        P.nbox = 0

        # Tail endpoint box.
        add_box(P, Box(
            ll_x=tail.x - tail.width / 2,
            ll_y=arc_base - arc_step,
            ur_x=tail.x + tail.width / 2,
            ur_y=tail.y + tail.height / 2,
        ))
        # Left transition: from tail box up to corridor level.
        add_box(P, Box(
            ll_x=left_x - (i + 1) * stepx,
            ll_y=arc_top,
            ur_x=tail.x + tail.width / 2 + (i + 1) * stepx,
            ur_y=arc_base - arc_step,
        ))
        # Horizontal corridor span at the top of the arc.
        add_box(P, Box(
            ll_x=left_x - (i + 1) * stepx,
            ll_y=arc_top - stepy,
            ur_x=right_x + (i + 1) * stepx,
            ur_y=arc_top,
        ))
        # Right transition: from corridor level down to head box.
        add_box(P, Box(
            ll_x=head.x - head.width / 2 - (i + 1) * stepx,
            ll_y=arc_top,
            ur_x=right_x + (i + 1) * stepx,
            ur_y=arc_base - arc_step,
        ))
        # Head endpoint box.
        add_box(P, Box(
            ll_x=head.x - head.width / 2,
            ll_y=arc_base - arc_step,
            ur_x=head.x + head.width / 2,
            ur_y=head.y + head.height / 2,
        ))

        is_spline = et == EDGETYPE_SPLINE
        ps = routesplines(P) if is_spline else routepolylines(P)
        if not ps:
            return

        clipped = clip_and_install(
            ps,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail.width / 2, tail_hh=tail.height / 2,
            tail_shape=_node_shape(tail),
            head_x=head.x, head_y=head.y,
            head_hw=head.width / 2, head_hh=head.height / 2,
            head_shape=_node_shape(head),
        )
        _install_points(le, clipped)
