"""Box-corridor spline router.

See: /lib/common/routespl.c @ 294

Converts a sequence of contiguous axis-aligned boxes (the "box corridor"
built by ``beginpath``/``rank_box``/``endpath`` in ``dotsplines.c``) into
a smooth cubic-Bezier spline.  The pipeline is:

1.  :func:`checkpath` — validate and repair minor box-chain errors
    (degenerate boxes, non-touching neighbours, overlapping pairs).
2.  Build a containing polygon from the box chain (forward walk =
    left side, backward walk = right side).
3.  :func:`Pshortestpath` — find the shortest polyline through the
    polygon from start to end.
4.  :func:`Proutespline` — fit a smooth cubic Bezier to the polyline
    while staying inside the polygon.
5.  :func:`limit_boxes` — sample the resulting spline with de Casteljau
    subdivision and tighten each box's x-extent to the spline's
    actual footprint, freeing space for neighbouring edges.

The public entry points are :func:`routesplines` (curved) and
:func:`routepolylines` (polyline), both delegating to
:func:`routesplines_`.  :func:`simple_spline_route` provides a
simpler interface for routing through a single polygon without a
box corridor.

Phase B step B6 of the splines port.
"""
from __future__ import annotations

import math
import sys

from gvpy.engines.layout.dot.path import Box, Path
from gvpy.engines.layout.dot.pathplan.pathgeom import Pedge, Ppoint, Ppoly, Ppolyline
from gvpy.engines.layout.dot.pathplan.route import Proutespline
from gvpy.engines.layout.dot.pathplan.shortest import Pshortestpath
from gvpy.engines.layout.dot.pathplan.util import make_polyline


# ── Constants ──────────────────────────────────────────────────────
FUDGE = 0.0001
INIT_DELTA = 10
LOOP_TRIES = 15


# ── overlap ────────────────────────────────────────────────────────

def overlap(i0: float, i1: float, j0: float, j1: float) -> float:
    """Return the overlap length between intervals [i0,i1) and [j0,j1).

    See: /lib/common/routespl.c @ 606
    """
    if i1 <= j0:
        return 0.0
    if i0 >= j1:
        return 0.0
    if i0 <= j0 and i1 >= j1:
        return i1 - i0
    if j0 <= i0 and j1 >= i1:
        return j1 - j0
    if j0 <= i0 <= j1:
        return j1 - i0
    return i1 - j0


# ── checkpath ──────────────────────────────────────────────────────

