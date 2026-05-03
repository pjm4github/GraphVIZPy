"""Fdp Phase 2 — force-based overlap removal.

Mirrors ``lib/fdpgen/xlayout.c``.  An additional force-directed
pass with a modified force model that respects node bounding
boxes: nodes that overlap get strong repulsion; non-overlapping
edge-connected pairs get a weaker attractive force based on their
clear distance after subtracting the bounding-box "radius".

This is fdp's signature contribution beyond plain F-R; it produces
non-overlapping layouts without disrupting the global structure
established by Phase 1.

Used by ``FdpLayout`` when ``overlap=fdp`` (the historical
default).  Other ``overlap=`` modes are dispatched through the
shared ``common.adjust.remove_overlap`` so fdp users can pick
``scale`` / ``voronoi`` / ``ortho`` / etc. like neato and twopi
users.

Trace tag: ``[TRACE fdp_xlayout]``.
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import Any


_DFLT_MAX_ATTEMPTS = 9
_K_GROW_FACTOR = 0.5            # K is multiplied by 1 + attempt × this
_REPEL_OVERLAP_FACTOR = 1.5     # F_rep when nodes overlap
_REPEL_NORMAL_FACTOR = 0.1      # F_rep otherwise


def _trace(msg: str) -> None:
    """Emit a ``[TRACE fdp_xlayout]`` line on stderr if tracing is
    enabled (``GVPY_TRACE_FDP=1``)."""
    if os.environ.get("GVPY_TRACE_FDP", "") == "1":
        print(f"[TRACE fdp_xlayout] {msg}", file=sys.stderr)


def _is_overlap(a: Any, b: Any, dx: float, dy: float,
                sep_x: float, sep_y: float) -> bool:
    """Bounding-box overlap test with separation margin."""
    return (abs(dx) <= (a.width + b.width) / 2 + sep_x
            and abs(dy) <= (a.height + b.height) / 2 + sep_y)


def _node_radius(ln: Any) -> float:
    """Approximate radius of the node's bounding box."""
    return math.hypot(ln.width / 2, ln.height / 2)


def xlayout(layout: Any, K: float, sep: float, max_iter: int) -> int:
    """Force-based overlap removal.

    Outer loop: up to :data:`_DFLT_MAX_ATTEMPTS` attempts; each
    attempt grows ``K`` to push nodes farther apart.  Inner loop:
    F-R-style force iteration with the modified overlap-aware
    repulsion / attraction.

    Returns the attempt count when overlaps cleared, or
    :data:`_DFLT_MAX_ATTEMPTS` if it bailed out.

    Mirrors ``xlayout.c::fdp_xLayout`` algorithm.
    """
    nodes = list(layout.lnodes.values())
    N = len(nodes)
    if N < 2:
        return 0

    sep_x = sep
    sep_y = sep
    inner_iters = min(max_iter, 100)

    for attempt in range(_DFLT_MAX_ATTEMPTS):
        K_eff = K * (1 + attempt * _K_GROW_FACTOR)
        K2 = K_eff * K_eff
        T0 = K_eff * math.sqrt(N) / 5.0
        overlaps = 0

        for it in range(inner_iters):
            temp = T0 * (inner_iters - it) / inner_iters
            if temp <= 0:
                break

            # Clear displacements.
            for ln in nodes:
                ln.disp_x = 0.0
                ln.disp_y = 0.0

            overlaps = 0
            # Pairwise repulsion with overlap-aware coefficient.
            for i in range(N):
                a = nodes[i]
                for j in range(i + 1, N):
                    b = nodes[j]
                    dx = b.x - a.x
                    dy = b.y - a.y
                    dist2 = dx * dx + dy * dy
                    if dist2 < 0.01:
                        dx = random.random() * 0.1
                        dy = random.random() * 0.1
                        dist2 = dx * dx + dy * dy

                    if _is_overlap(a, b, dx, dy, sep_x, sep_y):
                        overlaps += 1
                        force = _REPEL_OVERLAP_FACTOR * K2 / dist2
                    else:
                        force = _REPEL_NORMAL_FACTOR * K2 / dist2

                    fx = dx * force
                    fy = dy * force
                    b.disp_x += fx
                    b.disp_y += fy
                    a.disp_x -= fx
                    a.disp_y -= fy

            # Edge-attractive forces, clear-distance based.
            for key, edge in layout.graph.edges.items():
                t_ln = layout.lnodes.get(edge.tail.name)
                h_ln = layout.lnodes.get(edge.head.name)
                if t_ln is None or h_ln is None:
                    continue
                dx = h_ln.x - t_ln.x
                dy = h_ln.y - t_ln.y
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 0.01:
                    continue
                if _is_overlap(t_ln, h_ln, dx, dy, sep_x, sep_y):
                    continue
                rad_sum = _node_radius(t_ln) + _node_radius(h_ln)
                dout = max(dist - rad_sum, 0.01)
                force = dout * dout / ((K_eff + rad_sum) * dist)
                fx = dx * force
                fy = dy * force
                t_ln.disp_x += fx
                t_ln.disp_y += fy
                h_ln.disp_x -= fx
                h_ln.disp_y -= fy

            # Apply temperature-capped displacement to each unpinned node.
            for ln in nodes:
                if ln.pinned:
                    continue
                dx = ln.disp_x
                dy = ln.disp_y
                disp_len = math.sqrt(dx * dx + dy * dy)
                if disp_len <= 0:
                    continue
                if disp_len > temp:
                    scale = temp / disp_len
                    dx *= scale
                    dy *= scale
                ln.x += dx
                ln.y += dy

            if overlaps == 0:
                _trace(f"cleared in attempt={attempt} iter={it}")
                return attempt

        if overlaps == 0:
            return attempt

    _trace(f"bail max_attempts={_DFLT_MAX_ATTEMPTS} "
           f"final_overlaps={overlaps}")
    return _DFLT_MAX_ATTEMPTS
