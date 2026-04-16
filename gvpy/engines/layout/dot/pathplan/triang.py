"""Polygon triangulation via ear-clipping.

C analogue: ``lib/pathplan/triang.c`` + ``lib/pathplan/tri.h``.

Provides:

- ``ISCCW``/``ISCW``/``ISON`` enum values for :func:`ccw` return.
- :func:`ccw` — three-point orientation test returning one of the
  three enum values.  **Note:** different semantics from
  :func:`~...visibility.wind` — ``ccw`` has no tolerance window and
  returns the signed-area sign mapped to the enum.
- :func:`Ptriangulate` — top-level polygon triangulation API; calls
  a user callback ``fn(closure, triangle)`` for each triangle found.
- :func:`isdiagonal` — shared diagonal-viability test used by both
  :func:`Ptriangulate` and the triangulator in
  :mod:`...shortest` (via a caller-supplied ``indexer``).

The ``indexer`` pattern mirrors C's ``indexer_t`` typedef — it lets
:func:`isdiagonal` work with both raw point arrays (as in
``triang.c``) and linked-list adaptors (as in ``shortest.c``).
Python's default indexer just does ``points[k]``; callers that need
a different lookup pass their own.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint, Ppoly

# ── ccw return values ──────────────────────────────────────────────
# C analogue: ``tri.h:40-44`` enum::
#
#     enum {
#       ISCCW = 1,  ///< counter-clockwise
#       ISCW = 2,   ///< clockwise
#       ISON = 3,   ///< co-linear
#     };

ISCCW = 1
ISCW = 2
ISON = 3


def ccw(p1: Ppoint, p2: Ppoint, p3: Ppoint) -> int:
    """Return orientation of the triple ``(p1, p2, p3)``.

    C analogue: ``triang.c:25-28``::

        int ccw(Ppoint_t p1, Ppoint_t p2, Ppoint_t p3) {
            double d = (p1.y - p2.y) * (p3.x - p2.x) -
                       (p3.y - p2.y) * (p1.x - p2.x);
            return d > 0 ? ISCW : (d < 0 ? ISCCW : ISON);
        }

    Notable quirks preserved from C:

    - **No collinearity tolerance** — unlike
      :func:`~...visibility.wind`, which returns 0 within ``0.0001``,
      ``ccw`` treats any exact-zero cross product as collinear and
      anything non-zero as CW or CCW.
    - **Inverted sign convention** — C reports positive cross
      product as ``ISCW`` (clockwise), negative as ``ISCCW``.  Don't
      try to unify this with ``wind``'s convention; the two
      functions are used by different code paths that depend on
      their respective sign choices.
    """
    d = (p1.y - p2.y) * (p3.x - p2.x) - (p3.y - p2.y) * (p1.x - p2.x)
    if d > 0:
        return ISCW
    if d < 0:
        return ISCCW
    return ISON


# ── Default indexer ────────────────────────────────────────────────
# C analogue: ``triang.c:30-33``::
#
#     static Ppoint_t point_indexer(void *base, size_t index) {
#       Ppoint_t **b = base;
#       return *b[index];
#     }
#
# Python default: plain list subscription.  Callers that need a
# different lookup (e.g. ``shortest.py`` which stores pointnlink_t
# structs) pass their own indexer.

Indexer = Callable[[Any, int], Ppoint]


def _default_indexer(base: Any, index: int) -> Ppoint:
    return base[index]


# ── between / intersects (private helpers for isdiagonal) ──────────

def _between(pa: Ppoint, pb: Ppoint, pc: Ppoint) -> bool:
    """Return True if ``pb`` is between ``pa`` and ``pc`` on their line.

    C analogue: ``triang.c:94-101``::

        static bool between(Ppoint_t pa, Ppoint_t pb, Ppoint_t pc) {
          const Ppoint_t pba = {.x = pb.x - pa.x, .y = pb.y - pa.y};
          const Ppoint_t pca = {.x = pc.x - pa.x, .y = pc.y - pa.y};
          if (ccw(pa, pb, pc) != ISON) return false;
          return pca.x * pba.x + pca.y * pba.y >= 0 &&
                 pca.x * pca.x + pca.y * pca.y <= pba.x * pba.x + pba.y * pba.y;
        }

    Requires collinearity (``ccw == ISON``) and then does a
    dot-product range check against the ``pa→pb`` segment.
    """
    pba_x = pb.x - pa.x
    pba_y = pb.y - pa.y
    pca_x = pc.x - pa.x
    pca_y = pc.y - pa.y
    if ccw(pa, pb, pc) != ISON:
        return False
    return (pca_x * pba_x + pca_y * pba_y >= 0
            and pca_x * pca_x + pca_y * pca_y <= pba_x * pba_x + pba_y * pba_y)


def _intersects(pa: Ppoint, pb: Ppoint, pc: Ppoint, pd: Ppoint) -> bool:
    """Return True if segments ``(pa, pb)`` and ``(pc, pd)`` intersect.

    C analogue: ``triang.c:104-120``::

        static bool intersects(Ppoint_t pa, Ppoint_t pb, Ppoint_t pc, Ppoint_t pd) {
          int ccw1, ccw2, ccw3, ccw4;
          if (ccw(pa,pb,pc) == ISON || ccw(pa,pb,pd) == ISON ||
              ccw(pc,pd,pa) == ISON || ccw(pc,pd,pb) == ISON) {
            if (between(pa,pb,pc) || between(pa,pb,pd) ||
                between(pc,pd,pa) || between(pc,pd,pb))
              return true;
          } else {
            ccw1 = ccw(pa,pb,pc) == ISCCW ? 1 : 0;
            ccw2 = ccw(pa,pb,pd) == ISCCW ? 1 : 0;
            ccw3 = ccw(pc,pd,pa) == ISCCW ? 1 : 0;
            ccw4 = ccw(pc,pd,pb) == ISCCW ? 1 : 0;
            return (ccw1 ^ ccw2) && (ccw3 ^ ccw4);
          }
          return false;
        }

    Two cases:

    1. **Collinear** (any three of ``pa, pb, pc, pd`` are collinear):
       use ``_between`` to test for overlap.
    2. **General position**: a strict XOR test on CCW orientations.
    """
    if (ccw(pa, pb, pc) == ISON
            or ccw(pa, pb, pd) == ISON
            or ccw(pc, pd, pa) == ISON
            or ccw(pc, pd, pb) == ISON):
        if (_between(pa, pb, pc) or _between(pa, pb, pd)
                or _between(pc, pd, pa) or _between(pc, pd, pb)):
            return True
    else:
        ccw1 = 1 if ccw(pa, pb, pc) == ISCCW else 0
        ccw2 = 1 if ccw(pa, pb, pd) == ISCCW else 0
        ccw3 = 1 if ccw(pc, pd, pa) == ISCCW else 0
        ccw4 = 1 if ccw(pc, pd, pb) == ISCCW else 0
        return bool((ccw1 ^ ccw2) and (ccw3 ^ ccw4))
    return False


# ── isdiagonal ─────────────────────────────────────────────────────

def isdiagonal(i: int, ip2: int, pointp: Any, pointn: int,
               indexer: Optional[Indexer] = None) -> bool:
    """Return True if ``(points[i], points[ip2])`` is a polygon diagonal.

    C analogue: ``triang.c:122-150``.  Two-part test:

    1. **Neighbourhood test** — check that the proposed diagonal lies
       *inside* the polygon at vertex ``i``.  C uses a convex/reflex
       branch on the signs of ``ccw(i-1, i, i+1)``::

           if (ccw(i-1, i, i+1) == ISCCW)
             /* convex at i */
             res = ccw(i, ip2, i-1) == ISCCW &&
                   ccw(ip2, i, i+1) == ISCCW;
           else
             /* reflex at i */
             res = ccw(i, ip2, i+1) == ISCW;

    2. **Edge-intersection test** — walk every polygon edge (except
       the two incident to ``i`` or ``ip2``) and reject the diagonal
       if any edge intersects it.

    ``indexer`` lets callers plug in a different vertex lookup — C
    passes different functions from ``triang.c`` and ``shortest.c``
    because the two files store points differently (raw pointer
    arrays vs. ``pointnlink_t`` linked-list structs).  Python's
    default indexer just does ``pointp[k]``.
    """
    if indexer is None:
        indexer = _default_indexer

    # Neighbourhood test (C lines 127-138)
    ip1 = (i + 1) % pointn
    im1 = (i + pointn - 1) % pointn
    if ccw(indexer(pointp, im1),
           indexer(pointp, i),
           indexer(pointp, ip1)) == ISCCW:
        # convex at i
        res = (ccw(indexer(pointp, i),
                   indexer(pointp, ip2),
                   indexer(pointp, im1)) == ISCCW
               and ccw(indexer(pointp, ip2),
                       indexer(pointp, i),
                       indexer(pointp, ip1)) == ISCCW)
    else:
        # reflex at i (assume i-1, i, i+1 not collinear)
        res = (ccw(indexer(pointp, i),
                   indexer(pointp, ip2),
                   indexer(pointp, ip1)) == ISCW)
    if not res:
        return False

    # Check against every other edge (C lines 140-148)
    for j in range(pointn):
        jp1 = (j + 1) % pointn
        if j == i or jp1 == i or j == ip2 or jp1 == ip2:
            continue
        if _intersects(indexer(pointp, i),
                       indexer(pointp, ip2),
                       indexer(pointp, j),
                       indexer(pointp, jp1)):
            return False
    return True


# ── Ptriangulate (public API) ──────────────────────────────────────

def _point_indexer_triang(base: Any, index: int) -> Ppoint:
    """Indexer for :func:`Ptriangulate`'s working array.

    C analogue: ``triang.c:point_indexer`` lines 30-33::

        static Ppoint_t point_indexer(void *base, size_t index) {
          Ppoint_t **b = base;
          return *b[index];
        }

    In C, ``base`` is an array of pointers to Ppoint_t.  In Python
    we store Ppoint objects directly so the indexer is trivial.
    """
    return base[index]


def _triangulate_recursive(pointp: list, pointn: int,
                            fn: Callable[[Any, list], None],
                            vc: Any) -> int:
    """Recursive ear-clipping helper.

    C analogue: ``triang.c:63-91``.  Returns 0 on success, -1 if no
    diagonal exists (malformed polygon).
    """
    assert pointn >= 3
    if pointn > 3:
        for i in range(pointn):
            ip1 = (i + 1) % pointn
            ip2 = (i + 2) % pointn
            if isdiagonal(i, ip2, pointp, pointn, _point_indexer_triang):
                # Emit triangle
                A = [pointp[i], pointp[ip1], pointp[ip2]]
                fn(vc, A)
                # Remove ip1 from pointp and recurse on one fewer
                # vertex.  C does the removal in-place with a two-
                # pointer walk; Python uses a fresh list for clarity.
                reduced = [pointp[k] for k in range(pointn) if k != ip1]
                return _triangulate_recursive(reduced, pointn - 1, fn, vc)
        return -1
    else:
        A = [pointp[0], pointp[1], pointp[2]]
        fn(vc, A)
    return 0


def Ptriangulate(polygon: Ppoly,
                 fn: Callable[[Any, list], None],
                 vc: Any = None) -> int:
    """Triangulate ``polygon`` by ear-clipping.

    C analogue: ``triang.c:Ptriangulate`` lines 38-57::

        int Ptriangulate(Ppoly_t *polygon,
                         void (*fn)(void *, const Ppoint_t[]),
                         void *vc) {
          const size_t pointn = polygon->pn;
          Ppoint_t **pointp = gv_calloc(pointn, sizeof(Ppoint_t*));
          for (size_t i = 0; i < pointn; i++)
            pointp[i] = &(polygon->ps[i]);
          assert(pointn >= 3);
          if (triangulate(pointp, pointn, fn, vc) != 0) {
            free(pointp); return 1;
          }
          free(pointp);
          return 0;
        }

    ``fn(vc, triangle)`` is called for each ear triangle found,
    where ``triangle`` is a 3-element list of :class:`Ppoint`.
    Callers using ``vc`` as a closure append triangles to it; others
    pass ``vc=None``.

    **Precondition:** vertices must be in CCW order.  Returns 0 on
    success, 1 if triangulation fails (no diagonal found).
    """
    pointn = polygon.pn
    assert pointn >= 3
    # C allocates an Ppoint_t** array pointing into polygon->ps.
    # Python just stores the Ppoint values directly.
    pointp = list(polygon.ps)
    if _triangulate_recursive(pointp, pointn, fn, vc) != 0:
        return 1
    return 0
