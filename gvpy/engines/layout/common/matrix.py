"""Dense matrix primitives shared across layout engines.

Mirrors fragments of Graphviz ``lib/neatogen/matrix_ops.c``,
``lib/neatogen/lu.c``, and ``lib/neatogen/matinv.c``.  Kept in the
common package because future engines (fdp, sfdp) also need these
primitives — the dot engine has no use for them but other
force-directed engines all do.
"""
from __future__ import annotations

from typing import Optional


Matrix = list[list[float]]


def gauss_jordan_inverse(M: Matrix) -> Optional[Matrix]:
    """Return the inverse of ``M`` via Gauss-Jordan elimination.

    Mirrors ``lib/neatogen/matinv.c``'s small-matrix path.
    Returns ``None`` if the matrix is singular (pivot below 1e-12).
    Suitable for matrices up to a few hundred rows; for large or
    sparse systems use a conjugate-gradient solver instead.
    """
    n = len(M)
    aug = [row[:] + [1.0 if j == i else 0.0 for j in range(n)]
           for i, row in enumerate(M)]

    for col in range(n):
        max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[max_row][col]) < 1e-12:
            return None
        aug[col], aug[max_row] = aug[max_row], aug[col]

        pivot = aug[col][col]
        aug[col] = [v / pivot for v in aug[col]]

        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [aug[row][j] - factor * aug[col][j]
                        for j in range(2 * n)]

    return [row[n:] for row in aug]
