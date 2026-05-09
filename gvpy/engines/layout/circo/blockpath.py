"""C-aligned port of ``lib/circogen/blockpath.c`` —
single-block circular layout.

Given one biconnected block, this module produces:

1. A *skeleton* of the block — the original block minus
   "pair edges" that would otherwise distort the spanning tree
   topology.  Mirrors C ``remove_pair_edges`` / ``find_pair_edges``.
2. A spanning tree of the skeleton via DFS.  Mirrors C
   ``spanning_tree`` / ``dfs``.
3. The *longest path* in that tree (the diameter), via the
   measure-distance-from-every-leaf algorithm.  Mirrors C
   ``find_longest_path`` / ``measure_distance``.
4. The remaining nodes placed adjacent to neighbors already on
   the path.  Mirrors C ``place_residual_nodes`` /
   ``place_node``.
5. Edge-crossings reduction by trying to insert each node next
   to each of its neighbors.  Mirrors C ``reduce_edge_crossings``
   / ``reduce`` / ``count_all_crossings``.
6. Final placement on a circle: ``radius = N · (min_dist +
   largest_node) / (2π)``, nodes equispaced.  If any node is
   marked ``ISPARENT`` (an articulation point linking to a
   child block), the path is rotated so that node sits at
   index 0.  Mirrors C ``layout_block``.

The state-tracking macros from C ``circular.h`` (``DISTONE``,
``DISTTWO``, ``LEAFONE``, ``LEAFTWO``, ``TPARENT``, ``ONPATH``,
``NEIGHBOR``, ``POSITION``, ``PSI``, ``ISPARENT``, ``VISITED``)
are stored on a per-block :class:`BlockpathState` instead of
mutating Graphviz node objects in place.

The DFS uses an explicit work stack to dodge Python recursion
limits on dense blocks.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.circo.block import Block
from gvpy.engines.layout.circo.nodelist import (
    append_at,
    insert_relative,
    realign,
    reverse_append,
)


# ─────────────────────────────────────────────────────────────────
# Per-block scratch state (replaces C's ND_alg per-node fields)
# ─────────────────────────────────────────────────────────────────


@dataclass
class _NodeBPState:
    """Mirrors the Pass 3 fields of C ``cdata`` (circular.h:42).

    Only one of (visited/tparent + dist1/dist2/leaf1/leaf2) and
    (onpath + neighbor + position + psi) is meaningful at a
    time, but C overlays them with a union — we keep them as
    separate fields here for clarity.
    """
    visited: bool = False
    onpath: bool = False
    neighbor: bool = False
    is_parent: bool = False
    tparent: Optional[str] = None
    dist1: int = 0
    dist2: int = 0
    leaf1: Optional[str] = None
    leaf2: Optional[str] = None
    position: int = 0
    psi: float = 0.0


@dataclass
class BlockpathState:
    """Per-block scratch space for the layout algorithms.

    Instances are cheap (one per block); we don't bother
    pooling them.  Each :class:`_NodeBPState` is created lazily.
    """
    nodes: dict[str, _NodeBPState] = field(default_factory=dict)
    # Edge order during ``count_all_crossings``.  Keys are
    # canonical (min, max) pairs.  0 = edge not yet opened.
    edge_order: dict[tuple[str, str], int] = field(default_factory=dict)

    def n(self, name: str) -> _NodeBPState:
        """Lazy-create per-node state."""
        s = self.nodes.get(name)
        if s is None:
            s = _NodeBPState()
            self.nodes[name] = s
        return s


def _key(u: str, v: str) -> tuple[str, str]:
    """Canonical undirected edge key."""
    return (u, v) if u <= v else (v, u)


# ─────────────────────────────────────────────────────────────────
# remove_pair_edges + find_pair_edges (skeleton construction)
# ─────────────────────────────────────────────────────────────────


def _find_pair_edges(
    n: str,
    deg: dict[str, int],
    in_adj: dict[str, list[str]],
    out_adj: dict[str, list[str]],
) -> None:
    """Mirrors C ``find_pair_edges`` (blockpath.c:102).

    For node ``n`` (about to be peeled off the working graph
    ``in_adj``), partition its neighbors into "with pair edge"
    (the two nodes share another neighbour besides ``n``) and
    "without pair edge".  If there are extra "without" neighbors
    beyond a baseline of ``deg(n) - 1 - num_pairs``, add
    skeleton edges between consecutive unpaired neighbors so
    the spanning-tree topology is preserved when ``n`` is
    removed.

    Modifies:
    - ``in_adj`` (the working graph): adds pair-edges between
      consecutive ``neighbors_without`` so the spanning tree
      sees the same connectivity after ``n`` is peeled off.
    - ``deg``: degree counts updated for any added edges.
    - ``out_adj`` (the skeleton being built): removes the
      "pair edges" — duplicate edges between two of n's
      neighbors are collapsed.
    """
    nbrs = list(in_adj.get(n, []))
    node_degree = deg.get(n, len(nbrs))
    edge_cnt = 0
    # Use sets so we don't double-count pair edges.
    counted_pairs: set[tuple[str, str]] = set()

    neighbors_with: list[str] = []
    neighbors_without: list[str] = []

    for n1 in nbrs:
        has_pair_edge = False
        for n2 in nbrs:
            if n2 == n1:
                continue
            if n2 in in_adj.get(n1, ()):
                has_pair_edge = True
                pk = _key(n1, n2)
                if pk not in counted_pairs:
                    counted_pairs.add(pk)
                    edge_cnt += 1
                    # Remove this pair edge from the skeleton
                    # output graph (mirrors C ``agdelete``).
                    if n2 in out_adj.get(n1, ()):
                        out_adj[n1].remove(n2)
                    if n1 in out_adj.get(n2, ()):
                        out_adj[n2].remove(n1)
        if has_pair_edge:
            neighbors_with.append(n1)
        else:
            neighbors_without.append(n1)

    # We need ``node_degree - 1 - edge_cnt`` extra connectivity
    # edges to be added between unpaired neighbours.  The exact
    # count comes from C's invariant: removing n from a
    # 2-connected block must keep the rest connected.
    diff = node_degree - 1 - edge_cnt
    if diff <= 0:
        return

    nw = neighbors_without
    if diff < len(nw):
        # Pair up consecutive entries (mark, mark+1).
        mark = 0
        while mark + 1 < len(nw):
            tp, hp = nw[mark], nw[mark + 1]
            if hp not in in_adj.get(tp, ()):
                in_adj[tp].append(hp)
                in_adj[hp].append(tp)
                deg[tp] += 1
                deg[hp] += 1
            diff -= 1
            mark += 2
        # Then chain (nw[0], nw[2..]) until diff exhausted.
        mark = 2
        while diff > 0 and mark < len(nw):
            tp = nw[0]
            hp = nw[mark]
            if hp not in in_adj.get(tp, ()):
                in_adj[tp].append(hp)
                in_adj[hp].append(tp)
                deg[tp] += 1
                deg[hp] += 1
            mark += 1
            diff -= 1
    elif diff == len(nw):
        # Fan out from the first ``with`` neighbour to every
        # ``without`` neighbour.  C uses the first
        # neighbors_with entry; if there is none, edges are
        # created with NULL tail (no-op for C, no-op for us).
        if neighbors_with:
            tp = neighbors_with[0]
            for hp in nw:
                if hp not in in_adj.get(tp, ()):
                    in_adj[tp].append(hp)
                    in_adj[hp].append(tp)
                    deg[tp] += 1
                    deg[hp] += 1


def _remove_pair_edges(
    block_nodes: list[str],
    block_adj: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Mirrors C ``remove_pair_edges`` (blockpath.c:182).

    Builds the *skeleton* graph: a copy of the block with
    pair-edge duplicates collapsed.  Returns an adjacency dict
    over the same nodes; the original ``block_adj`` is NOT
    modified.

    Algorithm:

    1. Clone the block adjacency into a working ``in_adj`` and
       a separate output ``out_adj`` (the skeleton).
    2. Sort nodes by descending degree.
    3. Repeat ``len(nodes) - 3`` times:
       a. Pop the lowest-degree node ``cur`` off the sorted list.
       b. Call :func:`_find_pair_edges` on ``cur`` — this adds
          synthetic edges to ``in_adj`` between cur's
          neighbours so connectivity is preserved when cur is
          removed, and removes pair edges from ``out_adj``.
       c. Decrement neighbour degrees, re-sort.
       d. Remove ``cur`` from ``in_adj``.
    4. Return ``out_adj`` — the skeleton.

    The "minus 3" caps the algorithm at a 3-node residual
    so we don't degrade to a single node (the residual at
    the end is the seed for the spanning-tree DFS).
    """
    in_adj: dict[str, list[str]] = {
        n: list(block_adj.get(n, [])) for n in block_nodes
    }
    out_adj: dict[str, list[str]] = {
        n: list(block_adj.get(n, [])) for n in block_nodes
    }
    deg: dict[str, int] = {n: len(in_adj[n]) for n in block_nodes}

    # Working list, sorted descending by degree (C's
    # ``cmpDegree`` sorts descending; we POP_BACK so the
    # lowest-degree node is processed first).
    dl: list[str] = sorted(block_nodes, key=lambda x: -deg[x])

    for _ in range(len(block_nodes) - 3):
        if not dl:
            break
        cur = dl.pop()  # lowest degree
        # Snapshot neighbours before mutation.
        nbrs = list(in_adj.get(cur, []))
        # Remove neighbours from dl since they'll be re-inserted
        # after their degree changes.
        for adj_n in nbrs:
            if adj_n in dl:
                dl.remove(adj_n)

        _find_pair_edges(cur, deg, in_adj, out_adj)

        # Re-fetch nbrs (find_pair_edges may have added new
        # edges to cur, but we only iterate the *original*
        # neighbours per C semantics).
        for adj_n in nbrs:
            deg[adj_n] -= 1
            # Remove cur from adj_n's neighbour list.
            if cur in in_adj.get(adj_n, ()):
                in_adj[adj_n].remove(cur)
            dl.append(adj_n)

        # Re-sort descending by degree.
        dl.sort(key=lambda x: -deg[x])

        # Remove cur from in_adj.
        in_adj.pop(cur, None)

    return out_adj


