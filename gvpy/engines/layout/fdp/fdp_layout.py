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

from gvpy.core._graph_traversal import gather_all_subgraphs
from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine
from gvpy.engines.layout.common.adjust import remove_overlap
from gvpy.engines.layout.common.edge_routing import (
    EdgeRoute,
    route_edges,
    route_edges_compound,
)
from gvpy.engines.layout.fdp.cluster import (
    FdpCluster,
    build_node_to_cluster,
    compute_cluster_bboxes,
    discover_clusters,
    push_nonmembers_out_of_clusters,
    remove_cluster_overlap,
)
from gvpy.engines.layout.fdp.derive import derive_graph_layout
from gvpy.engines.layout.fdp.tlayout import init_positions, tlayout
from gvpy.engines.layout.fdp.xlayout import xlayout


# Mirrors ``DFLT_K`` from tlayout.c:98 (0.3 inches in points).
_DFLT_K = 0.3 * 72.0
# Mirrors ``DFLT_maxIters`` from tlayout.c:97.
_DFLT_MAXITER = 600
# Mirrors ``DFLT_overlap`` from xlayout.c:33 — 9 xlayout retries
# followed by a prism cleanup pass.
_DFLT_OVERLAP = "9:prism"


def _parse_overlap_spec(spec: str) -> tuple[int, str]:
    """Parse the ``n:mode`` overlap syntax (xlayout.c:325).

    Returns ``(tries, mode)``.  Examples::

        "9:prism" -> (9, "prism")
        ":prism"  -> (0, "prism")
        "prism"   -> (0, "prism")
        "true"    -> (0, "true")
        "9:"      -> (9, "")
        ""        -> parsed from _DFLT_OVERLAP
    """
    if not spec:
        spec = _DFLT_OVERLAP
    colon = spec.find(":")
    if colon >= 0:
        head = spec[:colon]
        if head == "" or head.isdigit():
            try:
                tries = max(0, int(head)) if head else 0
            except ValueError:
                tries = 0
            return tries, spec[colon + 1:]
    return 0, spec


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
        self.overlap = _DFLT_OVERLAP
        self.sep = 0.0
        self.pack = True
        self.use_grid = True
        # Edge attribute caches keyed by canonical (low, high) name pair.
        self._edge_len: dict[tuple[str, str], float] = {}
        self._edge_weight: dict[tuple[str, str], float] = {}
        # Routes populated by ``route_edges`` after layout.
        self.edge_routes: dict[tuple, EdgeRoute] = {}
        # Cluster tracking — populated by ``discover_clusters``
        # / ``build_node_to_cluster`` / ``compute_cluster_bboxes``
        # in :mod:`gvpy.engines.layout.fdp.cluster`.  Used by
        # cluster-aware edge routing (TODO §4.x); harmless on
        # flat graphs (lists / dicts stay empty).
        self._clusters: list[FdpCluster] = []
        self._cluster_parent: dict[str, Optional[str]] = {}
        self._cluster_level: dict[str, int] = {}
        self._node_to_cluster: dict[str, Optional[str]] = {}
        self._node_to_cluster_obj: dict[str, Optional[FdpCluster]] = {}

    # ── Public API ───────────────────────────────

    def layout(self) -> dict:
        self._init_from_graph()
        N = len(self.lnodes)
        if N == 0:
            return self._to_json()

        # Choose layout pipeline.  When clusters exist and the
        # deriveGraph gate is on (default since 2026-05-08), use
        # the C-aligned recursive two-level layout.  Otherwise
        # fall back to flat tlayout per connected component.
        import os as _os_dg
        use_derive_graph = (
            self._clusters
            and _os_dg.environ.get(
                "GVPY_FDP_DERIVE_GRAPH", "1"
            ) == "1"
        )

        if use_derive_graph:
            # Recursive bottom-up: lay out each cluster's interior
            # in its own coordinates, then lay out parents using
            # cluster proxies sized to each cluster's bbox.  See
            # ``gvpy/engines/layout/fdp/derive.py`` (port of C
            # ``lib/fdpgen/layout.c: layout()``).
            derive_graph_layout(self)
        else:
            adj = self._build_adjacency()
            components = self._find_components(adj)
            if len(components) > 1 and self.pack:
                for comp in components:
                    self._layout_component(comp)
                self._pack_components_lr(components,
                                         gap=max(self.K * 0.5, 36.0))
            else:
                self._layout_component(set(self.lnodes.keys()))

        # Phase 2 — overlap removal.  Mirrors ``fdp_xLayout``
        # (xlayout.c:325): parse the ``n:mode`` spec, run the
        # x_layout expansion pass for ``n`` tries (skipped if
        # ``n == 0``), then dispatch ``mode`` through the shared
        # common.adjust cleanup.  Default spec is "9:prism".
        tries, mode = _parse_overlap_spec(self.overlap)
        if tries > 0:
            remaining = xlayout(self, self.K, self.sep,
                                self.maxiter, tries=tries)
            if remaining == 0:
                mode = "true"   # already clear; skip cleanup
        self.overlap = mode
        remove_overlap(self)

        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        # Compute per-cluster bbox now that node positions have
        # settled (post-overlap, post-rotation/center).  Used by
        # cluster-aware edge routing.  No-op when the graph has no
        # clusters; harmless on flat graphs.
        if self._clusters:
            compute_cluster_bboxes(self)
            # Simple post-pass cluster fixes — only needed when
            # ``use_derive_graph`` is False (deriveGraph already
            # produces non-overlapping clusters with non-members
            # outside, so the simple fixes would just churn).
            if not use_derive_graph:
                # Cluster-level overlap removal: fdp's flat force
                # model has no awareness of cluster grouping, so
                # cluster bboxes computed from member positions can
                # still overlap visually after node-level overlap
                # removal.  This pass translates whole clusters
                # apart along the smaller-overlap axis until no
                # top-level pair overlaps.
                remove_cluster_overlap(self)
                # After cluster-level separation, non-member nodes
                # can still sit visually inside another cluster's
                # bbox if the force model pulled them there.  Push
                # them out along the shortest-escape axis.
                push_nonmembers_out_of_clusters(self)
            # Recompute cluster bboxes once more in case the prior
            # pass moved a member-of-other-cluster node enough to
            # change a cluster's bbox.
            compute_cluster_bboxes(self)
            # Phase B (TODO §4.x): clustered fdp graphs route via
            # the cluster-aware ``compoundEdges`` port.  Builds a
            # per-edge vconfig that excludes the endpoints'
            # enclosing clusters and any common ancestors so the
            # edge can exit/enter its own cluster.  Flat graphs
            # still use the single-vconfig flat router (faster +
            # matches neato's behaviour for non-cluster cases).
            route_edges_compound(self)
        else:
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

        ov_attr = self.graph.get_graph_attr("overlap")
        self.overlap = (ov_attr or _DFLT_OVERLAP).lower()

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
        # Walk root + every subgraph: edges declared inside a
        # cluster subgraph (e.g. ``cluster_X { a -- b; }``) live in
        # that subgraph's ``.edges`` dict, NOT root's.  Without
        # this enumeration the force model loses all intra-cluster
        # edges and cluster members have no internal cohesion.
        for key, edge in self._iter_all_edges():
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

        # Phase A of cluster-aware routing port (TODO §4.x):
        # discover clusters and build the node→cluster map up-front
        # so every downstream pass (xlayout, route_edges,
        # compoundEdges, _to_json) has a stable cluster topology.
        # Bbox computation is deferred to post-overlap
        # (see ``layout()``).
        discover_clusters(self)
        build_node_to_cluster(self)

    def _iter_all_edges(self):
        """Yield ``(key, edge)`` for every edge in the graph
        including those owned by subgraphs.

        See: ``gvpy.core._graph_traversal.gather_all_subgraphs``.
        Edges declared inside subgraph blocks are stored in the
        lowest-common-subgraph's ``.edges`` dict (mirrors C
        ``agedge`` ownership).  fdp's force model must see every
        edge — without this helper, intra-cluster edges are lost
        and cluster members have no internal cohesion.
        """
        for sg in gather_all_subgraphs(self.graph):
            for k, e in sg.edges.items():
                yield k, e

    def _build_adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = defaultdict(list)
        for name in self.lnodes:
            adj[name]
        for key, edge in self._iter_all_edges():
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
        # Walk all subgraphs so intra-cluster edges contribute spring
        # forces (otherwise cluster members have no cohesion).
        comp_edges: list[tuple[str, str, float, float]] = []
        for key, edge in self._iter_all_edges():
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

        # Edge spline points (overrides the base's 2-point fallback
        # when route_edges has computed splines).  Iterate the same
        # gather_all_subgraphs sequence the base used to build
        # ``result["edges"]`` so the zip stays aligned.
        if self.edge_routes:
            for entry, (key, edge) in zip(result["edges"],
                                          self._iter_all_edges()):
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

        # Cluster bboxes — populated by Phase A's
        # ``compute_cluster_bboxes`` for clustered graphs.  Format
        # matches dot's ``_to_json`` so the shared SVG renderer
        # (gvpy.render.svg_renderer._render_cluster) can draw the
        # cluster outline + label without engine-specific code.
        if self._clusters:
            clusters_json = []
            for cl in self._clusters:
                if cl.bb == (0.0, 0.0, 0.0, 0.0):
                    continue
                cl_entry: dict = {
                    "name": cl.name,
                    "label": cl.label,
                    "bb": [round(v, 2) for v in cl.bb],
                    "nodes": cl.nodes,
                }
                cl_entry.update(cl.attrs)
                clusters_json.append(cl_entry)
            if clusters_json:
                result["clusters"] = clusters_json
                # Expand graph bb to include cluster bboxes (which
                # already include the cluster margin).  Without
                # this the SVG ``viewBox`` clips cluster outlines
                # that extend beyond the node-only bounding box.
                if "graph" in result and "bb" in result["graph"]:
                    gx1, gy1, gx2, gy2 = result["graph"]["bb"]
                    for cl in self._clusters:
                        if cl.bb == (0.0, 0.0, 0.0, 0.0):
                            continue
                        cx1, cy1, cx2, cy2 = cl.bb
                        gx1 = min(gx1, cx1)
                        gy1 = min(gy1, cy1)
                        gx2 = max(gx2, cx2)
                        gy2 = max(gy2, cy2)
                    result["graph"]["bb"] = [
                        round(gx1, 2), round(gy1, 2),
                        round(gx2, 2), round(gy2, 2),
                    ]

        return result

    # ── Cluster-aware writeback for -Tdot ─────────

    def _write_back(self):
        """Write layout results back to graph object attributes.

        Extends the base ``_write_back`` (which handles nodes +
        edges + the root ``bb``) by setting ``bb=`` on every
        cluster subgraph so ``-Tdot`` round-trips include the
        post-layout cluster geometry.  Mirrors C
        ``-Tdot`` output where each cluster subgraph carries
        a ``bb="x1,y1,x2,y2"`` attribute.
        """
        super()._write_back()
        if not self._clusters:
            return

        # Map cluster name → Graph subgraph object.  Walk the tree
        # (clusters can nest at arbitrary depth) to find each one.
        cluster_subgraphs: dict[str, object] = {}

        def _index(g):
            for sub_name, sub in g.subgraphs.items():
                if sub_name.startswith("cluster"):
                    cluster_subgraphs[sub_name] = sub
                _index(sub)

        _index(self.graph)

        for cl in self._clusters:
            if cl.bb == (0.0, 0.0, 0.0, 0.0):
                continue
            sub = cluster_subgraphs.get(cl.name)
            if sub is None:
                continue
            x1, y1, x2, y2 = cl.bb
            # Write to the subgraph's own ``attr_record`` (which the
            # gv_writer iterates) rather than ``attr_dict_g`` (which
            # is the shared-default container ``set_graph_attr`` would
            # touch).  Without this the bb is set internally but
            # never makes it to ``-Tdot`` output.
            sub.attr_record["bb"] = (
                f"{round(x1, 2)},{round(y1, 2)},"
                f"{round(x2, 2)},{round(y2, 2)}"
            )

    # Shared methods inherited from LayoutEngine base class:
    # _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _estimate_label_size, _overlap_area, _compute_label_positions,
    # _clip_to_boundary, _find_components, _pack_components_lr.
