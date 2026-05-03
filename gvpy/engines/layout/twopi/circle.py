"""Twopi radial layout algorithm.

Mirrors ``lib/twopigen/circle.c`` (Emden Gansner's port of
Graham Wills' GD'97 algorithm).  Places nodes on concentric
circles radiating from a center node:

============================  =======================================
Python function               C source
============================  =======================================
``init_layout``               ``initLayout``               (line 74)
``set_n_steps_to_leaf``       ``setNStepsToLeaf``          (line 34)
``is_leaf``                   ``isLeaf``                   (line 55)
``find_center_node``          ``findCenterNode``           (line 96)
``set_n_steps_to_center``     ``setNStepsToCenter``        (line 117)
``set_parent_nodes``          ``setParentNodes``           (line 147)
``set_subtree_size``          ``setSubtreeSize``           (line 172)
``set_child_subtree_spans``   ``setChildSubtreeSpans``     (line 184)
``set_subtree_spans``         ``setSubtreeSpans``          (line 210)
``set_child_positions``       ``setChildPositions``        (line 220)
``set_positions``             ``setPositions``             (line 246)
``get_ranksep_array``         ``getRankseps``              (line 258)
``set_absolute_pos``          ``setAbsolutePos``           (line 289)
``circle_layout``             ``circleLayout``             (line 312)
============================  =======================================

Algorithm summary:

1. ``init_layout`` — set ``s_leaf = 0`` for leaves, ``∞`` for
   interior nodes; ``s_center = ∞``; ``theta = UNSET``.
2. ``find_center_node`` — DFS from each leaf to compute
   ``s_leaf(n) = min steps from n to any leaf``.  The node with
   max ``s_leaf`` is the most-interior node and becomes the
   center.
3. ``set_parent_nodes`` — BFS from center to assign
   ``s_center`` (radial level) and parent pointers.
4. ``set_subtree_size`` — for each leaf, increment ``stsize`` for
   the leaf itself and walk up parent chain; result is
   ``stsize(n) = leaves in subtree``.
5. ``set_subtree_spans`` — top-down: each child gets
   ``parent_span * child_stsize / parent_stsize``.
6. ``set_positions`` — top-down: each child theta is the lower
   boundary of the parent's fan plus its own half-span; siblings
   are placed left-to-right.
7. ``set_absolute_pos`` — convert (level, theta) to (x, y) using
   the ranksep array.

Trace tag: ``[TRACE twopi]``.
"""
from __future__ import annotations

import math
import os
import sys
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.twopi.twopi_layout import TwopiLayout

# ``UNSET`` sentinel for the ``theta`` field — mirrors
# ``circle.c:28``.  Any value outside [0, 2π] would do; we use 10.
UNSET_THETA = 10.0
# Default ranksep in points (1 inch × 72).  Mirrors ``DEF_RANKSEP``
# at circle.c:27.
DEF_RANKSEP = 72.0
# Minimum ranksep — see ``MIN_RANKSEP`` in C.
MIN_RANKSEP = 1.0


def _trace(msg: str) -> None:
    """Emit a ``[TRACE twopi]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_TWOPI=1``)."""
    if os.environ.get("GVPY_TRACE_TWOPI", "") == "1":
        print(f"[TRACE twopi] {msg}", file=sys.stderr)


def is_leaf(name: str, adj: dict[str, list[str]]) -> bool:
    """Return True if ``name`` has at most one distinct neighbour
    (excluding self-loops).

    Mirrors ``circle.c::isLeaf`` (line 55).  A node with all
    duplicate neighbours (multiedges to the same node) is still a
    leaf.
    """
    distinct = None
    for v in adj.get(name, ()):
        if v == name:
            continue
        if distinct is None:
            distinct = v
        elif distinct != v:
            return False
    return True


def init_layout(layout: "TwopiLayout",
                names: list[str],
                adj: dict[str, list[str]]) -> None:
    """Initialise per-node algorithm state.

    Mirrors ``circle.c::initLayout`` (line 74).  The ``∞`` sentinel
    is set to ``n²`` — guaranteed greater than any reachable
    distance in a graph of ``n`` nodes.
    """
    n_nodes = len(names)
    INF = n_nodes * n_nodes
    for name in names:
        ln = layout.lnodes[name]
        ln.s_center = INF
        ln.theta = UNSET_THETA
        ln.s_leaf = 0 if is_leaf(name, adj) else INF
        ln.parent = ""
        ln.stsize = 0
        ln.span = 0.0


