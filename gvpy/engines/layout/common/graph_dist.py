"""All-pairs shortest-path distance primitives shared across engines.

Mirrors Graphviz ``lib/neatogen/bfs.c`` and ``lib/neatogen/dijkstra.c``.
The neato wrappers (``neato/bfs.py`` / ``neato/dijkstra.py``) call
these and apply unit conversion (inches → points × 72).

The functions take a generic adjacency dict so any engine using
graph-theoretic distances can share them.
"""
from __future__ import annotations

import heapq
from collections import deque


def bfs_apsp_row(source: str,
                 node_idx: dict[str, int],
                 adj: dict[str, list[str]],
                 dist_row: list[float],
                 unit: float = 1.0) -> None:
    """Fill ``dist_row`` with BFS shortest-path distances from
    ``source`` to every node in ``node_idx`` (unweighted graph).

    ``unit`` scales each hop count (default 1.0 = raw hop count).
    Unreachable entries are left at their pre-existing value
    (typically a "default distance" sentinel set by the caller).
    """
    visited = {source}
    queue: deque[tuple[str, int]] = deque([(source, 0)])
    while queue:
        u, d = queue.popleft()
        ui = node_idx.get(u)
        if ui is not None:
            dist_row[ui] = d * unit
        for v in adj.get(u, ()):
            if v not in visited and v in node_idx:
                visited.add(v)
                queue.append((v, d + 1))


def dijkstra_apsp_row(source: str,
                      node_idx: dict[str, int],
                      adj: dict[str, list[str]],
                      edge_len: dict[tuple[str, str], float],
                      dist_row: list[float],
                      default_dist: float,
                      unit: float = 1.0) -> None:
    """Fill ``dist_row`` with Dijkstra shortest-path distances from
    ``source`` (weighted graph).

    ``edge_len`` is keyed by ``(min(u, v), max(u, v))``.
    ``unit`` scales each edge weight (default 1.0).
    Nodes unreachable from ``source`` are assigned ``default_dist``.
    """
    INF = float("inf")
    dist_map: dict[str, float] = {n: INF for n in node_idx}
    dist_map[source] = 0.0
    heap: list[tuple[float, str]] = [(0.0, source)]
    visited: set[str] = set()

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        for v in adj.get(u, ()):
            if v not in node_idx:
                continue
            pair = (min(u, v), max(u, v))
            w = edge_len.get(pair, 1.0) * unit
            nd = d + w
            if nd < dist_map.get(v, INF):
                dist_map[v] = nd
                heapq.heappush(heap, (nd, v))

    for n, i in node_idx.items():
        d = dist_map.get(n, default_dist)
        dist_row[i] = d if d < INF else default_dist
