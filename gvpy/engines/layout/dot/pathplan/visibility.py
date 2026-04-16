"""Visibility graph utilities.

C analogue: ``lib/pathplan/visibility.c``.

This is the Phase B step B2 port of the full visibility graph
builder.  It contains:

- Pure geometry primitives: :func:`area2`, :func:`wind` (landed in
  step B1), :func:`inBetween`, :func:`intersect`, :func:`in_cone`,
  :func:`dist2`, :func:`dist`, :func:`inCone`, :func:`clear`.
- 2D-array allocator: :func:`allocArray`.
- Internal compute pass: :func:`compVis` (builds visibility matrix
  from pairwise vertex checks).
- Public entry points: :func:`visibility` (top-level driver),
  :func:`polyhit` (which-polygon lookup), :func:`ptVis` (visibility
  vector from an external point), :func:`directVis` (two-point
  direct-visibility test).

Every function is a literal transliteration of the C source — same
variable names, same control flow, same predicate semantics.
"""
from __future__ import annotations

import math

from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint, Ppoly
from gvpy.engines.layout.dot.pathplan.vispath import POLYID_NONE, POLYID_UNKNOWN, Vconfig

# Note: ``in_poly`` is imported lazily inside :func:`polyhit` to avoid
# a circular import — ``inpoly.py`` depends on :func:`wind` from this
# module.


# ── Pure geometry primitives ────────────────────────────────────────

def area2(a: Ppoint, b: Ppoint, c: Ppoint) -> float:
    """Return twice the signed area of triangle ``abc``.

    C analogue: ``visibility.c:area2`` lines 46–49::

        COORD area2(Ppoint_t a, Ppoint_t b, Ppoint_t c) {
            return (a.y - b.y) * (c.x - b.x) - (c.y - b.y) * (a.x - b.x);
        }
    """
    return (a.y - b.y) * (c.x - b.x) - (c.y - b.y) * (a.x - b.x)


def wind(a: Ppoint, b: Ppoint, c: Ppoint) -> int:
    """Return ``1`` / ``0`` / ``-1`` for CCW / collinear / CW triangle ``abc``.

    C analogue: ``visibility.c:wind`` lines 55–62.  Collinearity
    tolerance is ``0.0001``, matching C's allowance for
    ``gcc -O2 -ffast-math`` rounding.
    """
    w = (a.y - b.y) * (c.x - b.x) - (c.y - b.y) * (a.x - b.x)
    if w > 0.0001:
        return 1
    if w < -0.0001:
        return -1
    return 0


def inBetween(a: Ppoint, b: Ppoint, c: Ppoint) -> bool:
    """Return True if ``c`` is strictly between ``a`` and ``b`` on their line.

    C analogue: ``visibility.c:inBetween`` lines 67–73.  Assumes
    ``a``, ``b``, ``c`` are collinear; uses x coords when the segment
    is non-vertical, y coords otherwise::

        static bool inBetween(Ppoint_t a, Ppoint_t b, Ppoint_t c) {
          if (a.x != b.x)
            return (a.x < c.x && c.x < b.x) || (b.x < c.x && c.x < a.x);
          else
            return (a.y < c.y && c.y < b.y) || (b.y < c.y && c.y < a.y);
        }

    The comparisons are strict, so endpoint coincidences return False.
    """
    if a.x != b.x:
        return (a.x < c.x < b.x) or (b.x < c.x < a.x)
    return (a.y < c.y < b.y) or (b.y < c.y < a.y)