def checkpath(boxes: list[Box], pp: Path) -> tuple[int, list[Box]]:
    """Validate and repair the box corridor.

    See: /lib/common/routespl.c @ 635

    Returns ``(status, repaired_boxes)`` where status is 0 on success,
    1 on failure.  The returned list may be shorter than the input
    (degenerate boxes are removed).  ``pp.start`` and ``pp.end`` are
    clamped to the first/last box if they fall outside.
    """
    # Remove degenerate boxes.
    kept: list[Box] = []
    for b in boxes:
        if abs(b.ll_y - b.ur_y) < 0.01:
            continue
        if abs(b.ll_x - b.ur_x) < 0.01:
            continue
        kept.append(b)
    boxes = kept
    boxn = len(boxes)

    if boxn == 0:
        print("in checkpath, no valid boxes", file=sys.stderr)
        return (1, boxes)

    ba = boxes[0]
    if ba.ll_x > ba.ur_x or ba.ll_y > ba.ur_y:
        print("in checkpath, box 0 has LL coord > UR coord", file=sys.stderr)
        return (1, boxes)

    for bi in range(boxn - 1):
        ba = boxes[bi]
        bb = boxes[bi + 1]
        if bb.ll_x > bb.ur_x or bb.ll_y > bb.ur_y:
            print(f"in checkpath, box {bi + 1} has LL coord > UR coord",
                  file=sys.stderr)
            return (1, boxes)

        l = 1 if ba.ur_x < bb.ll_x else 0
        r = 1 if ba.ll_x > bb.ur_x else 0
        d = 1 if ba.ur_y < bb.ll_y else 0
        u = 1 if ba.ll_y > bb.ur_y else 0
        errs = l + r + d + u

        if errs > 0:
            # Swap coordinates to force touching on the worst axis.
            if l == 1:
                ba.ur_x, bb.ll_x = bb.ll_x, ba.ur_x
                l = 0
            elif r == 1:
                ba.ll_x, bb.ur_x = bb.ur_x, ba.ll_x
                r = 0
            elif d == 1:
                ba.ur_y, bb.ll_y = bb.ll_y, ba.ur_y
                d = 0
            elif u == 1:
                ba.ll_y, bb.ur_y = bb.ur_y, ba.ll_y
                u = 0

            for _ in range(errs - 1):
                if l == 1:
                    xy = (ba.ur_x + bb.ll_x) / 2.0 + 0.5
                    ba.ur_x = bb.ll_x = xy
                    l = 0
                elif r == 1:
                    xy = (ba.ll_x + bb.ur_x) / 2.0 + 0.5
                    ba.ll_x = bb.ur_x = xy
                    r = 0
                elif d == 1:
                    xy = (ba.ur_y + bb.ll_y) / 2.0 + 0.5
                    ba.ur_y = bb.ll_y = xy
                    d = 0
                elif u == 1:
                    xy = (ba.ll_y + bb.ur_y) / 2.0 + 0.5
                    ba.ll_y = bb.ur_y = xy
                    u = 0

        # Check for overlapping boxes.
        xoverlap = overlap(ba.ll_x, ba.ur_x, bb.ll_x, bb.ur_x)
        yoverlap = overlap(ba.ll_y, ba.ur_y, bb.ll_y, bb.ur_y)
        if xoverlap > 0 and yoverlap > 0:
            if xoverlap < yoverlap:
                if ba.ur_x - ba.ll_x > bb.ur_x - bb.ll_x:
                    if ba.ur_x < bb.ur_x:
                        ba.ur_x = bb.ll_x
                    else:
                        ba.ll_x = bb.ur_x
                else:
                    if ba.ur_x < bb.ur_x:
                        bb.ll_x = ba.ur_x
                    else:
                        bb.ur_x = ba.ll_x
            else:
                if ba.ur_y - ba.ll_y > bb.ur_y - bb.ll_y:
                    if ba.ur_y < bb.ur_y:
                        ba.ur_y = bb.ll_y
                    else:
                        ba.ll_y = bb.ur_y
                else:
                    if ba.ur_y < bb.ur_y:
                        bb.ll_y = ba.ur_y
                    else:
                        bb.ur_y = ba.ll_y

    # Clamp start point to first box.
    sx, sy = pp.start.np
    b0 = boxes[0]
    if sx < b0.ll_x or sx > b0.ur_x or sy < b0.ll_y or sy > b0.ur_y:
        sx = max(sx, b0.ll_x)
        sx = min(sx, b0.ur_x)
        sy = max(sy, b0.ll_y)
        sy = min(sy, b0.ur_y)
        pp.start.np = (sx, sy)

    # Clamp end point to last box.
    ex, ey = pp.end.np
    bn = boxes[-1]
    if ex < bn.ll_x or ex > bn.ur_x or ey < bn.ll_y or ey > bn.ur_y:
        ex = max(ex, bn.ll_x)
        ex = min(ex, bn.ur_x)
        ey = max(ey, bn.ll_y)
        ey = min(ey, bn.ur_y)
        pp.end.np = (ex, ey)

    return (0, boxes)


# ── limit_boxes ────────────────────────────────────────────────────

