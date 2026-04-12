"""
Neato layout engine — spring-model force-directed layout.

Port of Graphviz ``lib/neatogen/``.  Positions nodes by minimizing a
stress energy function derived from graph-theoretic distances.

Algorithm modes
---------------
- **majorization** (default) — Stress majorization via iterative
  Laplacian solving with conjugate gradient.
- **KK** — Kamada-Kawai gradient descent: move one node at a time
  toward equilibrium.
- **sgd** — Stochastic gradient descent with exponential learning
  rate annealing.

Distance models
---------------
- **shortpath** (default) — Shortest-path distances (BFS unweighted,
  Dijkstra weighted).
- **circuit** — Effective resistance in a resistor network (requires
  matrix inversion).
- **subset** — Reweight edges by shared-neighbor count, then shortest
  path.

Command-line usage
------------------
::

    python gvcli.py -Kneato input.gv -Tsvg -o output.svg
    python gvcli.py -Kneato input.gv -Gmode=KK -Tsvg
    python gvcli.py -Kneato input.gv -Gmodel=circuit -Tsvg
    python gvcli.py -Kneato input.gv -Goverlap=false -Tsvg

API usage
---------
::

    from gvpy.grammar import read_gv
    from gvpy.engines.layout.neato import NeatoLayout
    from gvpy.render import render_svg

    graph = read_gv('graph G { a -- b -- c -- a; }')
    result = NeatoLayout(graph).layout()
    svg = render_svg(result)

Attributes
----------

**Graph:**
  mode, model, maxiter, epsilon, start, Damping, K, defaultdist,
  dim, overlap, sep, normalize, pack, splines, pad, dpi, size,
  ratio, rotate, landscape, center, label, labelloc, labeljust,
  bgcolor, fontname, fontsize, fontcolor, outputorder, forcelabels

**Node:**
  pos, pin, width, height, fixedsize, shape, label, xlabel,
  fontname, fontsize, fontcolor, color, fillcolor, style, penwidth

**Edge:**
  len, weight, label, headlabel, taillabel, color, fontcolor,
  fontname, fontsize, style, penwidth, arrowhead, arrowtail,
  arrowsize, dir
"""
from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine


# ── Constants ────────────────────────────────────

_DFLT_TOLERANCE = 1e-4
_DFLT_DAMPING = 0.99
_DFLT_MAXITER_MAJOR = 200
_DFLT_MAXITER_KK = None       # set to 100*N at runtime
_DFLT_MAXITER_SGD = 30
_CG_TOLERANCE = 1e-3
_CG_MAXITER = 500


# ── Data structures ─────────────────────────────

@dataclass
class LayoutNode:
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False         # True = position fixed
    pos_set: bool = False        # True = user specified pos


# ── Main layout class ───────────────────────────


