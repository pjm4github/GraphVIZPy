"""Shared ortho data structures — port of ``lib/ortho/structures.h``.

Types here are consumed by every ortho module (``maze``, ``sgraph``,
``ortho``) so they live in their own file to avoid import cycles.
Field names and semantics track the C header verbatim; deviation would
break the step-for-step trace diff workflow described in
``ORTHO_PORT_PLAN.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


@dataclass
class Paird:
    """``typedef struct { double p1, p2; } paird;``"""
    p1: float = 0.0
    p2: float = 0.0


@dataclass
class Pair:
    """``typedef struct { int a, b; } pair;``"""
    a: int = 0
    b: int = 0


@dataclass
class Pair2:
    """``typedef struct { pair t1, t2; } pair2;``"""
    t1: Pair = field(default_factory=Pair)
    t2: Pair = field(default_factory=Pair)


class Bend(IntEnum):
    """``typedef enum { B_NODE, B_UP, B_LEFT, B_DOWN, B_RIGHT } bend;``"""
    B_NODE = 0
    B_UP = 1
    B_LEFT = 2
    B_DOWN = 3
    B_RIGHT = 4


@dataclass
class Segment:
    """A single axis-aligned segment of an orthogonal route.

    Port of ``struct segment`` in ``structures.h``.  Example: a segment
    connecting maze points (3, 2) and (3, 8) has ``is_vert=True``,
    ``comm_coord=3``, ``p=Paird(2, 8)``.
    """
    is_vert: bool = False
    comm_coord: float = 0.0
    p: Paird = field(default_factory=Paird)
    l1: Bend = Bend.B_NODE
    l2: Bend = Bend.B_NODE
    ind_no: Optional[int] = None
    track_no: Optional[int] = None
    prev: Optional["Segment"] = None
    next: Optional["Segment"] = None


@dataclass
class Route:
    """``typedef struct { size_t n; segment* segs; } route;``"""
    segs: list[Segment] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.segs)


@dataclass
class Channel:
    """Port of ``channel`` — a row/column of segments sharing an axis.

    ``G`` is a :class:`rawgraph.Rawgraph` (interference graph); ``cp``
    is the :class:`maze.Cell` the channel lives in.  Both typed as
    ``object`` at scaffold time to avoid forward-import pain before
    phases 1 and 5 land.
    """
    p: Paird = field(default_factory=Paird)
    seg_list: list[Segment] = field(default_factory=list)
    G: object = None
    cp: object = None
