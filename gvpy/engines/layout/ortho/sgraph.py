"""Port of ``lib/ortho/sgraph.{h,c}`` — sparse graph + Dijkstra shortest-path.

Each :class:`Snode` corresponds to a border segment between two adjacent
maze cells; each :class:`Sedge` is a possible transition with a weight.
The ortho router runs :func:`short_path` once per edge to find the
least-cost traversal across the maze.

Semantics track C verbatim (``lib/ortho/sgraph.c``):

- :func:`short_path` stores tentative distances negated so the max-heap
  in :mod:`gvpy.engines.layout.ortho.fpq` acts as a min-priority queue.
  When a node pops from the heap its ``n_val`` is flipped to positive,
  signalling "finalized".
- :func:`gsave` / :func:`reset` form a checkpoint-and-restore mechanism
  used by the ortho orchestrator: build the maze once, checkpoint,
  then for each edge route {add terminal nodes → shortPath → reset}.
- ``UNSEEN`` matches C's ``INT_MIN`` and is less than any real
  tentative distance so the ``N_VAL(adjn) == UNSEEN`` check picks out
  nodes that have never been added to the heap.
- Weights on :class:`Sedge` are ``float`` in C but the algorithm
  assigns ``d = -(int + double)`` back to ``int n_val``, implicitly
  truncating toward zero.  :func:`short_path` mirrors that truncation
  with an explicit :class:`int` cast.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.ortho import fpq
from gvpy.engines.layout.ortho.fpq import Pq

UNSEEN: int = -(2 ** 31)  # matches INT_MIN in the C port


@dataclass
class Snode:
    """Port of ``struct snode`` in ``sgraph.h``."""
    n_val: int = 0
    n_idx: int = 0
    n_dad: Optional["Snode"] = None
    n_edge: Optional["Sedge"] = None
    n_adj: int = 0
    save_n_adj: int = 0
    cells: list = field(default_factory=lambda: [None, None])
    adj_edge_list: list[int] = field(default_factory=list)
    index: int = 0
    is_vert: bool = False


@dataclass
class Sedge:
    """Port of ``struct sedge`` in ``sgraph.h``.

    :attr:`base_weight` is a GraphvizPy addition, not in the C struct.
    It caches the weight assigned at :func:`create_sedge` time so
    :mod:`ortho`'s cluster-avoidance layer can reset per-edge
    penalties between routing iterations without losing the original
    channel-width cost.  Phase 7+ — see TODO §5b for the design note.
    """
    weight: float = 0.0
    cnt: int = 0
    v1: int = 0
    v2: int = 0
    base_weight: float = 0.0


@dataclass
class Sgraph:
    """Port of ``sgraph`` in ``sgraph.h`` — vectors of snodes and sedges."""
    nnodes: int = 0
    nedges: int = 0
    save_nnodes: int = 0
    save_nedges: int = 0
    nodes: list[Snode] = field(default_factory=list)
    edges: list[Sedge] = field(default_factory=list)


def create_sgraph(nnodes: int) -> Sgraph:
    """``createSGraph`` — pre-allocate ``nnodes`` empty snode slots.

    C zero-fills via ``gv_calloc``; we pre-populate with default
    :class:`Snode` instances whose ``index`` will be assigned on
    :func:`create_snode`.  The ``nnodes`` field stays at 0 until
    :func:`create_snode` is called.
    """
    g = Sgraph(nnodes=0, nodes=[Snode() for _ in range(nnodes)])
    return g


def free_sgraph(g: Sgraph) -> None:
    """``freeSGraph`` — no-op under Python GC."""


def create_snode(g: Sgraph) -> Snode:
    """``createSNode`` — take the next pre-allocated slot, bump nnodes."""
    if g.nnodes >= len(g.nodes):
        # C would buffer-overrun here; raising is safer and still matches
        # the "caller must size create_sgraph correctly" contract.
        raise IndexError(
            f"create_snode: capacity {len(g.nodes)} exhausted"
        )
    np = g.nodes[g.nnodes]
    np.index = g.nnodes
    g.nnodes += 1
    return np


def create_sedge(g: Sgraph, v1: Snode, v2: Snode, wt: float) -> Sedge:
    """``createSEdge`` — append a new edge, hook into both endpoints."""
    idx = g.nedges
    g.nedges += 1
    e = Sedge(v1=v1.index, v2=v2.index, weight=wt, cnt=0, base_weight=wt)
    # C pre-allocates the edges array; Python grows on demand.
    if idx < len(g.edges):
        g.edges[idx] = e
    else:
        g.edges.append(e)
    _add_edge_to_node(v1, idx)
    _add_edge_to_node(v2, idx)
    return e


def init_sedges(g: Sgraph, maxdeg: int) -> None:
    """``initSEdges`` — reserve edges/adj capacity.

    C pre-allocates the ``edges`` array and per-node ``adj_edge_list``
    slots in a single contiguous block.  Python lists grow on demand,
    so this is a no-op semantically; the function is kept for API
    parity with the C port.  ``maxdeg`` is unused.
    """
    del maxdeg  # parity-only parameter


def gsave(g: Sgraph) -> None:
    """``gsave`` — snapshot node/edge counts + per-node adj-list length."""
    g.save_nnodes = g.nnodes
    g.save_nedges = g.nedges
    for i in range(g.nnodes):
        g.nodes[i].save_n_adj = g.nodes[i].n_adj


def reset(g: Sgraph) -> None:
    """``reset`` — restore to the most recent :func:`gsave` checkpoint.

    Truncates every per-node ``adj_edge_list`` back to its saved
    length, then zeroes adj on the +2 terminal slots that ortho's
    per-edge routing populates after ``gsave``.
    """
    g.nnodes = g.save_nnodes
    g.nedges = g.save_nedges
    for i in range(g.nnodes):
        node = g.nodes[i]
        node.n_adj = node.save_n_adj
        # Truncate in place so subsequent _add_edge_to_node appends
        # cleanly without leaving stale mid-list entries.
        del node.adj_edge_list[node.save_n_adj:]
    # C resets n_adj=0 on nodes[nnodes], nodes[nnodes+1] (the two
    # terminals allocated for the routing-pair).  In Python those
    # slots may or may not exist depending on whether create_snode
    # was called; clear whatever is there.
    for i in range(g.nnodes, min(g.nnodes + 2, len(g.nodes))):
        g.nodes[i].n_adj = 0
        g.nodes[i].adj_edge_list = []


def short_path(pq: Pq, g: Sgraph, from_: Snode, to: Snode) -> int:
    """``shortPath`` — Dijkstra from ``from_`` to ``to``.

    Writes results into each node: ``n_val`` holds the final distance
    (positive) or remains ``UNSEEN`` if unreachable; ``n_dad`` gives the
    predecessor for path reconstruction; ``n_edge`` gives the edge
    taken into the node.

    Returns 0 on success, 1 on heap overflow.
    """
    _emit_entry_trace(g, from_, to)

    for x in range(g.nnodes):
        g.nodes[x].n_val = UNSEEN

    fpq.pq_init(pq)
    if fpq.pq_insert(pq, from_):
        _emit_overflow_trace()
        return 1
    from_.n_dad = None
    from_.n_val = 0

    while True:
        n = fpq.pq_remove(pq)
        if n is None:
            break
        n.n_val *= -1
        if n is to:
            break
        for y in range(n.n_adj):
            e = g.edges[n.adj_edge_list[y]]
            adjn = _adjacent_node(g, e, n)
            if adjn.n_val < 0:
                d = int(-(n.n_val + e.weight))
                if adjn.n_val == UNSEEN:
                    adjn.n_val = d
                    if fpq.pq_insert(pq, adjn):
                        _emit_overflow_trace()
                        return 1
                    adjn.n_dad = n
                    adjn.n_edge = e
                else:
                    if adjn.n_val < d:
                        fpq.pq_update(pq, adjn, d)
                        adjn.n_dad = n
                        adjn.n_edge = e

    _emit_exit_trace(to)
    return 0


def _adjacent_node(g: Sgraph, e: Sedge, n: Snode) -> Snode:
    """Return the endpoint of ``e`` that is not ``n``."""
    if e.v1 == n.index:
        return g.nodes[e.v2]
    return g.nodes[e.v1]


def _add_edge_to_node(np: Snode, idx: int) -> None:
    """Append edge index ``idx`` to ``np``; bump ``n_adj``."""
    np.adj_edge_list.append(idx)
    np.n_adj += 1


# Gated diagnostics — channel ``ortho_sgraph``.  Were unconditionally
# printed before 2026-04-24.
def _emit_entry_trace(g: Sgraph, from_: Snode, to: Snode) -> None:
    from gvpy.engines.layout.dot.trace import trace_on, trace
    if trace_on("ortho_sgraph"):
        trace("ortho_sgraph",
              f"shortpath from={from_.index} to={to.index} "
              f"nnodes={g.nnodes} nedges={g.nedges}")


def _emit_exit_trace(to: Snode) -> None:
    from gvpy.engines.layout.dot.trace import trace_on, trace
    if not trace_on("ortho_sgraph"):
        return
    if to.n_val == UNSEEN:
        trace("ortho_sgraph", "shortpath result cost=UNREACHABLE path=")
        return
    path_indices: list[int] = []
    cursor: Optional[Snode] = to
    while cursor is not None:
        path_indices.append(cursor.index)
        cursor = cursor.n_dad
    path_indices.reverse()
    path_str = ",".join(str(i) for i in path_indices)
    trace("ortho_sgraph",
          f"shortpath result cost={to.n_val} path={path_str}")


def _emit_overflow_trace() -> None:
    from gvpy.engines.layout.dot.trace import trace_on, trace
    if trace_on("ortho_sgraph"):
        trace("ortho_sgraph", "shortpath result error=overflow")
