"""Numba-accelerated hot path for ear-clip triangulation.

The pure-Python functions in :mod:`triang` and the triangulator in
:mod:`shortest` spend ~97% of the dot layout time on 2343.dot inside
``ccw``/``_intersects``/``_between``/``isdiagonal``.  These are
small arithmetic-heavy leaf functions called hundreds of millions of
times — the classic numba sweet spot.

This module provides:

- :func:`triangulate_nb` — ear-clip a CCW polygon given as flat
  ``xs``, ``ys`` float64 arrays.  Returns ``(triangle_indices,
  n_tris)`` where ``n_tris == -1`` on malformed-polygon failure.
  Triangle rows index the ORIGINAL polygon arrays (not the
  compacted working array).

- :func:`NUMBA_AVAILABLE` — ``True`` when numba imported; callers
  should fall back to the pure-Python path when ``False``.

Semantics exactly match :func:`...triang.isdiagonal` +
:func:`...triang._intersects` + :func:`...triang._between` +
:func:`...triang.ccw` — same sign conventions (``ISCW=2``,
``ISCCW=1``, ``ISON=3``), same neighbourhood branch, same
intersection XOR test.  The pure-Python implementations remain the
reference and are covered by the existing pathplan test suite.
"""
from __future__ import annotations

try:
    from numba import njit
    NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):  # type: ignore[misc]
        def _wrap(fn):
            return fn
        if args and callable(args[0]):
            return args[0]
        return _wrap

import numpy as np

# Must match triang.py constants exactly.
ISCCW = 1
ISCW = 2
ISON = 3


@njit(cache=True)
def _ccw_nb(p1x: float, p1y: float,
            p2x: float, p2y: float,
            p3x: float, p3y: float) -> int:
    d = (p1y - p2y) * (p3x - p2x) - (p3y - p2y) * (p1x - p2x)
    if d > 0:
        return ISCW
    if d < 0:
        return ISCCW
    return ISON


@njit(cache=True)
def _between_nb(pax: float, pay: float,
                pbx: float, pby: float,
                pcx: float, pcy: float) -> bool:
    pba_x = pbx - pax
    pba_y = pby - pay
    pca_x = pcx - pax
    pca_y = pcy - pay
    if _ccw_nb(pax, pay, pbx, pby, pcx, pcy) != ISON:
        return False
    dot = pca_x * pba_x + pca_y * pba_y
    len_ca_sq = pca_x * pca_x + pca_y * pca_y
    len_ba_sq = pba_x * pba_x + pba_y * pba_y
    return dot >= 0 and len_ca_sq <= len_ba_sq


@njit(cache=True)
def _intersects_nb(pax: float, pay: float,
                   pbx: float, pby: float,
                   pcx: float, pcy: float,
                   pdx: float, pdy: float) -> bool:
    c_ab_c = _ccw_nb(pax, pay, pbx, pby, pcx, pcy)
    c_ab_d = _ccw_nb(pax, pay, pbx, pby, pdx, pdy)
    c_cd_a = _ccw_nb(pcx, pcy, pdx, pdy, pax, pay)
    c_cd_b = _ccw_nb(pcx, pcy, pdx, pdy, pbx, pby)
    if (c_ab_c == ISON or c_ab_d == ISON
            or c_cd_a == ISON or c_cd_b == ISON):
        if (_between_nb(pax, pay, pbx, pby, pcx, pcy)
                or _between_nb(pax, pay, pbx, pby, pdx, pdy)
                or _between_nb(pcx, pcy, pdx, pdy, pax, pay)
                or _between_nb(pcx, pcy, pdx, pdy, pbx, pby)):
            return True
    else:
        ccw1 = 1 if c_ab_c == ISCCW else 0
        ccw2 = 1 if c_ab_d == ISCCW else 0
        ccw3 = 1 if c_cd_a == ISCCW else 0
        ccw4 = 1 if c_cd_b == ISCCW else 0
        return (ccw1 ^ ccw2) == 1 and (ccw3 ^ ccw4) == 1
    return False


@njit(cache=True)
def _isdiagonal_nb(i: int, ip2: int,
                   xs, ys, pointn: int) -> bool:
    ip1 = (i + 1) % pointn
    im1 = (i + pointn - 1) % pointn

    nb = _ccw_nb(xs[im1], ys[im1], xs[i], ys[i], xs[ip1], ys[ip1])
    if nb == ISCCW:
        res = (_ccw_nb(xs[i], ys[i], xs[ip2], ys[ip2],
                       xs[im1], ys[im1]) == ISCCW
               and _ccw_nb(xs[ip2], ys[ip2], xs[i], ys[i],
                           xs[ip1], ys[ip1]) == ISCCW)
    else:
        res = _ccw_nb(xs[i], ys[i], xs[ip2], ys[ip2],
                      xs[ip1], ys[ip1]) == ISCW
    if not res:
        return False

    for j in range(pointn):
        jp1 = (j + 1) % pointn
        if j == i or jp1 == i or j == ip2 or jp1 == ip2:
            continue
        if _intersects_nb(xs[i], ys[i], xs[ip2], ys[ip2],
                          xs[j], ys[j], xs[jp1], ys[jp1]):
            return False
    return True


@njit(cache=True)
def triangulate_nb(xs_in, ys_in):
    """Ear-clip a CCW polygon into triangles.

    Parameters:
        xs_in, ys_in: float64 1-D arrays of polygon vertex coords.

    Returns ``(tri_indices, n_tris)``:
        - ``tri_indices`` is an (N-2, 3) int64 array.  Each row gives
          the three original-polygon indices of an ear triangle.
        - ``n_tris`` is the number of valid rows in ``tri_indices``.
          ``n_tris == -1`` signals "no valid diagonal found" (the
          polygon is malformed / self-intersecting).

    Mirrors :func:`...shortest._triangulate_pnls` + the helpers in
    :mod:`...triang` line-for-line, converted to flat numpy arrays
    and an iterative ear-clip (C-style in-place compaction via a
    single shift pass per ear).
    """
    N = xs_in.shape[0]
    # Working arrays (will be compacted as ears are clipped).
    xs = xs_in.copy()
    ys = ys_in.copy()
    orig_idx = np.arange(N, dtype=np.int64)

    n_out = max(N - 2, 0)
    tris = np.zeros((n_out, 3), dtype=np.int64)
    tri_count = 0
    point_count = N

    while point_count > 3:
        found = False
        for pnli in range(point_count):
            pnlip2 = (pnli + 2) % point_count
            if _isdiagonal_nb(pnli, pnlip2, xs, ys, point_count):
                pnlip1 = (pnli + 1) % point_count
                tris[tri_count, 0] = orig_idx[pnli]
                tris[tri_count, 1] = orig_idx[pnlip1]
                tris[tri_count, 2] = orig_idx[pnlip2]
                tri_count += 1
                # In-place compaction: shift tail down by one.
                for k in range(pnlip1, point_count - 1):
                    xs[k] = xs[k + 1]
                    ys[k] = ys[k + 1]
                    orig_idx[k] = orig_idx[k + 1]
                point_count -= 1
                found = True
                break
        if not found:
            return tris, -1

    if point_count == 3:
        tris[tri_count, 0] = orig_idx[0]
        tris[tri_count, 1] = orig_idx[1]
        tris[tri_count, 2] = orig_idx[2]
        tri_count += 1
    return tris, tri_count
