"""Neato Dijkstra APSP wrapper.

Mirrors ``lib/neatogen/dijkstra.c``.  Thin layer over
``common.graph_dist.dijkstra_apsp_row`` that applies the inches →
points unit conversion neato uses for its distance matrix.
"""
from __future__ import annotations

from gvpy.engines.layout.common.graph_dist import dijkstra_apsp_row

POINTS_PER_INCH = 72.0


def dijkstra_distances(source: str,
                       node_idx: dict[str, int],
                       adj: dict[str, list[str]],
                       edge_len: dict[tuple[str, str], float],
                       dist_row: list[float],
                       default_dist: float) -> None:
    """Dijkstra shortest-path distances from ``source``, in points."""
    dijkstra_apsp_row(source, node_idx, adj, edge_len, dist_row,
                      default_dist, unit=POINTS_PER_INCH)
