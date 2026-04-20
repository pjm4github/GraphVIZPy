"""Stateless spline / polyline helpers shared across layout engines.

See: /lib/common/splines.c
See: /lib/pathplan/util.c @ 44   (make_polyline counterpart)
See: /lib/common/routespl.c @ 1  (mkspline / reallyroutespline —
                                   Schneider curve fit that ``to_bezier``
                                   reimplements)

Both functions below are pure geometry — they take polyline input and
return polyline / bezier output with no reference to a :class:`Graph`,
:class:`LayoutEdge`, or any other engine state.  That's what makes
them safe to share.

``to_bezier`` is the Schneider recursive cubic fit used by dot's Phase
4 polyline-to-bezier pass; ``make_polyline`` expands each interior
point in a polyline to the triple-copy layout Graphviz's cubic format
expects.
"""
from __future__ import annotations

import math

from gvpy.engines.layout.common.geom import Ppolyline


def make_polyline(line: Ppolyline) -> Ppolyline:
    """Expand a polyline into a bezier-ready control-point sequence.

    See: /lib/pathplan/util.c @ 44

    Each interior point of the input line is duplicated three times
    and the endpoints twice, producing the ``[P0, P0, P1, P1, P1, …,
    Pn, Pn]`` layout that Graphviz's cubic-Bezier format expects.

    Python deviation: C uses a ``static LIST(Ppoint_t) ispline`` which
    is cleared between calls — a thread-unsafe optimisation.  Python
    returns a fresh :class:`Ppolyline` on every call.
    """
    if line.pn == 0:
        return Ppolyline(ps=[])
    ispline: list = []
    i = 0
    ispline.append(line.ps[i])
    ispline.append(line.ps[i])
    i += 1
    while i + 1 < line.pn:
        ispline.append(line.ps[i])
        ispline.append(line.ps[i])
        ispline.append(line.ps[i])
        i += 1
    ispline.append(line.ps[i])
    ispline.append(line.ps[i])
    return Ppolyline(ps=ispline)


