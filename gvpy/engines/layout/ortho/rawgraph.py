"""Port of ``lib/ortho/rawgraph.{h,c}``.

Simple directed adjacency-list graph used by the ortho channel router
to build per-channel interference graphs and topologically sort them
(``assignTracks`` in ``ortho.c``).  Semantics track the C verbatim:

- :func:`insert_edge` is idempotent (dedups via :func:`edge_exists`).
- :func:`remove_redge` removes ``v1 -> v2`` AND ``v2 -> v1``
  (bidirectional; the "redge" in the C name = relation edge).
- :func:`edge_exists` tests ``v1 -> v2`` only (directed).
- :func:`top_sort` uses DFS with SCANNING/SCANNED coloring; each
  vertex's ``topsort_order`` is 0 for topological root(s), increasing
  downstream.  Cycles are not detected — matches C's silent behavior.

Adjacency lists preserve insertion order.  DFS visits children in that
order, so Python and C produce the same topsort given identical
insertion sequences.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

UNSCANNED = 0
SCANNING = 1
SCANNED = 2


@dataclass
class Vertex:
    """Port of ``vertex`` in ``rawgraph.h``."""
    color: int = UNSCANNED
    topsort_order: int = 0
    adj_list: list[int] = field(default_factory=list)


@dataclass
class Rawgraph:
    """Port of ``rawgraph`` in ``rawgraph.h`` — array of vertices."""
    nvs: int = 0
    vertices: list[Vertex] = field(default_factory=list)


def make_graph(n: int) -> Rawgraph:
    """``rawgraph.c::make_graph`` — n vertices, 0 edges, all UNSCANNED."""
    return Rawgraph(nvs=n, vertices=[Vertex() for _ in range(n)])


def free_graph(g: Rawgraph) -> None:
    """``rawgraph.c::free_graph`` — no-op under Python GC; kept for parity."""


def insert_edge(g: Rawgraph, v1: int, v2: int) -> None:
    """Insert directed edge ``v1 -> v2``; idempotent.  ``rawgraph.c:41``."""
    if not edge_exists(g, v1, v2):
        g.vertices[v1].adj_list.append(v2)


def remove_redge(g: Rawgraph, v1: int, v2: int) -> None:
    """Remove any edge between v1 and v2 (both directions).

    Port of ``rawgraph.c:47``.  C's ``LIST_REMOVE`` removes every
    occurrence, so mirror that here.
    """
    _remove_all(g.vertices[v1].adj_list, v2)
    _remove_all(g.vertices[v2].adj_list, v1)


def edge_exists(g: Rawgraph, v1: int, v2: int) -> bool:
    """Test directed edge ``v1 -> v2``.  ``rawgraph.c:52``."""
    return v2 in g.vertices[v1].adj_list


def top_sort(g: Rawgraph) -> None:
    """Topologically sort ``g``; write result to each vertex's
    ``topsort_order``.  Port of ``rawgraph.c::top_sort``.

    DFS from every UNSCANNED vertex, pushing each on a stack at its
    SCANNED transition.  Popping the stack produces forward
    topological order (roots first, order = 0, 1, ...).  The C ``time``
    counter is only used internally for debugging and is dropped here.
    """
    if g.nvs == 0:
        _emit_topsort_trace(g)
        return
    if g.nvs == 1:
        g.vertices[0].topsort_order = 0
        _emit_topsort_trace(g)
        return

    sp: list[int] = []
    for i in range(g.nvs):
        if g.vertices[i].color == UNSCANNED:
            _dfs_visit(g, i, sp)

    count = 0
    while sp:
        v = sp.pop()
        g.vertices[v].topsort_order = count
        count += 1

    _emit_topsort_trace(g)


def _dfs_visit(g: Rawgraph, v: int, sp: list[int]) -> None:
    """DFS from ``v``; push onto ``sp`` at SCANNED transition."""
    vp = g.vertices[v]
    vp.color = SCANNING
    for nid in vp.adj_list:
        if g.vertices[nid].color == UNSCANNED:
            _dfs_visit(g, nid, sp)
    vp.color = SCANNED
    sp.append(v)


def _remove_all(lst: list[int], value: int) -> None:
    """Remove every occurrence of ``value`` from ``lst``, preserving order."""
    lst[:] = [x for x in lst if x != value]


def _emit_topsort_trace(g: Rawgraph) -> None:
    order = ",".join(str(v.topsort_order) for v in g.vertices)
    print(f"[TRACE ortho-rawgraph] topsort n={g.nvs} order={order}",
          file=sys.stderr)
