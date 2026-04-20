"""Geometry primitives shared across layout engines.

See: /lib/pathplan/pathgeom.h @ 34  (C counterpart: Ppoint / Ppoly /
Ppolyline / Pedge)
See: /lib/common/geomprocs.h  (bounding-box helpers, bbox_intersect)

Types moved here from ``pathplan/pathgeom.py`` so any engine can
depend on geometry primitives without pulling in the pathplan
subpackage.  ``pathplan/pathgeom.py`` re-exports for back-compat.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ppoint:
    """2D point.

    See: /lib/pathplan/pathgeom.h @ 37
    """

    x: float = 0.0
    y: float = 0.0


# C aliases: ``typedef struct Pxy_t Pvector_t;``
# A Pvector is structurally identical to a Ppoint; C uses the distinct
# name to document intent (direction vs. position).  Python follows.
Pvector = Ppoint


@dataclass
class Ppoly:
    """Polygon as an ordered list of vertices.

    See: /lib/pathplan/pathgeom.h @ 45

    In C, ``pn`` is an explicit ``size_t`` because ``ps`` is a raw
    pointer.  Python's ``list`` carries its length, so ``pn`` is a
    read-only property here — callers that construct a :class:`Ppoly`
    need only supply ``ps``.
    """

    ps: list = field(default_factory=list)

    @property
    def pn(self) -> int:
        return len(self.ps)


# C: ``typedef Ppoly_t Ppolyline_t;``
# Structurally identical to Ppoly; C uses the alias to document that
# the points form an open polyline rather than a closed polygon.
Ppolyline = Ppoly


@dataclass
class Pedge:
    """Directed line segment from ``a`` to ``b``.

    See: /lib/pathplan/pathgeom.h @ 52
    """

    a: Ppoint = field(default_factory=Ppoint)
    b: Ppoint = field(default_factory=Ppoint)


# ── 1D / 2D primitives ───────────────────────────────────────────────

MILLIPOINT = 0.001


def approx_eq(a: Ppoint, b: Ppoint, eps: float = MILLIPOINT) -> bool:
    """True iff two points coincide to within ``eps`` on both axes.

    See: /lib/common/geom.h @ 71
    """
    return abs(a.x - b.x) < eps and abs(a.y - b.y) < eps


def interval_overlap(i0: float, i1: float, j0: float, j1: float) -> float:
    """Length of overlap between two 1D half-open intervals.

    See: /lib/common/routespl.c @ 606

    Returns ``0.0`` if the intervals are disjoint; otherwise the length
    of the intersection.
    """
    if i1 <= j0:
        return 0.0
    if i0 >= j1:
        return 0.0
    if i0 <= j0 and i1 >= j1:
        return i1 - i0
    if j0 <= i0 and j1 >= i1:
        return j1 - j0
    if j0 <= i0 <= j1:
        return j1 - i0
    return i1 - j0
