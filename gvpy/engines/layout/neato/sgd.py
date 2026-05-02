"""Neato stochastic gradient descent mode.

Mirrors ``lib/neatogen/sgd.c`` (the ``sgd`` function at line 142).
Term-based stress descent with exponential learning-rate annealing.

Algorithm
---------
For each pair (i, j) with graph-theoretic distance ``d_ij``, build
a stress term ``(i, j, d_ij, w_ij)`` with ``w_ij = 1/d_ij²``.  Each
iteration:

1. Fisher-Yates shuffle the term list (Python's ``random.shuffle``
   is FY internally).
2. ``eta = eta_max * exp(-lambda * t)`` — exponential anneal.
3. For each term:

   - ``mu = min(eta * w_ij, 1.0)``           (step cap — sgd.c:221)
   - ``dx = pos_i - pos_j``                  (i-to-j relative)
   - ``r  = mu * (mag - d_ij) / (2 * mag)``  (sgd.c:227)
   - apply ``pos_i -= r * d``, ``pos_j += r * d`` to unpinned nodes.

The step cap at ``mu = 1.0`` is the key SGD stabiliser: without it,
early iterations with very large ``eta * w`` can fling nodes
arbitrarily far.

Trace tag: ``[TRACE neato_sgd]``.
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


def _trace(msg: str) -> None:
    """Emit a ``[TRACE neato_sgd]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_NEATO=1``)."""
    if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
        print(f"[TRACE neato_sgd] {msg}", file=sys.stderr)


def calculate_stress(cx: list[float], cy: list[float],
                     terms: list[tuple[int, int, float, float]]) -> float:
    """Compute total stress over all terms.

    Mirrors ``calculate_stress`` (sgd.c:17).  Used for diagnostics;
    the iteration loop itself doesn't need to evaluate stress.
    """
    s = 0.0
    for i, j, d, w in terms:
        dx = cx[i] - cx[j]
        dy = cy[i] - cy[j]
        r = math.hypot(dx, dy) - d
        s += w * r * r
    return s


def sgd(layout: "NeatoLayout",
        node_list: list[str],
        dist: list[list[float]],
        N: int,
        idx: dict[str, int],
        edge_len: dict[tuple[str, str], float]) -> None:
    """Term-based SGD with exponential learning-rate anneal.

    Port of ``sgd()`` from ``lib/neatogen/sgd.c:142``.
    """
    # Build stress terms — only include unpinned-pair terms with
    # positive distance.  C extracts these via dijkstra_sgd; we get
    # the same list from the dense distance matrix already passed in.
    pinned = [layout.lnodes[node_list[i]].pinned for i in range(N)]
    terms: list[tuple[int, int, float, float]] = []
    for i in range(N):
        if pinned[i]:
            continue
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

    # Annealing schedule (sgd.c:184-195).
    w_min = min(t[3] for t in terms)
    w_max = max(t[3] for t in terms)
    # C: eta_max = 1/w_min ; eta_min = Epsilon/w_max ; lambda = log(...)/(MaxIter-1)
    eta_max = 1.0 / max(w_min, 1e-30)
    eta_min = layout.epsilon / max(w_max, 1e-30)
    # Defensive: if eta_min >= eta_max the schedule degenerates.  C has
    # no equivalent guard but its Epsilon default (0.01) keeps the ratio
    # safely positive on real inputs; we only intervene when it doesn't.
    if eta_max <= eta_min:
        eta_max = eta_min * 10.0
    lam = math.log(eta_max / max(eta_min, 1e-30)) / max(layout.maxiter - 1, 1)

    _trace(f"start N={N} terms={len(terms)} maxiter={layout.maxiter} "
           f"eta_max={eta_max:.4g} eta_min={eta_min:.4g} "
           f"lambda={lam:.4g} pinned={sum(pinned)}")
    initial_stress = calculate_stress(cx, cy, terms)
    _trace(f"initial stress={initial_stress:.6g}")

    for iteration in range(layout.maxiter):
        # Fisher-Yates shuffle (sgd.c:217); Python's random.shuffle is FY.
        random.shuffle(terms)
        eta = eta_max * math.exp(-lam * iteration)

        for i, j, d, w in terms:
            mu = min(eta * w, 1.0)            # step cap (sgd.c:221)

            dx = cx[i] - cx[j]                # i-to-j relative
            dy = cy[i] - cy[j]
            mag = math.hypot(dx, dy)
            if mag < 1e-30:
                continue                       # coincident: skip

            r = mu * (mag - d) / (2.0 * mag)  # sgd.c:227
            r_x = r * dx
            r_y = r * dy

            if not pinned[i]:
                cx[i] -= r_x
                cy[i] -= r_y
            if not pinned[j]:
                cx[j] += r_x
                cy[j] += r_y

        if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
            s = calculate_stress(cx, cy, terms)
            _trace(f"iter={iteration} eta={eta:.4g} stress={s:.6g}")

    final_stress = calculate_stress(cx, cy, terms)
    _trace(f"finish iters={layout.maxiter} final_stress={final_stress:.6g}")

    for i, name in enumerate(node_list):
        layout.lnodes[name].x = cx[i]
        layout.lnodes[name].y = cy[i]
