"""Port of ``lib/ortho/trapezoid.{h,c}`` — Seidel's randomized trapezoidation.

Decomposes a planar subdivision defined by line segments into
trapezoids.  Used by :mod:`partition` to slice cluster bounding boxes
into axis-aligned rectangles, which :mod:`maze` then treats as the
routing obstacle grid.

Semantics track the C verbatim:

- **1-indexed inputs.**  Segments are ``seg[1..nseg]``; ``seg[0]`` is
  a placeholder.  Permutation entries are 1-indexed segment numbers,
  but the permutation array itself is 0-indexed.
- **Trap sentinel at index 0.**  ``traps[0]`` is a zero-filled
  placeholder so the ``is_valid_trap`` check ``i != 0 and i != -1``
  disambiguates unset / explicitly-invalid indices.
- **DBL_MAX sentinels** for the topmost / bottommost trapezoid corners
  are represented as :data:`math.inf` / :data:`-math.inf`.  The C
  harness in ``tools/trapezoid_harness/`` emits literal ``INF`` /
  ``-INF`` for these, so Python's ``float("inf")`` matches on repr.
- **Float tolerance** ``C_EPS = 1e-7`` governs collinearity and
  left/right-of-segment decisions — decrease if inputs are very close
  together.
- **Permutation is caller-supplied.**  The C API takes an ``int *``
  permutation that fixes the segment-insertion order; we preserve that
  contract so tests can pin determinism.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.common.geom import Ppoint

# Q-node types.
T_X = 1
T_Y = 2
T_SINK = 3

# inserted() point selectors.
FIRSTPT = 1
LASTPT = 2

# merge_trapezoids() side selectors.
S_LEFT = 1
S_RIGHT = 2

# Float tolerance.
C_EPS = 1.0e-7

# Sentinel values for trap-index fields (u0/u1/d0/d1/sink/usave).
UNSET_TRAP = 0
INVALID_TRAP = -1  # mirrors C's SIZE_MAX


# ---------- predicates + helpers (trap.h inline functions) ----------


def fp_equal(s: float, t: float) -> bool:
    return abs(s - t) <= C_EPS


def dfp_cmp(f1: float, f2: float) -> int:
    """Three-way comparison with tolerance: <0, ~=0, >0 → -1, 0, 1."""
    d = f1 - f2
    if d < -C_EPS:
        return -1
    if d > C_EPS:
        return 1
    return 0


def equal_to(v0: Ppoint, v1: Ppoint) -> bool:
    return fp_equal(v0.y, v1.y) and fp_equal(v0.x, v1.x)


def greater_than(v0: Ppoint, v1: Ppoint) -> bool:
    """y-major with tolerance; x tie-breaks when y-equal."""
    if v0.y > v1.y + C_EPS:
        return True
    if v0.y < v1.y - C_EPS:
        return False
    return v0.x > v1.x


def greater_than_equal_to(v0: Ppoint, v1: Ppoint) -> bool:
    return greater_than(v0, v1) or equal_to(v0, v1)


def less_than(v0: Ppoint, v1: Ppoint) -> bool:
    return not greater_than_equal_to(v0, v1)


def is_valid_trap(index: int) -> bool:
    return index != UNSET_TRAP and index != INVALID_TRAP


def _cross(v0: Ppoint, v1: Ppoint, v2: Ppoint) -> float:
    return (v1.x - v0.x) * (v2.y - v0.y) - (v1.y - v0.y) * (v2.x - v0.x)


def _max(v0: Ppoint, v1: Ppoint) -> Ppoint:
    if v0.y > v1.y + C_EPS:
        return v0
    if fp_equal(v0.y, v1.y):
        if v0.x > v1.x + C_EPS:
            return v0
        return v1
    return v1


def _min(v0: Ppoint, v1: Ppoint) -> Ppoint:
    if v0.y < v1.y - C_EPS:
        return v0
    if fp_equal(v0.y, v1.y):
        if v0.x < v1.x:
            return v0
        return v1
    return v1


# ---------- data types (trap.h structs) ----------


@dataclass
class TrapSegment:
    """Port of ``segment_t`` in ``trap.h``.

    Segments carry a doubly-linked chain via :attr:`prev` / :attr:`next`
    so :func:`inserted` can tell whether an endpoint was already
    threaded by a neighbouring segment.
    """
    v0: Ppoint = field(default_factory=Ppoint)
    v1: Ppoint = field(default_factory=Ppoint)
    is_inserted: bool = False
    root0: int = 0
    root1: int = 0
    next: int = 0
    prev: int = 0


@dataclass
class Trap:
    """Port of ``trap_t`` in ``trap.h``."""
    lseg: int = 0
    rseg: int = 0
    hi: Ppoint = field(default_factory=Ppoint)
    lo: Ppoint = field(default_factory=Ppoint)
    u0: int = 0
    u1: int = 0
    d0: int = 0
    d1: int = 0
    sink: int = 0
    usave: int = 0
    uside: int = 0
    is_valid: bool = False


@dataclass
class QNode:
    """Internal query-structure node (T_X / T_Y / T_SINK).

    Lives only inside :mod:`trapezoid`; not exported.
    """
    nodetype: int = 0
    segnum: int = 0
    yval: Ppoint = field(default_factory=Ppoint)
    trnum: int = 0
    parent: int = 0
    left: int = 0
    right: int = 0


# ---------- list allocators ----------


def _new_node(qs: list[QNode]) -> int:
    qs.append(QNode())
    return len(qs) - 1


def _new_trap(tr: list[Trap]) -> int:
    tr.append(Trap())
    return len(tr) - 1


# ---------- init_query_structure ----------


def _init_query_structure(segnum: int, seg: list[TrapSegment],
                          tr: list[Trap], qs: list[QNode]) -> int:
    """First-segment seed: 4 trapezoids + 7 Q-nodes.  ``trapezoid.c:122``."""
    s = seg[segnum]

    i1 = _new_node(qs)
    qs[i1].nodetype = T_Y
    qs[i1].yval = _max(s.v0, s.v1)
    root = i1

    i2 = _new_node(qs)
    qs[i1].right = i2
    qs[i2].nodetype = T_SINK
    qs[i2].parent = i1

    i3 = _new_node(qs)
    qs[i1].left = i3
    qs[i3].nodetype = T_Y
    qs[i3].yval = _min(s.v0, s.v1)
    qs[i3].parent = i1

    i4 = _new_node(qs)
    qs[i3].left = i4
    qs[i4].nodetype = T_SINK
    qs[i4].parent = i3

    i5 = _new_node(qs)
    qs[i3].right = i5
    qs[i5].nodetype = T_X
    qs[i5].segnum = segnum
    qs[i5].parent = i3

    i6 = _new_node(qs)
    qs[i5].left = i6
    qs[i6].nodetype = T_SINK
    qs[i6].parent = i5

    i7 = _new_node(qs)
    qs[i5].right = i7
    qs[i7].nodetype = T_SINK
    qs[i7].parent = i5

    t1 = _new_trap(tr)  # middle left
    t2 = _new_trap(tr)  # middle right
    t3 = _new_trap(tr)  # bottom-most
    t4 = _new_trap(tr)  # topmost

    tr[t1].hi = qs[i1].yval
    tr[t2].hi = qs[i1].yval
    tr[t4].lo = qs[i1].yval
    tr[t1].lo = qs[i3].yval
    tr[t2].lo = qs[i3].yval
    tr[t3].hi = qs[i3].yval
    tr[t4].hi = Ppoint(math.inf, math.inf)
    tr[t3].lo = Ppoint(-math.inf, -math.inf)
    tr[t1].rseg = segnum
    tr[t2].lseg = segnum
    tr[t1].u0 = t4
    tr[t2].u0 = t4
    tr[t1].d0 = t3
    tr[t2].d0 = t3
    tr[t4].d0 = t1
    tr[t3].u0 = t1
    tr[t4].d1 = t2
    tr[t3].u1 = t2

    tr[t1].sink = i6
    tr[t2].sink = i7
    tr[t3].sink = i4
    tr[t4].sink = i2

    tr[t1].is_valid = True
    tr[t2].is_valid = True
    tr[t3].is_valid = True
    tr[t4].is_valid = True

    qs[i2].trnum = t4
    qs[i4].trnum = t3
    qs[i6].trnum = t1
    qs[i7].trnum = t2

    s.is_inserted = True
    return root


# ---------- point-vs-segment side test ----------


def _is_left_of(segnum: int, seg: list[TrapSegment], v: Ppoint) -> bool:
    """``trapezoid.c:213``.  Cross-product side test with y-tiebreak."""
    s = seg[segnum]
    if greater_than(s.v1, s.v0):  # segment going upwards
        if fp_equal(s.v1.y, v.y):
            area = 1.0 if v.x < s.v1.x else -1.0
        elif fp_equal(s.v0.y, v.y):
            area = 1.0 if v.x < s.v0.x else -1.0
        else:
            area = _cross(s.v0, s.v1, v)
    else:  # v0 > v1
        if fp_equal(s.v1.y, v.y):
            area = 1.0 if v.x < s.v1.x else -1.0
        elif fp_equal(s.v0.y, v.y):
            area = 1.0 if v.x < s.v0.x else -1.0
        else:
            area = _cross(s.v1, s.v0, v)
    return area > 0.0


def _inserted(segnum: int, seg: list[TrapSegment], whichpt: int) -> bool:
    """``trapezoid.c:258``."""
    if whichpt == FIRSTPT:
        return seg[seg[segnum].prev].is_inserted
    return seg[seg[segnum].next].is_inserted


# ---------- locate_endpoint (recursive Q-tree descent) ----------


def _locate_endpoint(v: Ppoint, vo: Ppoint, r: int,
                     seg: list[TrapSegment], qs: list[QNode]) -> int:
    """``trapezoid.c:269``.  Recursive; depth O(log n) on average."""
    rptr = qs[r]

    if rptr.nodetype == T_SINK:
        return rptr.trnum

    if rptr.nodetype == T_Y:
        if greater_than(v, rptr.yval):
            return _locate_endpoint(v, vo, rptr.right, seg, qs)
        if equal_to(v, rptr.yval):
            if greater_than(vo, rptr.yval):
                return _locate_endpoint(v, vo, rptr.right, seg, qs)
            return _locate_endpoint(v, vo, rptr.left, seg, qs)
        return _locate_endpoint(v, vo, rptr.left, seg, qs)

    # T_X
    if (equal_to(v, seg[rptr.segnum].v0)
            or equal_to(v, seg[rptr.segnum].v1)):
        if fp_equal(v.y, vo.y):  # horizontal segment
            if vo.x < v.x:
                return _locate_endpoint(v, vo, rptr.left, seg, qs)
            return _locate_endpoint(v, vo, rptr.right, seg, qs)
        if _is_left_of(rptr.segnum, seg, vo):
            return _locate_endpoint(v, vo, rptr.left, seg, qs)
        return _locate_endpoint(v, vo, rptr.right, seg, qs)
    if _is_left_of(rptr.segnum, seg, v):
        return _locate_endpoint(v, vo, rptr.left, seg, qs)
    return _locate_endpoint(v, vo, rptr.right, seg, qs)


# ---------- merge_trapezoids ----------


def _merge_trapezoids(segnum: int, tfirst: int, tlast: int, side: int,
                      tr: list[Trap], qs: list[QNode]) -> None:
    """``trapezoid.c:316``.  Merge same-segment neighbours on one side."""
    t = tfirst
    while is_valid_trap(t) and greater_than_equal_to(tr[t].lo, tr[tlast].lo):
        tnext = 0
        cond = False
        if side == S_LEFT:
            tnext = tr[t].d0
            cond = is_valid_trap(tnext) and tr[tnext].rseg == segnum
            if not cond:
                tnext = tr[t].d1
                cond = is_valid_trap(tnext) and tr[tnext].rseg == segnum
        else:
            tnext = tr[t].d0
            cond = is_valid_trap(tnext) and tr[tnext].lseg == segnum
            if not cond:
                tnext = tr[t].d1
                cond = is_valid_trap(tnext) and tr[tnext].lseg == segnum

        if cond:
            if (tr[t].lseg == tr[tnext].lseg
                    and tr[t].rseg == tr[tnext].rseg):
                # Good neighbours — merge.
                ptnext = qs[tr[tnext].sink].parent
                if qs[ptnext].left == tr[tnext].sink:
                    qs[ptnext].left = tr[t].sink
                else:
                    qs[ptnext].right = tr[t].sink

                # Fix upper-neighbour links on the lower traps.
                tr[t].d0 = tr[tnext].d0
                if is_valid_trap(tr[t].d0):
                    if tr[tr[t].d0].u0 == tnext:
                        tr[tr[t].d0].u0 = t
                    elif tr[tr[t].d0].u1 == tnext:
                        tr[tr[t].d0].u1 = t

                tr[t].d1 = tr[tnext].d1
                if is_valid_trap(tr[t].d1):
                    if tr[tr[t].d1].u0 == tnext:
                        tr[tr[t].d1].u0 = t
                    elif tr[tr[t].d1].u1 == tnext:
                        tr[tr[t].d1].u1 = t

                tr[t].lo = tr[tnext].lo
                tr[tnext].is_valid = False  # invalidate lower
            else:
                t = tnext
        else:
            t = tnext


# ---------- update_trapezoid ----------


def _update_trapezoid(s: TrapSegment, seg: list[TrapSegment],
                      tr: list[Trap], t: int, tn: int) -> None:
    """``trapezoid.c:376``.  Fix upper-neighbour pointers during split."""
    if is_valid_trap(tr[t].u0) and is_valid_trap(tr[t].u1):
        # Continuation of a chain from above.
        if is_valid_trap(tr[t].usave):
            # Three upper neighbours.
            if tr[t].uside == S_LEFT:
                tr[tn].u0 = tr[t].u1
                tr[t].u1 = INVALID_TRAP
                tr[tn].u1 = tr[t].usave

                tr[tr[t].u0].d0 = t
                tr[tr[tn].u0].d0 = tn
                tr[tr[tn].u1].d0 = tn
            else:
                # Intersects on the right.
                tr[tn].u1 = INVALID_TRAP
                tr[tn].u0 = tr[t].u1
                tr[t].u1 = tr[t].u0
                tr[t].u0 = tr[t].usave

                tr[tr[t].u0].d0 = t
                tr[tr[t].u1].d0 = t
                tr[tr[tn].u0].d0 = tn

            tr[t].usave = 0
            tr[tn].usave = 0
        else:
            # No usave — simple case.
            tr[tn].u0 = tr[t].u1
            tr[t].u1 = INVALID_TRAP
            tr[tn].u1 = INVALID_TRAP
            tr[tr[tn].u0].d0 = tn
    else:
        # Fresh segment or upward cusp.
        tmp_u = tr[t].u0
        td0 = tr[tmp_u].d0
        if is_valid_trap(td0) and is_valid_trap(tr[tmp_u].d1):
            # Upward cusp.
            if (tr[td0].rseg > 0
                    and not _is_left_of(tr[td0].rseg, seg, s.v1)):
                tr[t].u0 = INVALID_TRAP
                tr[t].u1 = INVALID_TRAP
                tr[tn].u1 = INVALID_TRAP
                tr[tr[tn].u0].d1 = tn
            else:
                # Cusp going leftwards.
                tr[tn].u0 = INVALID_TRAP
                tr[tn].u1 = INVALID_TRAP
                tr[t].u1 = INVALID_TRAP
                tr[tr[t].u0].d0 = t
        else:
            # Fresh segment.
            tr[tr[t].u0].d0 = t
            tr[tr[t].u0].d1 = tn


# ---------- add_segment ----------


def _add_segment(segnum: int, seg: list[TrapSegment],
                 tr: list[Trap], qs: list[QNode]) -> None:
    """``trapezoid.c:448``.  Thread segment ``segnum`` into the trapezoidation."""
    # Work on a shallow copy so swapping v0/v1 doesn't mutate the input.
    orig = seg[segnum]
    s = TrapSegment(
        v0=Ppoint(orig.v0.x, orig.v0.y),
        v1=Ppoint(orig.v1.x, orig.v1.y),
        is_inserted=orig.is_inserted,
        root0=orig.root0,
        root1=orig.root1,
        next=orig.next,
        prev=orig.prev,
    )

    if greater_than(s.v1, s.v0):
        s.v0, s.v1 = s.v1, s.v0
        s.root0, s.root1 = s.root1, s.root0
        is_swapped = True
    else:
        is_swapped = False

    tribot = False

    # Insert v0.
    if not _inserted(segnum, seg, LASTPT if is_swapped else FIRSTPT):
        tu = _locate_endpoint(s.v0, s.v1, s.root0, seg, qs)
        tl = _new_trap(tr)
        _copy_trap(tr[tl], tr[tu])
        tr[tu].lo = s.v0
        tr[tl].hi = s.v0
        tr[tu].d0 = tl
        tr[tu].d1 = 0
        tr[tl].u0 = tu
        tr[tl].u1 = 0

        tmp_d = tr[tl].d0
        if is_valid_trap(tmp_d) and tr[tmp_d].u0 == tu:
            tr[tmp_d].u0 = tl
        tmp_d = tr[tl].d0
        if is_valid_trap(tmp_d) and tr[tmp_d].u1 == tu:
            tr[tmp_d].u1 = tl

        tmp_d = tr[tl].d1
        if is_valid_trap(tmp_d) and tr[tmp_d].u0 == tu:
            tr[tmp_d].u0 = tl
        tmp_d = tr[tl].d1
        if is_valid_trap(tmp_d) and tr[tmp_d].u1 == tu:
            tr[tmp_d].u1 = tl

        i1 = _new_node(qs)
        i2 = _new_node(qs)
        sk = tr[tu].sink

        qs[sk].nodetype = T_Y
        qs[sk].yval = s.v0
        qs[sk].segnum = segnum
        qs[sk].left = i2
        qs[sk].right = i1

        qs[i1].nodetype = T_SINK
        qs[i1].trnum = tu
        qs[i1].parent = sk

        qs[i2].nodetype = T_SINK
        qs[i2].trnum = tl
        qs[i2].parent = sk

        tr[tu].sink = i1
        tr[tl].sink = i2
        tfirst = tl
    else:
        tfirst = _locate_endpoint(s.v0, s.v1, s.root0, seg, qs)

    # Insert v1.
    if not _inserted(segnum, seg, FIRSTPT if is_swapped else LASTPT):
        tu = _locate_endpoint(s.v1, s.v0, s.root1, seg, qs)
        tl = _new_trap(tr)
        _copy_trap(tr[tl], tr[tu])
        tr[tu].lo = s.v1
        tr[tl].hi = s.v1
        tr[tu].d0 = tl
        tr[tu].d1 = 0
        tr[tl].u0 = tu
        tr[tl].u1 = 0

        tmp_d = tr[tl].d0
        if is_valid_trap(tmp_d) and tr[tmp_d].u0 == tu:
            tr[tmp_d].u0 = tl
        tmp_d = tr[tl].d0
        if is_valid_trap(tmp_d) and tr[tmp_d].u1 == tu:
            tr[tmp_d].u1 = tl

        tmp_d = tr[tl].d1
        if is_valid_trap(tmp_d) and tr[tmp_d].u0 == tu:
            tr[tmp_d].u0 = tl
        tmp_d = tr[tl].d1
        if is_valid_trap(tmp_d) and tr[tmp_d].u1 == tu:
            tr[tmp_d].u1 = tl

        i1 = _new_node(qs)
        i2 = _new_node(qs)
        sk = tr[tu].sink

        qs[sk].nodetype = T_Y
        qs[sk].yval = s.v1
        qs[sk].segnum = segnum
        qs[sk].left = i2
        qs[sk].right = i1

        qs[i1].nodetype = T_SINK
        qs[i1].trnum = tu
        qs[i1].parent = sk

        qs[i2].nodetype = T_SINK
        qs[i2].trnum = tl
        qs[i2].parent = sk

        tr[tu].sink = i1
        tr[tl].sink = i2
        tlast = tu
    else:
        tlast = _locate_endpoint(s.v1, s.v0, s.root1, seg, qs)
        tribot = True

    tfirstr = 0
    tlastr = 0
    t = tfirst

    while is_valid_trap(t) and greater_than_equal_to(tr[t].lo, tr[tlast].lo):
        sk = tr[t].sink
        i1 = _new_node(qs)
        i2 = _new_node(qs)

        qs[sk].nodetype = T_X
        qs[sk].segnum = segnum
        qs[sk].left = i1
        qs[sk].right = i2

        qs[i1].nodetype = T_SINK
        qs[i1].trnum = t
        qs[i1].parent = sk

        qs[i2].nodetype = T_SINK
        tn = _new_trap(tr)
        qs[i2].trnum = tn
        tr[tn].is_valid = True
        qs[i2].parent = sk

        if t == tfirst:
            tfirstr = tn
        if equal_to(tr[t].lo, tr[tlast].lo):
            tlastr = tn

        _copy_trap(tr[tn], tr[t])
        tr[t].sink = i1
        tr[tn].sink = i2
        t_sav = t
        tn_sav = tn

        if not is_valid_trap(tr[t].d0) and not is_valid_trap(tr[t].d1):
            print("add_segment: error", file=sys.stderr)
            break

        elif is_valid_trap(tr[t].d0) and not is_valid_trap(tr[t].d1):
            _update_trapezoid(s, seg, tr, t, tn)

            if (fp_equal(tr[t].lo.y, tr[tlast].lo.y)
                    and fp_equal(tr[t].lo.x, tr[tlast].lo.x) and tribot):
                # Bottom forms a triangle.
                tmptriseg = (seg[segnum].prev if is_swapped
                             else seg[segnum].next)
                if tmptriseg > 0 and _is_left_of(tmptriseg, seg, s.v0):
                    # L-R downward cusp.
                    tr[tr[t].d0].u0 = t
                    tr[tn].d0 = INVALID_TRAP
                    tr[tn].d1 = INVALID_TRAP
                else:
                    # R-L downward cusp.
                    tr[tr[tn].d0].u1 = tn
                    tr[t].d0 = INVALID_TRAP
                    tr[t].d1 = INVALID_TRAP
            else:
                if (is_valid_trap(tr[tr[t].d0].u0)
                        and is_valid_trap(tr[tr[t].d0].u1)):
                    if tr[tr[t].d0].u0 == t:
                        tr[tr[t].d0].usave = tr[tr[t].d0].u1
                        tr[tr[t].d0].uside = S_LEFT
                    else:
                        tr[tr[t].d0].usave = tr[tr[t].d0].u0
                        tr[tr[t].d0].uside = S_RIGHT
                tr[tr[t].d0].u0 = t
                tr[tr[t].d0].u1 = tn

            t = tr[t].d0

        elif not is_valid_trap(tr[t].d0) and is_valid_trap(tr[t].d1):
            _update_trapezoid(s, seg, tr, t, tn)

            if (fp_equal(tr[t].lo.y, tr[tlast].lo.y)
                    and fp_equal(tr[t].lo.x, tr[tlast].lo.x) and tribot):
                tmptriseg = (seg[segnum].prev if is_swapped
                             else seg[segnum].next)
                if tmptriseg > 0 and _is_left_of(tmptriseg, seg, s.v0):
                    # L-R downward cusp.
                    tr[tr[t].d1].u0 = t
                    tr[tn].d0 = INVALID_TRAP
                    tr[tn].d1 = INVALID_TRAP
                else:
                    # R-L downward cusp.
                    tr[tr[tn].d1].u1 = tn
                    tr[t].d0 = INVALID_TRAP
                    tr[t].d1 = INVALID_TRAP
            else:
                if (is_valid_trap(tr[tr[t].d1].u0)
                        and is_valid_trap(tr[tr[t].d1].u1)):
                    if tr[tr[t].d1].u0 == t:
                        tr[tr[t].d1].usave = tr[tr[t].d1].u1
                        tr[tr[t].d1].uside = S_LEFT
                    else:
                        tr[tr[t].d1].usave = tr[tr[t].d1].u0
                        tr[tr[t].d1].uside = S_RIGHT
                tr[tr[t].d1].u0 = t
                tr[tr[t].d1].u1 = tn

            t = tr[t].d1

        else:
            # Two trapezoids below — pick the one intersected by s.
            i_d0 = False
            if fp_equal(tr[t].lo.y, s.v0.y):
                if tr[t].lo.x > s.v0.x:
                    i_d0 = True
            else:
                y0 = tr[t].lo.y
                yt = (y0 - s.v0.y) / (s.v1.y - s.v0.y)
                tmppt = Ppoint(s.v0.x + yt * (s.v1.x - s.v0.x), y0)
                if less_than(tmppt, tr[t].lo):
                    i_d0 = True

            _update_trapezoid(s, seg, tr, t, tn)

            if (fp_equal(tr[t].lo.y, tr[tlast].lo.y)
                    and fp_equal(tr[t].lo.x, tr[tlast].lo.x) and tribot):
                # Lowermost trapezoid — endpoint already threaded.
                tr[tr[t].d0].u0 = t
                tr[tr[t].d0].u1 = INVALID_TRAP
                tr[tr[t].d1].u0 = tn
                tr[tr[t].d1].u1 = INVALID_TRAP

                tr[tn].d0 = tr[t].d1
                tr[t].d1 = INVALID_TRAP
                tr[tn].d1 = INVALID_TRAP

                tnext = tr[t].d1
            elif i_d0:
                # Intersecting d0.
                tr[tr[t].d0].u0 = t
                tr[tr[t].d0].u1 = tn
                tr[tr[t].d1].u0 = tn
                tr[tr[t].d1].u1 = INVALID_TRAP

                tr[t].d1 = INVALID_TRAP
                tnext = tr[t].d0
            else:
                # Intersecting d1.
                tr[tr[t].d0].u0 = t
                tr[tr[t].d0].u1 = INVALID_TRAP
                tr[tr[t].d1].u0 = t
                tr[tr[t].d1].u1 = tn

                tr[tn].d0 = tr[t].d1
                tr[tn].d1 = INVALID_TRAP
                tnext = tr[t].d1

            t = tnext

        tr[t_sav].rseg = segnum
        tr[tn_sav].lseg = segnum

    tfirstl = tfirst
    tlastl = tlast
    _merge_trapezoids(segnum, tfirstl, tlastl, S_LEFT, tr, qs)
    _merge_trapezoids(segnum, tfirstr, tlastr, S_RIGHT, tr, qs)

    seg[segnum].is_inserted = True


def _copy_trap(dst: Trap, src: Trap) -> None:
    """C's ``LIST_SET(tr, tl, LIST_GET(tr, tu))`` — struct copy."""
    dst.lseg = src.lseg
    dst.rseg = src.rseg
    dst.hi = Ppoint(src.hi.x, src.hi.y)
    dst.lo = Ppoint(src.lo.x, src.lo.y)
    dst.u0 = src.u0
    dst.u1 = src.u1
    dst.d0 = src.d0
    dst.d1 = src.d1
    dst.sink = src.sink
    dst.usave = src.usave
    dst.uside = src.uside
    dst.is_valid = src.is_valid


