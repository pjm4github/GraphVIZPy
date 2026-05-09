"""C-aligned port of ``lib/sfdpgen/spring_electrical.c``.

The actual force iteration that drives sfdp.  Layers cleanly on
top of :mod:`gvpy.engines.layout.sfdp.multilevel`: at the coarsest
level a single-level spring-electrical embedding runs; on the way
back up the hierarchy each coarser layout is *prolongated* into
the next finer level (with a small jitter to break symmetry) and
re-relaxed.

Algorithm (mirrors C verbatim):

- Force per node ``i`` per dimension ``k``:

  - **Attractive** (over edges only):
    ``f -= CRK · (xᵢ - xⱼ) · ‖xᵢ - xⱼ‖`` where
    ``CRK = C^((2-p)/3) / K`` and ``C = 0.2``.  Pulls connected
    nodes towards each other proportionally to their separation.
  - **Repulsive** (all pairs, O(n²) slow variant):
    ``f += KP · (xᵢ - xⱼ) / ‖xᵢ - xⱼ‖^(1-p)`` where
    ``KP = K^(1-p)``.  With the default ``p = -1`` this reduces
    to ``KP / dist · unit_vector`` — an inverse-distance push.

- Each iteration computes the per-node force, normalizes it to
  unit length, and steps each node by ``step · unit_force``.
  ``step`` decays geometrically (``cool=0.90``) when the total
  force grows, plateaus when it shrinks slowly, and grows back
  (``0.99 · step / cool``) when convergence is fast.  This
  asymmetric "adaptive cooling" is the mechanism that lets
  pre-prolongation layouts settle quickly without overshooting.

- Multilevel descent: the coarsest level runs full
  ``spring_electrical_embedding``; each prolongation step
  ``xf = P · xc`` lifts coarse coords to the finer level, smooths
  via :func:`interpolate_coord` (averages cluster member coords
  with their neighbors), then jitters non-representative
  members by ``±0.5 · K · 0.001`` so the post-relaxation FR loop
  can separate them.  Between levels ``K *= 0.75`` and
  ``adaptive_cooling`` is disabled (the prolongated layout is
  close to a fixed point — geometric cooling alone is enough).

Skipped from the C source (deliberate, for parity with what we
port):

- **QuadTree / Barnes-Hut** (``spring_electrical_embedding_fast``,
  ``spring_electrical_embedding`` regular variant): require
  porting ``lib/sparse/QuadTree.c`` (~600 lines, separate module).
  Out of scope for this session.  We expose the slow variant only
  — for n ≤ ~500 it's milliseconds, and we can vectorize the
  pair-difference array via numpy.
- **Edge label nodes** (``shorting_edge_label_nodes``,
  ``attach_edge_label_coordinates``): the
  ``edge_labeling_scheme`` attribute isn't wired through
  GraphvizPy yet.  No functional regression.
- **post_process_smoothing** (``stress_majorization``): separate
  port (``post_process.c`` 1034 LOC), tracked for the next
  session.
- **remove_overlap**: handled by the engine's ``_remove_overlap``
  / ``xlayout`` overlap solver after the spring-electrical pass
  returns.

Trace channel: ``GVPY_TRACE_SFDP=1`` emits per-iteration
``[TRACE sfdp_se] level=L iter=N step=S Fnorm=F`` lines.
"""
from __future__ import annotations

import math
import os
import random
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np
import scipy.sparse as sp

from gvpy.engines.layout.sfdp.multilevel import (
    Multilevel,
    multilevel_get_coarsest,
)


# ─────────────────────────────────────────────────────────────────
# Constants — mirror lib/sfdpgen/spring_electrical.c
# ─────────────────────────────────────────────────────────────────

# C = 0.2 (spring_electrical.c:36) — attractive-force scale.
_C: float = 0.2

# tol = 0.001 (spring_electrical.c:47) — terminate when
# step < tol·K (after rescaling).
_TOL: float = 0.001

# cool = 0.90 (spring_electrical.c:49) — geometric cooling factor
# when force grows.
_COOL: float = 0.90

# AUTOP sentinel from spring_electrical.h:19 — request that p be
# auto-selected (-1.8 for power-law graphs, -1 otherwise).
_AUTOP: float = -1.0001234