def set_n_steps_to_leaf(layout: "TwopiLayout",
                        name: str,
                        prev: str,
                        adj: dict[str, list[str]]) -> None:
    """DFS from a leaf (or a node with already-set ``s_leaf``).

    Mirrors ``circle.c::setNStepsToLeaf`` (line 34).  For each
    neighbour ``next``, if ``s_leaf(name) + 1 < s_leaf(next)`` we
    update and recurse — the test guarantees termination because
    each visited node's value can only decrease finitely many
    times.
    """
    ln = layout.lnodes[name]
    nsteps = ln.s_leaf + 1
    for next_ in adj.get(name, ()):
        if next_ == prev:
            continue
        next_ln = layout.lnodes[next_]
        if nsteps < next_ln.s_leaf:
            next_ln.s_leaf = nsteps
            set_n_steps_to_leaf(layout, next_, name, adj)


def find_center_node(layout: "TwopiLayout",
                     names: list[str],
                     adj: dict[str, list[str]]) -> str:
    """Return the most-interior node — max ``s_leaf``.

    Mirrors ``circle.c::findCenterNode`` (line 96).  DFS from every
    leaf to propagate ``s_leaf`` (min distance to any leaf), then
    pick the node with max ``s_leaf``.
    """
    for name in names:
        if layout.lnodes[name].s_leaf == 0:
            set_n_steps_to_leaf(layout, name, "", adj)

    center = names[0]
    max_s = 0
    for name in names:
        if layout.lnodes[name].s_leaf > max_s:
            max_s = layout.lnodes[name].s_leaf
            center = name
    return center


def set_n_steps_to_center(layout: "TwopiLayout",
                          root: str,
                          adj: dict[str, list[str]]) -> None:
    """BFS from the root: assign ``s_center`` and parent pointers.

    Mirrors ``circle.c::setNStepsToCenter`` (line 117).  Uses a
    queue (FIFO) so each node is reached via a shortest path.
    Edges with ``weight=0`` are skipped — the C reference reads
    the edge attribute table; we rely on ``adj`` having already
    omitted such edges (Py builds adjacency at the layout
    boundary).
    """
    queue: deque[str] = deque([root])
    while queue:
        n = queue.popleft()
        n_ln = layout.lnodes[n]
        nsteps = n_ln.s_center + 1
        for next_ in adj.get(n, ()):
            next_ln = layout.lnodes[next_]
            if nsteps < next_ln.s_center:
                next_ln.s_center = nsteps
                next_ln.parent = n
                n_ln.n_child += 1
                queue.append(next_)


def set_parent_nodes(layout: "TwopiLayout",
                     names: list[str],
                     adj: dict[str, list[str]],
                     center: str) -> int:
    """Configure parent / s_center, return max s_center.

    Mirrors ``circle.c::setParentNodes`` (line 147).  Returns the
    largest s_center value across all nodes — the radial depth of
    the layout.  Returns ``-1`` if any node was unreached (matches
    the C ``UINT64_MAX`` failure path).
    """
    unset = layout.lnodes[center].s_center  # the INF sentinel
    layout.lnodes[center].s_center = 0
    layout.lnodes[center].parent = ""

    set_n_steps_to_center(layout, center, adj)

    maxn = 0
    for name in names:
        s = layout.lnodes[name].s_center
        if s == unset:
            return -1
        if s > maxn:
            maxn = s
    return maxn


def set_subtree_size(layout: "TwopiLayout",
                     names: list[str]) -> None:
    """Compute leaves-in-subtree per node.

    Mirrors ``circle.c::setSubtreeSize`` (line 172).  Bottom-up:
    for each leaf in the BFS tree (n_child == 0), increment its own
    ``stsize`` and walk up the parent chain incrementing each
    ancestor.
    """
    for name in names:
        ln = layout.lnodes[name]
        if ln.n_child > 0:
            continue
        ln.stsize += 1
        parent = ln.parent
        while parent:
            layout.lnodes[parent].stsize += 1
            parent = layout.lnodes[parent].parent


def set_child_subtree_spans(layout: "TwopiLayout",
                            n: str,
                            adj: dict[str, list[str]]) -> None:
    """Top-down recursion: distribute angular span among children.

    Mirrors ``circle.c::setChildSubtreeSpans`` (line 184).  Each
    child's span is ``parent_span * child_stsize / parent_stsize``.
    """
    n_ln = layout.lnodes[n]
    if n_ln.stsize == 0:
        return
    ratio = n_ln.span / n_ln.stsize
    for next_ in adj.get(n, ()):
        next_ln = layout.lnodes[next_]
        if next_ln.parent != n:
            continue   # not a child in the BFS tree
        if next_ln.span != 0:
            continue   # already set (multiedges)
        next_ln.span = ratio * next_ln.stsize
        if next_ln.n_child > 0:
            set_child_subtree_spans(layout, next_, adj)


