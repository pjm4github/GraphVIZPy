"""Neato overlap-removal post-pass.

Mirrors ``lib/neatogen/adjust.c``.  C dispatches between several
overlap-removal algorithms based on the ``overlap`` graph
attribute; this Py port matches the dispatch logic and ships the
two simplest algorithms (uniform and per-axis scaling).  Prism
(Voronoi-based) is deferred to Phase N3.3.

Mode mapping (mirrors ``adjust.c::adjustMode[]`` and
``getAdjustMode``):

================  =================  ============
``overlap=``      C constant         Py status
================  =================  ============
"" / unset         AM_NONE            implemented (no-op)
true               AM_NONE            implemented
false              AM_PRISM (default) **falls back to scale**
scale / scaling    AM_NSCALE          implemented
scalexy            AM_SCALEXY         implemented
prism / prismN     AM_PRISM           **falls back to scale**
voronoi / Voronoi  AM_VOR             **falls back to scale**
compress           AM_COMPRESS        not implemented
ortho* / portho*   AM_ORTHO_*         not implemented
ipsep              AM_IPSEP           not implemented
vpsc               AM_VPSC            not implemented
================  =================  ============

The fallback for prism / voronoi emits a one-line warning so users
know the C-default mode isn't yet active.

Trace tag: ``[TRACE neato_adjust]``.
"""
from __future__ import annotations

import math
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout


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
    }
    if low in named:
        return named[low], raw
    if low.startswith("prism"):
        return AM_PRISM, raw

    # Unknown -> treat as "false" per adjust.c:843.
    return AM_PRISM, raw


def _bbox_of(layout: "NeatoLayout") -> tuple[float, float, float, float]:
    """Return ``(min_x, min_y, max_x, max_y)`` over all nodes."""
    xs, ys = [], []
    for ln in layout.lnodes.values():
        xs.append(ln.x)
        ys.append(ln.y)
    return min(xs), min(ys), max(xs), max(ys)


def _has_overlap(layout: "NeatoLayout", sx: float = 1.0,
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


def scale_adjust(layout: "NeatoLayout",
                 incr: float = _SCALE_INCR,
                 max_iter: int = _DFLT_SCALE_MAXITER) -> int:
    """Uniform-scale overlap removal.

    Mirrors ``adjust.c::sAdjust`` (line 472) and ``rePos`` (462):
    repeatedly multiply every coordinate by ``1 + incr`` until no
    pairwise overlap remains.  Pinned nodes are not moved.

    Returns the number of scale iterations taken (0 if no
    overlap was present).
    """
    if not _has_overlap(layout):
        _trace("scale: no overlap, skip")
        return 0

    factor = 1.0 + incr
    iters = 0
    while iters < max_iter:
        for ln in layout.lnodes.values():
            if ln.pinned:
                continue
            ln.x *= factor
            ln.y *= factor
        iters += 1
        if not _has_overlap(layout):
            break

    _trace(f"scale: iters={iters} factor_total={factor**iters:.3f}")
    return iters


def scalexy_adjust(layout: "NeatoLayout",
                   incr: float = _SCALE_INCR,
                   max_iter: int = _DFLT_SCALE_MAXITER) -> int:
    """Per-axis scaling overlap removal.

    Mirrors C ``AM_SCALEXY``: same as ``scale_adjust`` but scales
    only the axis that needs more room (the one where overlap
    pairs are closer relative to their summed half-extent).
    """
    if not _has_overlap(layout):
        _trace("scalexy: no overlap, skip")
        return 0

    factor = 1.0 + incr
    iters = 0
    while iters < max_iter:
        # Decide which axis is tighter.
        nodes = list(layout.lnodes.values())
        worst_x_ratio = 0.0
        worst_y_ratio = 0.0
        sep = layout.sep
        for i in range(len(nodes)):
            a = nodes[i]
            for j in range(i + 1, len(nodes)):
                b = nodes[j]
                dx = abs(a.x - b.x)
                dy = abs(a.y - b.y)
                rx = dx / max(a.width / 2 + b.width / 2 + sep, 1e-9)
                ry = dy / max(a.height / 2 + b.height / 2 + sep, 1e-9)
                if rx < 1.0:
                    worst_x_ratio = max(worst_x_ratio, 1.0 - rx)
                if ry < 1.0:
                    worst_y_ratio = max(worst_y_ratio, 1.0 - ry)

        scale_x = factor if worst_x_ratio >= worst_y_ratio else 1.0
        scale_y = factor if worst_y_ratio > worst_x_ratio else 1.0
        for ln in layout.lnodes.values():
            if ln.pinned:
                continue
            ln.x *= scale_x
            ln.y *= scale_y
        iters += 1
        if not _has_overlap(layout):
            break

    _trace(f"scalexy: iters={iters}")
    return iters


def remove_overlap(layout: "NeatoLayout") -> int:
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
    if mode in (AM_PRISM, AM_VOR):
        # N3.3 will ship the real prism / voronoi.  Until then, fall
        # back to uniform scaling so users get *some* overlap removal.
        print(
            f"warning: overlap={raw!r} requested {mode} adjustment, "
            f"which is not yet implemented in gvpy; "
            f"falling back to scale.",
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
