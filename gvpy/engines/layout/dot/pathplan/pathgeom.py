"""Pathplan geometry primitives.

See: /lib/pathplan/pathgeom.h @ 34

Defines the fundamental point, vector, polygon, polyline, and edge
types used throughout the pathplan port.  These mirror the C structs
one-for-one but use Python idiom:

- ``Ppoint`` / ``Pvector`` — both are the same 2D ``(x, y)`` struct in
  C (typedef of ``Pxy_t``).  Python uses one class with a module-level
  alias so call sites read naturally.
- ``Ppoly`` — polygon with a mutable list of vertices.  C stores an
  explicit ``size_t pn`` field because ``ps`` is a raw pointer;
  Python's ``list`` carries its length so ``pn`` is exposed as a
  property that delegates to ``len(ps)``.
- ``Ppolyline`` — C typedefs it identically to ``Ppoly_t``; we do the
  same.
- ``Pedge`` — a line segment between two points.
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
