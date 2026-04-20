"""Transient routing workspace for phase-4 spline routing.

See: /lib/common/types.h @ 73

These classes mirror the C structs that :mod:`splines` will need for a
literal port of ``dot_splines_`` and its helpers.  They are strictly
compute-time workspace — a single :class:`Path` and :class:`SplineInfo`
are allocated once per ``phase4_routing`` call and reused across every
edge routed in the pass.  The *result* of routing lives on
:class:`~gvpy.engines.layout.dot.edge_route.EdgeRoute`, not here.

Mapping to C
------------

=====================  ================================================
Python                 C analogue
=====================  ================================================
:class:`Box`           ``boxf`` in ``lib/common/geom.h``
:class:`PathEnd`       ``pathend_t`` in ``lib/common/types.h``
:class:`Path`          ``path`` in ``lib/common/types.h``
:class:`SplineInfo`    ``spline_info_t`` in ``lib/dotgen/dotsplines.c``
=====================  ================================================

The flag-bit constants (``REGULAREDGE`` … ``AUXGRAPH``) mirror the
``#define``\\ s in ``lib/common/const.h`` lines 149–155 and
``lib/dotgen/dotsplines.c`` lines 41–47.  Together they compose the
``tree_index`` field on ``LayoutEdge``, which C stores via
``ED_tree_index(e)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── Sidemask bits ───────────────────────────────────────────────────────
# See: /lib/common/const.h @ 111

BOTTOM_IX = 0
RIGHT_IX = 1
TOP_IX = 2
LEFT_IX = 3

BOTTOM = 1 << BOTTOM_IX
RIGHT = 1 << RIGHT_IX
TOP = 1 << TOP_IX
LEFT = 1 << LEFT_IX


# ── Spline router tunables ───────────────────────────────────────────────
# See: /lib/dotgen/dotsplines.c @ 37

NSUB = 9
"""Number of subdivisions when re-aiming splines.  C: ``NSUB``."""

MINW = 16
"""Minimum width of a box in the edge path.  C: ``MINW``."""

HALFMINW = 8
"""``MINW / 2``.  C: ``HALFMINW``."""

FUDGE = 4
"""Horizontal padding added by :func:`maximal_bbox` around each node
when computing the maximum bbox it can claim for routing.  C:
``dotsplines.c:2171`` — *"The extra space provided by FUDGE allows
begin/endpath to create a box FUDGE-2 away from the node, so the
routing can avoid the node and the box is at least 2 wide."*"""


# ── Edge type enum (lib/common/const.h:234-240) ─────────────────────────
# Selects the routing algorithm used by ``dot_splines_``.  Values
# are pre-shifted by 1 (C uses ``(n << 1)`` so bit 0 is available as
# a flag in some callers).

EDGETYPE_NONE = 0 << 1
EDGETYPE_LINE = 1 << 1
EDGETYPE_CURVED = 2 << 1
EDGETYPE_PLINE = 3 << 1
EDGETYPE_ORTHO = 4 << 1
EDGETYPE_SPLINE = 5 << 1
EDGETYPE_COMPOUND = 6 << 1


def edge_type_from_splines(splines: str) -> int:
    """Map the Python ``splines`` attribute string to a C ``EDGETYPE_*``.

    Used by the phase 4 driver for trace emissions that mirror C's
    ``phase4 begin: et=<int>`` format.  Default (empty, ``"true"``,
    ``"spline"``) is :data:`EDGETYPE_SPLINE` — same as C's
    ``EDGE_TYPE(g)`` for graphs without an explicit splines attribute.
    """
    s = (splines or "").strip().lower()
    if s in ("", "true", "spline"):
        return EDGETYPE_SPLINE
    if s == "line" or s == "false":
        return EDGETYPE_LINE if s == "line" else EDGETYPE_NONE
    if s == "curved":
        return EDGETYPE_CURVED
    if s == "polyline":
        return EDGETYPE_PLINE
    if s == "ortho":
        return EDGETYPE_ORTHO
    if s == "compound":
        return EDGETYPE_COMPOUND
    if s == "none":
        return EDGETYPE_NONE
    return EDGETYPE_SPLINE  # default fallback


