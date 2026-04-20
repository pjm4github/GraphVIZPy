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

from gvpy.engines.layout.pathplan.pathgeom import Ppoint
from gvpy.engines.layout.pathplan.vispath import Vconfig
from gvpy.engines.layout.pathplan.visibility import directVis


# See: /lib/pathplan/shortestpth.c @ 30
# C uses INT_MAX; Python uses a plain int
# large enough to dominate any real distance.  ``math.inf`` would
# also work but the sign-flip trick (``val[k] *= -1``) needs a
# finite value to flip cleanly.
_UNSEEN = float(2**31 - 1)


def shortestPath(root: int, target: int, V: int, wadj: list) -> list[int]:
    """Dijkstra from ``root`` to ``target`` on the ``V × V`` matrix ``wadj``.

    See: /lib/pathplan/shortestpth.c @ 30

    Returns a list ``dad`` of length ``V`` where the shortest path
    from ``target`` back to ``root`` is ``target, dad[target],
    dad[dad[target]], ..., root``.  ``dad[root] == -1`` sentinels
    the end.

    C uses a sign-flip trick on ``val`` to distinguish "seen" from
    "in-frontier": positive values are settled, negative values
    are tentative distances, and a sentinel ``val[-1]`` below
    ``-unseen`` guards the min-search.  Python preserves the
    algorithm verbatim, using a list-plus-sentinel layout to match
    C's ``vl[0]`` / ``val = vl + 1`` indexing trick.

    Only the lower-left triangle of ``wadj`` is consulted (``wadj[i][j]``
    for ``i >= j``).
    """
    dad = [-1] * V
    # C: ``COORD *vl = gv_calloc(V + 1, sizeof(COORD)); val = vl + 1;``
    # val[-1] is vl[0] (the sentinel).  In Python we use a list
    # indexed from -1 to V-1 via an offset-by-one helper.
    #
    # Simpler approach: keep a ``val`` list of length V AND a
    # separate ``sentinel`` variable for what C calls ``val[-1]``.
    # Rewrite the ``val[t] > val[min]`` comparisons to special-case
    # ``min == -1`` → use ``sentinel``.
    val: list[float] = [-_UNSEEN] * V
    sentinel = -(_UNSEEN + 1.0)

    minidx = root

    # C loop: ``while (min != target)``
    while minidx != target:
        k = minidx
        val[k] *= -1  # mark settled
        minidx = -1
        if val[k] == _UNSEEN:
            val[k] = 0.0

        for t in range(V):
            if val[t] < 0:
                # Use lower triangle
                if k >= t:
                    wkt = wadj[k][t]
                else:
                    wkt = wadj[t][k]

                newpri = -(val[k] + wkt)
                if wkt != 0 and val[t] < newpri:
                    val[t] = newpri
                    dad[t] = k
                # Find new tentative minimum.  C uses val[-1]
                # (sentinel) as initial min value; we simulate
                # with the explicit sentinel.
                cur_min_val = sentinel if minidx == -1 else val[minidx]
                if val[t] > cur_min_val:
                    minidx = t

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
