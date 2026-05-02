"""
Neato layout engine — spring-model force-directed layout.

Port of Graphviz ``lib/neatogen/``.  Positions nodes by minimizing a
stress energy function derived from graph-theoretic distances.

This module orchestrates the pipeline; the algorithmic kernels live
in sibling modules that mirror the C file structure:

============================  =======================================
Python module                 C source
============================  =======================================
``neato.bfs``                 ``lib/neatogen/bfs.c``
``neato.dijkstra``            ``lib/neatogen/dijkstra.c``
``neato.stress``              ``lib/neatogen/stress.c``,
                              ``lib/neatogen/circuit.c``
``neato.kkutils``             ``lib/neatogen/kkutils.c``,
                              ``lib/neatogen/solve.c``
``neato.sgd``                 ``lib/neatogen/sgd.c``
``neato.adjust``              ``lib/neatogen/adjust.c``
``common.matrix``             ``lib/neatogen/matinv.c``,
                              ``lib/neatogen/lu.c``
``common.graph_dist``         shared BFS / Dijkstra primitives
============================  =======================================

Algorithm modes
---------------
- **majorization** (default) — Stress majorization via iterative
  Laplacian solving.  See ``neato.stress``.
- **KK** — Kamada-Kawai gradient descent.  See ``neato.kkutils``.
- **sgd** — Stochastic gradient descent.  See ``neato.sgd``.

Distance models
---------------
- **shortpath** (default) — BFS or Dijkstra shortest paths.
- **circuit** — Effective resistance.  See ``neato.stress.circuit_distances``.
- **subset** — Reweight edges by shared-neighbor count, then shortest path.

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
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine
from gvpy.engines.layout.neato.adjust import remove_overlap
from gvpy.engines.layout.neato.bfs import bfs_distances
from gvpy.engines.layout.neato.dijkstra import dijkstra_distances
from gvpy.engines.layout.neato.kkutils import kamada_kawai
from gvpy.engines.layout.neato.sgd import sgd as sgd_layout
from gvpy.engines.layout.neato.stress import (
    circuit_distances,
    stress_majorization,
)


# ── Constants ────────────────────────────────────

_DFLT_TOLERANCE = 1e-4
_DFLT_DAMPING = 0.99
_DFLT_MAXITER_MAJOR = 200
_DFLT_MAXITER_KK = None       # set to 100*N at runtime
_DFLT_MAXITER_SGD = 30
_POINTS_PER_INCH = 72.0


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


# ── Helpers reused inside the package ───────────

def _compute_distances(layout: "NeatoLayout",
                       nodes: set[str],
                       adj: dict[str, list[str]],
                       edge_len: dict[tuple[str, str], float]
                       ) -> list[list[float]]:
    """All-pairs shortest-path distance matrix.

    Picks BFS (unweighted) or Dijkstra (weighted).  Mirrors the
    dispatch at ``lib/neatogen/neatoinit.c::shortest_path``.
    """
    node_list = [n for n in layout.node_list if n in nodes]
    N = len(node_list)
    idx = {n: i for i, n in enumerate(node_list)}

    has_weights = any(v != 1.0 for v in edge_len.values())

    dist = [[layout.default_dist] * N for _ in range(N)]
    for i in range(N):
        dist[i][i] = 0.0

    for si, source in enumerate(node_list):
        if has_weights:
            dijkstra_distances(source, idx, adj, edge_len,
                               dist[si], layout.default_dist)
        else:
            bfs_distances(source, idx, adj, dist[si])

    return dist


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

        adj, edge_len = self._build_adjacency()

        components = self._find_components(adj)

        if len(components) > 1 and self.pack:
            self._layout_and_pack(components, adj, edge_len)
        else:
            self._layout_component(set(self.node_list), adj, edge_len)

        if self.overlap != "true":
            remove_overlap(self)

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
        """Read all graph attributes and initialize layout nodes."""
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

        dim_str = (self.graph.get_graph_attr("dim")
                   or self.graph.get_graph_attr("dimen"))
        if dim_str:
            try:
                self.dim = max(2, int(dim_str))
            except ValueError:
                pass

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

        start_str = self.graph.get_graph_attr("start") or ""
        if start_str.isdigit():
            self.seed = int(start_str)
        elif start_str == "self":
            self.seed = 0  # use existing positions
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

        self._init_common_attrs()

        self.normalize = (self.graph.get_graph_attr("normalize") or "true") \
            .lower() not in ("false", "0", "no")
        self.pack = (self.graph.get_graph_attr("pack") or "true") \
            .lower() not in ("false", "0", "no")

        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)

            pos_str = (node.attributes.get("pos") or "").strip()
            if pos_str:
                try:
                    parts = pos_str.replace("!", "").split(",")
                    ln.x = float(parts[0]) * _POINTS_PER_INCH
                    ln.y = float(parts[1]) * _POINTS_PER_INCH
                    ln.pos_set = True
                    ln.pinned = ("!" in pos_str
                                 or node.attributes.get("pin", "").lower()
                                 in ("true", "1", "yes"))
                except (ValueError, IndexError):
                    pass
            elif node.attributes.get("pin", "").lower() in ("true", "1", "yes"):
                ln.pinned = True

            self.lnodes[name] = ln

        self.node_list = list(self.lnodes.keys())
        self.node_idx = {n: i for i, n in enumerate(self.node_list)}

        N = len(self.node_list)
        if self.mode == "kk" and not maxiter_str:
            self.maxiter = 100 * N
        elif self.mode == "sgd" and not maxiter_str:
            self.maxiter = _DFLT_MAXITER_SGD
        if self.mode == "kk" and not eps_str:
            self.epsilon = 0.0001 * N
        elif self.mode == "sgd" and not eps_str:
            self.epsilon = 0.01

    # ── Adjacency build ──────────────────────────

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

        total_len = sum(edge_len.values())
        n_edges = max(len(edge_len), 1)
        N = len(self.node_list)
        self.default_dist = (total_len / n_edges) * math.sqrt(N) + 1

        dd_str = self.graph.get_graph_attr("defaultdist")
        if dd_str:
            try:
                self.default_dist = float(dd_str) * _POINTS_PER_INCH
            except ValueError:
                pass

        return dict(adj), edge_len

    # ── Layout dispatch ──────────────────────────

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

        if self.model == "circuit":
            dist = circuit_distances(self, nodes, adj, edge_len)
        else:
            dist = _compute_distances(self, nodes, adj, edge_len)

        self._initialize_positions(node_list, N)

        if self.mode == "kk":
            kamada_kawai(self, node_list, dist, N, idx)
        elif self.mode == "sgd":
            sgd_layout(self, node_list, dist, N, idx, edge_len)
        else:
            stress_majorization(self, node_list, dist, N, idx)

    def _initialize_positions(self, node_list, N):
        """Set initial node positions (random within sqrt(N)*72)."""
        for i, name in enumerate(node_list):
            ln = self.lnodes[name]
            if ln.pos_set:
                continue
            span = math.sqrt(N) * _POINTS_PER_INCH
            ln.x = random.random() * span
            ln.y = random.random() * span

    # ── Component handling ───────────────────────

    def _layout_and_pack(self, components, adj, edge_len):
        """Layout each component separately and pack left-to-right."""
        for comp in components:
            self._layout_component(comp, adj, edge_len)
        gap = max(self.default_dist * 0.5, 36.0)
        self._pack_components_lr(components, gap=gap)

    # Shared methods inherited from LayoutEngine base class:
    # _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _estimate_label_size, _overlap_area, _compute_label_positions,
    # _clip_to_boundary, _find_components, _pack_components_lr,
    # _write_back, _to_json
