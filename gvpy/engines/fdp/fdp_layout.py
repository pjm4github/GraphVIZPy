"""
Fdp layout engine — Fruchterman-Reingold force-directed placement.

Port of Graphviz ``lib/fdpgen/``.  Two-phase algorithm:

Phase 1 (tlayout): Force-directed placement with grid-accelerated
repulsive forces and linear cooling.

Phase 2 (xlayout): Overlap removal using modified repulsive/attractive
forces that respect node bounding boxes.

Command-line usage::

    python gvcli.py -Kfdp input.gv -Tsvg -o output.svg

API usage::

    from gvpy.engines.fdp import FdpLayout
    result = FdpLayout(graph).layout()

Attributes
----------
Graph: K, maxiter, start, overlap, sep, dim, pack, normalize, center
Node: pos, pin, width, height, shape, label, K (per-node override)
Edge: len, weight
"""
from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.base import LayoutEngine


# ── Constants ────────────────────────────────────

_DFLT_K = 0.3 * 72.0           # 0.3 inches in points
_DFLT_MAXITER = 600
_EXPFACTOR = 1.2
_GRID_CELLS = 3                 # grid cell size = _GRID_CELLS * K
_PORT_REPULSION = 10.0


# ── Data structures ─────────────────────────────

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
    disp_x: float = 0.0         # displacement accumulator
    disp_y: float = 0.0


