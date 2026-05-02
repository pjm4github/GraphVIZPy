"""Dense matrix primitives shared across layout engines.

Mirrors fragments of Graphviz ``lib/neatogen/matrix_ops.c``,
``lib/neatogen/lu.c``, ``lib/neatogen/matinv.c``, and
``lib/neatogen/solve.c``.  Kept in the common package because
future engines (fdp, sfdp) also need these primitives — the dot
engine has no use for them but other force-directed engines all
do.
"""
from __future__ import annotations

from typing import Optional


Matrix = list[list[float]]


def gauss_solve(a: list[float], c: list[float], n: int
                ) -> Optional[list[float]]:
    """Solve ``A x = c`` for an ``n``×``n`` matrix ``A`` stored
    row-major in ``a`` (length ``n²``).  Returns the solution
    vector ``x`` of length ``n``, or ``None`` if the system is
    ill-conditioned (any pivot below 1e-10 in absolute value).

    Mirrors ``lib/neatogen/solve.c::solve``.  Uses partial pivoting
    on rows for numerical stability.  Suitable for very small
    systems (typically ``n`` = 2 or 3 for the KK Newton step).
    Inputs are not modified.
    """
    if n < 2:
        return None

    # Work on copies so callers' inputs survive.
    a = [v for v in a]
    c = [v for v in c]

    nm = n - 1
    for i in range(nm):
        # Find the largest pivot in column i, rows i..n-1.
        amax = 0.0
        istar = i
        for ii in range(i, n):
            dum = abs(a[ii * n + i])
            if dum >= amax:
                istar = ii
                amax = dum
        if amax < 1e-10:
            return None

        # Swap rows istar and i (only columns >= i are non-zero).
        if istar != i:
            for j in range(i, n):
                t = istar * n + j
                s = i * n + j
                a[t], a[s] = a[s], a[t]
            c[istar], c[i] = c[i], c[istar]

        # Eliminate column i below the diagonal.
        for ii in range(i + 1, n):
            pivot = a[ii * n + i] / a[i * n + i]
            c[ii] -= pivot * c[i]
            for j in range(n):
                a[ii * n + j] -= pivot * a[i * n + j]

    if abs(a[n * n - 1]) < 1e-10:
        return None

    # Back substitute.
    b = [0.0] * n
    b[n - 1] = c[n - 1] / a[n * n - 1]
    for k in range(nm):
        m = n - k - 2
        b[m] = c[m]
        for j in range(m + 1, n):
            b[m] -= a[m * n + j] * b[j]
        b[m] /= a[m * n + m]
    return b


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