# ─────────────────────────────────────────────────────────────────
# spanning_tree + DFS
# ─────────────────────────────────────────────────────────────────


def _spanning_tree(
    block_nodes: list[str],
    skeleton_adj: dict[str, list[str]],
    state: BlockpathState,
) -> dict[str, list[str]]:
    """Mirrors C ``spanning_tree`` (blockpath.c:340).

    Returns a tree as an adjacency dict (still undirected — each
    tree edge appears in both endpoint's lists).  Sets
    ``state.n(n).tparent`` for every reachable n.
    """
    # Reset per-node state.
    for n in block_nodes:
        s = state.n(n)
        s.dist1 = 0
        s.dist2 = 0
        s.visited = False
        s.tparent = None
        s.leaf1 = None
        s.leaf2 = None

    tree: dict[str, list[str]] = {n: [] for n in block_nodes}

    for start in block_nodes:
        if state.n(start).visited:
            continue
        state.n(start).tparent = None
        # Iterative DFS — explicit stack of (node, neighbor_iter).
        stack: list = [(start, iter(skeleton_adj.get(start, [])))]
        state.n(start).visited = True
        while stack:
            u, it = stack[-1]
            try:
                v = next(it)
            except StopIteration:
                stack.pop()
                continue
            sv = state.n(v)
            if sv.visited:
                continue
            sv.visited = True
            sv.tparent = u
            tree[u].append(v)
            tree[v].append(u)
            stack.append((v, iter(skeleton_adj.get(v, []))))

    return tree


