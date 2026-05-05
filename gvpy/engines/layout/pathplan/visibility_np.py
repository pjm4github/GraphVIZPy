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

    Also caches the inner V×V visibility matrix as sparse COO triplets
    after ``compVis`` populates it, so the per-Pobspath shortest-path
    Dijkstra can build the full augmented sparse graph in O(nnz)
    rather than re-walking a list-of-lists.
    """

    __slots__ = ("V", "pts_x", "pts_y", "next_x", "next_y",
                 "coo_i", "coo_j", "coo_w")

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
        self.coo_i: np.ndarray | None = None
        self.coo_j: np.ndarray | None = None
        self.coo_w: np.ndarray | None = None


def get_np_ctx(conf: Vconfig) -> _NumpyCtx:
    """Build (or fetch the cached) numpy context for a Vconfig."""
    ctx = getattr(conf, "_np_ctx", None)
    if ctx is None or ctx.V != conf.N:
        ctx = _NumpyCtx(conf)
        conf._np_ctx = ctx
    return ctx


def cache_vis_coo(conf: Vconfig) -> None:
    """Populate ``ctx.coo_*`` with sparse COO triplets of the inner
    V×V visibility matrix.

    Called once after ``compVis`` finishes filling ``conf.vis``.
    The inner block is symmetric (compVis writes both ``wadj[i][j]``
    and ``wadj[j][i]``) so we keep both halves; ``directed=False``
    on scipy's dijkstra will treat them as one undirected edge.
    """
    ctx = get_np_ctx(conf)
    if ctx.coo_i is not None or conf.vis is None:
        return
    V = conf.N
    arr = np.array(conf.vis[:V], dtype=np.float64)
    nz_i, nz_j = np.nonzero(arr)
    ctx.coo_i = nz_i.astype(np.int64, copy=False)
    ctx.coo_j = nz_j.astype(np.int64, copy=False)
    ctx.coo_w = arr[nz_i, nz_j]


def _in_between(ax: float, ay: float, bx: float, by: float,
                cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    """Vectorized inBetween(): strict between-ness on the (a, b) line."""
    if ax != bx:
        return ((ax < cx) & (cx < bx)) | ((bx < cx) & (cx < ax))
    return ((ay < cy) & (cy < by)) | ((by < cy) & (cy < ay))


# Module-level scratch buffers for ``clear_vec``.  Each ``clear_vec``
# call computes 4 wind values (raw float64) and 8 boolean comparison
# masks (positive / negative sign per wind).  Pre-allocating + reusing
# these across ~1.8 M calls saves ~50-60 µs of allocator churn per
# call vs. letting NumPy auto-allocate intermediates each time.
#
# Buffers are resized lazily when a larger V_kept is needed.
_F_BUFS: list[np.ndarray] = [np.empty(0, dtype=np.float64) for _ in range(4)]
_B_BUFS: list[np.ndarray] = [np.empty(0, dtype=bool) for _ in range(8)]


def _ensure_scratch(n: int) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Resize the module-level float / bool scratch buffers if needed."""
    global _F_BUFS, _B_BUFS
    if _F_BUFS[0].shape[0] < n:
        _F_BUFS = [np.empty(n, dtype=np.float64) for _ in range(4)]
        _B_BUFS = [np.empty(n, dtype=bool) for _ in range(8)]
    return _F_BUFS, _B_BUFS


def clear_vec(ax: float, ay: float, bx: float, by: float,
              start: int, end: int, ctx: _NumpyCtx) -> bool:
    """Return True iff segment (a, b) is not blocked by any polygon edge.

    Mirrors ``visibility.clear``: tests every polygon edge except
    those in the skip range ``[start, end)`` (the polygon containing
    the query endpoints).  ``compVis`` passes ``start=end=V`` for an
    empty skip range; ``ptVis`` passes a single polygon's range.

    Implementation note: the 4 wind values are computed into 4 module-
    level scratch float64 buffers.  Sign comparisons against the wind
    tolerance produce two bool masks per wind (``pos``, ``neg``) that
    encode the int8 sign without allocating an int8 array.  Saves both
    allocator overhead and a few NumPy dispatches vs. the prior
    ``np.zeros + indexed assigns`` formulation.
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

    n = sx.shape[0]
    fbufs, bbufs = _ensure_scratch(n)
    w_abc = fbufs[0][:n]
    w_abd = fbufs[1][:n]
    w_cda = fbufs[2][:n]
    w_cdb = fbufs[3][:n]

    # 4 wind values, written into pre-allocated float64 scratch.
    np.multiply(sy - by, (ax - bx), out=w_abc)
    w_abc *= -1
    w_abc += (ay - by) * (sx - bx)
    np.multiply(ey - by, (ax - bx), out=w_abd)
    w_abd *= -1
    w_abd += (ay - by) * (ex - bx)
    np.multiply(ay - ey, (sx - ex), out=w_cda)
    w_cda *= -1
    w_cda += (sy - ey) * (ax - ex)
    np.multiply(by - ey, (sx - ex), out=w_cdb)
    w_cdb *= -1
    w_cdb += (sy - ey) * (bx - ex)

    abc_pos = bbufs[0][:n]
    abc_neg = bbufs[1][:n]
    abd_pos = bbufs[2][:n]
    abd_neg = bbufs[3][:n]
    cda_pos = bbufs[4][:n]
    cda_neg = bbufs[5][:n]
    cdb_pos = bbufs[6][:n]
    cdb_neg = bbufs[7][:n]

    np.greater(w_abc, _WIND_TOL, out=abc_pos)
    np.less(w_abc, -_WIND_TOL, out=abc_neg)
    np.greater(w_abd, _WIND_TOL, out=abd_pos)
    np.less(w_abd, -_WIND_TOL, out=abd_neg)
    np.greater(w_cda, _WIND_TOL, out=cda_pos)
    np.less(w_cda, -_WIND_TOL, out=cda_neg)
    np.greater(w_cdb, _WIND_TOL, out=cdb_pos)
    np.less(w_cdb, -_WIND_TOL, out=cdb_neg)

    # Proper crossing: sign(w_abc) and sign(w_abd) opposite (both
    # non-zero), AND sign(w_cda) and sign(w_cdb) opposite.
    cross_ab = (abc_pos & abd_neg) | (abc_neg & abd_pos)
    cross_cd = (cda_pos & cdb_neg) | (cda_neg & cdb_pos)
    proper = cross_ab & cross_cd
    if proper.any():
        return False

    # Collinear special cases (rare).
    abc_zero = ~(abc_pos | abc_neg)
    abd_zero = ~(abd_pos | abd_neg)
    if abc_zero.any():
        if (abc_zero & _in_between(ax, ay, bx, by, sx, sy)).any():
            return False
    if abd_zero.any():
        if (abd_zero & _in_between(ax, ay, bx, by, ex, ey)).any():
            return False
    return True


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
