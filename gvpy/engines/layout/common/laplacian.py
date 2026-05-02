"""Packed-Laplacian primitives shared across stress-based engines.

Mirrors fragments of Graphviz ``lib/neatogen/matrix_ops.c``.  The
packed format stores only the upper-triangular part of an
``n``×``n`` symmetric matrix as a flat array of length
``n*(n+1)/2``, row-major:

    row 0: diag, [0,1], [0,2], ..., [0,n-1]      (n entries)
    row 1: diag, [1,2], ..., [1,n-1]             (n-1 entries)
    ...
    row n-1: diag                                (1 entry)

Indexing helper: ``packed_index(n, i, j)`` for ``i <= j`` returns
the flat-array position.  Total length = ``n*(n+1)/2``.

References
----------
- ``right_mult_with_vector_ff``           matrix_ops.c:401
- ``invert_vec`` / ``invert_sqrt_vec`` /
  ``square_vec`` / ``sqrt_vecf``          matrix_ops.c:494-530
- ``orthog1f``                            matrix_ops.c:383
"""
from __future__ import annotations

import numpy as np


def packed_length(n: int) -> int:
    """Length of the packed upper-triangular array for an ``n``×``n``
    symmetric matrix."""
    return n * (n + 1) // 2


def packed_diag_index(n: int, i: int) -> int:
    """Flat-array index of the diagonal entry ``[i, i]`` in a
    packed upper-triangular matrix of size ``n``."""
    return i * (2 * n - i + 1) // 2


def packed_index(n: int, i: int, j: int) -> int:
    """Flat-array index of entry ``[i, j]`` (must have ``i <= j``)."""
    if i > j:
        i, j = j, i
    return packed_diag_index(n, i) + (j - i)


def right_mult_packed(lap: np.ndarray, n: int,
                      x: np.ndarray) -> np.ndarray:
    """Compute ``y = A @ x`` where ``A`` is the symmetric matrix
    stored in the packed upper-triangular form ``lap``.

    Mirrors ``right_mult_with_vector_ff`` (matrix_ops.c:401).
    The result is a fresh ``np.ndarray`` of length ``n``.
    """
    y = np.zeros(n, dtype=lap.dtype)
    index = 0
    for i in range(n):
        xi = x[i]
        # diagonal
        y[i] += lap[index] * xi
        index += 1
        # off-diagonal: row i, columns i+1..n-1
        for j in range(i + 1, n):
            v = lap[index]
            y[i] += v * x[j]
            y[j] += v * xi
            index += 1
    return y


def orthog1(vec: np.ndarray) -> None:
    """Project ``vec`` onto the subspace orthogonal to the all-ones
    vector (in place).  Equivalent to centring: subtracts the mean.

    Mirrors ``orthog1f`` (matrix_ops.c:383).  Used to enforce the
    centroid-at-origin gauge so the singular Laplacian has a unique
    solution.
    """
    vec -= vec.mean()