# ─────────────────────────────────────────────────────────────────
# find_longest_path + measure_distance
# ─────────────────────────────────────────────────────────────────


def _measure_distance(
    n: str,
    ancestor: str,
    dist: int,
    change: Optional[str],
    state: BlockpathState,
) -> None:
    """Mirrors C ``measure_distance`` (blockpath.c:225).

    From leaf ``n``, walk up the tree.  At each ancestor, see
    whether the path to ``n`` is the longest or second-longest
    so far rooted there; update ``leaf1`` / ``dist1`` /
    ``leaf2`` / ``dist2`` accordingly.

    Iterative version of the C recursion.  ``change`` is C's
    bookkeeping for the "leaf was previously this one — when
    upgrading, push the old leaf to second-place" case.
    """
    while True:
        s_anc = state.n(ancestor)
        parent = s_anc.tparent
        if parent is None:
            return
        dist += 1
        s_par = state.n(parent)

        if s_par.dist1 == 0:
            s_par.leaf1 = n
            s_par.dist1 = dist
        elif dist > s_par.dist1:
            if s_par.leaf1 != change:
                if not s_par.dist2 or s_par.leaf2 != change:
                    change = s_par.leaf1
                s_par.leaf2 = s_par.leaf1
                s_par.dist2 = s_par.dist1
            s_par.leaf1 = n
            s_par.dist1 = dist
        elif dist > s_par.dist2:
            s_par.leaf2 = n
            s_par.dist2 = dist
            return
        else:
            return

        ancestor = parent


