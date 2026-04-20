"""Edge routing result container.

See: /lib/common/types.h @ 89

An
:class:`EdgeRoute` holds the geometric result of phase-4 spline
routing for a single edge: control points, spline type, and label
anchor.  It is deliberately the stable boundary between the headless
layout engine and any downstream renderer (the current SVG renderer,
and the eventual PyQt ``QGraphicsPathItem``).

Kept separate from :class:`LayoutEdge` on purpose:

- :class:`LayoutEdge` is the compute-time view of an edge — mincross
  order, rank assignment, virtual-node chain state, tree index bits —
  all scratch state that is meaningless outside the layout run.
- :class:`EdgeRoute` is the *result* of that run.  It survives the
  layout engine, can be serialised, and has no references back into
  the engine's state graph.

Mapping to Graphviz C
---------------------
- ``points``       ↔ ``bezier.list`` — control points.  Interpretation
                     depends on ``spline_type``: a polyline is an
                     anchor-only sequence; a bezier follows Graphviz
                     cubic convention ``[P0, C1, C2, P1, C3, C4, P2, ...]``
                     where each subsequent group of three points (after
                     the first anchor) defines one cubic segment.
- ``spline_type``  ↔ the spline mode (``"polyline"`` or ``"bezier"``)
                     chosen for this edge.
- ``label_pos``    ↔ ``ED_label(e)->pos`` — set by label placement
                     after routing.
- ``sflag``        ↔ ``bezier.sflag`` — start-arrow shape flag.  Written
                     by the arrow-clip pass (Phase C); read by
                     ``swap_bezier`` during back-edge normalisation.
- ``eflag``        ↔ ``bezier.eflag`` — end-arrow shape flag.
- ``sp``           ↔ ``bezier.sp`` — spline start point after arrow clip.
- ``ep``           ↔ ``bezier.ep`` — spline end point after arrow clip.

Note on the single-bezier model
-------------------------------
C's ``bezier`` struct lives inside a ``splines`` container which can
hold a *list* of beziers per edge — useful for compound edges that
need distinct segments on each side of an inner node.  Python currently
has exactly **one** bezier per edge: :class:`EdgeRoute` *is* the
bezier.  The Phase A step 5 ports of ``swap_bezier`` / ``swap_spline``
both operate on :class:`EdgeRoute` directly and are equivalent under
this model.  When compound-edge routing lands (Phase E), this class
will gain a ``beziers: list[Bezier]`` field and the two functions
will diverge.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EdgeRoute:
    """Result of phase-4 spline routing for a single edge."""

    points: list = field(default_factory=list)
    spline_type: str = "polyline"
    label_pos: tuple = ()
    sflag: int = 0
    eflag: int = 0
    sp: tuple = (0.0, 0.0)
    ep: tuple = (0.0, 0.0)