def to_bezier(pts: list[tuple]) -> list[tuple]:
    """Convert a polyline to smooth cubic Bezier control points.

    Uses Schneider's recursive curve-fitting algorithm:

    1. Parameterize points by chord-length fraction.
    2. Estimate end tangents from neighboring points.
    3. Fit a cubic Bezier via least-squares tangent scaling.
    4. If max deviation > tolerance, split at worst point and recurse.

    Mirrors Graphviz ``routespl.c:mkspline()`` / ``reallyroutespline()``.

    Input:  ``[P0, P1, ..., Pn]``  (polyline waypoints)
    Output: ``[P0, C1, C2, P1, C3, C4, P2, ...]``  (cubic Bezier segments)
    """
    n = len(pts)
    if n <= 1:
        return list(pts)
    if n == 2:
        p0, p1 = pts
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        return [p0, (p0[0] + dx / 3, p0[1] + dy / 3),
                (p0[0] + 2 * dx / 3, p0[1] + 2 * dy / 3), p1]

    def _dist(a, b):
        return math.hypot(b[0] - a[0], b[1] - a[1])

    def _normalize(v):
        d = math.hypot(v[0], v[1])
        return (v[0] / d, v[1] / d) if d > 1e-9 else (0.0, 0.0)

    def _bezier_pt(p0, p1, p2, p3, t):
        s = 1 - t
        return (s*s*s*p0[0] + 3*s*s*t*p1[0] + 3*s*t*t*p2[0] + t*t*t*p3[0],
                s*s*s*p0[1] + 3*s*s*t*p1[1] + 3*s*t*t*p2[1] + t*t*t*p3[1])

    def _fit_cubic(points, t_params, ev0, ev1):
        """Schneider least-squares cubic fit with fixed tangent dirs."""
        p0 = points[0]
        p3 = points[-1]
        n = len(points)

        c00 = c01 = c10 = c11 = 0.0
        x0 = x1 = 0.0
        for i in range(n):
            t = t_params[i]
            s = 1 - t
            b1 = 3 * s * s * t
            b2 = 3 * s * t * t
            a1 = (ev0[0] * b1, ev0[1] * b1)
            a2 = (ev1[0] * b2, ev1[1] * b2)
            c00 += a1[0]*a1[0] + a1[1]*a1[1]
            c01 += a1[0]*a2[0] + a1[1]*a2[1]
            c11 += a2[0]*a2[0] + a2[1]*a2[1]
            b0 = s*s*s
            b3 = t*t*t
            tmp = (points[i][0] - b0*p0[0] - b3*p3[0],
                   points[i][1] - b0*p0[1] - b3*p3[1])
            x0 += a1[0]*tmp[0] + a1[1]*tmp[1]
            x1 += a2[0]*tmp[0] + a2[1]*tmp[1]
        c10 = c01

        det = c00*c11 - c01*c10
        if abs(det) < 1e-12:
            d = _dist(p0, p3) / 3.0
            return (p0, (p0[0]+ev0[0]*d, p0[1]+ev0[1]*d),
                    (p3[0]+ev1[0]*d, p3[1]+ev1[1]*d), p3)

        alpha0 = (x0*c11 - x1*c01) / det
        alpha1 = (c00*x1 - c10*x0) / det

        # Sanity bounds.  ``alpha`` is the tangent-vector scale factor;
        # geometrically reasonable values are roughly chord/3 to a small
        # multiple of the chord length.  Below ``eps`` the system was
        # near-degenerate (recover with chord/3); above ``max_alpha``
        # the matrix was technically non-singular but ill-conditioned
        # enough that the solution extrapolates wildly off-canvas.
        # Both fall back to the chord/3 heuristic — matches Graphviz
        # routespl.c:mkspline() which clamps via the same path.
        d = _dist(p0, p3)
        eps = d * 1e-6
        max_alpha = 2.0 * d if d > 0 else 0.0
        if (alpha0 < eps or alpha1 < eps
                or alpha0 > max_alpha or alpha1 > max_alpha):
            alpha0 = alpha1 = d / 3.0

        return (p0,
                (p0[0]+ev0[0]*alpha0, p0[1]+ev0[1]*alpha0),
                (p3[0]+ev1[0]*alpha1, p3[1]+ev1[1]*alpha1),
                p3)

    def _max_error(points, t_params, bezier):
        """Return (max_dist, index_of_worst)."""
        worst_d = 0.0
        worst_i = 0
        for i in range(len(points)):
            bp = _bezier_pt(*bezier, t_params[i])
            d = _dist(points[i], bp)
            if d > worst_d:
                worst_d = d
                worst_i = i
        return worst_d, worst_i

    def _fit_recursive(points, ev0, ev1, depth=0):
        """Recursively fit cubics, splitting at worst-fit point."""
        n = len(points)
        if n <= 2:
            p0, p1 = points[0], points[-1]
            dx, dy = p1[0]-p0[0], p1[1]-p0[1]
            return [p0, (p0[0]+dx/3, p0[1]+dy/3),
                    (p0[0]+2*dx/3, p0[1]+2*dy/3), p1]
        if n == 3:
            # Only one interior sample point — the 2x2 normal-equations
            # system in _fit_cubic is underdetermined and can produce
            # wildly extrapolated alpha values when the basis vectors
            # become near-collinear.  Skip the least-squares fit and
            # use the standard chord/3 tangent-length heuristic
            # (matches Graphviz routespl.c:mkspline()'s short-polyline
            # fallback path).
            p0, p3 = points[0], points[-1]
            d = _dist(p0, p3) / 3.0
            return [p0,
                    (p0[0] + ev0[0]*d, p0[1] + ev0[1]*d),
                    (p3[0] + ev1[0]*d, p3[1] + ev1[1]*d),
                    p3]

        # Chord-length parameterization
        dists = [0.0]
        for i in range(1, n):
            dists.append(dists[-1] + _dist(points[i-1], points[i]))
        total = dists[-1]
        if total < 1e-9:
            return [points[0], points[0], points[-1], points[-1]]
        t_params = [d / total for d in dists]

        bezier = _fit_cubic(points, t_params, ev0, ev1)
        err, split_i = _max_error(points, t_params, bezier)

        tolerance = 4.0  # 4pt tolerance
        if err <= tolerance or depth > 8 or n <= 3:
            return list(bezier)

        # Split at worst point and recurse
        split_i = max(1, min(split_i, n - 2))
        sp = points[split_i]
        # Tangent at split point: direction between neighbors
        if split_i > 0 and split_i < n - 1:
            mid_tan = _normalize((points[split_i+1][0] - points[split_i-1][0],
                                  points[split_i+1][1] - points[split_i-1][1]))
        else:
            mid_tan = _normalize((points[-1][0] - points[0][0],
                                  points[-1][1] - points[0][1]))
        neg_tan = (-mid_tan[0], -mid_tan[1])

        left = _fit_recursive(points[:split_i+1], ev0, neg_tan, depth+1)
        right = _fit_recursive(points[split_i:], mid_tan, ev1, depth+1)
        return left + right[1:]  # skip duplicate split point

    # Estimate end tangents
    ev0 = _normalize((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
    ev1 = _normalize((pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1]))

    return _fit_recursive(list(pts), ev0, ev1)
