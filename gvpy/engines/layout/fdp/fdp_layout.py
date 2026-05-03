"""Fdp layout engine — Fruchterman-Reingold force-directed placement.

Port of Graphviz ``lib/fdpgen/`` to a Py package mirroring the C
file structure:

============================  ===============================
Python module                 C source
============================  ===============================
``fdp_layout.py``             ``fdpinit.c`` + ``layout.c``
``tlayout.py``                ``tlayout.c``
``xlayout.py``                ``xlayout.c``
``grid.py``                   ``grid.c``
============================  ===============================

Two-phase layout:

- **Phase 1** (``tlayout``): Force-directed placement with grid-
  accelerated repulsive forces and linear cooling.
- **Phase 2** (``xlayout``): Overlap removal using a modified
  force model that respects node bounding boxes.  Used when
  ``overlap=fdp`` (the historical default).  Other ``overlap=``
  modes route through the shared ``common.adjust.remove_overlap``
  dispatcher (scale, scalexy, voronoi, prism, ortho, etc.) for
  consistency with neato and twopi.

Edge spline routing reuses ``common.edge_routing.route_edges``
(same path-planning infrastructure neato and twopi use).

Trace channel: ``GVPY_TRACE_FDP=1`` emits ``[TRACE fdp_*]`` lines.

Command-line usage::

    python gvcli.py -Kfdp input.gv -Tsvg -o output.svg

API usage::

    from gvpy.engines.layout.fdp import FdpLayout
    result = FdpLayout(graph).layout()

Attributes
----------
**Graph:** ``K``, ``maxiter``, ``T0``, ``start``, ``overlap``,
``sep``, ``splines``, ``pack``, ``normalize``, ``center``.

**Node:** ``pos``, ``pin``, ``width``, ``height``, ``shape``,
``label``.

**Edge:** ``len``, ``weight``.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine
from gvpy.engines.layout.common.adjust import remove_overlap
from gvpy.engines.layout.common.edge_routing import EdgeRoute, route_edges
from gvpy.engines.layout.fdp.tlayout import init_positions, tlayout
from gvpy.engines.layout.fdp.xlayout import xlayout


# Mirrors ``DFLT_K`` from tlayout.c:98 (0.3 inches in points).
_DFLT_K = 0.3 * 72.0
# Mirrors ``DFLT_maxIters`` from tlayout.c:97.
_DFLT_MAXITER = 600


@dataclass
class LayoutNode:
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False
    pos_set: bool = False
    disp_x: float = 0.0          # F-R displacement accumulator
    disp_y: float = 0.0


class FdpLayout(LayoutEngine):
    """Fruchterman-Reingold force-directed placement layout engine."""

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.K = _DFLT_K
        self.maxiter = _DFLT_MAXITER
        self.T0 = -1.0                  # auto-compute if negative
        self.seed = 1
        self.overlap = "true"
        self.sep = 0.0
        self.pack = True
        self.use_grid = True
        # Edge attribute caches keyed by canonical (low, high) name pair.
        self._edge_len: dict[tuple[str, str], float] = {}
        self._edge_weight: dict[tuple[str, str], float] = {}
        # Routes populated by ``route_edges`` after layout.
        self.edge_routes: dict[tuple, EdgeRoute] = {}

    # ── Public API ───────────────────────────────

    def layout(self) -> dict:
        self._init_from_graph()
        N = len(self.lnodes)
        if N == 0:
            return self._to_json()

        adj = self._build_adjacency()
        components = self._find_components(adj)

        if len(components) > 1 and self.pack:
            for comp in components:
                self._layout_component(comp)
            self._pack_components_lr(components,
                                     gap=max(self.K * 0.5, 36.0))
        else:
            self._layout_component(set(self.lnodes.keys()))

        # Phase 2 — overlap removal.  ``overlap=fdp`` runs the
        # historical fdp force-based pass; everything else routes
        # through the shared common.adjust dispatcher.
        ov_low = self.overlap.lower() if self.overlap else ""
        if ov_low == "fdp":
            xlayout(self, self.K, self.sep, self.maxiter)
        else:
            remove_overlap(self)

        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        # Edge spline routing (engine-agnostic helper).
        route_edges(self)

        self._compute_label_positions()
        self._write_back()
        return self._to_json()

    # ── Initialization ───────────────────────────

    def _init_from_graph(self):
        self._init_common_attrs()

        k_str = self.graph.get_graph_attr("K")
        if k_str:
            try:
                self.K = float(k_str) * 72.0
            except ValueError:
                pass

        maxiter_str = self.graph.get_graph_attr("maxiter")
        if maxiter_str:
            try:
                self.maxiter = int(maxiter_str)
            except ValueError:
                pass

        t0_str = self.graph.get_graph_attr("T0")
        if t0_str:
            try:
                self.T0 = float(t0_str) * 72.0
            except ValueError:
                pass

        start_str = self.graph.get_graph_attr("start") or ""
        if start_str.isdigit():
            self.seed = int(start_str)
        elif start_str == "random":
            import time
            self.seed = int(time.time())
        random.seed(self.seed)

        ov_str = (self.graph.get_graph_attr("overlap") or "true").lower()
        self.overlap = ov_str

        sep_str = self.graph.get_graph_attr("sep")
        if sep_str:
            try:
                self.sep = float(sep_str)
            except ValueError:
                pass

        self.pack = (self.graph.get_graph_attr("pack") or "true") \
            .lower() not in ("false", "0", "no")

        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)

            pos_str = (node.attributes.get("pos") or "").strip() if node else ""
            if pos_str:
                try:
                    parts = pos_str.replace("!", "").split(",")
                    ln.x = float(parts[0]) * 72.0
                    ln.y = float(parts[1]) * 72.0
                    ln.pos_set = True
                    ln.pinned = ("!" in pos_str
                                 or (node and node.attributes.get(
                                     "pin", "").lower() in ("true", "1", "yes")))
                except (ValueError, IndexError):
                    pass
            elif node and node.attributes.get("pin", "").lower() in (
                    "true", "1", "yes"):
                ln.pinned = True

            self.lnodes[name] = ln

        # Cache edge lengths and weights (default len = K).
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            pair = (min(t, h), max(t, h))

            try:
                length = float(edge.attributes.get("len", "")) * 72.0
            except (ValueError, TypeError):
                length = self.K

            try:
                weight = float(edge.attributes.get("weight", "1.0"))
            except ValueError:
                weight = 1.0

            self._edge_len[pair] = length
            self._edge_weight[pair] = weight

    def _build_adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = defaultdict(list)
        for name in self.lnodes:
            adj[name]
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if t in self.lnodes and h in self.lnodes:
                if h not in adj[t]:
                    adj[t].append(h)
                if t not in adj[h]:
                    adj[h].append(t)
        return dict(adj)

    # ── Component layout ─────────────────────────

    def _layout_component(self, nodes: set[str]) -> None:
        node_list = [n for n in self.lnodes if n in nodes]
        N = len(node_list)
        if N == 0:
            return
        if N == 1:
            ln = self.lnodes[node_list[0]]
            if not ln.pos_set:
                ln.x, ln.y = 0.0, 0.0
            return

        init_positions(self, node_list, self.K)

        # Initial temperature.
        T0 = self.T0
        if T0 < 0:
            T0 = self.K * math.sqrt(N) / 5.0

        # Build the per-component edge list (tail, head, len, weight).
        comp_edges: list[tuple[str, str, float, float]] = []
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if t not in nodes or h not in nodes:
                continue
            pair = (min(t, h), max(t, h))
            comp_edges.append((
                t, h,
                self._edge_len.get(pair, self.K),
                self._edge_weight.get(pair, 1.0),
            ))

        tlayout(self, node_list, comp_edges, self.K, T0,
                self.maxiter, use_grid=self.use_grid)

    # ── Edge-route-aware JSON output ─────────────

    def _to_json(self) -> dict:
        result = super()._to_json()
        if not self.edge_routes:
            return result
        for entry, (key, edge) in zip(result["edges"],
                                      self.graph.edges.items()):
            route = self.edge_routes.get(key)
            if route is None or not route.points:
                continue
            entry["points"] = [[round(p[0], 2), round(p[1], 2)]
                               for p in route.points]
            entry["spline_type"] = route.spline_type
            if entry.get("label"):
                mid_idx = len(route.points) // 2
                mx, my = route.points[mid_idx]
                entry["label_pos"] = [round(mx, 2), round(my, 2)]
        return result

    # Shared methods inherited from LayoutEngine base class:
    # _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _estimate_label_size, _overlap_area, _compute_label_positions,
    # _clip_to_boundary, _find_components, _pack_components_lr,
    # _write_back.
