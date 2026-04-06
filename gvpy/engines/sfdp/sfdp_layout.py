"""
Sfdp layout engine — scalable force-directed placement.

Port of Graphviz ``lib/sfdpgen/``.  Extends fdp with:

- **Multilevel coarsening**: Maximal independent edge set grouping,
  solve coarse → interpolate → refine
- **Barnes-Hut quadtree**: O(n log n) repulsive force approximation
- **Post-processing smoothing**: Optional stress majorization refinement

Command-line::

    python gvcli.py -Ksfdp input.gv -Tsvg -o output.svg

Attributes::

    K               — spring constant (default auto)
    repulsiveforce  — repulsive exponent (default 1)
    levels          — max coarsening levels
    smoothing       — post-processing: none, spring, avg_dist, graph_dist
    quadtree        — Barnes-Hut mode: normal, fast, none
    beautify        — arrange leaves in circle
    rotation        — rotate final layout (degrees)
    overlap         — overlap removal
    start           — random seed
    maxiter         — max iterations per level
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


_DFLT_K = 0.3 * 72.0
_DFLT_MAXITER = 200
_BH_THETA = 0.6          # Barnes-Hut opening angle threshold
_COARSEN_RATIO = 0.75     # stop coarsening when ratio > this
_COOLING = 0.90
_ADAPTIVE_C = 0.2         # attractive force constant


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
    disp_x: float = 0.0
    disp_y: float = 0.0
    mass: float = 1.0      # for coarsened super-nodes


@dataclass
class _QTNode:
    """Quadtree node for Barnes-Hut approximation."""
    cx: float = 0.0        # center of mass x
    cy: float = 0.0        # center of mass y
    mass: float = 0.0      # total mass
    x0: float = 0.0        # bounding box
    y0: float = 0.0
    size: float = 0.0      # side length
    children: list = field(default_factory=list)  # 4 children or empty
    is_leaf: bool = True
    node_idx: int = -1      # leaf: index of single node


class SfdpLayout(LayoutEngine):
    """Scalable force-directed placement layout engine."""

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.K = _DFLT_K
        self.maxiter = _DFLT_MAXITER
        self.max_levels = 100
        self.seed = 1
        self.overlap = "true"
        self.sep = 0.0
        self.pack = True
        self.repulsive_exp = 1.0
        self.smoothing = "none"
        self.use_quadtree = True
        self.beautify = False
        self.rotation_deg = 0.0
        self._edge_len: dict[tuple[str, str], float] = {}
        self._edge_weight: dict[tuple[str, str], float] = {}

    def layout(self) -> dict:
        self._init_from_graph()
        N = len(self.lnodes)
        if N == 0:
            return self._to_json()

        adj = self._build_adjacency()
        components = self._find_components(adj)

        if len(components) > 1 and self.pack:
            for comp in components:
                self._layout_component(comp, adj)
            self._pack_components_lr(components,
                                     gap=max(self.K * 0.5, 36.0))
        else:
            self._layout_component(set(self.lnodes.keys()), adj)

        # Overlap removal
        if self.overlap not in ("true", "1", "yes"):
            self._remove_overlap()

        # Sfdp-specific rotation
        if self.rotation_deg != 0:
            rad = math.radians(self.rotation_deg)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            for ln in self.lnodes.values():
                x, y = ln.x, ln.y
                ln.x = x * cos_a - y * sin_a
                ln.y = x * sin_a + y * cos_a

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

        levels_str = self.graph.get_graph_attr("levels")
        if levels_str:
            try:
                self.max_levels = int(levels_str)
            except ValueError:
                pass

        rf_str = self.graph.get_graph_attr("repulsiveforce")
        if rf_str:
            try:
                self.repulsive_exp = float(rf_str)
            except ValueError:
                pass

        self.smoothing = (self.graph.get_graph_attr("smoothing") or "none").lower()
        qt_str = (self.graph.get_graph_attr("quadtree") or "normal").lower()
        self.use_quadtree = qt_str not in ("none", "false", "0")
        self.beautify = (self.graph.get_graph_attr("beautify") or "").lower() \
                        in ("true", "1", "yes")

        rot_str = self.graph.get_graph_attr("rotation")
        if rot_str:
            try:
                self.rotation_deg = float(rot_str)
            except ValueError:
                pass

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

        start_str = self.graph.get_graph_attr("start") or ""
        if start_str.isdigit():
            self.seed = int(start_str)
        elif start_str == "random":
            import time
            self.seed = int(time.time())
        random.seed(self.seed)

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
                    ln.pinned = "!" in pos_str or \
                                (node and node.attributes.get("pin", "").lower()
                                 in ("true", "1", "yes"))
                except (ValueError, IndexError):
                    pass
            self.lnodes[name] = ln

        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            pair = (min(t, h), max(t, h))
            try:
                self._edge_len[pair] = float(edge.attributes.get("len", "")) * 72.0
            except (ValueError, TypeError):
                self._edge_len[pair] = self.K
            try:
                self._edge_weight[pair] = float(edge.attributes.get("weight", "1.0"))
            except ValueError:
                self._edge_weight[pair] = 1.0

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

    # ── Multilevel layout ────────────────────────

    def _layout_component(self, nodes: set[str], adj: dict[str, list[str]]):
        """Multilevel spring-electrical layout for a component."""
        node_list = [n for n in self.lnodes if n in nodes]
        N = len(node_list)
        if N == 0:
            return
        if N == 1:
            ln = self.lnodes[node_list[0]]
            if not ln.pos_set:
                ln.x, ln.y = 0.0, 0.0
            return

        # Build coarsening hierarchy
        levels = self._build_hierarchy(node_list, adj)

        # Solve at coarsest level
        coarsest = levels[-1]
        K_level = self.K
        for _ in range(len(levels) - 1):
            K_level *= 0.75

        self._init_positions(coarsest["nodes"], len(coarsest["nodes"]))
        self._spring_electrical(coarsest["nodes"], coarsest["adj"],
                                K_level, self.maxiter)

        # Uncoarsen: interpolate and refine
        for level_idx in range(len(levels) - 2, -1, -1):
            level = levels[level_idx]
            parent = levels[level_idx + 1]
            mapping = level.get("mapping", {})

            # Prolongate: interpolate positions from parent
            for name in level["nodes"]:
                ln = self.lnodes[name]
                parent_name = mapping.get(name, name)
                if parent_name in self.lnodes:
                    parent_ln = self.lnodes[parent_name]
                    if not ln.pos_set:
                        ln.x = parent_ln.x + (random.random() - 0.5) * K_level * 0.1
                        ln.y = parent_ln.y + (random.random() - 0.5) * K_level * 0.1

            K_level = self.K
            iters = min(self.maxiter, max(50, self.maxiter // (level_idx + 2)))
            self._spring_electrical(level["nodes"], level["adj"],
                                    K_level, iters)

        # Smoothing post-process
        if self.smoothing == "spring":
            self._spring_electrical(node_list, adj, self.K, 50)

        # Beautify: arrange leaf nodes in circle
        if self.beautify:
            self._beautify_leaves(node_list, adj)

    def _build_hierarchy(self, node_list: list[str],
                         adj: dict[str, list[str]]) -> list[dict]:
        """Build multilevel hierarchy via maximal independent edge set."""
        levels = [{"nodes": node_list, "adj": adj}]

        current_nodes = set(node_list)
        current_adj = adj

        for level in range(self.max_levels):
            N = len(current_nodes)
            if N <= 4:
                break

            # Find maximal independent edge set (greedy matching)
            matched: set[str] = set()
            groups: dict[str, str] = {}  # node → representative
            representatives: set[str] = set()

            # Sort edges by weight (heaviest first)
            edges = []
            for u in current_nodes:
                for v in current_adj.get(u, []):
                    if v in current_nodes and u < v:
                        pair = (min(u, v), max(u, v))
                        w = self._edge_weight.get(pair, 1.0)
                        edges.append((w, u, v))
            edges.sort(reverse=True)

            for w, u, v in edges:
                if u not in matched and v not in matched:
                    matched.add(u)
                    matched.add(v)
                    groups[u] = u
                    groups[v] = u  # v maps to u
                    representatives.add(u)
                    # Average positions
                    lu, lv = self.lnodes.get(u), self.lnodes.get(v)
                    if lu and lv:
                        lu.mass += lv.mass

            # Unmatched nodes become their own representative
            for n in current_nodes:
                if n not in groups:
                    groups[n] = n
                    representatives.add(n)

            # Check coarsening ratio
            if len(representatives) / N > _COARSEN_RATIO:
                break

            # Build coarsened adjacency
            coarse_adj: dict[str, list[str]] = defaultdict(list)
            for rep in representatives:
                coarse_adj[rep]
            for u in current_nodes:
                for v in current_adj.get(u, []):
                    if v in current_nodes:
                        ru, rv = groups[u], groups[v]
                        if ru != rv and rv not in coarse_adj[ru]:
                            coarse_adj[ru].append(rv)
                            coarse_adj[rv].append(ru)

            level_data = {
                "nodes": list(representatives),
                "adj": dict(coarse_adj),
                "mapping": groups,
            }
            levels.append(level_data)

            current_nodes = representatives
            current_adj = dict(coarse_adj)

        return levels

    def _init_positions(self, node_list, N):
        span = self.K * (math.sqrt(N) + 1.0)
        for name in node_list:
            ln = self.lnodes.get(name)
            if ln and not ln.pos_set:
                ln.x = (random.random() - 0.5) * span
                ln.y = (random.random() - 0.5) * span

    # ── Spring-electrical solver ─────────────────

    def _spring_electrical(self, node_list: list[str],
                           adj: dict[str, list[str]],
                           K: float, maxiter: int):
        """Spring-electrical force computation with optional quadtree."""
        N = len(node_list)
        if N < 2:
            return

        step = K
        K2 = K * K
        p = self.repulsive_exp

        for iteration in range(maxiter):
            # Clear displacements
            for name in node_list:
                ln = self.lnodes[name]
                ln.disp_x = 0.0
                ln.disp_y = 0.0

            # Repulsive forces
            if self.use_quadtree and N > 45:
                self._quadtree_repulsion(node_list, K, p)
            else:
                self._allpairs_repulsion(node_list, K, p)

            # Attractive forces
            seen = set()
            for u in node_list:
                for v in adj.get(u, []):
                    if v in set(node_list):
                        pair_key = (min(u, v), max(u, v))
                        if pair_key in seen:
                            continue
                        seen.add(pair_key)
                        pu, pv = self.lnodes[u], self.lnodes[v]
                        dx = pv.x - pu.x
                        dy = pv.y - pu.y
                        dist = math.sqrt(dx * dx + dy * dy)
                        if dist < 0.01:
                            continue
                        edge_len = self._edge_len.get(pair_key, K)
                        w = self._edge_weight.get(pair_key, 1.0)
                        # F_attr = C * d^2 / (K * d_ij)
                        force = _ADAPTIVE_C * w * dist / (K * max(edge_len / 72.0, 0.01))
                        fx, fy = dx / dist * force, dy / dist * force
                        pu.disp_x += fx
                        pu.disp_y += fy
                        pv.disp_x -= fx
                        pv.disp_y -= fy

            # Update positions with adaptive step
            max_disp = 0.0
            for name in node_list:
                ln = self.lnodes[name]
                if ln.pinned:
                    continue
                d = math.sqrt(ln.disp_x ** 2 + ln.disp_y ** 2)
                if d > 0:
                    scale = min(step, d) / d
                    ln.x += ln.disp_x * scale
                    ln.y += ln.disp_y * scale
                    max_disp = max(max_disp, d)

            # Adaptive cooling
            step *= _COOLING
            if max_disp < K * 0.001:
                break

    def _allpairs_repulsion(self, node_list, K, p):
        """O(n^2) repulsive forces."""
        Kp = K ** (1 + p)
        for i in range(len(node_list)):
            pi = self.lnodes[node_list[i]]
            for j in range(i + 1, len(node_list)):
                pj = self.lnodes[node_list[j]]
                dx = pj.x - pi.x
                dy = pj.y - pi.y
                dist2 = dx * dx + dy * dy
                if dist2 < 0.01:
                    dx += random.random() * 0.1
                    dy += random.random() * 0.1
                    dist2 = dx * dx + dy * dy
                dist = math.sqrt(dist2)
                # F_rep = K^(1+p) / dist^(1+p)
                force = Kp / (dist ** (1 + p))
                fx, fy = dx / dist * force, dy / dist * force
                pj.disp_x += fx
                pj.disp_y += fy
                pi.disp_x -= fx
                pi.disp_y -= fy

    # ── Barnes-Hut quadtree ──────────────────────

    def _quadtree_repulsion(self, node_list, K, p):
        """O(n log n) Barnes-Hut repulsive forces."""
        nodes_data = [(self.lnodes[n].x, self.lnodes[n].y,
                        self.lnodes[n].mass) for n in node_list]
        N = len(nodes_data)

        # Compute bounding box
        min_x = min(d[0] for d in nodes_data)
        max_x = max(d[0] for d in nodes_data)
        min_y = min(d[1] for d in nodes_data)
        max_y = max(d[1] for d in nodes_data)
        size = max(max_x - min_x, max_y - min_y, 1.0)

        # Build quadtree
        root = _QTNode(x0=min_x, y0=min_y, size=size)
        for i in range(N):
            self._qt_insert(root, i, nodes_data[i][0], nodes_data[i][1],
                            nodes_data[i][2])

        # Compute forces
        Kp = K ** (1 + p)
        for i in range(N):
            fx, fy = self._qt_force(root, i, nodes_data[i][0],
                                     nodes_data[i][1], Kp, p)
            ln = self.lnodes[node_list[i]]
            ln.disp_x += fx
            ln.disp_y += fy

    def _qt_insert(self, node: _QTNode, idx: int, x: float, y: float,
                   mass: float):
        """Insert a point into the quadtree."""
        if node.mass == 0 and node.is_leaf:
            node.cx, node.cy = x, y
            node.mass = mass
            node.node_idx = idx
            return

        if node.is_leaf and node.mass > 0:
            # Split: move existing point to child
            node.is_leaf = False
            half = node.size / 2
            node.children = [
                _QTNode(x0=node.x0, y0=node.y0, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0, size=half),
                _QTNode(x0=node.x0, y0=node.y0 + half, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0 + half, size=half),
            ]
            # Re-insert old point
            oi = self._qt_quadrant(node, node.cx, node.cy)
            self._qt_insert(node.children[oi], node.node_idx,
                            node.cx, node.cy, node.mass)
            node.node_idx = -1

        # Insert new point
        qi = self._qt_quadrant(node, x, y)
        if not node.children:
            half = node.size / 2
            node.children = [
                _QTNode(x0=node.x0, y0=node.y0, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0, size=half),
                _QTNode(x0=node.x0, y0=node.y0 + half, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0 + half, size=half),
            ]
        self._qt_insert(node.children[qi], idx, x, y, mass)

        # Update center of mass
        total = node.mass + mass
        node.cx = (node.cx * node.mass + x * mass) / total
        node.cy = (node.cy * node.mass + y * mass) / total
        node.mass = total

    @staticmethod
    def _qt_quadrant(node: _QTNode, x: float, y: float) -> int:
        half = node.size / 2
        mx = node.x0 + half
        my = node.y0 + half
        if x < mx:
            return 2 if y >= my else 0
        else:
            return 3 if y >= my else 1

    def _qt_force(self, node: _QTNode, idx: int, x: float, y: float,
                  Kp: float, p: float) -> tuple[float, float]:
        """Compute repulsive force on point idx from quadtree node."""
        if node.mass == 0:
            return 0.0, 0.0

        dx = node.cx - x
        dy = node.cy - y
        dist2 = dx * dx + dy * dy

        if node.is_leaf:
            if node.node_idx == idx:
                return 0.0, 0.0
            if dist2 < 0.01:
                dx += random.random() * 0.1
                dy += random.random() * 0.1
                dist2 = dx * dx + dy * dy
            dist = math.sqrt(dist2)
            force = Kp * node.mass / (dist ** (1 + p))
            return -dx / dist * force, -dy / dist * force

        # Check Barnes-Hut criterion: size/distance < theta
        dist = math.sqrt(max(dist2, 0.01))
        if node.size / dist < _BH_THETA:
            # Treat as single mass
            force = Kp * node.mass / (dist ** (1 + p))
            return -dx / dist * force, -dy / dist * force

        # Recurse into children
        fx, fy = 0.0, 0.0
        for child in node.children:
            cfx, cfy = self._qt_force(child, idx, x, y, Kp, p)
            fx += cfx
            fy += cfy
        return fx, fy

    # ── Beautify ─────────────────────────────────

    def _beautify_leaves(self, node_list, adj):
        """Arrange leaf nodes (degree 1) in a circle around their neighbor."""
        for name in node_list:
            nbrs = [n for n in adj.get(name, []) if n in set(node_list)]
            if len(nbrs) != 1:
                continue
            parent = self.lnodes[nbrs[0]]
            leaf = self.lnodes[name]
            # Count siblings
            siblings = [n for n in adj.get(nbrs[0], [])
                        if n in set(node_list) and
                        len(adj.get(n, [])) == 1]
            if len(siblings) <= 1:
                continue
            idx = siblings.index(name)
            angle = 2 * math.pi * idx / len(siblings)
            radius = self.K * 0.8
            leaf.x = parent.x + radius * math.cos(angle)
            leaf.y = parent.y + radius * math.sin(angle)

    # ── Overlap removal ──────────────────────────

    def _remove_overlap(self):
        """Simple iterative overlap removal."""
        nodes = list(self.lnodes.values())
        N = len(nodes)
        if N < 2:
            return
        for _ in range(50):
            has_overlap = False
            for i in range(N):
                for j in range(i + 1, N):
                    a, b = nodes[i], nodes[j]
                    dx, dy = b.x - a.x, b.y - a.y
                    dist = math.sqrt(dx * dx + dy * dy)
                    min_d = ((a.width + b.width) / 2 +
                             (a.height + b.height) / 2 + self.sep) * 0.5
                    if dist < min_d and dist > 0:
                        has_overlap = True
                        push = (min_d - dist) / 2 + 1
                        ux, uy = dx / dist, dy / dist
                        if not a.pinned:
                            a.x -= ux * push
                            a.y -= uy * push
                        if not b.pinned:
                            b.x += ux * push
                            b.y += uy * push
            if not has_overlap:
                break

    # Shared from LayoutEngine: _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _compute_label_positions, _clip_to_boundary, _find_components,
    # _pack_components_lr, _write_back, _to_json
