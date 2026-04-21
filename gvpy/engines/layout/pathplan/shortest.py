"""Funnel-algorithm shortest path inside a simple polygon.

See: /lib/pathplan/shortest.c @ 83

Given a simple polygon and two points inside it, :func:`Pshortestpath`
finds the shortest polyline from ``eps[0]`` to ``eps[1]`` that stays
inside the polygon.  The algorithm:

1. Triangulate the polygon (local ear-clipping using
   :func:`...triang.isdiagonal` with a ``pointnlink_t``-aware
   indexer).
2. Connect triangles that share an edge to form a dual graph.
3. Mark the triangle strip (sleeve) between the two endpoints via
   DFS (``marktripath``).
4. Walk the sleeve with a deque-based funnel algorithm that tracks
   the shortest-path tree through the sleeve.  The final result is
   a linked list of pointnlink_t records from ``eps[1]`` back to
   ``eps[0]``.

This is the single most intricate file in the ``pathplan`` port.
Every function is a literal transliteration of the C source.  The
module state that C keeps as static globals (``tris``, ``ops``) is
converted to **per-call** local state in :func:`Pshortestpath` —
thread-safe and test-isolated, unlike C.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from gvpy.engines.layout.pathplan.pathgeom import Ppoint, Ppoly, Ppolyline
from gvpy.engines.layout.pathplan.triang import (
    ISCCW,
    ISCW,
    ccw,
    isdiagonal,
)
from gvpy.engines.layout.pathplan.triang_nb import (
    NUMBA_AVAILABLE as _NB_AVAILABLE,
    triangulate_nb as _triangulate_nb,
)


# ── Deque-walk direction flags ─────────────────────────────────────
# See: /lib/pathplan/shortest.c @ 23

DQ_FRONT = 1
DQ_BACK = 2


# ── Funnel-algorithm support types ─────────────────────────────────

@dataclass
class _PointNLink:
    """Point + back-link node used by the funnel algorithm.

    See: /lib/pathplan/shortest.c @ 31

    ``pp`` is the underlying point.  ``link`` is a back-pointer in
    the shortest-path linked list — walking ``link`` from the
    destination endpoint yields the reversed path.
    """
    pp: Ppoint
    link: Optional["_PointNLink"] = None


@dataclass
class _TriEdge:
    """One edge of a triangle + the index of the adjacent triangle.

    See: /lib/pathplan/shortest.c @ 39
    """
    pnl0p: "_PointNLink | None" = None
    pnl1p: "_PointNLink | None" = None
    right_index: int = -1  # SIZE_MAX in C; Python uses -1 as sentinel


@dataclass
class _Triangle:
    """A triangle + its three edges + DFS mark.

    See: /lib/pathplan/shortest.c @ 45
    """
    mark: int = 0
    e: list = field(default_factory=lambda: [_TriEdge(), _TriEdge(), _TriEdge()])


@dataclass
class _Deque:
    """Funnel-algorithm deque with front/back indices and apex pointer.

    See: /lib/pathplan/shortest.c @ 50

    The deque is a pre-allocated array of ``pnlpn`` entries with
    front/back indices ``fpnlpi`` / ``lpnlpi`` and a persistent
    ``apex`` marker into the middle.  ``lpnlpi == fpnlpi - 1`` on
    init means empty; after ``add2dq`` the pair bracket the live
    range.
    """
    pnlps: list = field(default_factory=list)
    pnlpn: int = 0
    fpnlpi: int = 0
    lpnlpi: int = 0
    apex: int = 0


# Sentinel matching C's ``SIZE_MAX`` for "no adjacent triangle".
_NO_TRI = -1


# ── Indexer for isdiagonal over pointnlink_t arrays ────────────────

def _point_indexer_shortest(base: Any, index: int) -> Ppoint:
    """Indexer: ``base`` is a list of :class:`_PointNLink`; return ``pp``.

    See: /lib/pathplan/shortest.c @ 73
    """
    return base[index].pp


# ── Core algorithm: local triangulate + support helpers ────────────
#
# All of these take a mutable ``state`` dict with keys:
#   tris — list[_Triangle]
# Functions that grow ``tris`` append to the list.  This replaces
# C's ``static LIST(triangle_t) tris`` module global.

def _loadtriangle(state: dict,
                   pnlap: _PointNLink, pnlbp: _PointNLink, pnlcp: _PointNLink) -> int:
    """Append a fresh triangle with the three supplied edges.

    See: /lib/pathplan/shortest.c @ 343
    """
    trip = _Triangle()
    trip.e[0] = _TriEdge(pnl0p=pnlap, pnl1p=pnlbp, right_index=_NO_TRI)
    trip.e[1] = _TriEdge(pnl0p=pnlbp, pnl1p=pnlcp, right_index=_NO_TRI)
    trip.e[2] = _TriEdge(pnl0p=pnlcp, pnl1p=pnlap, right_index=_NO_TRI)
    state["tris"].append(trip)
    return 0


def _triangulate_pnls(state: dict, points: list, point_count: int) -> int:
    """Ear-clip a polygon into triangles, appending to ``state['tris']``.

    See: /lib/pathplan/shortest.c @ 317

    Delegates the ear-clip inner loop to a numba-JIT'd routine in
    :mod:`...triang_nb` when available — the arithmetic-heavy
    ``ccw`` / ``_intersects`` / ``isdiagonal`` helpers dominate
    phase-4 time on graphs with long virtual-chain corridors
    (97% of 2343.dot).  Falls back to the pure-Python iterative
    loop if numba isn't installed.
    """
    # Fast path: numba
    if _NB_AVAILABLE and point_count >= 4:
        xs = np.fromiter((p.pp.x for p in points[:point_count]),
                         dtype=np.float64, count=point_count)
        ys = np.fromiter((p.pp.y for p in points[:point_count]),
                         dtype=np.float64, count=point_count)
        tris_out, n_tris = _triangulate_nb(xs, ys)
        if n_tris < 0:
            return -1
        for row in range(n_tris):
            a = int(tris_out[row, 0])
            b = int(tris_out[row, 1])
            c = int(tris_out[row, 2])
            if _loadtriangle(state, points[a], points[b], points[c]) != 0:
                return -1
        return 0

    # Slow path: pure Python iterative ear-clip.
    while point_count > 3:
        found_ear = False
        for pnli in range(point_count):
            pnlip2 = (pnli + 2) % point_count
            if isdiagonal(pnli, pnlip2, points, point_count, _point_indexer_shortest):
                pnlip1 = (pnli + 1) % point_count
                if _loadtriangle(state, points[pnli], points[pnlip1], points[pnlip2]) != 0:
                    return -1
                # Remove points[pnlip1] — C's in-place compaction.
                points = points[:pnlip1] + points[pnlip1 + 1:]
                point_count -= 1
                found_ear = True
                break
        if not found_ear:
            return -1  # prerror: "triangulation failed"
    if _loadtriangle(state, points[0], points[1], points[2]) != 0:
        return -1
    return 0


def _connecttris(state: dict, tri1: int, tri2: int) -> None:
    """Link two triangles if they share an edge (set ``right_index``).

    See: /lib/pathplan/shortest.c @ 360
    """
    tris = state["tris"]
    for ei in range(3):
        for ej in range(3):
            tri1p = tris[tri1]
            tri2p = tris[tri2]
            # C compares Ppoint_t * pointers; Python compares the
            # referenced point objects by identity.
            if ((tri1p.e[ei].pnl0p.pp is tri2p.e[ej].pnl0p.pp
                    and tri1p.e[ei].pnl1p.pp is tri2p.e[ej].pnl1p.pp)
                    or (tri1p.e[ei].pnl0p.pp is tri2p.e[ej].pnl1p.pp
                        and tri1p.e[ei].pnl1p.pp is tri2p.e[ej].pnl0p.pp)):
                tri1p.e[ei].right_index = tri2
                tri2p.e[ej].right_index = tri1


def _marktripath(state: dict, trii: int, trij: int) -> bool:
    """DFS-mark the triangle strip from ``trii`` to ``trij``.

    See: /lib/pathplan/shortest.c @ 378

    Marks visited triangles with ``mark = 1``; resets to 0 on
    backtrack so unreachable branches are cleaned up.
    """
    tris = state["tris"]
    if tris[trii].mark:
        return False
    tris[trii].mark = 1
    if trii == trij:
        return True
    for ei in range(3):
        if (tris[trii].e[ei].right_index != _NO_TRI
                and _marktripath(state,
                                   tris[trii].e[ei].right_index, trij)):
            return True
    tris[trii].mark = 0
    return False


def _add2dq(dq: _Deque, side: int, pnlp: _PointNLink) -> None:
    """Push ``pnlp`` to the front (``DQ_FRONT``) or back (``DQ_BACK``).

    See: /lib/pathplan/shortest.c @ 395

    Also wires the shortest-path ``link`` pointer so that the
    back-chain is built as the deque grows.
    """
    if side == DQ_FRONT:
        if dq.lpnlpi >= dq.fpnlpi:
            pnlp.link = dq.pnlps[dq.fpnlpi]
        dq.fpnlpi -= 1
        dq.pnlps[dq.fpnlpi] = pnlp
    else:
        if dq.lpnlpi >= dq.fpnlpi:
            pnlp.link = dq.pnlps[dq.lpnlpi]
        dq.lpnlpi += 1
        dq.pnlps[dq.lpnlpi] = pnlp


def _splitdq(dq: _Deque, side: int, index: int) -> None:
    """Truncate the deque at ``index`` on the given side.

    See: /lib/pathplan/shortest.c @ 409
    """
    if side == DQ_FRONT:
        dq.lpnlpi = index
    else:
        dq.fpnlpi = index


def _finddqsplit(dq: _Deque, pnlp: _PointNLink) -> int:
    """Find the split index at which ``pnlp`` leaves the current funnel.

    See: /lib/pathplan/shortest.c @ 416
    """
    for index in range(dq.fpnlpi, dq.apex):
        if ccw(dq.pnlps[index + 1].pp,
               dq.pnlps[index].pp,
               pnlp.pp) == ISCCW:
            return index
    index = dq.lpnlpi
    while index > dq.apex:
        if ccw(dq.pnlps[index - 1].pp,
               dq.pnlps[index].pp,
               pnlp.pp) == ISCW:
            return index
        index -= 1
    return dq.apex


def _pointintri(state: dict, trii: int, pp: Ppoint) -> bool:
    """Return True iff ``pp`` lies in triangle ``trii``.

    See: /lib/pathplan/shortest.c @ 426

    Uses the sign convention of :func:`...triang.ccw` (not
    :func:`...visibility.wind`!).  Counts how many edges have the
    point on the non-CW side — 0 or 3 means all three sides agree,
    so the point is inside (or on the boundary).
    """
    tris = state["tris"]
    sum_ = 0
    for ei in range(3):
        if ccw(tris[trii].e[ei].pnl0p.pp,
               tris[trii].e[ei].pnl1p.pp,
               pp) != ISCW:
            sum_ += 1
    return sum_ == 3 or sum_ == 0


# ── Pshortestpath (public API) ─────────────────────────────────────

def Pshortestpath(polyp: Ppoly, eps: list) -> tuple[int, Ppolyline]:
    """Shortest polyline from ``eps[0]`` to ``eps[1]`` inside ``polyp``.

    See: /lib/pathplan/shortest.c @ 83

    Python API deviation: C returns an int status and fills an
    ``Ppolyline_t *output`` out-parameter.  Python returns
    ``(status, polyline)``:

    - ``status == 0``: success; ``polyline`` is the shortest path.
    - ``status == -1``: bad input (endpoint not in any triangle);
      ``polyline`` may be empty.
    - ``status == -2``: memory allocation problem (not used in
      Python but preserved for API fidelity).

    **Preconditions:** ``polyp`` is a simple polygon; ``eps`` has
    exactly two points that are both inside (or on the boundary of)
    ``polyp``.
    """
    # Per-call state replaces C's static globals ``tris`` and ``ops``.
    state: dict = {"tris": []}

    # Raise the process-wide recursion limit if the polygon is big
    # enough that ``_marktripath``'s DFS could need it.
    # ``_marktripath`` depth ≤ triangle count (≈ polygon_vertex_count).
    # Default 1000 trips on 2343.dot's 1000+ vertex corridors.
    # Monotonically raising the limit is fine — Python frames are
    # ~1 KB each; 20k deep ≈ 20 MB, well under any platform stack.
    if polyp.pn > 200:
        import sys as _sys_rec
        _needed = polyp.pn * 4 + 100
        if _sys_rec.getrecursionlimit() < _needed:
            _sys_rec.setrecursionlimit(_needed)

    # Build the pnls array in CCW order.  C also dedupes adjacent
    # coincident vertices.  We preserve both behaviours.
    #
    # Determine orientation: find the leftmost vertex and check the
    # sign of ccw(prev, leftmost, next).  If CW, walk the polygon
    # backwards when building pnls.
    if polyp.pn == 0:
        return (-1, Ppolyline(ps=[]))

    minx = math.inf
    minpi = -1
    for pi in range(polyp.pn):
        if minx > polyp.ps[pi].x:
            minx = polyp.ps[pi].x
            minpi = pi
    p2 = polyp.ps[minpi]
    p1 = polyp.ps[polyp.pn - 1 if minpi == 0 else minpi - 1]
    p3 = polyp.ps[(minpi + 1) % polyp.pn]

    pnls: list[_PointNLink] = []
    if ((p1.x == p2.x and p2.x == p3.x and p3.y > p2.y)
            or ccw(p1, p2, p3) != ISCCW):
        # Walk backwards (polygon was CW).
        pi = polyp.pn - 1
        while pi >= 0:
            if (pi < polyp.pn - 1
                    and polyp.ps[pi].x == polyp.ps[pi + 1].x
                    and polyp.ps[pi].y == polyp.ps[pi + 1].y):
                pi -= 1
                continue
            pnls.append(_PointNLink(pp=polyp.ps[pi]))
            pi -= 1
    else:
        # Walk forward (polygon was CCW).
        for pi in range(polyp.pn):
            if (pi > 0
                    and polyp.ps[pi].x == polyp.ps[pi - 1].x
                    and polyp.ps[pi].y == polyp.ps[pi - 1].y):
                continue
            pnls.append(_PointNLink(pp=polyp.ps[pi]))

    pnll = len(pnls)

    # Build pnlps — the working array for triangulation.
    pnlps = list(pnls)  # shallow copy: same _PointNLink refs

    # Deque: pnlpn = polyp.pn * 2, with fpnlpi starting at mid.
    # C: ``deque_t dq = {.pnlpn = polyp->pn * 2};``
    dq = _Deque(pnlpn=polyp.pn * 2)
    dq.pnlps = [None] * dq.pnlpn  # type: ignore[list-item]
    dq.fpnlpi = dq.pnlpn // 2
    dq.lpnlpi = dq.fpnlpi - 1

    # Triangulate the polygon.
    if _triangulate_pnls(state, pnlps, pnll) != 0:
        return (-2, Ppolyline(ps=[]))

    tris = state["tris"]

    # Connect adjacent triangles.  C: O(n²) nested loop.
    for trii in range(len(tris)):
        for trij in range(trii + 1, len(tris)):
            _connecttris(state, trii, trij)

    # Find the triangles containing eps[0] and eps[1].
    ftrii = _NO_TRI
    for trii in range(len(tris)):
        if _pointintri(state, trii, eps[0]):
            ftrii = trii
            break
    if ftrii == _NO_TRI:
        return (-1, Ppolyline(ps=[]))

    ltrii = _NO_TRI
    for trii in range(len(tris)):
        if _pointintri(state, trii, eps[1]):
            ltrii = trii
            break
    if ltrii == _NO_TRI:
        return (-1, Ppolyline(ps=[]))

    # Mark the triangle path from eps[0] to eps[1].  If the polygon
    # is disconnected by a wall, marktripath returns False and C
    # falls back to a straight line between endpoints.
    if not _marktripath(state, ftrii, ltrii):
        return (0, Ppolyline(ps=[eps[0], eps[1]]))

    # If both endpoints are in the same triangle, straight line.
    if ftrii == ltrii:
        return (0, Ppolyline(ps=[eps[0], eps[1]]))

    # Funnel-algorithm walk.
    epnls = [_PointNLink(pp=eps[0]), _PointNLink(pp=eps[1])]
    _add2dq(dq, DQ_FRONT, epnls[0])
    dq.apex = dq.fpnlpi
    trii = ftrii

    while trii != _NO_TRI:
        trip = tris[trii]
        trip.mark = 2

        # Find the edge whose ``right_index`` points at the next
        # marked triangle (the one we're exiting through).
        ei = 3
        for ei_scan in range(3):
            if (trip.e[ei_scan].right_index != _NO_TRI
                    and tris[trip.e[ei_scan].right_index].mark == 1):
                ei = ei_scan
                break

        if ei == 3:
            # Last triangle — the funnel closes at eps[1].
            fpnlp = dq.pnlps[dq.fpnlpi]
            lpnlp_cur = dq.pnlps[dq.lpnlpi]
            assert fpnlp is not None and lpnlp_cur is not None
            if ccw(eps[1], fpnlp.pp, lpnlp_cur.pp) == ISCCW:
                lpnlp = lpnlp_cur
                rpnlp = epnls[1]
            else:
                lpnlp = epnls[1]
                rpnlp = lpnlp_cur
        else:
            pnlp = trip.e[(ei + 1) % 3].pnl1p
            assert pnlp is not None
            assert trip.e[ei].pnl0p is not None and trip.e[ei].pnl1p is not None
            if ccw(trip.e[ei].pnl0p.pp,
                   pnlp.pp,
                   trip.e[ei].pnl1p.pp) == ISCCW:
                lpnlp = trip.e[ei].pnl1p
                rpnlp = trip.e[ei].pnl0p
            else:
                lpnlp = trip.e[ei].pnl0p
                rpnlp = trip.e[ei].pnl1p

        # Update deque.
        if trii == ftrii:
            _add2dq(dq, DQ_BACK, lpnlp)
            _add2dq(dq, DQ_FRONT, rpnlp)
        else:
            if (dq.pnlps[dq.fpnlpi] is not rpnlp
                    and dq.pnlps[dq.lpnlpi] is not rpnlp):
                # Add right point to deque.
                splitindex = _finddqsplit(dq, rpnlp)
                _splitdq(dq, DQ_BACK, splitindex)
                _add2dq(dq, DQ_FRONT, rpnlp)
                if splitindex > dq.apex:
                    dq.apex = splitindex
            else:
                # Add left point to deque.
                splitindex = _finddqsplit(dq, lpnlp)
                _splitdq(dq, DQ_FRONT, splitindex)
                _add2dq(dq, DQ_BACK, lpnlp)
                if splitindex < dq.apex:
                    dq.apex = splitindex

        # Find next triangle via an unmarked neighbour.
        trii = _NO_TRI
        for ei_scan in range(3):
            if (trip.e[ei_scan].right_index != _NO_TRI
                    and tris[trip.e[ei_scan].right_index].mark == 1):
                trii = trip.e[ei_scan].right_index
                break

    # Walk the linked list from eps[1] back through ``link`` chains
    # to collect the path in forward order.
    path_points: list[Ppoint] = []
    pnlp: Optional[_PointNLink] = epnls[1]
    while pnlp is not None:
        path_points.append(pnlp.pp)
        pnlp = pnlp.link
    path_points.reverse()
    return (0, Ppolyline(ps=path_points))
