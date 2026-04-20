"""Clip-and-install pipeline for edge splines.

See: /lib/common/splines.c @ 65

The pipeline takes raw spline control points from
:func:`routespl.routesplines`, clips the first and last cubic
segments to the tail and head node boundaries, adjusts for
arrowheads, and stores the result on the edge's
:class:`EdgeRoute`.

Phase C of the splines port.
"""
from __future__ import annotations

import math
from typing import Callable

from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint

MILLIPOINT = 0.001


# ── De Casteljau split ─────────────────────────────────────────────

def bezier_point(V: list, t: float,
                 left: list | None = None,
                 right: list | None = None) -> Ppoint:
    """Evaluate a cubic Bezier at parameter *t* via de Casteljau.

    See: /lib/common/utils.c @ 175

    Optionally fills *left* (4 elements) with the left sub-curve
    ``[V[0], ..., point]`` and *right* (4 elements) with the right
    sub-curve ``[point, ..., V[3]]``.

    *V* is a 4-element list of :class:`Ppoint`.
    """
    degree = 3
    Vt = [[Ppoint(0.0, 0.0)] * (degree + 1) for _ in range(degree + 1)]
    for j in range(degree + 1):
        Vt[0][j] = Ppoint(V[j].x, V[j].y)
    for i in range(1, degree + 1):
        for j in range(degree - i + 1):
            Vt[i][j] = Ppoint(
                (1.0 - t) * Vt[i - 1][j].x + t * Vt[i - 1][j + 1].x,
                (1.0 - t) * Vt[i - 1][j].y + t * Vt[i - 1][j + 1].y,
            )
    if left is not None:
        left.clear()
        for j in range(degree + 1):
            left.append(Ppoint(Vt[j][0].x, Vt[j][0].y))
    if right is not None:
        right.clear()
        for j in range(degree + 1):
            right.append(Ppoint(Vt[degree - j][j].x, Vt[degree - j][j].y))
    return Ppoint(Vt[degree][0].x, Vt[degree][0].y)


# ── Inside-test helpers ────────────────────────────────────────────
# Canonical definitions moved to :mod:`common.shapes`.  Re-export so
# existing call sites continue to resolve.

from gvpy.engines.layout.common.shapes import (  # noqa: F401
    InsideFn,
    ellipse_inside,
    box_inside,
    make_inside_fn,
)


# ── bezier_clip ────────────────────────────────────────────────────

def bezier_clip(inside: InsideFn, sp: list[Ppoint],
                left_inside: bool) -> None:
    """Clip a cubic Bezier to a node boundary using binary search.

    See: /lib/common/splines.c @ 109

    **Mutates** *sp* in place (4 elements).  The ``inside`` callable
    tests whether a point (in **node-local** coordinates) is inside
    the node.  ``left_inside`` indicates that ``sp[0]`` is inside
    (True) or ``sp[3]`` is inside (False).

    After the call, ``sp`` holds the sub-curve from the boundary
    crossing to the outside endpoint.
    """
    seg: list[Ppoint] = [Ppoint(0, 0)] * 4
    best: list[Ppoint] = [Ppoint(0, 0)] * 4

    if left_inside:
        right = seg
        pt = Ppoint(sp[0].x, sp[0].y)
    else:
        right = None
        pt = Ppoint(sp[3].x, sp[3].y)

    found = False
    low = 0.0
    high = 1.0

    while True:
        opt = Ppoint(pt.x, pt.y)
        t = (high + low) / 2.0
        if left_inside:
            pt = bezier_point(sp, t, left=None, right=seg)
        else:
            pt = bezier_point(sp, t, left=seg, right=None)

        if inside(pt):
            if left_inside:
                low = t
            else:
                high = t
            best = [Ppoint(s.x, s.y) for s in seg]
            found = True
        else:
            if left_inside:
                high = t
            else:
                low = t

        if abs(opt.x - pt.x) <= 0.5 and abs(opt.y - pt.y) <= 0.5:
            break

    result = best if found else seg
    for i in range(4):
        sp[i] = Ppoint(result[i].x, result[i].y)


# ── shape_clip0 / shape_clip ──────────────────────────────────────

def shape_clip0(inside: InsideFn, node_x: float, node_y: float,
                curve: list[Ppoint], left_inside: bool) -> None:
    """Clip Bezier to node boundary in graph coordinates.

    See: /lib/common/splines.c @ 162

    Converts *curve* (4 control points in graph coords) to
    node-local coords, calls :func:`bezier_clip`, then converts
    back.  **Mutates** *curve* in place.
    """
    c = [Ppoint(p.x - node_x, p.y - node_y) for p in curve[:4]]
    bezier_clip(inside, c, left_inside)
    for i in range(4):
        curve[i] = Ppoint(c[i].x + node_x, c[i].y + node_y)