# ---------- find_new_roots ----------


def _find_new_roots(segnum: int, seg: list[TrapSegment],
                    tr: list[Trap], qs: list[QNode]) -> None:
    s = seg[segnum]
    if s.is_inserted:
        return
    s.root0 = _locate_endpoint(s.v0, s.v1, s.root0, seg, qs)
    s.root0 = tr[s.root0].sink
    s.root1 = _locate_endpoint(s.v1, s.v0, s.root1, seg, qs)
    s.root1 = tr[s.root1].sink


# ---------- Seidel's log* partition ----------


def _math_logstar_n(n: int) -> int:
    i = 0
    v = float(n)
    while v >= 1:
        i += 1
        v = math.log2(v)
    return i - 1


def _math_N(n: int, h: int) -> int:
    v = float(n)
    for _ in range(h):
        v = math.log2(v)
    return math.ceil(n / v)


# ---------- public entry point ----------


def construct_trapezoids(nseg: int, seg: list[TrapSegment],
                         permute: list[int]) -> list[Trap]:
    """Decompose the planar subdivision into trapezoids.

    Port of ``construct_trapezoids`` in ``trapezoid.c:862``.

    Parameters
    ----------
    nseg
        Number of segments (1-indexed; ``seg[0]`` is a placeholder).
    seg
        List of length ``nseg + 1``.  ``seg[1..nseg]`` are the input
        segments; ``seg[0]`` is unused and should be a default-
        constructed :class:`TrapSegment`.
    permute
        List of length ``nseg`` giving the insertion order as
        1-indexed segment numbers.  Typically ``[1, 2, ..., nseg]``
        for deterministic runs; the C API randomizes this for
        expected-case performance.

    Returns
    -------
    list[Trap]
        ``tr[0]`` is a sentinel (zero-filled); ``tr[1..]`` are
        trapezoids in allocation order.  Some may have
        ``is_valid=False`` (invalidated during merge) — callers
        should skip those.
    """
    qs: list[QNode] = []
    tr: list[Trap] = [Trap()]  # sentinel at index 0

    _emit_entry_trace(nseg)

    segi = 0
    root = _init_query_structure(permute[segi], seg, tr, qs)
    segi += 1

    for i in range(1, nseg + 1):
        seg[i].root0 = root
        seg[i].root1 = root

    logstar = _math_logstar_n(nseg)
    for h in range(1, logstar + 1):
        lo = _math_N(nseg, h - 1) + 1
        hi = _math_N(nseg, h)
        for _ in range(lo, hi + 1):
            _add_segment(permute[segi], seg, tr, qs)
            segi += 1
        for i in range(1, nseg + 1):
            _find_new_roots(i, seg, tr, qs)

    lo = _math_N(nseg, logstar) + 1
    for _ in range(lo, nseg + 1):
        _add_segment(permute[segi], seg, tr, qs)
        segi += 1

    _emit_exit_trace(tr)
    return tr


