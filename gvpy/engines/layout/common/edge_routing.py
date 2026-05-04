"""Neato edge spline routing.

Mirrors ``lib/neatogen/neatosplines.c`` (the per-engine entry
points) on top of the path-planning infrastructure already ported
in ``gvpy.engines.layout.pathplan`` (``Pobsopen`` / ``Pobspath`` /
``Pobsclose``).

Algorithm (mirrors ``spline_edges_`` at neatosplines.c:586):

1. ``makeObstacle`` — build a ``Ppoly`` axis-aligned rectangle per
   node, inflated by the user margin.
2. ``Pobsopen`` — build a visibility configuration once for the
   whole graph.
3. For each edge:
   - Self-loop: arc above the node.
   - Otherwise: ``Pobspath`` from tail centre to head centre,
     then either keep as polyline (``EDGETYPE_PLINE``) or fit a
     cubic Bezier (``EDGETYPE_SPLINE``).
4. ``Pobsclose``.

The resulting routes live in ``layout.edge_routes``, a
``dict[edge_key, EdgeRoute]``; ``NeatoLayout._to_json`` reads them
and emits multi-point polyline / bezier control points instead of
the base class's two-point straight-line fallback.

Trace tag: ``[TRACE neato_splines]``.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Any

from gvpy.engines.layout.common.geom import Ppoint, Ppoly, Ppolyline
from gvpy.engines.layout.common.splines import to_bezier
from gvpy.engines.layout.dot.path import (
    EDGETYPE_LINE,
    EDGETYPE_NONE,
    EDGETYPE_PLINE,
    EDGETYPE_SPLINE,
    edge_type_from_splines,
)
from gvpy.engines.layout.pathplan.cvt import (
    Pobsclose,
    Pobsopen,
    Pobspath,
)
from gvpy.engines.layout.pathplan.vispath import POLYID_UNKNOWN



@dataclass
class EdgeRoute:
    """A routed edge.

    - ``points`` — list of ``(x, y)`` tuples.  For ``polyline`` /
      ``line`` types these are vertex coordinates; for ``bezier``
      types these are cubic-Bezier control points (``3k + 1``
      points for ``k`` segments).
    - ``spline_type`` — ``"line"``, ``"polyline"`` or ``"bezier"``.
    """

    points: list[tuple[float, float]]
    spline_type: str = "line"


def _trace(msg: str) -> None:
    """Emit a ``[TRACE neato_splines]`` line on stderr if tracing
    is enabled (``GVPY_TRACE_NEATO=1``)."""
    if os.environ.get("GVPY_TRACE_NEATO", "") == "1":
        print(f"[TRACE neato_splines] {msg}", file=sys.stderr)


def _node_bbox_polygon(x: float, y: float, w: float, h: float,
                       margin_x: float = 4.0,
                       margin_y: float = 4.0) -> Ppoly:
    """Build a **CW** Ppoly axis-aligned rectangle for a node bbox.

    Mirrors the ``isOrtho`` branch of ``makeObstacle`` (line 346).
    Pathplan requires polygons in **clockwise** order
    (``vispath.h:33`` — ``"Points in polygonal obstacles must be in
    clockwise order."``).  Reversing the order from CCW to CW makes
    the ``in_cone`` cone test (which checks ``wind(a0, a1, a2) > 0``
    for "convex at a1") classify the polygon's outward-facing
    direction correctly, so visibility queries actually detect
    obstacles between two points instead of waving them through.

    Vertex order in math y-up coords: SW → NW → NE → SE.
    """
    hw = w / 2 + margin_x
    hh = h / 2 + margin_y
    pts = [
        Ppoint(x - hw, y - hh),  # SW
        Ppoint(x - hw, y + hh),  # NW
        Ppoint(x + hw, y + hh),  # NE
        Ppoint(x + hw, y - hh),  # SE
    ]
    return Ppoly(ps=pts)


def _make_self_arc(t_ln, h_ln, gap: float = 18.0) -> EdgeRoute:
    """Generate a self-loop arc above the node.

    Simplified port of ``makeSelfArcs`` (multispline.c):
    a four-point polyline that traces a small loop above the
    node's bbox.
    """
    cx = t_ln.x
    cy = t_ln.y
    half_w = t_ln.width / 2
    half_h = t_ln.height / 2
    # Loop above the node, offset by ``gap``.
    p0 = (cx - half_w, cy)
    p1 = (cx - half_w, cy + half_h + gap)
    p2 = (cx + half_w, cy + half_h + gap)
    p3 = (cx + half_w, cy)
    return EdgeRoute(points=[p0, p1, p2, p3], spline_type="polyline")


def _line_box_intersect(p0: tuple[float, float],
                        p1: tuple[float, float],
                        cx: float, cy: float,
                        hw: float, hh: float
                        ) -> tuple[float, float]:
    """Clip the segment from ``p0`` toward ``p1`` to the bbox.

    Returns the point on the bbox boundary along the ``p0`` → ``p1``
    direction (used for trimming spline endpoints to node borders).
    Falls back to the bbox centre if the ray misses.
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return p0
    # Parametric clip: find smallest t in (0, 1] where the ray
    # exits the inflated box.
    candidates = []
    if abs(dx) > 1e-12:
        for x_edge in (cx - hw, cx + hw):
            t = (x_edge - p0[0]) / dx
            if 0 < t <= 1.0:
                y_at = p0[1] + t * dy
                if cy - hh - 1e-6 <= y_at <= cy + hh + 1e-6:
                    candidates.append((t, x_edge, y_at))
    if abs(dy) > 1e-12:
        for y_edge in (cy - hh, cy + hh):
            t = (y_edge - p0[1]) / dy
            if 0 < t <= 1.0:
                x_at = p0[0] + t * dx
                if cx - hw - 1e-6 <= x_at <= cx + hw + 1e-6:
                    candidates.append((t, x_at, y_edge))
    if not candidates:
        return p0
    candidates.sort()
    _, xc, yc = candidates[0]
    return xc, yc


def route_edges(layout: Any,
                edge_type: int | None = None,
                margin: float = 4.0) -> None:
    """Top-level edge routing.

    Reads the ``splines`` graph attribute, builds obstacle polygons
    from each node, and routes each edge through them.  Stores the
    result in ``layout.edge_routes`` (dict keyed by the same key
    the graph uses for ``edges``).
    """
    if edge_type is None:
        spl = (layout.graph.get_graph_attr("splines") or "").strip()
        edge_type = edge_type_from_splines(spl)

    # Initialize the output map even on early-return so callers can
    # always access it.
    layout.edge_routes = {}

    if edge_type == EDGETYPE_NONE:
        _trace("splines=false / none — skipping edge routing")
        return

    if edge_type == EDGETYPE_LINE:
        _trace("splines=line — straight-line edges (no obstacle avoidance)")
        for key, edge in layout.graph.edges.items():
            t_ln = layout.lnodes.get(edge.tail.name)
            h_ln = layout.lnodes.get(edge.head.name)
            if not t_ln or not h_ln:
                continue
            if edge.tail.name == edge.head.name:
                layout.edge_routes[key] = _make_self_arc(t_ln, h_ln)
            else:
                layout.edge_routes[key] = EdgeRoute(
                    points=[(t_ln.x, t_ln.y), (h_ln.x, h_ln.y)],
                    spline_type="line",
                )
        return

    # Build obstacles (one polygon per non-virtual node).
    node_names = list(layout.lnodes.keys())
    name_to_poly_idx: dict[str, int] = {}
    polys: list[Ppoly] = []
    for name in node_names:
        ln = layout.lnodes[name]
        poly = _node_bbox_polygon(
            ln.x, ln.y, ln.width, ln.height,
            margin_x=margin, margin_y=margin,
        )
        name_to_poly_idx[name] = len(polys)
        polys.append(poly)

    if not polys:
        return

    try:
        vconfig = Pobsopen(polys)
    except Exception as exc:
        _trace(f"Pobsopen failed ({exc}); falling back to straight lines")
        for key, edge in layout.graph.edges.items():
            t_ln = layout.lnodes.get(edge.tail.name)
            h_ln = layout.lnodes.get(edge.head.name)
            if not t_ln or not h_ln or edge.tail.name == edge.head.name:
                continue
            layout.edge_routes[key] = EdgeRoute(
                points=[(t_ln.x, t_ln.y), (h_ln.x, h_ln.y)],
                spline_type="line",
            )
        return

    n_routed = 0
    n_failed = 0
    try:
        for key, edge in layout.graph.edges.items():
            t_name, h_name = edge.tail.name, edge.head.name
            t_ln = layout.lnodes.get(t_name)
            h_ln = layout.lnodes.get(h_name)
            if not t_ln or not h_ln:
                continue
            if t_name == h_name:
                layout.edge_routes[key] = _make_self_arc(t_ln, h_ln)
                continue

            t_idx = name_to_poly_idx.get(t_name, POLYID_UNKNOWN)
            h_idx = name_to_poly_idx.get(h_name, POLYID_UNKNOWN)

            # Pobspath wants endpoints OUTSIDE the obstacle polys.
            # Use the centre of each node as the path endpoint and
            # let the path planner route around the bboxes.
            p0 = Ppoint(t_ln.x, t_ln.y)
            p1 = Ppoint(h_ln.x, h_ln.y)

            try:
                pl: Ppolyline = Pobspath(vconfig, p0, t_idx, p1, h_idx)
            except Exception as exc:
                _trace(f"Pobspath failed for {t_name}->{h_name} ({exc})")
                pl = Ppolyline(ps=[p0, p1])
                n_failed += 1

            pts = [(p.x, p.y) for p in pl.ps]

            # Clip first / last segments to node boundaries so the
            # rendered edge starts/ends on the node border, not
            # the centre.
            if len(pts) >= 2:
                pts[0] = _line_box_intersect(
                    pts[0], pts[1], t_ln.x, t_ln.y,
                    t_ln.width / 2, t_ln.height / 2,
                )
                pts[-1] = _line_box_intersect(
                    pts[-1], pts[-2], h_ln.x, h_ln.y,
                    h_ln.width / 2, h_ln.height / 2,
                )

            if edge_type == EDGETYPE_SPLINE and len(pts) >= 2:
                # Schneider cubic fit -> Bezier control points.
                try:
                    bez = to_bezier(pts)
                    layout.edge_routes[key] = EdgeRoute(
                        points=bez, spline_type="bezier",
                    )
                except Exception as exc:
                    _trace(
                        f"to_bezier failed {t_name}->{h_name} ({exc}); "
                        f"using polyline"
                    )
                    layout.edge_routes[key] = EdgeRoute(
                        points=pts, spline_type="polyline",
                    )
            else:
                layout.edge_routes[key] = EdgeRoute(
                    points=pts, spline_type="polyline",
                )
            n_routed += 1
    finally:
        Pobsclose(vconfig)

    _trace(f"routed={n_routed} failed={n_failed} edge_type={edge_type}")