def _find_longest_path(
    block_nodes: list[str],
    tree: dict[str, list[str]],
    state: BlockpathState,
) -> list[str]:
    """Mirrors C ``find_longest_path`` (blockpath.c:263).

    For each leaf in the tree, run ``measure_distance`` upward.
    Then find the node whose ``dist1 + dist2`` is maximal
    (= the diameter midpoint) and walk from each of its
    ``leaf1`` / ``leaf2`` back through ``tparent`` to build the
    path.

    Returns a list of node names along the longest path.  Sets
    ``state.n(n).onpath`` for every node on the path.
    """
    if len(block_nodes) == 1:
        n = block_nodes[0]
        state.n(n).onpath = True
        return [n]

    # Run measure_distance from every leaf.
    for n in block_nodes:
        if len(tree.get(n, [])) == 1:
            _measure_distance(n, n, 0, None, state)

    # Find diameter midpoint.
    common: Optional[str] = None
    maxlength = 0
    for n in block_nodes:
        s = state.n(n)
        length = s.dist1 + s.dist2
        if length > maxlength:
            common = n
            maxlength = length

    if common is None:
        # Degenerate (no leaves — shouldn't happen on a real
        # tree, but handle gracefully).
        for n in block_nodes:
            state.n(n).onpath = True
        return list(block_nodes)

    # Walk leaf1 back to common.
    begin_path: list[str] = []
    s_common = state.n(common)
    n = s_common.leaf1
    while n is not None and n != common:
        begin_path.append(n)
        state.n(n).onpath = True
        n = state.n(n).tparent
    begin_path.append(common)
    state.n(common).onpath = True

    # Walk leaf2 back to common, then reverse-append.
    if s_common.dist2:
        end_path: list[str] = []
        n = s_common.leaf2
        while n is not None and n != common:
            end_path.append(n)
            state.n(n).onpath = True
            n = state.n(n).tparent
        reverse_append(begin_path, end_path)

    return begin_path


# ─────────────────────────────────────────────────────────────────
# place_node + place_residual_nodes
# ─────────────────────────────────────────────────────────────────


def _place_node(
    n: str,
    block_adj: dict[str, list[str]],
    path: list[str],
    state: BlockpathState,
) -> None:
    """Mirrors C ``place_node`` (blockpath.c:507).

    Insert ``n`` into ``path`` next to whichever neighbour it
    has on the path.  Prefer a position between *two consecutive*
    path neighbours; fall back to "right after any one
    neighbour"; fall back to "append at end".
    """
    # Mark all of n's neighbours.
    nbrs = list(block_adj.get(n, []))
    for nb in nbrs:
        state.n(nb).neighbor = True
    placed = False

    if len(nbrs) >= 2 and path:
        # Look for two consecutive path entries that are both
        # neighbours of n.
        L = len(path)
        for one in range(L):
            two = (one + 1) % L
            if state.n(path[one]).neighbor and state.n(path[two]).neighbor:
                append_at(path, one + 1, n)
                placed = True
                break

    if not placed and nbrs and path:
        # Any single neighbour on path.
        for one in range(len(path)):
            if state.n(path[one]).neighbor:
                append_at(path, one + 1, n)
                placed = True
                break

    if not placed:
        path.append(n)

    # Unmark neighbours.
    for nb in nbrs:
        state.n(nb).neighbor = False


def _place_residual_nodes(
    block_nodes: list[str],
    block_adj: dict[str, list[str]],
    path: list[str],
    state: BlockpathState,
) -> None:
    """Mirrors C ``place_residual_nodes`` (blockpath.c:555)."""
    for n in block_nodes:
        if not state.n(n).onpath:
            _place_node(n, block_adj, path, state)


# ─────────────────────────────────────────────────────────────────
# count_all_crossings + reduce + reduce_edge_crossings
# ─────────────────────────────────────────────────────────────────