# ---------- trace emission ----------


def _emit_entry_trace(nseg: int) -> None:
    print(f"[TRACE ortho-trapezoid] construct nsegs={nseg}",
          file=sys.stderr)


def _emit_exit_trace(tr: list[Trap]) -> None:
    print(f"[TRACE ortho-trapezoid] construct ntraps={len(tr)}",
          file=sys.stderr)
    for i in range(1, len(tr)):
        t = tr[i]
        if not t.is_valid:
            continue
        hi_x = _fmt_coord(t.hi.x)
        hi_y = _fmt_coord(t.hi.y)
        lo_x = _fmt_coord(t.lo.x)
        lo_y = _fmt_coord(t.lo.y)
        print(
            f"[TRACE ortho-trapezoid] trap i={i} lseg={t.lseg} "
            f"rseg={t.rseg} hi={hi_x},{hi_y} lo={lo_x},{lo_y} "
            f"u0={t.u0} u1={t.u1} d0={t.d0} d1={t.d1}",
            file=sys.stderr,
        )


def _fmt_coord(v: float) -> str:
    if v == math.inf:
        return "INF"
    if v == -math.inf:
        return "-INF"
    return f"{v:.6f}"


# ---------- human-readable formatter (used by parity tests) ----------


def format_traps(tr: list[Trap]) -> str:
    """Format ``tr`` exactly the way the C harness does, for diff testing.

    Output begins with ``trapezoids ntraps=<n>`` then one ``trap ...``
    line per valid trapezoid.  Matches ``tools/trapezoid_harness/
    harness.c`` byte-for-byte modulo the fixed ``.6f`` coordinate format.
    """
    lines = [f"trapezoids ntraps={len(tr)}"]
    for i in range(1, len(tr)):
        t = tr[i]
        if not t.is_valid:
            continue
        hi_x = _fmt_coord(t.hi.x)
        hi_y = _fmt_coord(t.hi.y)
        lo_x = _fmt_coord(t.lo.x)
        lo_y = _fmt_coord(t.lo.y)
        lines.append(
            f"trap i={i} lseg={t.lseg} rseg={t.rseg} "
            f"hi={hi_x},{hi_y} lo={lo_x},{lo_y} "
            f"u0={t.u0} u1={t.u1} d0={t.d0} d1={t.d1}"
        )
    return "\n".join(lines) + "\n"


# ---------- fixture loader (used by parity tests) ----------


def load_fixture(path: str) -> tuple[int, list[TrapSegment], list[int]]:
    """Read a ``tools/trapezoid_harness/fixtures/*.in`` file.

    Returns ``(nseg, seg, permute)`` ready to hand to
    :func:`construct_trapezoids`.
    """
    with open(path, "r", encoding="utf-8") as f:
        tokens = f.read().split()
    it = iter(tokens)
    nseg = int(next(it))
    seg: list[TrapSegment] = [TrapSegment()]  # seg[0] placeholder
    for _ in range(nseg):
        v0x = float(next(it)); v0y = float(next(it))
        v1x = float(next(it)); v1y = float(next(it))
        nxt = int(next(it)); prv = int(next(it))
        seg.append(TrapSegment(
            v0=Ppoint(v0x, v0y),
            v1=Ppoint(v1x, v1y),
            next=nxt,
            prev=prv,
        ))
    permute = [int(next(it)) for _ in range(nseg)]
    return nseg, seg, permute
