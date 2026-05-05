"""Polyomino-grid 2D packing for disconnected components.

Port of ``lib/pack/pack.c::polyRects`` and helpers.  Produces
roughly-square overall extent rather than the long horizontal strip
that a plain LR pack yields when the input has hundreds of small
components.

Algorithm (Freivalds et al. GD'01 — "Disconnected Graph Layout and
the Polyomino Packing Approach"):

1. Compute a single grid step ``s`` from the components' total area
   so each component covers ~C cells on average (C = 100 in C ref).
   Solves the quadratic ``a·s² + b·s + c = 0`` with
   ``a = C·ng - 1``, ``b = -Σ(W_i + H_i)``, ``c = -Σ(W_i·H_i)``.
2. For each component build a ``ginfo`` covering set: the cells
   intersected by its bbox inflated by ``margin``.
3. Sort components by perimeter (cells in W + cells in H) descending.
4. Place each component greedily, spiralling outward from origin
   on a coarse cell grid.  ``fits`` checks the candidate offset
   against a global ``PointSet`` of already-claimed cells.

The output is a list of ``(dx, dy)`` translations that, when
applied to each component's nodes, position the components
disjointly in 2D.

Trace tag: ``[TRACE pack]``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# Mirrors ``#define C 100`` (pack.c:32) — target average polyomino
# size (cells per component) used to derive the grid step.
_TARGET_AVG_CELLS = 100


@dataclass
class Bbox:
    """Axis-aligned bounding box in layout coords."""
    ll_x: float
    ll_y: float
    ur_x: float
    ur_y: float

    @property
    def w(self) -> float:
        return self.ur_x - self.ll_x

    @property
    def h(self) -> float:
        return self.ur_y - self.ll_y


@dataclass
class _GInfo:
    """Per-component polyomino cover.

    Mirrors ``ginfo`` (pack.c:49).  ``cells`` is a frozen set of
    ``(cx, cy)`` integer cell coordinates relative to the component's
    nominal placement at origin.  ``perim`` is ``W + H`` measured in
    cells and drives the placement order.
    """
    index: int
    cells: frozenset[tuple[int, int]]
    perim: int


def _cell_index(v: float, step: int) -> int:
    """C ``CVAL`` + ``round`` macro pair (pack.c:44).

    Converts a continuous coordinate ``v`` to its cell index on a
    grid of step ``step``.  C uses the mapping
    ``v >= 0 ? v/step : (v+1)/step - 1`` (continuous division) and
    then rounds to the nearest integer.
    """
    if v >= 0:
        return int(round(v / step))
    return int(round((v + 1) / step - 1))


def _compute_step(bbs: list[Bbox], margin: float) -> int:
    """Compute the grid step size (pack.c:65).

    Solves ``a·s² + b·s + c = 0`` for the larger positive root,
    where ``a = C·ng - 1``, ``b = -Σ(W_i + H_i)``,
    ``c = -Σ(W_i · H_i)``.  Returns at least 1.
    """
    ng = len(bbs)
    if ng == 0:
        return 1
    a = _TARGET_AVG_CELLS * ng - 1
    b = 0.0
    c = 0.0
    for bb in bbs:
        W = bb.w + 2 * margin
        H = bb.h + 2 * margin
        b -= W + H
        c -= W * H
    d = b * b - 4.0 * a * c
    if d < 0 or a == 0:
        return 1
    r = math.sqrt(d)
    l1 = (-b + r) / (2 * a)
    root = int(l1)
    return max(root, 1)


def _gen_box(bb: Bbox, step: int, margin: float, index: int) -> _GInfo:
    """Compute the cell cover for a component's bbox (pack.c:227).

    The C version offsets cells by a per-component ``center``; in
    ``polyRects`` that's always ``(0, 0)``, so cells live near
    origin and are translated by ``placeGraph``'s candidate offset.
    """
    # In polyRects the center is always (0, 0).  Compute the
    # margin-inflated bbox in coords relative to that origin.
    ll_x = -margin
    ll_y = -margin
    ur_x = bb.w + margin
    ur_y = bb.h + margin

    cx_lo = _cell_index(ll_x, step)
    cy_lo = _cell_index(ll_y, step)
    cx_hi = _cell_index(ur_x, step)
    cy_hi = _cell_index(ur_y, step)

    cells = frozenset(
        (x, y)
        for x in range(cx_lo, cx_hi + 1)
        for y in range(cy_lo, cy_hi + 1)
    )
    W = math.ceil((bb.w + 2 * margin) / step)
    H = math.ceil((bb.h + 2 * margin) / step)
    return _GInfo(index=index, cells=cells, perim=int(W + H))


def _fits(x: int, y: int, info: _GInfo, ps: set[tuple[int, int]],
          step: int, bb: Bbox) -> tuple[float, float] | None:
    """Try to place ``info``'s polyomino at offset ``(x, y)`` cells.

    On success, marks the cells in ``ps`` and returns the placement
    translation ``(dx, dy)`` for the original layout coords.  On
    collision returns ``None``.

    Mirrors ``fits`` (pack.c:420).
    """
    placed = []
    for cx, cy in info.cells:
        cell = (cx + x, cy + y)
        if cell in ps:
            return None
        placed.append(cell)
    ps.update(placed)
    ll_x = round(bb.ll_x)
    ll_y = round(bb.ll_y)
    return (step * x - ll_x, step * y - ll_y)


def _place_graph(rank: int, info: _GInfo, ps: set[tuple[int, int]],
                 step: int, margin: float,
                 bb: Bbox) -> tuple[float, float]:
    """Spiral outward from origin and place this polyomino.

    Mirrors ``placeGraph`` (pack.c:481).  The first component
    (``rank == 0``) is centered on the origin if it fits; subsequent
    ones spiral outward in a rectangular pattern.  The spiral
    direction is chosen by aspect ratio so wider components grow
    horizontally and taller ones vertically.
    """
    if rank == 0:
        W = math.ceil((bb.w + 2 * margin) / step)
        H = math.ceil((bb.h + 2 * margin) / step)
        place = _fits(-W // 2, -H // 2, info, ps, step, bb)
        if place is not None:
            return place

    place = _fits(0, 0, info, ps, step, bb)
    if place is not None:
        return place

    bw = math.ceil(bb.w)
    bh = math.ceil(bb.h)
    if bw >= bh:
        bnd = 1
        while True:
            x, y = 0, -bnd
            while x < bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                x += 1
            while y < bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                y += 1
            while x > -bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                x -= 1
            while y > -bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                y -= 1
            while x < 0:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                x += 1
            bnd += 1
    else:
        bnd = 1
        while True:
            y, x = 0, -bnd
            while y > -bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                y -= 1
            while x < bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                x += 1
            while y < bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                y += 1
            while x > -bnd:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                x -= 1
            while y > 0:
                p = _fits(x, y, info, ps, step, bb)
                if p is not None:
                    return p
                y -= 1
            bnd += 1


def poly_rects(bbs: list[Bbox], margin: float = 8.0
               ) -> list[tuple[float, float]]:
    """2D polyomino-pack a list of axis-aligned bboxes.

    Mirrors ``polyRects`` (pack.c:716).  Returns a list of
    ``(dx, dy)`` translations — applying ``places[i]`` to every
    point in component ``i`` positions all components disjointly
    on a roughly-square grid.

    ``margin`` is the empty-cell halo around each component's bbox
    (in layout-coord units, NOT cells); set it to half the desired
    inter-component gap.
    """
    ng = len(bbs)
    if ng == 0:
        return []
    if ng == 1:
        return [(0.0, 0.0)]

    step = _compute_step(bbs, margin)
    infos = [_gen_box(bb, step, margin, i) for i, bb in enumerate(bbs)]

    # Sort by perimeter descending (largest components placed first
    # so they anchor the layout).
    order = sorted(range(ng), key=lambda i: -infos[i].perim)

    ps: set[tuple[int, int]] = set()
    places: list[tuple[float, float]] = [(0.0, 0.0)] * ng
    for rank, i in enumerate(order):
        places[i] = _place_graph(rank, infos[i], ps, step, margin, bbs[i])
    return places