def set_subtree_spans(layout: "TwopiLayout",
                      center: str,
                      adj: dict[str, list[str]]) -> None:
    """Seed the centre's span at 2π and recurse.

    Mirrors ``circle.c::setSubtreeSpans`` (line 210).
    """
    layout.lnodes[center].span = 2 * math.pi
    set_child_subtree_spans(layout, center, adj)


def set_child_positions(layout: "TwopiLayout",
                        n: str,
                        adj: dict[str, list[str]]) -> None:
    """Top-down position assignment.

    Mirrors ``circle.c::setChildPositions`` (line 220).  ``theta``
    walks left-to-right through the children: each child's theta
    is the lower boundary plus its own half-span.
    """
    n_ln = layout.lnodes[n]
    if not n_ln.parent:
        theta = 0.0
    else:
        theta = n_ln.theta - n_ln.span / 2

    for next_ in adj.get(n, ()):
        next_ln = layout.lnodes[next_]
        if next_ln.parent != n:
            continue
        if next_ln.theta != UNSET_THETA:
            continue   # multiedges already handled

        next_ln.theta = theta + next_ln.span / 2.0
        theta += next_ln.span

        if next_ln.n_child > 0:
            set_child_positions(layout, next_, adj)


def set_positions(layout: "TwopiLayout",
                  center: str,
                  adj: dict[str, list[str]]) -> None:
    """Seed the centre's theta at 0 and recurse.

    Mirrors ``circle.c::setPositions`` (line 246).
    """
    layout.lnodes[center].theta = 0.0
    set_child_positions(layout, center, adj)


def get_ranksep_array(ranksep_str: str,
                      max_rank: int) -> list[float]:
    """Build the cumulative ranksep array of length ``max_rank+1``.

    Mirrors ``circle.c::getRankseps`` (line 258).  Position 0 is
    always 0.  Each subsequent position is the cumulative sum of
    inch-deltas parsed from the colon-separated ``ranksep`` value
    (in points: each delta is converted to pt × 72).  If fewer
    deltas are provided than levels, the last delta is repeated.
    """
    ranks = [0.0] * (max_rank + 1)
    deltas: list[float] = []
    if ranksep_str:
        for token in ranksep_str.replace(":", " ").split():
            try:
                d = float(token) * 72.0
                if d > 0:
                    deltas.append(max(d, MIN_RANKSEP))
            except ValueError:
                pass

    if not deltas:
        delx = DEF_RANKSEP
    else:
        delx = deltas[-1]

    xf = 0.0
    for rk in range(1, max_rank + 1):
        if rk - 1 < len(deltas):
            xf += deltas[rk - 1]
        else:
            xf += delx
        ranks[rk] = xf

    return ranks


def set_absolute_pos(layout: "TwopiLayout",
                     names: list[str],
                     max_rank: int) -> None:
    """Convert (s_center, theta) to (x, y).

    Mirrors ``circle.c::setAbsolutePos`` (line 289).
    """
    rs_str = layout.graph.get_graph_attr("ranksep") or ""
    ranksep = get_ranksep_array(rs_str, max_rank)
    layout._ranksep_radii = ranksep  # exposed for tests / diagnostics

    for name in names:
        ln = layout.lnodes[name]
        if ln.s_center < 0 or ln.s_center >= len(ranksep):
            continue
        hyp = ranksep[ln.s_center]
        ln.x = hyp * math.cos(ln.theta)
        ln.y = hyp * math.sin(ln.theta)


def circle_layout(layout: "TwopiLayout",
                  names: list[str],
                  adj: dict[str, list[str]],
                  center_hint: str | None = None) -> str:
    """Top-level radial layout for one connected component.

    Mirrors ``circle.c::circleLayout`` (line 312).  Returns the
    name of the chosen centre node so the caller can write it back
    to the graph's ``root`` attribute.
    """
    if not names:
        return ""
    if len(names) == 1:
        ln = layout.lnodes[names[0]]
        ln.x, ln.y = 0.0, 0.0
        return names[0]

    init_layout(layout, names, adj)

    if center_hint and center_hint in layout.lnodes:
        center = center_hint
    else:
        center = find_center_node(layout, names, adj)

    max_rank = set_parent_nodes(layout, names, adj, center)
    if max_rank < 0:
        _trace(f"warning: weight=0 created a disconnected component "
               f"(centre {center})")
        return center

    _trace(f"centre={center} max_rank={max_rank}")

    set_subtree_size(layout, names)
    set_subtree_spans(layout, center, adj)
    set_positions(layout, center, adj)
    set_absolute_pos(layout, names, max_rank)
    return center
