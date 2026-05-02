"""Neato Kamada-Kawai mode.

Mirrors ``lib/neatogen/kkutils.c`` (KK utilities) and
``lib/neatogen/solve.c`` (the per-node Newton solver invoked by
``solve_model``).  Phase N2.2 will align this with the C
diffeq_model + solve_model driver; the current implementation
moves one node per iteration toward equilibrium.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


def kamada_kawai(layout: "NeatoLayout",
                 node_list: list[str],
                 dist: list[list[float]],
                 N: int,
                 idx: dict[str, int]) -> None:
    """Kamada-Kawai gradient descent layout.

    Port of ``kkNeato`` / ``solve_model`` from the C neatogen
    library (placeholder implementation — to be replaced with the
    diff-eq solver in Phase N2.2).
    """
    k = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(N):
            if i != j and dist[i][j] > 0:
                k[i][j] = 1.0 / (dist[i][j] * dist[i][j])

    cx = [layout.lnodes[node_list[i]].x for i in range(N)]
    cy = [layout.lnodes[node_list[i]].y for i in range(N)]
    pinned = [layout.lnodes[node_list[i]].pinned for i in range(N)]

    for _iteration in range(layout.maxiter):
        max_force = 0.0
        max_node = -1

        for i in range(N):
            if pinned[i]:
                continue
            fx, fy = 0.0, 0.0
            for j in range(N):
                if i == j:
                    continue
                dx = cx[i] - cx[j]
                dy = cy[i] - cy[j]
                eucl = math.sqrt(dx * dx + dy * dy)
                if eucl < 1e-10:
                    eucl = 1e-10
                force = k[i][j] * (eucl - dist[i][j]) / eucl
                fx += force * dx
                fy += force * dy

            force_mag = math.sqrt(fx * fx + fy * fy)
            if force_mag > max_force:
                max_force = force_mag
                max_node = i

        if max_force < layout.epsilon or max_node < 0:
            break

        i = max_node
        fx, fy = 0.0, 0.0
        fxx, fxy, fyy = 0.0, 0.0, 0.0

        for j in range(N):
            if i == j:
                continue
            dx = cx[i] - cx[j]
            dy = cy[i] - cy[j]
            eucl = math.sqrt(dx * dx + dy * dy)
            if eucl < 1e-10:
                eucl = 1e-10
            eucl3 = eucl * eucl * eucl

            kij = k[i][j]
            dij = dist[i][j]

            fx += kij * (dx - dij * dx / eucl)
            fy += kij * (dy - dij * dy / eucl)
            fxx += kij * (1.0 - dij * dy * dy / eucl3)
            fxy += kij * (dij * dx * dy / eucl3)
            fyy += kij * (1.0 - dij * dx * dx / eucl3)

        det = fxx * fyy - fxy * fxy
        if abs(det) < 1e-10:
            continue

        move_x = (-fx * fyy + fy * fxy) / det
        move_y = (fx * fxy - fy * fxx) / det

        cx[i] += move_x * layout.damping
        cy[i] += move_y * layout.damping

    for i, name in enumerate(node_list):
        layout.lnodes[name].x = cx[i]
        layout.lnodes[name].y = cy[i]
