"""Pathplan geometry primitives.

C analogue: ``lib/pathplan/pathgeom.h`` lines 33–54.

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
    """2D point.  C analogue: ``Ppoint_t`` / ``Pxy_t`` in
    ``pathgeom.h:37-41``::

        typedef struct Pxy_t {
            double x, y;
        } Pxy_t;

        typedef struct Pxy_t Ppoint_t;
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

    C analogue: ``Ppoly_t`` in ``pathgeom.h:45-48``::

        typedef struct Ppoly_t {
            Ppoint_t *ps;
            size_t pn;
        } Ppoly_t;

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

    C analogue: ``Pedge_t`` in ``pathgeom.h:52-54``::

        typedef struct Pedge_t {
            Ppoint_t a, b;
        } Pedge_t;
    """

    a: Ppoint = field(default_factory=Ppoint)
    b: Ppoint = field(default_factory=Ppoint)
