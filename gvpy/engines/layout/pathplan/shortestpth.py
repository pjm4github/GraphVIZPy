"""Dijkstra shortest-path on the visibility graph.

See: /lib/pathplan/shortestpth.c @ 30

Two functions:

- :func:`shortestPath` — Dijkstra on a ``V × V`` weighted adjacency
  matrix, returning a ``dad`` back-pointer array.
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
from gvpy.engines.layout.pathplan.vispath import Vconfig
from gvpy.engines.layout.pathplan.visibility import directVis


def shortestPath(root: int, target: int, V: int, wadj: list) -> list[int]:
    """Dijkstra from ``root`` to ``target`` on a visibility-graph matrix.

    Returns a length-``V`` list ``dad`` where ``dad[i]`` is the
    predecessor of node ``i`` on the shortest path from ``root``,
    or ``-1`` for unreachable nodes / the root itself.  Walking
    ``dad`` from ``target`` back through predecessors traces the
    shortest path to ``root``.

    Implementation: builds a dense ``V × V`` weight matrix from the
    list-of-lists ``wadj`` (whose rows have variable lengths in the
    C-port format — the first ``V - 2`` rows are length ``V - 2``
    and the last 2 are length ``V``) and runs ``scipy.sparse.csgraph
    .dijkstra``.  Replaces the hand-rolled dense Dijkstra; orders of
    magnitude faster on graphs with thousands of vertices.
    """
    arr = np.zeros((V, V), dtype=np.float64)
    for i in range(V):
        row = wadj[i]
        if row is None:
            continue
        rlen = min(len(row), V)
        if rlen > 0:
            arr[i, :rlen] = row[:rlen]
    # Symmetrise: row i may not extend into the columns covered by
    # the query-point rows V-2 / V-1 (which have length V).  Taking
    # max enforces undirected semantics on every populated cell.
    arr_sym = np.maximum(arr, arr.T)
    g = csr_matrix(arr_sym)

    _, predecessors = dijkstra(
        g, directed=False, indices=root, return_predecessors=True
    )
    # scipy returns -9999 for unreachable nodes and the root itself;
    # callers expect -1 as the sentinel.
    dad = [int(p) if p >= 0 else -1 for p in predecessors]
    return dad


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
    return shortestPath(V + 1, V, V + 2, conf.vis)
