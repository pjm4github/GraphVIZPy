"""Fdp Phase 1 — Fruchterman-Reingold force-directed placement.

Mirrors ``lib/fdpgen/tlayout.c``.  Iterative spring-electrical
model with linear cooling and grid-accelerated repulsive forces.

Per iteration:

1. Clear the displacement accumulator on each node.
2. Compute repulsive forces (grid-accelerated when ``use_grid``;
   all-pairs otherwise).
3. Compute attractive forces along each edge.
4. Cap each node's displacement by the current temperature and
   apply.

Temperature anneals linearly from ``T0`` to 0 over ``maxiter``
steps.

Trace tag: ``[TRACE fdp_tlayout]``.
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import Any

from gvpy.engines.layout.fdp.grid import build_grid, neighbour_offsets


# Mirrors ``EXPFACTOR`` from tlayout.c:96 — span multiplier for
# initial random placement.
_EXPFACTOR = 1.2
# Mirrors ``GRID_CELLS`` — cell side = grid_cells × K.
_GRID_CELLS = 3


def _trace(msg: str) -> None:
    """Emit a ``[TRACE fdp_tlayout]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_FDP=1``)."""
    if os.environ.get("GVPY_TRACE_FDP", "") == "1":
        print(f"[TRACE fdp_tlayout] {msg}", file=sys.stderr)


def init_positions(layout: Any, node_list: list[str],
                   K: float) -> None:
    """Set initial random positions in a square of side
    ``K (sqrt(N) + 1) EXPFACTOR``.

    Mirrors the random-init loop at ``tlayout.c`` (no-pos branch).
    Pinned / pos-set nodes are left alone.
    """
    N = len(node_list)
    span = K * (math.sqrt(N) + 1.0) * _EXPFACTOR
    for name in node_list:
        ln = layout.lnodes[name]
        if getattr(ln, "pos_set", False):
            continue
        ln.x = (random.random() - 0.5) * span
        ln.y = (random.random() - 0.5) * span


def _repel_pair(pa: Any, pb: Any, K2: float) -> None:
    """Apply repulsive force ``F = K² / dist²`` between two nodes.

    Equal and opposite — both displacement accumulators are
    updated.
    """
    dx = pb.x - pa.x
    dy = pb.y - pa.y
    dist2 = dx * dx + dy * dy
    if dist2 < 0.01:
        # Coincident or near-coincident: jitter one slightly so the
        # next iteration produces a meaningful force.
        dx = random.random() * 0.1
        dy = random.random() * 0.1
        dist2 = dx * dx + dy * dy
    dist = math.sqrt(dist2)
    force = K2 / (dist * dist2)
    fx = dx * force
    fy = dy * force
    pb.disp_x += fx
    pb.disp_y += fy
    pa.disp_x -= fx
    pa.disp_y -= fy


def all_pairs_repulsion(layout: Any, node_list: list[str],
                        K2: float) -> None:
    """O(N²) repulsive-force pass.  Used for small graphs or when
    ``use_grid`` is False."""
    n = len(node_list)
    for i in range(n):
        pi = layout.lnodes[node_list[i]]
        for j in range(i + 1, n):
            pj = layout.lnodes[node_list[j]]
            _repel_pair(pi, pj, K2)


def grid_repulsion(layout: Any, node_list: list[str], K2: float,
                   cell_size: float) -> None:
    """Grid-accelerated repulsive forces.

    Mirrors ``tlayout.c::doRep`` with the grid path.  Forces are
    only computed between nodes in the same cell or adjacent cells;
    nodes farther than ~one cell width contribute negligibly to the
    ``1/r²`` repulsion in practice.
    """
    grid = build_grid(node_list, layout.lnodes, cell_size)

    # Within-cell forces.
    for cell_nodes in grid.values():
        m = len(cell_nodes)
        for a in range(m):
            pa = layout.lnodes[cell_nodes[a]]
            for b in range(a + 1, m):
                pb = layout.lnodes[cell_nodes[b]]
                _repel_pair(pa, pb, K2)

    # Adjacent-cell forces (process each unordered pair once).
    processed: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    offsets = neighbour_offsets()
    for (ci, cj), cell_nodes in grid.items():
        for di, dj in offsets:
            nb_key = (ci + di, cj + dj)
            if nb_key not in grid:
                continue
            pair_key = (min((ci, cj), nb_key), max((ci, cj), nb_key))
            if pair_key in processed:
                continue
            processed.add(pair_key)
            for na in cell_nodes:
                pa = layout.lnodes[na]
                for nb in grid[nb_key]:
                    pb = layout.lnodes[nb]
                    _repel_pair(pa, pb, K2)


def apply_attraction(layout: Any, t_name: str, h_name: str,
                     edge_len: float, weight: float) -> None:
    """Apply the F-R attractive force along an edge.

    ``F_attr = weight × (dist - edge_len) / dist`` along the edge
    direction.  Pulls endpoints together when they're farther than
    ``edge_len``, pushes apart when closer.
    """
    pt = layout.lnodes[t_name]
    ph = layout.lnodes[h_name]
    dx = ph.x - pt.x
    dy = ph.y - pt.y
    dist = math.sqrt(dx * dx + dy * dy)
    if dist < 0.01:
        return
    force = weight * (dist - edge_len) / dist
    fx = dx * force
    fy = dy * force
    pt.disp_x += fx
    pt.disp_y += fy
    ph.disp_x -= fx
    ph.disp_y -= fy


def update_positions(layout: Any, node_list: list[str],
                     temp: float) -> None:
    """Apply each node's accumulated displacement, capped by temp.

    Pinned nodes are skipped.  Mirrors the position-update tail of
    the F-R inner loop in ``tlayout.c``.
    """
    for name in node_list:
        ln = layout.lnodes[name]
        if ln.pinned:
            continue
        dx = ln.disp_x
        dy = ln.disp_y
        disp_len = math.sqrt(dx * dx + dy * dy)
        if disp_len <= 0:
            continue
        if disp_len > temp:
            scale = temp / disp_len
            dx *= scale
            dy *= scale
        ln.x += dx
        ln.y += dy


def tlayout(layout: Any, node_list: list[str],
            comp_edges: list[tuple[str, str, float, float]],
            K: float, T0: float, maxiter: int,
            use_grid: bool = True) -> None:
    """Run the F-R force-directed iteration loop.

    ``comp_edges`` is a list of ``(tail, head, edge_len, weight)``
    tuples for the component being laid out.

    Mirrors ``tlayout.c::layoutSubGraph``.
    """
    K2 = K * K
    cell_size = _GRID_CELLS * K

    _trace(f"start N={len(node_list)} K={K:.2f} T0={T0:.2f} "
           f"maxiter={maxiter} use_grid={use_grid}")

    for iteration in range(maxiter):
        temp = T0 * (maxiter - iteration) / maxiter
        if temp <= 0:
            break

        # Reset displacements.
        for name in node_list:
            ln = layout.lnodes[name]
            ln.disp_x = 0.0
            ln.disp_y = 0.0

        # Repulsion.
        if use_grid and len(node_list) > 20:
            grid_repulsion(layout, node_list, K2, cell_size)
        else:
            all_pairs_repulsion(layout, node_list, K2)

        # Attraction along edges.
        for t, h, elen, wt in comp_edges:
            apply_attraction(layout, t, h, elen, wt)

        update_positions(layout, node_list, temp)

    _trace(f"finish iters={iteration + 1}")
