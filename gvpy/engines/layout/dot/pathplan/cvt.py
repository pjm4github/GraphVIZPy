"""Visibility-graph configuration + obstacle-avoidance path finder.

See: /lib/pathplan/cvt.c @ 28

Three public entry points:

- :func:`Pobsopen` — build a :class:`Vconfig` from a list of polygon
  obstacles and populate its visibility graph.
- :func:`Pobsclose` — free the Vconfig (no-op in Python).
- :func:`Pobspath` — compute the shortest polyline from ``p0`` to
  ``p1`` that avoids every obstacle in a prepared :class:`Vconfig`.

This is the **final** glue layer for the pathplan obstacle-avoidance
pipeline: a single ``Pobspath`` call drives
``ptVis`` → ``makePath`` → back-pointer walk and returns a clean
:class:`Ppolyline`.  The only remaining pathplan work is
``route.c`` (step B5: ``Proutespline``).
"""
from __future__ import annotations

from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint, Ppoly, Ppolyline
from gvpy.engines.layout.dot.pathplan.shortestpth import makePath
from gvpy.engines.layout.dot.pathplan.visibility import ptVis, visibility
from gvpy.engines.layout.dot.pathplan.vispath import Vconfig


def Pobsopen(obs: list[Ppoly]) -> Vconfig:
    """Build a :class:`Vconfig` from a list of polygonal obstacles.

    See: /lib/pathplan/cvt.c @ 28

    Takes a list of obstacle polygons (each in CW vertex order per
    the pathplan convention), flattens them into the Vconfig's
    ``P`` / ``start`` / ``next`` / ``prev`` layout, and calls
    :func:`visibility` to populate the visibility matrix.  The
    returned :class:`Vconfig` is ready for :func:`Pobspath` queries.

    Python deviation: C takes ``obstacles`` as ``Ppoly_t **obs, int n_obs``
    (double-pointer + count); Python takes a flat ``list[Ppoly]``.
    """
    rv = Vconfig(Npoly=len(obs))

    # Count total vertices across all polygons.
    n = 0
    for p in obs:
        n += p.pn
    rv.N = n

    # Allocate flat arrays sized to N.  C uses calloc; Python uses
    # zero/None lists of the right length.
    rv.P = [Ppoint(0.0, 0.0)] * n
    rv.start = [0] * (len(obs) + 1)
    rv.next = [0] * n
    rv.prev = [0] * n

    # Build the flat arrays.  Each polygon's vertices go into
    # contiguous slots [start..end]; the next/prev pointers form a
    # doubly-linked ring within each polygon's range.
    i = 0
    for poly_i in range(len(obs)):
        start = i
        rv.start[poly_i] = start
        end = start + obs[poly_i].pn - 1
        for pt_i in range(obs[poly_i].pn):
            rv.P[i] = obs[poly_i].ps[pt_i]
            rv.next[i] = i + 1
            rv.prev[i] = i - 1
            i += 1
        # Close the ring: last vertex's next points at first, first's
        # prev points at last.  Overwrites the ``i + 1`` / ``i - 1``
        # values written by the inner loop at the ring endpoints.
        rv.next[end] = start
        rv.prev[start] = end

    # Sentinel: start[Npoly] == N so iteration over start[i..i+1]
    # works uniformly for every polygon including the last.
    rv.start[len(obs)] = i

    # Populate the visibility matrix.
    visibility(rv)
    return rv


def Pobsclose(config: Vconfig) -> None:
    """Free a Vconfig.  No-op in Python — Python's GC handles cleanup.

    See: /lib/pathplan/cvt.c @ 89

    C frees ``P``, ``start``, ``next``, ``prev``, the visibility
    matrix rows, and the vconfig itself.  Python's reference counter
    does all of this automatically when the last reference drops.
    Kept as a symmetric API entry so call sites that mirror C's
    manual-free pattern compile unchanged.
    """
    # Intentionally empty.
    _ = config


def Pobspath(config: Vconfig, p0: Ppoint, poly0: int,
             p1: Ppoint, poly1: int) -> Ppolyline:
    """Shortest polyline from ``p0`` to ``p1`` avoiding all obstacles.

    See: /lib/pathplan/cvt.c @ 102

    Python deviation: C takes an ``output_route`` out-parameter;
    Python returns the :class:`Ppolyline` directly.

    Pipeline:

    1. :func:`ptVis` twice — compute the visibility vectors for the
       two endpoints against all barrier vertices.
    2. :func:`makePath` — find the shortest-path ``dad`` back-pointer
       array through the visibility graph.
    3. Walk ``dad`` from ``N`` (== ``p1``) back through intermediate
       barrier vertices to ``N + 1`` (== ``p0``), building the
       output polyline in natural ``[p0, vertex, vertex, ..., p1]``
       order.

    ``poly0`` / ``poly1`` are polygon-index hints for the two
    endpoints (see :data:`...vispath.POLYID_NONE` /
    :data:`...vispath.POLYID_UNKNOWN`).
    """
    ptvis0 = ptVis(config, poly0, p0)
    ptvis1 = ptVis(config, poly1, p1)

    dad = makePath(p0, poly0, ptvis0, p1, poly1, ptvis1, config)

    N = config.N

    # Count output vertices: 1 for p0 + every intermediate + 1 for p1.
    opn = 1
    i = dad[N]
    while i != N + 1:
        opn += 1
        i = dad[i]
    opn += 1

    # Build output array in reverse — C uses a ``j`` index walking
    # from opn-1 down to 0.  Literal port.
    ops: list = [Ppoint(0.0, 0.0)] * opn
    j = opn - 1
    ops[j] = p1
    j -= 1
    i = dad[N]
    while i != N + 1:
        ops[j] = config.P[i]
        j -= 1
        i = dad[i]
    ops[j] = p0
    assert j == 0, f"back-pointer walk mismatch: j={j}"

    return Ppolyline(ps=ops)
