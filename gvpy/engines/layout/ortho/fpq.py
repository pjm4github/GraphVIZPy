"""Port of ``lib/ortho/fPQ.{h,c}`` — binary max-heap keyed on ``Snode.n_val``.

Semantics track C verbatim:

- 1-indexed heap.  ``pq[0]`` is a ``guard`` sentinel whose ``n_val``
  stays at 0 so :func:`pq_upheap` terminates at the root without a
  bounds check.
- Max-heap — :func:`pq_upheap` promotes nodes with larger ``n_val``
  toward the root.  :func:`short_path` inverts distances (stores them
  as negatives) so "larger n_val" means "smaller tentative distance",
  giving a min-priority queue over actual distances.
- Each node tracks its own position via ``n_idx``.  :func:`pq_update`
  relies on this to re-heapify in place when a tentative distance
  improves.

C declares the heap size statically via ``PQgen(sz)``; this port keeps
the bound purely for parity with the ``Heap overflow`` error path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.ortho.sgraph import Snode

# C's ``PQcheck`` invariant runs only under ``#ifdef DEBUG``; release
# builds skip it.  Python followed the debug path on every heap
# operation, which profiled as ~50 % of total runtime on 2620.dot
# (37.7 s out of 76 s across 2.37 M invocations).  Gate the check
# behind an opt-in env var so production runs skip the O(n) walk
# while diagnostic sessions can still flip it on.
_PQCHECK_ENABLED = os.environ.get("GVPY_PQCHECK") == "1"


@dataclass
class Pq:
    """Port of ``struct pq`` in ``fPQ.c``.

    ``pq`` is 1-indexed; slot 0 holds the ``guard`` sentinel.
    """
    pq: list = field(default_factory=list)
    cnt: int = 0
    size: int = 0
    guard: object = None  # Snode instance; forward-declared to avoid cycle


def pq_gen(sz: int) -> Pq:
    """``PQgen`` — create a priority queue of capacity ``sz``."""
    from gvpy.engines.layout.ortho.sgraph import Snode
    guard = Snode()  # zero-initialized, n_val=0 acts as upheap sentinel
    # (size+1) slots with index 0 reserved for the guard.
    pq_list: list = [guard] + [None] * sz
    return Pq(pq=pq_list, cnt=0, size=sz, guard=guard)


def pq_free(pq: Pq) -> None:
    """``PQfree`` — no-op under Python GC; kept for parity."""


def pq_init(pq: Pq) -> None:
    """``PQinit`` — reset count to 0 without clearing storage."""
    pq.cnt = 0


def pq_insert(pq: Pq, np) -> int:
    """``PQ_insert`` — add ``np`` to the heap; return 1 on overflow."""
    if pq.cnt == pq.size:
        print("[ERROR ortho-fpq] Heap overflow", flush=True)
        return 1
    pq.cnt += 1
    pq.pq[pq.cnt] = np
    _pq_upheap(pq, pq.cnt)
    if _PQCHECK_ENABLED:
        _pq_check(pq)
    return 0


def pq_remove(pq: Pq):
    """``PQremove`` — pop and return the max-priority element, or None."""
    if pq.cnt:
        n = pq.pq[1]
        pq.pq[1] = pq.pq[pq.cnt]
        pq.cnt -= 1
        if pq.cnt:
            _pq_downheap(pq, 1)
        if _PQCHECK_ENABLED:
            _pq_check(pq)
        return n
    return None


def pq_update(pq: Pq, n, d: int) -> None:
    """``PQupdate`` — set ``n.n_val = d`` and re-heapify in place."""
    n.n_val = d
    _pq_upheap(pq, n.n_idx)
    if _PQCHECK_ENABLED:
        _pq_check(pq)


def _pq_upheap(pq: Pq, k: int) -> None:
    """Promote ``pq.pq[k]`` upward while parent's ``n_val`` is smaller.

    Terminates at the root because ``pq.pq[0].n_val == 0`` (guard) is
    never less than a freshly-inserted ``v`` in practice (see module
    docstring — tentative distances are non-positive).
    """
    x = pq.pq[k]
    v = x.n_val
    next_k = k // 2

    while pq.pq[next_k].n_val < v:
        n = pq.pq[next_k]
        pq.pq[k] = n
        n.n_idx = k
        k = next_k
        next_k //= 2

    pq.pq[k] = x
    x.n_idx = k


def _pq_downheap(pq: Pq, k: int) -> None:
    """Sift ``pq.pq[k]`` downward toward a leaf."""
    x = pq.pq[k]
    v = x.n_val
    lim = pq.cnt // 2

    while k <= lim:
        j = k + k
        n = pq.pq[j]
        if j < pq.cnt:
            if n.n_val < pq.pq[j + 1].n_val:
                j += 1
                n = pq.pq[j]
        if v >= n.n_val:
            break
        pq.pq[k] = n
        n.n_idx = k
        k = j

    pq.pq[k] = x
    x.n_idx = k


def _pq_check(pq: Pq) -> None:
    """Mirror C's ``PQcheck`` invariant: ``pq.pq[i].n_idx == i``.

    Runs under assertions; a violation means an update path dropped an
    ``n_idx`` assignment.
    """
    for i in range(1, pq.cnt + 1):
        assert pq.pq[i].n_idx == i, (
            f"PQcheck failed at i={i}: node.n_idx={pq.pq[i].n_idx}"
        )
