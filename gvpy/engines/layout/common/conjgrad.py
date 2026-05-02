"""Conjugate-gradient solver for symmetric positive-semidefinite
systems stored in packed upper-triangular form.

Mirrors ``conjugate_gradient_mkernel`` from
``lib/neatogen/conjgrad.c:162``.  The Laplacian has a one-dimensional
nullspace (the all-ones vector) so each CG iteration projects the
search vectors onto its orthogonal complement via :func:`orthog1`.

This module is engine-agnostic — placed in ``common/`` because both
neato (stress majorization) and a future fdp port will use it.
"""
from __future__ import annotations

import numpy as np

from gvpy.engines.layout.common.laplacian import (
    orthog1,
    right_mult_packed,
)


def conjugate_gradient_mkernel(A: np.ndarray, x: np.ndarray,
                               b: np.ndarray, n: int,
                               tol: float,
                               max_iterations: int) -> int:
    """Solve ``A x = b`` for symmetric ``A`` (packed upper-tri form).

    ``x`` is updated in place from its initial guess.  Returns 0 on
    success, 1 if a zero-length residual is encountered (a numerical
    edge case the C reference also reports as a non-fatal warning).

    Both ``x`` and ``b`` are centred (orthogonalised against the
    all-ones vector) before iteration to remove the Laplacian's
    null component.
    """
    orthog1(x)
    orthog1(b)

    Ax = right_mult_packed(A, n, x)
    orthog1(Ax)

    r = b - Ax
    p = r.copy()

    r_r = float(np.dot(r, r))
    rv = 0

    for i in range(max_iterations):
        if float(np.max(np.abs(r))) <= tol:
            break

        orthog1(p)
        orthog1(x)
        orthog1(r)

        Ap = right_mult_packed(A, n, p)
        orthog1(Ap)

        p_Ap = float(np.dot(p, Ap))
        if p_Ap == 0:
            break
        alpha = r_r / p_Ap

        # x += alpha * p
        x += alpha * p

        if i < max_iterations - 1:
            # r -= alpha * Ap
            r -= alpha * Ap

            r_r_new = float(np.dot(r, r))

            if r_r == 0:
                rv = 1
                break

            beta = r_r_new / r_r
            r_r = r_r_new

            # p = beta * p + r
            p = beta * p + r

    return rv
