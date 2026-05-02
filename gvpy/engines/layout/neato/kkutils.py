"""Neato Kamada-Kawai mode.

Mirrors the KK driver code from ``lib/neatogen/stuff.c``:

============================  ============================
Python function               C source
============================  ============================
``diffeq_model``              ``stuff.c::diffeq_model``    (line 341)
``solve_model``               ``stuff.c::solve_model``     (line 414)
``_choose_node``              ``stuff.c::choose_node``     (line 495)
``_move_node``                ``stuff.c::move_node``       (line 531)
``_update_arrays``            ``stuff.c::update_arrays``   (line 434)
``_D2E``                      ``stuff.c::D2E``             (line 461)
``total_energy``              ``stuff.c::total_e``         (line 390)
============================  ============================

(``kkutils.c`` itself contains only sort / distance utilities; the
module name is kept because per the §4.N scoping it absorbs both
``kkutils.c`` and ``stuff.c``'s KK helpers.)

Algorithm
---------
1. **Initialise springs** — ``K[i][j] = Spring_coeff / D[i][j]²``,
   modulated by per-edge ``ED_factor``.
2. **Initialise force tensors** — ``t[i][j][k] = K[i][j] * (del[k]
   - D[i][j] * del[k] / dist)``; row sums into ``sum_t[i][k]``.
3. **Iteration loop** — until ``max_i ||sum_t[i]||² < ε²`` OR
   ``MaxIter`` reached:

   a. ``choose_node`` — pick node with largest force magnitude.
   b. ``move_node`` — solve the local Newton system
      ``Hessian @ Δx = -sum_t[i]`` (size ``Ndim`` ≪ ``N``).
   c. Update ``t`` and ``sum_t`` for the moved node and its
      neighbours.

Trace tag: ``[TRACE neato_kk]``.
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import TYPE_CHECKING

import numpy as np

from gvpy.engines.layout.common.matrix import gauss_solve

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


# Mirrors ``Spring_coeff`` from ``lib/common/const.h:158`` (= 1.0).
_SPRING_COEFF = 1.0
_DIM = 2  # current Py is 2D-only


def _trace(msg: str) -> None:
    """Emit a ``[TRACE neato_kk]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_NEATO=1``)."""
    if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
        print(f"[TRACE neato_kk] {msg}", file=sys.stderr)


def _distvec(p0: np.ndarray, p1: np.ndarray) -> tuple[float, np.ndarray]:
    """Return (euclidean distance, per-axis delta)."""
    delta = p0 - p1
    dist = float(np.linalg.norm(delta))
    return dist, delta


def diffeq_model(coords: np.ndarray, dist: list[list[float]],
                 N: int, edge_factor: dict[tuple[int, int], float]
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Initialise spring constants and force tensors.

    Mirrors ``stuff.c::diffeq_model`` (line 341).  Returns
    ``(K, t, sum_t)``:

    - ``K[i][j]`` — spring constant ``Spring_coeff / D[i][j]²``,
      multiplied by per-edge ``ED_factor`` if an edge i-j exists.
    - ``t[i][j][k]`` — force on node i from node j along axis k.
    - ``sum_t[i][k]`` — total force on node i along axis k.

    All arrays are ``np.float64``.
    """
    K = np.zeros((N, N), dtype=np.float64)
    for i in range(N):
        for j in range(i):
            d = dist[i][j]
            if d <= 0:
                continue
            f = _SPRING_COEFF / (d * d)
            if (i, j) in edge_factor:
                f *= edge_factor[(i, j)]
            K[i, j] = f
            K[j, i] = f

    t = np.zeros((N, N, _DIM), dtype=np.float64)
    sum_t = np.zeros((N, _DIM), dtype=np.float64)

    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            d, delta = _distvec(coords[i], coords[j])
            if d < 1e-10:
                continue
            for k in range(_DIM):
                t[i, j, k] = K[i, j] * (
                    delta[k] - dist[i][j] * delta[k] / d
                )
                sum_t[i, k] += t[i, j, k]

    return K, t, sum_t


def _D2E(coords: np.ndarray, K: np.ndarray, dist: list[list[float]],
         N: int, n: int) -> list[float]:
    """Build the Ndim×Ndim local Hessian for node ``n``.

    Mirrors ``stuff.c::D2E`` (line 461).  Returns a flat row-major
    list of length ``Ndim²`` suitable for :func:`gauss_solve`.
    """
    M = [0.0] * (_DIM * _DIM)
    for i in range(N):
        if i == n:
            continue
        sq = 0.0
        t_local = [0.0] * _DIM
        for k in range(_DIM):
            t_local[k] = float(coords[n, k] - coords[i, k])
            sq += t_local[k] * t_local[k]
        if sq < 1e-20:
            continue
        scale = 1.0 / math.pow(sq, 1.5)
        kn_i_d_n_i = K[n, i] * dist[n][i]
        for k in range(_DIM):
            for l in range(k):
                M[l * _DIM + k] += (
                    kn_i_d_n_i * t_local[k] * t_local[l] * scale
                )
            M[k * _DIM + k] += K[n, i] * (
                1.0 - dist[n][i] * (sq - t_local[k] * t_local[k]) * scale
            )
    # Symmetrise
    for k in range(1, _DIM):
        for l in range(k):
            M[k * _DIM + l] = M[l * _DIM + k]
    return M


