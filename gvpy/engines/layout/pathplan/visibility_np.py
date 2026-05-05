"""NumPy-vectorized visibility primitives.

Drop-in replacement for the per-edge inner loops in
``visibility.compVis`` and ``visibility.ptVis``.  Same algorithm,
same 1e-4 wind tolerance, same skip-range semantics — just batched:
a single ``clear_vec`` call tests one query segment against all V
polygon edges in one NumPy broadcast instead of V Python-level
``intersect`` calls.

The polygon-edge endpoint arrays (``pts_x``, ``pts_y``, ``next_x``,
``next_y``) are built once on first use and cached on the Vconfig
as ``conf._np_ctx``.  All subsequent ``ptVis`` queries reuse them.
"""
from __future__ import annotations

import numpy as np

from gvpy.engines.layout.pathplan.vispath import Vconfig

# Match the scalar wind() tolerance from visibility.c:55.
_WIND_TOL = 0.0001


class _NumpyCtx:
    """Pre-extracted numpy coordinate arrays for a Vconfig's polygon edges.

    Edge k spans from ``pts[k]`` to ``pts[nextPt[k]]``; we materialize
    both endpoints as float64 arrays once so vectorized intersection
    tests don't have to repeatedly walk Python-level Ppoint objects.
    """

    __slots__ = ("V", "pts_x", "pts_y", "next_x", "next_y")

    def __init__(self, conf: Vconfig):
        V = conf.N
        self.V = V
        P = conf.P
        nxt = conf.next
        self.pts_x = np.fromiter((p.x for p in P), dtype=np.float64, count=V)
        self.pts_y = np.fromiter((p.y for p in P), dtype=np.float64, count=V)
        self.next_x = np.fromiter((P[nxt[k]].x for k in range(V)),
                                  dtype=np.float64, count=V)
        self.next_y = np.fromiter((P[nxt[k]].y for k in range(V)),
                                  dtype=np.float64, count=V)


def get_np_ctx(conf: Vconfig) -> _NumpyCtx:
    """Build (or fetch the cached) numpy context for a Vconfig."""
    ctx = getattr(conf, "_np_ctx", None)
    if ctx is None or ctx.V != conf.N:
        ctx = _NumpyCtx(conf)
        conf._np_ctx = ctx
    return ctx


