"""Point-in-polygon test.

C analogue: ``lib/pathplan/inpoly.c``.
"""
from __future__ import annotations

from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint, Ppoly
from gvpy.engines.layout.dot.pathplan.visibility import wind


def in_poly(poly: Ppoly, q: Ppoint) -> bool:
    """Test if point ``q`` is inside convex polygon ``poly``.

    C analogue: ``inpoly.c:in_poly`` lines 26–35::

        bool in_poly(const Ppoly_t poly, Ppoint_t q) {
          const Ppoint_t *P = poly.ps;
          const size_t n = poly.pn;
          for (size_t i = 0; i < n; i++) {
            const size_t i1 = (i + n - 1) % n;  // i1 = i-1 mod n
            if (wind(P[i1], P[i], q) == 1)
              return false;
          }
          return true;
        }

    **Precondition:** ``poly`` must be convex with vertices in
    clockwise order.  The test walks each edge and checks that ``q``
    is not on the CCW (left-hand) side of any edge — under CW
    winding, a point strictly inside is on the CW side of every edge.

    Returns True for points on the boundary (``wind`` returns 0 for
    collinear points).
    """
    P = poly.ps
    n = poly.pn
    for i in range(n):
        i1 = (i + n - 1) % n
        if wind(P[i1], P[i], q) == 1:
            return False
    return True
