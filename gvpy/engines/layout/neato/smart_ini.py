"""Neato smart-init via PivotMDS.

Mirrors the smart-init block at ``lib/neatogen/stress.c:884-913``,
which calls ``sparse_stress_subspace_majorization_kD`` (a sparse,
HDE+PCA-based pipeline).  This Py port substitutes PivotMDS
(Brandes & Pich 2007), an algorithmically simpler classical-MDS
specialisation that achieves the same goal: a near-globally-good
initial layout that lets the downstream stress majorization /
Kamada-Kawai descent escape local minima on symmetric graphs.

After PivotMDS produces the projected coordinates, we apply C's
post-processing: per-axis normalisation, a small random jitter to
break exact symmetries, and centring (the orthog1 step that
projects each axis onto the subspace orthogonal to the all-ones
vector).
"""
from __future__ import annotations

import os
import random
import sys
from typing import TYPE_CHECKING

import numpy as np

from gvpy.engines.layout.common.pivot_mds import pivot_mds

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


# Mirrors C ``num_pivots_stress`` (default 50 in stress.c).
_DEFAULT_PIVOTS = 50

# Below this node count PivotMDS degenerates and random init is
# fine — also matches C's behaviour where it skips smart-init for
# very small graphs.
_SMART_INIT_MIN_N = 4


def _trace(msg: str) -> None:
    """Emit a ``[TRACE neato_init]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_NEATO=1``)."""
    if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
        print(f"[TRACE neato_init] {msg}", file=sys.stderr)


def smart_init(layout: "NeatoLayout",
               node_list: list[str],
               dist: list[list[float]],
               N: int,
               dim: int = 2,
               n_pivots: int | None = None) -> bool:
    """Place each unpinned node at its PivotMDS coordinate.

    Returns ``True`` if smart-init ran (positions were updated),
    ``False`` if the graph was too small or all nodes were
    user-pinned.
    """
    if N < _SMART_INIT_MIN_N:
        _trace(f"skip: N={N} below threshold {_SMART_INIT_MIN_N}")
        return False

    # Skip if every node is pinned — nothing to do.
    if all(layout.lnodes[name].pos_set or layout.lnodes[name].pinned
           for name in node_list):
        _trace("skip: all nodes pinned/pos_set")
        return False

    pivots = n_pivots if n_pivots is not None else _DEFAULT_PIVOTS

    coords = pivot_mds(dist, N, n_pivots=pivots, dim=dim,
                       seed=layout.seed)

    # Per-axis normalisation (mirrors stress.c:897-907): scale each
    # axis to roughly unit max, then add tiny jitter, then centre.
    for k in range(dim):
        col = coords[:, k]
        max_abs = float(np.max(np.abs(col)))
        if max_abs > 1e-12:
            col /= max_abs
        # Small uniform noise in [-0.5e-6, 0.5e-6].
        for i in range(N):
            col[i] += 1e-6 * (random.random() - 0.5)
        # Centre against the all-ones vector.
        col -= col.mean()
        coords[:, k] = col

    # Rescale to layout-appropriate magnitude.  The normalised
    # coords are O(1); the previous random init produced
    # O(sqrt(N) * 72) magnitudes.  Scale to similar range so the
    # downstream stress majorisation lands in a sensible regime.
    import math
    target_span = math.sqrt(N) * 72.0
    coords *= target_span * 0.5

    # Write back, respecting pinned / pos_set nodes.
    n_updated = 0
    for i, name in enumerate(node_list):
        ln = layout.lnodes[name]
        if ln.pos_set or ln.pinned:
            continue
        ln.x = float(coords[i, 0]) if dim >= 1 else 0.0
        ln.y = float(coords[i, 1]) if dim >= 2 else 0.0
        n_updated += 1

    _trace(f"applied N={N} pivots={pivots} dim={dim} updated={n_updated}")
    return True