def limit_boxes(boxes: list[Box], pps: list[Ppoint], delta: float) -> None:
    """Tighten each box's x-extent to the spline's footprint.

    See: /lib/common/routespl.c @ 238

    Uses de Casteljau subdivision to sample the spline and shrink
    each box's ``ll_x`` / ``ur_x`` to the minimum enclosing range.
    """
    boxn = len(boxes)
    pn = len(pps)
    num_div = delta * boxn

    splinepi = 0
    while splinepi + 3 < pn:
        si = 0.0
        while si <= num_div:
            t = si / num_div
            sp = [
                Ppoint(pps[splinepi].x, pps[splinepi].y),
                Ppoint(pps[splinepi + 1].x, pps[splinepi + 1].y),
                Ppoint(pps[splinepi + 2].x, pps[splinepi + 2].y),
                Ppoint(pps[splinepi + 3].x, pps[splinepi + 3].y),
            ]
            # Three rounds of de Casteljau linear interpolation.
            sp[0].x += t * (sp[1].x - sp[0].x)
            sp[0].y += t * (sp[1].y - sp[0].y)
            sp[1].x += t * (sp[2].x - sp[1].x)
            sp[1].y += t * (sp[2].y - sp[1].y)
            sp[2].x += t * (sp[3].x - sp[2].x)
            sp[2].y += t * (sp[3].y - sp[2].y)
            sp[0].x += t * (sp[1].x - sp[0].x)
            sp[0].y += t * (sp[1].y - sp[0].y)
            sp[1].x += t * (sp[2].x - sp[1].x)
            sp[1].y += t * (sp[2].y - sp[1].y)
            sp[0].x += t * (sp[1].x - sp[0].x)
            sp[0].y += t * (sp[1].y - sp[0].y)

            for bi in range(boxn):
                if (sp[0].y <= boxes[bi].ur_y + FUDGE
                        and sp[0].y >= boxes[bi].ll_y - FUDGE):
                    boxes[bi].ll_x = min(boxes[bi].ll_x, sp[0].x)
                    boxes[bi].ur_x = max(boxes[bi].ur_x, sp[0].x)

            si += 1.0
        splinepi += 3


# ── routesplines_ ─────────────────────────────────────────────────

_INITIAL_LLX = float("inf")
_INITIAL_URX = float("-inf")


def routesplines_(pp: Path, polyline: bool = False) -> list[Ppoint] | None:
    """Route a spline through the box corridor in *pp*.

    See: /lib/common/routespl.c @ 294

    Returns a list of :class:`Ppoint` control points on success, or
    ``None`` on failure.  The boxes in ``pp.boxes`` are mutated:
    their x-extents are tightened to the spline's actual footprint
    so subsequent edges sharing the same boxes can use the freed
    space.
    """
    status, boxes = checkpath(list(pp.boxes), pp)
    if status != 0:
        return None
    boxn = len(boxes)
    if boxn == 0:
        return None

    # Detect whether boxes need y-flipping (bottom-to-top ordering).
    if boxn > 1 and boxes[0].ll_y > boxes[1].ll_y:
        flip = True
        for b in boxes:
            v = b.ur_y
            b.ur_y = -b.ll_y
            b.ll_y = -v
    else:
        flip = False

    # Build polygon from boxes: forward walk (left side) then backward
    # walk (right side), forming a CCW polygon around the corridor.
    polypoints: list[Ppoint] = []

    for bi in range(boxn):
        prev = 0
        nxt = 0
        if bi > 0:
            prev = -1 if boxes[bi].ll_y > boxes[bi - 1].ll_y else 1
        if bi + 1 < boxn:
            nxt = 1 if boxes[bi + 1].ll_y > boxes[bi].ll_y else -1
        if prev != nxt:
            if nxt == -1 or prev == 1:
                polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ur_y))
                polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ll_y))
            else:
                polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ll_y))
                polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ur_y))
        elif prev == 0:
            # Single box.
            polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ur_y))
            polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ll_y))

    # Backward walk for the right side.
    for bi in range(boxn - 1, -1, -1):
        prev = 0
        nxt = 0
        if bi + 1 < boxn:
            prev = -1 if boxes[bi].ll_y > boxes[bi + 1].ll_y else 1
        if bi > 0:
            nxt = 1 if boxes[bi - 1].ll_y > boxes[bi].ll_y else -1
        if prev != nxt:
            if nxt == -1 or prev == 1:
                polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ur_y))
                polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ll_y))
            else:
                polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ll_y))
                polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ur_y))
        elif prev == 0:
            # Single box.
            polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ll_y))
            polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ur_y))
        else:
            if not (prev == -1 and nxt == -1):
                print(f"in routesplines, illegal prev={prev} next={nxt}",
                      file=sys.stderr)
                return None
            polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ll_y))
            polypoints.append(Ppoint(boxes[bi].ur_x, boxes[bi].ur_y))
            polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ur_y))
            polypoints.append(Ppoint(boxes[bi].ll_x, boxes[bi].ll_y))

    # Un-flip if needed.
    if flip:
        for b in boxes:
            v = b.ur_y
            b.ur_y = -b.ll_y
            b.ll_y = -v
        for p in polypoints:
            p.y *= -1

    # Reset box x-extents — they'll be tightened by limit_boxes.
    for b in boxes:
        b.ll_x = _INITIAL_LLX
        b.ur_x = _INITIAL_URX

    poly = Ppoly(ps=polypoints)
    sx, sy = pp.start.np
    ex, ey = pp.end.np
    eps = [Ppoint(sx, sy), Ppoint(ex, ey)]

    status, pl = Pshortestpath(poly, eps)
    if status < 0:
        print("in routesplines, Pshortestpath failed", file=sys.stderr)
        return None

    if polyline:
        spl = make_polyline(pl)
    else:
        edges: list[Pedge] = []
        pn = len(polypoints)
        for ei in range(pn):
            edges.append(Pedge(
                a=polypoints[ei],
                b=polypoints[(ei + 1) % pn],
            ))
        evs: list[Ppoint] = [Ppoint(0.0, 0.0), Ppoint(0.0, 0.0)]
        if pp.start.constrained:
            evs[0] = Ppoint(math.cos(pp.start.theta),
                            math.sin(pp.start.theta))
        if pp.end.constrained:
            evs[1] = Ppoint(-math.cos(pp.end.theta),
                            -math.sin(pp.end.theta))
        spl = Proutespline(edges, pl, evs)
        if spl is None:
            print("in routesplines, Proutespline failed", file=sys.stderr)
            return None

    ps = list(spl.ps)

    # Detect trivially-bounded horizontal or vertical splines.
    unbounded = True
    if len(ps) > 0:
        is_horizontal = all(abs(ps[0].y - p.y) <= FUDGE for p in ps)
        is_vertical = all(abs(ps[0].x - p.x) <= FUDGE for p in ps)
        if is_horizontal or is_vertical:
            for b in boxes:
                b.ll_x = ps[0].x
                b.ur_x = ps[0].x
            unbounded = False

    # Iteratively tighten box x-extents via de Casteljau sampling.
    delta = float(INIT_DELTA)
    for _loopcnt in range(LOOP_TRIES):
        if not unbounded:
            break
        limit_boxes(boxes, ps, delta)
        all_bounded = True
        for b in boxes:
            if b.ll_x == _INITIAL_LLX or b.ur_x == _INITIAL_URX:
                delta *= 2
                all_bounded = False
                break
        if all_bounded:
            unbounded = False

    if unbounded:
        print("Unable to reclaim box space in spline routing",
              file=sys.stderr)
        polyspl = make_polyline(pl)
        limit_boxes(boxes, polyspl.ps, float(INIT_DELTA))

    # Write tightened boxes back to pp.
    pp.boxes = boxes
    pp.nbox = boxn

    return ps