def intersect(a: Ppoint, b: Ppoint, c: Ppoint, d: Ppoint) -> bool:
    """Return True if segment ``[c,d]`` blocks ``a`` and ``b`` seeing each other.

    C analogue: ``visibility.c:intersect`` lines 80–102.  Returns True
    if any endpoint of ``[c,d]`` lies on ``(a,b)`` or the two segments
    cross as open sets::

        static bool intersect(Ppoint_t a, Ppoint_t b, Ppoint_t c, Ppoint_t d) {
          int a_abc = wind(a, b, c);
          if (a_abc == 0 && inBetween(a, b, c)) return true;
          int a_abd = wind(a, b, d);
          if (a_abd == 0 && inBetween(a, b, d)) return true;
          int a_cda = wind(c, d, a);
          int a_cdb = wind(c, d, b);
          return a_abc * a_abd < 0 && a_cda * a_cdb < 0;
        }
    """
    a_abc = wind(a, b, c)
    if a_abc == 0 and inBetween(a, b, c):
        return True
    a_abd = wind(a, b, d)
    if a_abd == 0 and inBetween(a, b, d):
        return True
    a_cda = wind(c, d, a)
    a_cdb = wind(c, d, b)
    return a_abc * a_abd < 0 and a_cda * a_cdb < 0


def in_cone(a0: Ppoint, a1: Ppoint, a2: Ppoint, b: Ppoint) -> bool:
    """Return True iff point ``b`` is in the closed cone ``a0,a1,a2``.

    C analogue: ``visibility.c:in_cone`` lines 108–117.  Picks between
    two predicates based on whether the cone vertex ``a1`` is convex
    or reflex::

        static bool in_cone(Ppoint_t a0, Ppoint_t a1, Ppoint_t a2, Ppoint_t b) {
          int m = wind(b, a0, a1);
          int p = wind(b, a1, a2);
          if (wind(a0, a1, a2) > 0)
            return m >= 0 && p >= 0;   /* convex at a1 */
          else
            return m >= 0 || p >= 0;   /* reflex at a1 */
        }
    """
    m = wind(b, a0, a1)
    p = wind(b, a1, a2)
    if wind(a0, a1, a2) > 0:
        return m >= 0 and p >= 0
    return m >= 0 or p >= 0


def dist2(a: Ppoint, b: Ppoint) -> float:
    """Return the squared Euclidean distance between ``a`` and ``b``.

    C analogue: ``visibility.c:dist2`` lines 122–128.
    """
    delx = a.x - b.x
    dely = a.y - b.y
    return delx * delx + dely * dely


def dist(a: Ppoint, b: Ppoint) -> float:
    """Return the Euclidean distance between ``a`` and ``b``.

    C analogue: ``visibility.c:dist`` lines 133–136.  Static in C;
    public here because Python has no file-scope access control.
    """
    return math.sqrt(dist2(a, b))


def inCone(i: int, j: int, pts: list, nextPt: list, prevPt: list) -> bool:
    """Index-based :func:`in_cone` for polygon vertices.

    C analogue: ``visibility.c:inCone`` lines 138–141.  Looks up the
    prev/next neighbours of vertex ``i`` and tests whether vertex
    ``j`` is in the cone they define::

        static bool inCone(int i, int j, Ppoint_t pts[],
                           int nextPt[], int prevPt[]) {
          return in_cone(pts[prevPt[i]], pts[i], pts[nextPt[i]], pts[j]);
        }
    """
    return in_cone(pts[prevPt[i]], pts[i], pts[nextPt[i]], pts[j])


def clear(pti: Ppoint, ptj: Ppoint, start: int, end: int,
          V: int, pts: list, nextPt: list) -> bool:
    """Return True iff no polygon segment non-trivially blocks ``[pti, ptj]``.

    C analogue: ``visibility.c:clear`` lines 147–162.  Walks every
    polygon edge in ``[0, start) ∪ [end, V)``, testing each against
    ``intersect``; segments in ``[start, end)`` (the polygon the
    caller is hiding) are skipped.
    """
    for k in range(0, start):
        if intersect(pti, ptj, pts[k], pts[nextPt[k]]):
            return False
    for k in range(end, V):
        if intersect(pti, ptj, pts[k], pts[nextPt[k]]):
            return False
    return True


# ── 2D array allocator ──────────────────────────────────────────────

