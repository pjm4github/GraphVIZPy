"""C-aligned port of ``lib/sfdpgen/post_process.c`` and
``lib/sfdpgen/stress_model.c``.

Stress-majorization smoothing for sfdp.  Runs after the
multilevel spring-electrical descent
(:mod:`gvpy.engines.layout.sfdp.spring_electrical`) when the
``smoothing`` graph attribute is set to ``avg_dist``,
``graph_dist``, ``power_dist`` (Gansner-Koren-North stress
majorization), or ``spring`` (single re-pass through the
spring-electrical solver with a tightened control struct).

Algorithm — stress majorization (Gansner-Koren-North 2005):

Minimize the stress functional

    F(x) = Σᵢⱼ wᵢⱼ · (‖xᵢ - xⱼ‖ - dᵢⱼ)²

where ``dᵢⱼ`` is the *ideal* distance between ``i`` and ``j``
and ``wᵢⱼ`` is the importance weight.  The C implementation
exposes three ``ideal_dist_scheme`` policies for ``dᵢⱼ``:

- ``IDEAL_GRAPH_DIST``: ``dᵢⱼ = 1`` for direct neighbours, ``2``
  for distance-2 neighbours.
- ``IDEAL_AVG_DIST``: ``dᵢⱼ = (avgDist[i] + avgDist[j]) / 2``
  where ``avgDist[i]`` is the mean current-Euclidean-distance to
  ``i``'s neighbours.
- ``IDEAL_POWER_DIST``: ``dᵢⱼ = ‖xᵢ - xⱼ‖^0.4``.

Each outer iteration linearises ``F`` around the current ``x``
into a quadratic form ``½·xᵀ·Lw·x - xᵀ·Lwd(x)·x + λ·‖x - x₀‖²``
and solves the resulting normal equations
``Lw · x_{k+1} = Lwd(x_k) · x_k + λ · x_0`` by conjugate gradient
(see :mod:`gvpy.engines.layout.sfdp.sparse_solve`).  The matrices:

- ``Lw``: Laplacian-like; ``Lw[i,j] = -1/dᵢⱼ²`` off-diag,
  ``Lw[i,i] = -Σⱼ Lw[i,j] + λᵢ``.  Constant across outer iters.
- ``Lwd``: distance-rescaled Laplacian; off-diag is rebuilt each
  outer iter as ``Lwd[i,j] = -wᵢⱼ · dᵢⱼ / ‖xᵢ - xⱼ‖`` (so the
  RHS bakes in the current geometry).

Convergence: ``‖x_{k+1} - x_k‖ / ‖x_k‖ < tol = 0.001`` or
``maxit_sm`` reached (50 by default).

Skipped from C (deliberate, scope-limited):

- **TriangleSmoother / RNG smoother** — depend on
  ``neatogen/call_tri.c`` (Delaunay triangulation), separate
  ~600 LOC port.  Smoothing modes ``rng`` / ``triangle`` are
  unwired in GraphvizPy anyway; we no-op for now and surface a
  one-line warning so users know we saw the attribute.
- **Edge label matrix** (``get_edge_label_matrix``,
  ``SM_SCHEME_NORMAL_ELABEL``) — requires
  ``relative_position_constraints`` data plumbing that
  GraphvizPy doesn't have yet.
- **SpringSmoother** — uses
  ``spring_electrical_spring_embedding`` (a separate C variant
  with both adjacency and distance matrices).  We approximate
  with a single re-pass through the existing C-aligned
  ``spring_electrical_embedding`` against the post-descent
  layout — this matches what the legacy Python code did and is
  what most users get when they set ``smoothing=spring``.
"""
from __future__ import annotations

import math
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import scipy.sparse as sp

from gvpy.engines.layout.sfdp.sparse_solve import sparse_matrix_solve


# ─────────────────────────────────────────────────────────────────
# Constants — mirror C ``post_process.h`` enums and limits
# ─────────────────────────────────────────────────────────────────