# ── Tree-index flag bits ────────────────────────────────────────────────
# See: /lib/common/const.h @ 150
#
# ``LayoutEdge.tree_index`` is the bitwise OR of one value from each of
# the three groups: one edge-type flag, one direction flag, and one
# graph-type flag.  ``setflags`` assigns it during the top-level driver
# pass, ``edgecmp`` reads it for equivalence-class grouping, and the
# per-edge routers branch on it.

# Edge type (bits 0-3, masked by EDGETYPEMASK):
REGULAREDGE = 1
FLATEDGE = 2
SELFWPEDGE = 4   # self-edge with at least one port defined
SELFNPEDGE = 8   # self-edge with no ports defined
EDGETYPEMASK = 15

# Direction (bits 4-5):
FWDEDGE = 16
BWDEDGE = 32

# Graph type (bits 6-7, masked by GRAPHTYPEMASK):
MAINGRAPH = 64
AUXGRAPH = 128
GRAPHTYPEMASK = 192


# ── Box ──────────────────────────────────────────────────────────────────
# See: /lib/common/geom.h @ 41

@dataclass
class Box:
    """Axis-aligned 2D bounding box.

    Mutable so router box-path construction can widen a box in place
    (see ``adjustregularpath`` in ``dotsplines.c``, which stretches box
    edges to meet ``MINW``).
    """

    ll_x: float = 0.0
    ll_y: float = 0.0
    ur_x: float = 0.0
    ur_y: float = 0.0

    @property
    def width(self) -> float:
        return self.ur_x - self.ll_x

    @property
    def height(self) -> float:
        return self.ur_y - self.ll_y

    def is_valid(self) -> bool:
        """True iff ``ll`` is strictly below-and-left of ``ur``.

        See: /lib/common/geom.h @ 41
        """
        return self.ll_x < self.ur_x and self.ll_y < self.ur_y


# ── Port ─────────────────────────────────────────────────────────────────
# See: /lib/common/types.h @ 48

@dataclass
class Port:
    """Internal edge endpoint specification.

    See: /lib/common/types.h @ 48

    Default is an **undefined** port at the origin, matching C's
    zero-initialised ``port`` struct.
    """

    defined: bool = False
    p: tuple[float, float] = (0.0, 0.0)
    side: int = 0
    theta: float = 0.0
    constrained: bool = False
    dyna: bool = False
    clip: bool = True
    order: int = 0
    name: str = ""


# ── PathEnd ──────────────────────────────────────────────────────────────
# See: /lib/common/types.h @ 73

PATH_END_BOX_MAX = 20
"""Maximum number of end boxes, matching C ``pathend_t.boxes[20]``."""


@dataclass
class PathEnd:
    """Per-end routing state for one side of an edge.

    Fields mirror C ``pathend_t`` one-for-one:

    - ``nb``        — the node box (C ``boxf nb``)
    - ``np``        — node port anchor point (C ``pointf np``)
    - ``sidemask``  — bitwise OR of ``TOP`` / ``BOTTOM`` / ``LEFT`` /
      ``RIGHT`` (C ``int sidemask``)
    - ``boxn``      — count of valid entries in ``boxes``
      (C ``int boxn``)
    - ``boxes``     — end-side region boxes, up to :data:`PATH_END_BOX_MAX`
      (C ``boxf boxes[20]``)

    ``theta`` and ``constrained`` are not in C ``pathend_t`` — C stores
    them on the parent ``path``'s ``port start`` / ``port end`` fields.
    We hoist them up here so they travel together with the end-box
    chain, which is how every caller uses them anyway.
    """

    nb: Box = field(default_factory=Box)
    np: tuple[float, float] = (0.0, 0.0)
    sidemask: int = 0
    boxn: int = 0
    boxes: list = field(default_factory=list)
    theta: float = 0.0
    constrained: bool = False