def allocArray(V: int, extra: int) -> list:
    """Allocate a ``V × V`` matrix with ``extra`` trailing ``None`` rows.

    C analogue: ``visibility.c:allocArray`` lines 26–41.  C uses a
    flat ``V * V`` block of ``COORD`` with row pointers; Python uses
    nested lists.  The extra rows at positions ``V..V+extra-1`` are
    ``None`` placeholders — :func:`Pobspath` later fills them with
    visibility vectors for the two query points ``p`` and ``q``.

    ``extra`` is typically ``2`` (one row each for ``p`` and ``q``).
    """
    assert V >= 0, f"V must be non-negative, got {V}"
    arr: list = [[0.0] * V for _ in range(V)]
    arr.extend([None] * extra)
    return arr


# ── Private: build the visibility matrix ────────────────────────────

def compVis(conf: Vconfig) -> None:
    """Populate ``conf.vis`` with pairwise vertex-visibility distances.

    C analogue: ``visibility.c:compVis`` lines 171–206.  For each
    vertex ``i``, add an edge of length ``dist(pts[i], pts[prev[i]])``
    to the polygon-edge neighbour, then scan all earlier vertices
    ``j < i`` and add an edge if:

    1. ``j`` is in ``i``'s cone (``inCone(i, j, ...)``)
    2. ``i`` is in ``j``'s cone (``inCone(j, i, ...)``)
    3. The segment ``pts[i]-pts[j]`` is clear of every other polygon
       edge (``clear(..., V, V, V, ...)``)

    All three conditions must hold for the pair to be visible.
    """
    V = conf.N
    pts = conf.P
    nextPt = conf.next
    prevPt = conf.prev
    wadj = conf.vis
    assert wadj is not None, "compVis called before allocArray"

    for i in range(V):
        # Add the polygon edge between ``i`` and ``previ``.
        # Works for polygons of 1 or 2 vertices at the cost of some
        # redundant work (C note preserved).
        previ = prevPt[i]
        d = dist(pts[i], pts[previ])
        wadj[i][previ] = d
        wadj[previ][i] = d

        # Scan earlier vertices.  If ``previ`` is ``i - 1`` (the usual
        # case — polygon is walked in order), skip ``i - 1`` because
        # it's already been handled; otherwise include it.
        if previ == i - 1:
            j_start = i - 2
        else:
            j_start = i - 1
        j = j_start
        while j >= 0:
            if (inCone(i, j, pts, nextPt, prevPt) and
                    inCone(j, i, pts, nextPt, prevPt) and
                    clear(pts[i], pts[j], V, V, V, pts, nextPt)):
                d = dist(pts[i], pts[j])
                wadj[i][j] = d
                wadj[j][i] = d
            j -= 1


# ── Public entry points ─────────────────────────────────────────────

def visibility(conf: Vconfig) -> None:
    """Build the visibility graph for ``conf``.

    C analogue: ``visibility.c:visibility`` lines 213–217.  Allocates
    ``conf.vis`` with ``N + 2`` rows (the 2 extras are placeholders
    for the two query points ``Pobspath`` will add dynamically), then
    calls :func:`compVis` to populate the first ``N`` rows.
    """
    conf.vis = allocArray(conf.N, 2)
    compVis(conf)


def polyhit(conf: Vconfig, p: Ppoint) -> int:
    """Return the index of the polygon containing ``p``, or ``POLYID_NONE``.

    C analogue: ``visibility.c:polyhit`` lines 224–236.  Walks every
    polygon in ``conf`` and tests with :func:`~...inpoly.in_poly`::

        static int polyhit(vconfig_t *conf, Ppoint_t p) {
          Ppoly_t poly;
          for (int i = 0; i < conf->Npoly; i++) {
            poly.ps = &(conf->P[conf->start[i]]);
            poly.pn = conf->start[i+1] - conf->start[i];
            if (in_poly(poly, p)) return i;
          }
          return POLYID_NONE;
        }
    """
    # Lazy import: inpoly.py → visibility.py → inpoly.py cycle.
    from gvpy.engines.layout.dot.pathplan.inpoly import in_poly

    for i in range(conf.Npoly):
        sub_ps = conf.P[conf.start[i]:conf.start[i + 1]]
        poly = Ppoly(ps=sub_ps)
        if in_poly(poly, p):
            return i
    return POLYID_NONE


