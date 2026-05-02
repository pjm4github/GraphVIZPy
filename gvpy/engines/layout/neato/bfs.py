"""Neato BFS APSP wrapper.

Mirrors ``lib/neatogen/bfs.c``.  Thin layer over
``common.graph_dist.bfs_apsp_row`` that applies the inches → points
unit conversion neato uses for its distance matrix.
"""
from __future__ import annotations

from gvpy.engines.layout.common.graph_dist import bfs_apsp_row

# Graphviz convention: 72 points per inch.
POINTS_PER_INCH = 72.0


def bfs_distances(source: str,
                  node_idx: dict[str, int],
                  adj: dict[str, list[str]],
                  dist_row: list[float]) -> None:
    """BFS shortest-path distances from ``source``, in points."""
    bfs_apsp_row(source, node_idx, adj, dist_row, unit=POINTS_PER_INCH)