# ── Path ─────────────────────────────────────────────────────────────────
# See: /lib/common/types.h @ 81

@dataclass
class Path:
    """Transient routing workspace for one edge.

    A single :class:`Path` is allocated once by ``phase4_routing`` and
    reused across every edge routed in the pass.  Before routing each
    edge the driver resets ``nbox`` to 0 (C: ``P->nbox = 0``) and
    re-populates ``boxes``.  ``start`` and ``end`` are refilled by
    ``beginpath`` / ``endpath`` from the node + port + sidemask.

    C ``port start`` / ``port end`` carry extra fields (defined, clip,
    dyna, order, side, name) that live on :class:`LayoutEdge` or are
    recomputed on demand.  This struct only holds what the router
    mutates mid-route.

    C ``void *data`` is omitted — it is only used by the neato engine.
    """

    boxes: list = field(default_factory=list)
    nbox: int = 0
    start: PathEnd = field(default_factory=PathEnd)
    end: PathEnd = field(default_factory=PathEnd)


# ── SplineInfo ───────────────────────────────────────────────────────────
# See: /lib/dotgen/dotsplines.c @ 71

@dataclass
class SplineInfo:
    """Per-phase routing context.

    Allocated once by ``dot_splines_`` and passed by value (in C) or
    by reference (here) to every router helper.

    - ``left_bound`` / ``right_bound`` — graph-wide x bounds with
      ``MINW`` padding, used to clamp end boxes (C ``LeftBound`` /
      ``RightBound``).
    - ``splinesep`` — spline-to-cluster separation, ``GD_nodesep(g)/4``
      (C ``Splinesep``).
    - ``multisep`` — separation between parallel edges in a group,
      ``GD_nodesep(g)`` (C ``Multisep``).
    - ``rank_box`` — sparse cache of inter-rank corridor boxes,
      mapping rank index → :class:`Box`.  Mirrors the C
      ``boxf *Rank_box`` array which is lazily filled by the
      ``rank_box`` helper.
    """

    left_bound: float = 0.0
    right_bound: float = 0.0
    splinesep: float = 0.0
    multisep: float = 0.0
    rank_box: dict = field(default_factory=dict)


# ── Path construction helpers (B7) ──────────────────────────────────
# See: /lib/common/splines.c @ 338
#
# C accesses node/edge fields via macros (``ND_coord``, ``ED_tail_port``
# etc.).  Python passes the needed values explicitly to avoid circular
# imports between this module and ``dot_layout.py``.

_FUDGE_BEGINEND = 2
"""C ``#define FUDGE 2`` in ``splines.c:374``.  Distinct from
``FUDGE = 4`` in path.py line 61 (used by ``maximal_bbox``)."""


def add_box(P: Path, b: Box) -> None:
    """Append *b* to the path's box chain if it is valid.

    See: /lib/common/splines.c @ 338
    """
    if b.ll_x < b.ur_x and b.ll_y < b.ur_y:
        P.boxes.append(b)
        P.nbox += 1


