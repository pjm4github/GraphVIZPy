"""Twopi layout engine — radial layout.

Port of Graphviz ``lib/twopigen/`` to a Py package mirroring the C
file structure:

============================  ================================
Python module                 C source
============================  ================================
``twopi_layout.py``           ``twopiinit.c``
``circle.py``                 ``circle.c``
============================  ================================

Algorithm
---------
1. Find the most-interior node (``find_center_node``) — DFS from
   each leaf, take the node with max distance to its nearest leaf.
   User can override via the ``root`` attribute (graph or node).
2. BFS from the centre to assign radial level (``s_center``) and
   parent pointers.
3. Bottom-up: count leaves in each subtree (``stsize``).
4. Top-down: each subtree gets angular span proportional to its
   leaf count.
5. Top-down: set ``theta`` per node walking left-to-right through
   each parent's children.
6. Convert (level, theta) to (x, y) using the ``ranksep`` array.

Overlap removal and spline routing are delegated to the
neato-side engine-agnostic helpers (``neato.adjust.remove_overlap``
and ``neato.splines.route_edges``); twopi populates the same
``LayoutNode`` / ``edge_routes`` interface they expect.

Trace tag: ``[TRACE twopi]`` (set ``GVPY_TRACE_TWOPI=1``).

Command-line::

    python gvcli.py -Ktwopi input.gv -Tsvg -o output.svg

API usage::

    from gvpy.grammar import read_gv
    from gvpy.engines.layout.twopi import TwopiLayout

    graph = read_gv('graph G { c -- a; c -- b; c -- d; }')
    result = TwopiLayout(graph).layout()
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine
from gvpy.engines.layout.neato.adjust import remove_overlap
from gvpy.engines.layout.neato.splines import EdgeRoute, route_edges
from gvpy.engines.layout.twopi.circle import circle_layout


@dataclass
class LayoutNode:
    """Per-node algorithm + render state."""

    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False
    # Radial-layout state (mirrors circle.h's rdata struct).
    s_center: int = 0          # BFS level from centre
    s_leaf: int = 0            # min steps to a leaf
    parent: str = ""           # parent name in BFS tree
    n_child: int = 0           # children count in BFS tree
    stsize: int = 0            # leaves in subtree
    theta: float = 0.0         # angular position (rad)
    span: float = 0.0          # angular span allocated


class TwopiLayout(LayoutEngine):
    """Radial layout engine."""

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.root_name: str = ""
        # Default overlap behaviour: keep overlaps (matches
        # ``adjustNodes`` semantics in C twopi when no user attribute
        # is set).  Users can opt in via overlap=scale / voronoi /
        # etc., handled by the neato adjust dispatcher.
        self.overlap = "true"
        self.sep = 0.0
        self.pack = True
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
                circle_layout(self, list(comp), adj,
                              center_hint=self._root_for(comp))
            # Pack components left-to-right.  Use the largest ranksep
            # we computed as the gap to keep visual scale consistent.
            radii = getattr(self, "_ranksep_radii", None)
            gap = max(radii) * 0.25 if radii else 36.0
            self._pack_components_lr(components, gap=max(gap, 36.0))
        else:
            circle_layout(self, list(self.lnodes.keys()), adj,
                          center_hint=self.root_name or None)

        # Reuse the neato adjust dispatcher (engine-agnostic — uses
        # ``layout.lnodes`` / ``layout.sep`` / ``layout.overlap``).
        remove_overlap(self)

        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        # Edge spline routing — same path-planning infrastructure
        # neato uses; reads the ``splines`` graph attribute.
        route_edges(self)

        self._compute_label_positions()
        self._write_back()
        return self._to_json()

    # ── Initialization ───────────────────────────

    def _init_from_graph(self):
        self._init_common_attrs()

        self.root_name = self.graph.get_graph_attr("root") or ""

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
            # Per-node ``root`` attribute overrides graph-level.
            if node and node.attributes.get("root", "").lower() in (
                    "true", "1", "yes"):
                self.root_name = name
            self.lnodes[name] = ln

    def _build_adjacency(self) -> dict[str, list[str]]:
        """Build undirected adjacency, skipping ``weight=0`` edges
        (twopi uses these to mark "ignore in radial tree")."""
        adj: dict[str, list[str]] = defaultdict(list)
        for name in self.lnodes:
            adj[name]
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if t not in self.lnodes or h not in self.lnodes:
                continue
            try:
                w = float(edge.attributes.get("weight", "1"))
            except ValueError:
                w = 1.0
            if w <= 0:
                continue
            if h not in adj[t]:
                adj[t].append(h)
            if t not in adj[h]:
                adj[h].append(t)
        return dict(adj)

    def _root_for(self, component: set[str]) -> str | None:
        """Return ``self.root_name`` if it's in the given component,
        else ``None`` (let circle_layout pick the centre)."""
        if self.root_name and self.root_name in component:
            return self.root_name
        return None

    # ── Edge-route-aware JSON output ─────────────

    def _to_json(self) -> dict:
        """Override to emit routed splines.  Falls through to the
        base ``_to_json`` for the structural fields, then patches
        each edge entry with the route stored in ``self.edge_routes``.

        Mirrors :class:`NeatoLayout._to_json`.
        """
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

    # Shared from LayoutEngine: _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _compute_label_positions, _clip_to_boundary, _find_components,
    # _pack_components_lr, _write_back, _to_json