# ── Public wrappers ────────────────────────────────────────────────

def routesplines(pp: Path) -> list[Ppoint] | None:
    """Route a curved spline through the box corridor.

    See: /lib/common/routespl.c @ 598
    """
    return routesplines_(pp, polyline=False)


def routepolylines(pp: Path) -> list[Ppoint] | None:
    """Route a polyline through the box corridor.

    See: /lib/common/routespl.c @ 602
    """
    return routesplines_(pp, polyline=True)


# ── simple_spline_route ───────────────────────────────────────────

def simple_spline_route(tp: tuple[float, float],
                        hp: tuple[float, float],
                        poly: Ppoly,
                        polyline: bool = False) -> list[Ppoint] | None:
    """Route an edge from *tp* to *hp* through a simple CCW polygon.

    See: /lib/common/routespl.c @ 174

    A simpler interface than :func:`routesplines` — no box corridor,
    just a single containing polygon.  Used for compound (inter-cluster)
    edges.

    Returns a list of spline control points, or ``None`` on failure.
    """
    eps = [Ppoint(tp[0], tp[1]), Ppoint(hp[0], hp[1])]
    status, pl = Pshortestpath(poly, eps)
    if status < 0:
        return None

    if polyline:
        spl = make_polyline(pl)
    else:
        edges: list[Pedge] = []
        pn = poly.pn
        for i in range(pn):
            edges.append(Pedge(a=poly.ps[i], b=poly.ps[(i + 1) % pn]))
        evs: list[Ppoint] = [Ppoint(0.0, 0.0), Ppoint(0.0, 0.0)]
        spl = Proutespline(edges, pl, evs)
        if spl is None:
            return None

    return list(spl.ps)
