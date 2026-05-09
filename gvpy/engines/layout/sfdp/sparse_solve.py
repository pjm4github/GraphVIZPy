"""C-aligned port of ``lib/sfdpgen/sparse_solve.c``.

Diagonal-preconditioned conjugate gradient solver used as the
inner loop of stress majorization
(:mod:`gvpy.engines.layout.sfdp.post_process`).

We deliberately port the C algorithm verbatim rather than wrap
``scipy.sparse.linalg.cg`` because:

- C's ``post_process_smoothing`` uses a *very loose*
  tolerance (``tol_cg = 0.1``) — the inner solve is only one
  step of a Gauss-Seidel-like outer fixed-point iteration, and
  scipy's stricter convergence criterion would change the
  iteration count materially.
- C uses a hand-rolled diagonal Jacobi preconditioner that
  encodes ``1/Lw[i,i]`` directly; scipy's preconditioning API
  needs an ``M⁻¹`` operator and would add wrapping cost on
  every CG step.

API (mirrors C ``sparse_solve.h``):

- :func:`sparse_matrix_solve` — top-level multi-dimensional
  solve.  Solves ``A · x = rhs`` independently for each
  coordinate dimension.

The two helpers (``_diag_precon_new``, ``_conjugate_gradient``)
are module-private but exposed for tests.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import scipy.sparse as sp


def _diag_precon_new(A: sp.csr_matrix) -> np.ndarray:
    """Build the diagonal Jacobi preconditioner.

    Mirrors C ``diag_precon_new`` (sparse_solve.c:33).  Returns
    ``[1/A[i,i] if A[i,i] != 0 else 1.0 for i in range(m)]`` —
    the trivial Jacobi preconditioner.

    The C version stores ``m`` in the first slot of the data
    array and offsets the pointer by 1; we just return the
    length-m array directly.
    """
    m = A.shape[0]
    diag = np.ones(m, dtype=np.float64)
    A_diag = A.diagonal()
    nonzero = A_diag != 0.0
    diag[nonzero] = 1.0 / A_diag[nonzero]
    return diag


def _conjugate_gradient(
    A: sp.csr_matrix,
    precon: np.ndarray,
    x: np.ndarray,
    rhs: np.ndarray,
    tol: float,
    maxit: int,
) -> float:
    """Diagonal-preconditioned CG.

    Mirrors C ``conjugate_gradient`` (sparse_solve.c:56).
    Solves ``A · x = rhs`` in place.  Returns the final
    residual.

    The relative tolerance is ``tol·res0`` — i.e. terminate
    when residual drops to ``tol`` times the *initial*
    residual, not below an absolute floor.  This is the
    convention C's outer stress-majorization loop expects:
    one cheap iteration with ``tol = 0.1`` is enough since the
    outer loop will re-form the RHS anyway.
    """
    n = A.shape[0]
    rho_old = 1.0
    iter_count = 0

    # r = rhs - A · x
    r = rhs - A @ x
    res0 = math.sqrt(float(r @ r)) / n
    res = res0
    p = np.zeros(n, dtype=np.float64)

    while iter_count < maxit and res > tol * res0:
        iter_count += 1
        # Apply diagonal preconditioner: z = M⁻¹ · r.
        z = r * precon
        rho = float(r @ z)

        if iter_count > 1:
            beta = rho / rho_old
            p = z + beta * p
        else:
            p = z.copy()

        q = A @ p
        pq = float(p @ q)
        if pq == 0.0:
            break  # CG breakdown — the system is singular along p.
        alpha = rho / pq

        x += alpha * p
        r -= alpha * q

        res = math.sqrt(float(r @ r)) / n
        rho_old = rho

    return res


def sparse_matrix_solve(
    A: sp.csr_matrix,
    x0: np.ndarray,
    rhs: np.ndarray,
    tol: float = 0.01,
    maxit: Optional[int] = None,
) -> float:
    """Multi-dimensional CG solve: ``A · x = rhs`` per dimension.

    Mirrors C ``SparseMatrix_solve`` (sparse_solve.c:137).

    Parameters
    ----------
    A : csr_matrix, shape (n, n)
        Symmetric positive (semi-)definite matrix; stress-
        majorization's ``Lw`` qualifies.
    x0 : ndarray, shape (n, dim)
        Initial guess.  *Not* modified — used only to seed the
        CG iteration.
    rhs : ndarray, shape (n, dim)
        Right-hand side.  Modified in place: on return, holds
        the solution vector for each dim.  This matches C's
        contract — ``rhs`` doubles as the output buffer.
    tol : float
        Relative residual tolerance.
    maxit : int, optional
        Max CG iterations per dimension.  Defaults to
        ``floor(sqrt(n))`` — what C uses.

    Returns
    -------
    float
        Sum of final residuals across dims.
    """
    n = A.shape[0]
    if maxit is None:
        maxit = int(math.floor(math.sqrt(n)))
    precon = _diag_precon_new(A)
    res = 0.0
    dim = x0.shape[1]
    for k in range(dim):
        x = x0[:, k].copy()
        b = rhs[:, k].copy()
        res += _conjugate_gradient(A, precon, x, b, tol, maxit)
        rhs[:, k] = x
    return res