def _count_all_crossings(
    path: list[str],
    block_nodes: list[str],
    block_edges: list[tuple[str, str]],
    block_adj: dict[str, list[str]],
) -> int:
    """Mirrors C ``count_all_crossings`` (blockpath.c:382).

    Counts edge crossings on a circular layout where the nodes
    appear around the circle in ``path`` order.

    Algorithm: walk nodes in path order with an "open edge
    list".  When we hit a node that's the *second* endpoint
    of an open edge, every still-open edge whose first endpoint
    came strictly later in our walk than this edge's first
    endpoint AND that doesn't touch the current node, crosses
    this edge.
    """
    edge_order: dict[tuple[str, str], int] = {}
    for u, v in block_edges:
        edge_order[_key(u, v)] = 0

    open_edges: list[tuple[str, str]] = []
    crossings = 0
    order = 1

    pos_in_path = {n: i for i, n in enumerate(path)}

    for n in path:
        # First sweep: close edges incident to n (whose order > 0).
        # We collect the "to close" first to avoid mutating
        # ``open_edges`` mid-iteration.
        closing: list[tuple[str, str]] = []
        for nb in block_adj.get(n, []):
            if nb not in pos_in_path:
                continue
            ek = _key(n, nb)
            if edge_order.get(ek, 0) > 0:
                closing.append(ek)

        for ek in closing:
            ek_order = edge_order[ek]
            for ep in open_edges:
                if ep == ek:
                    continue
                ep_order = edge_order[ep]
                if ep_order > ek_order:
                    # Does ep touch n?
                    if n != ep[0] and n != ep[1]:
                        crossings += 1
            open_edges.remove(ek)

        # Second sweep: open edges incident to n with order==0.
        for nb in block_adj.get(n, []):
            if nb not in pos_in_path:
                continue
            ek = _key(n, nb)
            if edge_order.get(ek, 0) == 0:
                edge_order[ek] = order
                open_edges.append(ek)

        order += 1

    return crossings


_CROSS_ITER = 10


def _reduce(
    path: list[str],
    block_nodes: list[str],
    block_edges: list[tuple[str, str]],
    block_adj: dict[str, list[str]],
    cnt: list[int],
) -> list[str]:
    """Mirrors C ``reduce`` (blockpath.c:435).

    For each node, try moving it next to each of its neighbours
    (both before and after).  Keep any move that reduces
    crossings.  ``cnt`` is a 1-element mutable list (Python's
    int-by-pointer workaround) holding the current crossing
    count; updated in place.

    Returns the (possibly-reordered) path.
    """
    crossings = cnt[0]
    for cur in list(block_nodes):
        for nb in list(block_adj.get(cur, [])):
            if nb not in block_nodes:
                continue
            for j in (0, 1):
                snapshot = list(path)
                insert_relative(path, cur, nb, j)
                new_crossings = _count_all_crossings(
                    path, block_nodes, block_edges, block_adj,
                )
                if new_crossings < crossings:
                    crossings = new_crossings
                    if crossings == 0:
                        cnt[0] = 0
                        return path
                else:
                    path[:] = snapshot
    cnt[0] = crossings
    return path


def _reduce_edge_crossings(
    path: list[str],
    block_nodes: list[str],
    block_edges: list[tuple[str, str]],
    block_adj: dict[str, list[str]],
) -> list[str]:
    """Mirrors C ``reduce_edge_crossings`` (blockpath.c:474).

    Iterate :func:`_reduce` until either no crossings remain or
    no improvement was made (or we hit ``CROSS_ITER`` rounds).
    """
    crossings = _count_all_crossings(
        path, block_nodes, block_edges, block_adj,
    )
    if crossings == 0:
        return path
    cnt = [crossings]
    for _ in range(_CROSS_ITER):
        orig = cnt[0]
        path = _reduce(path, block_nodes, block_edges, block_adj, cnt)
        if cnt[0] == orig or cnt[0] == 0:
            return path
    return path


# ─────────────────────────────────────────────────────────────────
# layout_block — the public entry
# ─────────────────────────────────────────────────────────────────


def largest_nodesize(
    path: list[str],
    widths: dict[str, float],
    heights: dict[str, float],
) -> float:
    """Mirrors C ``largest_nodesize`` (blockpath.c:492).

    Returns ``max(width, height)`` over all nodes on the path.
    """
    out = 0.0
    for n in path:
        w = widths.get(n, 0.0)
        h = heights.get(n, 0.0)
        if w > out:
            out = w
        if h > out:
            out = h
    return out


