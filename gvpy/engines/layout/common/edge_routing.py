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


# ─────────────────────────────────────────────────────────────────
# Cluster-aware per-edge routing (fdp ``compoundEdges``)
# ─────────────────────────────────────────────────────────────────
#
# See: ``lib/fdpgen/clusteredges.c`` — ``compoundEdges`` and
# ``objectList``.
#
# Where ``route_edges`` (above) builds one global vconfig with all
# nodes as obstacles (mirrors neato's ``spline_edges_``), this
# helper builds a **per-edge** vconfig from a cluster-aware
# obstacle list:
#
# - The endpoints' enclosing clusters (and all common ancestors)
#   are EXCLUDED so the edge can exit/enter its own cluster.
# - Sibling clusters and sibling nodes at each level on the
#   tail-LCA-head path are INCLUDED as obstacles.
# - Real nodes become axis-aligned-box obstacles
#   (``_node_bbox_polygon``); clusters become bbox-shaped
#   obstacles (``_cluster_bbox_polygon``).
#
# Engine-agnostic by duck typing: any layout with
# ``_clusters``, ``_cluster_parent``, ``_cluster_level``,
# ``_node_to_cluster_obj``, ``lnodes``, and ``graph.edges``
# works.  fdp is the canonical caller; sfdp / osage may follow.
#
# Trace channel: ``GVPY_TRACE_NEATO=1`` (shared with the flat
# router) emits ``[TRACE neato_splines] compound: ...`` lines.


def _cluster_bbox_polygon(cl: Any, margin: float = 4.0) -> Ppoly:
    """Build a CW Ppoly axis-aligned rectangle for a cluster's
    post-layout bbox, inflated by ``margin`` (esep equivalent).

    ``cl.bb`` is ``(x_min, y_min, x_max, y_max)`` from
    :func:`gvpy.engines.layout.fdp.cluster.compute_cluster_bboxes`,
    which already includes the cluster's own margin.  ``margin``
    here adds the routing-margin gap on top.
    """
    x_min, y_min, x_max, y_max = cl.bb
    x_min -= margin
    y_min -= margin
    x_max += margin
    y_max += margin
    pts = [
        Ppoint(x_min, y_min),  # SW
        Ppoint(x_min, y_max),  # NW
        Ppoint(x_max, y_max),  # NE
        Ppoint(x_max, y_min),  # SE
    ]
    return Ppoly(ps=pts)


def _gparent(layout: Any, g: Any) -> Any:
    """C ``GPARENT(g)`` — return the parent cluster of ``g``, or
    ``None`` if ``g`` is at the root level (or ``g`` is already
    ``None``)."""
    if g is None:
        return None
    parent_name = layout._cluster_parent.get(g.name)
    if parent_name is None:
        return None
    for cl in layout._clusters:
        if cl.name is parent_name or cl.name == parent_name:
            return cl
    return None


def _add_graph_objs(layout: Any, g: Any, tex: Any, hex_: Any,
                    polys: list[Ppoly], margin: float) -> None:
    """C ``addGraphObjs(l, g, tex, hex, pm)`` — append obstacles
    for ``g``'s direct children (clusters + nodes), excluding
    ``tex`` and ``hex_``.

    ``g`` is an ``FdpCluster`` (or any object with ``.name`` /
    ``.direct_nodes``) or ``None`` (= root graph; iterate
    top-level clusters and nodes outside any cluster).

    ``tex`` / ``hex_`` are exclusions — the endpoints' own
    enclosing clusters and the endpoint nodes themselves.  Each
    is an ``FdpCluster`` instance, a node-name string, or
    ``None``.
    """
    if g is None:
        # Root: top-level clusters + nodes with no cluster parent.
        for cl in layout._clusters:
            if layout._cluster_parent[cl.name] is None:
                if cl is tex or cl is hex_:
                    continue
                polys.append(_cluster_bbox_polygon(cl, margin))
        for name, ln in layout.lnodes.items():
            if layout._node_to_cluster.get(name) is not None:
                continue
            if name == tex or name == hex_:
                continue
            polys.append(_node_bbox_polygon(
                ln.x, ln.y, ln.width, ln.height,
                margin_x=margin, margin_y=margin,
            ))
    else:
        # Cluster g: direct child clusters + direct member nodes.
        for cl in layout._clusters:
            if layout._cluster_parent.get(cl.name) == g.name:
                if cl is tex or cl is hex_:
                    continue
                polys.append(_cluster_bbox_polygon(cl, margin))
        for name in g.direct_nodes:
            if name == tex or name == hex_:
                continue
            ln = layout.lnodes.get(name)
            if ln is None:
                continue
            polys.append(_node_bbox_polygon(
                ln.x, ln.y, ln.width, ln.height,
                margin_x=margin, margin_y=margin,
            ))


