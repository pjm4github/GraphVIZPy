"""Neato stress-majorization mode.

Mirrors ``lib/neatogen/stress.c``.  Currently implements a basic
SMACOF (Scaling by MAjorizing a COmplicated Function) update; will
be aligned to ``stress_majorization_kD_mkernel`` in Phase N2.1.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from gvpy.engines.layout.common.matrix import gauss_jordan_inverse
from gvpy.engines.layout.neato.bfs import POINTS_PER_INCH

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


def compute_stress(cx: list[float], cy: list[float],
                   dist: list[list[float]],
                   w: list[list[float]], N: int) -> float:
    """Compute stress: ``sum w[i][j] * (d[i][j] - eucl_dist)^2``.

    Mirrors ``compute_stress`` in ``lib/neatogen/stress.c``.
    """
    stress = 0.0
    for i in range(N):
        for j in range(i + 1, N):
            dx = cx[i] - cx[j]
            dy = cy[i] - cy[j]
            eucl = math.sqrt(dx * dx + dy * dy)
            diff = dist[i][j] - eucl
            stress += w[i][j] * diff * diff
    return stress


def stress_majorization(layout: "NeatoLayout",
                        node_list: list[str],
                        dist: list[list[float]],
                        N: int,
                        idx: dict[str, int]) -> None:
    """Stress majorization via weighted Laplacian solving.

    Port of ``stress_majorization_kD_mkernel`` from ``stress.c``.
    Uses the SMACOF algorithm: iteratively solve
    ``L_w * X = L_Z(X) * X``.
    """
    w = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(N):
            if i != j and dist[i][j] > 0:
                w[i][j] = 1.0 / (dist[i][j] * dist[i][j])

    Lw_diag = [0.0] * N
    for i in range(N):
        for j in range(N):
            if i != j:
                Lw_diag[i] += w[i][j]

    cx = [layout.lnodes[node_list[i]].x for i in range(N)]
    cy = [layout.lnodes[node_list[i]].y for i in range(N)]
    pinned = [layout.lnodes[node_list[i]].pinned for i in range(N)]

    old_stress = compute_stress(cx, cy, dist, w, N)

    for _iteration in range(layout.maxiter):
        new_cx = [0.0] * N
        new_cy = [0.0] * N

        for i in range(N):
            if pinned[i]:
                new_cx[i] = cx[i]
                new_cy[i] = cy[i]
                continue
            if Lw_diag[i] < 1e-10:
                new_cx[i] = cx[i]
                new_cy[i] = cy[i]
                continue

            sx, sy = 0.0, 0.0
            for j in range(N):
                if i == j or w[i][j] == 0:
                    continue
                dx = cx[i] - cx[j]
                dy = cy[i] - cy[j]
                eucl = math.sqrt(dx * dx + dy * dy)
                if eucl < 1e-10:
                    cx[i] += random.random() * 0.1
                    cy[i] += random.random() * 0.1
                    eucl = 0.1

                ratio = dist[i][j] / eucl
                sx += w[i][j] * (cx[j] + ratio * dx)
                sy += w[i][j] * (cy[j] + ratio * dy)

            new_cx[i] = sx / Lw_diag[i]
            new_cy[i] = sy / Lw_diag[i]

        cx = new_cx
        cy = new_cy

        new_stress = compute_stress(cx, cy, dist, w, N)

        if (old_stress > 0
                and abs(new_stress - old_stress) < layout.epsilon * old_stress):
            break
        old_stress = new_stress

    for i, name in enumerate(node_list):
        layout.lnodes[name].x = cx[i]
        layout.lnodes[name].y = cy[i]


def circuit_distances(layout: "NeatoLayout",
                      nodes: set[str],
                      adj: dict[str, list[str]],
                      edge_len: dict[tuple[str, str], float]
                      ) -> list[list[float]]:
    """Effective-resistance distances for the circuit model.

    Mirrors ``lib/neatogen/circuit.c``.  Builds the conductance
    Laplacian, inverts the (n-1)x(n-1) reduced matrix (grounding
    the last node), and reads off pairwise effective resistance.
    Falls back to the shortest-path model on singular matrices.
    """
    node_list = [n for n in layout.node_list if n in nodes]
    N = len(node_list)
    idx = {n: i for i, n in enumerate(node_list)}

    G = [[0.0] * N for _ in range(N)]
    for pair, length in edge_len.items():
        u, v = pair
        if u not in idx or v not in idx:
            continue
        i, j = idx[u], idx[v]
        conductance = 1.0 / max(length, 0.001)
        G[i][j] -= conductance
        G[j][i] -= conductance
        G[i][i] += conductance
        G[j][j] += conductance

    if N <= 1:
        return [[0.0]]

    M = N - 1
    Gr = [[G[i][j] for j in range(M)] for i in range(M)]

    Gi = gauss_jordan_inverse(Gr)
    if Gi is None:
        # Singular — caller falls back to shortest-path.
        from gvpy.engines.layout.neato.neato_layout import _compute_distances
        return _compute_distances(layout, nodes, adj, edge_len)

    dist = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(i + 1, N):
            ii = min(i, M - 1)
            jj = min(j, M - 1)
            if i < M and j < M:
                r = abs(Gi[ii][ii] + Gi[jj][jj] - 2 * Gi[ii][jj])
            elif i < M:
                r = abs(Gi[ii][ii])
            elif j < M:
                r = abs(Gi[jj][jj])
            else:
                r = 0.0
            d = math.sqrt(max(r, 0.0)) * POINTS_PER_INCH
            dist[i][j] = d
            dist[j][i] = d

    return dist
