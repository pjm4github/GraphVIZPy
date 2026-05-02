"""Neato overlap-removal post-pass.

Mirrors ``lib/neatogen/adjust.c``.  C dispatches between several
algorithms (scaling, prism, ipsep, ortho_yx, vpsc); the current
Python implementation has only the basic radial scaling pass.
Phase N3 will port the prism (Voronoi-based) algorithm.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.neato.neato_layout import NeatoLayout

_DFLT_OVERLAP_MAXITER = 50


def remove_overlap(layout: "NeatoLayout") -> None:
    """Remove node overlaps by scaling positions outward.

    Falls through if ``layout.overlap`` is "false"/"0"/"no" — the
    user has explicitly opted out of overlap removal.
    """
    if layout.overlap in ("false", "0", "no"):
        return
    nodes = list(layout.lnodes.values())
    if len(nodes) < 2:
        return

    for _ in range(_DFLT_OVERLAP_MAXITER):
        has_overlap = False
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.sqrt(dx * dx + dy * dy)
                min_dist = ((a.width + b.width) / 2
                            + (a.height + b.height) / 2
                            + layout.sep)
                min_dist *= 0.5

                if dist < min_dist and dist > 0:
                    has_overlap = True
                    push = (min_dist - dist) / 2 + 1
                    ux, uy = dx / dist, dy / dist
                    if not a.pinned:
                        a.x -= ux * push
                        a.y -= uy * push
                    if not b.pinned:
                        b.x += ux * push
                        b.y += uy * push
        if not has_overlap:
            break