def object_list(layout: Any, edge: Any,
                margin: float = 4.0) -> list[Ppoly]:
    """C ``objectList(ep, pm)`` — per-edge obstacle list.

    Walk both endpoints up to their cluster LCA, accumulating
    sibling clusters/nodes at each level.  Excludes the
    endpoints, their enclosing clusters, and any common
    ancestors so the edge can pass through its own cluster
    boundary and stay inside common ancestors.

    Returns a list of ``Ppoly`` ready for ``Pobsopen``.

    Mirrors ``lib/fdpgen/clusteredges.c:151``.
    """
    t_name = edge.tail.name
    h_name = edge.head.name

    # PARENT(node): the node's innermost cluster (FdpCluster) or
    # None for nodes outside any cluster.
    hg = layout._node_to_cluster_obj.get(h_name)
    tg = layout._node_to_cluster_obj.get(t_name)
    # IS_CLUST_NODE branch from C is omitted — Py doesn't materialise
    # cluster proxy nodes (those are dot-engine artefacts).  The
    # exclusions are just the endpoint node names themselves.
    hex_: Any = h_name
    tex: Any = t_name

    # LEVEL: depth from root.  Root = 0; top-level clusters = 1;
    # nested = 2.  None (root-level free node) is level 0.
    hlevel = layout._cluster_level.get(hg.name, 0) if hg else 0
    tlevel = layout._cluster_level.get(tg.name, 0) if tg else 0

    polys: list[Ppoly] = []

    # raiseLevel: walk the deeper endpoint up until both are at
    # the same cluster depth.  At each step add the current
    # cluster's children (excluding the previous level's cluster).
    if hlevel > tlevel:
        for _ in range(hlevel - tlevel):
            _add_graph_objs(layout, hg, hex_, None, polys, margin)
            hex_ = hg
            hg = _gparent(layout, hg)
    elif tlevel > hlevel:
        for _ in range(tlevel - hlevel):
            _add_graph_objs(layout, tg, tex, None, polys, margin)
            tex = tg
            tg = _gparent(layout, tg)

    # Both at the same level now; walk both up to LCA.
    while hg is not tg:
        _add_graph_objs(layout, hg, None, hex_, polys, margin)
        _add_graph_objs(layout, tg, tex, None, polys, margin)
        hex_ = hg
        hg = _gparent(layout, hg)
        tex = tg
        tg = _gparent(layout, tg)

    # At the LCA (could be None = root): add its children
    # excluding both endpoint chains.
    _add_graph_objs(layout, tg, tex, hex_, polys, margin)

    return polys


def route_edges_compound(layout: Any,
                         edge_type: int | None = None,
                         margin: float = 4.0) -> None:
    """Cluster-aware per-edge spline routing.

    For each edge, build a per-edge vconfig from
    :func:`object_list` and route through it.  Mirrors C
    ``compoundEdges`` (clusteredges.c:207).

    Result lives in ``layout.edge_routes`` like the flat
    :func:`route_edges`.  Falls back to a straight line on
    Pobspath failure.

    When ``edge_type`` is ``EDGETYPE_LINE`` or ``EDGETYPE_NONE``
    we skip obstacle work entirely — same shape as the flat
    helper.
    """
    if edge_type is None:
        spl = (layout.graph.get_graph_attr("splines") or "").strip()
        edge_type = edge_type_from_splines(spl)

    layout.edge_routes = {}

    if edge_type == EDGETYPE_NONE:
        _trace("compound: splines=false / none — skipping")
        return

    if edge_type == EDGETYPE_LINE:
        _trace("compound: splines=line — straight lines")
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

    n_routed = 0
    n_failed = 0
    n_empty_obs = 0

    for key, edge in layout.graph.edges.items():
        t_name, h_name = edge.tail.name, edge.head.name
        t_ln = layout.lnodes.get(t_name)
        h_ln = layout.lnodes.get(h_name)
        if not t_ln or not h_ln:
            continue
        if t_name == h_name:
            layout.edge_routes[key] = _make_self_arc(t_ln, h_ln)
            continue

        polys = object_list(layout, edge, margin=margin)

        p0 = Ppoint(t_ln.x, t_ln.y)
        p1 = Ppoint(h_ln.x, h_ln.y)

        if not polys:
            # No obstacles to avoid — straight line is optimal.
            pl: Ppolyline = Ppolyline(ps=[p0, p1])
            n_empty_obs += 1
        else:
            vconfig = None
            try:
                vconfig = Pobsopen(polys)
            except Exception as exc:
                _trace(
                    f"compound: Pobsopen failed for {t_name}->{h_name} "
                    f"({exc}); falling back to straight line"
                )
                pl = Ppolyline(ps=[p0, p1])
                n_failed += 1
            if vconfig is not None:
                try:
                    pl = Pobspath(
                        vconfig, p0, POLYID_UNKNOWN, p1, POLYID_UNKNOWN,
                    )
                except Exception as exc:
                    _trace(
                        f"compound: Pobspath failed for "
                        f"{t_name}->{h_name} ({exc})"
                    )
                    pl = Ppolyline(ps=[p0, p1])
                    n_failed += 1
                finally:
                    Pobsclose(vconfig)

        pts = [(p.x, p.y) for p in pl.ps]

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
            try:
                bez = to_bezier(pts)
                layout.edge_routes[key] = EdgeRoute(
                    points=bez, spline_type="bezier",
                )
            except Exception as exc:
                _trace(
                    f"compound: to_bezier failed {t_name}->{h_name} "
                    f"({exc}); using polyline"
                )
                layout.edge_routes[key] = EdgeRoute(
                    points=pts, spline_type="polyline",
                )
        else:
            layout.edge_routes[key] = EdgeRoute(
                points=pts, spline_type="polyline",
            )
        n_routed += 1

    _trace(
        f"compound: routed={n_routed} failed={n_failed} "
        f"empty_obs_fallback={n_empty_obs} edge_type={edge_type}"
    )
