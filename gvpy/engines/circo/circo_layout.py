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


class CircoLayout:
    """Circular layout engine.

    Usage::

        from gvpycode.circo import CircoLayout
        result = CircoLayout(graph).layout()
    """

    def __init__(self, graph: Graph):
        self.graph = graph
        self.lnodes: dict[str, LayoutNode] = {}
        self.mindist = 1.0 * 72.0  # inches → points
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
            comp_adj = {n: [nb for nb in adj[n] if nb in comp_nodes]
                        for n in comp_nodes}
            self._layout_component(comp_nodes, comp_adj)
            component_results.append(set(comp_nodes))

        # Pack components if multiple
        if len(component_results) > 1:
            self._pack_components(component_results)

        # Write back positions
        self._write_back()

        return self._to_json()

    # ── Initialization ─────────────────────────────

    def _init_from_graph(self):
        """Read graph attributes and create layout nodes."""
        md = self.graph.get_graph_attr("mindist")
        if md:
            try:
                self.mindist = float(md) * 72.0
            except ValueError:
                pass

        self.root_name = self.graph.get_graph_attr("root") or ""
        ob = self.graph.get_graph_attr("oneblock") or ""
        self.oneblock = ob.lower() in ("true", "1", "yes")

        for name, node in self.graph.nodes.items():
            w, h = 54.0, 36.0
            try:
                w_str = node.attributes.get("width")
                if w_str:
                    w = float(w_str) * 72.0
            except ValueError:
                pass
            try:
                h_str = node.attributes.get("height")
                if h_str:
                    h = float(h_str) * 72.0
            except ValueError:
                pass
            self.lnodes[name] = LayoutNode(name=name, node=node,
                                           width=w, height=h)

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

    def _find_components(self, adj) -> list[list[str]]:
        """Find connected components using BFS."""
        visited = set()
        components = []
        for node in adj:
            if node in visited:
                continue
            comp = []
            queue = deque([node])
            while queue:
                n = queue.popleft()
                if n in visited:
                    continue
                visited.add(n)
                comp.append(n)
                for nb in adj.get(n, []):
                    if nb not in visited:
                        queue.append(nb)
            components.append(comp)
        return components

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

        Steps:
          1. Find spanning tree
          2. Find longest path (diameter)
          3. Place remaining nodes by neighbor proximity
          4. Reduce edge crossings
          5. Compute radius and place on circle
        """
        nodes = block.nodes
        if not nodes:
            return

        if len(nodes) == 1:
            block.circle_order = list(nodes)
            block.radius = 0
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

        # 1. Spanning tree via DFS
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
            for nb in local_adj.get(n, []):
                if nb not in visited:
                    tree_parent[nb] = n
                    tree_children[n].append(nb)
                    stack.append(nb)

        # 2. Find longest path (tree diameter)
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
        leaf2, dist_from_leaf1 = _bfs_farthest(leaf1)

        # Reconstruct path from leaf1 to leaf2
        path = []
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
        # Build path
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
            # Find neighbors already in order
            nbrs_in_order = [nb for nb in local_adj.get(n, []) if nb in set(order)]
            if len(nbrs_in_order) >= 2:
                # Insert between first two neighbors
                i0 = order.index(nbrs_in_order[0])
                i1 = order.index(nbrs_in_order[1])
                pos = max(i0, i1)
                order.insert(pos, n)
            elif nbrs_in_order:
                # Insert after the neighbor
                pos = order.index(nbrs_in_order[0]) + 1
                order.insert(pos, n)
            else:
                order.append(n)

        # 4. Edge crossing reduction (iterative improvement)
        order = self._reduce_crossings(order, local_adj, max_iter=10)

        # 5. Compute radius and place on circle
        block.circle_order = order
        N = len(order)
        largest = max(max(self.lnodes[n].width, self.lnodes[n].height)
                      for n in order)
        circumference = N * (self.mindist + largest)
        radius = max(circumference / (2 * math.pi), largest)
        block.radius = radius

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
            for name in block.node_pos:
                ox, oy = block.node_pos[name]
                nx = ox * math.cos(-current_angle) - oy * math.sin(-current_angle)
                ny = ox * math.sin(-current_angle) + oy * math.cos(-current_angle)
                block.node_pos[name] = (nx, ny)

    def _reduce_crossings(self, order: list[str],
                          adj: dict[str, list[str]],
                          max_iter: int = 10) -> list[str]:
        """Reduce edge crossings in circular ordering by local swaps."""
        best_order = list(order)
        best_crossings = self._count_crossings(order, adj)

        if best_crossings == 0:
            return best_order

        for _ in range(max_iter):
            improved = False
            for i in range(len(order)):
                for j in range(i + 1, len(order)):
                    # Try swapping i and j
                    trial = list(best_order)
                    trial[i], trial[j] = trial[j], trial[i]
                    c = self._count_crossings(trial, adj)
                    if c < best_crossings:
                        best_order = trial
                        best_crossings = c
                        improved = True
                        if c == 0:
                            return best_order
            if not improved:
                break

        return best_order

    @staticmethod
    def _count_crossings(order: list[str],
                         adj: dict[str, list[str]]) -> int:
        """Count edge crossings in a circular node ordering."""
        N = len(order)
        if N < 4:
            return 0
        pos = {name: i for i, name in enumerate(order)}
        edges = []
        seen = set()
        for u in order:
            for v in adj.get(u, []):
                key = (min(u, v), max(u, v))
                if key not in seen:
                    seen.add(key)
                    edges.append((pos[u], pos[v]))

        crossings = 0
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
                    crossings += 1
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
        """Place child blocks around their articulation points."""
        if not parent_block.children:
            return

        for child in parent_block.children:
            cut = child.cut_node
            if cut not in self.lnodes:
                continue

            # Position child block so cut_node aligns
            cut_ln = self.lnodes[cut]
            cut_global = (cut_ln.x, cut_ln.y)

            # Get cut_node's position in child block coords
            cut_in_child = child.node_pos.get(cut, (0.0, 0.0))

            # Offset: place child so cut_node overlaps parent's cut_node
            # But push outward by child radius to avoid overlap
            if parent_block.radius > 0 and child.radius > 0:
                # Direction from parent center to cut_node
                dx = cut_global[0] - parent_block.center_x
                dy = cut_global[1] - parent_block.center_y
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > 0:
                    ux, uy = dx / dist, dy / dist
                else:
                    ux, uy = 1.0, 0.0

                # Push child center outward
                push = child.radius + self.mindist * 0.5
                child.center_x = cut_global[0] + ux * push
                child.center_y = cut_global[1] + uy * push
            else:
                child.center_x = cut_global[0] - cut_in_child[0]
                child.center_y = cut_global[1] - cut_in_child[1]

            # Apply child block positions to global coords
            for name, (rx, ry) in child.node_pos.items():
                if name == cut:
                    continue  # cut_node already positioned by parent
                ln = self.lnodes.get(name)
                if ln:
                    ln.x = child.center_x + rx
                    ln.y = child.center_y + ry

            # Recurse
            self._position_children(child)

    # ── Component packing ──────────────────────────

    def _pack_components(self, components: list[set[str]]):
        """Pack multiple components left to right."""
        gap = self.mindist
        x_offset = 0.0

        for comp in components:
            if not comp:
                continue
            comp_lns = [self.lnodes[n] for n in comp if n in self.lnodes]
            if not comp_lns:
                continue
            min_x = min(ln.x - ln.width / 2 for ln in comp_lns)
            max_x = max(ln.x + ln.width / 2 for ln in comp_lns)
            comp_w = max_x - min_x

            # Shift component so left edge is at x_offset
            dx = x_offset - min_x
            for ln in comp_lns:
                ln.x += dx

            x_offset += comp_w + gap

    # ── Write-back and output ──────────────────────

    def _write_back(self):
        """Write layout positions back to graph node attributes."""
        for name, ln in self.lnodes.items():
            if ln.node:
                ln.node.agset("pos", f"{round(ln.x, 2)},{round(ln.y, 2)}")
                ln.node.agset("width", str(round(ln.width / 72.0, 4)))
                ln.node.agset("height", str(round(ln.height / 72.0, 4)))

    def _to_json(self) -> dict:
        """Convert layout results to JSON-serializable dict."""
        nodes_json = []
        for name, ln in self.lnodes.items():
            entry: dict = {
                "name": name,
                "x": round(ln.x, 2),
                "y": round(ln.y, 2),
                "width": round(ln.width, 2),
                "height": round(ln.height, 2),
            }
            if ln.node:
                for attr in ("shape", "label", "color", "fillcolor", "fontcolor",
                             "fontname", "fontsize", "style", "penwidth",
                             "xlabel", "_xlabel_pos_x", "_xlabel_pos_y",
                             "tooltip", "URL"):
                    val = ln.node.attributes.get(attr)
                    if val:
                        entry[attr] = val
            nodes_json.append(entry)

        edges_json = []
        for key, edge in self.graph.edges.items():
            t_name = edge.tail.name
            h_name = edge.head.name
            t_ln = self.lnodes.get(t_name)
            h_ln = self.lnodes.get(h_name)
            if not t_ln or not h_ln:
                continue

            # Straight-line edge routing
            points = [
                [round(t_ln.x, 2), round(t_ln.y, 2)],
                [round(h_ln.x, 2), round(h_ln.y, 2)],
            ]
            entry: dict = {
                "tail": t_name,
                "head": h_name,
                "points": points,
            }
            for attr in ("label", "color", "style", "penwidth",
                         "arrowhead", "arrowtail", "dir"):
                val = edge.attributes.get(attr)
                if val:
                    entry[attr] = val
            # Compute label position at midpoint
            if entry.get("label"):
                entry["label_pos"] = [
                    round((points[0][0] + points[1][0]) / 2, 2),
                    round((points[0][1] + points[1][1]) / 2, 2),
                ]
            edges_json.append(entry)

        # Bounding box
        if nodes_json:
            min_x = min(n["x"] - n["width"] / 2 for n in nodes_json)
            min_y = min(n["y"] - n["height"] / 2 for n in nodes_json)
            max_x = max(n["x"] + n["width"] / 2 for n in nodes_json)
            max_y = max(n["y"] + n["height"] / 2 for n in nodes_json)
        else:
            min_x = min_y = max_x = max_y = 0

        graph_meta: dict = {
            "name": self.graph.name,
            "directed": self.graph.directed,
            "bb": [round(min_x, 2), round(min_y, 2),
                   round(max_x, 2), round(max_y, 2)],
        }
        for attr in ("bgcolor", "label", "fontname", "fontsize", "fontcolor"):
            val = self.graph.get_graph_attr(attr)
            if val:
                graph_meta[attr] = val

        result: dict = {
            "graph": graph_meta,
            "nodes": nodes_json,
            "edges": edges_json,
        }
        return result
