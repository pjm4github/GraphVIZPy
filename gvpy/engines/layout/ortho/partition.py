"""Port of ``lib/ortho/partition.{h,c}``.

Decomposes the free space around a graph's nodes (represented as cell
bounding boxes) into axis-aligned rectangles.  The decomposition is
computed twice — once for horizontal cuts and once for vertical — and
the final rectangle set is the pairwise intersection of the two.

Semantics track the C verbatim except for one deliberate divergence:
C's ``partition()`` calls ``srand48(173)`` then generates a random
permutation for segment insertion order.  The Python port uses the
**identity permutation** by default because:

1. Seidel's algorithm is correct for any insertion order — only the
   expected-case running time depends on randomization.
2. The final rectangle set is a canonical decomposition of the input
   geometry, invariant under permutation.  Only internal trapezoid
   numbering differs.
3. The C harness (``filters/partition_harness/``) sorts its output
   rectangles lexicographically so parity tests compare by set
   membership rather than ordering.

Callers that need byte-identical trapezoidation can pass explicit
``hor_permute`` / ``ver_permute`` arguments.  The RNG path is not
reproduced.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.common.geom import Ppoint
from gvpy.engines.layout.ortho import trapezoid
from gvpy.engines.layout.ortho.trapezoid import (
    C_EPS,
    Trap,
    TrapSegment,
    construct_trapezoids,
    equal_to,
    fp_equal,
    greater_than,
    is_valid_trap,
)

# traverse-direction selectors (partition.c:35-36).
TR_FROM_UP = 1
TR_FROM_DN = 2

NPOINTS = 4  # rectangles only


@dataclass
class Boxf:
    """Axis-aligned box.  Port of ``boxf`` in ``common/geom.h``."""
    LL: Ppoint = field(default_factory=Ppoint)
    UR: Ppoint = field(default_factory=Ppoint)


@dataclass
class Cell:
    """Mirror of ``cell`` in ``ortho/maze.h``.

    :func:`partition` only consults ``bb``; the remaining fields
    (``flags``, ``nsides``, ``sides``, ``edges``) are populated by
    :mod:`maze` during ``mkMaze``.  They live here to avoid a circular
    import between ``partition`` and ``maze`` — both modules deal in
    the same cell type.
    """
    bb: Boxf = field(default_factory=Boxf)
    flags: int = 0
    nedges: int = 0
    edges: list = field(default_factory=list)
    nsides: int = 0
    sides: list = field(default_factory=list)


@dataclass
class _Monchain:
    """``monchain_t`` in ``partition.c:58`` — circular doubly-linked
    list of monotone-polygon vertices.
    """
    vnum: int = 0
    next: int = 0
    prev: int = 0
    marked: int = 0


@dataclass
class _VertexChain:
    """``vertexchain_t`` in ``partition.c:106``."""
    pt: Ppoint = field(default_factory=Ppoint)
    vnext: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    vpos: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    nextfree: int = 0


# ---------- segment generation ----------


def _perp(p: Ppoint) -> Ppoint:
    """90° CCW rotation — mirror of ``perp`` in ``common/geomprocs.h``.

    ``(x, y) -> (-y, x)``.  Used to "flip" input between the horizontal
    and vertical trapezoidation passes.
    """
    return Ppoint(-p.y, p.x)


def _convert(bb: Boxf, flip: bool, ccw: bool) -> list[Ppoint]:
    """``partition.c::convert`` — box → 4-point polygon."""
    pts = [Ppoint() for _ in range(4)]
    pts[0] = Ppoint(bb.LL.x, bb.LL.y)
    pts[2] = Ppoint(bb.UR.x, bb.UR.y)
    if ccw:
        pts[1] = Ppoint(bb.UR.x, bb.LL.y)
        pts[3] = Ppoint(bb.LL.x, bb.UR.y)
    else:
        pts[1] = Ppoint(bb.LL.x, bb.UR.y)
        pts[3] = Ppoint(bb.UR.x, bb.LL.y)
    if flip:
        for i in range(NPOINTS):
            pts[i] = _perp(pts[i])
    return pts


def _store(seg: list[TrapSegment], first: int, pts: list[Ppoint]) -> int:
    """``partition.c::store`` — write a 4-point polygon into seg[first..first+3].

    Returns the index after the last written slot (i.e. ``first + 4``).
    Sets up the circular ``prev``/``next`` linkage and shares endpoints
    between adjacent segments: ``seg[prev].v1 == seg[cur].v0``.
    """
    last = first + NPOINTS - 1
    j = 0
    for i in range(first, last + 1):
        if i == first:
            seg[i].next = first + 1
            seg[i].prev = last
        elif i == last:
            seg[i].next = first
            seg[i].prev = last - 1
        else:
            seg[i].next = i + 1
            seg[i].prev = i - 1
        seg[i].is_inserted = False
        # seg[prev].v1 = seg[cur].v0 = pts[j]
        seg[seg[i].prev].v1 = Ppoint(pts[j].x, pts[j].y)
        seg[i].v0 = Ppoint(pts[j].x, pts[j].y)
        j += 1
    return last + 1


def _gen_segments(cells: list[Cell], ncells: int, bb: Boxf,
                  seg: list[TrapSegment], flip: bool) -> None:
    """``partition.c::genSegments`` — fill ``seg`` with bb + cell polygons.

    Outer bb gets CCW orientation; each cell gets CW.  This is how the
    trapezoidation distinguishes "outside" vs "hole" when
    :func:`_inside_polygon` later checks segment direction.
    """
    i = 1
    pts = _convert(bb, flip, ccw=True)
    i = _store(seg, i, pts)
    for j in range(ncells):
        pts = _convert(cells[j].bb, flip, ccw=False)
        i = _store(seg, i, pts)


# ---------- inside-polygon test ----------


def _inside_polygon(t: Trap, seg: list[TrapSegment]) -> bool:
    """``partition.c::inside_polygon`` — is this trap inside the shape?

    Used once at the start of :func:`_monotonate_trapezoids` to find a
    triangular trapezoid to use as the traversal root.
    """
    rseg = t.rseg
    if not t.is_valid:
        return False
    if t.lseg <= 0 or t.rseg <= 0:
        return False
    # Triangle test: exactly one side missing both top and bottom neighbours.
    if ((not is_valid_trap(t.u0) and not is_valid_trap(t.u1))
            or (not is_valid_trap(t.d0) and not is_valid_trap(t.d1))):
        return greater_than(seg[rseg].v1, seg[rseg].v0)
    return False


# ---------- monotone-polygon bookkeeping ----------


def _get_angle(vp0: Ppoint, vpnext: Ppoint, vp1: Ppoint) -> float:
    """``partition.c::get_angle`` — signed angle between two edges.

    Returns values in [-2, 1]; the [-2, 0] range encodes "reflex"
    angles so the caller can compare anything against them with ``>``.

    Degenerate inputs (coincident vertices → zero-length edges) make
    the C implementation divide by zero silently (producing NaN/Inf
    that the caller's ``angle > temp`` comparison happens to reject).
    Mirror that skip-the-vertex behaviour explicitly by returning the
    :data:`-4.0` sentinel — less than any possible real angle, so
    :func:`_get_vertex_positions` won't pick this index.
    """
    v0 = Ppoint(vpnext.x - vp0.x, vpnext.y - vp0.y)
    v1 = Ppoint(vp1.x - vp0.x, vp1.y - vp0.y)
    cross_sine = v0.x * v1.y - v1.x * v0.y
    dot = v0.x * v1.x + v0.y * v1.y
    import math as _math
    len0 = _math.hypot(v0.x, v0.y)
    len1 = _math.hypot(v1.x, v1.y)
    if len0 == 0.0 or len1 == 0.0:
        return -4.0
    if cross_sine >= 0:
        return dot / len0 / len1
    return -1.0 * dot / len0 / len1 - 2


@dataclass
class _MonoState:
    """Encapsulates C's module-global state for monotonate_trapezoids.

    C uses static globals ``vert``, ``mon``, ``chain_idx``, ``mon_idx``
    — Python keeps them in a dataclass so multiple concurrent
    :func:`partition` calls would be safe (not relevant today but good
    hygiene).
    """
    vert: list[_VertexChain] = field(default_factory=list)
    mon: list[int] = field(default_factory=list)
    chain_idx: int = 0
    mon_idx: int = 0


def _monchain_get(chain: list[_Monchain], index: int) -> _Monchain:
    """``partition.c::monchains_get`` — zero-default for out-of-range reads."""
    if index < 0 or index >= len(chain):
        return _Monchain()
    return chain[index]


def _monchain_at(chain: list[_Monchain], index: int) -> _Monchain:
    """``partition.c::monchains_at`` — expand on demand, return slot."""
    assert index >= 0
    while index >= len(chain):
        chain.append(_Monchain())
    return chain[index]


def _get_vertex_positions(state: _MonoState, v0: int, v1: int) -> tuple[int, int]:
    """``partition.c::get_vertex_positions``.  Picks the chain to split on."""
    vp0 = state.vert[v0]
    vp1 = state.vert[v1]

    # Iterate every grown slot, not just 0..3 (see _make_new_monotone_poly
    # for why the lists may exceed 4 entries).
    angle = -4.0
    tp = 0
    for i in range(len(vp0.vnext)):
        if vp0.vnext[i] <= 0:
            continue
        temp = _get_angle(vp0.pt, state.vert[vp0.vnext[i]].pt, vp1.pt)
        if temp > angle:
            angle = temp
            tp = i

    angle = -4.0
    tq = 0
    for i in range(len(vp1.vnext)):
        if vp1.vnext[i] <= 0:
            continue
        temp = _get_angle(vp1.pt, state.vert[vp1.vnext[i]].pt, vp0.pt)
        if temp > angle:
            angle = temp
            tq = i

    return tp, tq


def _make_new_monotone_poly(state: _MonoState, chain: list[_Monchain],
                            mcur: int, v0: int, v1: int) -> int:
    """``partition.c::make_new_monotone_poly`` — split ``mcur`` on diagonal (v0,v1)."""
    state.mon_idx += 1
    mnew = state.mon_idx
    vp0 = state.vert[v0]
    vp1 = state.vert[v1]

    ip, iq = _get_vertex_positions(state, v0, v1)

    p = vp0.vpos[ip]
    q = vp1.vpos[iq]

    state.chain_idx += 1
    i = state.chain_idx
    state.chain_idx += 1
    j = state.chain_idx

    _monchain_at(chain, i).vnum = v0
    _monchain_at(chain, j).vnum = v1

    p_next = _monchain_get(chain, p).next
    q_prev = _monchain_get(chain, q).prev
    _monchain_at(chain, i).next = p_next
    _monchain_at(chain, p_next).prev = i
    _monchain_at(chain, i).prev = j
    _monchain_at(chain, j).next = i
    _monchain_at(chain, j).prev = q_prev
    _monchain_at(chain, q_prev).next = j

    _monchain_at(chain, p).next = q
    _monchain_at(chain, q).prev = p

    nf0 = vp0.nextfree
    nf1 = vp1.nextfree

    # C hard-codes vnext[4] / vpos[4] and silently buffer-overruns when
    # a vertex participates in more than four diagonal splits — happens
    # on larger graphs like 2620.dot.  Grow the Python lists on demand
    # rather than replicating the overflow, and let
    # :func:`_get_vertex_positions` iterate the actual length below.
    while len(vp0.vpos) <= nf0:
        vp0.vpos.append(0)
        vp0.vnext.append(0)
    while len(vp1.vpos) <= nf1:
        vp1.vpos.append(0)
        vp1.vnext.append(0)

    vp0.vnext[ip] = v1

    vp0.vpos[nf0] = i
    vp0.vnext[nf0] = _monchain_get(
        chain, _monchain_get(chain, i).next).vnum
    vp1.vpos[nf1] = j
    vp1.vnext[nf1] = v0

    vp0.nextfree += 1
    vp1.nextfree += 1

    # Grow mon[] on demand; C indexes into a fixed-size int*.
    while len(state.mon) <= max(mcur, mnew):
        state.mon.append(0)
    state.mon[mcur] = p
    state.mon[mnew] = i
    return mnew


# ---------- trapezoid traversal → horizontal/vertical rectangles ----------


def _traverse_polygon(state: _MonoState, chain: list[_Monchain],
                      visited: list[bool], decomp: list[Boxf],
                      seg: list[TrapSegment], tr: list[Trap],
                      mcur: int, trnum: int, from_: int,
                      flip: bool, direction: int) -> None:
    """``partition.c::traverse_polygon`` — recursively emit rectangles.

    Whenever a trapezoid has vertical left+right segments and non-zero
    height, emit it as a rectangle into ``decomp``.  The function also
    recursively splits monotone polygons at cusps so the caller ends
    up with axis-aligned tiles.
    """
    if not is_valid_trap(trnum):
        return
    if visited[trnum]:
        return

    t = tr[trnum]
    visited[trnum] = True

    # Vertical-left-and-right + nonzero-height → emit as a rect.
    if (t.hi.y > t.lo.y + C_EPS
            and fp_equal(seg[t.lseg].v0.x, seg[t.lseg].v1.x)
            and fp_equal(seg[t.rseg].v0.x, seg[t.rseg].v1.x)):
        if flip:
            new_box = Boxf(
                LL=Ppoint(t.lo.y, -seg[t.rseg].v0.x),
                UR=Ppoint(t.hi.y, -seg[t.lseg].v0.x),
            )
        else:
            new_box = Boxf(
                LL=Ppoint(seg[t.lseg].v0.x, t.lo.y),
                UR=Ppoint(seg[t.rseg].v0.x, t.hi.y),
            )
        decomp.append(new_box)

    # Cusp-case dispatch.  The C structure is reproduced branch-for-branch.
    if not is_valid_trap(t.u0) and not is_valid_trap(t.u1):
        if is_valid_trap(t.d0) and is_valid_trap(t.d1):
            # Downward-opening triangle.
            v0 = tr[t.d1].lseg
            v1 = t.lseg
            if from_ == t.d1:
                mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.d1, trnum, flip, TR_FROM_UP)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.d0, trnum, flip, TR_FROM_UP)
            else:
                mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.d0, trnum, flip, TR_FROM_UP)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.d1, trnum, flip, TR_FROM_UP)
        else:
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.u0, trnum, flip, TR_FROM_DN)
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.u1, trnum, flip, TR_FROM_DN)
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.d0, trnum, flip, TR_FROM_UP)
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.d1, trnum, flip, TR_FROM_UP)

    elif not is_valid_trap(t.d0) and not is_valid_trap(t.d1):
        if is_valid_trap(t.u0) and is_valid_trap(t.u1):
            # Upward-opening triangle.
            v0 = t.rseg
            v1 = tr[t.u0].rseg
            if from_ == t.u1:
                mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.u1, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.u0, trnum, flip, TR_FROM_DN)
            else:
                mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.u0, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.u1, trnum, flip, TR_FROM_DN)
        else:
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.u0, trnum, flip, TR_FROM_DN)
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.u1, trnum, flip, TR_FROM_DN)
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.d0, trnum, flip, TR_FROM_UP)
            _traverse_polygon(state, chain, visited, decomp, seg, tr,
                              mcur, t.d1, trnum, flip, TR_FROM_UP)

    elif is_valid_trap(t.u0) and is_valid_trap(t.u1):
        if is_valid_trap(t.d0) and is_valid_trap(t.d1):
            # Downward + upward cusps.
            v0 = tr[t.d1].lseg
            v1 = tr[t.u0].rseg
            if ((direction == TR_FROM_DN and t.d1 == from_)
                    or (direction == TR_FROM_UP and t.u1 == from_)):
                mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.u1, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.d1, trnum, flip, TR_FROM_UP)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.u0, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.d0, trnum, flip, TR_FROM_UP)
            else:
                mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.u0, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.d0, trnum, flip, TR_FROM_UP)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.u1, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mnew, t.d1, trnum, flip, TR_FROM_UP)
        else:
            # Only downward cusp.
            if equal_to(t.lo, seg[t.lseg].v1):
                v0 = tr[t.u0].rseg
                v1 = seg[t.lseg].next
                if direction == TR_FROM_UP and t.u0 == from_:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d1, trnum, flip, TR_FROM_UP)
                else:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u0, trnum, flip, TR_FROM_DN)
            else:
                v0 = t.rseg
                v1 = tr[t.u0].rseg
                if direction == TR_FROM_UP and t.u1 == from_:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u0, trnum, flip, TR_FROM_DN)
                else:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u1, trnum, flip, TR_FROM_DN)

    elif is_valid_trap(t.u0) or is_valid_trap(t.u1):  # no downward cusp
        if is_valid_trap(t.d0) and is_valid_trap(t.d1):
            # Only upward cusp.
            if equal_to(t.hi, seg[t.lseg].v0):
                v0 = tr[t.d1].lseg
                v1 = t.lseg
                if not (direction == TR_FROM_DN and t.d0 == from_):
                    mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d0, trnum, flip, TR_FROM_UP)
                else:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d1, trnum, flip, TR_FROM_UP)
            else:
                v0 = tr[t.d1].lseg
                v1 = seg[t.rseg].next
                if direction == TR_FROM_DN and t.d1 == from_:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d0, trnum, flip, TR_FROM_UP)
                else:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d1, trnum, flip, TR_FROM_UP)
        else:
            # No cusp.
            if (equal_to(t.hi, seg[t.lseg].v0)
                    and equal_to(t.lo, seg[t.rseg].v0)):
                v0 = t.rseg
                v1 = t.lseg
                if direction == TR_FROM_UP:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d0, trnum, flip, TR_FROM_UP)
                else:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u1, trnum, flip, TR_FROM_DN)
            elif (equal_to(t.hi, seg[t.rseg].v1)
                  and equal_to(t.lo, seg[t.lseg].v1)):
                v0 = seg[t.rseg].next
                v1 = seg[t.lseg].next
                if direction == TR_FROM_UP:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v1, v0)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.u1, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.d0, trnum, flip, TR_FROM_UP)
                else:
                    mnew = _make_new_monotone_poly(state, chain, mcur, v0, v1)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d1, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mcur, t.d0, trnum, flip, TR_FROM_UP)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u0, trnum, flip, TR_FROM_DN)
                    _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                      mnew, t.u1, trnum, flip, TR_FROM_DN)
            else:
                # No split possible — traverse all neighbours.
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.u0, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.d0, trnum, flip, TR_FROM_UP)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.u1, trnum, flip, TR_FROM_DN)
                _traverse_polygon(state, chain, visited, decomp, seg, tr,
                                  mcur, t.d1, trnum, flip, TR_FROM_UP)


def _monotonate_trapezoids(nsegs: int, seg: list[TrapSegment],
                           tr: list[Trap], flip: bool,
                           decomp: list[Boxf]) -> None:
    """``partition.c::monotonate_trapezoids`` — drive the traversal."""
    visited = [False] * len(tr)
    chain: list[_Monchain] = []

    state = _MonoState(
        vert=[_VertexChain() for _ in range(nsegs + 1)],
        mon=[0] * nsegs,
    )

    # Find a triangular trap that lies inside the polygon; use it as root.
    tr_start = 0
    for j in range(len(tr)):
        if _inside_polygon(tr[j], seg):
            tr_start = j
            break

    # Initialize mon data-structure.
    for i in range(1, nsegs + 1):
        _monchain_at(chain, i).prev = seg[i].prev
        _monchain_at(chain, i).next = seg[i].next
        _monchain_at(chain, i).vnum = i
        state.vert[i].pt = Ppoint(seg[i].v0.x, seg[i].v0.y)
        state.vert[i].vnext[0] = seg[i].next
        state.vert[i].vpos[0] = i
        state.vert[i].nextfree = 1

    state.chain_idx = nsegs
    state.mon_idx = 0
    state.mon[0] = 1

    # Traverse from the root.
    start_t = tr[tr_start]
    if is_valid_trap(start_t.u0):
        _traverse_polygon(state, chain, visited, decomp, seg, tr,
                          0, tr_start, start_t.u0, flip, TR_FROM_UP)
    elif is_valid_trap(start_t.d0):
        _traverse_polygon(state, chain, visited, decomp, seg, tr,
                          0, tr_start, start_t.d0, flip, TR_FROM_DN)


# ---------- rectangle intersection ----------


def _rect_intersect(r0: Boxf, r1: Boxf) -> Optional[Boxf]:
    """``partition.c::rectIntersect`` — returns intersection or None."""
    ll_x = max(r0.LL.x, r1.LL.x)
    ur_x = min(r0.UR.x, r1.UR.x)
    ll_y = max(r0.LL.y, r1.LL.y)
    ur_y = min(r0.UR.y, r1.UR.y)
    if ll_x >= ur_x or ll_y >= ur_y:
        return None
    return Boxf(LL=Ppoint(ll_x, ll_y), UR=Ppoint(ur_x, ur_y))


# ---------- public entry point ----------


def partition(cells: list[Cell], ncells: int, bb: Boxf,
              hor_permute: Optional[list[int]] = None,
              ver_permute: Optional[list[int]] = None) -> list[Boxf]:
    """Decompose ``bb`` around ``cells`` into axis-aligned rectangles.

    Port of ``partition.c::partition``.

    Parameters
    ----------
    cells, ncells
        Obstacle cells.  Only their ``bb`` is consulted.
    bb
        Outer bounding box to decompose.
    hor_permute, ver_permute
        Optional 1-indexed segment insertion orders for the horizontal
        and vertical trapezoidation passes respectively.  Default
        (``None``) uses identity ``[1, 2, ..., nsegs]`` — deterministic
        and correct, though different from C's RNG-based ordering.
        See the module docstring for why this is safe.

    Returns
    -------
    list[Boxf]
        Axis-aligned tiles covering ``bb`` minus cell interiors.
        Order is not guaranteed; callers that need a canonical form
        should sort by ``(LL.x, LL.y, UR.x, UR.y)``.
    """
    nsegs = 4 * (ncells + 1)
    _emit_entry_trace(ncells, bb)

    # Segment array is 1-indexed: seg[0] placeholder, seg[1..nsegs] populated.
    seg_h = _new_seg_array(nsegs)
    _gen_segments(cells, ncells, bb, seg_h, flip=False)

    if hor_permute is None:
        hor_permute = list(range(1, nsegs + 1))
    hor_traps = construct_trapezoids(nsegs, seg_h, hor_permute)

    hor_decomp: list[Boxf] = []
    _monotonate_trapezoids(nsegs, seg_h, hor_traps, flip=False,
                           decomp=hor_decomp)

    seg_v = _new_seg_array(nsegs)
    _gen_segments(cells, ncells, bb, seg_v, flip=True)

    if ver_permute is None:
        ver_permute = list(range(1, nsegs + 1))
    ver_traps = construct_trapezoids(nsegs, seg_v, ver_permute)

    vert_decomp: list[Boxf] = []
    _monotonate_trapezoids(nsegs, seg_v, ver_traps, flip=True,
                           decomp=vert_decomp)

    # Pairwise intersection of the two decompositions.
    rects: list[Boxf] = []
    for v in vert_decomp:
        for h in hor_decomp:
            inter = _rect_intersect(v, h)
            if inter is not None:
                rects.append(inter)

    _emit_exit_trace(rects)
    return rects


def _new_seg_array(nsegs: int) -> list[TrapSegment]:
    """Allocate ``seg[0..nsegs]`` — index 0 placeholder, rest default."""
    return [TrapSegment() for _ in range(nsegs + 1)]


# ---------- trace emission ----------


# Gated diagnostic — was unconditionally printed before
# 2026-04-24.  Channel: ``ortho_partition``.  Enables byte-match
# diff against ``filters/partition_harness/harness.c``.
def _emit_entry_trace(ncells: int, bb: Boxf) -> None:
    from gvpy.engines.layout.dot.trace import trace_on, trace
    if trace_on("ortho_partition"):
        trace("ortho_partition",
              f"ncells={ncells} "
              f"bb={bb.LL.x:.6f},{bb.LL.y:.6f},{bb.UR.x:.6f},{bb.UR.y:.6f}")


def _emit_exit_trace(rects: list[Boxf]) -> None:
    from gvpy.engines.layout.dot.trace import trace_on, trace
    if not trace_on("ortho_partition"):
        return
    trace("ortho_partition", f"nrects={len(rects)}")
    # Sort for deterministic emission order.
    ordered = sorted(
        rects,
        key=lambda b: (b.LL.x, b.LL.y, b.UR.x, b.UR.y),
    )
    for i, b in enumerate(ordered):
        trace("ortho_partition",
              f"rect i={i} "
              f"bb={b.LL.x:.6f},{b.LL.y:.6f},{b.UR.x:.6f},{b.UR.y:.6f}")


# ---------- parity-test helpers ----------


def format_partition(ncells: int, rects: list[Boxf]) -> str:
    """Format output matching ``filters/partition_harness/harness.c``.

    Rectangles are sorted lexicographically so Python vs C output
    compares as sets modulo order.
    """
    ordered = sorted(
        rects,
        key=lambda b: (b.LL.x, b.LL.y, b.UR.x, b.UR.y),
    )
    lines = [f"partition_result ncells={ncells} nrects={len(rects)}"]
    for b in ordered:
        lines.append(
            f"rect LL={b.LL.x:.6f},{b.LL.y:.6f} "
            f"UR={b.UR.x:.6f},{b.UR.y:.6f}"
        )
    return "\n".join(lines) + "\n"


def load_fixture(path: str) -> tuple[list[Cell], int, Boxf]:
    """Read a ``filters/partition_harness/fixtures/*.in`` file."""
    with open(path, "r", encoding="utf-8") as f:
        tokens = f.read().split()
    it = iter(tokens)
    ncells = int(next(it))
    bb = Boxf(
        LL=Ppoint(float(next(it)), float(next(it))),
        UR=Ppoint(float(next(it)), float(next(it))),
    )
    cells: list[Cell] = []
    for _ in range(ncells):
        c = Cell(bb=Boxf(
            LL=Ppoint(float(next(it)), float(next(it))),
            UR=Ppoint(float(next(it)), float(next(it))),
        ))
        cells.append(c)
    return cells, ncells, bb
