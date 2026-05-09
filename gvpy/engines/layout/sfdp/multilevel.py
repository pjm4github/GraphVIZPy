"""C-aligned port of ``lib/sfdpgen/Multilevel.c``.

Builds a multilevel coarsening hierarchy for sfdp's
spring-electrical layout.  At each level, a maximum independent
edge set ("MIES") with heaviest-edge-per-node matching collapses
the graph by ~25% (default ``min_coarsen_factor=0.75``);
the hierarchy bottoms out when no further reduction is possible
or the coarsest level has fewer than ``minsize=4`` nodes.

Algorithm (mirrors C verbatim):

1. **Supervariable decomposition** — group nodes with
   *identical* neighbour sets ("modules" in graph theory).
   Uses ``SparseMatrix_decompose_to_supervariables`` from
   ``lib/sparse/SparseMatrix.c`` ported to Py.  For most graphs
   this returns one supervariable per node (no grouping).
2. **Supernode pre-clustering** — for every supervariable with
   ≥ 2 members, cluster up to ``MAX_CLUSTER_SIZE=4`` per cluster.
3. **MIES heavy-edge matching** — for each unmatched node (in
   random permutation order), find its heaviest unmatched
   neighbour and pair them.
4. **Singleton fallback** — any node still unmatched becomes its
   own 1-element cluster.

Galerkin coarsening at each level: ``cA = R · A · P`` where
``P`` is the n×nc prolongation matrix (``P[i, c] = 1`` if node
``i`` is in cluster ``c``) and ``R`` is ``P`` transposed and
row-normalised by degree.  Edge weights aggregate correctly
through this product.

Uses ``scipy.sparse`` (already a project dependency) for the
``SparseMatrix`` machinery.

API surface (mirrors C ``Multilevel.h``):

- :class:`Multilevel` — one level in the hierarchy.
- :func:`multilevel_new` — entry point; build the hierarchy.
- :func:`multilevel_get_coarsest` — walk to the deepest level.
- :func:`multilevel_to_legacy_levels` — adapter that converts
  to the old ``[{nodes, adj, mapping}]`` shape that the existing
  ``SfdpLayout._spring_electrical`` consumes, so this module is
  a drop-in replacement for ``_build_hierarchy``.

Trace channel: ``GVPY_TRACE_SFDP=1`` emits
``[TRACE sfdp_multi] level=N n=M nz=K`` lines.
"""
from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np
import scipy.sparse as sp


_MAX_CLUSTER_SIZE = 4         # MAX_CLUSTER_SIZE (Multilevel.h:29)
_MIN_SIZE = 4                 # minsize (Multilevel.c:21)
_MIN_COARSEN_FACTOR = 0.75    # min_coarsen_factor (Multilevel.c:22)


