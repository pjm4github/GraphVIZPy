"""Recursive spline fit through polygonal barriers.

C analogue: ``lib/pathplan/route.c``.

This module lands in **three sub-passes** (Phase B steps B5a, B5b, B5d):

- **B5a + B5b** (this commit) — pure-math foundations: vector
  arithmetic (:func:`add`, :func:`sub`, :func:`dist`, :func:`scale`,
  :func:`dot`, :func:`normv`), Bernstein basis polynomials
  (:func:`B0`–:func:`B3`, :func:`B01`, :func:`B23`), polynomial
  helpers (:func:`points2coeff`, :func:`addroot`), the least-squares
  cubic-Bezier fit (:func:`mkspline`) and piecewise polyline length
  (:func:`dist_n`).
- **B5c** — :func:`splineintersectsline` (cubic × line-segment
  intersection using ``solve3`` from step B1).
- **B5d** — recursive core: :func:`splinefits`,
  :func:`reallyroutespline`, and the public entry point
  :func:`Proutespline`.

All functions are literal transliterations of the C source.  The
``static`` keyword in C gives file-scope access control; Python has
no equivalent, so private helpers are module-level but not
re-exported from ``pathplan/__init__.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint, Pvector
from gvpy.engines.layout.dot.pathplan.solvers import solve3


# ── Constants ──────────────────────────────────────────────────────
# C analogue: ``route.c:22``.
EPSILON2 = 1e-6


# ── Tna type ───────────────────────────────────────────────────────
# C analogue: ``route.c:24-27``::
#
#     typedef struct tna_t {
#         double t;
#         Ppoint_t a[2];
#     } tna_t;
#
# Used by mkspline to carry per-sample parameter ``t`` and the two
# basis-weighted tangent vectors ``a[0]``, ``a[1]``.

@dataclass
class Tna:
    """Sample + tangent pair used during least-squares Bezier fit."""

    t: float = 0.0
    a: list = field(default_factory=lambda: [Ppoint(0.0, 0.0), Ppoint(0.0, 0.0)])


# ── Vector math (B5a) ──────────────────────────────────────────────

def add(p1: Ppoint, p2: Ppoint) -> Ppoint:
    """Vector addition.

    C analogue: ``route.c:add`` lines 431-435::

        static Ppoint_t add(Ppoint_t p1, Ppoint_t p2) {
            p1.x += p2.x, p1.y += p2.y;
            return p1;
        }

    Python returns a fresh :class:`Ppoint` to avoid accidental
    mutation of the caller's copy (C's value-semantics give the
    same behaviour via struct copy).
    """
    return Ppoint(p1.x + p2.x, p1.y + p2.y)


def sub(p1: Ppoint, p2: Ppoint) -> Ppoint:
    """Vector subtraction ``p1 - p2``.

    C analogue: ``route.c:sub`` lines 437-441.
    """
    return Ppoint(p1.x - p2.x, p1.y - p2.y)


def dist(p1: Ppoint, p2: Ppoint) -> float:
    """Euclidean distance via ``math.hypot``.

    C analogue: ``route.c:dist`` lines 443-449::

        static double dist(Ppoint_t p1, Ppoint_t p2) {
            double dx = p2.x - p1.x, dy = p2.y - p1.y;
            return hypot(dx, dy);
        }

    This is a separate function from ``visibility.dist`` in the
    Python port — the C source has ``static`` copies in each of
    ``visibility.c`` and ``route.c``.  Both compute the same value;
    we preserve the file split for port fidelity.
    """
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    return math.hypot(dx, dy)


def scale(p: Ppoint, c: float) -> Ppoint:
    """Scalar multiplication ``p * c``.

    C analogue: ``route.c:scale`` lines 451-455.
    """
    return Ppoint(p.x * c, p.y * c)


def dot(p1: Ppoint, p2: Ppoint) -> float:
    """2D dot product.

    C analogue: ``route.c:dot`` lines 457-460.
    """
    return p1.x * p2.x + p1.y * p2.y


def normv(v: Pvector) -> Pvector:
    """Normalise a vector to unit length, or return it unchanged if tiny.

    C analogue: ``route.c:normv`` lines 409-419::

        static Pvector_t normv(Pvector_t v) {
            double d = v.x * v.x + v.y * v.y;
            if (d > 1e-6) {
                d = sqrt(d);
                v.x /= d, v.y /= d;
            }
            return v;
        }

    The ``d > 1e-6`` guard preserves zero (and near-zero) vectors
    without dividing by zero.  Python returns a fresh :class:`Ppoint`
    to match C's value semantics.
    """
    d = v.x * v.x + v.y * v.y
    if d > 1e-6:
        d = math.sqrt(d)
        return Ppoint(v.x / d, v.y / d)
    return Ppoint(v.x, v.y)


# ── Bernstein basis polynomials (B5a) ──────────────────────────────
# C analogue: ``route.c:462-495``.
#
# Standard cubic Bernstein basis::
#
#     B(t) = B0(t) * P0 + B1(t) * P1 + B2(t) * P2 + B3(t) * P3
#
# where ``B0 = (1-t)^3``, ``B1 = 3t(1-t)^2``, ``B2 = 3t^2(1-t)``,
# ``B3 = t^3``.
#
# ``B01`` and ``B23`` are convenience combinations used by
# :func:`mkspline` — they fold the fixed endpoint contributions
# (``P0`` and ``P3``) into single weights so the fit can solve for
# only the interior tangent magnitudes ``scale0`` / ``scale3``.


def B0(t: float) -> float:
    """``(1-t)^3``.  C analogue: ``route.c:462-466``."""
    tmp = 1.0 - t
    return tmp * tmp * tmp


def B1(t: float) -> float:
    """``3t(1-t)^2``.  C analogue: ``route.c:468-472``."""
    tmp = 1.0 - t
    return 3 * t * tmp * tmp


def B2(t: float) -> float:
    """``3t^2(1-t)``.  C analogue: ``route.c:474-478``."""
    tmp = 1.0 - t
    return 3 * t * t * tmp


def B3(t: float) -> float:
    """``t^3``.  C analogue: ``route.c:480-483``."""
    return t * t * t


def B01(t: float) -> float:
    """``(1-t)^2 ((1-t) + 3t)`` — combined ``B0 + B1`` weight.

    C analogue: ``route.c:485-489``::

        static double B01(double t) {
            double tmp = 1.0 - t;
            return tmp * tmp * (tmp + 3 * t);
        }

    Algebraically equivalent to ``B0(t) + B1(t) * (v1/v0)`` for
    ``v1 = (2/3) * v0`` — the combination used by ``mkspline`` to
    carry the endpoint's contribution to an interior sample.
    """
    tmp = 1.0 - t
    return tmp * tmp * (tmp + 3 * t)


def B23(t: float) -> float:
    """``t^2 (3(1-t) + t)`` — combined ``B2 + B3`` weight.

    C analogue: ``route.c:491-495``.  Mirror image of :func:`B01`.
    """
    tmp = 1.0 - t
    return t * t * (3 * tmp + t)


# ── Polynomial / root helpers (B5a) ────────────────────────────────

def points2coeff(v0: float, v1: float, v2: float, v3: float) -> list[float]:
    """Convert cubic Bezier control-point values to polynomial coefficients.

    C analogue: ``route.c:points2coeff`` lines 394-401::

        static void points2coeff(double v0, double v1, double v2,
                                 double v3, double *coeff) {
            coeff[3] = v3 + 3 * v1 - (v0 + 3 * v2);
            coeff[2] = 3 * v0 + 3 * v2 - 6 * v1;
            coeff[1] = 3 * (v1 - v0);
            coeff[0] = v0;
        }

    Python deviation: returns a fresh ``list[float]`` of length 4
    in the same ``[c0, c1, c2, c3]`` order C writes to its out-
    parameter ``coeff[]``.  Layout matches
    :func:`...solvers.solve3`'s coefficient convention (constant
    term first).
    """
    coeff = [0.0, 0.0, 0.0, 0.0]
    coeff[3] = v3 + 3 * v1 - (v0 + 3 * v2)
    coeff[2] = 3 * v0 + 3 * v2 - 6 * v1
    coeff[1] = 3 * (v1 - v0)
    coeff[0] = v0
    return coeff


def addroot(root: float, roots: list[float]) -> None:
    """Append ``root`` to ``roots`` if it lies in the closed interval ``[0, 1]``.

    C analogue: ``route.c:addroot`` lines 403-407::

        static void addroot(double root, double *roots, int *rootnp) {
            if (root >= 0 && root <= 1)
                roots[*rootnp] = root, (*rootnp)++;
        }

    Python deviation: C uses ``rootnp`` as an out-parameter for the
    count; Python mutates the ``roots`` list directly via ``append``.
    The caller inspects ``len(roots)`` in place of C's ``*rootnp``.
    """
    if 0 <= root <= 1:
        roots.append(root)


# ── dist_n (B5b) ────────────────────────────────────────────────────

def dist_n(p: list, n: int) -> float:
    """Piecewise polyline length — sum of segment distances ``p[0]..p[n-1]``.

    C analogue: ``route.c:dist_n`` lines 200-210::

        static double dist_n(Ppoint_t *p, int n) {
            double rv = 0.0;
            for (int i = 1; i < n; i++)
                rv += hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y);
            return rv;
        }
    """
    rv = 0.0
    for i in range(1, n):
        rv += math.hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y)
    return rv


# ── mkspline (B5b) ─────────────────────────────────────────────────

def mkspline(inps: list, inpn: int, tnas: list,
             ev0: Pvector, ev1: Pvector) -> tuple:
    """Least-squares cubic Bezier fit through ``inps[0..inpn-1]``.

    C analogue: ``route.c:mkspline`` lines 159-198.  C signature::

        static int mkspline(Ppoint_t *inps, int inpn, const tna_t *tnas,
                            Ppoint_t ev0, Ppoint_t ev1,
                            Ppoint_t *sp0, Ppoint_t *sv0,
                            Ppoint_t *sp1, Ppoint_t *sv1);

    Python returns the four output points as a tuple
    ``(sp0, sv0, sp1, sv1)`` instead of C's four out-parameters.

    The algorithm fits a cubic Bezier whose endpoint positions are
    pinned to ``inps[0]`` and ``inps[inpn - 1]`` and whose endpoint
    tangent *directions* are fixed to ``ev0`` and ``ev1`` (the
    caller-supplied unit tangents).  Only the two tangent
    *magnitudes* ``scale0`` and ``scale3`` are free parameters.
    Those are found by solving a 2×2 normal-equations system from
    the per-sample ``tna_t`` basis data.

    Fallback when the system is singular (``|det01| < 1e-6``) or
    produces non-positive scales: use ``d01 / 3`` where ``d01`` is
    the distance between the two endpoints — a generic "inflate
    tangents to one-third the chord length" heuristic.

    Returns ``(sp0, sv0, sp1, sv1)`` where:

    - ``sp0`` is the first control point (== ``inps[0]``).
    - ``sv0`` is the first tangent vector (``ev0 * scale0``).
    - ``sp1`` is the last control point (== ``inps[inpn - 1]``).
    - ``sv1`` is the last tangent vector (``ev1 * scale3``).
    """
    # 2×2 normal-equations matrix and RHS.
    c = [[0.0, 0.0], [0.0, 0.0]]
    x = [0.0, 0.0]
    scale0 = 0.0
    scale3 = 0.0

    # Accumulate Gram matrix + right-hand side over every sample.
    for i in range(inpn):
        c[0][0] += dot(tnas[i].a[0], tnas[i].a[0])
        c[0][1] += dot(tnas[i].a[0], tnas[i].a[1])
        c[1][0] = c[0][1]
        c[1][1] += dot(tnas[i].a[1], tnas[i].a[1])
        # tmp = inps[i] - (inps[0] * B01(t) + inps[n-1] * B23(t))
        tmp = sub(
            inps[i],
            add(
                scale(inps[0], B01(tnas[i].t)),
                scale(inps[inpn - 1], B23(tnas[i].t)),
            ),
        )
        x[0] += dot(tnas[i].a[0], tmp)
        x[1] += dot(tnas[i].a[1], tmp)

    # Cramer's rule on a 2×2 system.
    det01 = c[0][0] * c[1][1] - c[1][0] * c[0][1]
    det0X = c[0][0] * x[1] - c[0][1] * x[0]
    detX1 = x[0] * c[1][1] - x[1] * c[0][1]

    if abs(det01) >= 1e-6:
        scale0 = detX1 / det01
        scale3 = det0X / det01

    # Fallback when the system is singular or the solution is bogus.
    if abs(det01) < 1e-6 or scale0 <= 0.0 or scale3 <= 0.0:
        d01 = dist(inps[0], inps[inpn - 1]) / 3.0
        scale0 = d01
        scale3 = d01

    sp0 = inps[0]
    sv0 = scale(ev0, scale0)
    sp1 = inps[inpn - 1]
    sv1 = scale(ev1, scale3)
    return (sp0, sv0, sp1, sv1)


# ── splineintersectsline (B5c) ─────────────────────────────────────

def splineintersectsline(sps: list, lps: list) -> tuple[int, list]:
    """Find cubic-Bezier × line-segment intersection parameters.

    C analogue: ``route.c:splineintersectsline`` lines 314-392.
    C signature::

        static int splineintersectsline(Ppoint_t *sps, Ppoint_t *lps,
                                        double *roots);

    Python deviation: C uses an out-parameter ``roots[4]`` and
    returns the count; Python returns a tuple ``(count, roots)``.

    The ``count == 4`` sentinel is preserved: it signals that the
    cubic lies *entirely* on the line (degenerate), so every
    parameter ``t ∈ [0, 1]`` is an intersection.  In that case the
    returned list is empty — callers distinguish the "all roots"
    case by checking ``count == 4`` first.

    Arguments:
        sps: 4-element list of :class:`Ppoint` — cubic control points.
        lps: 2-element list of :class:`Ppoint` — line segment endpoints.

    Returns:
        ``(count, roots)`` where ``roots`` is a list of ``t ∈ [0, 1]``
        parameter values at which the cubic crosses the segment.
        Both the curve parameter ``t`` AND the segment parameter ``s``
        are checked to be in ``[0, 1]`` before a root is accepted
        (C calls this "the intersection lies on the segment, not
        the extended line").

    Three internal cases (preserved from C):

    1. **Degenerate line (point)** — both ``dx == 0`` and ``dy == 0``.
       The "line" is a single point.  Solve ``x(t) = lps[0].x`` and
       ``y(t) = lps[0].y`` as two separate cubics; the common roots
       are the intersection parameters.  Either solve may return
       ``4`` (identically zero — every ``t`` is a root of that
       dimension); the combining logic preserves C's behaviour.
    2. **Vertical line** — ``dx == 0`` but ``dy != 0``.  Solve
       ``x(t) = lps[0].x`` (constant x), then for each root
       ``tv`` check that the corresponding ``y(tv)`` maps to a
       segment parameter ``sv ∈ [0, 1]``.
    3. **General line** — ``dx != 0``.  Transform coordinates by
       subtracting ``rat * x`` from each ``y`` so the line becomes
       horizontal, build the resulting cubic, solve, and verify the
       segment parameter via ``x(tv)``.
    """
    # xcoeff/ycoeff: parameterise the line as
    #   x(s) = xcoeff[0] + s * xcoeff[1]
    #   y(s) = ycoeff[0] + s * ycoeff[1]
    xcoeff = [lps[0].x, lps[1].x - lps[0].x]
    ycoeff = [lps[0].y, lps[1].y - lps[0].y]

    roots: list[float] = []

    if xcoeff[1] == 0:
        if ycoeff[1] == 0:
            # Case 1: degenerate line is a single point.  Solve x(t) = px
            # and y(t) = py as two separate cubics.
            scoeff = points2coeff(sps[0].x, sps[1].x, sps[2].x, sps[3].x)
            scoeff[0] -= xcoeff[0]
            xrootn, xroots = solve3(scoeff)
            scoeff = points2coeff(sps[0].y, sps[1].y, sps[2].y, sps[3].y)
            scoeff[0] -= ycoeff[0]
            yrootn, yroots = solve3(scoeff)

            # C's conditional cascade combining x- and y-roots:
            #   if xrootn == 4 and yrootn == 4 → return 4 (all t match)
            #   if xrootn == 4 → use yroots
            #   if yrootn == 4 → use xroots
            #   otherwise → intersection of xroots ∩ yroots
            if xrootn == 4:
                if yrootn == 4:
                    return (4, [])
                for r in yroots:
                    addroot(r, roots)
            elif yrootn == 4:
                for r in xroots:
                    addroot(r, roots)
            else:
                for xr in xroots:
                    for yr in yroots:
                        if xr == yr:
                            addroot(xr, roots)
            return (len(roots), roots)
        else:
            # Case 2: vertical line — dx == 0, dy != 0.
            # Solve x(t) = xcoeff[0] (the constant x of the line),
            # then for each root check that y(t) is within the
            # segment's y range (parameterised as sv in [0, 1]).
            scoeff = points2coeff(sps[0].x, sps[1].x, sps[2].x, sps[3].x)
            scoeff[0] -= xcoeff[0]
            xrootn, xroots = solve3(scoeff)
            if xrootn == 4:
                return (4, [])
            for tv in xroots:
                if 0 <= tv <= 1:
                    # Evaluate y(tv) via Horner on a freshly built
                    # cubic polynomial in the y component.
                    scoeff_y = points2coeff(
                        sps[0].y, sps[1].y, sps[2].y, sps[3].y)
                    sv = (scoeff_y[0]
                          + tv * (scoeff_y[1]
                                  + tv * (scoeff_y[2]
                                          + tv * scoeff_y[3])))
                    sv = (sv - ycoeff[0]) / ycoeff[1]
                    if 0 <= sv <= 1:
                        addroot(tv, roots)
            return (len(roots), roots)
    else:
        # Case 3: general non-vertical line.
        # Rotate coordinates so the line becomes horizontal.  The
        # transformation is y' = y - rat * x where rat = dy/dx.  Then
        # the line becomes y' = ycoeff[0] - rat * xcoeff[0], a constant.
        rat = ycoeff[1] / xcoeff[1]
        scoeff = points2coeff(
            sps[0].y - rat * sps[0].x,
            sps[1].y - rat * sps[1].x,
            sps[2].y - rat * sps[2].x,
            sps[3].y - rat * sps[3].x,
        )
        scoeff[0] += rat * xcoeff[0] - ycoeff[0]
        xrootn, xroots = solve3(scoeff)
        if xrootn == 4:
            return (4, [])
        for tv in xroots:
            if 0 <= tv <= 1:
                # Evaluate x(tv) and back out the segment parameter sv.
                scoeff_x = points2coeff(
                    sps[0].x, sps[1].x, sps[2].x, sps[3].x)
                sv = (scoeff_x[0]
                      + tv * (scoeff_x[1]
                              + tv * (scoeff_x[2]
                                      + tv * scoeff_x[3])))
                sv = (sv - xcoeff[0]) / xcoeff[1]
                if 0 <= sv <= 1:
                    addroot(tv, roots)
        return (len(roots), roots)
