"""
Twopi layout engine — radial layout.

Port of Graphviz ``lib/twopigen/circle.c``.  Places nodes on
concentric circles (rings) radiating outward from a root node.

Algorithm:
  1. Select root node (from attribute, or graph center via eccentricity)
  2. BFS from root assigns ring levels (distance from root)
  3. Bottom-up: count leaves per subtree
  4. Top-down: allocate angular span proportional to subtree leaf count
  5. Convert polar (ring, angle) to Cartesian (x, y) using ranksep

Command-line::

    python gvcli.py -Ktwopi input.gv -Tsvg -o output.svg

Attributes::

    root      — root node name (or auto-detect from graph center)
    ranksep   — distance between rings (inches, default 1.0)
    overlap   — overlap removal
    weight    — edge weight (0 = ignore in BFS)
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.base import LayoutEngine


_DFLT_RANKSEP = 1.0 * 72.0  # 1 inch in points


@dataclass
class LayoutNode:
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False
    # Radial layout data
    level: int = -1          # BFS distance from root (-1 = unvisited)
    parent: str = ""         # parent in BFS tree
    children: list[str] = field(default_factory=list)
    subtree_leaves: int = 0  # leaf count in subtree
    theta: float = 0.0       # angular position (radians)
    span: float = 0.0        # angular span allocated


class TwopiLayout(LayoutEngine):
    """Radial layout engine."""

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.root_name: str = ""
        self.ranksep: list[float] = [_DFLT_RANKSEP]
        self.overlap = "true"
        self.pack = True

    def layout(self) -> dict:
        self._init_from_graph()
        N = len(self.lnodes)
        if N == 0:
            return self._to_json()

        adj = self._build_adjacency()
        components = self._find_components(adj)

        if len(components) > 1 and self.pack:
            for comp in components:
                self._layout_component(list(comp), adj)
            self._pack_components_lr(components, gap=_DFLT_RANKSEP)
        else:
            self._layout_component(list(self.lnodes.keys()), adj)

        # Overlap removal
        if self.overlap not in ("true", "1", "yes"):
            self._remove_overlap()

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

        self.root_name = self.graph.get_graph_attr("root") or ""

        rs_str = self.graph.get_graph_attr("ranksep")
        if rs_str:
            try:
                parts = rs_str.split(":")
                self.ranksep = [float(p) * 72.0 for p in parts if p.strip()]
            except ValueError:
                try:
                    self.ranksep = [float(rs_str) * 72.0]
                except ValueError:
                    pass

        ov_str = (self.graph.get_graph_attr("overlap") or "true").lower()
        self.overlap = ov_str
        self.pack = (self.graph.get_graph_attr("pack") or "true").lower() \
                    not in ("false", "0", "no")

        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)
            # Check node-level root attribute
            if node and node.attributes.get("root", "").lower() in ("true", "1"):
                self.root_name = name
            self.lnodes[name] = ln

    def _build_adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = defaultdict(list)
        for name in self.lnodes:
            adj[name]
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if t not in self.lnodes or h not in self.lnodes:
                continue
            # Skip edges with weight=0
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

    # ── Component layout ─────────────────────────

    def _layout_component(self, node_list: list[str],
                          adj: dict[str, list[str]]):
        """Radial layout for a single connected component."""
        N = len(node_list)
        if N == 0:
            return
        if N == 1:
            ln = self.lnodes[node_list[0]]
            ln.x, ln.y = 0.0, 0.0
            return

        node_set = set(node_list)

        # Select root
        root = self._select_root(node_list, adj, node_set)

        # BFS: assign levels and build tree
        self._bfs_levels(root, adj, node_set)

        # Count subtree leaves (bottom-up)
        self._count_leaves(root)

        # Assign angular spans (top-down)
        # Graphviz starts the first child at angle π (west/left), so
        # the root's theta is set to π so children radiate from the left.
        root_ln = self.lnodes[root]
        root_ln.theta = math.pi
        root_ln.span = 2 * math.pi
        self._assign_angles(root)

        # Convert polar to Cartesian
        self._polar_to_cartesian()

    # ── Root selection ───────────────────────────

    def _select_root(self, node_list: list[str],
                     adj: dict[str, list[str]],
                     node_set: set[str]) -> str:
        """Select root: from attribute, or find graph center."""
        # User-specified root
        if self.root_name and self.root_name in node_set:
            return self.root_name

        # Find center node: minimum eccentricity (max distance to any node)
        # Use double-BFS: find farthest from arbitrary start, then farthest
        # from that, then pick midpoint
        best_node = node_list[0]
        best_ecc = float("inf")

        # Sample a few starting points for speed
        samples = node_list[:min(3, len(node_list))]
        for start in samples:
            dist = self._bfs_distances(start, adj, node_set)
            ecc = max(dist.values()) if dist else 0
            if ecc < best_ecc:
                best_ecc = ecc
                best_node = start

        # Refine: find the node with minimum eccentricity from the
        # farthest-node search
        dist = self._bfs_distances(best_node, adj, node_set)
        if dist:
            farthest = max(dist, key=dist.get)
            dist2 = self._bfs_distances(farthest, adj, node_set)
            # Find midpoint of diameter path
            best_ecc = float("inf")
            for n in node_list:
                d1 = dist.get(n, 0)
                d2 = dist2.get(n, 0)
                ecc = max(d1, d2)
                if ecc < best_ecc:
                    best_ecc = ecc
                    best_node = n

        return best_node

    @staticmethod
    def _bfs_distances(start: str, adj: dict[str, list[str]],
                       node_set: set[str]) -> dict[str, int]:
        """BFS distances from start to all reachable nodes."""
        dist = {start: 0}
        queue = deque([start])
        while queue:
            u = queue.popleft()
            for v in adj.get(u, []):
                if v in node_set and v not in dist:
                    dist[v] = dist[u] + 1
                    queue.append(v)
        return dist

    # ── BFS level assignment ─────────────────────

    def _bfs_levels(self, root: str, adj: dict[str, list[str]],
                    node_set: set[str]):
        """BFS from root: assign levels and build parent-child tree."""
        root_ln = self.lnodes[root]
        root_ln.level = 0
        root_ln.parent = ""
        root_ln.children = []

        queue = deque([root])
        visited = {root}

        while queue:
            u = queue.popleft()
            u_ln = self.lnodes[u]
            for v in adj.get(u, []):
                if v in node_set and v not in visited:
                    visited.add(v)
                    v_ln = self.lnodes[v]
                    v_ln.level = u_ln.level + 1
                    v_ln.parent = u
                    v_ln.children = []
                    u_ln.children.append(v)
                    queue.append(v)

    # ── Subtree leaf counting ────────────────────

    def _count_leaves(self, root: str):
        """Bottom-up DFS: count leaves in each subtree."""
        def _count(name: str) -> int:
            ln = self.lnodes[name]
            if not ln.children:
                ln.subtree_leaves = 1
                return 1
            total = 0
            for child in ln.children:
                total += _count(child)
            ln.subtree_leaves = total
            return total
        _count(root)

    # ── Angular span allocation ──────────────────

    def _assign_angles(self, root: str):
        """Top-down: allocate angular span proportional to subtree leaves."""
        root_ln = self.lnodes[root]
        if not root_ln.children:
            return

        total_leaves = root_ln.subtree_leaves
        if total_leaves <= 0:
            total_leaves = 1

        start_angle = root_ln.theta - root_ln.span / 2

        for child_name in root_ln.children:
            child_ln = self.lnodes[child_name]
            child_frac = child_ln.subtree_leaves / total_leaves
            child_ln.span = root_ln.span * child_frac
            child_ln.theta = start_angle + child_ln.span / 2
            start_angle += child_ln.span

            # Recurse
            self._assign_angles(child_name)

    # ── Polar to Cartesian ───────────────────────

    def _polar_to_cartesian(self):
        """Convert (level, theta) to (x, y) using ranksep for ring gaps."""
        for name, ln in self.lnodes.items():
            if ln.level < 0:
                continue  # unvisited (disconnected)
            if ln.level == 0:
                ln.x, ln.y = 0.0, 0.0
            else:
                radius = self._get_radius(ln.level)
                ln.x = radius * math.cos(ln.theta)
                ln.y = radius * math.sin(ln.theta)

    def _get_radius(self, level: int) -> float:
        """Get cumulative radius for a given BFS level."""
        total = 0.0
        for i in range(level):
            if i < len(self.ranksep):
                total += self.ranksep[i]
            else:
                total += self.ranksep[-1]  # repeat last value
        return total

    # ── Overlap removal ──────────────────────────

    def _remove_overlap(self):
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
                             (a.height + b.height) / 2) * 0.5
                    if dist < min_d and dist > 0:
                        has_overlap = True
                        push = (min_d - dist) / 2 + 1
                        ux, uy = dx / dist, dy / dist
                        a.x -= ux * push
                        a.y -= uy * push
                        b.x += ux * push
                        b.y += uy * push
            if not has_overlap:
                break

    # Shared from LayoutEngine: _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _compute_label_positions, _clip_to_boundary, _find_components,
    # _pack_components_lr, _write_back, _to_json