def ptVis(conf: Vconfig, pp: int, p: Ppoint) -> list:
    """Compute a visibility vector from point ``p`` to every barrier vertex.

    C analogue: ``visibility.c:ptVis`` lines 247–299.  Returns a list
    of length ``N + 2`` where entry ``k`` (for ``k < N``) is:

    - ``dist(p, pts[k])`` if ``p`` and ``pts[k]`` can see each other
    - ``0`` otherwise (including any vertex inside ``p``'s own polygon)

    The final two slots (``vadj[N]``, ``vadj[N+1]``) are zero
    placeholders, matching C's caller-filled positions for the two
    query points in ``Pobspath``.

    ``pp`` is the polygon index containing ``p``:

    - ``pp >= 0`` — skip that polygon's edges when checking visibility
    - ``POLYID_NONE`` — ``p`` is not inside any polygon; use all edges
    - ``POLYID_UNKNOWN`` — caller doesn't know; call :func:`polyhit` first
    """
    V = conf.N
    pts = conf.P
    nextPt = conf.next
    prevPt = conf.prev

    vadj: list = [0.0] * (V + 2)

    if pp == POLYID_UNKNOWN:
        pp = polyhit(conf, p)
    if pp >= 0:
        start = conf.start[pp]
        end = conf.start[pp + 1]
    else:
        start = V
        end = V

    for k in range(0, start):
        pk = pts[k]
        if (in_cone(pts[prevPt[k]], pk, pts[nextPt[k]], p) and
                clear(p, pk, start, end, V, pts, nextPt)):
            vadj[k] = dist(p, pk)
        else:
            vadj[k] = 0.0

    for k in range(start, end):
        vadj[k] = 0.0

    for k in range(end, V):
        pk = pts[k]
        if (in_cone(pts[prevPt[k]], pk, pts[nextPt[k]], p) and
                clear(p, pk, start, end, V, pts, nextPt)):
            vadj[k] = dist(p, pk)
        else:
            vadj[k] = 0.0

    # C: vadj[V] = 0; vadj[V + 1] = 0;  (already zero from init)
    vadj[V] = 0.0
    vadj[V + 1] = 0.0

    return vadj


def directVis(p: Ppoint, pp: int, q: Ppoint, qp: int, conf: Vconfig) -> bool:
    """Return True if ``p`` and ``q`` have unobstructed line-of-sight.

    C analogue: ``visibility.c:directVis`` lines 306–355.  Walks every
    polygon edge except those belonging to the polygons of ``p`` and
    ``q``, testing each against :func:`intersect`.

    Both endpoint polygon indices (``pp``, ``qp``) work the same way:
    - ``>= 0`` — skip that polygon's edges
    - ``POLYID_NONE`` / negative — don't skip any edges
    """
    V = conf.N
    pts = conf.P
    nextPt = conf.next

    # Determine the two skip ranges ``[s1, e1)`` and ``[s2, e2)``.
    # C does a cascade of four branches; we preserve it literally so
    # the port matches case-by-case.
    if pp < 0:
        s1 = 0
        e1 = 0
        if qp < 0:
            s2 = 0
            e2 = 0
        else:
            s2 = conf.start[qp]
            e2 = conf.start[qp + 1]
    elif qp < 0:
        s1 = 0
        e1 = 0
        s2 = conf.start[pp]
        e2 = conf.start[pp + 1]
    elif pp <= qp:
        s1 = conf.start[pp]
        e1 = conf.start[pp + 1]
        s2 = conf.start[qp]
        e2 = conf.start[qp + 1]
    else:
        s1 = conf.start[qp]
        e1 = conf.start[qp + 1]
        s2 = conf.start[pp]
        e2 = conf.start[pp + 1]

    for k in range(0, s1):
        if intersect(p, q, pts[k], pts[nextPt[k]]):
            return False
    for k in range(e1, s2):
        if intersect(p, q, pts[k], pts[nextPt[k]]):
            return False
    for k in range(e2, V):
        if intersect(p, q, pts[k], pts[nextPt[k]]):
            return False
    return True
