"""Neato stress-majorization mode.

Mirrors ``lib/neatogen/stress.c::stress_majorization_kD_mkernel``
(the default neato algorithm — selected by ``mode=major``).

Algorithm
---------
Stress majorization minimises

    stress(X) = sum_{i<j} w_{ij} (||x_i - x_j|| - d_{ij})^2

where ``d_{ij}`` are graph-theoretic distances (BFS / Dijkstra) and
``w_{ij} = 1 / d_{ij}^2``.  The SMACOF approach majorises the
non-convex stress with a quadratic upper bound

    F(X, Z) = sum w_{ij} d_{ij}^2 + tr(X^T L_w X) - 2 tr(X^T L_Z(X) Z)

which is solved per-iteration by the linear system

    L_w X^{new} = L_Z(X^{old}) X^{old}

The C reference solves this with conjugate gradient on packed
Laplacians.  Each spatial dimension is solved independently.

Trace tag: ``[TRACE neato_major]``.

Phase N2.4 will add the smart-init via subspace majorization
(``sparse_stress_subspace_majorization_kD``); for now the seed is
random (set in ``neato_layout._initialize_positions``).
"""
from __future__ import annotations

import math
import os
import sys
from typing import TYPE_CHECKING

import numpy as np

from gvpy.engines.layout.common.conjgrad import conjugate_gradient_mkernel
from gvpy.engines.layout.common.laplacian import (
    packed_index,
    packed_length,
    right_mult_packed,
)
from gvpy.engines.layout.common.matrix import gauss_jordan_inverse
from gvpy.engines.layout.neato.bfs import POINTS_PER_INCH

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


# CG tolerance — mirrors ``tolerance_cg`` from C neatogen.
_CG_TOLERANCE = 1e-3
_DIM = 2  # current Py is 2D-only; kD parameterisation deferred


def _trace(msg: str) -> None:
    """Emit a ``[TRACE neato_major]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_NEATO=1``)."""
    if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
        print(f"[TRACE neato_major] {msg}", file=sys.stderr)


def _build_constant_laplacian(dist: list[list[float]],
                              N: int) -> np.ndarray:
    """Build the constant Laplacian ``L_w`` of weights
    ``w_{ij} = 1 / d_{ij}^2`` in packed upper-triangular form.

    Mirrors the constant-Laplacian construction at stress.c:947-970:
    ``lap2`` is initialised with the inverted-and-squared distances,
    then the diagonal entries are filled with the negative sum of
    the off-diagonals on each row.
    """
    L = packed_length(N)
    lap = np.zeros(L, dtype=np.float64)

    # Off-diagonals: -1/d_ij^2 (Laplacians use negated weights for
    # off-diagonal so the diagonal is positive).
    for i in range(N - 1):
        for j in range(i + 1, N):
            d = dist[i][j]
            if d <= 0:
                continue
            w = 1.0 / (d * d)
            lap[packed_index(N, i, j)] = -w

    # Diagonals: degrees[i] = -sum of off-diagonals in row i and column i.
    degrees = np.zeros(N, dtype=np.float64)
    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            ii, jj = (i, j) if i < j else (j, i)
            degrees[i] += -lap[packed_index(N, ii, jj)]

    for i in range(N):
        lap[packed_index(N, i, i)] = degrees[i]

    return lap


def _build_iteration_laplacian(coords: list[np.ndarray],
                               dist: list[list[float]],
                               N: int) -> np.ndarray:
    """Build the per-iteration Laplacian ``L_Z(X)`` whose entries
    are ``w_{ij} / ||x_i - x_j||`` (= ``1 / (d_{ij} * eucl)``) in
    packed form.

    Mirrors the lap1 construction at stress.c:997-1045.
    """
    L = packed_length(N)
    lap = np.zeros(L, dtype=np.float64)

    degrees = np.zeros(N, dtype=np.float64)
    for i in range(N - 1):
        # squared euclidean distances from i to i+1..N-1
        eucl_sq = np.zeros(N - i - 1, dtype=np.float64)
        for k in range(_DIM):
            diff = coords[k][i] - coords[k][i + 1:]
            eucl_sq += diff * diff
        # 1/eucl
        with np.errstate(divide="ignore", invalid="ignore"):
            inv_eucl = np.where(eucl_sq > 0, 1.0 / np.sqrt(eucl_sq), 0.0)

        for jj, j in enumerate(range(i + 1, N)):
            d = dist[i][j]
            if d <= 0:
                continue
            # w_{ij} / eucl  (the "1/(d_ij * eucl)" form because the
            # Laplacian here represents L_Z(X) for the SMACOF step)
            v = -inv_eucl[jj] / d
            if not math.isfinite(v):
                v = 0.0
            lap[packed_index(N, i, j)] = v
            degrees[i] += -v
            degrees[j] += -v

    for i in range(N):
        lap[packed_index(N, i, i)] = degrees[i]

    return lap


def compute_stress(cx: list[float] | np.ndarray,
                   cy: list[float] | np.ndarray,
                   dist: list[list[float]],
                   w: list[list[float]] | None,
                   N: int) -> float:
    """Pairwise stress sum.

    Mirrors ``compute_stressf`` in ``stress.c``.  ``w`` is optional;
    when ``None`` we recompute ``1 / d_{ij}^2`` inline.  Used for
    diagnostics; the iteration loop itself derives stress from
    inner products against the Laplacians (see :func:`_iter_stress`).
    """
    stress = 0.0
    for i in range(N):
        for j in range(i + 1, N):
            d = dist[i][j]
            if d <= 0:
                continue
            wij = w[i][j] if w is not None else 1.0 / (d * d)
            dx = cx[i] - cx[j]
            dy = cy[i] - cy[j]
            eucl = math.sqrt(dx * dx + dy * dy)
            diff = d - eucl
            stress += wij * diff * diff
    return stress


