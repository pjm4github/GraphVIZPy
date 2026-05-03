"""Grid-based spatial index for fdp force computation.

Mirrors ``lib/fdpgen/grid.c``.  Bins nodes into uniform cells of
size ``cell_size = grid_cells × K``; repulsive forces are computed
between nodes in the same cell and between adjacent cells only,
giving an O(N) average vs the O(N²) all-pairs approach.

Engine-agnostic: any object with ``x`` / ``y`` attributes can be
binned.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable


def build_grid(node_names: Iterable[str], lnodes: dict,
               cell_size: float
               ) -> dict[tuple[int, int], list[str]]:
    """Bucket nodes into a grid of cells of size ``cell_size``.

    Mirrors ``grid.c::adjustGrid``.  Returns a dict keyed by
    ``(cell_i, cell_j)`` with the list of node names in each cell.
    """
    grid: dict[tuple[int, int], list[str]] = defaultdict(list)
    for name in node_names:
        ln = lnodes[name]
        ci = int(math.floor(ln.x / cell_size))
        cj = int(math.floor(ln.y / cell_size))
        grid[(ci, cj)].append(name)
    return grid


def neighbour_offsets() -> list[tuple[int, int]]:
    """Return the 8 neighbour-cell offsets (Moore neighbourhood,
    excluding (0, 0) which is the cell itself)."""
    return [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1)
            if not (di == 0 and dj == 0)]
