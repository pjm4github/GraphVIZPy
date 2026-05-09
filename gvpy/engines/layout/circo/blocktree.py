"""C-aligned port of ``lib/circogen/blocktree.c`` —
biconnected component decomposition + block-cut tree
construction.

Algorithm (mirrors C ``createBlocktree`` and ``dfs`` verbatim):

1. **Find blocks** via Tarjan's articulation-point DFS:
   - For each node ``u``, track ``VAL(u)`` (DFS discovery
     index) and ``LOWVAL(u)`` (lowest VAL reachable from any
     descendant).
   - Push every traversed edge onto a stack as we go.
   - When we return from ``v`` to ``u`` and ``LOWVAL(v) >=
     VAL(u)``, ``u`` is an articulation point.  Pop the edge
     stack down to (and including) the ``(u, v)`` edge — those
     edges form one biconnected block.
   - Each non-block-yet node touched by the popped edges joins
     the block; ``u`` itself joins iff (it isn't already in a
     block) AND (the block has > 1 node).

2. **Build block-cut tree** (``createBlocktree``,
   blocktree.c:143):
   - For each non-root block, find the node with the smallest
     ``VAL`` — that's the "child" pointer (the articulation
     point shared with the parent block).  Its
     ``PARENT()`` (set during DFS) is in some other block.
   - Mark that parent node ``ISPARENT``.
   - Set ``CHILD(bp) = child`` (the node connecting bp to its
     parent block).
   - Append ``bp`` to the parent block's ``children`` list.

The block-cut tree's root block is whichever was added to the
state's blocklist first.  C uses ``insertBlock`` (front-insert)
when it detects we're processing the root node, and
``appendBlock`` (back-insert) for everything else, so the root
ends up at index 0.

The C version uses Graphviz's mutation-friendly graph types;
GraphvizPy uses a separate ``BlockState`` object that holds
per-DFS-call state (val, lowval, parent, block, isparent
flags).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.circo.block import (
    Block,
    Blocklist,
    block_size,
    make_block,
)


# ─────────────────────────────────────────────────────────────────
# Per-DFS state
# ─────────────────────────────────────────────────────────────────


@dataclass
class _NodeState:
    """Per-node state during the Tarjan DFS.  Mirrors the
    relevant subset of C ``cdata`` (circular.h:42) — only the
    Pass 1 fields ``val``, ``low_val``, ``parent``, ``block``,
    ``flags`` are populated here.
    """
    val: int = 0
    low_val: int = 0
    parent: Optional[str] = None
    block: Optional[Block] = None
    is_parent: bool = False


@dataclass
class BlockState:
    """Mirrors C ``circ_state`` (circular.h:16) — DFS scratch
    space + collected blocklist."""
    block_count: int = 0
    order_count: int = 1
    blocklist: Blocklist = field(default_factory=Blocklist)
    nodes: dict[str, _NodeState] = field(default_factory=dict)
    # Edge orientation: +1 = head reachable from u along edge,
    # -1 = tail reachable.  Mirrors C ``EDGEORDER(e)``.
    edge_order: dict[tuple[str, str], int] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Tarjan DFS
# ─────────────────────────────────────────────────────────────────


def _dfs(
    adj: dict[str, list[str]],
    u: str,
    state: BlockState,
    is_root: bool,
    stack: list[tuple[str, str]],
) -> None:
    """Mirrors C ``dfs`` (blocktree.c:59) verbatim.

    Uses an explicit work stack to avoid Python recursion
    limits on dense graphs (C used recursion freely; we adapt
    to the same algorithm without changing its semantics).

    Parameters
    ----------
    adj : dict
        Undirected adjacency: ``adj[u]`` is a list of u's neighbors.
    u : str
        Starting node.
    state : BlockState
        DFS scratch state.
    is_root : bool
        True iff u is the DFS root (drives the special-case
        block creation for an isolated root, blocktree.c:106).
    stack : list of (tail, head)
        Edge stack; each visited tree edge is pushed.
    """
    # We implement the recursion explicitly with a continuation
    # frame so we can preserve C's edge-stack ordering exactly.
    # Each frame: (u, neighbor_iter, is_root, parent_marker).
    # ``parent_marker`` distinguishes the "post-recursion"
    # branch where we decide articulation-point block extraction.
    frames: list = [_DfsFrame(u, iter(adj.get(u, [])), is_root)]

    su = state.nodes.setdefault(u, _NodeState())
    su.val = state.order_count
    su.low_val = state.order_count
    state.order_count += 1

    while frames:
        top = frames[-1]
        # If we're returning from a recursive call, finalize.
        if top.pending_v is not None:
            v = top.pending_v
            sv = state.nodes[v]
            su = state.nodes[top.u]
            su.low_val = min(su.low_val, sv.low_val)

            if sv.low_val >= su.val:
                # u is an articulation point — pop block off the
                # edge stack.  Mirrors blocktree.c:77-101.
                block: Optional[Block] = None
                # We pop edges until we pop the (u, v) tree edge
                # itself.  The (u, v) edge was pushed when we
                # descended into v.
                while stack:
                    e = stack.pop()
                    et, eh = e
                    # Pick the "non-u" endpoint as np.  C uses
                    # EDGEORDER to figure out tail vs head; we
                    # encoded that in (et, eh) when we pushed.
                    np = eh
                    s_np = state.nodes.get(np)
                    if s_np is None:
                        s_np = state.nodes.setdefault(np, _NodeState())
                    if s_np.block is None:
                        if block is None:
                            block = make_block()
                            state.block_count += 1
                        block.sub_graph.append(np)
                        s_np.block = block
                    if e == (top.u, v):
                        break

                if block is not None:
                    # u joins block iff u not already in a block
                    # AND block has > 1 node.
                    if su.block is None and block_size(block) > 1:
                        block.sub_graph.append(top.u)
                        su.block = block
                    if top.is_root and su.block is block:
                        state.blocklist.insert(block)
                    else:
                        state.blocklist.append(block)

            top.pending_v = None
            continue

        # Continue iterating neighbors.
        try:
            v = next(top.neighbors)
        except StopIteration:
            # Done with u — handle the root special case
            # (blocktree.c:106-110): if root never joined a block,
            # give it its own singleton block.
            su = state.nodes[top.u]
            if top.is_root and su.block is None:
                block = make_block([top.u])
                state.block_count += 1
                su.block = block
                state.blocklist.insert(block)
            frames.pop()
            continue

        if v == top.u:
            continue
        sv = state.nodes.get(v)
        if sv is None or sv.val == 0:
            # Tree edge — descend.
            sv = state.nodes.setdefault(v, _NodeState())
            sv.val = state.order_count
            sv.low_val = state.order_count
            state.order_count += 1
            sv.parent = top.u
            stack.append((top.u, v))
            top.pending_v = v
            frames.append(_DfsFrame(v, iter(adj.get(v, [])), False))
        elif state.nodes[top.u].parent != v:
            # Back edge — update low_val.
            su = state.nodes[top.u]
            su.low_val = min(su.low_val, sv.val)


@dataclass
class _DfsFrame:
    u: str
    neighbors: object  # iterator
    is_root: bool
    pending_v: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# Block-cut tree
# ─────────────────────────────────────────────────────────────────


def find_blocks(
    adj: dict[str, list[str]],
    nodes: list[str],
    root_name: Optional[str] = None,
) -> BlockState:
    """Mirrors C ``find_blocks`` (blocktree.c:113).

    Walks the graph via DFS to discover all biconnected blocks.
    Returns a populated :class:`BlockState`.

    The DFS starting node is ``root_name`` if supplied (and
    present in ``nodes``); otherwise the first node in ``nodes``.
    """
    state = BlockState()
    if not nodes:
        return state
    root = (
        root_name if (root_name and root_name in adj)
        else nodes[0]
    )
    stack: list[tuple[str, str]] = []
    _dfs(adj, root, state, True, stack)

    # Cover any unreached nodes by repeating DFS.  C doesn't do
    # this (it assumes a connected component), but GraphvizPy's
    # caller doesn't always guarantee connectivity — fall back
    # gracefully.
    for n in nodes:
        if n not in state.nodes or state.nodes[n].val == 0:
            _dfs(adj, n, state, True, stack)

    return state


def create_blocktree(
    adj: dict[str, list[str]],
    nodes: list[str],
    root_name: Optional[str] = None,
) -> Optional[Block]:
    """Mirrors C ``createBlocktree`` (blocktree.c:143).

    Parameters
    ----------
    adj : dict[str, list[str]]
        Undirected adjacency.
    nodes : list[str]
        All nodes in the (connected) component.
    root_name : str, optional
        Preferred DFS root.

    Returns
    -------
    Block or None
        Root of the block-cut tree, or None for an empty input.
        Each non-root block has its ``child`` field set to the
        articulation point connecting it to its parent block.
    """
    if not nodes:
        return None

    state = find_blocks(adj, nodes, root_name)
    if not state.blocklist:
        # Single-node fallback.  Graphviz's caller guards
        # against this (single-node graph is short-circuited);
        # we mirror that as belt-and-suspenders.
        return make_block([nodes[0]])

    # Root is the first block (insertBlock during DFS put the
    # root-containing block at index 0).
    root_block = state.blocklist.first
    assert root_block is not None

    # Walk every other block, find its smallest-VAL node — that's
    # the articulation point shared with the parent block.
    for bp in state.blocklist.items[1:]:
        if not bp.sub_graph:
            continue
        # Find min-val node in bp.
        first_n = bp.sub_graph[0]
        min_val = state.nodes[first_n].val
        child_node = first_n
        parent_node = state.nodes[first_n].parent
        for n in bp.sub_graph[1:]:
            sv = state.nodes[n]
            if sv.val < min_val:
                min_val = sv.val
                child_node = n
                parent_node = sv.parent
        if parent_node is None:
            # Shouldn't happen for non-root blocks, but be
            # defensive — skip linkage.
            continue
        state.nodes[parent_node].is_parent = True
        bp.child = child_node
        # Engine compatibility: store ``parent_node`` (the
        # articulation point in the *parent* block, i.e.,
        # ``PARENT(CHILD(bp))`` in C) on the block so the
        # legacy positioning code can look it up by name.  C
        # accesses this via ``BLK_PARENT(b)`` =
        # ``PARENT(CHILD(b))`` which dereferences both blocks'
        # state at use site; we cache it here for clarity.
        bp.parent_anchor = parent_node
        # Append bp to its parent block's children.
        parent_block = state.nodes[parent_node].block
        if parent_block is not None:
            parent_block.children.append(bp)

    return root_block