def beginpath(P: Path, et: int, endp: PathEnd, merge: bool, *,
              node_x: float, node_y: float,
              node_lw: float, node_rw: float, node_ht2: float,
              port_p: tuple[float, float] = (0.0, 0.0),
              port_side: int = 0,
              port_theta: float = 0.0,
              port_constrained: bool = False,
              is_normal: bool = True,
              ranksep: float = 0.0) -> bool:
    """Set up boxes near the **tail** node for spline routing.

    See: /lib/common/splines.c @ 378

    Sets ``P.start`` (point + theta/constrained) and fills
    ``endp.boxes`` / ``endp.boxn`` / ``endp.sidemask`` with 1-2
    boxes that anchor the spline to the tail node.

    Returns ``True`` if the caller should set ``clip = False`` on
    the original edge's tail port (C handles this internally via
    the ``ED_to_orig`` chain; Python lets the caller decide).

    Node geometry is passed explicitly:

    - *node_x*, *node_y* — ``ND_coord(n)``
    - *node_lw*, *node_rw* — ``ND_lw(n)``, ``ND_rw(n)``
    - *node_ht2* — ``ND_ht(n) / 2``
    - *port_p* — ``ED_tail_port(e).p`` (offset from node center)
    - *port_side* — ``ED_tail_port(e).side`` bitmask
    - *port_theta* — ``ED_tail_port(e).theta``
    - *port_constrained* — ``ED_tail_port(e).constrained``
    - *is_normal* — ``ND_node_type(n) == NORMAL``
    - *ranksep* — ``GD_ranksep(agraphof(n))``
    """
    import math

    start_x = node_x + port_p[0]
    start_y = node_y + port_p[1]

    if merge:
        P.start.theta = -math.pi / 2
        P.start.constrained = True
    else:
        if port_constrained:
            P.start.theta = port_theta
            P.start.constrained = True
        else:
            P.start.constrained = False

    P.nbox = 0
    P.boxes.clear()
    endp.np = (start_x, start_y)
    P.start.np = (start_x, start_y)

    # ── REGULAREDGE with a compass-port side ────────────────────
    if et == REGULAREDGE and is_normal and port_side:
        side = port_side
        b = Box(endp.nb.ll_x, endp.nb.ll_y, endp.nb.ur_x, endp.nb.ur_y)
        if side & TOP:
            endp.sidemask = TOP
            if start_x < node_x:
                b0 = Box(
                    ll_x=b.ll_x - 1,
                    ll_y=start_y,
                    ur_x=b.ur_x,
                    ur_y=node_y + node_ht2 + ranksep / 2,
                )
                b.ur_x = node_x - node_lw - (_FUDGE_BEGINEND - 2)
                b.ur_y = b0.ll_y
                b.ll_y = node_y - node_ht2
                b.ll_x -= 1
                endp.boxes = [b0, b]
            else:
                b0 = Box(
                    ll_x=b.ll_x,
                    ll_y=start_y,
                    ur_x=b.ur_x + 1,
                    ur_y=node_y + node_ht2 + ranksep / 2,
                )
                b.ll_x = node_x + node_rw + (_FUDGE_BEGINEND - 2)
                b.ur_y = b0.ll_y
                b.ll_y = node_y - node_ht2
                b.ur_x += 1
                endp.boxes = [b0, b]
            start_y += 1
            endp.boxn = 2
        elif side & BOTTOM:
            endp.sidemask = BOTTOM
            b.ur_y = max(b.ur_y, start_y)
            endp.boxes = [b]
            endp.boxn = 1
            start_y -= 1
        elif side & LEFT:
            endp.sidemask = LEFT
            b.ur_x = start_x
            b.ll_y = node_y - node_ht2
            b.ur_y = start_y
            endp.boxes = [b]
            endp.boxn = 1
            start_x -= 1
        else:
            endp.sidemask = RIGHT
            b.ll_x = start_x
            b.ll_y = node_y - node_ht2
            b.ur_y = start_y
            endp.boxes = [b]
            endp.boxn = 1
            start_x += 1
        P.start.np = (start_x, start_y)
        endp.np = P.start.np
        return True  # caller should set clip=False on orig tail port

    # ── FLATEDGE with a compass-port side ───────────────────────
    if et == FLATEDGE and port_side:
        side = port_side
        b = Box(endp.nb.ll_x, endp.nb.ll_y, endp.nb.ur_x, endp.nb.ur_y)
        if side & TOP:
            b.ll_y = min(b.ll_y, start_y)
            endp.boxes = [b]
            endp.boxn = 1
            start_y += 1
        elif side & BOTTOM:
            if endp.sidemask == TOP:
                b0 = Box(
                    ll_x=start_x,
                    ll_y=node_y - node_ht2 - ranksep / 2,
                    ur_x=b.ur_x + 1,
                    ur_y=node_y - node_ht2,
                )
                b.ll_x = node_x + node_rw + (_FUDGE_BEGINEND - 2)
                b.ll_y = b0.ur_y
                b.ur_y = node_y + node_ht2
                b.ur_x += 1
                endp.boxes = [b0, b]
                endp.boxn = 2
            else:
                b.ur_y = max(b.ur_y, start_y)
                endp.boxes = [b]
                endp.boxn = 1
            start_y -= 1
        elif side & LEFT:
            b.ur_x = start_x + 1
            if endp.sidemask == TOP:
                b.ur_y = node_y + node_ht2
                b.ll_y = start_y - 1
            else:
                b.ll_y = node_y - node_ht2
                b.ur_y = start_y + 1
            endp.boxes = [b]
            endp.boxn = 1
            start_x -= 1
        else:
            b.ll_x = start_x
            if endp.sidemask == TOP:
                b.ur_y = node_y + node_ht2
                b.ll_y = start_y
            else:
                b.ll_y = node_y - node_ht2
                b.ur_y = start_y + 1
            endp.boxes = [b]
            endp.boxn = 1
            start_x += 1
        endp.sidemask = side
        P.start.np = (start_x, start_y)
        endp.np = P.start.np
        return True  # caller should set clip=False on orig tail port

    # ── Fallback: no port side or pboxfn ────────────────────────
    if et == REGULAREDGE:
        side = BOTTOM
    else:
        side = endp.sidemask

    endp.boxes = [Box(endp.nb.ll_x, endp.nb.ll_y, endp.nb.ur_x, endp.nb.ur_y)]
    endp.boxn = 1

    if et == FLATEDGE:
        if endp.sidemask == TOP:
            endp.boxes[0].ll_y = start_y
        else:
            endp.boxes[0].ur_y = start_y
    elif et == REGULAREDGE:
        endp.boxes[0].ur_y = start_y
        endp.sidemask = BOTTOM
        start_y -= 1

    P.start.np = (start_x, start_y)
    endp.np = P.start.np
    return False


