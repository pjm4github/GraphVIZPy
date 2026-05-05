"""Post-processing helpers shared across layout engines.

See: /lib/common/postproc.c

Normalize / rotate / center of final coordinates; connected-component
detection + left-to-right packing.  These are engine-agnostic: any
`LayoutEngine` subclass can call into them once per-node ``(x, y,
width, height, pinned)`` fields are populated.

Functions take ``layout`` (a :class:`LayoutEngine` — anything with
``lnodes``, ``rotate_deg``, ``landscape``) rather than ``self``, so
they can also be invoked from outside a class context.
"""
from __future__ import annotations

import math
from collections import deque


def apply_normalize(layout) -> None:
    """Translate so minimum coordinates are at origin.

    Skips normalization if any nodes are pinned.
    """
    real = list(layout.lnodes.values())
    if not real:
        return
    if any(getattr(ln, "pinned", False) for ln in real):
        return
    min_x = min(ln.x - ln.width / 2 for ln in real)
    min_y = min(ln.y - ln.height / 2 for ln in real)
    for ln in real:
        ln.x -= min_x
        ln.y -= min_y


def apply_rotation(layout) -> None:
    """Rotate layout by ``rotate`` attribute or landscape mode."""
    angle = layout.rotate_deg
    if layout.landscape and angle == 0:
        angle = 90
    if angle == 0:
        return
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    for ln in layout.lnodes.values():
        x, y = ln.x, ln.y
        ln.x = x * cos_a - y * sin_a
        ln.y = x * sin_a + y * cos_a
        if angle in (90, 270, -90):
            ln.width, ln.height = ln.height, ln.width


def apply_center(layout) -> None:
    """Center the layout at the origin."""
    real = list(layout.lnodes.values())
    if not real:
        return
    min_x = min(ln.x - ln.width / 2 for ln in real)
    max_x = max(ln.x + ln.width / 2 for ln in real)
    min_y = min(ln.y - ln.height / 2 for ln in real)
    max_y = max(ln.y + ln.height / 2 for ln in real)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    for ln in real:
        ln.x -= cx
        ln.y -= cy


def find_components(adj: dict[str, list[str]]) -> list[set[str]]:
    """Find connected components of an adjacency graph using BFS."""
    visited: set[str] = set()
    components: list[set[str]] = []
    for node in adj:
        if node in visited:
            continue
        comp: set[str] = set()
        queue = deque([node])
        while queue:
            n = queue.popleft()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            for nb in adj.get(n, []):
                if nb not in visited:
                    queue.append(nb)
        components.append(comp)
    return components


def pack_components_lr(layout, components: list[set[str]],
                       gap: float = 36.0) -> None:
    """Pack multiple laid-out components left-to-right."""
    x_offset = 0.0
    for comp in components:
        comp_lns = [layout.lnodes[n] for n in comp if n in layout.lnodes]
        if not comp_lns:
            continue
        min_x = min(ln.x - ln.width / 2 for ln in comp_lns)
        max_x = max(ln.x + ln.width / 2 for ln in comp_lns)
        dx = x_offset - min_x
        for ln in comp_lns:
            ln.x += dx
        x_offset += (max_x - min_x) + gap


def pack_components_polyomino(layout, components: list[set[str]],
                              margin: float = 8.0) -> None:
    """Pack components into a roughly-square 2D layout.

    Mirrors ``lib/pack/pack.c::polyRects``: each component covers a
    set of cells on a coarse grid, components are sorted by
    perimeter descending, and each one is greedily placed by
    spiralling outward from origin.

    Replaces ``pack_components_lr`` for engines (notably neato) that
    would otherwise produce a degenerate horizontal strip when the
    input has many disconnected components.
    """
    from gvpy.engines.layout.common.pack import Bbox, poly_rects

    comp_lists = []
    bbs = []
    for comp in components:
        comp_lns = [layout.lnodes[n] for n in comp if n in layout.lnodes]
        if not comp_lns:
            continue
        ll_x = min(ln.x - ln.width / 2 for ln in comp_lns)
        ll_y = min(ln.y - ln.height / 2 for ln in comp_lns)
        ur_x = max(ln.x + ln.width / 2 for ln in comp_lns)
        ur_y = max(ln.y + ln.height / 2 for ln in comp_lns)
        comp_lists.append(comp_lns)
        bbs.append(Bbox(ll_x, ll_y, ur_x, ur_y))

    if not bbs:
        return

    places = poly_rects(bbs, margin=margin)
    for comp_lns, bb, (dx, dy) in zip(comp_lists, bbs, places):
        for ln in comp_lns:
            ln.x += dx
            ln.y += dy
