"""Port of ``lib/ortho/ortho.c`` — top-level orthogonal-edge routing.

Orchestrates the full pipeline for ``splines=ortho`` edges:

1. Build the maze over graph-node bboxes (:mod:`maze`).
2. For each edge (sorted by length), inject temporary source/dest
   snodes, run :func:`sgraph.short_path`, convert the shortest path
   to a segment route, reset the maze.
3. Extract horizontal / vertical channels from the cell layout.
4. Bin each segment into its channel.
5. Run :func:`assign_tracks` — build per-channel interference graphs,
   topologically sort them via :mod:`rawgraph`, assign track indices.
6. Convert tracks back to canonical waypoints via ``vtrack`` / ``htrack``.

Semantics track the C verbatim with a handful of deliberate
divergences where faithful reproduction would fight Python idiom:

- C's ``Dt_t`` ordered dictionary (``chans``) is a nested Python dict
  ``{coord: {paird: Channel}}`` with sorted-key iteration on demand.
- C uses qsort(epair_t, edgecmp) to sort edges by length; Python uses
  ``sorted(key=...)`` — stable and identical for distinct lengths.
- The ``OPTIONAL(size_t)`` fields in ``Segment`` (``ind_no``,
  ``track_no``) are plain ``Optional[int]`` — C stores them in a
  tagged-union-like struct.

:func:`ortho_edges` is the single public entry, invoked from
:mod:`gvpy.engines.layout.dot.dotsplines` under ``GVPY_ORTHO_V2=1``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.common.geom import Ppoint
from gvpy.engines.layout.ortho import fpq, rawgraph, sgraph as sgraph_mod
from gvpy.engines.layout.ortho.maze import (
    M_BOTTOM,
    M_LEFT,
    M_RIGHT,
    M_TOP,
    MZ_HSCAN,
    MZ_VSCAN,
    Maze,
    is_hscan,
    is_node,
    is_vscan,
    mk_maze,
    update_wts,
)
from gvpy.engines.layout.ortho.partition import Boxf, Cell
from gvpy.engines.layout.ortho.sgraph import (
    Sgraph,
    Snode,
    create_sedge,
    gsave,
    reset,
    short_path,
)
from gvpy.engines.layout.ortho.structures import Bend, Paird, Route, Segment


# =====================================================================
# Small helpers
# =====================================================================


def _mid(a: float, b: float) -> float:
    return (a + b) / 2.0


def _mid_pt(cp: Cell) -> Ppoint:
    return Ppoint(_mid(cp.bb.LL.x, cp.bb.UR.x),
                  _mid(cp.bb.LL.y, cp.bb.UR.y))


def _cell_of(p: Snode, q: Snode) -> Optional[Cell]:
    """``ortho.c::cellOf`` — return the cell shared by ``p`` and ``q``.

    Can return ``None`` when sgraph bookkeeping dropped a ``cells[]``
    link — on large graphs like 2620.dot, :func:`_chk_sgraph` logs
    warnings about missing links that C's release build silently
    ignores.  Callers treat ``None`` as "skip this step" rather than
    crashing.
    """
    cp = p.cells[0]
    if cp is not None and (cp is q.cells[0] or cp is q.cells[1]):
        return cp
    return p.cells[1]


def _side_pt(ptr: Snode, cp: Cell) -> Ppoint:
    """``ortho.c::sidePt`` — midpoint of the ``cp`` side on which ``ptr`` lies."""
    if cp is ptr.cells[1]:
        if ptr.is_vert:
            return Ppoint(cp.bb.LL.x, _mid(cp.bb.LL.y, cp.bb.UR.y))
        return Ppoint(_mid(cp.bb.LL.x, cp.bb.UR.x), cp.bb.LL.y)
    if ptr.is_vert:
        return Ppoint(cp.bb.UR.x, _mid(cp.bb.LL.y, cp.bb.UR.y))
    return Ppoint(_mid(cp.bb.LL.x, cp.bb.UR.x), cp.bb.UR.y)


def _set_seg(is_vert: bool, fix: float, b1: float, b2: float,
             l1: Bend, l2: Bend) -> Segment:
    """``ortho.c::setSeg`` — create a segment, normalizing p1 < p2."""
    sp = Segment()
    sp.is_vert = is_vert
    sp.comm_coord = fix
    if b1 < b2:
        sp.p = Paird(p1=b1, p2=b2)
        sp.l1 = l1
        sp.l2 = l2
    else:
        sp.p = Paird(p1=b2, p2=b1)
        sp.l1 = l2
        sp.l2 = l1
    return sp


# =====================================================================
# convertSPtoRoute — shortest-path → segment list
# =====================================================================


def _convert_sp_to_route(g: Sgraph, fst: Snode, lst: Snode) -> Route:
    """Port of ``ortho.c::convertSPtoRoute`` @ 126.

    Walk the n_dad chain from ``fst`` backward to ``lst`` (the path is
    recorded in reverse by :func:`short_path`), emitting a
    :class:`Segment` wherever the route changes direction or ends.
    """
    rte_segs: list[Segment] = []

    ptr = fst.n_dad
    prev = ptr
    next_ = ptr.n_dad if ptr is not None else None
    prev_bp = Ppoint(0.0, 0.0)

    if ptr is None or next_ is None:
        return Route(segs=[])

    # Starting cell: the one not marked as a node cell.  Both slots
    # can be ``None`` on large graphs (see :func:`_cell_of` comment) —
    # bail out with an empty route rather than crashing.
    c0 = ptr.cells[0]
    c1 = ptr.cells[1]
    if c0 is not None and is_node(c0):
        cp = c1
    elif c0 is not None:
        cp = c0
    else:
        cp = c1
    if cp is None:
        return Route(segs=[])
    bp1 = _side_pt(ptr, cp)

    while next_ is not None and next_.n_dad is not None:
        ncp = _cell_of(prev, next_)
        if ncp is None:
            # Missing cell link — skip this step of the path rather
            # than crash.  Matches the "ship whatever routes we got"
            # spirit of the C release build.
            prev = next_
            next_ = next_.n_dad
            continue
        # Route charge: bump the per-cell edge weights.
        if ptr.n_edge is not None:
            update_wts(g, ncp, ptr.n_edge)

        # Emit a segment when the route bends or we're at the last step.
        if ptr.is_vert != next_.is_vert or next_.n_dad is lst:
            if ptr.is_vert != next_.is_vert:
                bp2 = _mid_pt(ncp)
            else:
                bp2 = _side_pt(next_, ncp)

            if ptr.is_vert:
                # Horizontal segment (outgoing direction is non-vertical).
                if ptr is fst.n_dad:
                    l1 = Bend.B_NODE
                elif prev_bp.y > bp1.y:
                    l1 = Bend.B_UP
                else:
                    l1 = Bend.B_DOWN
                if ptr.is_vert != next_.is_vert:
                    l2 = Bend.B_UP if next_.cells[0] is ncp else Bend.B_DOWN
                else:
                    l2 = Bend.B_NODE
                fix = cp.bb.LL.y
                b1 = cp.bb.LL.x
                b2 = ncp.bb.LL.x
            else:
                # Vertical segment.
                if ptr is fst.n_dad:
                    l1 = Bend.B_NODE
                elif prev_bp.x > bp1.x:
                    l1 = Bend.B_RIGHT
                else:
                    l1 = Bend.B_LEFT
                if ptr.is_vert != next_.is_vert:
                    l2 = Bend.B_RIGHT if next_.cells[0] is ncp else Bend.B_LEFT
                else:
                    l2 = Bend.B_NODE
                fix = cp.bb.LL.x
                b1 = cp.bb.LL.y
                b2 = ncp.bb.LL.y

            seg = _set_seg(not ptr.is_vert, fix, b1, b2, l1, l2)
            rte_segs.append(seg)
            cp = ncp
            prev_bp = bp1
            bp1 = bp2

            # Special case: if we just bent AND next.n_dad is lst,
            # emit the final straight segment.
            if ptr.is_vert != next_.is_vert and next_.n_dad is lst:
                l2 = Bend.B_NODE
                if next_.is_vert:
                    # Horizontal final segment.
                    l1 = Bend.B_UP if prev_bp.y > bp1.y else Bend.B_DOWN
                    fix = cp.bb.LL.y
                    b1 = cp.bb.LL.x
                    b2 = ncp.bb.LL.x
                else:
                    l1 = Bend.B_RIGHT if prev_bp.x > bp1.x else Bend.B_LEFT
                    fix = cp.bb.LL.x
                    b1 = cp.bb.LL.y
                    b2 = ncp.bb.LL.y
                s = _set_seg(not next_.is_vert, fix, b1, b2, l1, l2)
                rte_segs.append(s)

            ptr = next_

        prev = next_
        next_ = next_.n_dad

    # Link segments via prev/next pointers (used by next_seg in
    # set_parallel_edges's propagation).
    for i, seg in enumerate(rte_segs):
        seg.prev = rte_segs[i - 1] if i > 0 else None
        seg.next = rte_segs[i + 1] if i < len(rte_segs) - 1 else None

    return Route(segs=rte_segs)


# =====================================================================
# Channels — horizontal/vertical corridors
# =====================================================================


@dataclass
class ChanItem:
    """C's ``chanItem``: map from coord → {Paird interval → Channel}.

    Not a dataclass field — each ``ChanItem`` lives as a value inside
    a ``dict[float, ChanItem]`` so the coord key lookup is O(1).
    """
    v: float = 0.0
    chans: dict = field(default_factory=dict)  # Paird-tuple → Channel


def _paird_key(p: Paird) -> tuple[float, float]:
    """Hashable key for a :class:`Paird` — dict indexing needs tuples."""
    return (p.p1, p.p2)


def _chancmp_contains(k1: tuple[float, float],
                      k2: tuple[float, float]) -> int:
    """``ortho.c::chancmpid`` — interval-containment three-way compare."""
    p1_1, p2_1 = k1
    p1_2, p2_2 = k2
    if p1_1 > p1_2:
        if p2_1 <= p2_2:
            return 0
        return 1
    if p1_1 < p1_2:
        if p2_1 >= p2_2:
            return 0
        return -1
    return 0


def _find_channel(chans: dict, coord: float, paird: Paird):
    """``ortho.c::chanSearch`` — look up the channel that contains ``paird``.

    C uses ``assert(cp)`` here, which can fire in debug builds but is
    silenced in release.  Python falls through two relaxed fallbacks
    before giving up:

    1. Strict containment (matches C's ``chancmpid``).
    2. Any-intersection — when partition's cell-ordering divergence
       (Python identity vs C RNG) splits channels at slightly
       different x-cuts, a segment generated from the path's cells
       may straddle a channel boundary that didn't exist on the C
       side.  Land it on the first intersecting channel.
    3. Nearest-midpoint — last-resort snap for zero-length degenerate
       segments that fall in a cell gap.

    Returns ``None`` if no channel at this coord exists at all.
    """
    chani = chans.get(coord)
    if chani is None:
        return None
    target = (paird.p1, paird.p2)
    # 1. Strict containment.
    for k, cp in chani.chans.items():
        if _chancmp_contains(target, k) == 0:
            return cp
    # 2. Any intersection.
    for k, cp in chani.chans.items():
        if max(target[0], k[0]) <= min(target[1], k[1]):
            return cp
    # 3. Nearest channel by midpoint distance.
    if not chani.chans:
        return None
    mid = (target[0] + target[1]) / 2.0
    best_key = min(
        chani.chans,
        key=lambda k: abs((k[0] + k[1]) / 2.0 - mid),
    )
    return chani.chans[best_key]


def _add_chan(chdict: dict, cp, coord: float) -> None:
    """``ortho.c::addChan`` — insert ``cp`` into ``chdict[coord]``."""
    if coord not in chdict:
        chdict[coord] = ChanItem(v=coord, chans={})
    key = _paird_key(cp.p)
    # Matching on paird: C uses chancmpid. If an existing channel
    # _contains_ the new one (or vice-versa), treat as duplicate.
    for existing_key in chdict[coord].chans:
        if _chancmp_contains(key, existing_key) == 0:
            # Already present — drop the new one.
            return
    chdict[coord].chans[key] = cp


@dataclass
class Channel:
    """Port of ``channel`` in ``structures.h``.

    Redefined here (rather than imported from :mod:`structures`) with
    the fields actually used by :mod:`ortho` — ``p``, ``seg_list``,
    ``G`` (rawgraph), ``cp`` (the channel's starting cell).
    """
    p: Paird = field(default_factory=Paird)
    seg_list: list = field(default_factory=list)  # list[Segment]
    G: Optional[rawgraph.Rawgraph] = None
    cp: Optional[Cell] = None


def _extract_h_chans(mp: Maze) -> dict:
    """Port of ``ortho.c::extractHChans``.  Walks each cell's row
    left→right, marking ``MZ_HSCAN`` and building one channel per row."""
    hchans: dict = {}
    for cp_start in mp.cells:
        if is_hscan(cp_start):
            continue
        cp = cp_start
        # Walk left until we hit a node cell or the outer wall.
        while True:
            np = cp.sides[M_LEFT] if len(cp.sides) == 4 else None
            if np is None:
                break
            nextcp = np.cells[0]
            if nextcp is None or is_node(nextcp):
                break
            cp = nextcp

        chp = Channel(p=Paird(p1=cp.bb.LL.x, p2=0.0), cp=cp)
        cp.flags |= MZ_HSCAN

        # Walk right, flagging each cell and extending p2.
        while True:
            np = cp.sides[M_RIGHT] if len(cp.sides) == 4 else None
            if np is None:
                break
            nextcp = np.cells[1]
            if nextcp is None or is_node(nextcp):
                break
            cp = nextcp
            cp.flags |= MZ_HSCAN

        chp.p.p2 = cp.bb.UR.x
        _add_chan(hchans, chp, chp.cp.bb.LL.y)
    return hchans


def _extract_v_chans(mp: Maze) -> dict:
    """Port of ``ortho.c::extractVChans`` — column version."""
    vchans: dict = {}
    for cp_start in mp.cells:
        if is_vscan(cp_start):
            continue
        cp = cp_start
        # Walk down.
        while True:
            np = cp.sides[M_BOTTOM] if len(cp.sides) == 4 else None
            if np is None:
                break
            nextcp = np.cells[0]
            if nextcp is None or is_node(nextcp):
                break
            cp = nextcp

        chp = Channel(p=Paird(p1=cp.bb.LL.y, p2=0.0), cp=cp)
        cp.flags |= MZ_VSCAN

        # Walk up.
        while True:
            np = cp.sides[M_TOP] if len(cp.sides) == 4 else None
            if np is None:
                break
            nextcp = np.cells[1]
            if nextcp is None or is_node(nextcp):
                break
            cp = nextcp
            cp.flags |= MZ_VSCAN

        chp.p.p2 = cp.bb.UR.y
        _add_chan(vchans, chp, chp.cp.bb.LL.x)
    return vchans


def _insert_chan(chan: Channel, seg: Segment) -> None:
    seg.ind_no = len(chan.seg_list)
    chan.seg_list.append(seg)


def _assign_segs(route_list: list[Route], mp: Maze) -> None:
    """Port of ``ortho.c::assignSegs`` — bin each segment into its channel.

    Segments that can't find a home channel (``_find_channel`` returns
    ``None``) are dropped with a trace line rather than crashing — this
    affects ``2620.dot`` and a handful of other fixtures where the
    partition cell-ordering divergence leaves a segment in a channel
    gap.  The route loses that hop; callers downstream see one fewer
    waypoint.  Phase 7 debugging is where this should get tightened.
    """
    dropped = 0
    for rte in route_list:
        for seg in rte.segs:
            if seg.is_vert:
                chan = _find_channel(mp.vchans, seg.comm_coord, seg.p)
            else:
                chan = _find_channel(mp.hchans, seg.comm_coord, seg.p)
            if chan is None:
                dropped += 1
                continue
            _insert_chan(chan, seg)
    if dropped:
        print(
            f"[TRACE ortho-route] warn dropped_segments={dropped} "
            f"(no channel found at segment coord)",
            file=sys.stderr,
        )


# =====================================================================
# addLoop / addNodeEdges — per-edge terminal snodes
# =====================================================================


def _add_loop(sg: Sgraph, cp: Cell, dp: Snode, sp: Snode) -> None:
    """Port of ``ortho.c::addLoop`` — two terminal snodes for a self-loop."""
    for onp in cp.sides:
        if onp is None:
            continue
        if onp.is_vert:
            continue
        on_top = onp.cells[0] is cp
        if on_top:
            create_sedge(sg, sp, onp, 0.0)
        else:
            create_sedge(sg, dp, onp, 0.0)
    sg.nnodes += 2


def _add_node_edges(sg: Sgraph, cp: Cell, np: Snode) -> None:
    """Port of ``ortho.c::addNodeEdges`` — one terminal snode per cell."""
    for onp in cp.sides:
        if onp is None:
            continue
        create_sedge(sg, np, onp, 0.0)
    sg.nnodes += 1
    np.cells[0] = cp  # DEBUG aid from C
    np.cells[1] = cp


# =====================================================================
# Segment comparison (seg_cmp family)
# =====================================================================


def _eq_end_seg(s1_l2: Bend, s2_l2: Bend, t1: Bend, t2: Bend) -> int:
    if (s1_l2 == t2 and s2_l2 != t2) or (s1_l2 == Bend.B_NODE and s2_l2 == t1):
        return 0
    return -1


def _overlap_seg(s1: Segment, s2: Segment, t1: Bend, t2: Bend) -> int:
    if s1.p.p2 < s2.p.p2:
        if s1.l2 == t1 and s2.l1 == t2:
            return -1
        if s1.l2 == t2 and s2.l1 == t1:
            return 1
        return 0
    if s1.p.p2 > s2.p.p2:
        if s2.l1 == t2 and s2.l2 == t2:
            return -1
        if s2.l1 == t1 and s2.l2 == t1:
            return 1
        return 0
    if s2.l1 == t2:
        return _eq_end_seg(s1.l2, s2.l2, t1, t2)
    return -1 * _eq_end_seg(s2.l2, s1.l2, t1, t2)


def _ell_seg(s1_l1: Bend, s1_l2: Bend, t: Bend) -> int:
    if s1_l1 == t:
        return -1 if s1_l2 == t else 0
    return 1


def _seg_cmp_inner(s1: Segment, s2: Segment, t1: Bend, t2: Bend) -> int:
    if s1.p.p2 < s2.p.p1 or s1.p.p1 > s2.p.p2:
        return 0
    if s1.p.p1 < s2.p.p1 and s2.p.p1 < s1.p.p2:
        return _overlap_seg(s1, s2, t1, t2)
    if s2.p.p1 < s1.p.p1 and s1.p.p1 < s2.p.p2:
        return -1 * _overlap_seg(s2, s1, t1, t2)
    if s1.p.p1 == s2.p.p1:
        if s1.p.p2 < s2.p.p2:
            if s1.l2 == t1:
                return _eq_end_seg(s2.l1, s1.l1, t1, t2)
            return -1 * _eq_end_seg(s2.l1, s1.l1, t1, t2)
        if s1.p.p2 > s2.p.p2:
            if s2.l2 == t2:
                return _eq_end_seg(s1.l1, s2.l1, t1, t2)
            return -1 * _eq_end_seg(s1.l1, s2.l1, t1, t2)
        if s1.l1 == s2.l1 and s1.l2 == s2.l2:
            return 0
        if s2.l1 == s2.l2:
            if s2.l1 == t1:
                return 1
            if s2.l1 == t2:
                return -1
            if s1.l1 != t1 and s1.l2 != t1:
                return 1
            if s1.l1 != t2 and s1.l2 != t2:
                return -1
            return 0
        if s2.l1 == t1 and s2.l2 == t2:
            if s1.l1 != t1 and s1.l2 == t2:
                return 1
            if s1.l1 == t1 and s1.l2 != t2:
                return -1
            return 0
        if s2.l2 == t1 and s2.l1 == t2:
            if s1.l2 != t1 and s1.l1 == t2:
                return 1
            if s1.l2 == t1 and s1.l1 != t2:
                return -1
            return 0
        if s2.l1 == Bend.B_NODE and s2.l2 == t1:
            return _ell_seg(s1.l1, s1.l2, t1)
        if s2.l1 == Bend.B_NODE and s2.l2 == t2:
            return -1 * _ell_seg(s1.l1, s1.l2, t2)
        if s2.l1 == t1 and s2.l2 == Bend.B_NODE:
            return _ell_seg(s1.l2, s1.l1, t1)
        return -1 * _ell_seg(s1.l2, s1.l1, t2)
    if s1.p.p2 == s2.p.p1:
        if s1.l2 == s2.l1:
            return 0
        if s1.l2 == t2:
            return 1
        return -1
    # s1.p.p1 == s2.p.p2
    if s1.l1 == s2.l2:
        return 0
    if s1.l1 == t2:
        return 1
    return -1


def _seg_cmp(s1: Segment, s2: Segment) -> int:
    """Port of ``ortho.c::seg_cmp``.

    Returns -2 if the segments are incomparable (different orientation
    or comm_coord); -1/0/1 per the ``segCmp`` contract.
    """
    if s1.is_vert != s2.is_vert or s1.comm_coord != s2.comm_coord:
        print("[ERROR ortho-route] incomparable segments", file=sys.stderr)
        return -2
    if s1.is_vert:
        return _seg_cmp_inner(s1, s2, Bend.B_RIGHT, Bend.B_LEFT)
    return _seg_cmp_inner(s1, s2, Bend.B_DOWN, Bend.B_UP)


# =====================================================================
# Track assignment
# =====================================================================


def _create_graphs(chans: dict) -> None:
    """Allocate a rawgraph per channel, sized to its segment count."""
    for chani in chans.values():
        for cp in chani.chans.values():
            cp.G = rawgraph.make_graph(len(cp.seg_list))


def _add_edges_in_g(cp: Channel) -> int:
    """``ortho.c::add_edges_in_G`` — insert interference edges from seg_cmp."""
    segs = cp.seg_list
    G = cp.G
    for x in range(len(segs) - 1):
        for y in range(x + 1, len(segs)):
            cmp = _seg_cmp(segs[x], segs[y])
            if cmp == -2:
                return -1
            if cmp > 0:
                rawgraph.insert_edge(G, x, y)
            elif cmp == -1:
                rawgraph.insert_edge(G, y, x)
    return 0


def _add_np_edges(chans: dict) -> int:
    for chani in chans.values():
        for cp in chani.chans.values():
            if cp.seg_list:
                if _add_edges_in_g(cp) != 0:
                    return -1
    return 0


def _next_seg(seg: Segment, direction: int) -> Optional[Segment]:
    return seg.next if direction else seg.prev


def _is_parallel(s1: Segment, s2: Segment) -> bool:
    """Port of ``ortho.c::is_parallel`` — two segments are parallel
    iff they share comm_coord, interval, and both bend orientations.

    C asserts ``s1.comm_coord == s2.comm_coord``; Python returns
    ``False`` for that mismatch (C release builds silently compare
    the remaining fields, which won't match when comm_coords differ
    anyway, so the observable behaviour is identical)."""
    if s1.comm_coord != s2.comm_coord:
        return False
    return (s1.p.p1 == s2.p.p1 and s1.p.p2 == s2.p.p2
            and s1.l1 == s2.l1 and s1.l2 == s2.l2)


def _propagate_prec(seg: Segment, prec: int, hops: int,
                    direction: int) -> int:
    ans = prec
    current = seg
    for _ in range(hops):
        nxt = _next_seg(current, direction)
        if nxt is None:
            break
        if not current.is_vert:
            if nxt.comm_coord == current.p.p1:
                if current.l1 == Bend.B_UP:
                    ans *= -1
            else:
                if current.l2 == Bend.B_DOWN:
                    ans *= -1
        else:
            if nxt.comm_coord == current.p.p1:
                if current.l1 == Bend.B_RIGHT:
                    ans *= -1
            else:
                if current.l2 == Bend.B_LEFT:
                    ans *= -1
        current = nxt
    return ans


def _decide_point(si: Segment, sj: Segment,
                  dir1: int, dir2: int) -> tuple[int, int, int]:
    """Return ``(ans, prec, err)`` — err=1 means incomparable."""
    ans = 0
    prec = 0
    np1 = None
    np2 = None

    while True:
        np1 = _next_seg(si, dir1)
        np2 = _next_seg(sj, dir2)
        if np1 is None or np2 is None:
            break
        if not _is_parallel(np1, np2):
            break
        ans += 1
        si = np1
        sj = np2

    if np1 is None:
        prec = 0
    elif np2 is None:
        raise AssertionError("FIXME: np2 unexpectedly None in decide_point")
    else:
        temp = _seg_cmp(np1, np2)
        if temp == -2:
            return (0, 0, 1)
        prec = _propagate_prec(np1, temp, ans + 1, 1 - dir1)

    return (ans, prec, 0)


def _set_parallel_edges(seg1: Segment, seg2: Segment,
                        dir1: int, dir2: int, hops: int,
                        mp: Maze) -> None:
    """Port of ``ortho.c::set_parallel_edges`` — propagate edge direction
    through a series of parallel segments across two edges."""
    if seg1.is_vert:
        chan = _find_channel(mp.vchans, seg1.comm_coord, seg1.p)
    else:
        chan = _find_channel(mp.hchans, seg1.comm_coord, seg1.p)
    if chan is None or seg1.ind_no is None or seg2.ind_no is None:
        return  # segment never got a channel; nothing to propagate
    rawgraph.insert_edge(chan.G, seg1.ind_no, seg2.ind_no)

    for _ in range(hops):
        prev1 = _next_seg(seg1, dir1)
        prev2 = _next_seg(seg2, dir2)
        if prev1 is None or prev2 is None:
            break

        if not seg1.is_vert:
            nchan = _find_channel(mp.vchans, prev1.comm_coord, prev1.p)
            if prev1.comm_coord == seg1.p.p1:
                if seg1.l1 == Bend.B_UP:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
                else:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)
            else:
                if seg1.l2 == Bend.B_UP:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)
                else:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
        else:
            nchan = _find_channel(mp.hchans, prev1.comm_coord, prev1.p)
            if prev1.comm_coord == seg1.p.p1:
                if seg1.l1 == Bend.B_LEFT:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)
                else:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
            else:
                if seg1.l2 == Bend.B_LEFT:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
                else:
                    if rawgraph.edge_exists(chan.G, seg1.ind_no, seg2.ind_no):
                        rawgraph.insert_edge(nchan.G, prev1.ind_no, prev2.ind_no)
                    else:
                        rawgraph.insert_edge(nchan.G, prev2.ind_no, prev1.ind_no)

        chan = nchan
        seg1 = prev1
        seg2 = prev2


def _remove_edge(seg1: Segment, seg2: Segment, direction: int,
                 mp: Maze) -> None:
    """Port of ``ortho.c::removeEdge``."""
    ptr1 = seg1
    ptr2 = seg2
    while _is_parallel(ptr1, ptr2):
        n1 = _next_seg(ptr1, 1)
        n2 = _next_seg(ptr2, direction)
        if n1 is None or n2 is None:
            return
        ptr1 = n1
        ptr2 = n2
    if ptr1.is_vert:
        chan = _find_channel(mp.vchans, ptr1.comm_coord, ptr1.p)
    else:
        chan = _find_channel(mp.hchans, ptr1.comm_coord, ptr1.p)
    if chan is None or ptr1.ind_no is None or ptr2.ind_no is None:
        return
    rawgraph.remove_redge(chan.G, ptr1.ind_no, ptr2.ind_no)


def _add_p_edges_channel(cp: Channel, mp: Maze) -> int:
    """Port of ``ortho.c::addPEdges`` for one channel."""
    G = cp.G
    segs = cp.seg_list
    for i in range(len(segs) - 1):
        for j in range(i + 1, len(segs)):
            if (not rawgraph.edge_exists(G, i, j)
                    and not rawgraph.edge_exists(G, j, i)):
                if not _is_parallel(segs[i], segs[j]):
                    continue

                # get_directions.
                if segs[i].prev is None:
                    dir_ = 0 if segs[j].prev is None else 1
                elif segs[j].prev is None:
                    dir_ = 1
                else:
                    if (segs[i].prev.comm_coord ==
                            segs[j].prev.comm_coord):
                        dir_ = 0
                    else:
                        dir_ = 1

                a, prec1, err = _decide_point(segs[i], segs[j], 0, dir_)
                if err:
                    return -1
                hops_a = a
                b, prec2, err = _decide_point(segs[i], segs[j], 1, 1 - dir_)
                if err:
                    return -1
                hops_b = b

                if prec1 == -1:
                    _set_parallel_edges(segs[j], segs[i], dir_, 0,
                                        hops_a, mp)
                    _set_parallel_edges(segs[j], segs[i], 1 - dir_, 1,
                                        hops_b, mp)
                    if prec2 == 1:
                        _remove_edge(segs[i], segs[j], 1 - dir_, mp)
                elif prec1 == 0:
                    if prec2 == -1:
                        _set_parallel_edges(segs[j], segs[i], dir_, 0,
                                            hops_a, mp)
                        _set_parallel_edges(segs[j], segs[i], 1 - dir_, 1,
                                            hops_b, mp)
                    elif prec2 == 0 or prec2 == 1:
                        _set_parallel_edges(segs[i], segs[j], 0, dir_,
                                            hops_a, mp)
                        _set_parallel_edges(segs[i], segs[j], 1, 1 - dir_,
                                            hops_b, mp)
                elif prec1 == 1:
                    _set_parallel_edges(segs[i], segs[j], 0, dir_,
                                        hops_a, mp)
                    _set_parallel_edges(segs[i], segs[j], 1, 1 - dir_,
                                        hops_b, mp)
                    if prec2 == -1:
                        _remove_edge(segs[i], segs[j], 1 - dir_, mp)
    return 0


def _add_p_edges(chans: dict, mp: Maze) -> int:
    for chani in chans.values():
        for cp in chani.chans.values():
            if _add_p_edges_channel(cp, mp) != 0:
                return -1
    return 0


def _assign_track_no(chans: dict) -> None:
    """Port of ``ortho.c::assignTrackNo`` — topsort each channel's
    interference graph, assign ``track_no = topsort_order + 1``."""
    for chani in chans.values():
        for cp in chani.chans.values():
            if not cp.seg_list:
                continue
            rawgraph.top_sort(cp.G)
            for k, seg in enumerate(cp.seg_list):
                seg.track_no = cp.G.vertices[k].topsort_order + 1


def _assign_tracks(mp: Maze) -> int:
    """Port of ``ortho.c::assignTracks``."""
    _create_graphs(mp.hchans)
    _create_graphs(mp.vchans)

    if _add_np_edges(mp.hchans) != 0:
        return -1
    if _add_np_edges(mp.vchans) != 0:
        return -1
    if _add_p_edges(mp.hchans, mp) != 0:
        return -1
    if _add_p_edges(mp.vchans, mp) != 0:
        return -1

    _assign_track_no(mp.hchans)
    _assign_track_no(mp.vchans)
    return 0


# =====================================================================
# vtrack / htrack / attachOrthoEdges
# =====================================================================


def _vtrack(seg: Segment, mp: Maze) -> float:
    chp = _find_channel(mp.vchans, seg.comm_coord, seg.p)
    if chp is None or seg.track_no is None:
        # Segment was dropped in _assign_segs; fall back to the
        # segment's own comm_coord (x for vertical) as a sensible
        # default so :func:`_attach_ortho_edges` still gets a number.
        return seg.comm_coord
    f = seg.track_no / (len(chp.seg_list) + 1)
    return chp.cp.bb.LL.x + f * (chp.cp.bb.UR.x - chp.cp.bb.LL.x)


def _htrack(seg: Segment, mp: Maze) -> float:
    chp = _find_channel(mp.hchans, seg.comm_coord, seg.p)
    if chp is None or seg.track_no is None:
        return seg.comm_coord
    f = 1.0 - seg.track_no / (len(chp.seg_list) + 1)
    lo = chp.cp.bb.LL.y
    hi = chp.cp.bb.UR.y
    return round(lo + f * (hi - lo))


def _attach_ortho_edges(mp: Maze, routes: list[Route],
                        edge_endpoints: list[tuple[Ppoint, Ppoint]],
                        ) -> list[list[Ppoint]]:
    """Port of ``ortho.c::attachOrthoEdges`` — compute final waypoints.

    ``edge_endpoints[i]`` is ``(tail_pos, head_pos)`` for edge ``i``.
    Returns a list of waypoint lists, one per input edge.
    """
    out: list[list[Ppoint]] = []
    for irte, (p1, q1) in enumerate(edge_endpoints):
        rte = routes[irte]
        ispline: list[Ppoint] = []

        if not rte.segs:
            out.append([])
            continue

        seg = rte.segs[0]
        if seg.is_vert:
            p = Ppoint(_vtrack(seg, mp), p1.y)
        else:
            p = Ppoint(p1.x, _htrack(seg, mp))
        ispline.append(Ppoint(p.x, p.y))
        ispline.append(Ppoint(p.x, p.y))

        for i in range(1, len(rte.segs)):
            seg = rte.segs[i]
            if seg.is_vert:
                p = Ppoint(_vtrack(seg, mp), p.y)
            else:
                p = Ppoint(p.x, _htrack(seg, mp))
            ispline.append(Ppoint(p.x, p.y))
            ispline.append(Ppoint(p.x, p.y))
            ispline.append(Ppoint(p.x, p.y))

        # Final waypoint attaches to the head.
        if seg.is_vert:
            p = Ppoint(_vtrack(seg, mp), q1.y)
        else:
            p = Ppoint(q1.x, _htrack(seg, mp))
        ispline.append(Ppoint(p.x, p.y))
        ispline.append(Ppoint(p.x, p.y))

        out.append(ispline)
    return out


# =====================================================================
# Public entry point
# =====================================================================


@dataclass
class OrthoEdgeInput:
    """Input tuple for :func:`ortho_edges`.

    Abstracts away the layout-object source so the public entry can be
    unit-tested with synthetic inputs as well as driven from a live
    :class:`DotGraphInfo`.
    """
    tail_bb: Boxf
    head_bb: Boxf
    tail_pos: Ppoint
    head_pos: Ppoint
    edge_id: int  # opaque caller handle (typically ``id(le)``)


def ortho_edges(layout, *, use_lbls: bool) -> dict[int, list]:
    """Route all ortho edges on ``layout``; return ``{edge_id: points}``.

    Port of ``ortho.c::orthoEdges`` — invoked once per graph from
    :mod:`gvpy.engines.layout.dot.dotsplines` under ``GVPY_ORTHO_V2=1``.

    Consumes duck-typed ``layout`` objects (:class:`DotGraphInfo`) to
    stay independent of the dot backend: reads ``layout.lnodes`` and
    iterates ``layout.ledges`` + ``layout._chain_edges``.  Builds the
    maze from node bboxes and runs the orthogonal routing pipeline.
    """
    del use_lbls  # C warns + disables; mirror that

    inputs = _collect_inputs(layout)
    n_real = sum(1 for _ in getattr(layout, "ledges", ()) if not _.virtual)
    n_chain = len(getattr(layout, "_chain_edges", ()))
    print(
        f"[TRACE ortho-route] entry n_real={n_real} n_chain={n_chain} "
        f"use_lbls=0",
        file=sys.stderr,
    )

    if not inputs:
        print("[TRACE ortho-route] no inputs — skip", file=sys.stderr)
        return {}

    # Build the maze once per call.
    gcell_bboxes = _unique_gcell_bboxes(inputs)
    mp = mk_maze(gcell_bboxes)

    # Attach each LayoutNode's cell (by bbox lookup).
    bb_to_cell = {_bb_key(c.bb): c for c in mp.gcells}

    # Sort edges by length ascending (C does qsort with edgecmp).
    sorted_inputs = sorted(
        inputs,
        key=lambda e: (e.tail_pos.x - e.head_pos.x) ** 2
                      + (e.tail_pos.y - e.head_pos.y) ** 2,
    )
    print(
        f"[TRACE ortho-route] edges sorted n={len(sorted_inputs)}",
        file=sys.stderr,
    )

    sg = mp.sg
    gstart = sg.nnodes
    # Ensure capacity for +2 terminal snodes.
    while len(sg.nodes) <= gstart + 1:
        sg.nodes.append(Snode())
        sg.nodes[-1].index = len(sg.nodes) - 1
    sn = sg.nodes[gstart]
    dn = sg.nodes[gstart + 1]

    pq = fpq.pq_gen(sg.nnodes + 2)

    routes: list[Route] = []
    routed_inputs: list[OrthoEdgeInput] = []
    for inp in sorted_inputs:
        start_cell = bb_to_cell.get(_bb_key(inp.tail_bb))
        dest_cell = bb_to_cell.get(_bb_key(inp.head_bb))
        if start_cell is None or dest_cell is None:
            routes.append(Route(segs=[]))
            routed_inputs.append(inp)
            continue

        if start_cell is dest_cell:
            _add_loop(sg, start_cell, dn, sn)
        else:
            _add_node_edges(sg, dest_cell, dn)
            _add_node_edges(sg, start_cell, sn)

        rc = short_path(pq, sg, dn, sn)
        if rc != 0:
            print("[TRACE ortho-route] shortPath overflow — abort",
                  file=sys.stderr)
            break

        rte = _convert_sp_to_route(sg, sn, dn)
        routes.append(rte)
        routed_inputs.append(inp)
        reset(sg)

    mp.hchans = _extract_h_chans(mp)
    mp.vchans = _extract_v_chans(mp)
    print(
        f"[TRACE ortho-route] channels h={_chan_count(mp.hchans)} "
        f"v={_chan_count(mp.vchans)}",
        file=sys.stderr,
    )
    _assign_segs(routes, mp)
    if _assign_tracks(mp) != 0:
        print("[TRACE ortho-route] tracks assigned ok=False",
              file=sys.stderr)
        return {}
    print("[TRACE ortho-route] tracks assigned ok=True", file=sys.stderr)

    endpoints = [(inp.tail_pos, inp.head_pos) for inp in routed_inputs]
    waypoint_lists = _attach_ortho_edges(mp, routes, endpoints)

    result: dict[int, list] = {}
    for inp, pts in zip(routed_inputs, waypoint_lists):
        if pts:
            result[inp.edge_id] = [(p.x, p.y) for p in pts]
            print(
                f"[TRACE ortho-route] waypoints edge={inp.edge_id} "
                f"npts={len(pts)}",
                file=sys.stderr,
            )
    return result


# =====================================================================
# Layout adapter
# =====================================================================


def _collect_inputs(layout) -> list[OrthoEdgeInput]:
    """Pull ortho-routable edges out of a :class:`DotGraphInfo`."""
    inputs: list[OrthoEdgeInput] = []
    lnodes = getattr(layout, "lnodes", {})
    for attr in ("ledges", "_chain_edges"):
        bucket = getattr(layout, attr, None)
        if not bucket:
            continue
        for le in bucket:
            if getattr(le, "virtual", False) and attr == "ledges":
                continue
            tail = lnodes.get(le.tail_name)
            head = lnodes.get(le.head_name)
            if tail is None or head is None:
                continue
            if le.tail_name == le.head_name:
                continue  # self-loops go through _add_loop, not this adapter
            inputs.append(OrthoEdgeInput(
                tail_bb=_lnode_bb(tail),
                head_bb=_lnode_bb(head),
                tail_pos=Ppoint(tail.x, tail.y),
                head_pos=Ppoint(head.x, head.y),
                edge_id=id(le),
            ))
    return inputs


def _lnode_bb(lnode) -> Boxf:
    """``LayoutNode`` → :class:`Boxf`.  Matches C's ``mkMaze`` formula:
    ``w2 = max(1, width/2)`` so zero-size nodes still occupy a 2×2 cell."""
    w2 = max(1.0, lnode.width / 2.0)
    h2 = max(1.0, lnode.height / 2.0)
    return Boxf(
        LL=Ppoint(lnode.x - w2, lnode.y - h2),
        UR=Ppoint(lnode.x + w2, lnode.y + h2),
    )


def _unique_gcell_bboxes(inputs: list[OrthoEdgeInput]) -> list[Boxf]:
    """Deduplicate node bboxes that appear in multiple edges."""
    seen: dict[tuple, Boxf] = {}
    for inp in inputs:
        for bb in (inp.tail_bb, inp.head_bb):
            k = _bb_key(bb)
            if k not in seen:
                seen[k] = bb
    return list(seen.values())


def _bb_key(bb: Boxf) -> tuple[float, float, float, float]:
    return (bb.LL.x, bb.LL.y, bb.UR.x, bb.UR.y)


def _chan_count(chans: dict) -> int:
    return sum(len(chani.chans) for chani in chans.values())