def _update_arrays(coords: np.ndarray, K: np.ndarray,
                   dist: list[list[float]], t: np.ndarray,
                   sum_t: np.ndarray, N: int, i: int) -> None:
    """Recompute force contributions involving node ``i``.

    Mirrors ``stuff.c::update_arrays`` (line 434).  Updates
    ``t[i][:]`` row, ``sum_t[i]``, plus the symmetric entries
    ``t[j][i]`` and the corresponding ``sum_t[j]`` deltas.
    """
    sum_t[i, :] = 0.0
    for j in range(N):
        if i == j:
            continue
        d, delta = _distvec(coords[i], coords[j])
        if d < 1e-10:
            continue
        for k in range(_DIM):
            new = K[i, j] * (delta[k] - dist[i][j] * delta[k] / d)
            t[i, j, k] = new
            sum_t[i, k] += new
            old = t[j, i, k]
            t[j, i, k] = -new
            sum_t[j, k] += -new - old


def _choose_node(sum_t: np.ndarray, pinned: list[bool],
                 N: int, eps2: float, max_iter: int,
                 move_count: int) -> int:
    """Return the index of the highest-force unpinned node, or -1
    if the residual is below ε² (converged) or ``max_iter`` reached.

    Mirrors ``stuff.c::choose_node`` (line 495).
    """
    if move_count >= max_iter:
        return -1
    max_m = 0.0
    choice = -1
    for i in range(N):
        if pinned[i]:
            continue
        m = float(np.dot(sum_t[i], sum_t[i]))
        if m > max_m:
            choice = i
            max_m = m
    if max_m < eps2:
        return -1
    return choice


def _move_node(coords: np.ndarray, K: np.ndarray,
               dist: list[list[float]], t: np.ndarray,
               sum_t: np.ndarray, N: int, n: int,
               damping: float) -> None:
    """Solve the local Newton step for node ``n`` and apply it.

    Mirrors ``stuff.c::move_node`` (line 531).  The damping factor
    follows the C convention: ``b = (Damping + 2 (1 - Damping) r) b``
    where ``r`` is uniform on [0, 1).
    """
    a = _D2E(coords, K, dist, N, n)
    c = [-float(sum_t[n, k]) for k in range(_DIM)]
    b = gauss_solve(a, c, _DIM)
    if b is None:
        return  # ill-conditioned — leave node in place
    for k in range(_DIM):
        bk = (damping + 2.0 * (1.0 - damping) * random.random()) * b[k]
        coords[n, k] += bk
    _update_arrays(coords, K, dist, t, sum_t, N, n)


def total_energy(coords: np.ndarray, K: np.ndarray,
                 dist: list[list[float]], N: int) -> float:
    """Twice the system energy ``E = sum w_ij (eucl - d_ij)²``.

    Mirrors ``stuff.c::total_e`` (line 390).
    """
    e = 0.0
    for i in range(N - 1):
        for j in range(i + 1, N):
            t0 = 0.0
            for k in range(_DIM):
                t1 = float(coords[i, k] - coords[j, k])
                t0 += t1 * t1
            e += K[i, j] * (
                t0 + dist[i][j] * dist[i][j]
                - 2.0 * dist[i][j] * math.sqrt(t0)
            )
    return e


def solve_model(coords: np.ndarray, K: np.ndarray, t: np.ndarray,
                sum_t: np.ndarray, dist: list[list[float]],
                N: int, pinned: list[bool],
                max_iter: int, epsilon: float,
                damping: float) -> int:
    """Run the KK iteration loop until convergence.

    Mirrors ``stuff.c::solve_model`` (line 414).  Returns the
    number of node-move steps taken.
    """
    eps2 = epsilon * epsilon
    move_count = 0
    while True:
        n = _choose_node(sum_t, pinned, N, eps2, max_iter, move_count)
        if n < 0:
            break
        _move_node(coords, K, dist, t, sum_t, N, n, damping)
        move_count += 1
    return move_count


def kamada_kawai(layout: "NeatoLayout",
                 node_list: list[str],
                 dist: list[list[float]],
                 N: int,
                 idx: dict[str, int]) -> None:
    """Public entry point for KK layout.

    Wires :func:`diffeq_model` (one-time spring + force init) into
    :func:`solve_model` (iteration loop), then writes the resulting
    coordinates back into the layout's ``LayoutNode`` records.
    """
    if N < 2:
        return

    # Coordinates as an N×Ndim numpy array.
    coords = np.array(
        [[layout.lnodes[name].x, layout.lnodes[name].y]
         for name in node_list],
        dtype=np.float64,
    )
    pinned = [layout.lnodes[name].pinned for name in node_list]

    # Edge-factor map keyed by (low_idx, high_idx) tuples.
    edge_factor: dict[tuple[int, int], float] = {}
    for edge in layout.graph.edges.values():
        a, b = edge.tail.name, edge.head.name
        if a not in idx or b not in idx:
            continue
        ia, ib = idx[a], idx[b]
        if ia == ib:
            continue
        if ia > ib:
            ia, ib = ib, ia
        try:
            wt = float(edge.attributes.get("weight", "1.0"))
        except ValueError:
            wt = 1.0
        edge_factor[(ib, ia)] = wt  # K accessed as K[i][j] with i>j

    K, t, sum_t = diffeq_model(coords, dist, N, edge_factor)

    _trace(f"start N={N} maxiter={layout.maxiter} "
           f"eps={layout.epsilon} damping={layout.damping} "
           f"pinned={sum(pinned)}")
    initial_energy = total_energy(coords, K, dist, N)
    _trace(f"initial total_e={initial_energy:.6g}")

    moves = solve_model(coords, K, t, sum_t, dist, N, pinned,
                        layout.maxiter, layout.epsilon, layout.damping)

    final_energy = total_energy(coords, K, dist, N)
    _trace(f"finish moves={moves} max={layout.maxiter} "
           f"final_e={final_energy:.6g}")

    for i, name in enumerate(node_list):
        layout.lnodes[name].x = float(coords[i, 0])
        layout.lnodes[name].y = float(coords[i, 1])