def shape_clip(node_x: float, node_y: float,
               hw: float, hh: float, shape: str,
               curve: list[Ppoint]) -> None:
    """Clip Bezier to node shape, auto-detecting which side is inside.

    See: /lib/common/splines.c @ 195

    Tests ``curve[0]`` in node-local coords to decide
    ``left_inside``, then delegates to :func:`shape_clip0`.
    """
    inside = make_inside_fn(shape, hw, hh)
    c0 = Ppoint(curve[0].x - node_x, curve[0].y - node_y)
    left_inside = inside(c0)
    shape_clip0(inside, node_x, node_y, curve, left_inside)


# ── clip_and_install ───────────────────────────────────────────────

def clip_and_install(
    ps: list[Ppoint],
    *,
    tail_x: float, tail_y: float,
    tail_hw: float, tail_hh: float,
    tail_shape: str = "ellipse",
    tail_clip: bool = True,
    head_x: float, head_y: float,
    head_hw: float, head_hh: float,
    head_shape: str = "ellipse",
    head_clip: bool = True,
) -> list[Ppoint]:
    """Clip raw spline points to tail/head node boundaries.

    See: /lib/common/splines.c @ 236

    Takes the raw control points from :func:`routespl.routesplines`
    and clips the first cubic segment to the tail node boundary and
    the last cubic segment to the head node boundary.  Also strips
    any degenerate (zero-length) segments at either end.

    Returns the clipped control-point list.  Arrow adjustment is
    **not** applied here — the caller can apply arrow offsets on the
    returned points if needed.

    Node geometry for each end is passed explicitly:

    - *tail_x*, *tail_y* — node center
    - *tail_hw*, *tail_hh* — half-width, half-height
    - *tail_shape* — shape name (for inside test)
    - *tail_clip* — whether to clip (False if port set clip=False)
    - Same for head.
    """
    pn = len(ps)
    if pn < 4:
        return list(ps)

    start = 0
    end = pn - 4

    # Clip to tail node boundary.
    if tail_clip:
        tail_inside = make_inside_fn(tail_shape, tail_hw, tail_hh)
        while start < pn - 4:
            p2 = Ppoint(ps[start + 3].x - tail_x,
                        ps[start + 3].y - tail_y)
            if not tail_inside(p2):
                break
            start += 3
        seg = [Ppoint(ps[start + i].x, ps[start + i].y) for i in range(4)]
        shape_clip0(tail_inside, tail_x, tail_y, seg, True)
        for i in range(4):
            ps[start + i] = seg[i]

    # Clip to head node boundary.
    if head_clip:
        head_inside = make_inside_fn(head_shape, head_hw, head_hh)
        while end > 0:
            p2 = Ppoint(ps[end].x - head_x, ps[end].y - head_y)
            if not head_inside(p2):
                break
            end -= 3
        seg = [Ppoint(ps[end + i].x, ps[end + i].y) for i in range(4)]
        shape_clip0(head_inside, head_x, head_y, seg, False)
        for i in range(4):
            ps[end + i] = seg[i]

    # Strip degenerate zero-length segments from the front.
    while start < pn - 4:
        if not _approx_eq(ps[start], ps[start + 3]):
            break
        start += 3

    # Strip degenerate zero-length segments from the back.
    while end > 0:
        if not _approx_eq(ps[end], ps[end + 3]):
            break
        end -= 3

    return [Ppoint(ps[i].x, ps[i].y) for i in range(start, end + 4)]


def _approx_eq(a: Ppoint, b: Ppoint) -> bool:
    """See: /lib/common/geom.h @ 71"""
    return abs(a.x - b.x) < MILLIPOINT and abs(a.y - b.y) < MILLIPOINT


# ── conc_slope ─────────────────────────────────────────────────────

def conc_slope(node_x: float, node_y: float,
               in_xs: list[float], in_ys: list[float],
               out_xs: list[float], out_ys: list[float]) -> float:
    """Compute the mean slope at a concentrator node.

    See: /lib/common/splines.c @ 318

    *in_xs*/*in_ys* are the x/y coordinates of tail nodes of
    incoming edges.  *out_xs*/*out_ys* are the x/y coords of head
    nodes of outgoing edges.

    Returns the average of the incoming and outgoing mean slopes
    (in radians).
    """
    cnt_in = len(in_xs)
    cnt_out = len(out_xs)
    if cnt_in == 0 or cnt_out == 0:
        return -math.pi / 2  # straight down fallback

    s_in = sum(in_xs)
    s_out = sum(out_xs)

    x1 = node_x - s_in / cnt_in
    y1 = node_y - in_ys[0]
    m_in = math.atan2(y1, x1)

    x2 = s_out / cnt_out - node_x
    y2 = out_ys[0] - node_y
    m_out = math.atan2(y2, x2)

    return (m_in + m_out) / 2.0