# ── Main layout class ───────────────────────────


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
        # Edge data
        self._edge_len: dict[tuple[str, str], float] = {}
        self._edge_weight: dict[tuple[str, str], float] = {}

    def layout(self) -> dict:
        """Run the fdp layout pipeline."""
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

        # Overlap removal (phase 2)
        if self.overlap not in ("true", "1", "yes"):
            self._remove_overlap()

        # Post-processing (inherited from LayoutEngine)
        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        self._compute_label_positions()
        self._write_back()
        return self._to_json()

    # ── Initialization ───────────────────────────

    def _init_from_graph(self):
        self._init_common_attrs()

        # Fdp-specific attributes
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

        self.pack = (self.graph.get_graph_attr("pack") or "true").lower() \
                    not in ("false", "0", "no")

        # Create layout nodes
        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)

            # Per-node K override
            if node:
                k_node = node.attributes.get("K")
                if k_node:
                    try:
                        # Store as node attribute for later use
                        pass
                    except ValueError:
                        pass

            # Read pos/pin
            pos_str = (node.attributes.get("pos") or "").strip() if node else ""
            if pos_str:
                try:
                    parts = pos_str.replace("!", "").split(",")
                    ln.x = float(parts[0]) * 72.0
                    ln.y = float(parts[1]) * 72.0
                    ln.pos_set = True
                    ln.pinned = "!" in pos_str or \
                                (node and node.attributes.get("pin", "").lower()
                                 in ("true", "1", "yes"))
                except (ValueError, IndexError):
                    pass
            elif node and node.attributes.get("pin", "").lower() \
                    in ("true", "1", "yes"):
                ln.pinned = True

            self.lnodes[name] = ln

        # Collect edge lengths and weights
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

    # ── Phase 1: Fruchterman-Reingold layout ─────

    def _layout_component(self, nodes: set[str]):
        """Force-directed layout for a connected component."""
        node_list = [n for n in self.lnodes if n in nodes]
        N = len(node_list)
        if N == 0:
            return
        if N == 1:
            ln = self.lnodes[node_list[0]]
            if not ln.pos_set:
                ln.x, ln.y = 0.0, 0.0
            return

        # Initial positions
        self._init_positions(node_list, N)

        # Compute initial temperature
        T0 = self.T0
        if T0 < 0:
            T0 = self.K * math.sqrt(N) / 5.0

        # Build adjacency for this component
        comp_edges = []
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if t in nodes and h in nodes:
                pair = (min(t, h), max(t, h))
                comp_edges.append((t, h, pair))

        # Grid cell size
        cell_size = _GRID_CELLS * self.K

        # Main iteration loop
        for iteration in range(self.maxiter):
            temp = T0 * (self.maxiter - iteration) / self.maxiter
            if temp <= 0:
                break

            # Clear displacements
            for name in node_list:
                ln = self.lnodes[name]
                ln.disp_x = 0.0
                ln.disp_y = 0.0

            # Repulsive forces (grid-accelerated)
            if self.use_grid and N > 20:
                self._grid_repulsion(node_list, cell_size)
            else:
                self._all_pairs_repulsion(node_list)

            # Attractive forces (along edges)
            for t, h, pair in comp_edges:
                self._apply_attraction(t, h, pair)

            # Update positions
            self._update_positions(node_list, temp)

    def _init_positions(self, node_list, N):
        """Set initial node positions."""
        span = self.K * (math.sqrt(N) + 1.0) * _EXPFACTOR
        for name in node_list:
            ln = self.lnodes[name]
            if ln.pos_set:
                continue
            ln.x = (random.random() - 0.5) * span
            ln.y = (random.random() - 0.5) * span

    def _all_pairs_repulsion(self, node_list):
        """Compute repulsive forces between all pairs (O(n^2))."""
        K2 = self.K * self.K
        for i in range(len(node_list)):
            pi = self.lnodes[node_list[i]]
            for j in range(i + 1, len(node_list)):
                pj = self.lnodes[node_list[j]]
                dx = pj.x - pi.x
                dy = pj.y - pi.y
                dist2 = dx * dx + dy * dy
                if dist2 < 0.01:
                    dx = random.random() * 0.1
                    dy = random.random() * 0.1
                    dist2 = dx * dx + dy * dy
                dist = math.sqrt(dist2)
                # F_rep = K^2 / d^3 (new formula)
                force = K2 / (dist * dist2)
                fx = dx * force
                fy = dy * force
                pj.disp_x += fx
                pj.disp_y += fy
                pi.disp_x -= fx
                pi.disp_y -= fy

    def _grid_repulsion(self, node_list, cell_size):
        """Grid-accelerated repulsive forces (O(n) average)."""
        K2 = self.K * self.K

        # Build grid
        grid: dict[tuple[int, int], list[str]] = defaultdict(list)
        for name in node_list:
            ln = self.lnodes[name]
            ci = int(math.floor(ln.x / cell_size))
            cj = int(math.floor(ln.y / cell_size))
            grid[(ci, cj)].append(name)

        # For each cell, compute forces with same cell and neighbor cells
        processed = set()
        for (ci, cj), cell_nodes in grid.items():
            # Within same cell
            for a in range(len(cell_nodes)):
                na = cell_nodes[a]
                pa = self.lnodes[na]
                for b in range(a + 1, len(cell_nodes)):
                    nb = cell_nodes[b]
                    pb = self.lnodes[nb]
                    self._repel_pair(pa, pb, K2)

            # Neighbor cells (only forward to avoid double-counting)
            for di in range(-1, 2):
                for dj in range(-1, 2):
                    if di == 0 and dj == 0:
                        continue
                    ni, nj = ci + di, cj + dj
                    neighbor_key = (ni, nj)
                    if neighbor_key not in grid:
                        continue
                    # Only process each cell pair once
                    pair_key = (min((ci, cj), neighbor_key),
                                max((ci, cj), neighbor_key))
                    if pair_key in processed:
                        continue
                    processed.add(pair_key)

                    for na in cell_nodes:
                        pa = self.lnodes[na]
                        for nb in grid[neighbor_key]:
                            pb = self.lnodes[nb]
                            self._repel_pair(pa, pb, K2)

    @staticmethod
    def _repel_pair(pa, pb, K2):
        """Apply repulsive force between two nodes."""
        dx = pb.x - pa.x
        dy = pb.y - pa.y
        dist2 = dx * dx + dy * dy
        if dist2 < 0.01:
            dx = random.random() * 0.1
            dy = random.random() * 0.1
            dist2 = dx * dx + dy * dy
        dist = math.sqrt(dist2)
        force = K2 / (dist * dist2)
        fx, fy = dx * force, dy * force
        pb.disp_x += fx
        pb.disp_y += fy
        pa.disp_x -= fx
        pa.disp_y -= fy

    def _apply_attraction(self, t_name, h_name, pair):
        """Apply attractive force along an edge."""
        pt = self.lnodes[t_name]
        ph = self.lnodes[h_name]
        dx = ph.x - pt.x
        dy = ph.y - pt.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.01:
            return

        edge_len = self._edge_len.get(pair, self.K)
        weight = self._edge_weight.get(pair, 1.0)

        # F_attr = weight * (d - len) / d
        force = weight * (dist - edge_len) / dist
        fx, fy = dx * force, dy * force

        pt.disp_x += fx
        pt.disp_y += fy
        ph.disp_x -= fx
        ph.disp_y -= fy

    def _update_positions(self, node_list, temp):
        """Update node positions, capping displacement by temperature."""
        for name in node_list:
            ln = self.lnodes[name]
            if ln.pinned:
                continue
            dx, dy = ln.disp_x, ln.disp_y
            disp_len = math.sqrt(dx * dx + dy * dy)
            if disp_len > 0:
                # Cap displacement at temperature
                if disp_len > temp:
                    scale = temp / disp_len
                    dx *= scale
                    dy *= scale
                ln.x += dx
                ln.y += dy

    # ── Phase 2: Overlap removal ─────────────────

    def _remove_overlap(self):
        """Remove node overlaps using modified force model.

        Port of fdp_xLayout from xlayout.c.
        """
        nodes = [ln for ln in self.lnodes.values()]
        N = len(nodes)
        if N < 2:
            return

        sep_x = self.sep
        sep_y = self.sep
        max_tries = 9
        x_maxiter = min(self.maxiter, 100)

        for attempt in range(max_tries):
            K_eff = self.K * (1 + attempt * 0.5)
            T0 = K_eff * math.sqrt(N) / 5.0

            for iteration in range(x_maxiter):
                temp = T0 * (x_maxiter - iteration) / x_maxiter
                if temp <= 0:
                    break

                # Clear displacements
                for ln in nodes:
                    ln.disp_x = 0.0
                    ln.disp_y = 0.0

                overlaps = 0

                # Repulsive forces with overlap detection
                K2 = K_eff * K_eff
                for i in range(N):
                    for j in range(i + 1, N):
                        a, b = nodes[i], nodes[j]
                        dx = b.x - a.x
                        dy = b.y - a.y
                        dist2 = dx * dx + dy * dy
                        if dist2 < 0.01:
                            dx = random.random() * 0.1
                            dy = random.random() * 0.1
                            dist2 = dx * dx + dy * dy

                        # Check overlap
                        is_overlap = (abs(dx) <= (a.width + b.width) / 2 + sep_x and
                                      abs(dy) <= (a.height + b.height) / 2 + sep_y)
                        if is_overlap:
                            overlaps += 1
                            force = 1.5 * K2 / dist2
                        else:
                            force = 0.1 * K2 / dist2

                        fx, fy = dx * force, dy * force
                        b.disp_x += fx
                        b.disp_y += fy
                        a.disp_x -= fx
                        a.disp_y -= fy

                # Attractive forces (edge-connected only, non-overlapping)
                for key, edge in self.graph.edges.items():
                    t_ln = self.lnodes.get(edge.tail.name)
                    h_ln = self.lnodes.get(edge.head.name)
                    if not t_ln or not h_ln:
                        continue
                    dx = h_ln.x - t_ln.x
                    dy = h_ln.y - t_ln.y
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist < 0.01:
                        continue

                    is_overlap = (abs(dx) <= (t_ln.width + h_ln.width) / 2 + sep_x and
                                  abs(dy) <= (t_ln.height + h_ln.height) / 2 + sep_y)
                    if is_overlap:
                        continue

                    rad_sum = math.sqrt((t_ln.width / 2) ** 2 + (t_ln.height / 2) ** 2) + \
                              math.sqrt((h_ln.width / 2) ** 2 + (h_ln.height / 2) ** 2)
                    dout = max(dist - rad_sum, 0.01)
                    force = dout * dout / ((K_eff + rad_sum) * dist)

                    fx, fy = dx * force, dy * force
                    t_ln.disp_x += fx
                    t_ln.disp_y += fy
                    h_ln.disp_x -= fx
                    h_ln.disp_y -= fy

                # Update positions
                for ln in nodes:
                    if ln.pinned:
                        continue
                    dx, dy = ln.disp_x, ln.disp_y
                    disp_len = math.sqrt(dx * dx + dy * dy)
                    if disp_len > temp:
                        scale = temp / disp_len
                        dx *= scale
                        dy *= scale
                    ln.x += dx
                    ln.y += dy

                if overlaps == 0:
                    return

            if overlaps == 0:
                return

    # Shared methods inherited from LayoutEngine base class:
    # _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _estimate_label_size, _overlap_area, _compute_label_positions,
    # _clip_to_boundary, _find_components, _pack_components_lr,
    # _write_back, _to_json