def layout_block(
    block: Block,
    block_adj: dict[str, list[str]],
    widths: dict[str, float],
    heights: dict[str, float],
    min_dist: float,
) -> list[str]:
    """Mirrors C ``layout_block`` (blockpath.c:566).

    Lays out a single block in its own ``(0, 0)``-anchored
    coordinate frame:

    1. Build skeleton (``_remove_pair_edges``).
    2. Spanning tree (``_spanning_tree``).
    3. Longest path (``_find_longest_path``).
    4. Place residual nodes (``_place_residual_nodes``).
    5. Reduce crossings (``_reduce_edge_crossings``).
    6. Realign so any ``ISPARENT`` node sits at index 0.
    7. Place on circle, set ``block.radius`` and ``block.rad0``,
       initialize ``block.parent_pos = -1``.

    Updates :attr:`block.circle_list`, :attr:`block.node_pos`
    (per-node coords relative to block center), :attr:`block.radius`,
    :attr:`block.rad0`, :attr:`block.parent_pos`.

    Returns the final ordered node list (= ``block.circle_list``).
    """
    nodes = list(block.sub_graph)
    node_set = set(nodes)
    # Filter the global adjacency down to edges within this
    # block.  ``block_adj`` is the graph-wide adjacency; the
    # blockpath algorithms (skeleton + spanning tree + crossings)
    # all assume neighbours are restricted to the block.
    block_adj = {
        n: [v for v in block_adj.get(n, []) if v in node_set]
        for n in nodes
    }
    state = BlockpathState()
    # Mark the parent_anchor's "own anchor" as ISPARENT so the
    # circle realigns to put it at index 0.  Mirrors C: the
    # block-cut tree builder calls ``SET_PARENT(parent)`` on the
    # articulation point; the ``CHILD(bp)`` of each child block
    # is what gets placed at index 0 in *that* child's circle.
    # Here we mark the node IN this block that's the entry point
    # to a child block — i.e., any node that is a parent of some
    # child block.
    for ch in block.children:
        if ch.parent_anchor:
            state.n(ch.parent_anchor).is_parent = True

    if len(nodes) == 1:
        n = nodes[0]
        block.circle_list = [n]
        block.node_pos = {n: (0.0, 0.0)}
        block.radius = max(widths.get(n, 0.0), heights.get(n, 0.0)) / 2.0
        block.rad0 = block.radius
        block.parent_pos = -1.0
        return block.circle_list

    if len(nodes) == 2:
        # Skip the full algorithm; just place them on a tiny circle.
        n0, n1 = nodes[0], nodes[1]
        # Circle radius from the same N·(min_dist + largest)/(2π)
        # formula C uses, with N=2.
        largest = largest_nodesize(nodes, widths, heights)
        radius = 2.0 * (min_dist + largest) / (2.0 * math.pi)
        block.circle_list = [n0, n1]
        block.node_pos = {
            n0: (radius, 0.0),
            n1: (-radius, 0.0),
        }
        block.radius = radius
        block.rad0 = radius
        block.parent_pos = -1.0
        return block.circle_list

    # 1. Skeleton.
    skeleton = _remove_pair_edges(nodes, block_adj)
    # 2. Spanning tree on skeleton.
    tree = _spanning_tree(nodes, skeleton, state)
    # 3. Longest path through the tree.
    path = _find_longest_path(nodes, tree, state)
    # 4. Place residual nodes.
    _place_residual_nodes(nodes, block_adj, path, state)
    # 5. Reduce edge crossings.  Use the block's edge list so
    #    crossings are counted on real graph edges (not skeleton
    #    edges).
    if not block.edges:
        # Engine should have populated block.edges, but fall
        # back to deriving from adjacency.
        seen: set[tuple[str, str]] = set()
        edges: list[tuple[str, str]] = []
        for u in nodes:
            for v in block_adj.get(u, []):
                if v not in nodes:
                    continue
                ek = _key(u, v)
                if ek in seen:
                    continue
                seen.add(ek)
                edges.append(ek)
        block.edges = edges
    path = _reduce_edge_crossings(
        path, nodes, list(block.edges), block_adj,
    )

    # 6. Realign: rotate so any ISPARENT node sits at index 0.
    for i, n in enumerate(path):
        if state.n(n).is_parent:
            realign(path, i)
            break

    # 7. Place on circle.
    N = len(path)
    largest = largest_nodesize(path, widths, heights)
    if N == 1:
        radius = 0.0
    else:
        radius = N * (min_dist + largest) / (2.0 * math.pi)

    block.node_pos = {}
    for k, n in enumerate(path):
        sk = state.n(n)
        sk.position = k
        sk.psi = 0.0
        theta = k * (2.0 * math.pi / N)
        block.node_pos[n] = (
            radius * math.cos(theta),
            radius * math.sin(theta),
        )

    if N == 1:
        block.radius = largest / 2.0
    else:
        block.radius = radius
    block.rad0 = block.radius
    block.parent_pos = -1.0
    block.circle_list = list(path)
    # Stash positions/psi for circpos to read.
    for n in path:
        block.node_psi[n] = state.n(n).psi
    block._bp_state = state  # type: ignore[attr-defined]

    return block.circle_list
