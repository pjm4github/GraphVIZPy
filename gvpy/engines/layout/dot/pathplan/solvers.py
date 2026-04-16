"""Real-root finders for polynomials of degree 1, 2, and 3.

C analogue: ``lib/pathplan/solvers.c`` lines 26–105.  Used by
``splineintersectsline`` in ``route.c`` to detect cubic-vs-line
intersections during spline fitting through barriers.

Python API deviation
--------------------
C uses in-out parameters::

    int solve3(double *coeff, double *roots);

with ``roots`` pointing at a caller-allocated buffer and the return
value indicating how many real roots were found (1, 2, or 3), or 0 for
no roots, or 4 as a sentinel for a degenerate equation (``0 = 0``).

Python uses a tuple return instead::

    n, roots = solve3(coeff)

- ``n == 1|2|3``: number of real roots in ``roots[0..n-1]``
- ``n == 0``: no real roots (coefficients describe ``c == 0`` where
  ``c`` is nonzero, or a quadratic with negative discriminant)
- ``n == 4``: degenerate equation (``0 == 0``) — caller must handle
  specially (infinite roots).  Preserved from C so downstream callers
  can recognise the same sentinel.

Coefficient convention
----------------------
``coeff[i]`` is the coefficient of ``x^i``.  Example: a cubic
``a x^3 + b x^2 + c x + d`` is passed as ``[d, c, b, a]``.  This
matches C's original layout where ``coeff[0]`` is the constant term.
"""
from __future__ import annotations

import math

# C: ``#define EPS 1E-7`` and ``#define AEQ0(x) ((x < EPS) && (x > -EPS))``
_EPS = 1e-7


def _aeq0(x: float) -> bool:
    """Approximate zero test.  C analogue: ``AEQ0`` macro."""
    return -_EPS < x < _EPS


def solve1(coeff: list[float]) -> tuple[int, list[float]]:
    """Solve ``coeff[1]*x + coeff[0] == 0`` for real ``x``.

    C analogue: ``solvers.c:solve1`` lines 92–105.  Returns:
    - ``(1, [root])`` for a single real root
    - ``(0, [])`` when the leading coefficient is ~0 and the constant
      is nonzero (``c == 0`` for nonzero ``c``)
    - ``(4, [])`` when both coefficients are ~0 (``0 == 0``, degenerate)
    """
    a = coeff[1]
    b = coeff[0]
    if _aeq0(a):
        if _aeq0(b):
            return (4, [])
        return (0, [])
    return (1, [-b / a])


def solve2(coeff: list[float]) -> tuple[int, list[float]]:
    """Solve ``coeff[2]*x^2 + coeff[1]*x + coeff[0] == 0``.

    C analogue: ``solvers.c:solve2`` lines 69–90.  Falls back to
    :func:`solve1` when the leading coefficient is ~0.
    """
    a = coeff[2]
    b = coeff[1]
    c = coeff[0]
    if _aeq0(a):
        return solve1(coeff)
    b_over_2a = b / (2 * a)
    c_over_a = c / a
    disc = b_over_2a * b_over_2a - c_over_a
    if disc < 0:
        return (0, [])
    if disc > 0:
        root0 = -b_over_2a + math.sqrt(disc)
        root1 = -2 * b_over_2a - root0
        return (2, [root0, root1])
    return (1, [-b_over_2a])


def solve3(coeff: list[float]) -> tuple[int, list[float]]:
    """Solve ``coeff[3]*x^3 + coeff[2]*x^2 + coeff[1]*x + coeff[0] == 0``.

    C analogue: ``solvers.c:solve3`` lines 26–67.  Uses the
    depressed-cubic + trigonometric method (casus irreducibilis
    handled via ``atan2`` / ``cbrt``).  Falls back to :func:`solve2`
    when the leading coefficient is ~0.
    """
    a = coeff[3]
    b = coeff[2]
    c = coeff[1]
    d = coeff[0]
    if _aeq0(a):
        return solve2(coeff)
    b_over_3a = b / (3 * a)
    c_over_a = c / a
    d_over_a = d / a

    p = b_over_3a * b_over_3a
    q = 2 * b_over_3a * p - b_over_3a * c_over_a + d_over_a
    p = c_over_a / 3 - p
    disc = q * q + 4 * p * p * p

    roots = [0.0, 0.0, 0.0]
    if disc < 0:
        r = 0.5 * math.sqrt(-disc + q * q)
        theta = math.atan2(math.sqrt(-disc), -q)
        temp = 2 * math.cbrt(r)
        roots[0] = temp * math.cos(theta / 3)
        roots[1] = temp * math.cos((theta + math.pi + math.pi) / 3)
        roots[2] = temp * math.cos((theta - math.pi - math.pi) / 3)
        rootn = 3
    else:
        alpha = 0.5 * (math.sqrt(disc) - q)
        beta = -q - alpha
        roots[0] = math.cbrt(alpha) + math.cbrt(beta)
        if disc > 0:
            rootn = 1
        else:
            roots[1] = roots[2] = -0.5 * roots[0]
            rootn = 3

    # Shift roots back from depressed form.
    for i in range(rootn):
        roots[i] -= b_over_3a

    return (rootn, roots[:rootn])
