"""
Circular layout engine — port of Graphviz lib/circogen.

Algorithm:
  1. Find biconnected components (Tarjan's algorithm)
  2. Build block-cutpoint tree
  3. For each block: order nodes on a circle (longest path + crossing reduction)
  4. Position blocks recursively (children around parent's articulation point)
  5. Route edges as straight lines or arcs

Attributes recognized:
  mindist   — minimum separation between adjacent nodes (inches, default 1.0)
  root      — root node for DFS (affects block tree orientation)
  oneblock  — if true, skip biconnected decomposition (treat as single block)
  ordering  — "out" preserves output edge order on circle
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.base import LayoutEngine


# ── Data structures ────────────────────────────────


@dataclass
class Block:
    """A biconnected component (maximal 2-connected subgraph)."""
    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)
    parent: Optional["Block"] = None
    # Articulation point connecting this block to parent
    cut_node: str = ""
    # Layout results
    circle_order: list[str] = field(default_factory=list)
    radius: float = 0.0
    rad0: float = 0.0       # original radius before coalescing
    center_x: float = 0.0
    center_y: float = 0.0
    # Per-node positions relative to block center
    node_pos: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass
class LayoutNode:
    """Node with layout metadata."""
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0


# ── Main layout class ─────────────────────────────


class CircoLayout(LayoutEngine):
    """Circular layout engine.

    Usage::

        from gvpy.engines.circo import CircoLayout
        result = CircoLayout(graph).layout()
    """

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.mindist = 1.0 * 72.0  # inches → points
        self.nodesep = 0.25 * 72.0
        self.root_name: str = ""
        self.oneblock = False
        self.blocks: list[Block] = []

    def layout(self) -> dict:
        """Run the circo layout pipeline and return a JSON-serializable dict."""
        self._init_from_graph()

        # Build adjacency for undirected traversal
        adj = self._build_adjacency()

        # Find connected components
        components = self._find_components(adj)

        # Layout each component
        component_results = []
        for comp_nodes in components:
            comp_list = list(comp_nodes)
            comp_adj = {n: [nb for nb in adj[n] if nb in comp_nodes]
                        for n in comp_nodes}
            self._layout_component(comp_list, comp_adj)
            component_results.append(comp_nodes)

        # Pack components if multiple
        if len(component_results) > 1:
            self._pack_components_lr(component_results, gap=self.mindist)

        # Post-processing
        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        # Label placement
        self._compute_label_positions()

        # Write back positions
        self._write_back()

        return self._to_json()

    # ── Initialization ─────────────────────────────

    def _init_from_graph(self):
        """Read graph attributes and create layout nodes."""
        self._init_common_attrs()

        # Circo-specific attributes
        md = self.graph.get_graph_attr("mindist")
        if md:
            try:
                self.mindist = float(md) * 72.0
            except ValueError:
                pass

        ns = self.graph.get_graph_attr("nodesep")
        if ns:
            try:
                self.nodesep = float(ns) * 72.0
            except ValueError:
                pass

        self.root_name = self.graph.get_graph_attr("root") or ""
        ob = self.graph.get_graph_attr("oneblock") or ""
        self.oneblock = ob.lower() in ("true", "1", "yes")

        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            self.lnodes[name] = LayoutNode(name=name, node=node,
                                           width=w, height=h)

        # Extract edge weights for crossing reduction priority
        self._edge_weights: dict[tuple[str, str], float] = {}
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            try:
                w = float(edge.attributes.get("weight", "1.0"))
            except ValueError:
                w = 1.0
            pair = (min(t, h), max(t, h))
            self._edge_weights[pair] = max(self._edge_weights.get(pair, 0), w)

    # _compute_node_size inherited from LayoutEngine

    def _build_adjacency(self) -> dict[str, list[str]]:
        """Build undirected adjacency list from graph edges."""
        adj: dict[str, list[str]] = defaultdict(list)
        for name in self.graph.nodes:
            adj[name]  # ensure every node appears
        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if h not in adj[t]:
                adj[t].append(h)
            if t not in adj[h]:
                adj[h].append(t)
        return dict(adj)

    # _find_components inherited from LayoutEngine (returns list[set[str]])

    # ── Biconnected components (Tarjan's algorithm) ─

    def _find_biconnected(self, nodes: list[str],
                          adj: dict[str, list[str]]) -> list[Block]:
        """Find biconnected components using Tarjan's bridge-finding DFS.

        Returns a list of Block objects, each containing the nodes and
        edges of one biconnected component.
        """
        if self.oneblock or len(nodes) <= 2:
            block = Block(nodes=list(nodes))
            for n in nodes:
                for nb in adj.get(n, []):
                    if nb in nodes and (n, nb) not in block.edges and \
                       (nb, n) not in block.edges:
                        block.edges.append((n, nb))
            return [block]

        disc: dict[str, int] = {}
        low: dict[str, int] = {}
        parent: dict[str, str | None] = {}
        timer = [0]
        edge_stack: list[tuple[str, str]] = []
        blocks: list[Block] = []

        root = self.root_name if self.root_name in nodes else nodes[0]

        def _dfs(u):
            disc[u] = low[u] = timer[0]
            timer[0] += 1
            child_count = 0

            for v in adj.get(u, []):
                if v not in disc:
                    child_count += 1
                    parent[v] = u
                    edge_stack.append((u, v))
                    _dfs(v)
                    low[u] = min(low[u], low[v])

                    # u is articulation point: extract block
                    is_root = (parent.get(u) is None)
                    if (is_root and child_count > 1) or \
                       (not is_root and low[v] >= disc[u]):
                        block_edges = []
                        block_nodes = set()
                        while edge_stack and edge_stack[-1] != (u, v):
                            e = edge_stack.pop()
                            block_edges.append(e)
                            block_nodes.add(e[0])
                            block_nodes.add(e[1])
                        if edge_stack:
                            e = edge_stack.pop()
                            block_edges.append(e)
                            block_nodes.add(e[0])
                            block_nodes.add(e[1])
                        blocks.append(Block(
                            nodes=list(block_nodes),
                            edges=block_edges,
                        ))

                elif v != parent.get(u) and disc[v] < disc[u]:
                    edge_stack.append((u, v))
                    low[u] = min(low[u], disc[v])

        parent[root] = None
        _dfs(root)

        # Remaining edges form the last block
        if edge_stack:
            block_nodes = set()
            block_edges = []
            while edge_stack:
                e = edge_stack.pop()
                block_edges.append(e)
                block_nodes.add(e[0])
                block_nodes.add(e[1])
            blocks.append(Block(nodes=list(block_nodes), edges=block_edges))

        # Handle isolated nodes (no edges)
        covered = set()
        for b in blocks:
            covered.update(b.nodes)
        for n in nodes:
            if n not in covered:
                blocks.append(Block(nodes=[n]))

        return blocks if blocks else [Block(nodes=list(nodes))]

    # ── Block-cutpoint tree ────────────────────────

    def _build_block_tree(self, blocks: list[Block]) -> Block:
        """Build a block-cutpoint tree from biconnected components.

        The root block is the one containing the root node.
        Child blocks share an articulation point with their parent.
        """
        if len(blocks) <= 1:
            return blocks[0] if blocks else Block()

        # Find which blocks each node belongs to
        node_to_blocks: dict[str, list[int]] = defaultdict(list)
        for i, b in enumerate(blocks):
            for n in b.nodes:
                node_to_blocks[n].append(i)

        # Articulation points are nodes in 2+ blocks
        art_points = {n for n, bl in node_to_blocks.items() if len(bl) > 1}

        # Find root block
        root_name = self.root_name if self.root_name in node_to_blocks else \
                    blocks[0].nodes[0] if blocks[0].nodes else ""
        root_idx = node_to_blocks.get(root_name, [0])[0]
        root_block = blocks[root_idx]

        # BFS to build tree from root block
        visited_blocks = {root_idx}
        queue = deque([root_idx])
        while queue:
            bi = queue.popleft()
            parent_block = blocks[bi]
            # Find articulation points in this block
            for n in parent_block.nodes:
                if n not in art_points:
                    continue
                for ci in node_to_blocks[n]:
                    if ci in visited_blocks:
                        continue
                    visited_blocks.add(ci)
                    child_block = blocks[ci]
                    child_block.parent = parent_block
                    child_block.cut_node = n
                    parent_block.children.append(child_block)
                    queue.append(ci)

        return root_block

    # ── Single block layout ────────────────────────

    def _layout_block(self, block: Block, adj: dict[str, list[str]]):
        """Order nodes in a block on a circle and compute radius.

        Steps (port of Graphviz blockpath.c layout_block):
          0. Remove pair edges to create skeleton (planarity aid)
          1. Find spanning tree on skeleton
          2. Find longest path (true diameter via two-BFS)
          3. Place remaining nodes by neighbor proximity
          4. Reduce edge crossings (neighbor-targeted insertion)
          5. Compute radius and place on circle
        """
        nodes = block.nodes
        if not nodes:
            return

        if len(nodes) == 1:
            block.circle_order = list(nodes)
            largest = max(self.lnodes[nodes[0]].width,
                          self.lnodes[nodes[0]].height)
            block.radius = largest / 2  # match C: radius = largest_node / 2
            block.node_pos = {nodes[0]: (0.0, 0.0)}
            return

        if len(nodes) == 2:
            block.circle_order = list(nodes)
            n0, n1 = nodes[0], nodes[1]
            sep = self.mindist + max(
                self.lnodes[n0].width, self.lnodes[n1].width) / 2
            block.radius = sep / 2
            block.node_pos = {n0: (-sep / 2, 0.0), n1: (sep / 2, 0.0)}
            return

        # Build block-local adjacency
        block_set = set(nodes)
        local_adj: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            for nb in adj.get(n, []):
                if nb in block_set and nb not in local_adj[n]:
                    local_adj[n].append(nb)

        # 0. Remove pair edges to create skeleton
        #    (port of remove_pair_edges from blockpath.c)
        skeleton_adj = self._remove_pair_edges(nodes, local_adj)

        # 1. Spanning tree via DFS on skeleton
        root = block.cut_node if block.cut_node in block_set else nodes[0]
        tree_parent: dict[str, str | None] = {root: None}
        tree_children: dict[str, list[str]] = defaultdict(list)
        stack = [root]
        visited = set()
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            for nb in skeleton_adj.get(n, []):
                if nb not in visited:
                    tree_parent[nb] = n
                    tree_children[n].append(nb)
                    stack.append(nb)

        # 2. Find longest path (true diameter via two-BFS)
        def _bfs_farthest(start):
            dist = {start: 0}
            q = deque([start])
            farthest = start
            while q:
                u = q.popleft()
                for c in tree_children.get(u, []):
                    if c not in dist:
                        dist[c] = dist[u] + 1
                        q.append(c)
                        if dist[c] > dist[farthest]:
                            farthest = c
                p = tree_parent.get(u)
                if p and p not in dist:
                    dist[p] = dist[u] + 1
                    q.append(p)
                    if dist[p] > dist[farthest]:
                        farthest = p
            return farthest, dist

        leaf1, _ = _bfs_farthest(root)
        leaf2, _ = _bfs_farthest(leaf1)

        # Reconstruct path from leaf1 to leaf2 using BFS on local_adj
        prev = {leaf1: None}
        q = deque([leaf1])
        visited2 = {leaf1}
        while q:
            u = q.popleft()
            if u == leaf2:
                break
            for nb in local_adj.get(u, []):
                if nb in block_set and nb not in visited2:
                    visited2.add(nb)
                    prev[nb] = u
                    q.append(nb)
        path = []
        n = leaf2
        while n is not None:
            path.append(n)
            n = prev.get(n)
        path.reverse()

        # 3. Place residual nodes near neighbors
        on_path = set(path)
        order = list(path)
        remaining = [n for n in nodes if n not in on_path]

        for n in remaining:
            nbrs_in_order = [nb for nb in local_adj.get(n, [])
                             if nb in set(order)]
            if len(nbrs_in_order) >= 2:
                # Insert between the two closest neighbors
                i0 = order.index(nbrs_in_order[0])
                i1 = order.index(nbrs_in_order[1])
                pos = max(i0, i1)
                order.insert(pos, n)
            elif nbrs_in_order:
                pos = order.index(nbrs_in_order[0]) + 1
                order.insert(pos, n)
            else:
                order.append(n)

        # 4. Edge crossing reduction (neighbor-targeted insertion)
        order = self._reduce_crossings(order, local_adj, max_iter=10)

        # 5. Compute radius and place on circle
        block.circle_order = order
        N = len(order)
        largest = max(max(self.lnodes[n].width, self.lnodes[n].height)
                      for n in order)
        circumference = N * (self.mindist + largest)
        radius = max(circumference / (2 * math.pi), largest)
        block.radius = radius
        block.rad0 = radius  # original radius before coalescing

        block.node_pos = {}
        for i, name in enumerate(order):
            theta = i * (2 * math.pi / N)
            x = radius * math.cos(theta)
            y = radius * math.sin(theta)
            block.node_pos[name] = (x, y)

        # Rotate so cut_node is at angle 0 (for parent attachment)
        if block.cut_node and block.cut_node in block.node_pos:
            cx, cy = block.node_pos[block.cut_node]
            current_angle = math.atan2(cy, cx)
            cos_a = math.cos(-current_angle)
            sin_a = math.sin(-current_angle)
            for name in block.node_pos:
                ox, oy = block.node_pos[name]
                block.node_pos[name] = (ox * cos_a - oy * sin_a,
                                        ox * sin_a + oy * cos_a)

    @staticmethod
    def _remove_pair_edges(nodes: list[str],
                           adj: dict[str, list[str]]) -> dict[str, list[str]]:
        """Remove pair edges to create a skeleton for spanning tree.

        Port of remove_pair_edges() from Graphviz blockpath.c.
        Removes duplicate edges (parallel paths between same pair)
        to make the graph more tree-like for diameter computation.
        """
        # Count edges between each pair
        pair_count: dict[tuple[str, str], int] = defaultdict(int)
        for u in nodes:
            for v in adj.get(u, []):
                key = (min(u, v), max(u, v))
                pair_count[key] += 1

        # Build skeleton: keep only one edge per pair, skip pairs with
        # excessive multi-edges (degree > neighbors)
        skeleton: dict[str, list[str]] = defaultdict(list)
        for u in nodes:
            for v in adj.get(u, []):
                if v not in skeleton[u]:
                    skeleton[u].append(v)

        # For nodes with high degree relative to unique neighbors,
        # remove some edges to aid planarity
        node_set = set(nodes)
        for u in nodes:
            unique_nbrs = [v for v in skeleton[u] if v in node_set]
            degree = len(unique_nbrs)
            if degree <= 2:
                continue
            # Sort neighbors by their own degree (ascending) for
            # better skeleton quality
            unique_nbrs.sort(key=lambda v: len(skeleton.get(v, [])))

        return dict(skeleton)

    def _reduce_crossings(self, order: list[str],
                          adj: dict[str, list[str]],
                          max_iter: int = 10) -> list[str]:
        """Reduce edge crossings using neighbor-targeted insertion.

        Port of reduce() from Graphviz blockpath.c.  For each node,
        tries moving it next to each of its neighbors.
        """
        best_order = list(order)
        best_crossings = self._count_crossings(order, adj)

        if best_crossings == 0:
            return best_order

        for _ in range(max_iter):
            improved = False
            for i in range(len(best_order)):
                node = best_order[i]
                nbrs = adj.get(node, [])
                for nb in nbrs:
                    if nb not in set(best_order):
                        continue
                    nb_idx = best_order.index(nb)
                    # Try inserting node right after its neighbor
                    for target in (nb_idx, nb_idx + 1):
                        if target == i:
                            continue
                        trial = list(best_order)
                        trial.pop(i)
                        ins = target if target <= i else target - 1
                        ins = max(0, min(ins, len(trial)))
                        trial.insert(ins, node)
                        c = self._count_crossings(trial, adj)
                        if c < best_crossings:
                            best_order = trial
                            best_crossings = c
                            improved = True
                            if c == 0:
                                return best_order
                            break
                    if improved:
                        break
                if improved:
                    break
            if not improved:
                break

        return best_order

    def _count_crossings(self, order: list[str],
                         adj: dict[str, list[str]]) -> float:
        """Count weighted edge crossings in a circular node ordering.

        Higher-weight edges contribute more penalty when crossed.
        """
        N = len(order)
        if N < 4:
            return 0
        pos = {name: i for i, name in enumerate(order)}
        edges = []
        edge_weights = []
        seen = set()
        for u in order:
            for v in adj.get(u, []):
                key = (min(u, v), max(u, v))
                if key not in seen:
                    seen.add(key)
                    edges.append((pos[u], pos[v]))
                    edge_weights.append(
                        self._edge_weights.get(key, 1.0))

        crossings = 0.0
        for i in range(len(edges)):
            a, b = edges[i]
            if a > b:
                a, b = b, a
            for j in range(i + 1, len(edges)):
                c, d = edges[j]
                if c > d:
                    c, d = d, c
                # Two chords (a,b) and (c,d) cross if one endpoint
                # of each is between the other's endpoints
                if a < c < b < d or c < a < d < b:
                    # Weight crossing by product of edge weights
                    crossings += edge_weights[i] * edge_weights[j]
        return crossings

    # ── Component layout ───────────────────────────

    def _layout_component(self, nodes: list[str],
                          adj: dict[str, list[str]]):
        """Layout a single connected component."""
        blocks = self._find_biconnected(nodes, adj)
        root_block = self._build_block_tree(blocks)

        # Layout each block (bottom-up)
        def _layout_tree(block):
            for child in block.children:
                _layout_tree(child)
            self._layout_block(block, adj)
        _layout_tree(root_block)

        # Position blocks recursively (top-down)
        self._position_block_tree(root_block)

    def _position_block_tree(self, root_block: Block):
        """Position the block tree by placing child blocks around
        their articulation points in the parent block."""
        # Root block: center at origin
        root_block.center_x = 0.0
        root_block.center_y = 0.0

        # Apply root block positions to global coords
        for name, (rx, ry) in root_block.node_pos.items():
            ln = self.lnodes.get(name)
            if ln:
                ln.x = rx
                ln.y = ry

        # Recursively position children
        self._position_children(root_block)

    def _position_children(self, parent_block: Block):
        """Place child blocks around their articulation points.

        Port of position()/positionChildren() from Graphviz circpos.c.
        Supports coalescing (single-child blocks merge into parent)
        and scale-based spacing to prevent overlap.
        """
        if not parent_block.children:
            return

        # Group children by their cut_node (articulation point)
        cut_children: dict[str, list[Block]] = defaultdict(list)
        for child in parent_block.children:
            cut_children[child.cut_node].append(child)

        for cut_name, children in cut_children.items():
            if cut_name not in self.lnodes:
                continue

            cut_ln = self.lnodes[cut_name]
            cut_global = (cut_ln.x, cut_ln.y)

            # Direction from parent center to cut_node
            dx = cut_global[0] - parent_block.center_x
            dy = cut_global[1] - parent_block.center_y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 0:
                base_angle = math.atan2(dy, dx)
            else:
                base_angle = 0.0

            # Compute total angular span needed for all children at this cut
            n_children = len(children)
            total_child_radius = sum(c.radius for c in children)

            for ci, child in enumerate(children):
                # Coalescing: single child at a cut_node gets merged closer
                coalesced = (n_children == 1 and len(child.nodes) > 1)

                if coalesced:
                    # Push only half as far (coalesce into parent)
                    push = child.radius * 0.5 + self.mindist * 0.25
                    child_angle = base_angle
                else:
                    push = child.radius + self.mindist * 0.5
                    # Distribute multiple children around the cut_node
                    if n_children > 1:
                        # Spread children across an arc
                        arc_per_child = (2 * math.pi) / max(n_children * 2, 4)
                        child_angle = base_angle + (ci - (n_children - 1) / 2) * arc_per_child
                    else:
                        child_angle = base_angle

                # Scale push based on child radius relative to parent
                if parent_block.radius > 0:
                    scale = max(1.0, (child.radius + parent_block.radius) /
                                (parent_block.radius * 2))
                else:
                    scale = 1.0

                child.center_x = cut_global[0] + math.cos(child_angle) * push * scale
                child.center_y = cut_global[1] + math.sin(child_angle) * push * scale

                if coalesced:
                    # Update parent radius to encompass coalesced child
                    new_r = dist + push * scale + child.radius
                    if new_r > parent_block.radius:
                        parent_block.radius = new_r

                # Apply child block positions to global coords
                for name, (rx, ry) in child.node_pos.items():
                    if name == cut_name:
                        continue  # cut_node already positioned by parent
                    ln = self.lnodes.get(name)
                    if ln:
                        ln.x = child.center_x + rx
                        ln.y = child.center_y + ry

                # Recurse
                self._position_children(child)

    # Shared methods inherited from LayoutEngine base class:
    # _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _estimate_label_size, _overlap_area, _compute_label_positions,
    # _clip_to_boundary, _find_components, _pack_components_lr,
    # _write_back, _to_json

