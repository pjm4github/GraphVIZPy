"""Straight and curved edge routing (splines=line, splines=curved).

See: /lib/common/routespl.c @ 975

Phase G of the splines port.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from gvpy.engines.layout.dot.clip import clip_and_install
from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint
from gvpy.engines.layout.dot.regular_edge import _node_shape, _install_points

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import LayoutEdge, LayoutNode

MILLIPOINT = 0.001
EDGETYPE_CURVED = 2 << 1
EDGETYPE_PLINE = 3 << 1


# ── Graph centroid ─────────────────────────────────────────────────

def get_centroid(layout) -> tuple[float, float]:
    """Centroid of the graph bounding box.

    See: /lib/common/routespl.c @ 773
    """
    if not layout.lnodes:
        return (0.0, 0.0)
    xs = [ln.x for ln in layout.lnodes.values()]
    ys = [ln.y for ln in layout.lnodes.values()]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


# ── Cycle detection ────────────────────────────────────────────────

def _find_all_cycles(layout) -> list[list[str]]:
    """Find all simple directed cycles in the graph.

    See: /lib/common/routespl.c @ 865
    Uses DFS from each node to find cycles back to itself.
    """
    adj: dict[str, list[str]] = {}
    for le in layout.ledges:
        if le.virtual:
            continue
        adj.setdefault(le.tail_name, []).append(le.head_name)

    cycles: list[list[str]] = []

    def _dfs(start: str, current: str, visited: list[str]):
        if current in visited:
            if current == start:
                cycle = list(visited)
                cycle_set = frozenset(cycle)
                if not any(frozenset(c) == cycle_set and len(c) == len(cycle)
                           for c in cycles):
                    cycles.append(cycle)
            return
        visited.append(current)
        for nb in adj.get(current, []):
            _dfs(start, nb, visited)
        visited.pop()

    for name in layout.lnodes:
        if name in adj:
            _dfs(name, name, [])

    return cycles


def _cycle_contains_edge(cycle: list[str], tail: str, head: str) -> bool:
    """Check if the directed edge tail→head is in the cycle.

    See: /lib/common/routespl.c @ 793
    """
    n = len(cycle)
    for i in range(n):
        c_start = cycle[i - 1] if i > 0 else cycle[n - 1]
        c_end = cycle[i]
        if c_start == tail and c_end == head:
            return True
    return False


def _find_shortest_cycle_with_edge(cycles: list[list[str]],
                                   tail: str, head: str,
                                   min_size: int = 3) -> list[str] | None:
    """Find the shortest cycle containing the edge tail→head.

    See: /lib/common/routespl.c @ 884
    """
    shortest = None
    for cycle in cycles:
        if len(cycle) < min_size:
            continue
        if shortest is not None and len(shortest) <= len(cycle):
            continue
        if _cycle_contains_edge(cycle, tail, head):
            shortest = cycle
    return shortest


def get_cycle_centroid(layout, le) -> tuple[float, float]:
    """Centroid of the shortest cycle containing edge *le*.

    See: /lib/common/routespl.c @ 904
    Falls back to graph centroid if no cycle found.
    """
    cycles = _find_all_cycles(layout)
    cycle = _find_shortest_cycle_with_edge(
        cycles, le.tail_name, le.head_name, min_size=3)
    if cycle is None:
        return get_centroid(layout)
    sx, sy = 0.0, 0.0
    cnt = 0
    for name in cycle:
        ln = layout.lnodes.get(name)
        if ln:
            sx += ln.x
            sy += ln.y
            cnt += 1
    if cnt == 0:
        return get_centroid(layout)
    return (sx / cnt, sy / cnt)


# ── bend ───────────────────────────────────────────────────────────

def bend(spl: list[Ppoint], centroid: tuple[float, float]) -> None:
    """Bend interior control points away from *centroid*.

    See: /lib/common/routespl.c @ 933

    Computes the midpoint of the straight edge ``spl[0]→spl[3]``,
    moves a distance ``dist/5`` AWAY from the centroid, and sets
    both interior control points ``spl[1]`` and ``spl[2]`` to that
    offset point.  This gives the edge a gentle curve away from the
    cycle center.
    """
    mid_x = (spl[0].x + spl[3].x) / 2
    mid_y = (spl[0].y + spl[3].y) / 2
    dist = math.hypot(spl[3].x - spl[0].x, spl[3].y - spl[0].y)
    r = dist / 5.0

    vx = centroid[0] - mid_x
    vy = centroid[1] - mid_y
    mag = math.hypot(vx, vy)
    if mag == 0:
        return
    ax = mid_x - vx / mag * r
    ay = mid_y - vy / mag * r
    spl[1] = Ppoint(ax, ay)
    spl[2] = Ppoint(ax, ay)


# ── makeStraightEdges ──────────────────────────────────────────────

def make_straight_edges(layout, edges: list, et: int) -> None:
    """Route edges as straight or gently curved lines.

    See: /lib/common/routespl.c @ 975

    For ``EDGETYPE_CURVED`` (``splines=curved``), the interior
    control points are bent away from the cycle centroid via
    :func:`bend`.  For all other modes, the edge is a degenerate
    cubic where ``spl[1] = spl[0]`` and ``spl[2] = spl[3]``
    (a straight line rendered as a Bezier).

    Multi-edge groups are fanned out perpendicular to the edge
    direction using ``nodesep`` spacing.
    """
    if not edges:
        return

    e_cnt = len(edges)
    le0 = edges[0]
    curved = et == EDGETYPE_CURVED

    tail = layout.lnodes.get(le0.tail_name)
    head = layout.lnodes.get(le0.head_name)
    if tail is None or head is None:
        return

    p0 = Ppoint(tail.x, tail.y)
    p3 = Ppoint(head.x, head.y)
    dumb = [Ppoint(p0.x, p0.y), Ppoint(p0.x, p0.y),
            Ppoint(p3.x, p3.y), Ppoint(p3.x, p3.y)]

    if e_cnt == 1:
        if curved:
            bend(dumb, get_cycle_centroid(layout, le0))
        clipped = clip_and_install(
            dumb,
            tail_x=tail.x, tail_y=tail.y,
            tail_hw=tail.width / 2, tail_hh=tail.height / 2,
            tail_shape=_node_shape(tail),
            tail_clip=getattr(le0, 'tailclip', True),
            head_x=head.x, head_y=head.y,
            head_hw=head.width / 2, head_hh=head.height / 2,
            head_shape=_node_shape(head),
            head_clip=getattr(le0, 'headclip', True),
        )
        _install_points(le0, clipped)
        return

    # Multi-edge: fan out perpendicular to the edge direction.
    if (abs(dumb[0].x - dumb[3].x) < MILLIPOINT and
            abs(dumb[0].y - dumb[3].y) < MILLIPOINT):
        del_x = 0.0
        del_y = 0.0
    else:
        perp_x = dumb[0].y - dumb[3].y
        perp_y = dumb[3].x - dumb[0].x
        l_perp = math.hypot(perp_x, perp_y)
        xstep = layout.nodesep
        dx = xstep * (e_cnt - 1) / 2
        dumb[1] = Ppoint(dumb[0].x + dx * perp_x / l_perp,
                         dumb[0].y + dx * perp_y / l_perp)
        dumb[2] = Ppoint(dumb[3].x + dx * perp_x / l_perp,
                         dumb[3].y + dx * perp_y / l_perp)
        del_x = -xstep * perp_x / l_perp
        del_y = -xstep * perp_y / l_perp

    for i, le in enumerate(edges):
        le_tail = layout.lnodes.get(le.tail_name)
        le_head = layout.lnodes.get(le.head_name)
        if le_tail is None or le_head is None:
            continue
        if le_head.name == head.name:
            pts = [Ppoint(d.x, d.y) for d in dumb]
        else:
            pts = [Ppoint(dumb[3 - j].x, dumb[3 - j].y) for j in range(4)]

        clipped = clip_and_install(
            pts,
            tail_x=le_tail.x, tail_y=le_tail.y,
            tail_hw=le_tail.width / 2, tail_hh=le_tail.height / 2,
            tail_shape=_node_shape(le_tail),
            tail_clip=getattr(le, 'tailclip', True),
            head_x=le_head.x, head_y=le_head.y,
            head_hw=le_head.width / 2, head_hh=le_head.height / 2,
            head_shape=_node_shape(le_head),
            head_clip=getattr(le, 'headclip', True),
        )
        _install_points(le, clipped)
        dumb[1] = Ppoint(dumb[1].x + del_x, dumb[1].y + del_y)
        dumb[2] = Ppoint(dumb[2].x + del_x, dumb[2].y + del_y)