def _iter_stress(coords: list[np.ndarray],
                 b: list[np.ndarray],
                 lap2: np.ndarray,
                 N: int,
                 constant_term: float) -> float:
    """Compute stress via inner products against the Laplacians.

    Borg-Groenen SMACOF derivation with proper-Laplacian sign
    convention (off-diagonals negative, diagonal = positive
    row-sum):

        stress = const + <X, V X> - 2 <X, B(X) X>
               = const + <X, lap2 X> - 2 <X, b>

    where ``b = lap1 @ X``.  Mirrors stress.c:1056-1065 — the C
    reference uses NEGATED Laplacians (opposite sign convention),
    so its formula reads as ``const + 2 <X, b> - <X, lap2 X>``;
    the two forms are equivalent under the corresponding sign
    flips.
    """
    s = constant_term
    for k in range(_DIM):
        # +<X, lap2 X>
        tmp = right_mult_packed(lap2, N, coords[k])
        s += float(np.dot(coords[k], tmp))
        # -2 <X, b>
        s -= 2.0 * float(np.dot(coords[k], b[k]))
    return s


def stress_majorization(layout: "NeatoLayout",
                        node_list: list[str],
                        dist: list[list[float]],
                        N: int,
                        idx: dict[str, int]) -> None:
    """Stress majorization with conjugate-gradient inner solver.

    Port of ``stress_majorization_kD_mkernel`` (stress.c:795-1124).

    The previous implementation was a naive O(N²) per-iteration
    SMACOF direct update; this version solves the per-iteration
    Laplacian system via CG on a packed symmetric matrix, matching
    C's behaviour and convergence rate.
    """
    if N < 2:
        return

    # Constant Laplacian L_w = w_{ij} = 1/d_ij^2.  Built once.
    lap2 = _build_constant_laplacian(dist, N)

    # Constant term in the stress sum: sum_{i<j} w_{ij} d_{ij}^2.
    # With w_{ij} = 1/d_{ij}^2 this collapses to the count of
    # non-zero pairs (= n*(n-1)/2 for a complete distance matrix).
    constant_term = 0.0
    pair_count = 0
    for i in range(N):
        for j in range(i + 1, N):
            if dist[i][j] > 0:
                constant_term += 1.0
                pair_count += 1

    # Coordinate vectors per dim.
    coords = [
        np.array([layout.lnodes[node_list[i]].x for i in range(N)],
                 dtype=np.float64),
        np.array([layout.lnodes[node_list[i]].y for i in range(N)],
                 dtype=np.float64),
    ]
    pinned = [layout.lnodes[node_list[i]].pinned for i in range(N)]
    have_pinned = any(pinned)

    _trace(f"start N={N} pairs={pair_count} maxiter={layout.maxiter} "
           f"eps={layout.epsilon} pinned={sum(pinned)}")

    old_stress = float("inf")
    new_stress = old_stress

    for iteration in range(layout.maxiter):
        # Per-iteration Laplacian L_Z(X).
        lap1 = _build_iteration_laplacian(coords, dist, N)

        # Right-hand side: b[k] = lap1 @ coords[k]
        b = [right_mult_packed(lap1, N, coords[k]) for k in range(_DIM)]

        # Stress derived from inner products (see C ref lines 1054-1065).
        new_stress = _iter_stress(coords, b, lap2, N, constant_term)

        if iteration > 0 and old_stress > 0:
            change = abs(old_stress - new_stress)
            converged = (change / old_stress < layout.epsilon
                         or new_stress < layout.epsilon)
            _trace(f"iter={iteration} stress={new_stress:.6g} "
                   f"change={change:.6g} converged={converged}")
            if converged:
                old_stress = new_stress
                break
        else:
            _trace(f"iter={iteration} stress={new_stress:.6g} (initial)")

        old_stress = new_stress

        # Per-axis CG solve: lap2 @ coords_new[k] = b[k]
        for k in range(_DIM):
            if have_pinned:
                tmp = coords[k].copy()
                rv = conjugate_gradient_mkernel(
                    lap2, tmp, b[k], N, _CG_TOLERANCE, N)
                if rv < 0:
                    return
                # Only overwrite non-pinned positions
                for i in range(N):
                    if not pinned[i]:
                        coords[k][i] = tmp[i]
            else:
                rv = conjugate_gradient_mkernel(
                    lap2, coords[k], b[k], N, _CG_TOLERANCE, N)
                if rv < 0:
                    return

    # Write back
    for i, name in enumerate(node_list):
        layout.lnodes[name].x = float(coords[0][i])
        layout.lnodes[name].y = float(coords[1][i])

    _trace(f"finish iters≤{layout.maxiter} final_stress={new_stress:.6g}")


def circuit_distances(layout: "NeatoLayout",
                      nodes: set[str],
                      adj: dict[str, list[str]],
                      edge_len: dict[tuple[str, str], float]
                      ) -> list[list[float]]:
    """Effective-resistance distances for the circuit model.

    Mirrors ``lib/neatogen/circuit.c``.  Builds the conductance
    Laplacian, inverts the (n-1)×(n-1) reduced matrix (grounding
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
