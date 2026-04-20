"""Pathplan utility helpers.

See: /lib/pathplan/util.c @ 19
"""
from __future__ import annotations

from gvpy.engines.layout.pathplan.pathgeom import Pedge, Ppoly, Ppolyline


def Ppolybarriers(polys: list[Ppoly]) -> list[Pedge]:
    """Flatten a list of polygons into a single list of edge barriers.

    See: /lib/pathplan/util.c @ 24

    Python deviation: C uses a double-pointer output parameter for
    the barrier list and a separate int for the count.  Python just
    returns the list directly — the count is ``len(result)``.
    ``npolys`` is implicit (``len(polys)``).  Success return value
    (``1`` in C) is dropped; callers can check for an empty return.
    """
    bar: list[Pedge] = []
    for pp in polys:
        n = pp.pn
        for j in range(n):
            k = j + 1
            if k >= n:
                k = 0
            bar.append(Pedge(a=pp.ps[j], b=pp.ps[k]))
    return bar


# Canonical implementation lives in :mod:`common.splines`.  Kept here
# as a re-export so existing ``pathplan.util.make_polyline`` imports
# continue to resolve.
from gvpy.engines.layout.common.splines import make_polyline  # noqa: F401


def freePath(p: Ppolyline) -> None:
    """No-op: C frees the heap-allocated ``ps`` array and the wrapper.

    See: /lib/pathplan/util.c @ 19

    Python's garbage collector handles this automatically.  The
    function exists as a no-op for callers that mirror C's manual
    free pattern.
    """
    # Intentionally empty.
    pass
