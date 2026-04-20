"""Port of ``lib/ortho/maze.{h,c}`` — build an orthogonal routing maze.

Takes a list of graph-node bounding boxes (``gcell`` bboxes), runs
:func:`partition` to decompose the surrounding space into cells, then
builds an :class:`sgraph.Sgraph` whose snodes sit on cell-to-cell
boundaries and whose sedges are the six possible traversals (4 corner
bends + 1 vertical cut + 1 horizontal cut) per cell.

Semantics track the C verbatim:

- ``MARGIN = 36`` pixels of breathing room around the node-union BB.
- Cell flag bits ``MZ_ISNODE`` / ``MZ_VSCAN`` / ``MZ_HSCAN`` /
  ``MZ_SMALLV`` / ``MZ_SMALLH`` match C's ``maze.h``.
- Edge weight formula — ``wt = delta*(w+h)/2 + mu`` — matches C's
  ``createSEdges``, with ``delta=1`` (length weight) and ``mu=500``
  (bend weight).
- Narrow cells (``IS_SMALL``: ``(dim - 3) / 2 < 2``) get their
  longitudinal traversal weighted to ``BIG = 16384`` so the router
  avoids them.
- :func:`mark_small` propagates ``MZ_SMALLV`` / ``MZ_SMALLH`` through
  adjacent non-node cells so the side-of-node cells become passable
  for routes that would otherwise be blocked by narrow channels.

**Input adapter.**  C's ``mkMaze`` reads ``graph_t`` directly
(``ND_coord``, ``ND_xsize``, ``ND_ysize``, ``ND_alg``).  This port
takes pre-computed :class:`Boxf` list to keep the module independent
of any particular layout object shape; the Phase 6 orchestration
layer will bridge :class:`DotGraphInfo` → bbox list.

**Parity strategy.**  Unlike :mod:`trapezoid` / :mod:`partition`, no
standalone C harness is provided because ``mkMazeGraph`` is ``static``
and ``mkMaze`` requires a full libcgraph + libcommon + libgvc scaffold
to construct a ``graph_t``.  Instead this module is validated by
structural invariants (4-sides shape, edge-count formula, sgraph
connectivity) plus integration through :func:`short_path` on the
produced sgraph; full end-to-end parity falls to Phase 6.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.common.geom import Ppoint
from gvpy.engines.layout.ortho import sgraph as sgraph_mod
from gvpy.engines.layout.ortho.partition import Boxf, Cell, partition
from gvpy.engines.layout.ortho.sgraph import Sgraph, Snode, create_sedge

# Side indices — ``maze.h`` @ 21: ``enum {M_RIGHT=0, M_TOP, M_LEFT, M_BOTTOM};``
M_RIGHT = 0
M_TOP = 1
M_LEFT = 2
M_BOTTOM = 3

# Cell-flag bits — ``maze.h`` @ 23-27.
MZ_ISNODE = 1
MZ_VSCAN = 2
MZ_HSCAN = 4
MZ_SMALLV = 8
MZ_SMALLH = 16

# Edge-weight constants — ``maze.c`` @ 136-143.
DELTA = 1       # weight of length
MU = 500        # weight of bends
BIG = 16384
MARGIN = 36


def is_node(cp: Cell) -> bool:
    return bool(cp.flags & MZ_ISNODE)


def is_vscan(cp: Cell) -> bool:
    return bool(cp.flags & MZ_VSCAN)


def is_hscan(cp: Cell) -> bool:
    return bool(cp.flags & MZ_HSCAN)


def is_smallv(cp: Cell) -> bool:
    return bool(cp.flags & MZ_SMALLV)


def is_smallh(cp: Cell) -> bool:
    return bool(cp.flags & MZ_SMALLH)


def _chansz(w: float) -> float:
    """``CHANSZ`` macro — channel size: ``(w - 3) / 2``."""
    return (w - 3) / 2


def _is_small(v: float) -> bool:
    """``IS_SMALL`` macro — channel fits fewer than 2 routes."""
    return _chansz(v) < 2


@dataclass
class Maze:
    """Port of ``maze`` in ``maze.h`` @ 66.

    ``hchans`` / ``vchans`` are populated later by ortho.c's
    ``extractHChans`` / ``extractVChans`` (Phase 6) — they live here
    as placeholder ``None`` fields for forward compatibility.
    """
    ncells: int = 0
    ngcells: int = 0
    cells: list[Cell] = field(default_factory=list)
    gcells: list[Cell] = field(default_factory=list)
    sg: Optional[Sgraph] = None
    hchans: Optional[list] = None
    vchans: Optional[list] = None


# ---------- weight updates ----------


def update_wt(ep, sz: float) -> None:
    """``maze.c::updateWt`` — bump edge count; spike weight at capacity."""
    ep.cnt += 1
    if ep.cnt > sz:
        ep.cnt = 0
        ep.weight += BIG


def update_wts(g: Sgraph, cp: Cell, ep) -> None:
    """``maze.c::updateWts`` — reweight cell's edges after a route passes.

    Bend edges are always bumped; straight edges are bumped only if
    the passing route ``ep`` itself bends, or if ``ep`` is the very
    edge being updated.
    """
    # BEND(g, e) — the two endpoints have different isVert.
    def _bend(e) -> bool:
        return g.nodes[e.v1].is_vert != g.nodes[e.v2].is_vert

    def _horz(e) -> bool:
        return g.nodes[e.v1].is_vert

    is_bend_ep = _bend(ep)
    hsz = _chansz(cp.bb.UR.y - cp.bb.LL.y)
    vsz = _chansz(cp.bb.UR.x - cp.bb.LL.x)
    minsz = min(hsz, vsz)

    # Bend edges come first in the per-cell list (createSEdges ordering).
    i = 0
    while i < cp.nedges:
        e = cp.edges[i]
        if not _bend(e):
            break
        update_wt(e, minsz)
        i += 1
    while i < cp.nedges:
        e = cp.edges[i]
        if is_bend_ep or e is ep:
            update_wt(e, hsz if _horz(e) else vsz)
        i += 1


# ---------- markSmall ----------


def _mark_small(cp: Cell) -> None:
    """``maze.c::markSmall`` — propagate SMALLV/SMALLH into side cells.

    A narrow gcell's side-cells (cells touching its left/right or
    top/bottom) inherit the ``MZ_SMALLV`` / ``MZ_SMALLH`` flag so the
    router's channel-width penalty treats them as deliberately narrow
    rather than accidentally narrow.
    """
    if _is_small(cp.bb.UR.y - cp.bb.LL.y):
        for onp in cp.sides:
            if onp is None or not onp.is_vert:
                continue
            if onp.cells[0] is cp:  # onp on cp's right
                ocp = onp.cells[1]
                if ocp is not None:
                    ocp.flags |= MZ_SMALLV
                    while True:
                        right = _side_at(ocp, M_RIGHT)
                        if right is None:
                            break
                        nxt = right.cells[1]
                        if nxt is None or is_node(nxt):
                            break
                        ocp = nxt
                        ocp.flags |= MZ_SMALLV
            else:  # onp on cp's left
                ocp = onp.cells[0]
                if ocp is not None:
                    ocp.flags |= MZ_SMALLV
                    while True:
                        left = _side_at(ocp, M_LEFT)
                        if left is None:
                            break
                        nxt = left.cells[0]
                        if nxt is None or is_node(nxt):
                            break
                        ocp = nxt
                        ocp.flags |= MZ_SMALLV

    if _is_small(cp.bb.UR.x - cp.bb.LL.x):
        for onp in cp.sides:
            if onp is None or onp.is_vert:
                continue
            if onp.cells[0] is cp:  # onp on cp's top
                ocp = onp.cells[1]
                if ocp is not None:
                    ocp.flags |= MZ_SMALLH
                    while True:
                        top = _side_at(ocp, M_TOP)
                        if top is None:
                            break
                        nxt = top.cells[1]
                        if nxt is None or is_node(nxt):
                            break
                        ocp = nxt
                        ocp.flags |= MZ_SMALLH
            else:  # onp on cp's bottom
                ocp = onp.cells[0]
                if ocp is not None:
                    ocp.flags |= MZ_SMALLH
                    while True:
                        bot = _side_at(ocp, M_BOTTOM)
                        if bot is None:
                            break
                        nxt = bot.cells[0]
                        if nxt is None or is_node(nxt):
                            break
                        ocp = nxt
                        ocp.flags |= MZ_SMALLH


def _side_at(cp: Cell, slot: int) -> Optional[Snode]:
    """Return ``cp.sides[slot]`` iff ``cp.sides`` has the 4-slot layout.

    Cells produced from the partition have exactly 4 sides (R/T/L/B);
    gcells collected from the hdict/vdict walk have variable-length
    side lists without a fixed slot convention, so ``_side_at`` is
    only meaningful on cells.
    """
    if len(cp.sides) == 4 and slot < 4:
        return cp.sides[slot]
    return None


# ---------- cell-edge creation ----------


def _create_sedges(cp: Cell, g: Sgraph) -> None:
    """``maze.c::createSEdges`` — up to 6 edges per cell.

    The four bend edges (LT, TR, LB, BR) come first in C's ordering;
    ``update_wts`` relies on this "bends first" sequencing.
    """
    bb = cp.bb
    hwt = DELTA * (bb.UR.x - bb.LL.x)
    vwt = DELTA * (bb.UR.y - bb.LL.y)
    wt = (hwt + vwt) / 2.0 + MU

    # Small channels cost more, guiding routes to spacious ones.
    if _is_small(bb.UR.y - bb.LL.y) and not is_smallv(cp):
        hwt = BIG
        wt = BIG
    if _is_small(bb.UR.x - bb.LL.x) and not is_smallh(cp):
        vwt = BIG
        wt = BIG

    sides = cp.sides
    left = sides[M_LEFT] if len(sides) == 4 else None
    top = sides[M_TOP] if len(sides) == 4 else None
    right = sides[M_RIGHT] if len(sides) == 4 else None
    bottom = sides[M_BOTTOM] if len(sides) == 4 else None

    if left is not None and top is not None:
        cp.edges.append(create_sedge(g, left, top, wt))
        cp.nedges += 1
    if top is not None and right is not None:
        cp.edges.append(create_sedge(g, top, right, wt))
        cp.nedges += 1
    if left is not None and bottom is not None:
        cp.edges.append(create_sedge(g, left, bottom, wt))
        cp.nedges += 1
    if bottom is not None and right is not None:
        cp.edges.append(create_sedge(g, bottom, right, wt))
        cp.nedges += 1
    if top is not None and bottom is not None:
        cp.edges.append(create_sedge(g, top, bottom, vwt))
        cp.nedges += 1
    if left is not None and right is not None:
        cp.edges.append(create_sedge(g, left, right, hwt))
        cp.nedges += 1


# ---------- snode lookup tables ----------


def _find_svert(g: Sgraph, cdict: dict, pt: tuple[float, float],
                is_vert: bool) -> Snode:
    """``maze.c::findSVert`` — lookup-or-create snode at ``pt``."""
    if pt in cdict:
        return cdict[pt]
    np = sgraph_mod.create_snode(g)
    np.is_vert = is_vert
    cdict[pt] = np
    return np


def _walk_hdict_row(hdict: dict, start_x: float, y: float,
                    x_limit: float) -> list[Snode]:
    """Emulate C's ``dtmatch(hdict, &pt)`` + forward ``dtnext`` walk.

    Returns the snodes at the given ``y`` with ``x ∈ [start_x, x_limit)``,
    sorted by ``x`` ascending.  Empty list if no snode exists at
    exactly ``(start_x, y)`` — matches C's behaviour where
    ``dtmatch`` returning NULL skips the loop body entirely.
    """
    if (start_x, y) not in hdict:
        return []
    return [
        hdict[(x, yy)]
        for (x, yy) in sorted(
            ((xx, yy) for (xx, yy) in hdict
             if yy == y and start_x <= xx < x_limit),
            key=lambda xy: xy[0],
        )
    ]


def _walk_vdict_col(vdict: dict, x: float, start_y: float,
                    y_limit: float) -> list[Snode]:
    """``dtmatch`` + forward walk on the vertical dict (ordered by x,y)."""
    if (x, start_y) not in vdict:
        return []
    return [
        vdict[(xx, yy)]
        for (xx, yy) in sorted(
            ((xx, yy) for (xx, yy) in vdict
             if xx == x and start_y <= yy < y_limit),
            key=lambda xy: xy[1],
        )
    ]


# ---------- mkMazeGraph ----------


def _mk_maze_graph(mp: Maze, bb: Boxf) -> Sgraph:
    """``maze.c::mkMazeGraph`` — build the sgraph over all cells + gcells."""
    bound = 4 * mp.ncells
    g = sgraph_mod.create_sgraph(bound + 2)

    vdict: dict[tuple[float, float], Snode] = {}
    hdict: dict[tuple[float, float], Snode] = {}

    # Phase 1 — for each cell, create snodes at its 4 internal sides.
    # "Internal" = not coincident with the outer BB boundary.
    for cp in mp.cells:
        cp.nsides = 4
        cp.sides = [None, None, None, None]
        if cp.bb.UR.x < bb.UR.x:
            pt = (cp.bb.UR.x, cp.bb.LL.y)
            np = _find_svert(g, vdict, pt, is_vert=True)
            np.cells[0] = cp
            cp.sides[M_RIGHT] = np
        if cp.bb.UR.y < bb.UR.y:
            pt = (cp.bb.LL.x, cp.bb.UR.y)
            np = _find_svert(g, hdict, pt, is_vert=False)
            np.cells[0] = cp
            cp.sides[M_TOP] = np
        if cp.bb.LL.x > bb.LL.x:
            pt = (cp.bb.LL.x, cp.bb.LL.y)
            np = _find_svert(g, vdict, pt, is_vert=True)
            np.cells[1] = cp
            cp.sides[M_LEFT] = np
        if cp.bb.LL.y > bb.LL.y:
            pt = (cp.bb.LL.x, cp.bb.LL.y)
            np = _find_svert(g, hdict, pt, is_vert=False)
            np.cells[1] = cp
            cp.sides[M_BOTTOM] = np

    # Phase 2 — for each gcell, collect all snodes sitting on its border.
    maxdeg = 0
    for cp in mp.gcells:
        sides: list[Snode] = []

        # bottom (y = LL.y, x walks LL.x → UR.x).
        for np in _walk_hdict_row(hdict, cp.bb.LL.x, cp.bb.LL.y,
                                  cp.bb.UR.x):
            sides.append(np)
            np.cells[1] = cp
        # left (x = LL.x, y walks LL.y → UR.y).
        for np in _walk_vdict_col(vdict, cp.bb.LL.x, cp.bb.LL.y,
                                  cp.bb.UR.y):
            sides.append(np)
            np.cells[1] = cp
        # top (y = UR.y, x walks LL.x → UR.x).
        for np in _walk_hdict_row(hdict, cp.bb.LL.x, cp.bb.UR.y,
                                  cp.bb.UR.x):
            sides.append(np)
            np.cells[0] = cp
        # right (x = UR.x, y walks LL.y → UR.y).
        for np in _walk_vdict_col(vdict, cp.bb.UR.x, cp.bb.LL.y,
                                  cp.bb.UR.y):
            sides.append(np)
            np.cells[0] = cp

        cp.sides = sides
        cp.nsides = len(sides)
        if cp.nsides > maxdeg:
            maxdeg = cp.nsides

    # Phase 3 — propagate small-channel flags.
    for cp in mp.gcells:
        _mark_small(cp)

    # Index the +2 dummy slots used during per-edge routing.
    if g.nnodes + 1 < len(g.nodes):
        g.nodes[g.nnodes].index = g.nnodes
        g.nodes[g.nnodes + 1].index = g.nnodes + 1

    # Phase 4 — allocate edge storage + wire cell edges.
    sgraph_mod.init_sedges(g, maxdeg)
    for cp in mp.cells:
        _create_sedges(cp, g)

    _chk_sgraph(g)
    sgraph_mod.gsave(g)
    return g


def _chk_sgraph(g: Sgraph) -> None:
    """``maze.c::chkSgraph`` — warn when an snode is missing a cell link.

    C uses ``assert`` for this check, which compiles out in release
    builds — so in practice graphs where the invariant fails still
    route (with potentially wrong output) in upstream ``dot.exe``.
    Mirror that forgiving behaviour here: emit a trace line instead
    of crashing, so Phase 6 can surface the issue for debugging
    without breaking the full pipeline.
    """
    for i in range(g.nnodes):
        np = g.nodes[i]
        if np.cells[0] is None or np.cells[1] is None:
            print(
                f"[TRACE ortho-maze] chk_sgraph warn snode={i} "
                f"cells0={np.cells[0] is not None} "
                f"cells1={np.cells[1] is not None}",
                file=sys.stderr,
            )


# ---------- public entry point ----------


def mk_maze(gcell_bboxes: list[Boxf], margin: float = MARGIN) -> Maze:
    """Build a routing maze from a list of graph-node bounding boxes.

    Port of ``maze.c::mkMaze``, with the ``graph_t`` adapter pulled
    out of the signature — the Phase 6 orchestrator is responsible
    for converting :class:`DotGraphInfo` nodes into :class:`Boxf`
    inputs and reassigning cells back to nodes via ``ND_alg``.

    Parameters
    ----------
    gcell_bboxes
        One :class:`Boxf` per graph node — the node's visual bounding
        box in layout coordinates.
    margin
        Padding around the combined BB.  Default 36 matches C's
        ``MARGIN`` constant.
    """
    mp = Maze()
    mp.ngcells = len(gcell_bboxes)
    mp.gcells = [
        Cell(bb=Boxf(LL=Ppoint(b.LL.x, b.LL.y), UR=Ppoint(b.UR.x, b.UR.y)),
             flags=MZ_ISNODE)
        for b in gcell_bboxes
    ]

    # Union of all gcell bboxes, expanded by margin.
    if not gcell_bboxes:
        # Degenerate case — no nodes.  Pick an arbitrary unit box;
        # ortho routing never calls this in practice.
        bb = Boxf(LL=Ppoint(-margin, -margin), UR=Ppoint(margin, margin))
    else:
        bb = Boxf(
            LL=Ppoint(
                min(b.LL.x for b in gcell_bboxes) - margin,
                min(b.LL.y for b in gcell_bboxes) - margin,
            ),
            UR=Ppoint(
                max(b.UR.x for b in gcell_bboxes) + margin,
                max(b.UR.y for b in gcell_bboxes) + margin,
            ),
        )

    _emit_entry_trace(mp.ngcells, bb)

    rects = partition(mp.gcells, mp.ngcells, bb)
    mp.ncells = len(rects)
    mp.cells = [Cell(bb=r) for r in rects]

    mp.sg = _mk_maze_graph(mp, bb)

    _emit_exit_trace(mp)
    return mp


# ---------- trace emission ----------


def _emit_entry_trace(ngcells: int, bb: Boxf) -> None:
    print(
        f"[TRACE ortho-maze] mkmaze entry gnodes={ngcells} "
        f"bb={bb.LL.x:.6f},{bb.LL.y:.6f},{bb.UR.x:.6f},{bb.UR.y:.6f}",
        file=sys.stderr,
    )


def _emit_exit_trace(mp: Maze) -> None:
    print(
        f"[TRACE ortho-maze] mkmaze exit ncells={mp.ncells} "
        f"ngcells={mp.ngcells} sg_nnodes={mp.sg.nnodes if mp.sg else 0} "
        f"sg_nedges={mp.sg.nedges if mp.sg else 0}",
        file=sys.stderr,
    )