# Ideal-distance schemes (post_process.h:37).
IDEAL_GRAPH_DIST: int = 0
IDEAL_AVG_DIST: int = 1
IDEAL_POWER_DIST: int = 2

# Outer convergence tolerance (post_process.c:588).
_TOL_OUTER: float = 0.001

# Default outer iteration cap (post_process.c:1015).
_DEFAULT_MAXIT_SM: int = 50

# CG inner-loop tolerance for stress majorization
# (post_process.c:128).  Loose because the outer loop will
# re-form the RHS regardless.
_DEFAULT_TOL_CG: float = 0.01


def _trace(msg: str) -> None:
    if os.environ.get("GVPY_TRACE_SFDP", "") == "1":
        print(f"[TRACE sfdp_pp] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────
# Helpers — distances, ideal distance matrix, average node distance
# ─────────────────────────────────────────────────────────────────


def _distance(x: np.ndarray, i: int, j: int) -> float:
    """Plain Euclidean distance between rows ``i`` and ``j`` of x."""
    return float(np.linalg.norm(x[i] - x[j]))


def _distance_cropped(x: np.ndarray, i: int, j: int) -> float:
    """C ``distance_cropped`` — Euclidean distance, clamped to a
    small floor to avoid division by zero in stress weights."""
    d = float(np.linalg.norm(x[i] - x[j]))
    return max(d, 1.0e-9)


def _avg_neighbor_distances(A: sp.csr_matrix, x: np.ndarray) -> np.ndarray:
    """Per-node mean Euclidean distance to neighbours (post_process.c:138)."""
    n = A.shape[0]
    indptr = A.indptr
    indices = A.indices
    out = np.zeros(n, dtype=np.float64)
    for i in range(n):
        total = 0.0
        nz = 0
        for jj in range(indptr[i], indptr[i + 1]):
            j = int(indices[jj])
            if j == i:
                continue
            total += _distance(x, i, j)
            nz += 1
        if nz > 0:
            out[i] = total / nz
    return out


def _ideal_distance_matrix(
    A: sp.csr_matrix, x: np.ndarray
) -> sp.csr_matrix:
    """Symmetric-difference-based ideal distance matrix.

    Mirrors C ``ideal_distance_matrix`` (post_process.c:36).  For
    each edge ``(i, k)`` the ideal distance is

        |N(i) ∪ N(k)| - |N(i) ∩ N(k)|

    (degree-i + degree-k - 2 × shared-neighbours).  After
    populating, the entire matrix is rescaled so that the mean
    ideal distance equals the mean Euclidean distance — i.e. the
    layout's current scale is preserved.
    """
    n = A.shape[0]
    D = A.copy().astype(np.float64).tocsr()
    indptr = D.indptr
    indices = D.indices
    data = D.data

    mask = np.full(n, -1, dtype=np.int64)
    degrees = np.diff(indptr).astype(np.int64)

    for i in range(n):
        di = int(degrees[i])
        mask[i] = i
        for jj in range(indptr[i], indptr[i + 1]):
            k = int(indices[jj])
            if k == i:
                continue
            mask[k] = i
        for jj in range(indptr[i], indptr[i + 1]):
            k = int(indices[jj])
            if k == i:
                continue
            length = di + int(degrees[k])
            for ll in range(indptr[k], indptr[k + 1]):
                if mask[int(indices[ll])] == i:
                    length -= 1
            data[jj] = float(length)
            assert length > 0

    # Rescale so mean ideal distance == mean Euclidean distance.
    sum_eucl = 0.0
    sum_ideal = 0.0
    nz = 0
    for i in range(n):
        for jj in range(indptr[i], indptr[i + 1]):
            k = int(indices[jj])
            if k == i:
                continue
            nz += 1
            sum_eucl += _distance(x, i, k)
            sum_ideal += data[jj]
    if nz > 0 and sum_ideal > 0:
        s = (sum_eucl / nz) / (sum_ideal / nz)
        for jj in range(len(data)):
            data[jj] *= s

    return D


# ─────────────────────────────────────────────────────────────────
# StressMajorizationSmoother
# ─────────────────────────────────────────────────────────────────


@dataclass
class StressMajorizationSmoother:
    """One-shot smoother state.  Mirrors C
    ``StressMajorizationSmoother_struct`` (post_process.h:18).

    - ``Lw``: weighted Laplacian, off-diag = ``-1/dᵢⱼ²``.
    - ``Lwd``: distance-rescaled Laplacian, off-diag is rebuilt
      each outer iter as ``-wᵢⱼ · dᵢⱼ / ‖xᵢ - xⱼ‖``.
    - ``lambda_arr``: per-node penalty term anchoring ``x`` to
      its initial position.
    - ``scaling``: post-iteration coordinate divisor (so the
      output is in the same units as the input).
    - ``tol_cg``, ``maxit_cg``: inner CG controls.
    """

    Lw: sp.csr_matrix
    Lwd: sp.csr_matrix
    lambda_arr: np.ndarray
    scaling: float
    tol_cg: float = _DEFAULT_TOL_CG
    maxit_cg: int = 0  # filled in __post_init__-style by callers


# ─────────────────────────────────────────────────────────────────
# Builder: full version with distance-2 neighbours
# (post_process.c StressMajorizationSmoother2_new)
# ─────────────────────────────────────────────────────────────────


def stress_majorization_smoother2_new(
    A: sp.csr_matrix,
    x: np.ndarray,
    lambda0: float,
    ideal_dist_scheme: int,
) -> Optional[StressMajorizationSmoother]:
    """Build a stress-majorization smoother with distance-2
    coverage.

    Mirrors C ``StressMajorizationSmoother2_new``
    (post_process.c:108).  Includes both direct-neighbour edges
    (i, k) and distance-2 paths (i, k, l) in ``Lw`` / ``Lwd``,
    so even sparse graphs see meaningful constraints in the
    stress functional.

    Parameters
    ----------
    A : csr_matrix
        Symmetric adjacency.  Must be diagonal-free for the
        ideal-distance accounting to be correct (the C code
        asserts this implicitly via ``i == ja[j]`` skips).
    x : ndarray, shape (n, dim)
        Current layout — used to compute ``avg_dist`` and to
        seed the ``IDEAL_POWER_DIST`` ``‖xᵢ - xⱼ‖^0.4``
        formula.
    lambda0 : float
        Per-node penalty coefficient anchoring the smoothed
        layout to its initial position.
    ideal_dist_scheme : int
        One of :data:`IDEAL_GRAPH_DIST`, :data:`IDEAL_AVG_DIST`,
        :data:`IDEAL_POWER_DIST`.

    Returns
    -------
    StressMajorizationSmoother or None
        ``None`` if the rescaling factor ``s = stop / sbot``
        evaluates to 0 (no meaningful constraints — caller
        should skip smoothing).
    """
    m = A.shape[0]
    indptr = A.indptr
    indices = A.indices

    avg_dist = _avg_neighbor_distances(A, x)

    # First pass: count nz including distance-2 neighbours.  We
    # build Lw/Lwd as triplet lists since the per-row nz count is
    # data-dependent and not analytically tight.
    lw_rows: list[int] = []
    lw_cols: list[int] = []
    lw_vals: list[float] = []
    lwd_rows: list[int] = []
    lwd_cols: list[int] = []
    lwd_vals: list[float] = []

    lambda_arr = np.full(m, lambda0, dtype=np.float64)
    mask = np.full(m, -1, dtype=np.int64)
    stop = 0.0
    sbot = 0.0

    for i in range(m):
        mask[i] = i + m
        diag_d = 0.0
        diag_w = 0.0

        # Direct neighbours.
        for jj in range(indptr[i], indptr[i + 1]):
            k = int(indices[jj])
            if mask[k] != i + m:
                mask[k] = i + m

                if ideal_dist_scheme == IDEAL_GRAPH_DIST:
                    dist = 1.0
                elif ideal_dist_scheme == IDEAL_AVG_DIST:
                    dist = (avg_dist[i] + avg_dist[k]) * 0.5
                elif ideal_dist_scheme == IDEAL_POWER_DIST:
                    dist = _distance_cropped(x, i, k) ** 0.4
                else:
                    raise ValueError(
                        f"unknown ideal_dist_scheme={ideal_dist_scheme}"
                    )

                w = -1.0 / (dist * dist)
                lw_rows.append(i)
                lw_cols.append(k)
                lw_vals.append(w)
                diag_w += w

                d_off = w * dist
                lwd_rows.append(i)
                lwd_cols.append(k)
                lwd_vals.append(d_off)
                stop += d_off * _distance(x, i, k)
                sbot += d_off * dist
                diag_d += d_off

        # Distance-2 neighbours.
        for jj in range(indptr[i], indptr[i + 1]):
            k = int(indices[jj])
            for ll in range(indptr[k], indptr[k + 1]):
                lk = int(indices[ll])
                if mask[lk] != i + m:
                    mask[lk] = i + m

                    if ideal_dist_scheme == IDEAL_GRAPH_DIST:
                        dist = 2.0
                    elif ideal_dist_scheme == IDEAL_AVG_DIST:
                        dist = (
                            avg_dist[i] + 2.0 * avg_dist[k] + avg_dist[lk]
                        ) * 0.5
                    elif ideal_dist_scheme == IDEAL_POWER_DIST:
                        dist = _distance_cropped(x, i, lk) ** 0.4
                    else:
                        raise ValueError(
                            f"unknown ideal_dist_scheme={ideal_dist_scheme}"
                        )

                    w = -1.0 / (dist * dist)
                    lw_rows.append(i)
                    lw_cols.append(lk)
                    lw_vals.append(w)
                    diag_w += w

                    d_off = w * dist
                    lwd_rows.append(i)
                    lwd_cols.append(lk)
                    lwd_vals.append(d_off)
                    stop += d_off * _distance(x, lk, k)
                    sbot += d_off * dist
                    diag_d += d_off

        # Diagonal.
        lambda_arr[i] *= -diag_w
        lw_rows.append(i)
        lw_cols.append(i)
        lw_vals.append(-diag_w + lambda_arr[i])
        lwd_rows.append(i)
        lwd_cols.append(i)
        lwd_vals.append(-diag_d)

    if sbot == 0.0:
        return None
    s = stop / sbot
    Lw = sp.csr_matrix(
        (lw_vals, (lw_rows, lw_cols)), shape=(m, m), dtype=np.float64,
    )
    Lwd = sp.csr_matrix(
        (np.asarray(lwd_vals, dtype=np.float64) * s,
         (lwd_rows, lwd_cols)),
        shape=(m, m), dtype=np.float64,
    )
    return StressMajorizationSmoother(
        Lw=Lw, Lwd=Lwd,
        lambda_arr=lambda_arr,
        scaling=s,
        tol_cg=_DEFAULT_TOL_CG,
        maxit_cg=int(math.floor(math.sqrt(m))),
    )


# ─────────────────────────────────────────────────────────────────
# Builder: sparse variant for stress_model.c
# ─────────────────────────────────────────────────────────────────


def sparse_stress_majorization_smoother_new(
    A: sp.csr_matrix,
    x: np.ndarray,
    rng: Optional[random.Random] = None,
) -> Optional[StressMajorizationSmoother]:
    """Build a sparse stress-majorization smoother.

    Mirrors C ``SparseStressMajorizationSmoother_new``
    (post_process.c:309).  Used by ``stress_model.c`` —
    distances come straight from ``A.data`` (the input
    *adjacency* matrix is interpreted as a *distance* matrix),
    and the structure is unit-weighted.

    If ``x`` is all-zero, ``x`` is randomized to ``72 · drand()``
    in place (matches C behaviour).  If ``rng`` is None, uses
    ``random.random()`` directly.
    """
    m = A.shape[0]
    dim = x.shape[1]
    indptr = A.indptr
    indices = A.indices
    data = A.data

    # Match C: if x is all-zero, seed with 72 · uniform random.
    if not np.any(x):
        rand = (rng.random if rng is not None else random.random)
        for i in range(m):
            for k in range(dim):
                x[i, k] = 72.0 * rand()

    lw_rows: list[int] = []
    lw_cols: list[int] = []
    lw_vals: list[float] = []
    lwd_rows: list[int] = []
    lwd_cols: list[int] = []
    lwd_vals: list[float] = []
    lambda_arr = np.zeros(m, dtype=np.float64)
    stop = 0.0
    sbot = 0.0

    for i in range(m):
        diag_d = 0.0
        diag_w = 0.0
        for jj in range(indptr[i], indptr[i + 1]):
            k = int(indices[jj])
            if k == i:
                continue
            dist = float(data[jj])
            w = -1.0
            lw_rows.append(i)
            lw_cols.append(k)
            lw_vals.append(w)
            diag_w += w
            d_off = w * dist
            lwd_rows.append(i)
            lwd_cols.append(k)
            lwd_vals.append(d_off)
            stop += d_off * _distance(x, i, k)
            sbot += d_off * dist
            diag_d += d_off
        lambda_arr[i] *= -diag_w
        lw_rows.append(i)
        lw_cols.append(i)
        lw_vals.append(-diag_w + lambda_arr[i])
        lwd_rows.append(i)
        lwd_cols.append(i)
        lwd_vals.append(-diag_d)

    if sbot == 0.0:
        return None
    s = stop / sbot
    if s == 0.0:
        return None
    Lw = sp.csr_matrix(
        (lw_vals, (lw_rows, lw_cols)), shape=(m, m), dtype=np.float64,
    )
    Lwd = sp.csr_matrix(
        (np.asarray(lwd_vals, dtype=np.float64) * s,
         (lwd_rows, lwd_cols)),
        shape=(m, m), dtype=np.float64,
    )
    return StressMajorizationSmoother(
        Lw=Lw, Lwd=Lwd,
        lambda_arr=lambda_arr,
        scaling=s,
        tol_cg=_DEFAULT_TOL_CG,
        maxit_cg=int(math.floor(math.sqrt(m))),
    )


# ─────────────────────────────────────────────────────────────────
# Outer iteration
# ─────────────────────────────────────────────────────────────────


def stress_majorization_smoother_smooth(
    sm: StressMajorizationSmoother,
    x: np.ndarray,
    maxit_sm: int = _DEFAULT_MAXIT_SM,
    rng: Optional[random.Random] = None,
) -> float:
    """Run the outer fixed-point iteration.

    Mirrors C ``StressMajorizationSmoother_smooth``
    (post_process.c:579).  Modifies ``x`` in place.  Returns the
    final relative-displacement ``‖x_k+1 - x_k‖ / ‖x_k‖``.

    Each iteration:

    1. **Rebuild Lwdd**: copy ``sm.Lwd``'s structure, then
       rescale each off-diagonal entry by ``1/‖xᵢ - xⱼ‖`` (the
       current geometry's reciprocal).  The diagonal becomes
       ``-Σⱼ off-diag``.  C calls this matrix ``Lwdd`` and treats
       it as the per-iteration RHS multiplier.
    2. **Compute RHS**: ``y = Lwdd · x + λ · x_0``.
    3. **Solve** ``Lw · x' = y`` via CG (loose tolerance).
    4. **Convergence check**: ``‖x' - x‖ / ‖x‖``.
    5. **Update**: ``x = x'``.

    The "perturbation" branch (post_process.c:639-645) is
    important: when two nodes coincide exactly, ``1/dist`` would
    blow up, so we nudge the second node by a small random
    amount proportional to the ideal distance.
    """
    m = sm.Lw.shape[0]
    dim = x.shape[1]
    Lw = sm.Lw
    Lwd = sm.Lwd
    lambda_arr = sm.lambda_arr

    # Snapshot for the lambda·x_0 anchor term.
    x0 = x.copy()
    if rng is None:
        rng = random.Random(123)

    Lw_csr = Lw.tocsr()
    Lwd_csr = Lwd.tocsr()
    Lw_indptr = Lw_csr.indptr
    Lw_indices = Lw_csr.indices
    Lw_data = Lw_csr.data
    Lwd_indptr = Lwd_csr.indptr
    Lwd_indices = Lwd_csr.indices

    iter_count = 0
    diff = 1.0
    tol = _TOL_OUTER

    # Working buffer for Lwdd.data — same sparsity as Lwd, but
    # off-diag entries get rescaled each iter.  We keep one
    # writable copy so the C-style "modify in place" pattern is
    # visible.
    Lwdd_data = Lwd_csr.data.copy()

    while iter_count < maxit_sm and diff > tol:
        iter_count += 1

        # 1. Rebuild Lwdd off-diags with current x.
        for i in range(m):
            idiag = -1
            diag = 0.0
            for jj in range(Lwd_indptr[i], Lwd_indptr[i + 1]):
                j = int(Lwd_indices[jj])
                if j == i:
                    idiag = jj
                    continue

                dist = _distance(x, i, j)
                d_orig = float(Lwd_csr.data[jj])
                # Find the matching entry in Lw to recover wᵢⱼ.
                # Lw and Lwd share off-diagonal sparsity per
                # design (post_process.c:282-294 builds them in
                # lockstep), so position jj indexes both.
                w = float(Lw_data[jj])
                if d_orig == 0.0:
                    Lwdd_data[jj] = 0.0
                else:
                    if dist == 0.0:
                        # Perturb to break the degeneracy.
                        ideal = d_orig / w  # negative/negative → positive
                        for k in range(dim):
                            x[j, k] += 0.0001 * (rng.random() + 0.0001) * ideal
                        dist = _distance(x, i, j)
                    Lwdd_data[jj] = d_orig / dist
                diag += Lwdd_data[jj]
            assert idiag >= 0
            Lwdd_data[idiag] = -diag

        # Build the per-iter Lwdd as a CSR sharing structure.
        Lwdd = sp.csr_matrix(
            (Lwdd_data.copy(), Lwd_csr.indices, Lwd_csr.indptr),
            shape=Lwd_csr.shape,
        )

        # 2. RHS: y = Lwdd · x + λ · x_0.
        y = np.asarray(Lwdd @ x)
        if lambda_arr is not None:
            y += lambda_arr[:, None] * x0

        # 3. Solve Lw · x' = y; sparse_matrix_solve writes the
        # solution back into y.
        sparse_matrix_solve(
            Lw_csr, x, y,
            tol=sm.tol_cg, maxit=sm.maxit_cg,
        )
        # After the call, ``y`` holds ``x'``.

        # 4. Convergence: ‖x' - x‖ / ‖x‖ (C's metric).
        delta = float(np.sum(np.linalg.norm(y - x, axis=1)))
        x_norm = math.sqrt(float(np.sum(x * x)))
        diff = delta / x_norm if x_norm > 0 else 1.0

        # 5. Update.
        x[:] = y

        _trace(
            f"iter={iter_count} diff={diff:.6f} maxit={maxit_sm}"
        )

    return diff


# ─────────────────────────────────────────────────────────────────
# stress_model.c port
# ─────────────────────────────────────────────────────────────────


def stress_model(
    A: sp.csr_matrix,
    x: np.ndarray,
    maxit_sm: int = _DEFAULT_MAXIT_SM,
    rng: Optional[random.Random] = None,
) -> int:
    """Pure stress majorization on the input distance matrix.

    Mirrors C ``stress_model`` (stress_model.c:10).  Used by neato
    when ``mode=major``; we expose it for completeness so any
    engine can call into the smoother directly.

    The input ``A`` is interpreted as a *distance* matrix:
    ``A[i,j]`` is the desired Euclidean distance between ``i``
    and ``j`` (NOT a weight).  After the smoother runs, we
    rescale ``x`` by ``1/scaling`` so the output is in the same
    units as the input distances.

    Returns 0 on success, -1 if the smoother couldn't be built.
    """
    sm = sparse_stress_majorization_smoother_new(A, x, rng=rng)
    if sm is None:
        return -1
    sm.tol_cg = 0.1
    stress_majorization_smoother_smooth(sm, x, maxit_sm=maxit_sm, rng=rng)
    if sm.scaling != 0.0:
        x /= sm.scaling
    return 0


# ─────────────────────────────────────────────────────────────────
# Entry point: post_process_smoothing
# ─────────────────────────────────────────────────────────────────


# Smoothing modes (subset of ``spring_electrical.h`` enum, lower-
# cased for the GraphvizPy attribute convention).  Maps to the
# integer values C uses in ``ctrl.smoothing``.
_SMOOTHING_MODES: dict[str, int] = {
    "none": 0,
    "graph_dist": 1,   # SMOOTHING_STRESS_MAJORIZATION_GRAPH_DIST
    "avg_dist": 2,     # SMOOTHING_STRESS_MAJORIZATION_AVG_DIST
    "power_dist": 3,   # SMOOTHING_STRESS_MAJORIZATION_POWER_DIST
    "spring": 4,       # SMOOTHING_SPRING
    "triangle": 5,     # SMOOTHING_TRIANGLE — unwired
    "rng": 6,          # SMOOTHING_RNG — unwired
}


def post_process_smoothing(
    A: sp.csr_matrix,
    smoothing: str,
    x: np.ndarray,
    *,
    rng: Optional[random.Random] = None,
    spring_re_run: Optional[callable] = None,
) -> None:
    """Dispatch entry point.  Mirrors C ``post_process_smoothing``
    (post_process.c:974).

    Modifies ``x`` in place.

    Parameters
    ----------
    A : csr_matrix
        Symmetric, diagonal-free adjacency.
    smoothing : str
        One of ``none``, ``graph_dist``, ``avg_dist``,
        ``power_dist``, ``spring``, ``triangle``, ``rng``.
    x : ndarray, shape (n, dim)
        Current layout.  Modified in place.
    rng : random.Random, optional
        For the perturbation branch in the inner iteration.
    spring_re_run : callable, optional
        Callback for the ``spring`` mode — takes ``x`` and
        returns nothing (modifies in place).  Implementations
        typically rerun ``multilevel_spring_electrical_embedding``
        with ``ctrl.maxiter=20``, ``ctrl.step/=2``,
        ``ctrl.random_start=False``.  C bundles this in
        ``SpringSmoother_new`` / ``SpringSmoother_smooth``.
    """
    mode = _SMOOTHING_MODES.get(smoothing.lower(), 0)
    if mode == 0:
        return
    if mode in (1, 2, 3):
        scheme = {
            1: IDEAL_GRAPH_DIST,
            2: IDEAL_AVG_DIST,
            3: IDEAL_POWER_DIST,
        }[mode]
        sm = stress_majorization_smoother2_new(
            A, x, lambda0=0.05, ideal_dist_scheme=scheme,
        )
        if sm is None:
            _trace("smoothing skipped — stress smoother declined to build")
            return
        stress_majorization_smoother_smooth(sm, x, rng=rng)
    elif mode == 4:
        if spring_re_run is not None:
            spring_re_run(x)
        else:
            _trace("smoothing=spring requested but no spring_re_run "
                   "callback provided; skipping")
    elif mode in (5, 6):
        # Triangle / RNG: depend on a Delaunay triangulator that
        # we haven't ported.  Surface a one-line warning and
        # return — non-fatal.
        print(
            f"[gvpy.sfdp.post_process] smoothing={smoothing!r} requires "
            f"the triangulation port (call_tri.c); skipping.",
            file=sys.stderr,
        )
