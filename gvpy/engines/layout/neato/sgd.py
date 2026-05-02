"""Neato stochastic gradient descent mode.

Mirrors ``lib/neatogen/sgd.c``.  Uses the term-shuffling SGD with
exponential learning-rate annealing.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


def sgd(layout: "NeatoLayout",
        node_list: list[str],
        dist: list[list[float]],
        N: int,
        idx: dict[str, int],
        edge_len: dict[tuple[str, str], float]) -> None:
    """Stochastic gradient descent layout.

    Port of ``sgd()`` from ``lib/neatogen/sgd.c``.
    """
    terms: list[tuple[int, int, float, float]] = []
    for i in range(N):
        for j in range(i + 1, N):
            d = dist[i][j]
            if d <= 0:
                continue
            w = 1.0 / (d * d)
            terms.append((i, j, d, w))

    if not terms:
        return

    cx = [layout.lnodes[node_list[i]].x for i in range(N)]
    cy = [layout.lnodes[node_list[i]].y for i in range(N)]
    pinned = [layout.lnodes[node_list[i]].pinned for i in range(N)]

    w_min = min(t[3] for t in terms)
    w_max = max(t[3] for t in terms)
    eta_max = 1.0 / max(w_min, 1e-10)
    eta_min = layout.epsilon / max(w_max, 1e-10)
    if eta_max <= eta_min:
        eta_max = eta_min * 10

    lam = math.log(eta_max / max(eta_min, 1e-10)) / max(layout.maxiter - 1, 1)

    for iteration in range(layout.maxiter):
        eta = eta_max * math.exp(-lam * iteration)

        random.shuffle(terms)

        for i, j, d, w in terms:
            dx = cx[j] - cx[i]
            dy = cy[j] - cy[i]
            eucl = math.sqrt(dx * dx + dy * dy)
            if eucl < 1e-10:
                eucl = 1e-10

            delta = (d - eucl) / eucl
            step = eta * w * delta * 0.5

            if not pinned[i]:
                cx[i] -= step * dx
                cy[i] -= step * dy
            if not pinned[j]:
                cx[j] += step * dx
                cy[j] += step * dy

    for i, name in enumerate(node_list):
        layout.lnodes[name].x = cx[i]
        layout.lnodes[name].y = cy[i]
