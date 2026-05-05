"""Dijkstra shortest-path on the visibility graph.

See: /lib/pathplan/shortestpth.c @ 30

Two functions:

- :func:`shortestPath` — Dijkstra on the augmented visibility graph
  (cached inner block + 2 query rows), returning a ``dad``
  back-pointer array.
- :func:`makePath` — glue layer that either returns a direct link
  if ``directVis`` succeeds, or falls back to :func:`shortestPath`
  on the visibility graph with the two query points' visibility
  vectors spliced into rows ``V`` and ``V + 1`` of ``conf.vis``.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from gvpy.engines.layout.pathplan.pathgeom import Ppoint
from gvpy.engines.layout.pathplan.visibility import directVis
from gvpy.engines.layout.pathplan.visibility_np import cache_vis_coo, get_np_ctx
from gvpy.engines.layout.pathplan.vispath import Vconfig


def _shortestPath_dense(root: int, V: int, wadj: list) -> list[int]:
    """Generic dense-matrix Dijkstra for a list-of-lists adjacency.

    Used when callers hand us a raw adjacency directly (e.g. unit
    tests).  The fast path is :func:`shortestPath` with a
    :class:`Vconfig`, which reuses cached COO triplets.
    """
    arr = np.zeros((V, V), dtype=np.float64)
    for i in range(V):
        row = wadj[i]
        if row is None:
            continue
        rlen = min(len(row), V)
        if rlen > 0:
            arr[i, :rlen] = row[:rlen]
    arr_sym = np.maximum(arr, arr.T)
    g = csr_matrix(arr_sym)
    _, predecessors = dijkstra(
        g, directed=False, indices=root, return_predecessors=True
    )
    return [int(p) if p >= 0 else -1 for p in predecessors]


def shortestPath(root: int, target: int, V_full: int,
                 conf_or_wadj) -> list[int]:
    """Dijkstra from ``root`` to ``target`` on the visibility graph.

    Returns a length-``V_full`` list ``dad`` where ``dad[i]`` is the
    predecessor of node ``i`` on the shortest path from ``root``, or
    ``-1`` for unreachable nodes / the root itself.

    The fast path takes a :class:`Vconfig`: the inner ``V × V``
    polygon-vertex visibility block is cached by ``cache_vis_coo`` as
    sparse COO triplets and reused across every shortest-path query.
    Per call we only build the 4 short triplet arrays for the two
    query-point rows (``conf.vis[V]`` and ``conf.vis[V + 1]``) and
    concatenate with the cached inner triplets before handing the
    CSR matrix to scipy's dijkstra.

    Direct callers passing a raw list-of-lists adjacency drop into a
    dense-matrix legacy path (used by unit tests).
    """
    if not isinstance(conf_or_wadj, Vconfig):
        return _shortestPath_dense(root, V_full, conf_or_wadj)

    conf = conf_or_wadj
    V = conf.N
    assert V_full == V + 2, f"expected V_full == V + 2, got {V_full} != {V} + 2"

    if get_np_ctx(conf).coo_i is None:
        cache_vis_coo(conf)
    ctx = get_np_ctx(conf)

    # Query-point rows live at indices V and V+1, populated by makePath.
    qvis_q = np.array(conf.vis[V], dtype=np.float64)        # length V+2
    qvis_p = np.array(conf.vis[V + 1], dtype=np.float64)    # length V+2

    # Non-zero entries from each query row, restricted to the inner
    # polygon-vertex columns (the last 2 slots are zero by construction).
    nz_q = np.nonzero(qvis_q[:V])[0]
    nz_p = np.nonzero(qvis_p[:V])[0]
    w_q = qvis_q[nz_q]
    w_p = qvis_p[nz_p]

    # Augment the cached inner COO with both directions of each
    # query→inner edge so scipy's directed=False dijkstra sees them
    # as undirected without relying on row/col asymmetry.
    n_q = nz_q.shape[0]
    n_p = nz_p.shape[0]
    row_v = np.full(n_q, V, dtype=np.int64)
    row_vp1 = np.full(n_p, V + 1, dtype=np.int64)
    nz_q_i64 = nz_q.astype(np.int64, copy=False)
    nz_p_i64 = nz_p.astype(np.int64, copy=False)

    all_rows = np.concatenate([ctx.coo_i, row_v, nz_q_i64,
                               row_vp1, nz_p_i64])
    all_cols = np.concatenate([ctx.coo_j, nz_q_i64, row_v,
                               nz_p_i64, row_vp1])
    all_data = np.concatenate([ctx.coo_w, w_q, w_q, w_p, w_p])

    g = csr_matrix((all_data, (all_rows, all_cols)),
                   shape=(V_full, V_full))

    _, predecessors = dijkstra(
        g, directed=False, indices=root, return_predecessors=True
    )
    return [int(p) if p >= 0 else -1 for p in predecessors]


def makePath(p: Ppoint, pp: int, pvis: list,
             q: Ppoint, qp: int, qvis: list,
             conf: Vconfig) -> list[int]:
    """Compute the ``dad`` back-pointer array for the ``p → q`` shortest path.

    See: /lib/pathplan/shortestpth.c @ 93

    Encoding convention (from C comment): ``q`` is indexed at
    ``V``, ``p`` at ``V + 1``.  The returned path in natural
    order is ``V(==q), dad[V], dad[dad[V]], ..., V+1(==p)``, i.e.
    walking ``dad`` from ``q`` back to ``p``.

    Python mutates ``conf.vis[V]`` and ``conf.vis[V + 1]`` just
    like C assigns to the row pointers.  The two slots were
    allocated as ``None`` placeholders by :func:`...visibility.allocArray`
    during :func:`...visibility.visibility`.
    """
    V = conf.N

    if directVis(p, pp, q, qp, conf):
        # Direct line-of-sight: dad has just two meaningful entries.
        # V points to V+1 (q → p), V+1 is the root sentinel.
        dad = [-1] * (V + 2)
        dad[V] = V + 1
        dad[V + 1] = -1
        return dad

    # Splice per-query visibility vectors into rows V and V+1.
    assert conf.vis is not None, "makePath requires visibility() to have run"
    conf.vis[V] = qvis
    conf.vis[V + 1] = pvis
    return shortestPath(V + 1, V, V + 2, conf)
