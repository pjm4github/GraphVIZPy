"""Neato Voronoi-based overlap removal.

Mirrors ``lib/neatogen/adjust.c::vAdjust`` (line 415) and its
support routines ``rmEquality``, ``newpos``, ``newPos``,
``addCorners``.

Algorithm
---------
Iteratively move each overlapping node to the area-weighted
centroid of its Voronoi cell:

1. If no pairwise bounding-box overlap, return.
2. ``rmEquality`` — jitter coincident points (Voronoi is undefined
   on duplicate sites).
3. Compute Voronoi diagram of all node centres.
4. For each node, find its Voronoi cell; clip to a bounding
   rectangle; move the node to the cell centroid.
5. If overlaps remain, expand the bounding rectangle slightly and
   loop.

C handles all of step 3 with its own hand-rolled Voronoi
infrastructure (``voronoi.c``, ``site.c``, ``hedges.c``, ``heap.c``,
``legal.c``, ``delaunay.c``).  We delegate to ``scipy.spatial.
Voronoi`` for the diagram itself; the surrounding iteration logic
is a faithful port of ``vAdjust``.

This serves as our substitute for both ``AM_VOR`` and ``AM_PRISM``
modes (PRISM is preferred in C when GTS is available; we use
Voronoi-based for both since the qualitative result — non-overlap
preserving relative positions — is the same).

Trace tag: ``[TRACE neato_voronoi]``.
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


# Mirrors ``incr`` (adjust.c:46) — used to pad the bounding box
# each iteration so Voronoi cells stay bounded.
_INCR = 0.05
_DFLT_MAX_ITER = 50
# Voronoi degenerates with very few sites; below this, fall back to
# scaling.
_MIN_SITES = 4


def _trace(msg: str) -> None:
    """Emit a ``[TRACE neato_voronoi]`` line on stderr if tracing
    is enabled (``GVPY_TRACE_NEATO=1``)."""
    if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
        print(f"[TRACE neato_voronoi] {msg}", file=sys.stderr)


def _bbox_with_pad(points: np.ndarray, pad_factor: float = 1.5
                   ) -> tuple[float, float, float, float]:
    """Bounding box of ``points`` inflated by ``pad_factor``×span
    on each axis.

    The padding ensures Voronoi cells of real sites are bounded by
    the auxiliary fence points we'll add at the corners (see
    :func:`_fence_points`).
    """
    xmin, ymin = points.min(axis=0)
    xmax, ymax = points.max(axis=0)
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2
    half_w = max((xmax - xmin) / 2, 1.0) * pad_factor
    half_h = max((ymax - ymin) / 2, 1.0) * pad_factor
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h


def _fence_points(bbox: tuple[float, float, float, float]
                  ) -> np.ndarray:
    """Return four "fence" sites at the corners of ``bbox``.

    Adding these to the Voronoi input ensures every real site's
    cell is bounded; without them outer sites end up with cells
    extending to infinity, which makes centroid computation
    undefined.
    """
    xmin, ymin, xmax, ymax = bbox
    return np.array([[xmin, ymin], [xmin, ymax],
                     [xmax, ymin], [xmax, ymax]],
                    dtype=np.float64)


def _polygon_centroid(verts: np.ndarray
                      ) -> tuple[float, float, float]:
    """Compute the area-weighted centroid of a polygon via the
    shoelace formula.

    Mirrors ``adjust.c::newpos`` (line 329): triangulate the
    polygon as a fan from the first vertex, accumulate
    ``area × centroid`` per triangle, divide.

    Returns ``(cx, cy, total_area)``.  If the polygon is
    degenerate (zero area) returns the simple vertex mean.
    """
    n = len(verts)
    if n < 3:
        if n == 0:
            return 0.0, 0.0, 0.0
        m = verts.mean(axis=0)
        return float(m[0]), float(m[1]), 0.0

    cx = 0.0
    cy = 0.0
    total_area = 0.0
    anchor = verts[0]
    for i in range(1, n - 1):
        p = verts[i]
        q = verts[i + 1]
        # Signed area of triangle (anchor, p, q).
        area = 0.5 * (
            (p[0] - anchor[0]) * (q[1] - anchor[1])
            - (q[0] - anchor[0]) * (p[1] - anchor[1])
        )
        # Triangle centroid = (anchor + p + q) / 3.
        tcx = (anchor[0] + p[0] + q[0]) / 3.0
        tcy = (anchor[1] + p[1] + q[1]) / 3.0
        cx += area * tcx
        cy += area * tcy
        total_area += area

    if abs(total_area) < 1e-12:
        m = verts.mean(axis=0)
        return float(m[0]), float(m[1]), 0.0
    return cx / total_area, cy / total_area, abs(total_area)


def _rm_equality(layout: "NeatoLayout", names: list[str]) -> int:
    """Jitter coincident positions so Voronoi is well-defined.

    Mirrors ``adjust.c::rmEquality`` (line 227) — uses tiny offsets
    so the visible layout doesn't change but Voronoi can produce a
    valid diagram.

    Returns the number of nodes nudged.
    """
    seen: dict[tuple[float, float], int] = {}
    nudged = 0
    for name in names:
        ln = layout.lnodes[name]
        key = (round(ln.x, 6), round(ln.y, 6))
        if key in seen:
            seen[key] += 1
            jitter = 1e-3 * seen[key]
            ln.x += jitter * (random.random() - 0.5)
            ln.y += jitter * (random.random() - 0.5)
            nudged += 1
        else:
            seen[key] = 1
    return nudged


def _has_overlap_at(layout: "NeatoLayout", positions: dict[str, tuple[float, float]]) -> bool:
    """Pairwise overlap test using a position override map (used to
    test moves before committing them)."""
    names = list(positions.keys())
    sep = layout.sep
    for i in range(len(names)):
        a = layout.lnodes[names[i]]
        ax, ay = positions[names[i]]
        ah_w, ah_h = a.width / 2, a.height / 2
        for j in range(i + 1, len(names)):
            b = layout.lnodes[names[j]]
            bx, by = positions[names[j]]
            bh_w, bh_h = b.width / 2, b.height / 2
            if (abs(ax - bx) < ah_w + bh_w + sep
                    and abs(ay - by) < ah_h + bh_h + sep):
                return True
    return False


def voronoi_adjust(layout: "NeatoLayout",
                   max_iter: int = _DFLT_MAX_ITER) -> int:
    """Voronoi-cell-centroid iteration for overlap removal.

    Returns the iteration count (0 if no overlap was present, or
    if Voronoi degenerated and we fell back to scaling).
    """
    # Late imports so optional scipy isn't loaded for non-Voronoi paths.
    try:
        from scipy.spatial import Voronoi, QhullError
    except ImportError as exc:
        _trace(f"scipy unavailable ({exc}); voronoi_adjust skipped")
        return 0

    # Reuse the dispatcher's overlap detector to stay consistent.
    from gvpy.engines.layout.neato.adjust import (
        _has_overlap, scale_adjust,
    )

    # Need at least 2 nodes for any pairwise overlap.
    names = [name for name, ln in layout.lnodes.items()
             if not ln.pinned]
    if len(names) < 2 or not _has_overlap(layout):
        _trace("no overlap or all pinned; skip")
        return 0

    if len(names) < _MIN_SITES:
        _trace(f"only {len(names)} unpinned nodes; falling back to scale")
        return scale_adjust(layout)

    # Jitter coincident positions so Voronoi is defined.
    nudged = _rm_equality(layout, names)
    if nudged:
        _trace(f"rm_equality nudged {nudged} sites")

    def _overlap_pair_count() -> tuple[int, set[str]]:
        """Return (pair count, set of overlapping node names)."""
        cnt = 0
        offenders: set[str] = set()
        sep = layout.sep
        for i in range(len(names)):
            a = layout.lnodes[names[i]]
            for j in range(i + 1, len(names)):
                b = layout.lnodes[names[j]]
                if (abs(a.x - b.x) < a.width / 2 + b.width / 2 + sep
                        and abs(a.y - b.y)
                        < a.height / 2 + b.height / 2 + sep):
                    cnt += 1
                    offenders.add(names[i])
                    offenders.add(names[j])
        return cnt, offenders

    iters = 0
    pad_factor = 1.1
    prev_count, _ = _overlap_pair_count()
    bad_level = 0
    do_all = False
    while iters < max_iter:
        cnt, offenders = _overlap_pair_count()
        if cnt == 0:
            break

        points = np.array([[layout.lnodes[n].x, layout.lnodes[n].y]
                           for n in names], dtype=np.float64)
        bbox = _bbox_with_pad(points, pad_factor)
        fence = _fence_points(bbox)
        all_points = np.vstack([points, fence])

        try:
            vor = Voronoi(all_points)
        except QhullError as exc:
            _trace(f"Voronoi failed: {exc}; falling back to scale")
            return iters + scale_adjust(layout)

        # Move overlapping nodes first; only move *all* nodes once we
        # see progress (mirrors vAdjust's doAll heuristic).
        for i, name in enumerate(names):
            if not do_all and name not in offenders:
                continue
            region_idx = vor.point_region[i]
            region = vor.regions[region_idx]
            if not region or -1 in region:
                continue
            verts = vor.vertices[region]
            xmin, ymin, xmax, ymax = bbox
            verts = np.clip(verts, [xmin, ymin], [xmax, ymax])
            if len(verts) < 3:
                continue
            cx, cy, area = _polygon_centroid(verts)
            if area > 0:
                layout.lnodes[name].x = cx
                layout.lnodes[name].y = cy

        iters += 1
        # vAdjust badLevel heuristic: if overlap count shrank, set
        # doAll for the next iteration; if it didn't shrink, expand
        # the bbox (give cells more room).
        new_count, _ = _overlap_pair_count()
        if new_count >= prev_count:
            bad_level += 1
            pad_factor *= 1.0 + _INCR
        else:
            bad_level = 0
        do_all = True
        prev_count = new_count

    _trace(f"voronoi: iters={iters} final_pad={pad_factor:.3f} "
           f"bad_level={bad_level}")
    return iters