def _wind_sign(ax: float, ay: float, bx: float, by: float,
               cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    """Vectorized wind() sign for fixed (a, b) vs. array of c points.

    Returns int8 array of {-1, 0, 1} matching scalar ``wind``'s
    1e-4 tolerance.
    """
    w = (ay - by) * (cx - bx) - (cy - by) * (ax - bx)
    sign = np.zeros(w.shape, dtype=np.int8)
    sign[w > _WIND_TOL] = 1
    sign[w < -_WIND_TOL] = -1
    return sign


def _wind_sign_seg(cx: np.ndarray, cy: np.ndarray,
                   dx: np.ndarray, dy: np.ndarray,
                   ax: float, ay: float) -> np.ndarray:
    """Vectorized wind(c, d, a) for arrays (c, d) and fixed point a."""
    w = (cy - dy) * (ax - dx) - (ay - dy) * (cx - dx)
    sign = np.zeros(w.shape, dtype=np.int8)
    sign[w > _WIND_TOL] = 1
    sign[w < -_WIND_TOL] = -1
    return sign


def _in_between(ax: float, ay: float, bx: float, by: float,
                cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    """Vectorized inBetween(): strict between-ness on the (a, b) line."""
    if ax != bx:
        return ((ax < cx) & (cx < bx)) | ((bx < cx) & (cx < ax))
    return ((ay < cy) & (cy < by)) | ((by < cy) & (cy < ay))


def clear_vec(ax: float, ay: float, bx: float, by: float,
              start: int, end: int, ctx: _NumpyCtx) -> bool:
    """Return True iff segment (a, b) is not blocked by any polygon edge.

    Mirrors ``visibility.clear``: tests every polygon edge except
    those in the skip range ``[start, end)`` (the polygon containing
    the query endpoints).  ``compVis`` passes ``start=end=V`` for an
    empty skip range; ``ptVis`` passes a single polygon's range.
    """
    V = ctx.V
    cx, cy = ctx.pts_x, ctx.pts_y
    dx, dy = ctx.next_x, ctx.next_y

    # Carve out the skip range [start, end) from [0, V).
    if start <= 0 and end >= V:
        return True                          # nothing to test
    if start >= end:
        sx, sy, ex, ey = cx, cy, dx, dy      # empty skip — test all
    elif start == 0:
        sx, sy, ex, ey = cx[end:], cy[end:], dx[end:], dy[end:]
    elif end >= V:
        sx, sy, ex, ey = cx[:start], cy[:start], dx[:start], dy[:start]
    else:
        sx = np.concatenate((cx[:start], cx[end:]))
        sy = np.concatenate((cy[:start], cy[end:]))
        ex = np.concatenate((dx[:start], dx[end:]))
        ey = np.concatenate((dy[:start], dy[end:]))

    # 4 wind sign tests + 2 inBetween, batched over the kept edges.
    a_abc = _wind_sign(ax, ay, bx, by, sx, sy)
    a_abd = _wind_sign(ax, ay, bx, by, ex, ey)
    a_cda = _wind_sign_seg(sx, sy, ex, ey, ax, ay)
    a_cdb = _wind_sign_seg(sx, sy, ex, ey, bx, by)

    blocks = (
        ((a_abc * a_abd < 0) & (a_cda * a_cdb < 0))      # proper crossing
        | ((a_abc == 0) & _in_between(ax, ay, bx, by, sx, sy))  # collinear c
        | ((a_abd == 0) & _in_between(ax, ay, bx, by, ex, ey))  # collinear d
    )
    return not bool(blocks.any())


def _carve_skip(start: int, end: int, ctx: _NumpyCtx
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return the four polygon-edge endpoint arrays with ``[start, end)`` removed.

    Used by both the scalar and batched clear paths.  Empty skip
    range (``start >= end``) returns the full arrays unchanged.
    """
    V = ctx.V
    cx, cy = ctx.pts_x, ctx.pts_y
    dx, dy = ctx.next_x, ctx.next_y

    if start >= end:
        return cx, cy, dx, dy
    if start == 0:
        return cx[end:], cy[end:], dx[end:], dy[end:]
    if end >= V:
        return cx[:start], cy[:start], dx[:start], dy[:start]
    return (
        np.concatenate((cx[:start], cx[end:])),
        np.concatenate((cy[:start], cy[end:])),
        np.concatenate((dx[:start], dx[end:])),
        np.concatenate((dy[:start], dy[end:])),
    )


def _sign_with_tol(w: np.ndarray) -> np.ndarray:
    """Return int8 sign of ``w`` with the 1e-4 tolerance band → 0."""
    s = np.zeros(w.shape, dtype=np.int8)
    s[w > _WIND_TOL] = 1
    s[w < -_WIND_TOL] = -1
    return s


# Chunk size for ``clear_vec_batch``.  At V ≈ 2200 (1879.dot scale)
# a single un-chunked (K=V) call materialises ~70 MB float64
# intermediates per wind term, blowing past L3 cache and causing
# ~1.7× slowdown vs. chunked.  K=512 keeps each wind tensor at
# ~9 MB — well-cached, ~20µs/chunk numpy overhead.  Empirically
# 256–1024 are all within ~10% of each other.
_BATCH_CHUNK = 512


def _clear_vec_chunk(ax: float, ay: float,
                     bx: np.ndarray, by: np.ndarray,
                     sx: np.ndarray, sy: np.ndarray,
                     ex: np.ndarray, ey: np.ndarray,
                     s_cda: np.ndarray) -> np.ndarray:
    """Inner kernel for a single (K_chunk × V_kept) batch.

    The carved polygon-edge arrays (``sx`` … ``ey``) and the
    edge-only sign array ``s_cda`` are computed once by the caller
    and reused across chunks — they don't depend on which subset
    of ``b`` segments is being processed.
    """
    bx2 = bx[:, None]                        # (Kc, 1)
    by2 = by[:, None]
    sx_row = sx[None, :]                     # (1, V_kept)
    sy_row = sy[None, :]
    ex_row = ex[None, :]
    ey_row = ey[None, :]

    ay_minus_by = ay - by2
    ax_minus_bx = ax - bx2

    w_abc = ay_minus_by * (sx_row - bx2) - (sy_row - by2) * ax_minus_bx
    s_abc = _sign_with_tol(w_abc)
    w_abd = ay_minus_by * (ex_row - bx2) - (ey_row - by2) * ax_minus_bx
    s_abd = _sign_with_tol(w_abd)
    w_cdb = (sy_row - ey_row) * (bx2 - ex_row) - (by2 - ey_row) * (sx_row - ex_row)
    s_cdb = _sign_with_tol(w_cdb)

    cross_proper = (s_abc * s_abd < 0) & (s_cda[None, :] * s_cdb < 0)

    use_x = (ax != bx)[:, None]
    x_btw_c = ((ax < sx_row) & (sx_row < bx2)) | ((bx2 < sx_row) & (sx_row < ax))
    y_btw_c = ((ay < sy_row) & (sy_row < by2)) | ((by2 < sy_row) & (sy_row < ay))
    btw_c = np.where(use_x, x_btw_c, y_btw_c)
    x_btw_d = ((ax < ex_row) & (ex_row < bx2)) | ((bx2 < ex_row) & (ex_row < ax))
    y_btw_d = ((ay < ey_row) & (ey_row < by2)) | ((by2 < ey_row) & (ey_row < ay))
    btw_d = np.where(use_x, x_btw_d, y_btw_d)

    blocks = cross_proper | ((s_abc == 0) & btw_c) | ((s_abd == 0) & btw_d)
    return ~blocks.any(axis=1)


def clear_vec_batch(ax: float, ay: float,
                    bx: np.ndarray, by: np.ndarray,
                    start: int, end: int,
                    ctx: _NumpyCtx) -> np.ndarray:
    """Batched clear test for K segments sharing endpoint (ax, ay).

    Tests, for each ``k in range(K)``, whether segment
    ``((ax, ay) → (bx[k], by[k]))`` is unobstructed by any polygon
    edge outside the skip range ``[start, end)``.  Returns a length-K
    boolean array where ``True`` = clear.

    Equivalent to ``[clear_vec(ax, ay, bx[k], by[k], start, end, ctx)
    for k in range(K)]`` but performs the wind/inBetween tests as
    ``(K_chunk, V_kept)`` numpy broadcasts in chunks of
    ``_BATCH_CHUNK``.  Chunking caps the working-set size of each
    numpy intermediate so it stays in L2/L3 cache.

    Used by ``compVis`` (``a`` = ``pts[i]``, ``b`` = ``pts[0..j_max]``)
    and ``ptVis`` (``a`` = query point, ``b`` = polygon vertices).
    """
    K = bx.shape[0]
    if K == 0:
        return np.empty(0, dtype=bool)

    V = ctx.V
    if start <= 0 and end >= V:
        return np.ones(K, dtype=bool)

    sx, sy, ex, ey = _carve_skip(start, end, ctx)
    if sx.shape[0] == 0:
        return np.ones(K, dtype=bool)

    # wind(c, d, a) — depends only on the polygon edge and the
    # fixed endpoint ``a``.  Compute once and reuse across chunks.
    w_cda = (sy - ey) * (ax - ex) - (ay - ey) * (sx - ex)
    s_cda = _sign_with_tol(w_cda)

    if K <= _BATCH_CHUNK:
        return _clear_vec_chunk(ax, ay, bx, by, sx, sy, ex, ey, s_cda)

    out = np.empty(K, dtype=bool)
    for s in range(0, K, _BATCH_CHUNK):
        e = s + _BATCH_CHUNK
        if e > K:
            e = K
        out[s:e] = _clear_vec_chunk(
            ax, ay, bx[s:e], by[s:e], sx, sy, ex, ey, s_cda
        )
    return out