def endpath(P: Path, et: int, endp: PathEnd, merge: bool, *,
            node_x: float, node_y: float,
            node_lw: float, node_rw: float, node_ht2: float,
            port_p: tuple[float, float] = (0.0, 0.0),
            port_side: int = 0,
            port_theta: float = 0.0,
            port_constrained: bool = False,
            is_normal: bool = True,
            ranksep: float = 0.0) -> bool:
    """Set up boxes near the **head** node for spline routing.

    See: /lib/common/splines.c @ 575

    Mirror image of :func:`beginpath` for the head end.  Sets
    ``P.end`` and fills ``endp`` for the final 1-2 boxes of the
    corridor.  Returns ``True`` if the caller should set
    ``clip = False`` on the original edge's head port.

    Parameters are identical to :func:`beginpath`; see its docstring
    for descriptions.
    """
    import math

    end_x = node_x + port_p[0]
    end_y = node_y + port_p[1]

    if merge:
        P.end.theta = math.pi / 2 + math.pi
        P.end.constrained = True
    else:
        if port_constrained:
            P.end.theta = port_theta
            P.end.constrained = True
        else:
            P.end.constrained = False

    endp.np = (end_x, end_y)
    P.end.np = (end_x, end_y)

    # ── REGULAREDGE with a compass-port side ────────────────────
    if et == REGULAREDGE and is_normal and port_side:
        side = port_side
        b = Box(endp.nb.ll_x, endp.nb.ll_y, endp.nb.ur_x, endp.nb.ur_y)
        if side & TOP:
            endp.sidemask = TOP
            b.ll_y = min(b.ll_y, end_y)
            endp.boxes = [b]
            endp.boxn = 1
            end_y += 1
        elif side & BOTTOM:
            endp.sidemask = BOTTOM
            if end_x < node_x:
                b0 = Box(
                    ll_x=b.ll_x - 1,
                    ll_y=node_y - node_ht2 - ranksep / 2,
                    ur_x=b.ur_x,
                    ur_y=end_y,
                )
                b.ur_x = node_x - node_lw - (_FUDGE_BEGINEND - 2)
                b.ll_y = b0.ur_y
                b.ur_y = node_y + node_ht2
                b.ll_x -= 1
                endp.boxes = [b0, b]
            else:
                b0 = Box(
                    ll_x=b.ll_x,
                    ll_y=node_y - node_ht2 - ranksep / 2,
                    ur_x=b.ur_x + 1,
                    ur_y=end_y,
                )
                b.ll_x = node_x + node_rw + (_FUDGE_BEGINEND - 2)
                b.ll_y = b0.ur_y
                b.ur_y = node_y + node_ht2
                b.ur_x += 1
                endp.boxes = [b0, b]
            endp.boxn = 2
            end_y -= 1
        elif side & LEFT:
            endp.sidemask = LEFT
            b.ur_x = end_x
            b.ur_y = node_y + node_ht2
            b.ll_y = end_y
            endp.boxes = [b]
            endp.boxn = 1
            end_x -= 1
        else:
            endp.sidemask = RIGHT
            b.ll_x = end_x
            b.ur_y = node_y + node_ht2
            b.ll_y = end_y
            endp.boxes = [b]
            endp.boxn = 1
            end_x += 1
        endp.sidemask = side
        P.end.np = (end_x, end_y)
        endp.np = P.end.np
        return True  # caller should set clip=False on orig head port

    # ── FLATEDGE with a compass-port side ───────────────────────
    if et == FLATEDGE and port_side:
        side = port_side
        b = Box(endp.nb.ll_x, endp.nb.ll_y, endp.nb.ur_x, endp.nb.ur_y)
        if side & TOP:
            b.ll_y = min(b.ll_y, end_y)
            endp.boxes = [b]
            endp.boxn = 1
            end_y += 1
        elif side & BOTTOM:
            if endp.sidemask == TOP:
                b0 = Box(
                    ll_x=b.ll_x - 1,
                    ll_y=node_y - node_ht2 - ranksep / 2,
                    ur_x=end_x,
                    ur_y=node_y - node_ht2,
                )
                b.ur_x = node_x - node_lw - 2
                b.ll_y = b0.ur_y
                b.ur_y = node_y + node_ht2
                b.ll_x -= 1
                endp.boxes = [b0, b]
                endp.boxn = 2
            else:
                b.ur_y = max(b.ur_y, P.start.np[1])
                endp.boxes = [b]
                endp.boxn = 1
            end_y -= 1
        elif side & LEFT:
            b.ur_x = end_x + 1
            if endp.sidemask == TOP:
                b.ur_y = node_y + node_ht2
                b.ll_y = end_y - 1
            else:
                b.ll_y = node_y - node_ht2
                b.ur_y = end_y + 1
            endp.boxes = [b]
            endp.boxn = 1
            end_x -= 1
        else:
            b.ll_x = end_x - 1
            if endp.sidemask == TOP:
                b.ur_y = node_y + node_ht2
                b.ll_y = end_y - 1
            else:
                b.ll_y = node_y - node_ht2
                b.ur_y = end_y
            endp.boxes = [b]
            endp.boxn = 1
            end_x += 1
        endp.sidemask = side
        P.end.np = (end_x, end_y)
        endp.np = P.end.np
        return True  # caller should set clip=False on orig head port

    # ── Fallback: no port side or pboxfn ────────────────────────
    if et == REGULAREDGE:
        side = TOP
    else:
        side = endp.sidemask

    endp.boxes = [Box(endp.nb.ll_x, endp.nb.ll_y, endp.nb.ur_x, endp.nb.ur_y)]
    endp.boxn = 1

    if et == FLATEDGE:
        if endp.sidemask == TOP:
            endp.boxes[0].ll_y = end_y
        else:
            endp.boxes[0].ur_y = end_y
    elif et == REGULAREDGE:
        endp.boxes[0].ll_y = end_y
        endp.sidemask = TOP
        end_y += 1

    P.end.np = (end_x, end_y)
    endp.np = P.end.np
    return False