def _trace(msg: str) -> None:
    if os.environ.get("GVPY_TRACE_SFDP", "") == "1":
        print(f"[TRACE sfdp_multi] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────
# Supervariable decomposition
# ─────────────────────────────────────────────────────────────────


def _decompose_to_supervariables(
    A: sp.csr_matrix,
) -> tuple[list[int], list[int]]:
    """Group nodes that share identical neighbour sets.

    Mirrors C ``SparseMatrix_decompose_to_supervariables``
    (``lib/sparse/SparseMatrix.c:1352``).

    Returns ``(super_arr, super_groups)`` where:
    - ``super_arr[i]`` is the supervariable id node ``i`` belongs to;
    - ``super_groups`` is the per-supervariable member list,
      flattened in the format C uses: ``superp + super``, here
      returned as a list of lists.
    """
    n = A.shape[0]
    indptr = A.indptr
    indices = A.indices

    # Initially every node is in supervariable 0.
    super_arr = [0] * n
    nsuper = [n]               # count per supervariable
    mask = [-1] * n            # last row that touched each supervar
    newmap = [0] * n           # current row's split target per supervar
    isup = 1                   # next free supervariable id

    for i in range(n):
        # Decrement count: every neighbour of row i will (potentially) move
        # out of its current supervariable.
        for jj in range(indptr[i], indptr[i + 1]):
            j = indices[jj]
            if super_arr[j] < len(nsuper):
                nsuper[super_arr[j]] -= 1

        for jj in range(indptr[i], indptr[i + 1]):
            j = indices[jj]
            isuper = super_arr[j]
            if mask[isuper] < i:
                mask[isuper] = i
                if nsuper[isuper] == 0:
                    # All members of isuper are neighbours of row i —
                    # j stays in isuper.
                    nsuper[isuper] = 1
                    newmap[isuper] = isuper
                else:
                    # Some members of isuper aren't neighbours of row i —
                    # split j into a new supervariable.
                    newmap[isuper] = isup
                    while len(nsuper) <= isup:
                        nsuper.append(0)
                    nsuper[isup] = 1
                    super_arr[j] = isup
                    isup += 1
            else:
                # Already saw isuper this row — j joins its split target.
                tgt = newmap[isuper]
                super_arr[j] = tgt
                nsuper[tgt] += 1

    # Flatten: build super_groups[s] = [nodes in supervariable s].
    super_groups: list[list[int]] = [[] for _ in range(isup)]
    for i in range(n):
        super_groups[super_arr[i]].append(i)
    # Drop empty supervariables.
    super_groups = [g for g in super_groups if g]
    return super_arr, super_groups


# ─────────────────────────────────────────────────────────────────
# Maximal independent edge set with heavy-edge matching
# ─────────────────────────────────────────────────────────────────


def _maximal_independent_edge_set(
    A: sp.csr_matrix,
    rng: random.Random,
) -> list[list[int]]:
    """MIES with heaviest-edge-per-node matching, supernodes first.

    Mirrors C
    ``maximal_independent_edge_set_heavest_edge_pernode_supernodes_first``
    (Multilevel.c:56).

    Returns the cluster list — each cluster is a list of node
    indices.  Every node appears in exactly one cluster.
    """
    n = A.shape[0]
    indptr = A.indptr
    indices = A.indices
    data = A.data
    MATCHED = -1
    matched = list(range(n))   # matched[i] = i means unmatched

    clusters: list[list[int]] = []

    # 1. Supervariable pre-clustering.
    _, super_groups = _decompose_to_supervariables(A)
    for group in super_groups:
        if len(group) <= 1:
            continue
        # Group up to MAX_CLUSTER_SIZE per cluster.
        cur: list[int] = []
        for node_idx in group:
            matched[node_idx] = MATCHED
            cur.append(node_idx)
            if len(cur) >= _MAX_CLUSTER_SIZE:
                clusters.append(cur)
                cur = []
        if cur:
            clusters.append(cur)

    # 2. Random-permutation heavy-edge matching.
    perm = list(range(n))
    rng.shuffle(perm)
    for i in perm:
        if matched[i] == MATCHED:
            continue
        amax = -1.0
        jamax = -1
        first = True
        for jj in range(indptr[i], indptr[i + 1]):
            j = indices[jj]
            if i == j:
                continue
            if matched[j] != MATCHED and matched[i] != MATCHED:
                w = float(data[jj])
                if first or w > amax:
                    amax = w
                    jamax = j
                    first = False
        if not first:
            matched[jamax] = MATCHED
            matched[i] = MATCHED
            clusters.append([i, jamax])

    # 3. Singleton fallback for any remaining unmatched nodes.
    for i in range(n):
        if matched[i] == i:    # still unmatched
            clusters.append([i])

    return clusters


# ─────────────────────────────────────────────────────────────────
# Galerkin coarsening
# ─────────────────────────────────────────────────────────────────


def _coarsen_internal(
    A: sp.csr_matrix,
    rng: random.Random,
) -> tuple[Optional[sp.csr_matrix],
           Optional[sp.csr_matrix],
           Optional[sp.csr_matrix]]:
    """Single coarsening step.

    Mirrors C ``Multilevel_coarsen_internal`` (Multilevel.c:146).

    Returns ``(cA, P, R)`` — the coarse adjacency, the
    prolongation matrix, and the (degree-normalised)
    restriction matrix.  Returns ``(None, None, None)`` when no
    useful reduction is possible (cA would equal A or fall below
    ``minsize``).
    """
    n = A.shape[0]
    clusters = _maximal_independent_edge_set(A, rng)
    nc = len(clusters)
    if nc == n or nc < _MIN_SIZE:
        return None, None, None

    # Build P: n×nc, P[i, c] = 1 if node i is in cluster c.
    rows: list[int] = []
    cols: list[int] = []
    for c_idx, cluster in enumerate(clusters):
        for node_idx in cluster:
            rows.append(node_idx)
            cols.append(c_idx)
    vals = [1.0] * len(rows)
    P = sp.csr_matrix(
        (vals, (rows, cols)), shape=(n, nc), dtype=np.float64,
    )
    R = P.transpose().tocsr()

    # Galerkin coarsening: cA = R · A · P.
    cA = (R @ A @ P).tocsr()

    # Normalise R by row degree so prolongation back averages
    # cluster member positions instead of summing them.
    R_dense_degrees = np.asarray(R.sum(axis=1)).flatten()
    R_dense_degrees[R_dense_degrees == 0] = 1.0
    inv_deg = 1.0 / R_dense_degrees
    D_inv = sp.diags(inv_deg, format="csr")
    R = (D_inv @ R).tocsr()

    # Strip diagonal of cA (mirrors SparseMatrix_remove_diagonal).
    cA = cA - sp.diags(cA.diagonal(), format="csr")
    cA.eliminate_zeros()

    return cA, P, R


def _coarsen(
    A: sp.csr_matrix,
    rng: random.Random,
) -> tuple[Optional[sp.csr_matrix],
           Optional[sp.csr_matrix],
           Optional[sp.csr_matrix]]:
    """Outer coarsening loop — keep coarsening until reduction
    ratio falls below ``min_coarsen_factor``.

    Mirrors C ``Multilevel_coarsen`` (Multilevel.c:204).  When a
    single ``_coarsen_internal`` step doesn't reduce enough,
    repeat with the result and accumulate the P/R matrices via
    multiplication so the cumulative transformation maps the
    original A to the final cA.
    """
    n = A.shape[0]
    P_acc: Optional[sp.csr_matrix] = None
    R_acc: Optional[sp.csr_matrix] = None
    cA_acc: Optional[sp.csr_matrix] = None
    cur = A
    while True:
        cA0, P0, R0 = _coarsen_internal(cur, rng)
        if cA0 is None:
            return cA_acc, P_acc, R_acc
        nc = cA0.shape[0]
        if P_acc is None:
            P_acc = P0
            R_acc = R0
        else:
            P_acc = (P_acc @ P0).tocsr()
            R_acc = (R0 @ R_acc).tocsr()
        cA_acc = cA0
        if nc <= _MIN_COARSEN_FACTOR * n:
            return cA_acc, P_acc, R_acc
        cur = cA0


# ─────────────────────────────────────────────────────────────────
# Multilevel data structure
# ─────────────────────────────────────────────────────────────────


@dataclass
class Multilevel:
    """One level of the multilevel hierarchy.

    Mirrors C ``struct Multilevel_struct`` (Multilevel.h:18).

    - ``level`` — depth from the finest level (level 0 is the
      original graph).
    - ``A`` — adjacency / weight matrix at this level.
    - ``P`` — prolongation matrix to interpolate from THIS level
      to the FINER level above (level - 1).  ``None`` at the
      finest level.
    - ``R`` — restriction matrix to coarsen from THIS level
      to the COARSER level below (level + 1).  ``None`` at the
      coarsest level.
    - ``next`` / ``prev`` — pointers along the hierarchy.
    """

    level: int
    n: int
    A: sp.csr_matrix
    P: Optional[sp.csr_matrix] = None
    R: Optional[sp.csr_matrix] = None
    next: Optional["Multilevel"] = None
    prev: Optional["Multilevel"] = None


def multilevel_new(
    A: sp.csr_matrix,
    *,
    max_levels: int = 100,
    seed: int = 1,
) -> Multilevel:
    """Build the multilevel coarsening hierarchy.

    Mirrors C ``Multilevel_new`` (Multilevel.c:282).

    The input matrix should be the (symmetric) weighted
    adjacency of the graph.  We coarsen until either:

    - ``_coarsen`` returns ``None`` (no further reduction
      possible),
    - the current level has fewer than ``minsize=4`` nodes,
      or
    - we hit ``max_levels``.
    """
    rng = random.Random(seed)
    grid = Multilevel(level=0, n=A.shape[0], A=A)
    _trace(
        f"level=0 n={grid.n} nz={A.nnz} "
        f"density={A.nnz / (grid.n * grid.n):.4f}"
    )

    cur = grid
    for level in range(max_levels):
        if cur.n < _MIN_SIZE:
            break
        cA, P, R = _coarsen(cur.A, rng)
        if cA is None or P is None or R is None:
            break
        coarse = Multilevel(level=cur.level + 1, n=cA.shape[0], A=cA)
        cur.R = R
        coarse.P = P
        coarse.prev = cur
        cur.next = coarse
        _trace(
            f"level={coarse.level} n={coarse.n} nz={cA.nnz} "
            f"reduction={coarse.n / cur.n:.3f}"
        )
        cur = coarse

    return grid


def multilevel_get_coarsest(grid: Multilevel) -> Multilevel:
    """Walk to the deepest level.  Mirrors C
    ``Multilevel_get_coarsest`` (Multilevel.c:298).
    """
    while grid.next is not None:
        grid = grid.next
    return grid


# ─────────────────────────────────────────────────────────────────
# Adapter for SfdpLayout's existing _spring_electrical
# ─────────────────────────────────────────────────────────────────


def multilevel_to_legacy_levels(
    grid: Multilevel,
    node_names: list[str],
) -> list[dict]:
    """Convert the C-aligned hierarchy to the
    ``[{nodes, adj, mapping}]`` shape the existing
    ``SfdpLayout._spring_electrical`` consumes.

    ``node_names[i]`` gives the original node name for matrix
    row ``i`` at the finest level.  Each cluster at every
    coarsening level is identified by the **first member's
    name** rather than a synthetic supernode name — this keeps
    every hierarchy-level node name resolvable in
    ``layout.lnodes``, so the existing flat solver runs without
    needing synthetic-supernode entries installed.

    ``mapping[child_rep_name] = parent_rep_name`` lets the
    existing prolongation step interpolate from a coarse level
    to its finer level by copying the parent's position into
    each child.
    """
    levels: list[dict] = []

    # Level 0: original nodes.
    cur = grid
    cur_names = list(node_names)
    levels.append({
        "nodes": list(cur_names),
        "adj": _adj_from_csr(cur.A, cur_names),
        "mapping": {},  # finest level has no parent
    })

    while cur.next is not None:
        coarse = cur.next
        P = coarse.P  # cur.n × coarse.n — column c lists children
                      # of cluster c.
        P_csc = P.tocsc()
        coarse_names: list[str] = []
        mapping: dict[str, str] = {}
        for c in range(coarse.n):
            members = []
            for ii in range(P_csc.indptr[c], P_csc.indptr[c + 1]):
                members.append(P_csc.indices[ii])
            members.sort()  # deterministic representative
            assert members, "empty cluster"
            rep_idx = members[0]
            rep_name = cur_names[rep_idx]
            coarse_names.append(rep_name)
            for child_idx in members:
                mapping[cur_names[child_idx]] = rep_name

        levels.append({
            "nodes": list(coarse_names),
            "adj": _adj_from_csr(coarse.A, coarse_names),
            "mapping": mapping,
        })

        cur = coarse
        cur_names = coarse_names

    return levels


def _adj_from_csr(
    A: sp.csr_matrix,
    names: list[str],
) -> dict[str, list[str]]:
    """Convert a CSR adjacency matrix to the ``{name: [neighbor_names]}``
    dict shape the existing solver expects.  Drops self-loops."""
    indptr = A.indptr
    indices = A.indices
    adj: dict[str, list[str]] = {n: [] for n in names}
    n = A.shape[0]
    for i in range(n):
        for jj in range(indptr[i], indptr[i + 1]):
            j = indices[jj]
            if i == j:
                continue
            adj[names[i]].append(names[j])
    return adj


# ─────────────────────────────────────────────────────────────────
# Build initial sparse matrix from an adjacency dict
# ─────────────────────────────────────────────────────────────────


def csr_from_adjacency(
    node_list: list[str],
    adj: dict[str, list[str]],
    edge_weight: Optional[dict[tuple[str, str], float]] = None,
) -> sp.csr_matrix:
    """Build a symmetric weighted adjacency CSR matrix from the
    engine's adjacency dict.

    ``node_list`` defines the row/column ordering.  Each undirected
    edge contributes two CSR entries (one per direction).
    ``edge_weight`` is keyed by the canonical ``(min, max)`` pair;
    missing edges default to weight 1.
    """
    name_to_idx = {n: i for i, n in enumerate(node_list)}
    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    seen: set[tuple[int, int]] = set()
    for u in node_list:
        i = name_to_idx[u]
        for v in adj.get(u, ()):
            j = name_to_idx.get(v)
            if j is None or i == j:
                continue
            key = (i, j) if i < j else (j, i)
            if key in seen:
                continue
            seen.add(key)
            pair = (u, v) if u < v else (v, u)
            w = 1.0
            if edge_weight is not None:
                w = edge_weight.get(pair, 1.0)
            rows.append(i)
            cols.append(j)
            vals.append(w)
            rows.append(j)
            cols.append(i)
            vals.append(w)
    n = len(node_list)
    return sp.csr_matrix(
        (vals, (rows, cols)), shape=(n, n), dtype=np.float64,
    )
