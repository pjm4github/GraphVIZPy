"""Engine-agnostic overlap-removal post-pass.

Mirrors ``lib/neatogen/adjust.c``.  C dispatches between several
overlap-removal algorithms based on the ``overlap`` graph
attribute; this Py port matches the dispatch logic across all the
mainline algorithms (scale, scalexy, compress, voronoi/prism,
ortho/portho family).

Originally lived in ``neato/adjust.py``; promoted to ``common/``
so neato, twopi, fdp, and future force-directed engines can share
the same dispatcher.  The accepted ``layout`` argument is
duck-typed: any object with ``lnodes`` (dict of objects with
``x``, ``y``, ``width``, ``height``, ``pinned`` attributes),
``sep`` (float), and ``overlap`` (string) works.

Mode mapping (mirrors ``adjust.c::adjustMode[]`` /
``getAdjustMode``):

================  =================  ============
``overlap=``      C constant         Py status
================  =================  ============
"" / unset         AM_NONE            implemented (no-op)
true               AM_NONE            implemented
false              AM_PRISM (default) Voronoi-based
scale / scaling    AM_NSCALE          Marriott closed-form
scalexy            AM_SCALEXY         Marriott separate-axis
prism / prismN     AM_PRISM           Voronoi-based
voronoi / Voronoi  AM_VOR             Voronoi-based
compress           AM_COMPRESS        Marriott shrink
ortho / portho     AM_ORTHO* /        iterative slide-apart
                   AM_PORTHO*
ipsep              AM_IPSEP           falls back to scale
vpsc               AM_VPSC            falls back to scale
================  =================  ============

Trace tag: ``[TRACE neato_adjust]`` (kept for back-compat — the
adjust pass historically belonged to the neato engine).
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any


# Mirrors ``incr`` (adjust.c:46): each scaling iteration multiplies
# coordinates by 1.05.
_SCALE_INCR = 0.05
_DFLT_SCALE_MAXITER = 200

# Adjustment modes (mirrors enum ``adjust_mode`` in adjust.h).
AM_NONE = "none"
AM_PRISM = "prism"
AM_VOR = "voronoi"
AM_NSCALE = "scale"
AM_SCALEXY = "scalexy"
AM_COMPRESS = "compress"
AM_VPSC = "vpsc"
AM_IPSEP = "ipsep"
AM_ORTHO = "ortho"
AM_ORTHO_YX = "ortho_yx"
AM_ORTHOXY = "orthoxy"
AM_ORTHOYX = "orthoyx"
AM_PORTHO = "portho"
AM_PORTHO_YX = "portho_yx"
AM_PORTHOXY = "porthoxy"
AM_PORTHOYX = "porthoyx"


def _trace(msg: str) -> None:
    """Emit a ``[TRACE neato_adjust]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_NEATO=1``)."""
    if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
        print(f"[TRACE neato_adjust] {msg}", file=sys.stderr)


def _parse_adjust_mode(s: str) -> tuple[str, str]:
    """Map an ``overlap`` attribute value to ``(mode, raw)``.

    Mirrors ``adjust.c::getAdjustMode`` (line 814).  Unset / "true"
    means "overlap is OK, leave it alone" (AM_NONE).  "false" means
    "remove overlap using the default" (AM_PRISM in C).  Named
    modes pass through.

    Returns the canonical mode constant and the original string
    (the latter is preserved so prism/N variants can carry their
    iteration count later).
    """
    if not s:
        return AM_NONE, ""
    raw = s.strip()
    low = raw.lower()

    # Boolean shortcuts.
    if low in ("true", "1", "yes"):
        return AM_NONE, raw
    if low in ("false", "0", "no"):
        return AM_PRISM, raw

    # Named modes (including prism with optional integer suffix).
    named = {
        "scale": AM_NSCALE, "scaling": AM_NSCALE, "oscale": AM_NSCALE,
        "scalexy": AM_SCALEXY,
        "voronoi": AM_VOR,
        "compress": AM_COMPRESS,
        "vpsc": AM_VPSC,
        "ipsep": AM_IPSEP,
        "ortho": AM_ORTHO, "ortho_yx": AM_ORTHO_YX,
        "orthoxy": AM_ORTHOXY, "orthoyx": AM_ORTHOYX,
        "portho": AM_PORTHO, "portho_yx": AM_PORTHO_YX,
        "porthoxy": AM_PORTHOXY, "porthoyx": AM_PORTHOYX,
    }
    if low in named:
        return named[low], raw
    if low.startswith("prism"):
        return AM_PRISM, raw

    # Unknown -> treat as "false" per adjust.c:843.
    return AM_PRISM, raw


def _bbox_of(layout: Any) -> tuple[float, float, float, float]:
    """Return ``(min_x, min_y, max_x, max_y)`` over all nodes."""
    xs, ys = [], []
    for ln in layout.lnodes.values():
        xs.append(ln.x)
        ys.append(ln.y)
    return min(xs), min(ys), max(xs), max(ys)


def _has_overlap(layout: Any, sx: float = 1.0,
                 sy: float = 1.0) -> bool:
    """Return True if any pair of nodes has overlapping bounding
    boxes (axis-aligned, inflated by ``layout.sep``).

    The optional ``sx`` / ``sy`` factors let callers test whether a
    *hypothetical* uniform scale would clear the overlaps without
    mutating the layout.
    """
    nodes = list(layout.lnodes.values())
    sep = layout.sep
    for i in range(len(nodes)):
        a = nodes[i]
        ax, ay, ah_w, ah_h = a.x * sx, a.y * sy, a.width / 2, a.height / 2
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            bx, by = b.x * sx, b.y * sy
            bh_w, bh_h = b.width / 2, b.height / 2
            if (abs(ax - bx) < ah_w + bh_w + sep
                    and abs(ay - by) < ah_h + bh_h + sep):
                return True
    return False


def _pair_min_scales(layout: Any
                     ) -> tuple[list[tuple[float, float]], bool]:
    """Build the per-pair minimum-scale set used by ``scAdjust``.

    Mirrors ``constraint.c::mkOverlapSet`` (line 665) for overlap
    pairs and ``compress`` (line 629) for the no-overlap case.
    Returns ``(pairs, any_overlap)`` where each pair is the
    ``(min_sx, min_sy)`` factor that would just-separate the two
    nodes along that axis.

    For overlap pairs (``any_overlap=True``) the values are
    clamped to ``>= 1.0``: scaling up by less than 1.0 wouldn't
    help.  For the no-overlap case (compress) the values can be
    ``< 1.0``: each pair tells us how far we could shrink before
    that pair would touch.
    """
    nodes = list(layout.lnodes.values())
    sep = layout.sep
    pairs: list[tuple[float, float]] = []
    any_overlap = False
    for i in range(len(nodes)):
        a = nodes[i]
        ah_w = a.width / 2 + sep / 2
        ah_h = a.height / 2 + sep / 2
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            bh_w = b.width / 2 + sep / 2
            bh_h = b.height / 2 + sep / 2
            dx = abs(a.x - b.x)
            dy = abs(a.y - b.y)
            overlap = dx < ah_w + bh_w and dy < ah_h + bh_h
            if overlap:
                any_overlap = True
            sx = float("inf") if dx == 0 else (ah_w + bh_w) / dx
            sy = float("inf") if dy == 0 else (ah_h + bh_h) / dy
            if overlap:
                pairs.append((max(sx, 1.0), max(sy, 1.0)))
            else:
                # Used by compress: how much we could shrink before
                # this pair just touches.
                pairs.append((sx, sy))
    return pairs, any_overlap


def _compute_scale(pairs: list[tuple[float, float]]) -> float:
    """Optimal uniform scale: ``max_pair min(sx, sy)``.

    Mirrors ``constraint.c::computeScale`` (line 743).
    """
    sc = 0.0
    for sx, sy in pairs:
        v = min(sx, sy)
        if v > sc:
            sc = v
    return sc


def _compute_scale_xy(pairs: list[tuple[float, float]]
                      ) -> tuple[float, float]:
    """Optimal separate-axis scale minimising area = sx * sy.

    Mirrors ``constraint.c::computeScaleXY`` (line 704).  The C
    code prepends a sentinel ``(1, +inf)`` to the pair list and
    initialises the right-to-left running ``sy`` max at ``1``;
    these two tricks let the optimiser pick "no x scaling"
    (``sx=1``) or "no y scaling" (``sy=1``) as extreme solutions.

    Sorts pairs by sx ascending; for each candidate index k the
    y-scale must be ``max(sy_i for i >= k)``.  Total area
    ``sx * sy`` is minimised over k.
    """
    if not pairs:
        return 1.0, 1.0
    # Sort by sx ascending; prepend the sentinel after sorting so
    # it stays at index 0.
    sorted_pairs = sorted(pairs, key=lambda p: (p[0], p[1]))
    s = [(1.0, float("inf"))] + sorted_pairs
    n = len(s)
    # max_sy_right[k] = max(sy_i for i > k) with base 1 (mirrors C
    # ``barr[m-1].y = 1`` initialisation).
    max_sy_right = [1.0] * n
    cur = 1.0
    for k in range(n - 1, -1, -1):
        if k + 1 < n:
            cur = max(cur, s[k + 1][1])
        max_sy_right[k] = cur

    best_cost = float("inf")
    best_x = 1.0
    best_y = 1.0
    for k in range(n):
        sx = s[k][0]
        sy = max_sy_right[k]
        cost = sx * sy
        if cost < best_cost:
            best_cost = cost
            best_x = sx
            best_y = sy
    return best_x, best_y


def scale_adjust(layout: Any) -> int:
    """Uniform-scale overlap removal (Marriott closed-form).

    Mirrors ``constraint.c::scAdjust(g, 1)`` (line 767) — the
    algorithm that backs ``overlap=scale``.  Computes the optimal
    single scale factor in O(N²) time and applies it once, so
    "iterations" is 1 if a scale was applied, 0 otherwise.

    Reference: Marriott, Stuckey, Tam, He, "Removing Node
    Overlapping in Graph Layout Using Constrained Optimization"
    (2003).
    """
    if not _has_overlap(layout):
        _trace("scale: no overlap, skip")
        return 0
    pairs, any_overlap = _pair_min_scales(layout)
    if not any_overlap:
        return 0
    overlap_pairs = [p for p in pairs if p[0] >= 1.0 or p[1] >= 1.0]
    s = _compute_scale(overlap_pairs)
    if s <= 1.0:
        _trace(f"scale: computed scale {s:.4f} ≤ 1; no-op")
        return 0
    for ln in layout.lnodes.values():
        if ln.pinned:
            continue
        ln.x *= s
        ln.y *= s
    _trace(f"scale: applied uniform scale {s:.4f}")
    return 1


def scalexy_adjust(layout: Any) -> int:
    """Per-axis scaling overlap removal (Marriott closed-form).

    Mirrors ``constraint.c::scAdjust(g, 0)`` — solves for the
    minimum-area pair ``(sx, sy)`` that satisfies every overlap
    constraint via the sort-based DP in
    ``computeScaleXY`` (line 704).
    """
    if not _has_overlap(layout):
        _trace("scalexy: no overlap, skip")
        return 0
    pairs, any_overlap = _pair_min_scales(layout)
    if not any_overlap:
        return 0
    overlap_pairs = [p for p in pairs if p[0] >= 1.0 or p[1] >= 1.0]
    sx, sy = _compute_scale_xy(overlap_pairs)
    if sx <= 1.0 and sy <= 1.0:
        _trace(f"scalexy: ({sx:.4f}, {sy:.4f}) ≤ 1; no-op")
        return 0
    for ln in layout.lnodes.values():
        if ln.pinned:
            continue
        ln.x *= sx
        ln.y *= sy
    _trace(f"scalexy: applied ({sx:.4f}, {sy:.4f})")
    return 1


def compress_adjust(layout: Any) -> int:
    """Compress an already-non-overlapping layout uniformly.

    Mirrors ``constraint.c::scAdjust(g, -1)`` (line 767, ``equal=-1``)
    via ``compress`` (line 629).  When the layout has no overlap,
    finds the smallest uniform scale factor ``s ≤ 1`` such that
    no pair would overlap, and applies it.  Returns 0 if any
    overlap is currently present (refuses to compress through it),
    1 if a compression was applied.
    """
    pairs, any_overlap = _pair_min_scales(layout)
    if any_overlap:
        _trace("compress: overlap present; skip (matches C behaviour)")
        return 0
    if not pairs:
        return 0
    # max-min: take the most restrictive shrink-to-touch scale.
    s = 0.0
    for sx, sy in pairs:
        v = min(sx, sy)
        if v > s:
            s = v
    if s <= 0 or s >= 1.0:
        _trace(f"compress: scale {s:.4f}; no-op")
        return 0
    for ln in layout.lnodes.values():
        if ln.pinned:
            continue
        ln.x *= s
        ln.y *= s
    _trace(f"compress: applied uniform scale {s:.4f}")
    return 1


def ortho_adjust(layout: Any,
                 axes: str = "both",
                 max_iter: int = 100) -> int:
    """Orthogonal-constraint overlap removal.

    Approximates ``constraint.c::cAdjust`` for the AM_ORTHO* /
    AM_PORTHO* family.  C's implementation solves a per-axis
    constraint optimisation with network simplex; this Py port
    uses a simpler iterative projection — for each overlapping
    pair, slide the pair apart along the chosen axis by the
    minimum amount needed.

    Less optimal than the C QP-style solve (more layout drift),
    but produces non-overlapping output and respects the
    "preserve relative order" property of orthogonal modes.

    ``axes``:
    - ``"x"`` — slide overlap pairs along the X axis only.
    - ``"y"`` — slide along Y only.
    - ``"both"`` (AM_ORTHO/PORTHO default) — alternates.
    """
    iters = 0
    while iters < max_iter:
        nodes = list(layout.lnodes.values())
        moved = False
        sep = layout.sep
        for i in range(len(nodes)):
            a = nodes[i]
            for j in range(i + 1, len(nodes)):
                b = nodes[j]
                dx = b.x - a.x
                dy = b.y - a.y
                ovx = (a.width + b.width) / 2 + sep - abs(dx)
                ovy = (a.height + b.height) / 2 + sep - abs(dy)
                if ovx <= 0 or ovy <= 0:
                    continue
                # Choose axis per mode.
                push_x = axes == "x" or (axes == "both" and ovx <= ovy)
                push_y = axes == "y" or (axes == "both" and not push_x)
                shift = (ovx if push_x else ovy) / 2 + 0.5
                if push_x:
                    sgn = 1.0 if dx >= 0 else -1.0
                    if not a.pinned:
                        a.x -= sgn * shift
                    if not b.pinned:
                        b.x += sgn * shift
                else:
                    sgn = 1.0 if dy >= 0 else -1.0
                    if not a.pinned:
                        a.y -= sgn * shift
                    if not b.pinned:
                        b.y += sgn * shift
                moved = True
        iters += 1
        if not moved:
            break
    _trace(f"ortho({axes}): iters={iters}")
    return iters


def remove_overlap(layout: Any) -> int:
    """Top-level overlap-removal dispatcher.

    Mirrors ``adjust.c::removeOverlapWith`` / ``getAdjustMode``.
    The previous Py implementation had an inverted boolean check
    that caused ``overlap=false`` to skip removal entirely; this
    rewrite fixes the dispatch and aligns with C's semantics.

    Returns the number of iterations performed (0 if no removal
    was needed or applicable).
    """
    if not layout.lnodes or len(layout.lnodes) < 2:
        return 0

    mode, raw = _parse_adjust_mode(layout.overlap)
    _trace(f"dispatch mode={mode} raw={raw!r}")

    if mode == AM_NONE:
        return 0
    if mode == AM_NSCALE:
        return scale_adjust(layout)
    if mode == AM_SCALEXY:
        return scalexy_adjust(layout)
    if mode == AM_COMPRESS:
        return compress_adjust(layout)
    if mode in (AM_PRISM, AM_VOR):
        # §4.N.3.3: Voronoi-based overlap removal serves as our
        # substitute for both AM_PRISM and AM_VOR.  C uses GTS for
        # PRISM when available; we use scipy.spatial.Voronoi for
        # both modes since the qualitative result (non-overlap
        # preserving relative positions) is the same.
        from gvpy.engines.layout.common.voronoi import voronoi_adjust
        return voronoi_adjust(layout)
    # §4.N.3.4 — orthogonal modes.  C uses constraint solvers; this
    # port uses an iterative slide-apart pass.
    if mode in (AM_ORTHO, AM_PORTHO):
        return ortho_adjust(layout, axes="both")
    if mode in (AM_ORTHOXY, AM_PORTHOXY):
        # X first, then Y.
        ortho_adjust(layout, axes="x")
        return ortho_adjust(layout, axes="y")
    if mode in (AM_ORTHOYX, AM_PORTHOYX):
        ortho_adjust(layout, axes="y")
        return ortho_adjust(layout, axes="x")
    if mode in (AM_ORTHO_YX, AM_PORTHO_YX):
        # YX variant: Y first then X (same flow with different
        # constraint relation in C — we approximate with the order
        # swap which is what visibly differs).
        ortho_adjust(layout, axes="y")
        return ortho_adjust(layout, axes="x")
    if mode in (AM_VPSC, AM_IPSEP):
        # IPSEP / VPSC need a quadratic-programming solver
        # (constrained_majorization).  Not implemented; fall back
        # to scale and warn so users see something reasonable.
        print(
            f"warning: overlap={raw!r} requested {mode}; QP solver "
            f"not yet implemented in gvpy; falling back to scale.",
            file=sys.stderr,
        )
        return scale_adjust(layout)
    # Unknown mode beyond what we map.
    print(
        f"warning: overlap={raw!r} not supported, "
        f"falling back to scale.",
        file=sys.stderr,
    )
    return scale_adjust(layout)
