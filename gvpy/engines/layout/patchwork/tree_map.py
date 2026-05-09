"""C-aligned port of ``lib/patchwork/tree_map.c`` —
the squarified-treemap rectangle packer.

Given a parent rectangle and a list of child *areas*, produce a
list of child rectangles that fill the parent and each have an
aspect ratio as close to 1:1 as possible (the "squarified"
property from Bruls / Huizing / van Wijk 2000).

API:

- :class:`Rectangle` — ``(center, size)`` representation matching
  C ``rectangle`` (tree_map.h).  Both ``center`` and ``size`` are
  2-tuples ``(x, y)``.
- :func:`tree_map` — top-level entry, mirrors C ``tree_map``
  (tree_map.c:104).  Returns a list of :class:`Rectangle` with
  the same length and order as the input ``areas``.

Algorithm (mirrors C ``squarify`` recursion verbatim):

1. Pick the shorter side of the fill rectangle as the "fixed"
   dimension ``w``.
2. Greedily extend a strip along ``w`` with successive items.
3. For each candidate next item, compute the worst aspect
   ratio if it were added to the current strip.  If the worst
   aspect ratio improved (or this is the first item), commit the
   add and continue.  Otherwise lock in the current strip,
   carve it off the fill rectangle, and recurse into the
   remaining sub-rectangle.
4. Within a committed strip, items are placed perpendicular to
   ``w``: if ``fillrec`` is tall (``size[0] <= size[1]``),
   strip is at the top and items run left-to-right; if
   ``fillrec`` is wide, strip is at the left and items run
   top-to-bottom.

The C convention has ``y`` going up (math-y), so "top of the
fillrec" means ``x[1] + size[1]/2`` (high-y end).  Downstream
GraphvizPy renders in SVG-y (y down); the patchwork engine
flips at output time so the coordinate system here stays
math-y to match C verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Rectangle:
    """Mirrors C ``rectangle`` (tree_map.h:16).

    Stored as center + size — NOT lower-left + size.  This
    matches C's representation and keeps the squarify recursion
    straightforward (each recursive call shrinks ``size`` and
    nudges ``x`` toward the still-empty side).
    """
    cx: float
    cy: float
    sw: float
    sh: float

    def copy(self) -> "Rectangle":
        return Rectangle(self.cx, self.cy, self.sw, self.sh)


# ─────────────────────────────────────────────────────────────────
# squarify recursion
# ─────────────────────────────────────────────────────────────────


def _squarify(
    areas: list[float],
    recs: list[Optional[Rectangle]],
    start: int,
    nadded: int,
    maxarea: float,
    minarea: float,
    totalarea: float,
    asp: float,
    fillrec: Rectangle,
) -> None:
    """Mirrors C ``squarify`` (tree_map.c:19).

    Operates on ``areas[start:]`` — the items already committed
    to earlier strips have been sliced off by the caller.
    Writes its results into ``recs[start:start+nadded]`` (and
    recurses for the remainder).

    The C signature passes ``area + nadded`` and ``recs +
    nadded`` pointers in the recursive call after committing a
    strip; we use index arithmetic to the same effect.

    Parameters
    ----------
    areas : list of float
        Per-item area (sum should equal fillrec.sw * fillrec.sh
        before the first call).
    recs : list of Rectangle or None
        Output buffer.  Caller pre-allocates with ``[None] * n``.
    start : int
        Index of the first item NOT yet placed.
    nadded : int
        Items currently in the trial strip (always ``< n - start``).
    maxarea, minarea : float
        Largest / smallest area in the trial strip.
    totalarea : float
        Sum of areas in the trial strip.
    asp : float
        Worst aspect ratio of items in the trial strip.
    fillrec : Rectangle
        The remaining empty rectangle to fill.
    """
    n = len(areas) - start
    if n == 0:
        return

    # Shorter dimension determines strip thickness.
    w = min(fillrec.sw, fillrec.sh)

    if nadded == 0:
        # First item: seed the strip with item 0.
        nadded = 1
        a0 = areas[start]
        maxarea = a0
        minarea = a0
        # Item 0 occupies a w-by-w square cell along the strip;
        # its aspect is max(area/w², w²/area).
        cell = w * w
        asp = max(a0 / cell, cell / a0) if cell > 0 else float("inf")
        totalarea = a0
        _squarify(
            areas, recs, start, nadded,
            maxarea, minarea, totalarea, asp, fillrec,
        )
        return

    # Try extending the strip with the next item.
    new_asp: float
    s = totalarea
    if nadded < n:
        next_a = areas[start + nadded]
        new_max = max(maxarea, next_a)
        new_min = min(minarea, next_a)
        s = totalarea + next_a
        h_strip = s / w if w > 0 else 0.0
        max_w = new_max / h_strip if h_strip > 0 else 0.0
        min_w = new_min / h_strip if h_strip > 0 else 0.0
        if min_w > 0 and h_strip > 0:
            new_asp = max(h_strip / min_w, max_w / h_strip)
        else:
            new_asp = float("inf")
    else:
        new_asp = float("inf")
        new_max = maxarea
        new_min = minarea

    if nadded < n and new_asp <= asp:
        # Aspect ratio improved — keep adding.
        _squarify(
            areas, recs, start, nadded + 1,
            new_max, new_min, s, new_asp, fillrec,
        )
        return

    # Aspect ratio would worsen (or all items consumed).  Commit
    # the strip and recurse on the remaining empty rectangle.
    if fillrec.sw <= fillrec.sh:
        # Tall rectangle — strip at top, items run left-to-right.
        hh = totalarea / w if w > 0 else 0.0
        # Walk x from the LEFT edge of fillrec.
        xx = fillrec.cx - fillrec.sw / 2.0
        # Strip's center-y is the top of fillrec offset by hh/2 down.
        strip_cy = fillrec.cy + 0.5 * fillrec.sh - hh / 2.0
        for i in range(nadded):
            ai = areas[start + i]
            ww = ai / hh if hh > 0 else 0.0
            recs[start + i] = Rectangle(
                cx=xx + ww / 2.0,
                cy=strip_cy,
                sw=ww,
                sh=hh,
            )
            xx += ww
        # Carve the strip off the top.
        fillrec.cy -= hh / 2.0
        fillrec.sh -= hh
    else:
        # Wide rectangle — strip at left, items run top-to-bottom.
        ww = totalarea / w if w > 0 else 0.0
        yy = fillrec.cy + fillrec.sh / 2.0
        strip_cx = fillrec.cx - 0.5 * fillrec.sw + ww / 2.0
        for i in range(nadded):
            ai = areas[start + i]
            hh = ai / ww if ww > 0 else 0.0
            recs[start + i] = Rectangle(
                cx=strip_cx,
                cy=yy - hh / 2.0,
                sw=ww,
                sh=hh,
            )
            yy -= hh
        # Carve the strip off the left.
        fillrec.cx += ww / 2.0
        fillrec.sw -= ww

    # Recurse on the carved-down rectangle for items not yet placed.
    _squarify(
        areas, recs, start + nadded, 0,
        0.0, 0.0, 0.0, 1.0, fillrec,
    )


# ─────────────────────────────────────────────────────────────────
# Public entry
# ─────────────────────────────────────────────────────────────────


def tree_map(
    areas: list[float],
    fillrec: Rectangle,
) -> Optional[list[Rectangle]]:
    """Mirrors C ``tree_map`` (tree_map.c:104).

    Parameters
    ----------
    areas : list of float
        Per-item areas.  Sum must not exceed
        ``fillrec.sw * fillrec.sh`` (with a 0.001 fudge for
        floating-point slop, matching C).
    fillrec : Rectangle
        The rectangle to fill.  Stored center + size.

    Returns
    -------
    list of Rectangle, or None
        One rectangle per input area.  ``None`` if the input
        areas overflow the fill rectangle (matches C's NULL
        return).

    Notes
    -----
    The fill rectangle ``fillrec`` is *not* modified by the
    caller's perspective — we work on a copy internally.
    """
    n = len(areas)
    if n == 0:
        return []

    total = sum(areas)
    if total > fillrec.sw * fillrec.sh + 0.001:
        return None

    recs: list[Optional[Rectangle]] = [None] * n
    work = fillrec.copy()
    _squarify(
        areas, recs, 0, 0,
        0.0, 1.0, 0.0, 1.0, work,
    )
    # Sanity: every slot should be filled.
    return [r if r is not None else Rectangle(0, 0, 0, 0) for r in recs]
