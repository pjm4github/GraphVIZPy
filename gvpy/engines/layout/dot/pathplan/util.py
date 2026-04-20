"""Pathplan utility helpers.

See: /lib/pathplan/util.c @ 19
"""
from __future__ import annotations

from gvpy.engines.layout.dot.pathplan.pathgeom import Pedge, Ppoly, Ppolyline


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


def make_polyline(line: Ppolyline) -> Ppolyline:
    """Expand a polyline into a bezier-ready control-point sequence.

    See: /lib/pathplan/util.c @ 44

    Each interior point of the input line is duplicated three times
    and the endpoints twice, producing the
    ``[P0, P0, P1, P1, P1, ..., Pn, Pn]`` layout that Graphviz's
    cubic-Bezier format expects (first anchor + triples of subsequent
    anchors).

    Python deviation: C uses a ``static LIST(Ppoint_t) ispline`` which
    is cleared between calls — a thread-unsafe optimisation.  Python
    returns a fresh :class:`Ppolyline` on every call.  The C function
    also takes an output-parameter ``sline``; Python returns the
    expanded polyline directly.
    """
    if line.pn == 0:
        return Ppolyline(ps=[])
    ispline: list = []
    i = 0
    ispline.append(line.ps[i])
    ispline.append(line.ps[i])
    i += 1
    while i + 1 < line.pn:
        ispline.append(line.ps[i])
        ispline.append(line.ps[i])
        ispline.append(line.ps[i])
        i += 1
    ispline.append(line.ps[i])
    ispline.append(line.ps[i])
    return Ppolyline(ps=ispline)


def freePath(p: Ppolyline) -> None:
    """No-op: C frees the heap-allocated ``ps`` array and the wrapper.

    See: /lib/pathplan/util.c @ 19

    Python's garbage collector handles this automatically.  The
    function exists as a no-op for callers that mirror C's manual
    free pattern.
    """
    # Intentionally empty.
    pass
