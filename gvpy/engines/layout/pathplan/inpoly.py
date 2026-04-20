"""Point-in-polygon test.

See: /lib/pathplan/inpoly.c @ 26
"""
from __future__ import annotations

from gvpy.engines.layout.pathplan.pathgeom import Ppoint, Ppoly
from gvpy.engines.layout.pathplan.visibility import wind


def in_poly(poly: Ppoly, q: Ppoint) -> bool:
    """Test if point ``q`` is inside convex polygon ``poly``.

    See: /lib/pathplan/inpoly.c @ 26

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
