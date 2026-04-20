"""Geometry primitives shared across layout engines.

See: /lib/pathplan/pathgeom.h @ 34  (C counterpart: Ppoint / Ppoly /
Ppolyline / Pedge)
See: /lib/common/geomprocs.h  (bounding-box helpers, bbox_intersect)

Types moved here from ``dot/pathplan/pathgeom.py`` so any engine can
depend on geometry primitives without pulling in the dot-specific
pathplan subpackage.  ``dot/pathplan/pathgeom.py`` re-exports for
back-compat.
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
