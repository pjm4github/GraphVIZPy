"""Pathplan utility helpers.

C analogue: ``lib/pathplan/util.c``.
"""
from __future__ import annotations

from gvpy.engines.layout.dot.pathplan.pathgeom import Pedge, Ppoly, Ppolyline


def Ppolybarriers(polys: list[Ppoly]) -> list[Pedge]:
    """Flatten a list of polygons into a single list of edge barriers.

    C analogue: ``util.c:Ppolybarriers`` lines 24–42::

        int Ppolybarriers(Ppoly_t **polys, int npolys, Pedge_t **barriers,
                          int *n_barriers) {
          LIST(Pedge_t) bar = {0};
          for (int i = 0; i < npolys; i++) {
            const Ppoly_t pp = *polys[i];
            for (size_t j = 0; j < pp.pn; j++) {
              size_t k = j + 1;
              if (k >= pp.pn) k = 0;
              LIST_APPEND(&bar, ((Pedge_t){.a = pp.ps[j], .b = pp.ps[k]}));
            }
          }
          ...
          return 1;
        }

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

    C analogue: ``util.c:make_polyline`` lines 44–62.  Each interior
    point of the input line is duplicated three times and the
    endpoints twice, producing the ``[P0, P0, P1, P1, P1, ..., Pn, Pn]``
    layout that Graphviz's cubic-Bezier format expects (first anchor
    + triples of subsequent anchors).

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

    C analogue: ``util.c:freePath`` lines 19–22::

        void freePath(Ppolyline_t *p) {
          free(p->ps);
          free(p);
        }

    Python's garbage collector handles this automatically.  The
    function exists as a no-op for callers that mirror C's manual
    free pattern.
    """
    # Intentionally empty.
    pass