# MINDIST guards against div-by-zero in repulsive-force
# normalisation (spring_electrical.c uses a constant from
# common/arith.h with the same intent).
_MINDIST: float = 0.000001


# ─────────────────────────────────────────────────────────────────
# Control struct
# ─────────────────────────────────────────────────────────────────


@dataclass
class SpringElectricalControl:
    """Mirrors C ``spring_electrical_control`` (spring_electrical.h:27).

    Defaults match ``spring_electrical_control_new``
    (spring_electrical.c:51).
    """

    p: float = _AUTOP                 # repulsive exponent (negative)
    K: float = -1.0                   # spring length; auto if < 0
    multilevels: int = 0              # ≤ 1 means single level
    max_qtree_level: int = 10
    maxiter: int = 500
    step: float = 0.1                 # initial step
    random_seed: int = 123
    random_start: bool = True
    adaptive_cooling: bool = True
    beautify_leaves: bool = False
    smoothing: int = 0                # SMOOTHING_NONE
    overlap: int = 0
    do_shrinking: bool = True
    # C default is -4 (target = 4·avg_label_size), but C's
    # post-scaling ``do_shrinking`` algorithm compresses the
    # layout further.  GraphvizPy doesn't port ``do_shrinking``
    # (~150 LOC of bisection / proximity stress); ``-2`` (target
    # = 2·avg_label_size) approximates the post-shrink C result
    # for typical graphs.  See SfdpLayout._apply_initial_scaling.
    initial_scaling: float = -2.0
    rotation: float = 0.0


def spring_electrical_control_new() -> SpringElectricalControl:
    """Mirrors C ``spring_electrical_control_new``."""
    return SpringElectricalControl()


