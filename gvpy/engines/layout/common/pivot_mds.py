"""Pivot MDS — classical multidimensional scaling restricted to a
pivot subspace.

Reference: Brandes & Pich, "Eigensolver Methods for Progressive
Multidimensional Scaling of Large Data" (2007).

This is the engine-agnostic kernel behind neato's smart-init.
The C reference (``lib/neatogen/stress.c::sparse_stress_subspace_
majorization_kD`` plus ``embed_graph.c`` and ``pca.c``) achieves
the same goal via:

1. High-Dimensional Embedding (HDE) — pick ``num_centers`` pivots
   uniformly spread across the graph using a farthest-point
   heuristic, then BFS / Dijkstra from each pivot.
2. PCA on the resulting ``num_centers``-dimensional embedding —
   power iteration on the centred Gram matrix.
3. Project the n-by-num_centers embedding down to ``dim`` D using
   the top eigenvectors.

PivotMDS is the analytical specialisation: instead of running
power iteration ourselves we delegate to ``np.linalg.eigh``, which
is O(K³) where K is the pivot count (≪ N for large graphs).  The
result is the same: each node lands on its top-``dim`` PCA
projection of the squared-distance-to-pivots matrix, with the
classical-MDS double-centering applied.

Used by neato (``neato.smart_ini``) and intended for future fdp /
sfdp ports.
"""
from __future__ import annotations

import math
import random

import numpy as np


def farthest_point_pivots(dist: list[list[float]], N: int,
                          n_pivots: int,
                          first: int | None = None) -> list[int]:
    """Pick ``n_pivots`` indices from 0..N-1 spread across the
    graph by the farthest-point heuristic.

    Mirrors ``stress.c:347-385``: the first pivot is random, each
    subsequent pivot is the node maximally far from any pivot
    already chosen.

    ``first`` overrides the random initial pivot (useful for
    deterministic test fixtures).
    """
    if n_pivots <= 0 or N == 0:
        return []
    n_pivots = min(n_pivots, N)

    if first is None:
        first = random.randrange(N)
    pivots = [first]
    # min_dist[i] = min over chosen pivots p of dist[p][i]
    min_dist = [dist[first][i] for i in range(N)]
    for _ in range(1, n_pivots):
        # Pick the node whose nearest existing pivot is furthest.
        # Ties broken by index (stable choice).
        best_i = -1
        best_d = -1.0
        for i in range(N):
            if i in pivots:
                continue
            if min_dist[i] > best_d:
                best_d = min_dist[i]
                best_i = i
        if best_i < 0:
            break
        pivots.append(best_i)
        for i in range(N):
            if dist[best_i][i] < min_dist[i]:
                min_dist[i] = dist[best_i][i]
    return pivots


def pivot_mds(dist: list[list[float]], N: int,
              n_pivots: int = 50,
              dim: int = 2,
              seed: int | None = None) -> np.ndarray:
    """Project the all-pairs distance matrix down to ``dim`` via
    PivotMDS.  Returns an ``N`` × ``dim`` ``np.ndarray`` of
    coordinates.

    Steps (Brandes & Pich):

    1. Pick ``n_pivots`` pivots via farthest-point.
    2. Build ``C = D[:, pivots]²`` — the squared distances from
       every node to each pivot (``N``-by-``K``).
    3. Double-centre ``C`` in classical-MDS form:
       ``B = -1/2 (C - row_mean - col_mean + grand_mean)``.
    4. Compute the top ``dim`` eigenvectors / values of ``B B^T``
       (an ``N``×``N`` matrix expressed implicitly as
       ``B @ B.T``; the small-eigendecomp trick turns it into the
       ``K``×``K`` matrix ``B^T @ B`` for efficiency).
    5. Coordinates = top eigenvectors scaled by ``sqrt(eigvals)``.

    For ``N <= dim + 1`` we fall back to a small jittered random
    placement — PivotMDS degenerates in that regime.
    """
    if N <= dim + 1:
        if seed is not None:
            rng = np.random.default_rng(seed)
        else:
            rng = np.random.default_rng()
        return rng.normal(scale=1.0, size=(N, dim))

    if seed is not None:
        random.seed(seed)
    n_pivots = min(n_pivots, N)
    pivots = farthest_point_pivots(dist, N, n_pivots)

    # C[i, k] = D[i, pivots[k]]² — row i is the squared distance
    # vector from node i to every pivot.
    C = np.empty((N, len(pivots)), dtype=np.float64)
    for k, p in enumerate(pivots):
        col = np.array(dist[p], dtype=np.float64)
        C[:, k] = col * col

    # Double-centring (classical MDS): B = -1/2 (I - 1/N J) C (I - 1/K J)
    # where J is the all-ones matrix.  Equivalent to subtracting row,
    # column, and grand means from the squared-distance matrix.
    row_mean = C.mean(axis=1, keepdims=True)   # per-node means
    col_mean = C.mean(axis=0, keepdims=True)   # per-pivot means
    grand = float(C.mean())
    B = -0.5 * (C - row_mean - col_mean + grand)

    # Top dim eigenvectors of B B^T via the small-eig trick:
    #   B B^T u = λ u
    # Let v = B^T u / sqrt(λ); then B^T B v = λ v
    # so the K×K matrix B^T B has the same non-zero eigenvalues.
    K = B.shape[1]
    if K >= dim:
        BtB = B.T @ B  # K × K
        eigvals, eigvecs = np.linalg.eigh(BtB)
        # eigh returns ascending; we want top dim.
        order = np.argsort(eigvals)[::-1][:dim]
        eigvals = eigvals[order]
        eigvecs = eigvecs[:, order]
        # u_i = B v_i / sqrt(λ_i); coordinate matrix has columns u_i × sqrt(λ_i) = B v_i.
        # That collapses to coords = B @ eigvecs (already scaled by sqrt(λ) implicitly via the
        # B v projection length).  Take the absolute eigenvalue for sign safety.
        scales = np.sqrt(np.maximum(eigvals, 0.0))
        coords = (B @ eigvecs) / np.where(scales > 1e-12, scales, 1.0)
        coords = coords * scales  # back to scaled form
    else:
        # Pivot count smaller than requested dim — pad with zeros.
        coords = np.zeros((N, dim), dtype=np.float64)
        if K > 0:
            BtB = B.T @ B
            eigvals, eigvecs = np.linalg.eigh(BtB)
            order = np.argsort(eigvals)[::-1]
            eigvals = eigvals[order]
            eigvecs = eigvecs[:, order]
            scales = np.sqrt(np.maximum(eigvals, 0.0))
            coords[:, :K] = ((B @ eigvecs) / np.where(scales > 1e-12, scales, 1.0)) * scales
    return coords
