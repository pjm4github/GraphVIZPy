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
_REPEL_C = 1.5                  # X_C in xlayout.c:39 (xpms->C)


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


def xlayout(layout: Any, K: float, sep: float, max_iter: int,
            tries: int = _DFLT_MAX_ATTEMPTS) -> int:
    """Force-based overlap removal.

    Outer loop: up to ``tries`` attempts; ``K`` grows additively
    by the original ``K`` per try (mirrors ``xpms.K += K`` in
    xlayout.c:300).  Inner loop: F-R-style force iteration with
    overlap-aware repulsion + clearance-distance attraction.

    Returns the number of overlapping pairs *remaining* (0 means
    fully cleared).  Mirrors ``xlayout.c::x_layout``.
    """
    nodes = list(layout.lnodes.values())
    N = len(nodes)
    if N < 2:
        return 0

    n_edges = len(layout.graph.edges)
    sep_x = sep
    sep_y = sep
    inner_iters = min(max_iter, 100)

    # Initial overlap count — mirrors x_layout.c:273.
    if not _count_overlaps(nodes, sep_x, sep_y):
        return 0

    K_eff = K
    overlaps = 0
    for attempt in range(tries):
        K2 = K_eff * K_eff
        # X_ov / X_nonov mirror xlayout.c:281-282.
        x_ov = _REPEL_C * K2
        if N > 1:
            x_nonov = n_edges * x_ov * 2.0 / (N * (N - 1))
        else:
            x_nonov = 0.0
        T0 = K_eff * math.sqrt(N) / 5.0

        for it in range(inner_iters):
            temp = T0 * (inner_iters - it) / inner_iters
            if temp <= 0:
                break

            for ln in nodes:
                ln.disp_x = 0.0
                ln.disp_y = 0.0

            overlaps = 0
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
                        force = x_ov / dist2
                    else:
                        force = x_nonov / dist2

                    fx = dx * force
                    fy = dy * force
                    b.disp_x += fx
                    b.disp_y += fy
                    a.disp_x -= fx
                    a.disp_y -= fy

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
                return 0

        if overlaps == 0:
            return 0
        K_eff += K          # additive growth, mirrors xlayout.c:300

    _trace(f"bail tries={tries} remaining_overlaps={overlaps}")
    return overlaps


def _count_overlaps(nodes: list, sep_x: float, sep_y: float) -> int:
    """Count pairs of overlapping bounding boxes."""
    cnt = 0
    N = len(nodes)
    for i in range(N):
        a = nodes[i]
        for j in range(i + 1, N):
            b = nodes[j]
            if _is_overlap(a, b, b.x - a.x, b.y - a.y, sep_x, sep_y):
                cnt += 1
    return cnt