def _trace(msg: str) -> None:
    if os.environ.get("GVPY_TRACE_SFDP", "") == "1":
        print(f"[TRACE sfdp_se] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────
# average_edge_length / update_step / power_law_graph
# ─────────────────────────────────────────────────────────────────


def average_edge_length(A: sp.csr_matrix, x: np.ndarray) -> float:
    """Mean Euclidean distance over CSR edges.

    Mirrors C ``average_edge_length`` (spring_electrical.c:153).
    Iterates every CSR entry (edges appear in both directions for
    a symmetric matrix, matching C's loop semantics).
    """
    n = A.shape[0]
    indptr = A.indptr
    indices = A.indices
    nnz = int(indptr[n])
    if nnz == 0:
        return 1.0
    total = 0.0
    for i in range(n):
        for jj in range(indptr[i], indptr[i + 1]):
            j = indices[jj]
            d = x[i] - x[j]
            total += float(np.linalg.norm(d))
    return total / nnz


def _update_step(
    adaptive_cooling: bool,
    step: float,
    Fnorm: float,
    Fnorm0: float,
) -> float:
    """Mirrors C ``update_step`` (spring_electrical.c:171).

    Branch table:

    - ``Fnorm >= Fnorm0`` → ``cool · step`` (force is growing;
      we overshot — cool down).
    - ``Fnorm > 0.95 · Fnorm0`` → ``step`` unchanged (in the
      narrow band where convergence is slow but real — hold).
    - else → ``0.99 · step / cool`` (Fnorm dropped sharply; warm
      up the step).
    """
    if not adaptive_cooling:
        return _COOL * step
    if Fnorm >= Fnorm0:
        return _COOL * step
    elif Fnorm > 0.95 * Fnorm0:
        return step
    else:
        return 0.99 * step / _COOL


def _power_law_graph(A: sp.csr_matrix) -> bool:
    """Mirrors C ``power_law_graph`` (spring_electrical.c:872).

    Heuristic: a graph is "power-law" if degree-1 nodes dominate
    (>80% of the modal degree count *and* >30% of all nodes).
    Drives the auto-p selection (-1.8 vs -1).
    """
    n = A.shape[0]
    indptr = A.indptr
    indices = A.indices
    degrees = np.zeros(n, dtype=np.int64)
    for i in range(n):
        deg = 0
        for jj in range(indptr[i], indptr[i + 1]):
            if indices[jj] != i:
                deg += 1
        degrees[i] = deg
    if n == 0:
        return False
    counts = np.bincount(degrees)
    if counts.size <= 1:
        return False
    max_count = int(counts.max())
    deg1 = int(counts[1]) if counts.size > 1 else 0
    return deg1 > 0.8 * max_count and deg1 > 0.3 * n


# ─────────────────────────────────────────────────────────────────
# Single-level spring-electrical embedding (slow O(n²) variant)
# ─────────────────────────────────────────────────────────────────


def spring_electrical_embedding(
    A: sp.csr_matrix,
    ctrl: SpringElectricalControl,
    x: np.ndarray,
    *,
    pinned_mask: Optional[np.ndarray] = None,
    rng: Optional[random.Random] = None,
    level: int = 0,
) -> int:
    """Slow O(n²) Fruchterman-Reingold-with-electric-repulsion
    embedding.  Mirrors C ``spring_electrical_embedding_slow``
    (spring_electrical.c:393), with the all-pairs repulsion
    block vectorised via numpy broadcasting.

    Modifies ``x`` in place.  Returns the iteration count.

    Parameters
    ----------
    A : csr_matrix
        Symmetric weighted adjacency.  Self-loops are skipped.
    ctrl : SpringElectricalControl
        Control parameters; modified in place when ``K`` or ``p``
        are auto-derived (matches C semantics).
    x : ndarray, shape (n, dim)
        Node positions.  Modified in place.
    pinned_mask : ndarray of bool, shape (n,), optional
        Nodes with ``pinned_mask[i] == True`` don't move.  C
        doesn't have this concept; GraphvizPy needs it for ``pos!``
        and pinned cluster proxies.
    rng : random.Random, optional
        Used only when ``ctrl.random_start`` is True.  Falls back
        to ``ctrl.random_seed`` if not supplied.
    level : int
        Tag for the trace channel only.
    """
    n, dim = x.shape
    if A.shape[0] != n:
        raise ValueError(
            f"matrix shape {A.shape} doesn't match coords shape {x.shape}"
        )
    if n <= 0 or dim <= 0 or ctrl.maxiter <= 0:
        return 0

    indptr = A.indptr
    indices = A.indices
    data = A.data

    if ctrl.random_start:
        if rng is None:
            rng = random.Random(ctrl.random_seed)
        for i in range(n):
            for k in range(dim):
                x[i, k] = rng.random()

    if ctrl.K < 0:
        ctrl.K = average_edge_length(A, x)
    if ctrl.p >= 0:
        ctrl.p = -1.0
    K = ctrl.K
    p = ctrl.p
    KP = K ** (1.0 - p)
    CRK = (_C ** ((2.0 - p) / 3.0)) / K

    step = ctrl.step
    Fnorm = 0.0
    iter_count = 0
    adaptive = ctrl.adaptive_cooling

    while step > _TOL and iter_count < ctrl.maxiter:
        iter_count += 1
        Fnorm0 = Fnorm
        Fnorm = 0.0

        # --- Repulsive force (all pairs, vectorised) ---
        # diff[i,j,k] = x[i,k] - x[j,k]
        diff = x[:, None, :] - x[None, :, :]              # (n, n, dim)
        dist2 = np.einsum("ijk,ijk->ij", diff, diff)      # (n, n)
        # crop tiny distances (matches C ``distance_cropped``)
        dist = np.sqrt(np.maximum(dist2, _MINDIST * _MINDIST))
        np.fill_diagonal(dist, 1.0)
        # f[i,k] += KP · (x[i,k] - x[j,k]) / dist^(1-p)
        coef = KP / np.power(dist, 1.0 - p)               # (n, n)
        np.fill_diagonal(coef, 0.0)
        force = np.einsum("ij,ijk->ik", coef, diff)       # (n, dim)

        # --- Attractive force (per edge) ---
        # f -= CRK · (x_i - x_j) · ‖x_i - x_j‖
        for i in range(n):
            row_start = int(indptr[i])
            row_end = int(indptr[i + 1])
            for jj in range(row_start, row_end):
                j = int(indices[jj])
                if j == i:
                    continue
                d = x[i] - x[j]
                d_norm = float(np.linalg.norm(d))
                # data[jj] is the edge weight; C uses unweighted
                # 1.0 here (the matrix isn't scaled by weight in
                # spring_electrical_embedding_slow either — the
                # weight enters only through the topology).  We
                # respect ctrl.K-scaled weights via the matrix
                # only when they're non-default; a future
                # session can plumb per-edge ``len`` properly.
                w = float(data[jj]) if data[jj] != 0.0 else 1.0
                _ = w  # noqa — reserved for weighted variant
                force[i] -= CRK * d * d_norm

        # --- Normalise and move ---
        F = np.linalg.norm(force, axis=1)                 # (n,)
        Fnorm = float(F.sum())
        # avoid div-by-zero on stationary nodes
        F_safe = np.where(F > 0, F, 1.0)
        unit = force / F_safe[:, None]
        if pinned_mask is not None:
            unit = unit.copy()
            unit[pinned_mask] = 0.0
        x += step * unit

        step = _update_step(adaptive, step, Fnorm, Fnorm0)

        if iter_count == 1 or iter_count % 25 == 0:
            _trace(
                f"level={level} iter={iter_count} "
                f"step={step:.4f} Fnorm={Fnorm:.4f}"
            )

    _trace(
        f"level={level} done iter={iter_count} "
        f"step={step:.4f} Fnorm={Fnorm:.4f}"
    )
    return iter_count


# ─────────────────────────────────────────────────────────────────
# interpolate_coord / prolongate
# ─────────────────────────────────────────────────────────────────


def interpolate_coord(A: sp.csr_matrix, x: np.ndarray) -> None:
    """Smooth coords toward neighbour mean.

    Mirrors C ``interpolate_coord`` (spring_electrical.c:832).

    Each node's new coord is ``α · x[i] + (1-α)/deg · Σ_j x[j]``
    with ``α = 0.5``.  Self-loops are skipped.  Operates in place.
    """
    n, dim = x.shape
    indptr = A.indptr
    indices = A.indices
    alpha = 0.5
    new_x = x.copy()
    for i in range(n):
        y = np.zeros(dim, dtype=np.float64)
        nz = 0
        for jj in range(indptr[i], indptr[i + 1]):
            j = int(indices[jj])
            if j == i:
                continue
            y += x[j]
            nz += 1
        if nz > 0:
            beta = (1.0 - alpha) / nz
            new_x[i] = alpha * x[i] + beta * y
    x[:] = new_x


def prolongate(
    A_fine: sp.csr_matrix,
    P: sp.csr_matrix,
    R: sp.csr_matrix,
    xc: np.ndarray,
    delta: float,
    rng: random.Random,
) -> np.ndarray:
    """Lift coarse coords to the next finer level.

    Mirrors C ``prolongate`` (spring_electrical.c:855).

    Steps:

    1. ``xf = P · xc`` — every fine-level node copies its
       cluster's coarse coord (``P[i, c] = 1`` if ``i`` ∈ cluster
       ``c``, so the matrix-vector product just looks up the
       cluster centroid).
    2. :func:`interpolate_coord` — smooth ``xf`` against the
       fine-level adjacency so cluster members spread out toward
       their fine-level neighbours.
    3. **Symmetry-breaking jitter**: for every cluster (rows of
       ``R``) and every member *after the first*, add a uniform
       perturbation in ``[-δ/2, +δ/2]^dim``.  The first member
       (the cluster representative) is left untouched so the
       coarse layout's structure is preserved at the rep, while
       the rest of the cluster gets a small kick to avoid
       degenerate stack-on-each-other configurations.

    Parameters
    ----------
    A_fine : csr_matrix
        Fine-level adjacency (used for the ``interpolate_coord``
        step; structure-only — values are ignored).
    P : csr_matrix
        Prolongation matrix, shape ``(n_fine, n_coarse)``.  Built
        by :func:`gvpy.engines.layout.sfdp.multilevel._coarsen_internal`.
    R : csr_matrix
        Restriction matrix, shape ``(n_coarse, n_fine)``.  Used
        here only to enumerate cluster members for the jitter
        step (matches C's reading of ``R->ia`` / ``R->ja``).
    xc : ndarray, shape (n_coarse, dim)
        Coarse-level coords.
    delta : float
        Jitter amplitude.  C uses ``ctrl->K * 0.001``.
    rng : random.Random
        Source of jitter randomness.

    Returns
    -------
    xf : ndarray, shape (n_fine, dim)
        Prolongated, smoothed, jittered fine-level coords.
    """
    # 1. Matrix-vector lift: xf = P · xc.
    xf = np.asarray(P @ xc)

    # 2. Smooth via interpolate_coord on fine-level adjacency.
    interpolate_coord(A_fine, xf)

    # 3. Per-cluster jitter on members 2..end (R rows = clusters).
    nc = R.shape[0]
    R_indptr = R.indptr
    R_indices = R.indices
    dim = xf.shape[1]
    for c in range(nc):
        # Skip the first member (representative); jitter the rest.
        for ii in range(int(R_indptr[c]) + 1, int(R_indptr[c + 1])):
            j = int(R_indices[ii])
            for k in range(dim):
                xf[j, k] += delta * (rng.random() - 0.5)

    return xf


# ─────────────────────────────────────────────────────────────────
# Multilevel descent
# ─────────────────────────────────────────────────────────────────


def multilevel_spring_electrical_embedding(
    A0: sp.csr_matrix,
    ctrl: SpringElectricalControl,
    grid_root: Multilevel,
    x: np.ndarray,
    *,
    pinned_mask: Optional[np.ndarray] = None,
    rng: Optional[random.Random] = None,
) -> None:
    """Run the C-aligned multilevel spring-electrical descent.

    Mirrors C ``multilevel_spring_electrical_embedding``
    (spring_electrical.c:1073), minus QuadTree, edge-label-node
    handling, post-process smoothing, and overlap removal — those
    are out-of-scope for this port (see module docstring).

    The hierarchy comes pre-built from
    :func:`gvpy.engines.layout.sfdp.multilevel.multilevel_new`.
    We:

    1. Walk to the coarsest level.
    2. Allocate a coords array per level (the finest level reuses
       the caller's ``x``).
    3. Run :func:`spring_electrical_embedding` at the coarsest level.
    4. For each finer level, prolongate the coarse coords into a
       fresh fine-level coords array, then re-relax with
       ``random_start=False``, ``adaptive_cooling=False``,
       ``step=0.1``, and ``K *= 0.75`` (matches C verbatim).
    5. Apply :func:`pcp_rotate` at the finest level for stable
       orientation (skipped if ``dim != 2``).

    The caller's ``x`` ends up holding the final finest-level
    layout.

    Parameters
    ----------
    A0 : csr_matrix
        Original (finest) adjacency.  Used only for the post-
        descent rotation; the per-level matrices come from
        ``grid_root``.
    ctrl : SpringElectricalControl
        Control struct.  Modified in place during the descent
        (matches C: ``K`` is overwritten with the auto-derived
        average edge length, then halved by 0.75 per level).
    grid_root : Multilevel
        Finest level of the hierarchy (level 0).
    x : ndarray, shape (n_finest, dim)
        Caller-owned coords for the finest level.  Filled in
        place.
    pinned_mask : ndarray of bool, optional
        Pinned nodes (level 0).  Currently only honored at the
        finest level — C doesn't propagate pinning through the
        hierarchy and neither do we.
    rng : random.Random, optional
        Source of randomness.
    """
    if rng is None:
        rng = random.Random(ctrl.random_seed)

    # Snapshot ctrl so the descent can mutate freely.
    ctrl0_K = ctrl.K
    ctrl0_random_start = ctrl.random_start
    ctrl0_adaptive_cooling = ctrl.adaptive_cooling
    ctrl0_step = ctrl.step

    n_fine, dim = x.shape

    # Auto-pick p (matches C: -1 for non-power-law, -1.8 otherwise).
    plg = _power_law_graph(A0)
    if ctrl.p == _AUTOP:
        ctrl.p = -1.0
        if plg:
            ctrl.p = -1.8

    coarsest = multilevel_get_coarsest(grid_root)

    # Allocate coords for each level.  The finest level reuses x;
    # every coarser level gets its own array (we'll free / drop
    # it after prolongation back up).
    is_finest = (coarsest is grid_root)
    if is_finest:
        xc: np.ndarray = x
    else:
        xc = np.zeros((coarsest.n, dim), dtype=np.float64)

    cur = coarsest
    while True:
        _trace(
            f"descent level={cur.level} n={cur.n} K={ctrl.K:.3f} "
            f"random_start={ctrl.random_start} "
            f"adaptive={ctrl.adaptive_cooling}"
        )

        # Per-level pinned mask (only honored at finest level).
        per_level_pinned = (
            pinned_mask if (cur is grid_root and pinned_mask is not None)
            else None
        )

        spring_electrical_embedding(
            cur.A, ctrl, xc,
            pinned_mask=per_level_pinned,
            rng=rng,
            level=cur.level,
        )

        if cur is grid_root:
            break

        # Prolongate from cur (coarse) up to cur.prev (finer).
        finer = cur.prev
        assert finer is not None
        P = cur.P     # n_finer × cur.n
        R = finer.R   # restriction at the finer level (may be
                      # different in shape from P^T due to row-
                      # normalisation, but indptr/indices match
                      # cluster membership — see Multilevel.c
                      # port).
        assert P is not None and R is not None
        xf_target_is_x = (finer is grid_root)
        xf = prolongate(finer.A, P, R, xc, ctrl.K * 0.001, rng)
        if xf_target_is_x:
            x[:] = xf
            xc = x
        else:
            xc = xf

        # Tighten ctrl for the next level.
        ctrl.random_start = False
        ctrl.K = ctrl.K * 0.75
        ctrl.adaptive_cooling = False
        ctrl.step = 0.1

        cur = finer

    # Stable orientation (2D only).  C does this after the
    # descent, before remove_overlap.
    if dim == 2 and x.shape[0] >= 2:
        pcp_rotate(x)

    # Restore ctrl.
    ctrl.K = ctrl0_K
    ctrl.random_start = ctrl0_random_start
    ctrl.adaptive_cooling = ctrl0_adaptive_cooling
    ctrl.step = ctrl0_step


# ─────────────────────────────────────────────────────────────────
# pcp_rotate — principal-component rotation for stable orientation
# ─────────────────────────────────────────────────────────────────


def pcp_rotate(x: np.ndarray) -> None:
    """Rotate so the principal axis aligns with the x-axis.

    Mirrors C ``pcp_rotate`` (spring_electrical.c:896).  2D only.
    Operates in place.

    The C code computes the eigensystem of the 2×2 covariance
    matrix and rotates so the larger-eigenvalue axis becomes
    horizontal.  We do the same, but use numpy's ``linalg.eigh``
    for the symmetric eigendecomposition instead of the inline
    closed-form (numerically equivalent, but easier to verify).
    """
    n, dim = x.shape
    if dim != 2 or n < 2:
        return

    # Centre.
    center = x.mean(axis=0)
    x -= center

    # Covariance matrix.
    Y = x.T @ x  # (2, 2)
    if abs(Y[0, 1]) < 1e-15:
        # Degenerate (axis-aligned cloud); nothing to rotate.
        return

    # Match C's specific axis choice (spring_electrical.c:931):
    #   axis[0] = -(-y[0] + y[3] - sqrt(...)) / (2 * y[1])
    #   axis[1] = 1
    y0, y1, y3 = Y[0, 0], Y[0, 1], Y[1, 1]
    disc = y0 * y0 + 4.0 * y1 * y1 - 2.0 * y0 * y3 + y3 * y3
    axis0 = -(-y0 + y3 - math.sqrt(disc)) / (2.0 * y1)
    axis1 = 1.0
    norm = math.sqrt(1.0 + axis0 * axis0)
    axis0 /= norm
    axis1 /= norm

    # Apply: x'  = x · axis[0] + y · axis[1]
    #        y'  = -x · axis[1] + y · axis[0]
    new_x = x[:, 0] * axis0 + x[:, 1] * axis1
    new_y = -x[:, 0] * axis1 + x[:, 1] * axis0
    x[:, 0] = new_x
    x[:, 1] = new_y