class NeatoLayout(LayoutEngine):
    """Neato spring-model layout engine.

    Usage::

        from gvpy.engines.layout.neato import NeatoLayout
        result = NeatoLayout(graph).layout()
    """

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.node_list: list[str] = []       # ordered node names
        self.node_idx: dict[str, int] = {}   # name → index

        # Neato-specific parameters
        self.mode = "majorization"           # kk, majorization, sgd
        self.model = "shortpath"             # shortpath, circuit, subset
        self.dim = 2
        self.maxiter = _DFLT_MAXITER_MAJOR
        self.epsilon = _DFLT_TOLERANCE
        self.damping = _DFLT_DAMPING
        self.default_dist = 0.0              # auto-computed
        self.seed = 1
        self.overlap = "true"
        self.sep = 0.0
        self.pack = True

    # ── Public API ───────────────────────────────

    def layout(self) -> dict:
        """Run the neato layout pipeline."""
        self._init_from_graph()
        N = len(self.node_list)
        if N == 0:
            return self._to_json()

        # Build adjacency and edge lengths
        adj, edge_len = self._build_adjacency()

        # Find connected components
        components = self._find_components(adj)

        if len(components) > 1 and self.pack:
            self._layout_and_pack(components, adj, edge_len)
        else:
            self._layout_component(set(self.node_list), adj, edge_len)

        # Overlap removal
        if self.overlap != "true":
            self._remove_overlap()

        # Post-processing
        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        # Label placement
        self._compute_label_positions()

        # Write-back
        self._write_back()

        return self._to_json()

    # ── Initialization ───────────────────────────

    def _init_from_graph(self):
        """Read all graph attributes and initialize layout nodes."""
        # Mode and model
        mode_str = (self.graph.get_graph_attr("mode") or "").lower()
        if mode_str in ("kk", "kamada-kawai", "kamadakawai"):
            self.mode = "kk"
        elif mode_str in ("sgd",):
            self.mode = "sgd"
        elif mode_str in ("major", "majorization"):
            self.mode = "majorization"

        model_str = (self.graph.get_graph_attr("model") or "").lower()
        if model_str in ("circuit",):
            self.model = "circuit"
        elif model_str in ("subset",):
            self.model = "subset"
        elif model_str in ("mds",):
            self.model = "mds"

        # Dimension
        dim_str = self.graph.get_graph_attr("dim") or \
                  self.graph.get_graph_attr("dimen")
        if dim_str:
            try:
                self.dim = max(2, int(dim_str))
            except ValueError:
                pass

        # Iteration limits
        maxiter_str = self.graph.get_graph_attr("maxiter")
        if maxiter_str:
            try:
                self.maxiter = int(maxiter_str)
            except ValueError:
                pass

        eps_str = self.graph.get_graph_attr("epsilon")
        if eps_str:
            try:
                self.epsilon = float(eps_str)
            except ValueError:
                pass

        damp_str = self.graph.get_graph_attr("Damping")
        if damp_str:
            try:
                self.damping = float(damp_str)
            except ValueError:
                pass

        # Start / seed
        start_str = self.graph.get_graph_attr("start") or ""
        if start_str.isdigit():
            self.seed = int(start_str)
        elif start_str == "self":
            self.seed = 0  # use existing positions
        elif start_str == "random":
            import time
            self.seed = int(time.time())
        random.seed(self.seed)

        # Overlap
        ov_str = (self.graph.get_graph_attr("overlap") or "true").lower()
        self.overlap = ov_str

        sep_str = self.graph.get_graph_attr("sep")
        if sep_str:
            try:
                self.sep = float(sep_str)
            except ValueError:
                pass

        # Common attributes (pad, dpi, rotate, size, ratio, etc.)
        self._init_common_attrs()

        # Neato-specific overrides
        self.normalize = (self.graph.get_graph_attr("normalize") or "true").lower() \
                         not in ("false", "0", "no")
        self.pack = (self.graph.get_graph_attr("pack") or "true").lower() \
                    not in ("false", "0", "no")

        # Create layout nodes
        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)

            # Read pos attribute
            pos_str = (node.attributes.get("pos") or "").strip()
            if pos_str:
                try:
                    parts = pos_str.replace("!", "").split(",")
                    ln.x = float(parts[0]) * 72.0
                    ln.y = float(parts[1]) * 72.0
                    ln.pos_set = True
                    ln.pinned = "!" in pos_str or \
                                node.attributes.get("pin", "").lower() in \
                                ("true", "1", "yes")
                except (ValueError, IndexError):
                    pass
            elif node.attributes.get("pin", "").lower() in ("true", "1", "yes"):
                ln.pinned = True

            self.lnodes[name] = ln

        self.node_list = list(self.lnodes.keys())
        self.node_idx = {n: i for i, n in enumerate(self.node_list)}

        # Set mode-specific defaults
        N = len(self.node_list)
        if self.mode == "kk" and not maxiter_str:
            self.maxiter = 100 * N
        elif self.mode == "sgd" and not maxiter_str:
            self.maxiter = _DFLT_MAXITER_SGD
        if self.mode == "kk" and not eps_str:
            self.epsilon = 0.0001 * N
        elif self.mode == "sgd" and not eps_str:
            self.epsilon = 0.01

    # _compute_node_size inherited from LayoutEngine
    # ── Adjacency and distance ───────────────────

    def _build_adjacency(self):
        """Build undirected adjacency and edge length maps."""
        adj: dict[str, list[str]] = defaultdict(list)
        edge_len: dict[tuple[str, str], float] = {}

        for name in self.node_list:
            adj[name]  # ensure present

        for key, edge in self.graph.edges.items():
            t, h = edge.tail.name, edge.head.name
            if t not in self.node_idx or h not in self.node_idx:
                continue

            # Edge length from "len" attribute (default 1.0)
            try:
                length = float(edge.attributes.get("len", "1.0"))
            except ValueError:
                length = 1.0

            if h not in adj[t]:
                adj[t].append(h)
            if t not in adj[h]:
                adj[h].append(t)

            pair = (min(t, h), max(t, h))
            edge_len[pair] = length

        # Compute default distance for disconnected pairs
        total_len = sum(edge_len.values())
        n_edges = max(len(edge_len), 1)
        N = len(self.node_list)
        self.default_dist = (total_len / n_edges) * math.sqrt(N) + 1

        dd_str = self.graph.get_graph_attr("defaultdist")
        if dd_str:
            try:
                self.default_dist = float(dd_str) * 72.0
            except ValueError:
                pass

        return dict(adj), edge_len

    def _compute_distances(self, nodes: set[str], adj: dict[str, list[str]],
                           edge_len: dict[tuple[str, str], float]) -> list[list[float]]:
        """Compute all-pairs shortest-path distances.

        Uses BFS for unweighted graphs, Dijkstra for weighted.
        Returns NxN distance matrix indexed by node order in self.node_list.
        """
        node_list = [n for n in self.node_list if n in nodes]
        N = len(node_list)
        idx = {n: i for i, n in enumerate(node_list)}

        # Check if weighted
        has_weights = any(v != 1.0 for v in edge_len.values())

        dist = [[self.default_dist] * N for _ in range(N)]
        for i in range(N):
            dist[i][i] = 0.0

        for si, source in enumerate(node_list):
            if has_weights:
                self._dijkstra(source, node_list, adj, edge_len, dist[si], idx)
            else:
                self._bfs_dist(source, node_list, adj, dist[si], idx)

        return dist

    def _bfs_dist(self, source, node_list, adj, dist_row, idx):
        """BFS shortest path from source (unweighted)."""
        visited = {source}
        queue = deque([(source, 0)])
        while queue:
            u, d = queue.popleft()
            ui = idx.get(u)
            if ui is not None:
                dist_row[ui] = d * 72.0  # convert to points
            for v in adj.get(u, []):
                if v not in visited and v in idx:
                    visited.add(v)
                    queue.append((v, d + 1))

    def _dijkstra(self, source, node_list, adj, edge_len, dist_row, idx):
        """Dijkstra shortest path from source (weighted)."""
        import heapq
        INF = float("inf")
        dist_map = {n: INF for n in node_list}
        dist_map[source] = 0.0
        heap = [(0.0, source)]
        visited = set()

        while heap:
            d, u = heapq.heappop(heap)
            if u in visited:
                continue
            visited.add(u)
            for v in adj.get(u, []):
                if v not in idx:
                    continue
                pair = (min(u, v), max(u, v))
                w = edge_len.get(pair, 1.0) * 72.0
                nd = d + w
                if nd < dist_map.get(v, INF):
                    dist_map[v] = nd
                    heapq.heappush(heap, (nd, v))

        for n, i in idx.items():
            d = dist_map.get(n, self.default_dist)
            dist_row[i] = d if d < INF else self.default_dist

    def _compute_circuit_distances(self, nodes, adj, edge_len):
        """Circuit resistance model: effective resistance distances."""
        node_list = [n for n in self.node_list if n in nodes]
        N = len(node_list)
        idx = {n: i for i, n in enumerate(node_list)}

        # Build conductance matrix
        G = [[0.0] * N for _ in range(N)]
        for pair, length in edge_len.items():
            u, v = pair
            if u not in idx or v not in idx:
                continue
            i, j = idx[u], idx[v]
            conductance = 1.0 / max(length, 0.001)
            G[i][j] -= conductance
            G[j][i] -= conductance
            G[i][i] += conductance
            G[j][j] += conductance

        # Invert via pseudoinverse (ground last node)
        # Remove last row/col, invert, pad back
        if N <= 1:
            return [[0.0]]

        M = N - 1
        Gr = [[G[i][j] for j in range(M)] for i in range(M)]

        # Simple Gauss-Jordan inversion for small matrices
        Gi = self._matrix_inverse(Gr)
        if Gi is None:
            # Fallback to shortest path
            return self._compute_distances(nodes, adj, edge_len)

        # Compute effective resistance distances
        dist = [[0.0] * N for _ in range(N)]
        for i in range(N):
            for j in range(i + 1, N):
                ii = min(i, M - 1)
                jj = min(j, M - 1)
                if i < M and j < M:
                    r = abs(Gi[ii][ii] + Gi[jj][jj] - 2 * Gi[ii][jj])
                elif i < M:
                    r = abs(Gi[ii][ii])
                elif j < M:
                    r = abs(Gi[jj][jj])
                else:
                    r = 0.0
                d = math.sqrt(max(r, 0.0)) * 72.0
                dist[i][j] = d
                dist[j][i] = d

        return dist

    @staticmethod
    def _matrix_inverse(M):
        """Gauss-Jordan matrix inverse for small matrices."""
        n = len(M)
        # Augment with identity
        aug = [row[:] + [1.0 if j == i else 0.0 for j in range(n)]
               for i, row in enumerate(M)]

        for col in range(n):
            # Find pivot
            max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
            if abs(aug[max_row][col]) < 1e-12:
                return None  # singular
            aug[col], aug[max_row] = aug[max_row], aug[col]

            pivot = aug[col][col]
            aug[col] = [v / pivot for v in aug[col]]

            for row in range(n):
                if row == col:
                    continue
                factor = aug[row][col]
                aug[row] = [aug[row][j] - factor * aug[col][j]
                            for j in range(2 * n)]

        return [row[n:] for row in aug]

    # ── Layout modes ─────────────────────────────

    def _layout_component(self, nodes: set[str], adj, edge_len):
        """Layout a single connected component."""
        node_list = [n for n in self.node_list if n in nodes]
        N = len(node_list)
        if N == 0:
            return
        if N == 1:
            ln = self.lnodes[node_list[0]]
            if not ln.pos_set:
                ln.x, ln.y = 0.0, 0.0
            return

        idx = {n: i for i, n in enumerate(node_list)}

        # Compute distance matrix based on model
        if self.model == "circuit":
            dist = self._compute_circuit_distances(nodes, adj, edge_len)
        else:
            dist = self._compute_distances(nodes, adj, edge_len)

        # Initialize positions
        self._initialize_positions(node_list, N)

        # Run layout algorithm
        if self.mode == "kk":
            self._kamada_kawai(node_list, dist, N, idx)
        elif self.mode == "sgd":
            self._sgd(node_list, dist, N, idx, edge_len)
        else:
            self._stress_majorization(node_list, dist, N, idx)

    def _initialize_positions(self, node_list, N):
        """Set initial node positions."""
        for i, name in enumerate(node_list):
            ln = self.lnodes[name]
            if ln.pos_set:
                continue
            # Random initial positions in [0, sqrt(N)*72)
            span = math.sqrt(N) * 72.0
            ln.x = random.random() * span
            ln.y = random.random() * span

    # ── Stress majorization (MODE_MAJOR) ─────────

    def _stress_majorization(self, node_list, dist, N, idx):
        """Stress majorization via weighted Laplacian solving.

        Port of stress_majorization_kD_mkernel from stress.c.
        Uses the SMACOF (Scaling by MAjorizing a COmplicated Function)
        algorithm: iteratively solve L_w * X = L_Z(X) * X.
        """
        # Build weight matrix: w[i][j] = 1/d[i][j]^2
        w = [[0.0] * N for _ in range(N)]
        for i in range(N):
            for j in range(N):
                if i != j and dist[i][j] > 0:
                    w[i][j] = 1.0 / (dist[i][j] * dist[i][j])

        # Build weighted Laplacian diagonal: Lw_diag[i] = sum_j w[i][j]
        Lw_diag = [0.0] * N
        for i in range(N):
            for j in range(N):
                if i != j:
                    Lw_diag[i] += w[i][j]

        # Extract coords
        cx = [self.lnodes[node_list[i]].x for i in range(N)]
        cy = [self.lnodes[node_list[i]].y for i in range(N)]
        pinned = [self.lnodes[node_list[i]].pinned for i in range(N)]

        old_stress = self._compute_stress(cx, cy, dist, w, N)

        for iteration in range(self.maxiter):
            # Compute new positions via SMACOF update:
            # x_new[i] = (1/Lw_diag[i]) * sum_{j!=i} w[i][j] * (x[j] + d[i][j] * (x[i]-x[j])/||x[i]-x[j]||)
            new_cx = [0.0] * N
            new_cy = [0.0] * N

            for i in range(N):
                if pinned[i]:
                    new_cx[i] = cx[i]
                    new_cy[i] = cy[i]
                    continue
                if Lw_diag[i] < 1e-10:
                    new_cx[i] = cx[i]
                    new_cy[i] = cy[i]
                    continue

                sx, sy = 0.0, 0.0
                for j in range(N):
                    if i == j or w[i][j] == 0:
                        continue
                    dx = cx[i] - cx[j]
                    dy = cy[i] - cy[j]
                    eucl = math.sqrt(dx * dx + dy * dy)
                    if eucl < 1e-10:
                        # Add small random perturbation
                        cx[i] += random.random() * 0.1
                        cy[i] += random.random() * 0.1
                        eucl = 0.1

                    # SMACOF: x_new[i] += w[i][j] * (x[j] + d[i][j] * (x[i]-x[j]) / eucl)
                    ratio = dist[i][j] / eucl
                    sx += w[i][j] * (cx[j] + ratio * dx)
                    sy += w[i][j] * (cy[j] + ratio * dy)

                new_cx[i] = sx / Lw_diag[i]
                new_cy[i] = sy / Lw_diag[i]

            cx = new_cx
            cy = new_cy

            new_stress = self._compute_stress(cx, cy, dist, w, N)

            if old_stress > 0 and \
               abs(new_stress - old_stress) < self.epsilon * old_stress:
                break
            old_stress = new_stress

        # Write back
        for i, name in enumerate(node_list):
            self.lnodes[name].x = cx[i]
            self.lnodes[name].y = cy[i]

    @staticmethod
    def _compute_stress(cx, cy, dist, w, N):
        """Compute stress: sum w[i][j] * (d[i][j] - eucl_dist)^2."""
        stress = 0.0
        for i in range(N):
            for j in range(i + 1, N):
                dx = cx[i] - cx[j]
                dy = cy[i] - cy[j]
                eucl = math.sqrt(dx * dx + dy * dy)
                diff = dist[i][j] - eucl
                stress += w[i][j] * diff * diff
        return stress

    # ── Kamada-Kawai (MODE_KK) ───────────────────

    def _kamada_kawai(self, node_list, dist, N, idx):
        """Kamada-Kawai gradient descent layout.

        Port of kkNeato/solve_model from kkutils.c.
        """
        # Spring constants: k[i][j] = 1 / d[i][j]^2
        k = [[0.0] * N for _ in range(N)]
        for i in range(N):
            for j in range(N):
                if i != j and dist[i][j] > 0:
                    k[i][j] = 1.0 / (dist[i][j] * dist[i][j])

        cx = [self.lnodes[node_list[i]].x for i in range(N)]
        cy = [self.lnodes[node_list[i]].y for i in range(N)]
        pinned = [self.lnodes[node_list[i]].pinned for i in range(N)]

        for iteration in range(self.maxiter):
            # Find node with maximum force
            max_force = 0.0
            max_node = -1

            for i in range(N):
                if pinned[i]:
                    continue
                fx, fy = 0.0, 0.0
                for j in range(N):
                    if i == j:
                        continue
                    dx = cx[i] - cx[j]
                    dy = cy[i] - cy[j]
                    eucl = math.sqrt(dx * dx + dy * dy)
                    if eucl < 1e-10:
                        eucl = 1e-10
                    force = k[i][j] * (eucl - dist[i][j]) / eucl
                    fx += force * dx
                    fy += force * dy

                force_mag = math.sqrt(fx * fx + fy * fy)
                if force_mag > max_force:
                    max_force = force_mag
                    max_node = i

            if max_force < self.epsilon or max_node < 0:
                break

            # Move the node with maximum force
            i = max_node
            # Newton step: solve for equilibrium position
            fx, fy = 0.0, 0.0
            fxx, fxy, fyy = 0.0, 0.0, 0.0

            for j in range(N):
                if i == j:
                    continue
                dx = cx[i] - cx[j]
                dy = cy[i] - cy[j]
                eucl = math.sqrt(dx * dx + dy * dy)
                if eucl < 1e-10:
                    eucl = 1e-10
                eucl3 = eucl * eucl * eucl

                kij = k[i][j]
                dij = dist[i][j]

                fx += kij * (dx - dij * dx / eucl)
                fy += kij * (dy - dij * dy / eucl)
                fxx += kij * (1.0 - dij * dy * dy / eucl3)
                fxy += kij * (dij * dx * dy / eucl3)
                fyy += kij * (1.0 - dij * dx * dx / eucl3)

            # Solve 2x2 system: [fxx fxy; fxy fyy] * [dx; dy] = [-fx; -fy]
            det = fxx * fyy - fxy * fxy
            if abs(det) < 1e-10:
                continue

            move_x = (-fx * fyy + fy * fxy) / det
            move_y = (fx * fxy - fy * fxx) / det

            cx[i] += move_x * self.damping
            cy[i] += move_y * self.damping

        for i, name in enumerate(node_list):
            self.lnodes[name].x = cx[i]
            self.lnodes[name].y = cy[i]

    # ── SGD mode ─────────────────────────────────

    def _sgd(self, node_list, dist, N, idx, edge_len):
        """Stochastic gradient descent layout.

        Port of sgd() from sgd.c.
        """
        # Build stress terms
        terms = []
        for i in range(N):
            for j in range(i + 1, N):
                d = dist[i][j]
                if d <= 0:
                    continue
                w = 1.0 / (d * d)
                terms.append((i, j, d, w))

        if not terms:
            return

        cx = [self.lnodes[node_list[i]].x for i in range(N)]
        cy = [self.lnodes[node_list[i]].y for i in range(N)]
        pinned = [self.lnodes[node_list[i]].pinned for i in range(N)]

        # Compute learning rate schedule
        w_min = min(t[3] for t in terms)
        w_max = max(t[3] for t in terms)
        eta_max = 1.0 / max(w_min, 1e-10)
        eta_min = self.epsilon / max(w_max, 1e-10)
        if eta_max <= eta_min:
            eta_max = eta_min * 10

        lam = math.log(eta_max / max(eta_min, 1e-10)) / max(self.maxiter - 1, 1)

        for iteration in range(self.maxiter):
            eta = eta_max * math.exp(-lam * iteration)

            # Shuffle terms
            random.shuffle(terms)

            for i, j, d, w in terms:
                dx = cx[j] - cx[i]
                dy = cy[j] - cy[i]
                eucl = math.sqrt(dx * dx + dy * dy)
                if eucl < 1e-10:
                    eucl = 1e-10

                # Stress gradient step
                delta = (d - eucl) / eucl
                step = eta * w * delta * 0.5

                if not pinned[i]:
                    cx[i] -= step * dx
                    cy[i] -= step * dy
                if not pinned[j]:
                    cx[j] += step * dx
                    cy[j] += step * dy

        for i, name in enumerate(node_list):
            self.lnodes[name].x = cx[i]
            self.lnodes[name].y = cy[i]

    # ── Component handling ───────────────────────

    # _find_components inherited from LayoutEngine

    def _layout_and_pack(self, components, adj, edge_len):
        """Layout each component separately and pack left-to-right."""
        for comp in components:
            self._layout_component(comp, adj, edge_len)
        gap = max(self.default_dist * 0.5, 36.0)
        self._pack_components_lr(components, gap=gap)

    # ── Overlap removal ──────────────────────────

    def _remove_overlap(self):
        """Remove node overlaps by scaling positions outward."""
        if self.overlap in ("false", "0", "no"):
            return
        nodes = list(self.lnodes.values())
        if len(nodes) < 2:
            return

        max_iter = 50
        for _ in range(max_iter):
            has_overlap = False
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    a, b = nodes[i], nodes[j]
                    dx = b.x - a.x
                    dy = b.y - a.y
                    dist = math.sqrt(dx * dx + dy * dy)
                    min_dist = (a.width + b.width) / 2 + \
                               (a.height + b.height) / 2 + self.sep
                    min_dist *= 0.5

                    if dist < min_dist and dist > 0:
                        has_overlap = True
                        push = (min_dist - dist) / 2 + 1
                        ux, uy = dx / dist, dy / dist
                        if not a.pinned:
                            a.x -= ux * push
                            a.y -= uy * push
                        if not b.pinned:
                            b.x += ux * push
                            b.y += uy * push
            if not has_overlap:
                break

    # Shared methods inherited from LayoutEngine base class:
    # _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _estimate_label_size, _overlap_area, _compute_label_positions,
    # _clip_to_boundary, _find_components, _pack_components_lr,
    # _write_back, _to_json
