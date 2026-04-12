"""
Dot layout engine — hierarchical layout for directed graphs.

A pure-Python implementation of the Graphviz ``dot`` layout algorithm.
It reads a graph parsed by the ANTLR4-based DOT parser and computes
node coordinates, edge routes, and cluster bounding boxes.

Algorithm
---------
The layout runs in four phases, following the Sugiyama framework:

  1. **Rank assignment** — Network simplex assigns each node to a
     hierarchical rank (layer).  Cycles are broken via DFS edge reversal.
     Rank constraints (``rank=same/min/max/source/sink``) and the
     ``newrank`` attribute control whether clusters are ranked
     independently or globally.

  2. **Crossing minimization** — Iterative weighted-median heuristic
     with transposition reduces edge crossings within each rank.
     Controlled by ``mclimit`` and ``remincross``.

  3. **Coordinate assignment** — Y coordinates from rank × ``ranksep``;
     X coordinates via a second network-simplex pass that balances
     connected-node alignment against node-separation constraints.
     ``rankdir`` (TB/BT/LR/RL), ``size``, ``ratio``, ``quantum``, and
     ``normalize`` are applied as post-processing transforms.

  4. **Edge routing** — Polyline waypoints through virtual-node chains,
     with optional Catmull-Rom → cubic-Bézier conversion (default),
     orthogonal routing (``splines=ortho``), or straight lines
     (``splines=line``).  Ports, record-field ports, ``headclip``/
     ``tailclip``, compound-edge clipping (``lhead``/``ltail``), and
     ``samehead``/``sametail`` grouping are all handled here.

Command-line usage
------------------
Use ``gvcli.py`` (the unified CLI) with ``-Kdot`` or simply ``dot.py``
(a wrapper that defaults to the dot engine)::

    python gvcli.py input.gv -Tsvg -o output.svg      # dot layout (default)
    python gvcli.py -Kdot input.gv -Tsvg               # explicit engine
    python dot.py input.gv -Tsvg -o output.svg          # same as above

    python gvcli.py input.gv                            # JSON to stdout
    python gvcli.py input.gv -Tdot                      # DOT with layout coords
    python gvcli.py input.gv -Tjson0                    # structural JSON (no layout)
    python gvcli.py input.gv -Tgxl                      # GXL XML output

    echo "digraph{a->b}" | python gvcli.py - -Tsvg     # stdin
    python gvcli.py input.gv -Grankdir=LR -Nshape=box  # attribute overrides
    python gvcli.py --ui                                # interactive wizard

API usage
---------
Parse a DOT file and run the layout::

    from gvpy.grammar import read_gv, read_gv_file
    from gvpy.engines.dot import DotGraphInfo  # or the DotLayout alias

    # From a file
    graph = read_gv_file("input.gv")
    result = DotGraphInfo(graph).layout()  # JSON-serializable dict

    # From a string
    graph = read_gv('digraph G { a -> b -> c; }')
    result = DotGraphInfo(graph).layout()

Or use the engine registry::

    from gvpy.engines import get_engine

    EngineClass = get_engine("dot")
    result = EngineClass(graph).layout()

The returned dict has the structure::

    {
      "graph": {
        "name": "G",
        "directed": true,
        "bb": [min_x, min_y, max_x, max_y],
        "ratio": "...",          # if set
        "size": [w_pt, h_pt]    # if set
      },
      "nodes": [
        {
          "name": "a",
          "x": 100.0,   "y": 50.0,
          "width": 72.0, "height": 36.0,
          "shape": "box",                # if set
          "record_ports": {"f0": 0.25}   # if record shape
        }
      ],
      "edges": [
        {
          "tail": "a", "head": "b",
          "points": [[x1,y1], [x2,y2], ...],
          "spline_type": "bezier",       # or absent for polyline
          "label": "calls",              # if set
          "label_pos": [x, y],           # if label set
          "lhead": "cluster_0",          # if set
          "ltail": "cluster_1"           # if set
        }
      ],
      "clusters": [                      # present only if clusters exist
        {
          "name": "cluster_0",
          "label": "Group",
          "bb": [x1, y1, x2, y2],
          "nodes": ["a", "b"]
        }
      ]
    }

Coordinates are in **points** (1 pt = 1/72 inch).  The Y axis increases
downward (rank 0 at the top in TB mode).

After layout, ``pos``, ``width``, ``height`` are written back to each
node's attributes, edge spline points are written to ``pos``, and the
graph bounding box is set as ``bb``.  This means ``-Tdot`` output
contains embedded layout coordinates.

To render the result as SVG::

    from gvpy.render import render_svg, render_svg_file

    svg_string = render_svg(result)
    render_svg_file(result, "output.svg")

Supported DOT attributes
------------------------

**Graph attributes:**

===============  ===========================================================
Attribute        Effect
===============  ===========================================================
``rankdir``      Layout direction: TB (default), BT, LR, RL
``ranksep``      Separation between ranks (inches, default 0.5)
``nodesep``      Separation between nodes in same rank (inches, default 0.25)
``splines``      Edge routing: (empty)/true/curved/spline → Bézier;
                 ortho/polyline → right-angle; line → straight
``size``         Maximum canvas size ``"W,H"`` in inches (``!`` to force)
``ratio``        Aspect ratio: compress, fill, or auto
``rankdir``      TB, BT, LR, RL
``compound``     Enable cluster edge clipping (``true``/``false``)
``concentrate``  Merge parallel edges (``true``/``false``)
``ordering``     Preserve input order: ``out`` or ``in``
``newrank``      Global ranking ignoring clusters (``true``/``false``)
``clusterrank``  Cluster handling: local (default), global, none
``normalize``    Shift coordinates to origin (``true``/``false``)
``quantum``      Snap coordinates to grid (points)
``nslimit``      Network-simplex iteration limit for X positioning
``nslimit1``     Network-simplex iteration limit for ranking
``searchsize``   Network-simplex search limit
``mclimit``      Scale crossing-minimization iterations (float, default 1.0)
``remincross``   Second crossing-minimization pass (``true``/``false``)
===============  ===========================================================

**Node attributes:**

===============  ===========================================================
Attribute        Effect
===============  ===========================================================
``label``        Text label (defaults to node name); affects node sizing
``shape``        Passed through to output; ``record``/``Mrecord`` triggers
                 field parsing for sizing and port creation
``width``        Explicit width in inches (overrides label sizing)
``height``       Explicit height in inches (overrides label sizing)
``fontsize``     Font size in points (default 14); affects label sizing
``group``        Same-group edges get ×100 weight boost for alignment
``pos``          Fixed position ``"x,y"`` in inches; ``!`` suffix pins
``pin``          Pin node at current/fixed position (``true``/``false``)
===============  ===========================================================

**Edge attributes:**

================  ==========================================================
Attribute         Effect
================  ==========================================================
``minlen``        Minimum rank span (default 1, capped at 100)
``weight``        Ranking importance (default 1, capped at 1000)
``constraint``    Include in ranking (``true``/``false``)
``label``         Edge label text; positioned at midpoint
``labelangle``    Rotate label position (degrees)
``labeldistance`` Offset label from midpoint (multiplied by font size)
``tailport``      Attachment compass or record port at tail node
``headport``      Attachment compass or record port at head node
``tailclip``      Clip edge at tail boundary (``true``/``false``)
``headclip``      Clip edge at head boundary (``true``/``false``)
``lhead``         Clip edge endpoint to cluster bounding box (compound)
``ltail``         Clip edge start to cluster bounding box (compound)
``samehead``      Group edges sharing same head attachment point
``sametail``      Group edges sharing same tail attachment point
================  ==========================================================

**Subgraph/cluster attributes:**

===============  ===========================================================
Attribute        Effect
===============  ===========================================================
``rank``         Rank constraint: same, min, max, source, sink
``label``        Cluster label (included in output)
``margin``       Cluster bounding-box padding (inches, default ~0.11)
===============  ===========================================================
"""
from __future__ import annotations

import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.core.edge import Edge
from gvpy.engines.base import LayoutEngine


# ── Internal data structures ─────────────────────

@dataclass
class LayoutNode:
    node: Optional[Node]
    rank: int = 0
    order: int = 0
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0   # 0.75 in * 72 dpi
    height: float = 36.0  # 0.50 in * 72 dpi
    virtual: bool = False
    pinned: bool = False
    fixed_pos: tuple | None = None  # (x, y) from pos attribute


@dataclass
class LayoutEdge:
    edge: Optional[Edge]
    tail_name: str
    head_name: str
    minlen: int = 1
    weight: int = 1
    reversed: bool = False
    virtual: bool = False
    orig_tail: str = ""
    orig_head: str = ""
    points: list = field(default_factory=list)
    constraint: bool = True
    label: str = ""
    label_pos: tuple = ()
    tailport: str = ""
    headport: str = ""
    lhead: str = ""
    ltail: str = ""
    spline_type: str = "polyline"  # "polyline" or "bezier"
    headclip: bool = True
    tailclip: bool = True
    samehead: str = ""
    sametail: str = ""
    edge_type: str = "normal"  # normal, flat, reversed, self, virtual


@dataclass
class LayoutCluster:
    name: str
    label: str = ""
    nodes: list = field(default_factory=list)       # recursive (all descendants)
    direct_nodes: list = field(default_factory=list) # direct children only
    bb: tuple = (0.0, 0.0, 0.0, 0.0)
    margin: float = 8.0
    attrs: dict = field(default_factory=dict)  # visual attributes from subgraph


# Compass direction offsets (fraction of half-width/half-height)
_COMPASS = {
    "n": (0.0, -1.0), "ne": (1.0, -1.0), "e": (1.0, 0.0),
    "se": (1.0, 1.0), "s": (0.0, 1.0), "sw": (-1.0, 1.0),
    "w": (-1.0, 0.0), "nw": (-1.0, -1.0), "c": (0.0, 0.0),
    "_": (0.0, 0.0),
}


# ── Network Simplex ──────────────────────────────

class _NetworkSimplex:
    """Network simplex for ranking / positioning — NumPy-accelerated.

    Internally all node names are mapped to integer indices ``0 .. N-1``
    and edge data is stored in four parallel NumPy int32 arrays
    (``_e_tail``, ``_e_head``, ``_e_minlen``, ``_e_weight``).  Ranks,
    DFS ranges (``_low`` / ``_lim``), cut values, and tree membership
    are also NumPy arrays, enabling vectorised hot-loops in
    ``_compute_all_cutvalues``, ``_enter_edge``, ``_feasible_tree``,
    and ``_update``.
    """

    SEARCH_LIMIT = 30

    # ── Construction ─────────────────────────────

    def __init__(self, node_names: list[str],
                 edges: list[tuple[str, str, int, int]]):
        """*edges*: list of ``(tail, head, minlen, weight)``."""
        self.node_names = list(node_names)
        N = len(self.node_names)

        # Name ↔ index maps
        self._n2i: dict[str, int] = {n: i for i, n in enumerate(self.node_names)}
        self._N = N

        # Store original edge tuples for _connect_components / callers
        self._edges_raw: list[tuple[str, str, int, int]] = list(edges)

        # Build NumPy edge arrays
        self._rebuild_edge_arrays()

        # Rank array (filled by _init_rank / caller)
        self.rank = np.zeros(N, dtype=np.int64)

        # Tree membership (bool per edge)
        self._in_tree: np.ndarray = np.zeros(len(edges), dtype=np.bool_)
        self._tree_list: np.ndarray = np.empty(0, dtype=np.intp)  # sorted edge indices

        # Cut values (one per edge, only meaningful for tree edges)
        self._cut: np.ndarray = np.zeros(len(edges), dtype=np.int64)

        # DFS range arrays
        self._low = np.zeros(N, dtype=np.int64)
        self._lim = np.zeros(N, dtype=np.int64)
        self._par_edge = np.full(N, -1, dtype=np.intp)  # parent edge index

        self._si = 0  # search start for _leave_edge

        # Precompute adjacency (node index → list of edge indices)
        self._out: list[list[int]] = [[] for _ in range(N)]
        self._inc: list[list[int]] = [[] for _ in range(N)]
        for i in range(len(self._edges_raw)):
            t_str, h_str = self._edges_raw[i][0], self._edges_raw[i][1]
            ti, hi = self._n2i[t_str], self._n2i[h_str]
            self._out[ti].append(i)
            self._inc[hi].append(i)

        # Weighted-edge mask (precomputed after edges finalised)
        self._we_mask: np.ndarray | None = None

    def _rebuild_edge_arrays(self):
        """(Re)build the four parallel NumPy edge arrays from _edges_raw."""
        E = len(self._edges_raw)
        self._e_tail = np.empty(E, dtype=np.intp)
        self._e_head = np.empty(E, dtype=np.intp)
        self._e_minlen = np.empty(E, dtype=np.int64)
        self._e_weight = np.empty(E, dtype=np.int64)
        n2i = self._n2i
        for i, (t, h, ml, w) in enumerate(self._edges_raw):
            self._e_tail[i] = n2i[t]
            self._e_head[i] = n2i[h]
            self._e_minlen[i] = ml
            self._e_weight[i] = w

    @property
    def edges(self):          # back-compat for callers reading tuples
        return self._edges_raw

    # ── Vectorised helpers ───────────────────────

    def _slack_all(self) -> np.ndarray:
        """Slack of every edge as a 1-D int64 array."""
        return self.rank[self._e_head] - self.rank[self._e_tail] - self._e_minlen

    def _slack(self, ei: int) -> int:
        return int(self.rank[self._e_head[ei]]
                   - self.rank[self._e_tail[ei]]
                   - self._e_minlen[ei])

    # ── Initial feasible ranking ─────────────────

    def _init_rank(self):
        """Compute initial feasible ranks using iterative relaxation.

        Uses Bellman-Ford style relaxation: repeatedly scan all edges
        and update head ranks until no more changes.  This handles
        non-DAG constraint topologies where simple BFS misses backward
        constraints (e.g. weight=0 separation edges between nodes that
        are also connected via edge-pair or containment constraints).
        """
        N = self._N
        E = len(self._edges_raw)
        self.rank[:] = 0

        # Bellman-Ford: relax all edges up to N times
        tails = self._e_tail[:E]
        heads = self._e_head[:E]
        minlens = self._e_minlen[:E]
        for _ in range(N):
            needed = self.rank[tails] + minlens
            violations = self.rank[heads] < needed
            if not violations.any():
                break
            np.maximum.at(self.rank, heads[violations],
                          needed[violations])

    # ── Spanning tree construction ───────────────

    def _feasible_tree(self):
        E = len(self._edges_raw)
        N = self._N
        self._in_tree[:E] = False
        in_tree_node = np.zeros(N, dtype=np.bool_)

        if N == 0:
            return
        in_tree_node[0] = True

        slacks = self._slack_all()

        # Greedy: add tight edges (slack == 0) via repeated scan
        changed = True
        while changed:
            changed = False
            tight = (slacks == 0) & ~self._in_tree[:E]
            for ei in np.where(tight)[0]:
                ti, hi = int(self._e_tail[ei]), int(self._e_head[ei])
                if in_tree_node[ti] and not in_tree_node[hi]:
                    self._in_tree[ei] = True
                    in_tree_node[hi] = True
                    changed = True
                elif in_tree_node[hi] and not in_tree_node[ti]:
                    self._in_tree[ei] = True
                    in_tree_node[ti] = True
                    changed = True

        # Add minimum-slack edges for remaining nodes
        n_in_tree = int(in_tree_node.sum())
        while n_in_tree < N:
            not_tree_edges = ~self._in_tree[:E]
            t_in = in_tree_node[self._e_tail[:E]]
            h_in = in_tree_node[self._e_head[:E]]
            crossing = (t_in != h_in) & not_tree_edges
            if not crossing.any():
                # Disconnected node — just add it
                for i in range(N):
                    if not in_tree_node[i]:
                        in_tree_node[i] = True
                        n_in_tree += 1
                        break
                continue

            abs_slack = np.abs(slacks)
            abs_slack[~crossing] = np.iinfo(np.int64).max
            best_ei = int(np.argmin(abs_slack))

            delta = int(slacks[best_ei])
            ti = int(self._e_tail[best_ei])
            if in_tree_node[ti]:
                # Shift ALL tree nodes UP
                self.rank[in_tree_node] += delta
            else:
                # Shift ALL tree nodes DOWN
                self.rank[in_tree_node] -= delta
            slacks = self._slack_all()  # refresh after rank shift

            self._in_tree[best_ei] = True
            in_tree_node[self._e_tail[best_ei]] = True
            in_tree_node[self._e_head[best_ei]] = True
            n_in_tree = int(in_tree_node.sum())

            # Try adding more tight edges
            changed = True
            while changed:
                changed = False
                tight = (slacks == 0) & ~self._in_tree[:E]
                for ei in np.where(tight)[0]:
                    ti2, hi2 = int(self._e_tail[ei]), int(self._e_head[ei])
                    if in_tree_node[ti2] and not in_tree_node[hi2]:
                        self._in_tree[ei] = True
                        in_tree_node[hi2] = True
                        n_in_tree += 1
                        changed = True
                    elif in_tree_node[hi2] and not in_tree_node[ti2]:
                        self._in_tree[ei] = True
                        in_tree_node[ti2] = True
                        n_in_tree += 1
                        changed = True

    # ── DFS range for subtree queries ────────────

    def _dfs_range(self):
        N = self._N
        if N == 0:
            return
        # Build tree adjacency from edge arrays
        tree_idx = np.where(self._in_tree[:len(self._edges_raw)])[0]
        adj: list[list[tuple[int, int]]] = [[] for _ in range(N)]
        for ei in tree_idx:
            ti, hi = int(self._e_tail[ei]), int(self._e_head[ei])
            adj[ti].append((int(ei), hi))
            adj[hi].append((int(ei), ti))

        self._par_edge[:] = -1
        self._low[:] = 0
        self._lim[:] = 0
        counter = 0

        # Iterative DFS from node 0
        stack: list[tuple[int, int, bool]] = [(0, -1, False)]
        visited = np.zeros(N, dtype=np.bool_)
        while stack:
            node, par_ei, returning = stack[-1]
            if not returning:
                self._low[node] = counter
                counter += 1
                visited[node] = True
                stack[-1] = (node, par_ei, True)
                for ei, nbr in adj[node]:
                    if not visited[nbr]:
                        self._par_edge[nbr] = ei
                        stack.append((nbr, ei, False))
            else:
                self._lim[node] = counter
                counter += 1
                stack.pop()

    def _subtree_mask(self, sub_root: int) -> np.ndarray:
        """Bool mask: which nodes are in the subtree rooted at *sub_root*."""
        lo, li = int(self._low[sub_root]), int(self._lim[sub_root])
        return (self._low >= lo) & (self._low <= li)

    # ── Cut values (vectorised) ──────────────────

    def _init_cutvalues(self):
        self._dfs_range()
        E = len(self._edges_raw)
        self._cut = np.zeros(E, dtype=np.int64)
        # Weighted-edge mask (skip w==0 edges for cut-value sums)
        self._we_mask = self._e_weight[:E] != 0
        self._tree_list = np.where(self._in_tree[:E])[0]
        self._compute_all_cutvalues()

    def _compute_all_cutvalues(self):
        """Vectorised cut-value computation for ALL tree edges at once."""
        E = len(self._edges_raw)
        we = self._we_mask
        if we is None or not we.any():
            return

        # Weighted edge data (only non-zero weight)
        we_tails = self._e_tail[:E][we]
        we_heads = self._e_head[:E][we]
        we_weights = self._e_weight[:E][we]
        we_low_t = self._low[we_tails]
        we_low_h = self._low[we_heads]

        for tree_ei in self._tree_list:
            ti = int(self._e_tail[tree_ei])
            hi = int(self._e_head[tree_ei])
            if self._lim[ti] < self._lim[hi]:
                sub_low = int(self._low[ti])
                sub_lim = int(self._lim[ti])
                direction = 1
            else:
                sub_low = int(self._low[hi])
                sub_lim = int(self._lim[hi])
                direction = -1

            t_in = (we_low_t >= sub_low) & (we_low_t <= sub_lim)
            h_in = (we_low_h >= sub_low) & (we_low_h <= sub_lim)
            crossing = t_in != h_in
            if not crossing.any():
                self._cut[tree_ei] = 0
                continue
            signs = np.where(t_in[crossing], direction, -direction)
            self._cut[tree_ei] = int(np.dot(signs, we_weights[crossing]))

    # ── Pivot operations ─────────────────────────

    def _leave_edge(self) -> int | None:
        tl = self._tree_list
        n = len(tl)
        if n == 0:
            return None
        # Gather cut values for tree edges
        cvs = self._cut[tl]
        neg = cvs < 0
        if not neg.any():
            return None
        # Respect SEARCH_LIMIT: pick the first (up to SEARCH_LIMIT)
        # negative cut value starting from _si
        start = self._si % n
        order = np.roll(np.arange(n), -start)
        neg_positions = order[neg[order]]
        if len(neg_positions) == 0:
            return None
        # Pick the most negative among the first SEARCH_LIMIT candidates
        candidates = neg_positions[:self.SEARCH_LIMIT]
        best_local = candidates[np.argmin(cvs[candidates])]
        self._si = (int(best_local) + 1) % n
        return int(tl[best_local])

    def _enter_edge(self, leaving_ei: int) -> int | None:
        ti = int(self._e_tail[leaving_ei])
        hi = int(self._e_head[leaving_ei])
        sub_root = ti if self._lim[ti] < self._lim[hi] else hi
        sub_low = int(self._low[sub_root])
        sub_lim = int(self._lim[sub_root])

        E = len(self._edges_raw)
        t_low = self._low[self._e_tail[:E]]
        h_low = self._low[self._e_head[:E]]
        t_in = (t_low >= sub_low) & (t_low <= sub_lim)
        h_in = (h_low >= sub_low) & (h_low <= sub_lim)
        crossing = (t_in != h_in) & ~self._in_tree[:E]
        if not crossing.any():
            return None
        slacks = self._slack_all()
        feasible = crossing & (slacks >= 0)
        if not feasible.any():
            return None
        candidates = np.where(feasible)[0]
        return int(candidates[np.argmin(slacks[candidates])])

    def _update(self, leaving_ei: int, entering_ei: int):
        delta = self._slack(entering_ei)
        if delta != 0:
            ti = int(self._e_tail[leaving_ei])
            hi = int(self._e_head[leaving_ei])
            sub_root = ti if self._lim[ti] < self._lim[hi] else hi
            mask = self._subtree_mask(sub_root)

            # Determine shift direction from entering edge
            ent_t = int(self._e_tail[entering_ei])
            shift = delta if mask[ent_t] else -delta
            self.rank[mask] += shift

        # Exchange tree edges
        self._in_tree[leaving_ei] = False
        self._in_tree[entering_ei] = True

        # Recompute DFS ranges and cut values
        self._init_cutvalues()

    # ── Normalize ────────────────────────────────

    def _normalize(self):
        if self._N > 0:
            self.rank -= self.rank.min()

    # ── Main entry point ─────────────────────────

    def solve(self, max_iter: int = 200,
              initial_ranks: dict[str, int] | None = None) -> dict[str, int]:
        if not self.node_names:
            return {}
        if initial_ranks:
            for n, i in self._n2i.items():
                self.rank[i] = initial_ranks.get(n, 0)
            # Light feasibility fixup (2 passes)
            E = len(self._edges_raw)
            for _pass in range(2):
                needed = self.rank[self._e_tail[:E]] + self._e_minlen[:E]
                violations = self.rank[self._e_head[:E]] < needed
                if violations.any():
                    for ei in np.where(violations)[0]:
                        h = int(self._e_head[ei])
                        self.rank[h] = max(int(self.rank[h]),
                                           int(needed[ei]))
        else:
            self._init_rank()
        if self._N <= 1:
            self._normalize()
            return {n: int(self.rank[i]) for n, i in self._n2i.items()}
        self._connect_components()
        if not self._edges_raw:
            self._normalize()
            return {n: int(self.rank[i]) for n, i in self._n2i.items()}
        self._feasible_tree()
        self._init_cutvalues()
        for _ in range(max_iter):
            leaving = self._leave_edge()
            if leaving is None:
                break
            entering = self._enter_edge(leaving)
            if entering is None:
                break
            self._update(leaving, entering)
        self._normalize()
        return {n: int(self.rank[i]) for n, i in self._n2i.items()}

    def _connect_components(self):
        """Add zero-weight edges between disconnected components."""
        N = self._N
        adj: list[list[int]] = [[] for _ in range(N)]
        seen: list[set[int]] = [set() for _ in range(N)]
        for t, h in zip(self._e_tail, self._e_head):
            ti, hi = int(t), int(h)
            if hi not in seen[ti]:
                seen[ti].add(hi)
                adj[ti].append(hi)
            if ti not in seen[hi]:
                seen[hi].add(ti)
                adj[hi].append(ti)
        visited = np.zeros(N, dtype=np.bool_)
        components: list[list[int]] = []
        for start in range(N):
            if visited[start]:
                continue
            comp: list[int] = []
            queue = deque([start])
            while queue:
                u = queue.popleft()
                if visited[u]:
                    continue
                visited[u] = True
                comp.append(u)
                for v in adj[u]:
                    if not visited[v]:
                        queue.append(v)
            components.append(comp)
        # Link components with dummy edges
        for i in range(1, len(components)):
            t_idx = components[i - 1][0]
            h_idx = components[i][0]
            t_name = self.node_names[t_idx]
            h_name = self.node_names[h_idx]
            self._edges_raw.append((t_name, h_name, 0, 0))
            self._out[t_idx].append(len(self._edges_raw) - 1)
            self._inc[h_idx].append(len(self._edges_raw) - 1)
        # Rebuild NumPy arrays if edges were added
        if len(components) > 1:
            self._rebuild_edge_arrays()
            E = len(self._edges_raw)
            self._in_tree = np.zeros(E, dtype=np.bool_)
            self._cut = np.zeros(E, dtype=np.int64)



# Record label parsing removed � now handled by
# gvpy.grammar.record_parser (ANTLR4 RecordLexer/RecordParser)
# with field tree stored on Node.record_fields.
# Removed: _parse_record_fields, _parse_one_field,
# _parse_record_ports (replaced by Node.record_fields.port_fraction).


# ── Layout engine ────────────────────────────────

class DotGraphInfo(LayoutEngine):
    """Hierarchical (dot) layout state container.

    C analogue: ``Agraphinfo_t`` in ``lib/dotgen/dot.h``.  Holds all
    per-layout state for a dot layout (rank arrays, cluster skeletons,
    coordinate assignments, etc.) and drives the four-phase pipeline
    (rank → mincross → position → splines).

    Attaches to a graph via ``graph.attach_view(info, "dot")`` and
    takes the ``view_name="dot"`` key by default.  The ``DotLayout``
    alias defined at the bottom of this module preserves the original
    class name for backward compatibility; all existing
    ``from gvpy.engines.dot import DotLayout`` imports continue to
    work unchanged.
    """

    view_name: str = "dot"
    MAX_MINCROSS_ITER = 24

    # Dot-specific sizing constants for record shapes
    _FIELD_PAD = 8.0

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.ledges: list[LayoutEdge] = []
        self.ranks: dict[int, list[str]] = {}
        self.rankdir: str = "TB"
        self.ranksep: float = 36.0
        self.nodesep: float = 18.0
        self.splines: str = ""
        self.ordering: str = ""
        self.concentrate: bool = False
        self.compound: bool = False
        self.ratio: str = ""
        self.graph_size: tuple[float, float] | None = None
        self.nslimit: int = 200
        self.nslimit1: int = 200
        self.searchsize: int = 30
        self.mclimit: float = 1.0
        self.remincross: bool = True  # C default: ON for clustered graphs
        self.quantum: float = 0.0
        self.normalize: bool = False
        self.clusterrank: str = "local"
        self.newrank: bool = False
        self.center: bool = False
        self.pad: float = 4.0  # points (~0.055 inches)
        self.dpi: float = 96.0
        self.landscape: bool = False
        self.rotate_deg: int = 0
        self.outputorder: str = "breadthfirst"
        self.forcelabels: bool = True
        self._rank_constraints: list[tuple[str, list[str]]] = []
        self._vnode_chains: dict[tuple[str, str], list[str]] = {}
        self._chain_edges: list[LayoutEdge] = []
        self._clusters: list[LayoutCluster] = []
        # _record_ports removed — port fractions now come from
        # Node.record_fields (parsed at DOT load, sized at layout start)

    # ── Public API ───────────────────────────────

    def layout(self) -> dict:
        """Run the full layout pipeline and return a JSON-serializable dict."""
        self._init_from_graph()

        # Component packing: if graph has disconnected components,
        # lay out each one separately and pack them side by side.
        components = self._find_components()
        if len(components) > 1:
            print(f"[TRACE rank] component packing: {len(components)} components", file=sys.stderr)
            return self._pack_components(components)

        print(f"[TRACE rank] begin layout: nodes={len(self.lnodes)} edges={len(self.ledges)} clusters={len(self._clusters)}", file=sys.stderr)
        self._phase1_rank()
        self._phase2_ordering()
        self._phase3_position()
        self._apply_fixed_positions()
        self._apply_size()
        self._compute_cluster_boxes()
        self._phase4_routing()
        if self.concentrate:
            self._concentrate_edges()
        if self.quantum > 0:
            self._apply_quantum()
        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()
        self._compute_xlabel_positions()
        self._write_back()
        return self._to_json()

    # ── Initialization ───────────────────────────

    def _init_from_graph(self):
        rd = self.graph.get_graph_attr("rankdir")
        if rd:
            self.rankdir = rd.upper()

        rs = self.graph.get_graph_attr("ranksep")
        if rs:
            try:
                self.ranksep = float(rs) * 72.0
            except ValueError:
                pass

        ns = self.graph.get_graph_attr("nodesep")
        if ns:
            try:
                self.nodesep = float(ns) * 72.0
            except ValueError:
                pass

        self.splines = (self.graph.get_graph_attr("splines") or "").lower()
        self.ordering = (self.graph.get_graph_attr("ordering") or "").lower()
        self.concentrate = (self.graph.get_graph_attr("concentrate") or "").lower() == "true"
        self.compound = (self.graph.get_graph_attr("compound") or "").lower() == "true"
        self.ratio = (self.graph.get_graph_attr("ratio") or "").lower()

        # Optimization parameters
        for attr, field, conv in [
            ("nslimit", "nslimit", int), ("nslimit1", "nslimit1", int),
            ("searchsize", "searchsize", int),
            ("mclimit", "mclimit", float), ("quantum", "quantum", float),
        ]:
            val = self.graph.get_graph_attr(attr)
            if val:
                try:
                    setattr(self, field, conv(val))
                except ValueError:
                    pass
        self.remincross = (self.graph.get_graph_attr("remincross") or "").lower() in ("true", "1", "yes")
        self.normalize = (self.graph.get_graph_attr("normalize") or "").lower() in ("true", "1", "yes")
        self.clusterrank = (self.graph.get_graph_attr("clusterrank") or "local").lower()
        self.newrank = (self.graph.get_graph_attr("newrank") or "").lower() in ("true", "1", "yes")
        self.center = (self.graph.get_graph_attr("center") or "").lower() in ("true", "1", "yes")
        self.landscape = (self.graph.get_graph_attr("landscape") or "").lower() in ("true", "1", "yes")
        self.forcelabels = (self.graph.get_graph_attr("forcelabels") or "true").lower() not in ("false", "0", "no")
        self.outputorder = (self.graph.get_graph_attr("outputorder") or "breadthfirst").lower()

        pad_str = self.graph.get_graph_attr("pad")
        if pad_str:
            try:
                self.pad = float(pad_str) * 72.0
            except ValueError:
                pass

        dpi_str = self.graph.get_graph_attr("dpi") or self.graph.get_graph_attr("resolution")
        if dpi_str:
            try:
                self.dpi = float(dpi_str)
            except ValueError:
                pass

        rot_str = self.graph.get_graph_attr("rotate")
        if rot_str:
            try:
                self.rotate_deg = int(rot_str)
            except ValueError:
                pass

        size_str = self.graph.get_graph_attr("size")
        if size_str:
            try:
                parts = size_str.rstrip("!").split(",")
                self.graph_size = (float(parts[0]) * 72.0, float(parts[1]) * 72.0)
            except (ValueError, IndexError):
                pass

        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(node=node, width=w, height=h)

            # Size record fields and store geometry on Node
            # (C shapes.c:3687-3731 record_init)
            # Flow: parse_reclbl → size_reclbl → resize_reclbl → pos_reclbl
            # For LR/RL, C starts with flip=TRUE (shapes.c:3705) which
            # swaps the LR direction at the top level.
            if node.record_fields is not None:
                fontsize = 14.0
                try:
                    fontsize = float(node.attributes.get("fontsize", "14"))
                except (ValueError, TypeError):
                    pass
                # Flip for LR/RL (C shapes.c:3705 flip = GD_flip)
                if self.rankdir in ("LR", "RL"):
                    self._flip_record_lr(node.record_fields)
                # Step 1: compute natural sizes (C size_reclbl, shapes.c:3711)
                node.record_fields.compute_size(fontsize=fontsize)
                # Step 2: resize to fit node bounds (C shapes.c:3712-3724)
                # sz = max(natural_size, node_default_size)
                # C: sz.x = INCH2PS(ND_width(n)), sz.y = INCH2PS(ND_height(n))
                # Default node size: 0.75in × 0.5in = 54pt × 36pt
                node_w = w  # from _compute_node_size (already in points)
                node_h = h
                rw = max(node.record_fields.width, node_w)
                rh = max(node.record_fields.height, node_h)
                # C resize_reclbl (shapes.c:3724): distribute excess space
                node.record_fields.resize(rw, rh)
                # Step 3: position fields (C pos_reclbl, shapes.c:3725)
                node.record_fields.compute_positions(
                    0, 0, node.record_fields.width,
                    node.record_fields.height)
            # Store computed geometry on Node (C: ND_lw, ND_rw, ND_ht)
            node.lw = w / 2.0
            node.rw = w / 2.0
            node.ht = h
            # Read pos and pin attributes
            pos_str = node.attributes.get("pos", "")
            if pos_str:
                try:
                    parts = pos_str.replace("!", "").split(",")
                    ln.fixed_pos = (float(parts[0]) * 72.0, float(parts[1]) * 72.0)
                    ln.pinned = "!" in node.attributes.get("pos", "") or \
                                node.attributes.get("pin", "").lower() in ("true", "1", "yes")
                except (ValueError, IndexError):
                    pass
            elif node.attributes.get("pin", "").lower() in ("true", "1", "yes"):
                ln.pinned = True
            self.lnodes[name] = ln

        self._collect_edges(self.graph)

        # Read pack attribute
        pack_str = self.graph.get_graph_attr("pack")
        self.pack = pack_str is None or pack_str.lower() not in ("false", "0", "no")
        pack_sep = self.graph.get_graph_attr("packmode") or ""
        self.pack_sep = 16.0  # default gap between components
        if pack_str:
            try:
                self.pack_sep = float(pack_str)
            except ValueError:
                pass

        if not self.graph.directed:
            self._orient_undirected()

        self._collect_rank_constraints()
        self._collect_clusters()

    def _find_components(self) -> list[set[str]]:
        """Find connected components using BFS.  Returns list of node-name sets.

        Nodes in the same subgraph are treated as connected (they share
        a cluster).  If pack=false or there's only one component,
        returns a single set.
        """
        if not self.pack:
            return [set(self.lnodes.keys())]

        real_nodes = {n for n, ln in self.lnodes.items() if not ln.virtual}
        if not real_nodes:
            return [set()]

        # Don't pack if any nodes are pinned (pinned positions are absolute)
        if any(ln.pinned or ln.fixed_pos for ln in self.lnodes.values()
               if not ln.virtual):
            return [real_nodes]

        # Build adjacency from edges
        adj: dict[str, set[str]] = defaultdict(set)
        for le in self.ledges:
            if le.tail_name in real_nodes and le.head_name in real_nodes:
                adj[le.tail_name].add(le.head_name)
                adj[le.head_name].add(le.tail_name)

        # Nodes in the same subgraph hierarchy are implicitly connected
        def _all_nodes_in(g):
            """Gather all nodes in g and its nested subgraphs."""
            result = set()
            for n in g.nodes:
                if n in real_nodes:
                    result.add(n)
            for sub in g.subgraphs.values():
                result.update(_all_nodes_in(sub))
            return result

        def _link_subgraph_nodes(g):
            for sub in g.subgraphs.values():
                # All nodes in this subgraph tree are connected
                all_sub = list(_all_nodes_in(sub))
                for i in range(len(all_sub)):
                    for j in range(i + 1, len(all_sub)):
                        adj[all_sub[i]].add(all_sub[j])
                        adj[all_sub[j]].add(all_sub[i])
                _link_subgraph_nodes(sub)
        _link_subgraph_nodes(self.graph)

        visited: set[str] = set()
        components: list[set[str]] = []
        for node in real_nodes:
            if node in visited:
                continue
            comp: set[str] = set()
            queue = deque([node])
            while queue:
                n = queue.popleft()
                if n in visited:
                    continue
                visited.add(n)
                comp.add(n)
                for nb in adj.get(n, ()):
                    if nb not in visited:
                        queue.append(nb)
            components.append(comp)

        return components

    def _pack_components(self, components: list[set[str]]) -> dict:
        """Lay out each connected component separately, then pack side by side.

        Port of Graphviz lib/common/pack.c packing algorithm.
        """
        all_results: list[dict] = []
        component_bbs: list[tuple[float, float, float, float]] = []

        for comp_nodes in components:
            # Create a sub-layout with only this component's nodes/edges
            sub_graph = Graph(self.graph.name, directed=self.graph.directed,
                              strict=self.graph.strict)
            sub_graph.method_init()
            # Copy graph attributes
            for k, v in self.graph.attr_dict_g.items():
                sub_graph.set_graph_attr(k, v)
            # Copy nodes
            for name in comp_nodes:
                node = self.graph.nodes.get(name)
                if node:
                    n = sub_graph.add_node(name)
                    for k, v in node.attributes.items():
                        n.agset(k, v)
            # Copy edges within this component
            for key, edge in self.graph.edges.items():
                if edge.tail.name in comp_nodes and edge.head.name in comp_nodes:
                    e = sub_graph.add_edge(edge.tail.name, edge.head.name)
                    for k, v in edge.attributes.items():
                        e.agset(k, v)

            # Copy subgraphs that contain nodes in this component
            def _copy_subgraphs(src, dst, comp):
                for sub_name, sub in src.subgraphs.items():
                    sub_node_names = [n for n in sub.nodes if n in comp]
                    if sub_node_names:
                        new_sub = dst.create_subgraph(sub_name)
                        for k, v in sub.attr_record.items():
                            new_sub.attr_record[k] = v
                        for n in sub_node_names:
                            new_sub.add_node(n)
                        _copy_subgraphs(sub, new_sub, comp)
            _copy_subgraphs(self.graph, sub_graph, comp_nodes)

            result = DotGraphInfo(sub_graph).layout()
            all_results.append(result)

            bb = result.get("graph", {}).get("bb", [0, 0, 100, 100])
            component_bbs.append(tuple(bb))

        # Pack components left-to-right
        gap = self.pack_sep
        x_offset = 0.0
        merged = {
            "graph": {
                "name": self.graph.name,
                "directed": self.graph.directed,
                "bb": [0, 0, 0, 0],
            },
            "nodes": [],
            "edges": [],
            "clusters": [],
        }

        global_min_y = float("inf")
        global_max_y = float("-inf")

        for result, bb in zip(all_results, component_bbs):
            comp_w = bb[2] - bb[0]
            comp_h = bb[3] - bb[1]
            # Shift this component so its left edge starts at x_offset
            dx = x_offset - bb[0]
            dy = -bb[1]  # align tops

            for node in result.get("nodes", []):
                node["x"] += dx
                node["y"] += dy
                merged["nodes"].append(node)

            for edge in result.get("edges", []):
                edge["points"] = [[p[0] + dx, p[1] + dy] for p in edge.get("points", [])]
                if "label_pos" in edge:
                    edge["label_pos"] = [edge["label_pos"][0] + dx,
                                         edge["label_pos"][1] + dy]
                merged["edges"].append(edge)

            for cl in result.get("clusters", []):
                old_bb = cl.get("bb", [0, 0, 0, 0])
                cl["bb"] = [old_bb[0] + dx, old_bb[1] + dy,
                            old_bb[2] + dx, old_bb[3] + dy]
                merged["clusters"].append(cl)

            global_min_y = min(global_min_y, dy)
            global_max_y = max(global_max_y, dy + comp_h)
            x_offset += comp_w + gap

        merged["graph"]["bb"] = [
            0, global_min_y if global_min_y != float("inf") else 0,
            round(x_offset - gap, 2),
            round(global_max_y if global_max_y != float("-inf") else 100, 2),
        ]

        # Pass through graph-level attrs
        for attr in ("bgcolor", "label", "labelloc", "labeljust",
                     "fontname", "fontsize", "fontcolor",
                     "_label_pos_x", "_label_pos_y"):
            val = self.graph.get_graph_attr(attr)
            if val:
                merged["graph"][attr] = val

        if not merged.get("clusters"):
            del merged["clusters"]

        return merged

    def _orient_undirected(self):
        visited = set()
        adj: dict[str, list[int]] = defaultdict(list)
        for i, le in enumerate(self.ledges):
            adj[le.tail_name].append(i)
            adj[le.head_name].append(i)
        oriented = set()

        def dfs(u):
            visited.add(u)
            for idx in adj[u]:
                le = self.ledges[idx]
                if idx in oriented:
                    continue
                oriented.add(idx)
                other = le.head_name if le.tail_name == u else le.tail_name
                if le.tail_name != u:
                    le.tail_name, le.head_name = u, other
                if other not in visited:
                    dfs(other)

        for name in self.lnodes:
            if name not in visited:
                dfs(name)

    def _collect_rank_constraints(self):
        self._rank_constraints = []
        self._scan_subgraphs(self.graph)

    def _scan_subgraphs(self, g: Graph):
        for sub_name, sub in g.subgraphs.items():
            rank_attr = sub.get_graph_attr("rank")
            if rank_attr and rank_attr in ("same", "min", "max", "source", "sink"):
                node_names = [n for n in sub.nodes if n in self.lnodes]
                if node_names:
                    self._rank_constraints.append((rank_attr, node_names))
            self._scan_subgraphs(sub)

    def _collect_edges(self, g: Graph):
        """Recursively collect edges from graph and all subgraphs."""
        seen = set()  # avoid duplicates from shared edges
        self._collect_edges_recursive(g, seen)

    def _collect_edges_recursive(self, g: Graph, seen: set):
        for key, edge in g.edges.items():
            if id(edge) in seen:
                continue
            seen.add(id(edge))
            tail_name, head_name, _ = key
            if tail_name not in self.lnodes or head_name not in self.lnodes:
                continue
            ml = min(int(edge.attributes.get("minlen", "1")), 100)
            # Edge label ranks: labeled edges with minlen=1 get minlen=2
            # to reserve a rank slot for the label.  Only applies to
            # cross-rank edges (flat edges are handled separately).
            # Graphviz also halves ranksep to compensate, but we skip
            # that since our ranksep handling differs.
            if edge.attributes.get("label") and ml == 1:
                ml = 2
            wt = min(int(edge.attributes.get("weight", "1")), 1000)
            cstr = edge.attributes.get("constraint", "true").lower()
            has_constraint = cstr not in ("false", "none", "no", "0")
            label = edge.attributes.get("label", "")
            tp = edge.attributes.get("tailport", "")
            hp = edge.attributes.get("headport", "")
            lh = edge.attributes.get("lhead", "")
            lt = edge.attributes.get("ltail", "")
            hc = edge.attributes.get("headclip", "true").lower() not in ("false", "0", "no")
            tc = edge.attributes.get("tailclip", "true").lower() not in ("false", "0", "no")
            sh = edge.attributes.get("samehead", "")
            st = edge.attributes.get("sametail", "")
            self.ledges.append(LayoutEdge(
                edge=edge, tail_name=tail_name, head_name=head_name,
                minlen=ml, weight=wt, constraint=has_constraint,
                label=label, tailport=tp, headport=hp,
                lhead=lh, ltail=lt, headclip=hc, tailclip=tc,
                samehead=sh, sametail=st,
            ))
        for sub in g.subgraphs.values():
            self._collect_edges_recursive(sub, seen)

    def _collect_clusters(self):
        """Scan subgraphs for cluster_* names and record membership.

        After scanning, a deduplication pass removes nodes that were
        spuriously added to a cluster because an edge referencing them
        appeared in that cluster's subgraph body.  In Graphviz C,
        a node belongs to a cluster only if it was *defined* there (or
        in a descendant cluster), not merely *referenced* in an edge.
        """
        self._clusters = []
        if self.clusterrank != "none":
            self._scan_clusters(self.graph)
            self._dedup_cluster_nodes()

    def _all_nodes_recursive(self, sub) -> list[str]:
        """Collect all unique node names from a subgraph and its descendants."""
        seen: set[str] = set()
        self._collect_nodes_into(sub, seen)
        return sorted(seen)

    def _collect_nodes_into(self, sub, seen: set[str]):
        for n in sub.nodes:
            if n in self.lnodes:
                seen.add(n)
        for child in sub.subgraphs.values():
            self._collect_nodes_into(child, seen)

    def _scan_clusters(self, g: Graph):
        for sub_name, sub in g.subgraphs.items():
            if sub_name.startswith("cluster"):
                node_names = self._all_nodes_recursive(sub)
                direct_names = [n for n in sub.nodes if n in self.lnodes]
                label = sub.get_graph_attr("label") or ""
                margin_str = sub.get_graph_attr("margin")
                # margin is in points (not inches)
                margin = float(margin_str) if margin_str else 8.0
                # Collect visual attributes for rendering
                cl_attrs = {}
                for attr in ("color", "fillcolor", "bgcolor", "pencolor",
                             "fontcolor", "fontname", "fontsize", "style",
                             "penwidth", "peripheries", "labelloc", "labeljust",
                             "tooltip", "URL", "href", "target", "id", "class",
                             "colorscheme", "gradientangle"):
                    val = sub.get_graph_attr(attr)
                    if val:
                        cl_attrs[attr] = val
                self._clusters.append(LayoutCluster(
                    name=sub_name, label=label, nodes=node_names,
                    direct_nodes=direct_names, margin=margin, attrs=cl_attrs,
                ))
            self._scan_clusters(sub)

    def _dedup_cluster_nodes(self):
        """Remove spurious node membership caused by edge references.

        In DOT, when an edge ``A -> B`` appears inside a subgraph, the
        parser adds both A and B to that subgraph's node dict even if
        A was *defined* in a different subgraph.  Graphviz C only adds a
        node to a cluster if it was created there.

        Strategy: use the **subgraph tree** (not node-set containment)
        to determine the true cluster hierarchy.  Then for each node,
        find the deepest cluster that is its true home by checking which
        cluster's child subgraphs do NOT contain the node.
        """
        if not self._clusters:
            return

        cl_names = {cl.name for cl in self._clusters}

        # Build the TRUE parent map from the subgraph tree structure,
        # not from node-set containment (which is corrupted by the bug).
        tree_parent: dict[str, str | None] = {}

        def _walk_tree(g, parent_cl: str | None):
            for sub_name, sub in g.subgraphs.items():
                if sub_name in cl_names:
                    tree_parent[sub_name] = parent_cl
                    _walk_tree(sub, sub_name)
                else:
                    # Non-cluster subgraph: pass through parent
                    _walk_tree(sub, parent_cl)

        _walk_tree(self.graph, None)

        tree_children: dict[str | None, list[str]] = {}
        for cn, par in tree_parent.items():
            tree_children.setdefault(par, []).append(cn)

        # For each cluster, collect nodes from all descendant clusters
        _desc_nodes_cache: dict[str, set[str]] = {}
        def _desc_nodes(cl_name: str) -> set[str]:
            if cl_name in _desc_nodes_cache:
                return _desc_nodes_cache[cl_name]
            result: set[str] = set()
            for kid in tree_children.get(cl_name, []):
                cl_obj = next((c for c in self._clusters if c.name == kid), None)
                if cl_obj:
                    result.update(cl_obj.nodes)
                result.update(_desc_nodes(kid))
            _desc_nodes_cache[cl_name] = result
            return result

        # A node's true home: the deepest cluster (by tree structure)
        # where it appears but is NOT in any tree-child cluster.
        home_of: dict[str, str] = {}
        for cl in self._clusters:
            desc = _desc_nodes(cl.name)
            for n in cl.nodes:
                if n not in desc:
                    # n is in this cluster but not in any child → home
                    # Smallest cluster wins (overwrite from larger to smaller)
                    if n not in home_of:
                        home_of[n] = cl.name
                    else:
                        # Keep the deeper one (further from root in tree)
                        cur_depth = 0
                        p = cl.name
                        while tree_parent.get(p) is not None:
                            cur_depth += 1
                            p = tree_parent[p]
                        old_depth = 0
                        p = home_of[n]
                        while tree_parent.get(p) is not None:
                            old_depth += 1
                            p = tree_parent[p]
                        if cur_depth > old_depth:
                            home_of[n] = cl.name

        def _tree_ancestors(cl_name: str) -> set[str]:
            anc: set[str] = set()
            cur = cl_name
            while tree_parent.get(cur) is not None:
                cur = tree_parent[cur]
                anc.add(cur)
            return anc

        # Remove nodes whose home is not this cluster or a descendant.
        for cl in self._clusters:
            cleaned = []
            for n in cl.nodes:
                home = home_of.get(n)
                if home is None:
                    cleaned.append(n)
                    continue
                # Keep if: home == this cluster, or this cluster is a
                # tree-ancestor of home.
                if home == cl.name or cl.name in _tree_ancestors(home):
                    cleaned.append(n)
            cl.nodes = cleaned
            cl.direct_nodes = [n for n in cl.direct_nodes
                               if n in set(cleaned)]

    def _compute_cluster_boxes(self):
        """Delegates to gvpy.engines.dot.position.compute_cluster_boxes."""
        from gvpy.engines.dot import position
        return position.compute_cluster_boxes(self)

    def _separate_sibling_clusters(self):
        """Push apart sibling clusters whose bounding boxes overlap.

        Builds a cluster hierarchy, identifies sibling groups, and shifts
        nodes so that sibling clusters occupy non-overlapping regions.
        After shifting, ``_compute_cluster_boxes`` should be called again.
        """
        if not self._clusters:
            return

        # Build parent map: for each cluster, find the smallest containing cluster
        cl_by_name: dict[str, "LayoutCluster"] = {cl.name: cl for cl in self._clusters}
        node_sets = {cl.name: set(cl.nodes) for cl in self._clusters}
        parent_of: dict[str, str | None] = {}

        for cl in self._clusters:
            best_parent = None
            best_size = float("inf")
            for other in self._clusters:
                if other.name == cl.name:
                    continue
                if node_sets[cl.name] < node_sets[other.name]:
                    if len(node_sets[other.name]) < best_size:
                        best_parent = other.name
                        best_size = len(node_sets[other.name])
            parent_of[cl.name] = best_parent

        # Group siblings (same parent)
        children_of: dict[str | None, list[str]] = {}
        for cl_name, par in parent_of.items():
            children_of.setdefault(par, []).append(cl_name)

        # Only separate leaf-level sibling clusters (those with no children).
        # This avoids cascading shifts from parent-level separations.
        gap = 8.0

        # Only separate leaf-level sibling clusters (those with no children)
        # to avoid cascading shifts from parent-level separation.
        has_children = set()
        for par in parent_of.values():
            if par is not None:
                has_children.add(par)

        # Always separate on X-axis because this runs BEFORE
        # _apply_rankdir (coordinates are still in TB space).
        for _parent, siblings in children_of.items():
            leaf_sibs = [s for s in siblings if s not in has_children]
            if len(leaf_sibs) < 2:
                continue
            sib_cls = [cl_by_name[s] for s in leaf_sibs if cl_by_name[s].bb]
            if len(sib_cls) < 2:
                continue

            sib_cls.sort(key=lambda c: c.bb[0])
            for i in range(len(sib_cls) - 1):
                c1 = sib_cls[i]
                c2 = sib_cls[i + 1]
                overlap_val = c1.bb[2] + gap - c2.bb[0]
                if overlap_val > 0:
                    # Shift all nodes in subsequent siblings rightward
                    shift_nodes: set[str] = set()
                    for sib in sib_cls[i + 1:]:
                        shift_nodes.update(node_sets.get(sib.name, set()))
                    for name in shift_nodes:
                        if name in self.lnodes:
                            self.lnodes[name].x += overlap_val
                    # Recompute bboxes for shifted clusters
                    for sib in sib_cls[i + 1:]:
                        members = [self.lnodes[n] for n in sib.nodes
                                   if n in self.lnodes]
                        if members:
                            sib.bb = (
                                min(ln.x - ln.width/2 for ln in members) - sib.margin,
                                min(ln.y - ln.height/2 for ln in members) - sib.margin,
                                max(ln.x + ln.width/2 for ln in members) + sib.margin,
                                max(ln.y + ln.height/2 for ln in members) + sib.margin,
                            )

    def _shift_cluster_nodes_y(self, cl, dy: float, node_sets: dict,
                                subsequent: list, prior: list):
        """Shift nodes exclusively in subsequent siblings by dy.

        Nodes shared with prior (already positioned) siblings are not moved.
        """
        prior_nodes: set[str] = set()
        for p in prior:
            prior_nodes.update(node_sets.get(p.name, set()))

        nodes_to_shift: set[str] = set()
        for sib in subsequent:
            nodes_to_shift.update(node_sets.get(sib.name, set()))
        nodes_to_shift -= prior_nodes

        for name in nodes_to_shift:
            if name in self.lnodes:
                self.lnodes[name].y += dy

    def _shift_cluster_nodes_x(self, cl, dx: float, node_sets: dict,
                                subsequent: list, prior: list):
        """Shift nodes exclusively in subsequent siblings by dx."""
        prior_nodes: set[str] = set()
        for p in prior:
            prior_nodes.update(node_sets.get(p.name, set()))

        nodes_to_shift: set[str] = set()
        for sib in subsequent:
            nodes_to_shift.update(node_sets.get(sib.name, set()))
        nodes_to_shift -= prior_nodes

        for name in nodes_to_shift:
            if name in self.lnodes:
                self.lnodes[name].x += dx

    # ── Node sizing ──────────────────────────────

    # _MIN_WIDTH, _MIN_HEIGHT, _H_PAD, _V_PAD inherited from LayoutEngine

    @staticmethod
    def _flip_record_lr(rf):
        """Flip LR flags for LR/RL rankdir.

        C shapes.c:3705: record_init calls parse_reclbl with flip=TRUE
        for LR/RL, which makes the top-level fields stack vertically
        (TB) instead of horizontally (LR).  Each {} nesting flips again.
        """
        rf.LR = not rf.LR
        for child in rf.children:
            DotGraphInfo._flip_record_lr(child)

    def _rankdir_int(self) -> int:
        """Return rankdir as Graphviz integer constant.

        Matches C's GD_rankdir values (const.h:181-184):
          RANKDIR_TB=0, RANKDIR_LR=1, RANKDIR_BT=2, RANKDIR_RL=3
        """
        return {"TB": 0, "LR": 1, "BT": 2, "RL": 3}.get(self.rankdir, 0)

    def _compute_node_size(self, name: str, node) -> tuple[float, float]:
        """Compute node dimensions from label text, shape, and explicit width/height."""
        attrs = node.attributes if node else {}

        fixedsize = attrs.get("fixedsize", "false").lower() in ("true", "1", "yes", "shape")
        explicit_w = attrs.get("width")
        explicit_h = attrs.get("height")
        # fixedsize=true: use explicit dimensions exactly, ignore label
        if fixedsize:
            w = float(explicit_w) * 72.0 if explicit_w else self._MIN_WIDTH
            h = float(explicit_h) * 72.0 if explicit_h else self._MIN_HEIGHT
            return w, h
        # Both explicit: use as-is (acts as minimum that label can expand)
        if explicit_w and explicit_h:
            return float(explicit_w) * 72.0, float(explicit_h) * 72.0

        shape = attrs.get("shape", "ellipse")
        label = attrs.get("label", name)
        try:
            fontsize = float(attrs.get("fontsize", "14"))
        except ValueError:
            fontsize = 14.0
        char_w = fontsize * 0.52  # proportional character width estimate

        # Record shapes: parse fields to determine dimensions
        # Port positions now come from Node.record_fields (sized in
        # _init_from_graph), not from _parse_record_ports.
        if shape in ("record", "Mrecord"):
            w, h = self._record_size(label, fontsize, char_w)
        else:
            # Strip HTML tags for sizing
            if label.startswith("<") and label.endswith(">"):
                import re
                label = re.sub(r"<[^>]+>", "", label)

            lines = label.replace("\\n", "\n").split("\n")
            max_line_len = max(len(line) for line in lines) if lines else len(name)
            num_lines = len(lines)
            text_w = max_line_len * char_w
            text_h = num_lines * fontsize * 1.2
            w = text_w + self._H_PAD
            h = text_h + self._V_PAD

        # Apply explicit overrides if only one dimension is set
        if explicit_w:
            w = float(explicit_w) * 72.0
        if explicit_h:
            h = float(explicit_h) * 72.0

        w = max(w, self._MIN_WIDTH)
        h = max(h, self._MIN_HEIGHT)
        return w, h

    def _record_size(self, label: str, fontsize: float, char_w: float) -> tuple[float, float]:
        """Compute width and height for a record shape label.

        Record labels use | to separate fields and {} to flip orientation.
        For TB/BT the base orientation is horizontal (fields left-to-right).
        For LR/RL the base orientation is vertical (fields top-to-bottom).
        Each {} flips the orientation.

        The measurement uses the **rotated** base orientation for LR/RL so
        that after ``_apply_rankdir`` swaps width↔height, the final
        dimensions match the Graphviz C reference.  In Graphviz C the
        record layout routine (``record_init`` in ``shapes.c``) checks
        ``rankdir`` and starts with ``flip=TRUE`` for LR/RL.
        """
        from gvpy.render.svg_renderer import _parse_record_label
        tree = _parse_record_label(label)
        if self.rankdir in ("LR", "RL"):
            # For LR/RL, measure with horizontal=False so that the
            # outer {} in labels like {A|B|C} flips to horizontal,
            # producing content-proportional field widths.  Since
            # _apply_rankdir will swap w↔h, we return (h, w) here
            # so the final dimensions are correct.
            w, h = self._measure_record_tree(tree, False, fontsize, char_w)
            w, h = h, w  # pre-swap for _apply_rankdir
        else:
            w, h = self._measure_record_tree(tree, True, fontsize, char_w)
        return max(w, self._MIN_WIDTH), max(h, self._MIN_HEIGHT)

    def _measure_record_tree(self, node: dict, horizontal: bool,
                             fontsize: float, char_w: float) -> tuple[float, float]:
        """Recursively measure a record tree node, returning (width, height)."""
        cell_h = fontsize * 1.4 + 4.0  # height of a single text cell
        min_cell_w = 20.0

        effective_h = not horizontal if node.get("flipped") else horizontal

        if not node.get("children"):
            # Leaf node: size based on text
            text = node.get("text", "")
            w = max(len(text) * char_w + self._FIELD_PAD * 2, min_cell_w)
            return w, cell_h

        # Measure all children
        child_sizes = [
            self._measure_record_tree(c, effective_h, fontsize, char_w)
            for c in node["children"]
        ]

        if effective_h:
            # Horizontal: children laid out left-to-right
            total_w = sum(cw for cw, _ in child_sizes)
            max_h = max(ch for _, ch in child_sizes)
            return total_w, max_h
        else:
            # Vertical: children laid out top-to-bottom
            max_w = max(cw for cw, _ in child_sizes)
            total_h = sum(ch for _, ch in child_sizes)
            return max_w, total_h

    # ── Phase 1: Rank assignment ─────────────────

    def _phase1_rank(self):
        print(f"[TRACE rank] phase1 begin: newrank={self.newrank} clusterrank={self.clusterrank}", file=sys.stderr)
        self._break_cycles()
        reversed_count = sum(1 for le in self.ledges if le.reversed)
        print(f"[TRACE rank] break_cycles: reversed={reversed_count}", file=sys.stderr)
        self._classify_edges()
        # Inject rank=same constraints as zero-length high-weight edges
        # BEFORE running NS so the solver respects them natively
        # (matching Graphviz collapse_sets).
        self._inject_same_rank_edges()
        if self.newrank or self.clusterrank == "none":
            self._network_simplex_rank()
        else:
            self._cluster_aware_rank()
        # Log rank assignments for all real (non-virtual) nodes
        for name in sorted(self.lnodes.keys()):
            ln = self.lnodes[name]
            if not ln.virtual:
                print(f"[TRACE rank] node_rank: {name} rank={ln.rank}", file=sys.stderr)
        self._apply_rank_constraints()
        self._compact_ranks()
        max_rank = max((ln.rank for ln in self.lnodes.values()), default=0)
        print(f"[TRACE rank] after compact: max_rank={max_rank}", file=sys.stderr)
        self._add_virtual_nodes()
        vcount = sum(1 for ln in self.lnodes.values() if ln.virtual)
        print(f"[TRACE rank] virtual_nodes: {vcount}", file=sys.stderr)
        self._build_ranks()
        self._classify_flat_edges()
        print(f"[TRACE rank] phase1 done: ranks={sorted(self.ranks.keys())} nodes_per_rank={[(r, len(self.ranks[r])) for r in sorted(self.ranks.keys())]}", file=sys.stderr)

    def _inject_same_rank_edges(self):
        """Add zero-length high-weight edges between rank=same nodes.

        This ensures the network simplex solver assigns them the same rank
        rather than relying on a post-hoc fixup that can violate other
        edge constraints.  Mirrors Graphviz ``rank.c:collapse_sets()``.
        """
        for kind, node_names in self._rank_constraints:
            if kind != "same" or len(node_names) < 2:
                continue
            # Chain consecutive pairs with bidirectional zero-length edges
            for i in range(len(node_names) - 1):
                a, b = node_names[i], node_names[i + 1]
                if a not in self.lnodes or b not in self.lnodes:
                    continue
                # Forward: a → b, minlen=0, weight=1000
                self.ledges.append(LayoutEdge(
                    edge=None, tail_name=a, head_name=b,
                    minlen=0, weight=1000, virtual=True,
                    constraint=True,
                ))
                # Backward: b → a, minlen=0, weight=1000
                self.ledges.append(LayoutEdge(
                    edge=None, tail_name=b, head_name=a,
                    minlen=0, weight=1000, virtual=True,
                    constraint=True,
                ))

    def _classify_flat_edges(self):
        """Post-ranking pass: mark same-rank edges as flat."""
        for le in self.ledges:
            if le.virtual:
                continue
            t = self.lnodes.get(le.tail_name)
            h = self.lnodes.get(le.head_name)
            if t and h and t.rank == h.rank:
                le.edge_type = "flat"

    def _classify_edges(self):
        """Classify edges by type for downstream processing.

        Sets ``le.edge_type`` on each LayoutEdge to one of:
        - ``'normal'`` — standard cross-rank edge
        - ``'flat'`` — same-rank edge (detected after ranking)
        - ``'reversed'`` — edge reversed by cycle breaking
        - ``'self'`` — self-loop

        This runs before ranking so types are preliminary; flat edges
        can only be fully detected after ranks are assigned.  A second
        pass runs after ranking to finalize flat-edge classification.

        Mirrors Graphviz ``class1.c:class1()`` (pre-rank) and
        ``class2.c:class2()`` (post-rank) classification.
        """
        for le in self.ledges:
            if le.virtual:
                le.edge_type = "virtual"
            elif le.tail_name == le.head_name:
                le.edge_type = "self"
            elif le.reversed:
                le.edge_type = "reversed"
            else:
                le.edge_type = "normal"

    def _cluster_aware_rank(self):
        """Rank nodes using recursive bottom-up cluster ranking.

        Mirrors Graphviz ``rank.c:dot1_rank()`` which recursively ranks
        each cluster bottom-up via ``collapse_sets()`` → ``collapse_cluster()``
        → ``dot1_rank(child)``.  Each cluster is ranked independently
        starting from the deepest leaves of the cluster tree, then the
        parent graph is ranked with cluster-internal edges replaced by
        min-length constraints between cluster boundary nodes.
        """
        if not self._clusters:
            self._network_simplex_rank()
            return

        # Build cluster hierarchy from the Graph's subgraph tree
        # so we can walk it bottom-up like the C code does.
        cl_by_name: dict[str, "LayoutCluster"] = {
            cl.name: cl for cl in self._clusters
        }
        cl_node_sets: dict[str, set[str]] = {
            cl.name: set(cl.nodes) for cl in self._clusters
        }

        # Determine parent-child relationships among clusters:
        # A cluster P is parent of C if C.nodes ⊂ P.nodes and P is the
        # smallest such containing cluster.
        children_of: dict[str | None, list[str]] = {None: []}
        for cl in self._clusters:
            children_of[cl.name] = []
        parent_of: dict[str, str | None] = {}
        for cl in self._clusters:
            best_parent: str | None = None
            best_size = float("inf")
            for other in self._clusters:
                if other.name == cl.name:
                    continue
                if cl_node_sets[cl.name] < cl_node_sets[other.name]:
                    if len(cl_node_sets[other.name]) < best_size:
                        best_parent = other.name
                        best_size = len(cl_node_sets[other.name])
            parent_of[cl.name] = best_parent
            children_of.setdefault(best_parent, []).append(cl.name)

        # Track which nodes have been ranked by a cluster pass
        ranked_nodes: set[str] = set()

        # ── Recursive bottom-up ranking (mirrors dot1_rank) ─────────
        def _dot1_rank_cluster(cl_name: str):
            """Rank a single cluster bottom-up: children first, then self.

            This mirrors the C code path:
              dot1_rank(g) → collapse_sets(g) → for each child cluster:
                collapse_cluster(g, child) → dot1_rank(child)
              then: class1 → decompose → acyclic → rank1 → expand_ranksets
            """
            # 1. Recursively rank all child clusters first (bottom-up)
            for child_name in children_of.get(cl_name, []):
                _dot1_rank_cluster(child_name)

            cl = cl_by_name[cl_name]
            cl_members = cl_node_sets[cl_name]

            # 2. Collect edges internal to this cluster that involve
            #    nodes NOT already locked by a child cluster ranking.
            #    For nodes ranked by children, we keep their relative
            #    ranks fixed and add constraint edges to anchor them.
            child_ranked = ranked_nodes & cl_members
            unranked = cl_members - ranked_nodes

            # All internal edges (both endpoints in this cluster)
            cl_edges: list[tuple[str, str, int, int]] = []
            for le in self.ledges:
                if not le.constraint:
                    continue
                if le.tail_name in cl_members and le.head_name in cl_members:
                    cl_edges.append((
                        le.tail_name, le.head_name, le.minlen, le.weight,
                    ))

            # If child clusters have already been ranked, anchor their
            # nodes with high-weight edges so NS preserves their relative
            # ranks while positioning them within the parent cluster.
            anchor_edges: list[tuple[str, str, int, int]] = []
            for child_name in children_of.get(cl_name, []):
                child_nodes_sorted = sorted(
                    (n for n in cl_by_name[child_name].nodes
                     if n in self.lnodes and n in ranked_nodes),
                    key=lambda n: self.lnodes[n].rank,
                )
                for i in range(len(child_nodes_sorted) - 1):
                    a, b = child_nodes_sorted[i], child_nodes_sorted[i + 1]
                    span = self.lnodes[b].rank - self.lnodes[a].rank
                    if span >= 1:
                        anchor_edges.append((a, b, span, 1000))

            all_edges = cl_edges + anchor_edges
            all_nodes = sorted(cl_members)

            if not all_nodes:
                return

            # 3. Run network simplex on this cluster
            ns = _NetworkSimplex(all_nodes, all_edges)
            ns.SEARCH_LIMIT = self.searchsize
            ranks = ns.solve(max_iter=self.nslimit1)

            # 4. Apply ranks to nodes
            for n, r in ranks.items():
                if n in self.lnodes:
                    self.lnodes[n].rank = r

            # 5. Mark all nodes in this cluster as ranked
            ranked_nodes.update(cl_members)

        # ── Walk the cluster tree: rank leaf clusters first ─────────
        # Process top-level clusters (those with no parent cluster).
        # Each one recursively processes its children first.
        top_level = children_of.get(None, [])
        for cl_name in top_level:
            _dot1_rank_cluster(cl_name)

        # ── UF_union collapse → global NS → expand ──────────
        # Mirrors C rank.c: cluster_leader() collapses each top-level
        # cluster to a single leader via UF_union.  class1/interclust1
        # converts inter-cluster edges using the "slack node + 2 edges"
        # pattern with offset-adjusted minlens.  rank1() runs global NS.
        # expand_ranksets() maps: rank(n) += rank(UF_find(n)).

        # 1. Build UF_find map: every node in a top-level cluster
        #    maps to that cluster's leader (min-rank node).
        top_clusters = children_of.get(None, [])
        uf_find: dict[str, str] = {}         # node → leader
        local_offset: dict[str, int] = {}    # node → rank offset from leader

        for cl_name in top_clusters:
            cl = cl_by_name[cl_name]
            members = [n for n in cl.nodes
                       if n in self.lnodes and n in ranked_nodes]
            if not members:
                continue
            members.sort(key=lambda n: self.lnodes[n].rank)
            leader = members[0]
            min_rank = self.lnodes[leader].rank
            for n in members:
                uf_find[n] = leader
                local_offset[n] = self.lnodes[n].rank - min_rank

        # 2. Build global NS graph.
        #    - Non-cluster nodes and leaders appear as themselves.
        #    - Intra-cluster edges (both endpoints → same leader) are skipped.
        #    - Inter-cluster/cross edges use interclust1 pattern:
        #      slack_node → UF_find(tail), slack_node → UF_find(head)
        #      with offset-adjusted minlens.
        _CL_BACK = 10  # C CL_BACK weight multiplier for tail side

        global_nodes: set[str] = set()
        for name in self.lnodes:
            global_nodes.add(uf_find.get(name, name))

        global_edges: list[tuple[str, str, int, int]] = []
        _vn_ctr = [0]

        for le in self.ledges:
            if not le.constraint:
                continue
            t, h = le.tail_name, le.head_name
            if t not in self.lnodes or h not in self.lnodes:
                continue

            t0 = uf_find.get(t, t)
            h0 = uf_find.get(h, h)

            if t0 == h0:
                continue  # intra-cluster

            t_in_cluster = t in uf_find
            h_in_cluster = h in uf_find

            if not t_in_cluster and not h_in_cluster:
                # Neither endpoint in a cluster — regular edge
                global_edges.append((t0, h0, le.minlen, le.weight))
            else:
                # At least one endpoint in a cluster — use interclust1
                # pattern: create slack node V with offset-adjusted edges
                t_rank = local_offset.get(t, 0)
                h_rank = local_offset.get(h, 0)
                offset = le.minlen + t_rank - h_rank
                if offset > 0:
                    t_len = 0
                    h_len = offset
                else:
                    t_len = -offset
                    h_len = 0

                _vn_ctr[0] += 1
                vn = f"_uf_v{_vn_ctr[0]}"
                global_nodes.add(vn)
                global_edges.append((vn, t0, t_len,
                                     _CL_BACK * le.weight))
                global_edges.append((vn, h0, h_len, le.weight))

        # 3. Run global NS (sorted for deterministic results —
        #    set iteration order varies with PYTHONHASHSEED)
        ns = _NetworkSimplex(sorted(global_nodes), global_edges)
        ns.SEARCH_LIMIT = self.searchsize
        ranks = ns.solve(max_iter=self.nslimit1)

        # 4. Re-normalize: C expand_ranksets iterates real nodes only
        #    (agfstnode), so slack nodes from interclust1 don't affect
        #    the rank floor.  Shift so min real/leader rank == 0.
        real_min = min(
            (ranks[uf_find.get(n, n)]
             for n in self.lnodes if uf_find.get(n, n) in ranks),
            default=0)
        if real_min != 0:
            ranks = {k: v - real_min for k, v in ranks.items()}

        # 5. Expand: rank(n) = rank(UF_find(n)) + local_offset(n)
        for name in self.lnodes:
            leader = uf_find.get(name, name)
            if leader in ranks:
                self.lnodes[name].rank = ranks[leader] + local_offset.get(name, 0)

    def _break_cycles(self):
        UNVISITED, IN_PROGRESS, DONE = 0, 1, 2
        state = {n: UNVISITED for n in self.lnodes}

        def dfs(u):
            state[u] = IN_PROGRESS
            for le in self.ledges:
                if le.tail_name != u:
                    continue
                v = le.head_name
                if state[v] == IN_PROGRESS:
                    le.reversed = True
                    le.tail_name, le.head_name = le.head_name, le.tail_name
                elif state[v] == UNVISITED:
                    dfs(v)
            state[u] = DONE

        for n in self.lnodes:
            if state[n] == UNVISITED:
                dfs(n)

    def _network_simplex_rank(self):
        if not self.lnodes:
            return
        # Build node group map for weight boosting
        node_groups: dict[str, str] = {}
        for name, ln in self.lnodes.items():
            if ln.node:
                grp = ln.node.attributes.get("group", "")
                if grp:
                    node_groups[name] = grp

        # Only edges with constraint=True affect ranking
        # Boost weight ×100 for edges connecting nodes in the same group
        ns_edges = []
        for le in self.ledges:
            if not le.constraint:
                continue
            w = le.weight
            t_grp = node_groups.get(le.tail_name, "")
            h_grp = node_groups.get(le.head_name, "")
            if t_grp and t_grp == h_grp:
                w = min(w * 100, 1000)
            ns_edges.append((le.tail_name, le.head_name, le.minlen, w))
        ns = _NetworkSimplex(list(self.lnodes.keys()), ns_edges)
        ns.SEARCH_LIMIT = self.searchsize
        ranks = ns.solve(max_iter=self.nslimit1)
        for name, r in ranks.items():
            if name in self.lnodes:
                self.lnodes[name].rank = r

    def _apply_rank_constraints(self):
        if not self._rank_constraints:
            return
        max_rank = max(ln.rank for ln in self.lnodes.values()) if self.lnodes else 0
        for kind, node_names in self._rank_constraints:
            existing = [self.lnodes[n] for n in node_names if n in self.lnodes]
            if not existing:
                continue
            if kind == "same":
                target = min(ln.rank for ln in existing)
                for ln in existing:
                    ln.rank = target
            elif kind in ("min", "source"):
                for ln in existing:
                    ln.rank = 0
            elif kind in ("max", "sink"):
                for ln in existing:
                    ln.rank = max_rank

    def _compact_ranks(self):
        if not self.lnodes:
            return
        min_rank = min(ln.rank for ln in self.lnodes.values())
        if min_rank != 0:
            for ln in self.lnodes.values():
                ln.rank -= min_rank

    def _add_virtual_nodes(self):
        """Insert virtual nodes for edges spanning multiple ranks."""
        self._vnode_chains = {}
        new_edges = []
        to_remove = []

        for i, le in enumerate(self.ledges):
            t_rank = self.lnodes[le.tail_name].rank
            h_rank = self.lnodes[le.head_name].rank
            span = h_rank - t_rank
            if span <= 1:
                continue  # No virtual nodes needed
            if span > 100:
                continue  # Too many virtual nodes, skip

            # Create chain of virtual nodes
            chain = []
            prev_name = le.tail_name
            for j in range(1, span):
                vname = f"_v_{le.tail_name}_{le.head_name}_{j}"
                # Ensure unique name
                while vname in self.lnodes:
                    vname += "_"
                self.lnodes[vname] = LayoutNode(
                    node=None, rank=t_rank + j, virtual=True,
                    width=2.0, height=2.0,
                )
                chain.append(vname)
                new_edges.append(LayoutEdge(
                    edge=None, tail_name=prev_name, head_name=vname,
                    minlen=1, weight=le.weight, virtual=True,
                    orig_tail=le.tail_name, orig_head=le.head_name,
                ))
                prev_name = vname

            # Final edge to head
            new_edges.append(LayoutEdge(
                edge=None, tail_name=prev_name, head_name=le.head_name,
                minlen=1, weight=le.weight, virtual=True,
                orig_tail=le.tail_name, orig_head=le.head_name,
            ))

            self._vnode_chains[(le.tail_name, le.head_name)] = chain
            to_remove.append(i)

        # Move original long edges to _chain_edges, add virtual edges to ledges
        for idx in sorted(to_remove, reverse=True):
            self._chain_edges.append(self.ledges.pop(idx))
        self.ledges.extend(new_edges)

    def _build_ranks(self):
        """Populate self.ranks with DFS-based initial ordering.

        Mirrors Graphviz ``init_mincross()`` / ``dfs_range()``: traverse
        from a root node following edges, assigning order within each
        rank based on DFS visit order.  This naturally groups connected
        components and clusters together, giving the mincross a better
        starting configuration than simple dict-order iteration.
        """
        self.ranks = defaultdict(list)

        # Build adjacency preserving edge list order (matching C's edge
        # traversal in decompose search_component).
        # C visits: flat_in, flat_out, in, out — in reverse edge order.
        # We approximate this: for each node, collect neighbors in the
        # order edges appear in self.ledges, then reverse (to match C's
        # reverse iteration with a LIFO stack).
        adj: dict[str, list[str]] = defaultdict(list)
        for le in self.ledges:
            adj[le.tail_name].append(le.head_name)
            adj[le.head_name].append(le.tail_name)
        # Reverse to match C's stack-based reverse iteration
        for k in adj:
            adj[k].reverse()

        visited: set[str] = set()

        # Use explicit stack to mirror C's search_component:
        # push neighbors in reverse order (C iterates edge list backward
        # and pushes, stack pops give forward order).
        def _dfs(start: str):
            if start in visited or start not in self.lnodes:
                return
            stack: list[str] = [start]
            while stack:
                name = stack.pop()
                if name in visited:
                    continue
                visited.add(name)
                self.ranks[self.lnodes[name].rank].append(name)
                # Push neighbors in reverse order so first neighbor
                # gets processed first (LIFO)
                nbrs = [n for n in adj.get(name, [])
                        if n in self.lnodes and n not in visited]
                for nbr in reversed(nbrs):
                    stack.append(nbr)

        # Start from nodes in DOT file order (matching C's agfstnode)
        # The graph.nodes dict preserves insertion order.
        dot_order_nodes: list[str] = []
        for name in self.graph.nodes:
            if name in self.lnodes:
                dot_order_nodes.append(name)
        # Also include virtual nodes (sorted by rank for consistency)
        virtual_nodes = [n for n in self.lnodes if n not in set(dot_order_nodes)]
        virtual_nodes.sort(key=lambda n: (self.lnodes[n].rank, n))
        for name in dot_order_nodes + virtual_nodes:
            _dfs(name)

        # Ensure all nodes are in ranks (disconnected nodes)
        for name, ln in self.lnodes.items():
            if name not in visited:
                self.ranks[ln.rank].append(name)

    # ── Phase 2: Crossing minimization ───────────

    _CL_CROSS = 1000  # Graphviz CL_CROSS: penalty weight for crossing cluster borders

    def _mark_low_clusters(self):
        """Label every node with its innermost cluster (C: mark_lowclusters).

        Largest clusters are processed first so that smaller (more
        deeply nested) clusters overwrite, leaving each node mapped to
        its innermost containing cluster.
        """
        self._node_to_cluster: dict[str, str | None] = {}
        if not self._clusters:
            return
        for cl in sorted(self._clusters,
                         key=lambda c: len(c.nodes), reverse=True):
            for n in cl.nodes:
                if n in self.lnodes:
                    self._node_to_cluster[n] = cl.name

    def _left2right(self, v: str, w: str) -> bool:
        """Return True if swapping v and w should be BLOCKED.

        Mirrors Graphviz ``left2right()`` in ``mincross.c``: nodes in
        different clusters must not be swapped during transpose, except
        when one is a virtual (skeleton) node.
        """
        v_ln = self.lnodes.get(v)
        w_ln = self.lnodes.get(w)
        if not v_ln or not w_ln:
            return False
        # Virtual / skeleton nodes can always be swapped
        if v_ln.virtual or w_ln.virtual:
            return False
        v_cl = self._node_to_cluster.get(v)
        w_cl = self._node_to_cluster.get(w)
        if v_cl == w_cl:
            return False
        # Both are real nodes in different clusters — block
        return True

    def _phase2_ordering(self):
        print(f"[TRACE order] phase2 begin: ordering={self.ordering}", file=sys.stderr)
        if not self.ranks:
            return

        for rank_nodes in self.ranks.values():
            for i, name in enumerate(rank_nodes):
                self.lnodes[name].order = i

        # Build innermost-cluster map (used by _left2right)
        self._mark_low_clusters()

        # ordering=out preserves input order — skip crossing minimization
        if self.ordering in ("out", "in"):
            print(f"[TRACE order] skip mincross: ordering={self.ordering}", file=sys.stderr)
            return

        # ── Skeleton-based cluster ordering ──────────────
        # Mirrors Graphviz class2 build_skeleton → init_mincross → mincross
        # → mincross_clust expand_cluster → mincross per cluster.
        if self._clusters:
            self._skeleton_mincross()
            # Final remincross on full expanded graph (C: mincross(g, 2))
            # C mincross.c:381-398: runs mincross on the fully expanded
            # graph with ReMincross=true.  Uses VAL with port.order from
            # real node record fields.
            if self.remincross:
                self._mark_low_clusters()
                self._remincross_full()
        else:
            self._run_mincross()

        crossings = self._count_all_crossings()
        print(f"[TRACE order] after mincross: crossings={crossings}", file=sys.stderr)

        # Enforce flat-edge ordering: tails left of heads
        self._flat_reorder()

        # Log final ordering (matching C format: name(order))
        for r in sorted(self.ranks.keys()):
            names = self.ranks[r]
            parts = []
            for n in names:
                if not self.lnodes[n].virtual:
                    parts.append(f"{n}({self.lnodes[n].order})")
            if parts:
                print(f"[TRACE order] rank {r}: {' '.join(parts)}", file=sys.stderr)

    def _run_mincross(self):
        """Run crossing minimization sweeps on the current rank arrays."""
        max_rank = max(self.ranks.keys()) if self.ranks else 0
        best_crossings = self._count_all_crossings()
        best_order = self._save_ordering()

        iterations = max(1, int(self.MAX_MINCROSS_ITER * self.mclimit))
        for _ in range(iterations):
            for r in range(1, max_rank + 1):
                if r in self.ranks:
                    self._order_by_weighted_median(r, r - 1)
                    self._transpose_rank(r)
            for r in range(max_rank - 1, -1, -1):
                if r in self.ranks:
                    self._order_by_weighted_median(r, r + 1)
                    self._transpose_rank(r)
            c = self._count_all_crossings()
            if c < best_crossings:
                best_crossings = c
                best_order = self._save_ordering()

        if self.remincross and best_crossings > 0:
            for _ in range(iterations):
                for r in range(1, max_rank + 1):
                    if r in self.ranks:
                        self._order_by_weighted_median(r, r - 1)
                        self._transpose_rank(r)
                for r in range(max_rank - 1, -1, -1):
                    if r in self.ranks:
                        self._order_by_weighted_median(r, r + 1)
                        self._transpose_rank(r)
                c = self._count_all_crossings()
                if c < best_crossings:
                    best_crossings = c
                    best_order = self._save_ordering()

        self._restore_ordering(best_order)

    def _remincross_full(self):
        """Final remincross on the fully expanded graph.

        Matches C mincross.c:381-398: mincross(g, 2) with ReMincross=true
        after all cluster expansion.  Uses _cluster_medians with VAL
        + port.order from Node.record_fields, and _cluster_reorder with
        the full reorder bubble sort.  Scoped fast graph covers all nodes.
        """
        all_nodes = set(self.lnodes.keys())
        max_rank = max(self.ranks.keys()) if self.ranks else 0
        min_rank = min(self.ranks.keys()) if self.ranks else 0

        # Build scoped fast graph for the full graph
        # (matching C class2 at root level, class2.c:155-282)
        fg_out: dict[str, list[str]] = defaultdict(list)
        fg_in: dict[str, list[str]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        # mark_clusters for ReMincross: left2right blocks ALL
        # cross-cluster swaps (mincross.c:612-613)
        node_cl: dict[str, str] = {}
        if self._clusters:
            for cl in sorted(self._clusters,
                             key=lambda c: len(c.nodes), reverse=True):
                for n in cl.nodes:
                    if n in self.lnodes:
                        node_cl[n] = cl.name  # innermost cluster

        for le in self.ledges:
            t, h = le.tail_name, le.head_name
            if t not in self.lnodes or h not in self.lnodes:
                continue
            if t == h:
                continue
            pair = (t, h)
            if pair not in seen:
                seen.add(pair)
                fg_out[t].append(h)
                fg_in[h].append(t)

        # C mincross.c:774-797 iteration loop
        max_iter = max(4, int(24 * self.mclimit))
        cur_cross = best_cross = self._count_all_crossings()
        best_order = self._save_ordering()
        _MIN_QUIT = 8
        _CONVERGENCE = 0.995
        trying = 0

        for _pass in range(max_iter):
            if cur_cross == 0:
                break
            if trying >= _MIN_QUIT:
                break
            trying += 1

            reverse = (_pass % 4) < 2
            if _pass % 2 == 0:
                for r in range(min_rank + 1, max_rank + 1):
                    if r in self.ranks:
                        self._cluster_medians(
                            r, r - 1, all_nodes, fg_out, fg_in)
                        self._cluster_reorder(
                            r, all_nodes, node_cl, reverse)
            else:
                for r in range(max_rank - 1, min_rank - 1, -1):
                    if r in self.ranks:
                        self._cluster_medians(
                            r, r + 1, all_nodes, fg_out, fg_in)
                        self._cluster_reorder(
                            r, all_nodes, node_cl, reverse)
            # Single transpose (mincross.c:1553)
            for r in range(min_rank, max_rank + 1):
                if r in self.ranks:
                    self._cluster_transpose(r, all_nodes, node_cl)

            cur_cross = self._count_all_crossings()
            if cur_cross <= best_cross:
                if cur_cross < _CONVERGENCE * best_cross:
                    trying = 0
                best_cross = cur_cross
                best_order = self._save_ordering()

        self._restore_ordering(best_order)

    def _skeleton_mincross(self):
        """Skeleton-based cluster ordering matching Graphviz mincross.

        1. Build skeleton: replace each top-level cluster with one virtual
           rank-leader node per rank it spans.
        2. Run mincross on the reduced graph.
        3. Expand: splice real cluster nodes at the skeleton position,
           run mincross within each cluster, recurse into children.
        4. Clean up skeleton nodes.
        """
        node_sets = {cl.name: set(cl.nodes) for cl in self._clusters}

        # Build parent map
        parent_of: dict[str, str | None] = {}
        for cl in self._clusters:
            best, best_sz = None, float("inf")
            for other in self._clusters:
                if other.name == cl.name:
                    continue
                if node_sets[cl.name] < node_sets[other.name]:
                    if len(node_sets[other.name]) < best_sz:
                        best, best_sz = other.name, len(node_sets[other.name])
            parent_of[cl.name] = best

        children_of: dict[str | None, list[str]] = {}
        for cn, par in parent_of.items():
            children_of.setdefault(par, []).append(cn)

        top_clusters = children_of.get(None, [])
        if not top_clusters:
            self._run_mincross()
            return

        cl_by_name = {cl.name: cl for cl in self._clusters}

        # ── Build skeletons for ALL clusters (all levels) ──
        skeleton_nodes: dict[str, dict[int, str]] = {}
        skeleton_edges: list[LayoutEdge] = []

        def _build_skeleton(cl_name: str):
            """Create rank-leader virtual nodes for a cluster."""
            cl_node_set = node_sets[cl_name]
            # Only use DIRECT nodes (not in child clusters)
            child_nodes: set[str] = set()
            for child in children_of.get(cl_name, []):
                child_nodes.update(node_sets[child])
            direct = cl_node_set - child_nodes

            cl_ranks = sorted(set(
                self.lnodes[n].rank for n in cl_node_set if n in self.lnodes
            ))
            if not cl_ranks:
                return

            rank_leaders: dict[int, str] = {}
            prev_leader = None
            for r in cl_ranks:
                vn_name = f"_skel_{cl_name}_{r}"
                vn = LayoutNode(node=None, rank=r, virtual=True,
                                width=4.0, height=4.0)
                self.lnodes[vn_name] = vn
                rank_leaders[r] = vn_name
                if prev_leader is not None:
                    se = LayoutEdge(
                        edge=None, tail_name=prev_leader, head_name=vn_name,
                        minlen=1, weight=self._CL_CROSS, virtual=True,
                    )
                    skeleton_edges.append(se)
                    self.ledges.append(se)
                prev_leader = vn_name
            skeleton_nodes[cl_name] = rank_leaders

            # Build child skeletons first (depth-first)
            for child in children_of.get(cl_name, []):
                _build_skeleton(child)

        for cl_name in top_clusters:
            _build_skeleton(cl_name)

        # ── Inter-cluster skeleton edges ──────────────────────
        # For each real edge crossing between child clusters of the same
        # parent, create a skeleton edge between the rank-leader nodes.
        # This gives the local mincross (during expand) something to work
        # with when ordering sibling cluster skeletons.
        #
        # Build a map: real node → innermost skeleton-owning cluster
        _node_skel_cluster: dict[str, str] = {}
        for cl_name in skeleton_nodes:
            for n in node_sets[cl_name]:
                if n in self.lnodes:
                    _node_skel_cluster[n] = cl_name  # last write = innermost

        _seen_skel_edges: set[tuple[str, str]] = set()
        for le in self.ledges:
            if le.virtual:
                continue
            t_cl = _node_skel_cluster.get(le.tail_name)
            h_cl = _node_skel_cluster.get(le.head_name)
            if not t_cl or not h_cl or t_cl == h_cl:
                continue
            # Find the sibling level: walk up until both share the same parent
            t_path: list[str] = [t_cl]
            cur = t_cl
            while parent_of.get(cur) is not None:
                cur = parent_of[cur]
                t_path.append(cur)
            h_path: list[str] = [h_cl]
            cur = h_cl
            while parent_of.get(cur) is not None:
                cur = parent_of[cur]
                h_path.append(cur)
            h_set = set(h_path)
            # Find sibling pair: for each parent, check if both are children
            for par_cl in t_path:
                if par_cl in h_set:
                    # par_cl is the common ancestor
                    # t_child = the child of par_cl on the tail side
                    t_child = t_path[max(0, t_path.index(par_cl) - 1)]
                    h_child = h_path[max(0, h_path.index(par_cl) - 1)]
                    if t_child == par_cl or h_child == par_cl:
                        break  # one is a direct node of par_cl, not a child cluster
                    if t_child == h_child:
                        break  # same child cluster
                    # Create inter-cluster edge chain between rank-leaders.
                    # Mirrors C class2.c:99-124 interclrep() → make_chain():
                    # instead of a direct edge from t_skel to h_skel,
                    # create a chain of virtual nodes at intermediate ranks
                    # so the BFS visits all ranks between the endpoints.
                    t_rank = self.lnodes[le.tail_name].rank
                    h_rank = self.lnodes[le.head_name].rank
                    t_skel = skeleton_nodes.get(t_child, {}).get(t_rank)
                    h_skel = skeleton_nodes.get(h_child, {}).get(h_rank)
                    if t_skel and h_skel and t_rank != h_rank:
                        # Ensure t_rank < h_rank (C interclrep:106-108)
                        if t_rank > h_rank:
                            t_skel, h_skel = h_skel, t_skel
                            t_rank, h_rank = h_rank, t_rank
                        key = (t_skel, h_skel)
                        if key not in _seen_skel_edges:
                            _seen_skel_edges.add(key)
                            # C class2.c:70-96 make_chain(): create chain
                            # from→v1→v2→...→to with virtual nodes at
                            # each intermediate rank.
                            prev_name = t_skel
                            for cr in range(t_rank + 1, h_rank + 1):
                                if cr < h_rank:
                                    # Intermediate virtual node
                                    # (C class2.c:87 plain_vnode)
                                    cvn = f"_icv_{t_skel}_{h_skel}_{cr}"
                                    self.lnodes[cvn] = LayoutNode(
                                        node=None, rank=cr, virtual=True,
                                        width=2.0, height=2.0)
                                    next_name = cvn
                                else:
                                    next_name = h_skel
                                ce = LayoutEdge(
                                    edge=None, tail_name=prev_name,
                                    head_name=next_name,
                                    minlen=1, weight=le.weight,
                                    virtual=True)
                                skeleton_edges.append(ce)
                                self.ledges.append(ce)
                                prev_name = next_name
                    elif t_skel and h_skel and t_rank == h_rank:
                        # Same rank: C interclrep:114-115 skips same-rank
                        # inter-cluster edges.  No edge created.
                        pass
                    break

        # ── Collapse: replace clusters with skeletons, top-down ──
        # For each cluster (deepest first), hide its direct nodes and
        # child skeleton nodes, replace with this cluster's skeleton.
        # Process deepest children first so their skeletons are in place
        # before the parent collapses.

        # Compute depth for ordering
        depth_of: dict[str, int] = {}
        for cl_name in skeleton_nodes:
            d, cur = 0, cl_name
            while parent_of.get(cur) is not None:
                d += 1
                cur = parent_of[cur]
            depth_of[cl_name] = d
        max_depth = max(depth_of.values()) if depth_of else 0

        # Track which nodes are currently visible (not hidden)
        hidden_by: dict[str, str] = {}  # node_name → cl_name that hid it

        # Collapse from deepest to shallowest
        for d in range(max_depth, -1, -1):
            for cl_name, rank_leaders in skeleton_nodes.items():
                if depth_of.get(cl_name, 0) != d:
                    continue

                # Nodes to hide: direct nodes + child cluster skeletons
                cl_node_set = node_sets[cl_name]
                child_skel_nodes: set[str] = set()
                for child in children_of.get(cl_name, []):
                    if child in skeleton_nodes:
                        child_skel_nodes.update(skeleton_nodes[child].values())

                to_hide = set()
                for n in cl_node_set:
                    if n in self.lnodes and n not in hidden_by:
                        to_hide.add(n)
                to_hide.update(n for n in child_skel_nodes if n not in hidden_by)

                for r in sorted(rank_leaders.keys()):
                    rank_list = self.ranks.get(r, [])
                    new_rank = []
                    skel_inserted = False
                    for name in rank_list:
                        if name in to_hide:
                            hidden_by[name] = cl_name
                            if not skel_inserted:
                                new_rank.append(rank_leaders[r])
                                skel_inserted = True
                        else:
                            new_rank.append(name)
                    if not skel_inserted and r in rank_leaders:
                        new_rank.append(rank_leaders[r])
                    self.ranks[r] = new_rank
                    for i, name in enumerate(self.ranks[r]):
                        self.lnodes[name].order = i

        # ── Run mincross on fully collapsed graph ──
        self._run_mincross()

        # Trace skeleton ordering (just skeleton node positions)
        for r in sorted(self.ranks.keys()):
            skel_parts = []
            for n in self.ranks[r]:
                if n.startswith("_skel_"):
                    skel_parts.append(n)
            if skel_parts:
                print(f"[TRACE order] skeleton rank {r}: {skel_parts}", file=sys.stderr)

        # ── Expand: DFS through cluster tree ──
        # C mincross.c:574-598 mincross_clust recurses depth-first
        # through the cluster tree in GD_clust (definition) order:
        #   mincross_clust(g):
        #     expand_cluster(g); mincross(g, 2);
        #     for c in GD_clust(g): mincross_clust(c)
        # This is different from BFS by depth — for each cluster, we
        # fully recurse into all its children before moving to the
        # next sibling.  Mixing up this order changes what's visible
        # as a skeleton vs a real node at mincross time, and changes
        # the median/reorder results.
        cluster_dfs_order: list[str] = []
        def _dfs_cluster_order(parent: str | None):
            for child in children_of.get(parent, []):
                if child in skeleton_nodes:
                    cluster_dfs_order.append(child)
                    _dfs_cluster_order(child)
        _dfs_cluster_order(None)

        for cl_name in cluster_dfs_order:
            if True:  # preserve existing indentation
                rank_leaders = skeleton_nodes[cl_name]

                # Collect nodes hidden by this cluster
                cl_hidden = {n for n, hider in hidden_by.items()
                             if hider == cl_name and n in self.lnodes}

                # Collect virtual nodes that participate in this cluster's
                # BFS.  In C, the cluster subgraph contains virtual nodes
                # from edge splitting AND inter-cluster chain nodes from
                # interclrep/make_chain (class2.c:70-96).
                cl_member_set = node_sets[cl_name]
                cl_virtual: set[str] = set()
                cl_min_r = min(rank_leaders.keys())
                cl_max_r = max(rank_leaders.keys())
                for vname, vln in self.lnodes.items():
                    if not vln.virtual:
                        continue
                    if vln.rank < cl_min_r or vln.rank > cl_max_r:
                        continue
                    # Include inter-cluster chain nodes (_icv_*) created
                    # by interclrep make_chain (C class2.c:70-96)
                    if vname.startswith("_icv_"):
                        cl_virtual.add(vname)
                        continue
                    # Include virtual nodes from edge splitting whose
                    # chain connects two cluster members
                    for le in self.ledges:
                        if le.tail_name == vname or le.head_name == vname:
                            ot = getattr(le, 'orig_tail', None)
                            oh = getattr(le, 'orig_head', None)
                            if ot and oh and ot in cl_member_set and oh in cl_member_set:
                                cl_virtual.add(vname)
                                break

                # Child skeleton nodes
                child_skel_set: set[str] = set()
                child_skel_ranks: dict[str, dict[int, str]] = {}
                for child in children_of.get(cl_name, []):
                    if child in skeleton_nodes:
                        child_skel_ranks[child] = skeleton_nodes[child]
                        for sn in skeleton_nodes[child].values():
                            child_skel_set.add(sn)

                # BFS over hidden + virtual + child skeleton nodes
                bfs_nodes = cl_hidden | cl_virtual | child_skel_set
                bfs_order, cl_fg_out, cl_fg_in = self._cluster_build_ranks(
                    bfs_nodes, child_skel_set, child_skel_ranks,
                    node_sets)

                # Splice BFS-ordered nodes at skeleton positions.
                # Virtual nodes that were already in self.ranks at
                # their positions need to be removed first then
                # re-inserted in BFS order.
                for r, skel_name in rank_leaders.items():
                    rank_list = self.ranks.get(r, [])
                    try:
                        skel_pos = rank_list.index(skel_name)
                    except ValueError:
                        continue

                    # Remove virtual nodes that will be re-placed by BFS.
                    # Sort for deterministic removal order (cl_virtual is a set).
                    virt_at_r = sorted(n for n in cl_virtual
                                       if n in self.lnodes
                                       and self.lnodes[n].rank == r)
                    for vn in virt_at_r:
                        if vn in rank_list:
                            idx = rank_list.index(vn)
                            rank_list.pop(idx)
                            if idx < skel_pos:
                                skel_pos -= 1

                    # Get BFS-ordered nodes for this rank, filter to
                    # correct rank
                    restore = [n for n in bfs_order.get(r, [])
                               if n in self.lnodes
                               and self.lnodes[n].rank == r]
                    if restore:
                        rank_list[skel_pos:skel_pos + 1] = restore
                    else:
                        rank_list.pop(skel_pos)
                    self.ranks[r] = rank_list
                    for i, name in enumerate(rank_list):
                        self.lnodes[name].order = i

                # Un-hide these nodes
                for n in list(hidden_by):
                    if hidden_by[n] == cl_name:
                        del hidden_by[n]

                # Trace expand ordering (matching C format)
                print(f"[TRACE order] expand_cluster {cl_name}: after build_ranks", file=sys.stderr)
                for r2 in sorted(rank_leaders.keys()):
                    parts = []
                    for n in self.ranks.get(r2, []):
                        if n in child_skel_set:
                            # Find which child cluster this skeleton represents
                            for ch, rls in child_skel_ranks.items():
                                if n in rls.values():
                                    parts.append(f"[CL:{ch}]")
                                    break
                        elif n in self.lnodes and not self.lnodes[n].virtual:
                            if n in node_sets.get(cl_name, set()):
                                parts.append(n)
                    if parts:
                        print(f"[TRACE order]   rank {r2}: {' '.join(parts)}", file=sys.stderr)

                # Local mincross within this cluster.
                # Include child skeleton nodes that haven't been expanded
                # yet — they stand in for the child clusters and carry
                # inter-cluster edges needed by the median heuristic.
                cl_node_set = set(node_sets[cl_name])
                for child in children_of.get(cl_name, []):
                    if child in skeleton_nodes:
                        for sn in skeleton_nodes[child].values():
                            if sn in self.lnodes:
                                cl_node_set.add(sn)
                cl_ranks = sorted(set(
                    self.lnodes[n].rank for n in cl_node_set
                    if n in self.lnodes
                ))
                if len(cl_ranks) >= 2:
                    min_r, max_r = min(cl_ranks), max(cl_ranks)

                    # Build child-cluster map matching C's mark_clusters:
                    # each node maps to its top-level child cluster within
                    # cl_name.  Skeleton nodes are NOT mapped (they can be
                    # swapped freely — matching C left2right exception for
                    # CLUSTER+VIRTUAL nodes).
                    child_cl_map: dict[str, str] = {}
                    for child in children_of.get(cl_name, []):
                        for n in node_sets.get(child, set()):
                            if n in cl_node_set:
                                child_cl_map[n] = child

                    max_iter = max(4, int(24 * self.mclimit))

                    # Build post-expansion scoped fast graph for real
                    # nodes, matching C class2 inside expand_cluster
                    # (cluster.c:282,298 → class2.c:155-282).
                    # Includes edges where both endpoints are in
                    # cl_node_set.  Excludes intra-child-cluster edges.
                    mc_fg_out: dict[str, list[str]] = defaultdict(list)
                    mc_fg_in: dict[str, list[str]] = defaultdict(list)
                    mc_seen: set[tuple[str, str]] = set()
                    for le in self.ledges:
                        t, h = le.tail_name, le.head_name
                        if t not in cl_node_set and h not in cl_node_set:
                            continue
                        if t not in self.lnodes or h not in self.lnodes:
                            continue
                        t_in = t in cl_node_set
                        h_in = h in cl_node_set
                        if not t_in and not h_in:
                            continue
                        # Include virtual nodes within rank range
                        if not t_in or not h_in:
                            t_r = self.lnodes[t].rank
                            h_r = self.lnodes[h].rank
                            if t_r < min_r or t_r > max_r:
                                continue
                            if h_r < min_r or h_r > max_r:
                                continue
                        if t == h:
                            continue  # class2.c:226
                        # Exclude intra-child-cluster (class2.c:199)
                        t_ch = child_cl_map.get(t)
                        h_ch = child_cl_map.get(h)
                        if t_ch and h_ch and t_ch == h_ch:
                            continue
                        pair = (t, h)
                        if pair not in mc_seen:
                            mc_seen.add(pair)
                            mc_fg_out[t].append(h)
                            mc_fg_in[h].append(t)

                    # C ncross() (mincross.c:1617) uses ND_out which is
                    # the cluster's scoped fast graph — intra-child-cluster
                    # edges are excluded (class2.c:199).  We emulate this
                    # by counting only edges in mc_fg_out.
                    def _scoped_cross():
                        return self._count_scoped_crossings(
                            mc_fg_out, min_r, max_r)
                    cur_cross = best_cross = _scoped_cross()
                    best_order = self._save_ordering()

                    # C mincross.c:774-797: iteration loop.
                    _MIN_QUIT = 8       # mincross.c:1820
                    _CONVERGENCE = 0.995  # mincross.c:159
                    trying = 0

                    # C mincross_step (mincross.c:1534-1546):
                    # down pass: first = GD_minrank(g) + 1, but for
                    # sub-clusters (GD_minrank(g) > GD_minrank(Root)),
                    # first-- (so it includes the cluster's first rank).
                    # up pass: symmetric with GD_maxrank(g).
                    # Root's min rank for this graph.
                    root_min = min(self.ranks.keys()) if self.ranks else 0
                    root_max = max(self.ranks.keys()) if self.ranks else 0
                    down_first = min_r + 1
                    if min_r > root_min:
                        down_first = min_r
                    up_first = max_r - 1
                    if max_r < root_max:
                        up_first = max_r

                    for _pass in range(max_iter):
                        if cur_cross == 0:
                            break
                        if trying >= _MIN_QUIT:
                            break
                        trying += 1

                        # mincross_step (mincross.c:1528-1554)
                        reverse = (_pass % 4) < 2
                        if _pass % 2 == 0:
                            for r in range(down_first, max_r + 1):
                                if r in self.ranks:
                                    self._cluster_medians(
                                        r, r - 1, cl_node_set,
                                        mc_fg_out, mc_fg_in)
                                    self._cluster_reorder(
                                        r, cl_node_set, child_cl_map,
                                        reverse)
                        else:
                            for r in range(up_first, min_r - 1, -1):
                                if r in self.ranks:
                                    self._cluster_medians(
                                        r, r + 1, cl_node_set,
                                        mc_fg_out, mc_fg_in)
                                    self._cluster_reorder(
                                        r, cl_node_set, child_cl_map,
                                        reverse)
                        for r in range(min_r, max_r + 1):
                            if r in self.ranks:
                                self._cluster_transpose(
                                    r, cl_node_set, child_cl_map)

                        # mincross.c:786-791: check improvement using scoped count
                        cur_cross = _scoped_cross()
                        if cur_cross <= best_cross:
                            if cur_cross < _CONVERGENCE * best_cross:
                                trying = 0
                            best_cross = cur_cross
                            best_order = self._save_ordering()

                    self._restore_ordering(best_order)

        # ── Clean up skeleton nodes, chain nodes, and edges ──
        for cl_name, rank_leaders in skeleton_nodes.items():
            for r, skel_name in rank_leaders.items():
                if r in self.ranks and skel_name in self.ranks[r]:
                    self.ranks[r].remove(skel_name)
                self.lnodes.pop(skel_name, None)

        # Remove inter-cluster chain virtual nodes (_icv_* from
        # interclrep make_chain, C class2.c:70-96)
        icv_names = [n for n in self.lnodes if n.startswith("_icv_")]
        for n in icv_names:
            for r in self.ranks.values():
                if n in r:
                    r.remove(n)
            del self.lnodes[n]

        skel_edge_set = set(id(se) for se in skeleton_edges)
        self.ledges = [le for le in self.ledges if id(le) not in skel_edge_set]

        for r, rank_nodes in self.ranks.items():
            for i, name in enumerate(rank_nodes):
                if name in self.lnodes:
                    self.lnodes[name].order = i

    def _flat_reorder(self):
        """Enforce left-to-right ordering for flat (same-rank) edges.

        For each rank, flat edges with weight > 0 establish an ordering
        constraint: tail must be left of head.  This is implemented as
        a topological sort on the flat-edge graph within each rank.
        Mirrors Graphviz ``mincross.c:flat_reorder()``.
        """
        # Collect flat edges per rank
        flat_by_rank: dict[int, list[tuple[str, str]]] = {}
        for le in self.ledges:
            if le.virtual:
                continue
            t = self.lnodes.get(le.tail_name)
            h = self.lnodes.get(le.head_name)
            if t and h and t.rank == h.rank and le.weight > 0:
                flat_by_rank.setdefault(t.rank, []).append(
                    (le.tail_name, le.head_name))

        for rank_val, flat_edges in flat_by_rank.items():
            rank_nodes = self.ranks.get(rank_val)
            if not rank_nodes or len(rank_nodes) < 2:
                continue

            # Build adjacency for topological sort
            in_degree: dict[str, int] = {}
            adj: dict[str, list[str]] = {}
            rank_set = set(rank_nodes)
            for t, h in flat_edges:
                if t not in rank_set or h not in rank_set:
                    continue
                adj.setdefault(t, []).append(h)
                in_degree[h] = in_degree.get(h, 0) + 1
                in_degree.setdefault(t, in_degree.get(t, 0))

            # Nodes with flat-edge constraints
            constrained = set(in_degree.keys())
            if not constrained:
                continue

            # Topological sort (Kahn's algorithm) on constrained nodes
            queue = [n for n in rank_nodes if n in constrained
                     and in_degree.get(n, 0) == 0]
            topo_order: list[str] = []
            while queue:
                u = queue.pop(0)
                topo_order.append(u)
                for v in adj.get(u, []):
                    in_degree[v] -= 1
                    if in_degree[v] == 0:
                        queue.append(v)

            if len(topo_order) != len(constrained):
                # Cycle in flat edges — skip (cycle should have been
                # broken by _break_cycles, but flat edges may create new
                # cycles if they were added after cycle breaking)
                continue

            # Merge: constrained nodes in topo order, unconstrained keep
            # their relative positions
            unconstrained = [n for n in rank_nodes if n not in constrained]
            # Interleave: place constrained nodes at their original
            # positions, preserving unconstrained order
            new_order: list[str] = []
            ci = 0  # index into topo_order
            for n in rank_nodes:
                if n in constrained:
                    new_order.append(topo_order[ci])
                    ci += 1
                else:
                    new_order.append(n)

            for i, name in enumerate(new_order):
                self.lnodes[name].order = i
            self.ranks[rank_val] = new_order

    def _cluster_group_ordering(self):
        """Reorder nodes within each rank so that cluster members are contiguous.

        Assigns each cluster a fixed slot index via DFS of the cluster tree.
        Nodes are sorted by their cluster's slot, keeping the entire cluster
        hierarchy grouped.
        """
        if not self._clusters:
            return

        node_sets = {cl.name: set(cl.nodes) for cl in self._clusters}

        # Build parent map
        parent_of: dict[str, str | None] = {}
        for cl in self._clusters:
            best_parent = None
            best_size = float("inf")
            for other in self._clusters:
                if other.name == cl.name:
                    continue
                if node_sets[cl.name] < node_sets[other.name]:
                    if len(node_sets[other.name]) < best_size:
                        best_parent = other.name
                        best_size = len(node_sets[other.name])
            parent_of[cl.name] = best_parent

        children_of: dict[str | None, list[str]] = {}
        for cl_name, par in parent_of.items():
            children_of.setdefault(par, []).append(cl_name)

        # DFS to assign a fixed slot index to each cluster.
        # Sibling order: sort by the median rank of their nodes so that
        # clusters with lower-ranked nodes come first.
        cluster_slot: dict[str, int] = {}
        slot_counter = [0]

        def assign_slots(parent: str | None):
            kids = children_of.get(parent, [])
            # Sort siblings by median rank of their nodes
            def median_rank(cl_name):
                ranks = [self.lnodes[n].rank for n in node_sets.get(cl_name, set())
                         if n in self.lnodes]
                if not ranks:
                    return 0
                ranks.sort()
                return ranks[len(ranks) // 2]
            kids.sort(key=median_rank)
            for kid in kids:
                cluster_slot[kid] = slot_counter[0]
                slot_counter[0] += 1
                assign_slots(kid)

        assign_slots(None)

        # Map each node to its innermost (smallest) cluster
        sorted_cls = sorted(self._clusters, key=lambda c: len(c.nodes), reverse=True)
        node_cluster: dict[str, str] = {}
        for cl in sorted_cls:
            for n in cl.nodes:
                if n in self.lnodes:
                    node_cluster[n] = cl.name

        # Reorder each rank
        for rank_val, rank_nodes in self.ranks.items():
            if len(rank_nodes) < 2:
                continue

            def sort_key(name):
                cl = node_cluster.get(name, "")
                slot = cluster_slot.get(cl, 999999)
                return (slot, self.lnodes[name].order)

            rank_nodes.sort(key=sort_key)
            for i, name in enumerate(rank_nodes):
                self.lnodes[name].order = i
            self.ranks[rank_val] = rank_nodes


    # Dead code removed: _mincross_within_clusters and _cluster_median_order.
    # Cluster-level mincross is now handled inline in _skeleton_mincross
    # expand section using _cluster_medians + _cluster_reorder +
    # _cluster_transpose with scoped fast graph edges
    # (matching C mincross.c:574-598 mincross_clust).
    # _cluster_median_order replaced by _cluster_medians (mincross.c:1687)
    # + _cluster_reorder (mincross.c:1476).

    # ── Per-node mval storage for medians/reorder ──────────
    _node_mval: dict[str, float] = {}
    _MC_SCALE = 256  # C const.h:99 — scale factor for VAL() macro
    _port_order_cache: dict[tuple[str, str], int] = {}

    def _mval(self, node_name: str, port_order: int = 128) -> int:
        """C mincross.c:1685 VAL(node, port).
        Returns MC_SCALE * ND_order(node) + port.order.
        Default port_order=128 (MC_SCALE/2) for center port
        (C shapes.c:2865)."""
        if node_name in self.lnodes:
            return self._MC_SCALE * self.lnodes[node_name].order + port_order
        return 0

    def _mval_edge(self, node_name: str, port_name: str) -> int:
        """VAL(node, port) with port.order from Node.record_fields.

        Matches C mincross.c:1685 VAL() + sameport.c:151-152:
          port.order = MC_SCALE * (lw + port.x) / (lw + rw)

        The port fraction comes from Node.record_fields (parsed at
        DOT load time, sized by RecordField.compute_size/positions).
        Node is the single source of truth for port geometry.
        """
        if node_name not in self.lnodes:
            return 0
        ln = self.lnodes[node_name]
        order = ln.order

        if not port_name:
            # C: edges without explicit ports have ED_port.order = 0
            # (the port struct is zero-initialized).  Only edges that
            # go through resolvePort/sameport get nonzero port.order.
            # C shapes.c:2865 sets pp->order = MC_SCALE/2 for
            # NORMAL shapes, but virtual/skeleton edges keep 0.
            return self._MC_SCALE * order

        cache_key = (node_name, port_name)
        if cache_key in self._port_order_cache:
            return self._MC_SCALE * order + self._port_order_cache[cache_key]

        # Look up port fraction from Node.record_fields
        # (parsed at DOT load, sized at layout start)
        port_order = self._MC_SCALE // 2  # default center
        if ln.node and ln.node.record_fields is not None:
            frac = ln.node.record_fields.port_fraction(
                port_name, rankdir=self._rankdir_int())
            if frac is not None:
                port_order = int(frac * self._MC_SCALE)

        self._port_order_cache[cache_key] = port_order
        return self._MC_SCALE * order + port_order

    # _port_order_from_label and _split_record_fields removed �
    # port.order now comes from Node.record_fields.port_fraction()
    # (ANTLR4 RecordParser, sized at layout start).


    def _cluster_medians(self, rank: int, adj_rank: int,
                          cl_nodes: set[str],
                          fg_out: dict | None = None,
                          fg_in: dict | None = None):
        """Compute median values for nodes at rank.

        Mirrors C mincross.c:1687-1743 medians().
        Uses VAL(node, port) = MC_SCALE * order + port.order
        (mincross.c:1685, sameport.c:151-152) for neighbor positions.
        Stores results in self._node_mval[name].
        """
        rank_nodes = self.ranks.get(rank, [])
        adj_set = set(self.ranks.get(adj_rank, []))

        # Build port lookup for edges: (tail, head) → (headport, tailport)
        # Used to compute VAL with port.order (C mincross.c:1702,1706)
        if not hasattr(self, '_edge_port_lookup'):
            self._edge_port_lookup: dict[tuple[str, str], tuple[str, str]] = {}
            for le in self.ledges:
                hp = getattr(le, 'headport', '') or ''
                tp = getattr(le, 'tailport', '') or ''
                # Strip compass suffix (e.g., "Out0:n" → "Out0")
                if ':' in hp:
                    hp = hp.split(':')[0]
                if ':' in tp:
                    tp = tp.split(':')[0]
                self._edge_port_lookup[(le.tail_name, le.head_name)] = (hp, tp)

        for name in rank_nodes:
            if name not in cl_nodes:
                self._node_mval[name] = -1.0
                continue

            positions = []
            if fg_out is not None and fg_in is not None:
                # Fast graph edges (C ND_out/ND_in)
                # Use VAL(node, port) (mincross.c:1702,1706)
                if adj_rank > rank:
                    # Down: VAL(aghead(e), ED_head_port(e))
                    for nbr in fg_out.get(name, []):
                        if nbr in adj_set:
                            hp, _ = self._edge_port_lookup.get(
                                (name, nbr), ('', ''))
                            positions.append(self._mval_edge(nbr, hp))
                else:
                    # Up: VAL(agtail(e), ED_tail_port(e))
                    for nbr in fg_in.get(name, []):
                        if nbr in adj_set:
                            _, tp = self._edge_port_lookup.get(
                                (nbr, name), ('', ''))
                            positions.append(self._mval_edge(nbr, tp))
            else:
                for le in self.ledges:
                    if le.tail_name == name and le.head_name in adj_set:
                        hp = getattr(le, 'headport', '') or ''
                        if ':' in hp:
                            hp = hp.split(':')[0]
                        positions.append(self._mval_edge(le.head_name, hp))
                    elif le.head_name == name and le.tail_name in adj_set:
                        tp = getattr(le, 'tailport', '') or ''
                        if ':' in tp:
                            tp = tp.split(':')[0]
                        positions.append(self._mval_edge(le.tail_name, tp))

            # C mincross.c:1708-1735
            if not positions:
                self._node_mval[name] = -1.0
            elif len(positions) == 1:
                self._node_mval[name] = float(positions[0])
            elif len(positions) == 2:
                self._node_mval[name] = (positions[0] + positions[1]) / 2.0
            else:
                positions.sort()
                m = len(positions) // 2
                if len(positions) % 2:
                    self._node_mval[name] = float(positions[m])
                else:
                    lm = m - 1
                    rspan = positions[-1] - positions[m]
                    lspan = positions[lm] - positions[0]
                    if lspan == rspan:
                        self._node_mval[name] = (positions[lm] + positions[m]) / 2.0
                    elif lspan + rspan > 0:
                        self._node_mval[name] = (
                            positions[lm] * rspan + positions[m] * lspan
                        ) / (lspan + rspan)
                    else:
                        self._node_mval[name] = (positions[lm] + positions[m]) / 2.0

        # Trace median values + VAL details for specific ranks
        # Capture both skeleton level (>10 nodes) and child level (<10)
        _trace_names = {'c4118', 'c4145', 'c4147', 'c4051', 'c4139', 'c4138',
                        'c4143', 'c4146', 'c4236', 'c4243'}
        _has_trace_nodes = any(n in _trace_names for n in self.ranks.get(rank, []))
        if _has_trace_nodes and rank in (1, 2, 3, 4, 5, 6):
            parts = []
            for name in self.ranks.get(rank, []):
                if name in cl_nodes:
                    v = "v" if (name in self.lnodes and self.lnodes[name].virtual) else ""
                    parts.append(f"{name}{v}={self._node_mval.get(name, -9):.1f}")
            print(f"[TRACE median] rank {rank} (adj {adj_rank}): {' '.join(parts)}", file=sys.stderr)
            # Trace per-node neighbor VAL details
            adj_s = set(self.ranks.get(adj_rank, []))
            for name in self.ranks.get(rank, []):
                if name not in cl_nodes:
                    continue
                nbr_parts = []
                if fg_out is not None and fg_in is not None:
                    edge_list = fg_out.get(name, []) if adj_rank > rank else (fg_in or {}).get(name, [])
                    for nbr in edge_list:
                        if nbr in adj_s:
                            if adj_rank > rank:
                                hp, _ = self._edge_port_lookup.get((name, nbr), ('', ''))
                                val = self._mval_edge(nbr, hp)
                                po = self._port_order_cache.get((nbr, hp), 128)
                            else:
                                _, tp = self._edge_port_lookup.get((nbr, name), ('', ''))
                                val = self._mval_edge(nbr, tp)
                                po = self._port_order_cache.get((nbr, tp), 128)
                            nbr_parts.append(f"{nbr}(ord={self.lnodes[nbr].order},port={po},val={val})")
                else:
                    for le in self.ledges:
                        nbr = None
                        if le.tail_name == name and le.head_name in adj_s:
                            nbr = le.head_name
                            hp = (getattr(le, 'headport', '') or '').split(':')[0]
                            val = self._mval_edge(nbr, hp)
                            po = self._port_order_cache.get((nbr, hp), 128)
                        elif le.head_name == name and le.tail_name in adj_s:
                            nbr = le.tail_name
                            tp = (getattr(le, 'tailport', '') or '').split(':')[0]
                            val = self._mval_edge(nbr, tp)
                            po = self._port_order_cache.get((nbr, tp), 128)
                        if nbr:
                            nbr_parts.append(f"{nbr}(ord={self.lnodes[nbr].order},port={po},val={val})")
                if nbr_parts:
                    print(f"[TRACE median]   {name} adj_nbrs: {' '.join(nbr_parts)}", file=sys.stderr)

    def _cluster_reorder(self, rank: int, cl_nodes: set[str],
                          child_cl_map: dict[str, str] | None = None,
                          reverse: bool = False):
        """Bubble-sort reorder matching C mincross.c:1476-1526 reorder().

        Compares nodes by mval (from _cluster_medians).  Skips nodes
        with mval < 0 (no neighbors).  Respects left2right (blocks
        swaps between different child clusters).  The sawclust logic
        allows jumping over a single cluster group.
        """
        nodes = self.ranks.get(rank, [])
        n = len(nodes)
        if n < 2:
            return

        mval = self._node_mval
        ep = n  # shrinking endpoint (C: ep = vlist + n)

        for nelt in range(n - 1, -1, -1):  # C: nelt = n-1 downto 0
            li = 0
            while li < ep:
                # Find leftmost with mval >= 0 (C: mincross.c:1486)
                while li < ep and mval.get(nodes[li], -1) < 0:
                    li += 1
                if li >= ep:
                    break

                # Find right comparison partner (C: mincross.c:1493)
                sawclust = False
                muststay = False
                ri = li + 1
                while ri < ep:
                    rn = nodes[ri]
                    # sawclust: skip consecutive cluster nodes
                    # (C mincross.c:1494-1495)
                    r_cl = (child_cl_map or {}).get(rn)
                    if sawclust and r_cl:
                        ri += 1
                        continue
                    # left2right check (C mincross.c:1496-1498)
                    l_cl = (child_cl_map or {}).get(nodes[li])
                    if l_cl and r_cl and l_cl != r_cl:
                        # Check if either is virtual/skeleton (can swap)
                        lv = nodes[li] in self.lnodes and self.lnodes[nodes[li]].virtual
                        rv = rn in self.lnodes and self.lnodes[rn].virtual
                        if not lv and not rv:
                            muststay = True
                            break
                    # Found node with mval >= 0 (C mincross.c:1500)
                    if mval.get(rn, -1) >= 0:
                        break
                    # Mark cluster encounter (C mincross.c:1502-1503)
                    if r_cl:
                        sawclust = True
                    ri += 1

                if ri >= ep:
                    break

                if not muststay:
                    p1 = mval.get(nodes[li], -1)
                    p2 = mval.get(nodes[ri], -1)
                    # C mincross.c:1510: swap if p1>p2 or tie+reverse
                    if p1 > p2 or (p1 >= p2 and reverse):
                        # exchange (swap positions)
                        nodes[li], nodes[ri] = nodes[ri], nodes[li]
                        self.lnodes[nodes[li]].order = li
                        self.lnodes[nodes[ri]].order = ri

                li = ri

            # C mincross.c:1517-1518: shrink unless hasfixed or reverse
            if not reverse:
                ep -= 1

    def _cluster_build_ranks(
        self,
        bfs_nodes: set[str],
        child_skel_set: set[str],
        child_skel_ranks: dict[str, dict[int, str]],
        node_sets: dict[str, set[str]] | None = None,
    ) -> dict[int, list[str]]:
        """Initial ordering for cluster expand via class2 + decompose + build_ranks.

        Ports C expand_cluster (cluster.c:280-296):
          class2(subg)            → build fast graph with scoped edge lists
          build_ranks(subg, 0)    → decompose DFS for nlist, then BFS
        """
        _ns = node_sets or {}

        # ── Maps ──
        skel_to_child: dict[str, str] = {}
        for child_name, rleaders in child_skel_ranks.items():
            for sn in rleaders.values():
                skel_to_child[sn] = child_name

        # mark_clusters (class2.c:163): node → top-level child cluster
        node_child: dict[str, str] = {}
        for child_name in child_skel_ranks:
            for n in _ns.get(child_name, set()):
                if n in bfs_nodes:
                    node_child[n] = child_name

        # ── Step 1: class2 — build fast graph (class2.c:155-282) ──
        # Per-node out/in edge lists + nlist, matching C fastgr.c.
        fg_nlist: list[str] = []          # GD_nlist — prepend order
        fg_nlist_set: set[str] = set()
        fg_out: dict[str, list[str]] = defaultdict(list)  # ND_out
        fg_in: dict[str, list[str]] = defaultdict(list)   # ND_in
        fg_edges: set[tuple[str, str]] = set()  # dedup

        def _fg_fast_node(n: str):
            """C fastgr.c:175-187 — prepend n to nlist."""
            if n not in fg_nlist_set:
                fg_nlist.insert(0, n)
                fg_nlist_set.add(n)

        def _fg_fast_edge(t: str, h: str):
            """C fastgr.c:71-93 — append to tail out / head in."""
            pair = (t, h)
            if pair not in fg_edges:
                fg_edges.add(pair)
                fg_out[t].append(h)
                fg_in[h].append(t)

        # 1a. build_skeleton for each child cluster
        # C class2.c:164-165, cluster.c:356-374.
        # virtual_node calls fast_node (prepend), virtual_edge calls
        # fast_edge (append to ND_out).  C iterates GD_clust array
        # which is in subgraph registration order (make_new_cluster
        # during initial ranking).  We approximate with the DOT file
        # subgraph definition order by walking self.graph.subgraphs
        # recursively.
        def _subgraph_order(g) -> list[str]:
            """Collect cluster subgraph names in DOT definition order."""
            result = []
            for name, sub in g.subgraphs.items():
                if name in child_skel_ranks:
                    result.append(name)
                result.extend(_subgraph_order(sub))
            return result
        child_order = _subgraph_order(self.graph)
        # Add any child clusters not found in subgraph walk
        for cn in sorted(child_skel_ranks.keys()):
            if cn not in child_order:
                child_order.append(cn)
        for child_name in child_order:
            rleaders = child_skel_ranks[child_name]
            prev_sn = None
            for r in sorted(rleaders.keys()):
                sn = rleaders[r]
                _fg_fast_node(sn)            # virtual_node → fast_node
                if prev_sn is not None:
                    _fg_fast_edge(prev_sn, sn)  # virtual_edge chain
                prev_sn = sn

        # 1b. Process each node's outgoing edges (class2.c:174-282).
        # C iterates agfstnode(g)/agnxtnode(g,n) for node order, then
        # agfstout(g,n)/agnxtout(g,e) for per-node edge order.
        # agfstout returns edges in the subgraph's edge dictionary
        # order — matching self.graph.edges insertion order for
        # original edges.
        #
        # Build per-node outgoing edge index matching agfstout order.
        # Walk the graph's edge dictionary recursively (subgraphs
        # first, matching how edges appear in the DOT file).
        node_out_edges: dict[str, list] = defaultdict(list)

        def _collect_out_edges(g):
            """Collect per-node outgoing edges in DOT definition order
            (matching agfstout/agnxtout for the subgraph)."""
            for key, edge in g.edges.items():
                tail_name = key[0]
                if tail_name in bfs_nodes:
                    node_out_edges[tail_name].append(edge)
            for sub in g.subgraphs.values():
                _collect_out_edges(sub)
        _collect_out_edges(self.graph)

        # Also index virtual/skeleton edges per tail node
        # (these come from edge splitting and skeleton construction,
        # appended to self.ledges after original edges)
        node_virt_edges: dict[str, list] = defaultdict(list)
        for le in self.ledges:
            if le.virtual and le.tail_name in bfs_nodes:
                node_virt_edges[le.tail_name].append(le)

        dot_order = {name: i for i, name in enumerate(self.graph.nodes)}
        ordered_nodes = sorted(
            bfs_nodes,
            key=lambda n: (dot_order.get(n, len(dot_order)), n))

        for n in ordered_nodes:
            # class2.c:175-176: non-cluster leader nodes → fast_node
            n_child = node_child.get(n) or skel_to_child.get(n)
            is_virtual = n in self.lnodes and self.lnodes[n].virtual
            if not n_child and not is_virtual:
                _fg_fast_node(n)

            # class2.c:179: iterate outgoing edges in agfstout order.
            # Process original edges first (from graph.edges), then
            # virtual edges (from self.ledges, appended later).
            seen_heads: set[str] = set()

            # Helper: leader_of (class2.c:55-66) — for a node in a
            # child cluster, return the skeleton rank leader at the
            # node's rank.  For non-cluster nodes, return the node.
            def _leader_of(name):
                ch = node_child.get(name) or skel_to_child.get(name)
                if ch and ch in child_skel_ranks:
                    r = self.lnodes[name].rank if name in self.lnodes else None
                    if r is not None and r in child_skel_ranks[ch]:
                        return child_skel_ranks[ch][r]
                return name

            for edge in node_out_edges.get(n, []):
                h = edge.head.name if edge.head else None
                if not h or h not in bfs_nodes or h == n:
                    continue

                t_ch = node_child.get(n) or skel_to_child.get(n)
                h_ch = node_child.get(h) or skel_to_child.get(h)

                if t_ch or h_ch:
                    if t_ch and h_ch and t_ch == h_ch:
                        continue  # intra-cluster (class2.c:199)
                    # interclrep (class2.c:99-124): convert to edge
                    # between rank leaders via leader_of
                    lt = _leader_of(n)
                    lh = _leader_of(h)
                    if lt != lh:
                        pair_key = (lt, lh)
                        if pair_key not in seen_heads:
                            seen_heads.add(pair_key)
                            _fg_fast_edge(lt, lh)
                    continue

                # class2.c:251: regular edge → make_chain/fast_edge
                if h not in seen_heads:
                    seen_heads.add(h)
                    _fg_fast_edge(n, h)

            # Virtual/skeleton edges from this node (interclrep chains,
            # edge-split virtual edges)
            for le in node_virt_edges.get(n, []):
                h = le.head_name
                if h not in bfs_nodes or h == n:
                    continue

                t_ch = node_child.get(n) or skel_to_child.get(n)
                h_ch = node_child.get(h) or skel_to_child.get(h)

                if t_ch or h_ch:
                    if t_ch and h_ch and t_ch == h_ch:
                        continue  # intra-cluster
                    lt = _leader_of(n)
                    lh = _leader_of(h)
                    if lt != lh:
                        pair_key = (lt, lh)
                        if pair_key not in seen_heads:
                            seen_heads.add(pair_key)
                            _fg_fast_edge(lt, lh)
                    continue

                if h not in seen_heads:
                    seen_heads.add(h)
                    _fg_fast_edge(n, h)

        # ── Step 2: build_ranks uses GD_nlist directly ──────
        # expand_cluster (cluster.c:280-296) calls class2 then
        # build_ranks.  build_ranks (mincross.c:1270,1292-1298)
        # iterates GD_nlist(g) — the fast graph nlist built by
        # class2's fast_node (prepend) calls.  It does NOT call
        # decompose.  The nlist IS the traversal order.
        #
        # fast_node prepends, so fg_nlist[0] = last node added.
        # walkbackwards (mincross.c:1288): walk from END of nlist
        # toward front = reversed(fg_nlist).

        # ── Step 3: build_ranks BFS (mincross.c:1265-1339) ──
        # Walk GD_nlist backward (mincross.c:1288-1298 walkbackwards).
        # Source = node with ND_in(n).list[0] == NULL (pass=0).
        sources = []
        for n in reversed(fg_nlist):
            if fg_in.get(n):
                continue  # has incoming — not a source
            if (n in self.lnodes and self.lnodes[n].virtual
                    and not n.startswith("_skel_")):
                continue  # _v_* virtual node — skip
            sources.append(n)

        # BFS from sources (mincross.c:1302-1320)
        result: dict[int, list[str]] = defaultdict(list)
        visited: set[str] = set()
        installed_children: set[str] = set()
        _bfs_trace = len(bfs_nodes) > 20

        if _bfs_trace:
            skel_nlist = [n for n in fg_nlist if n.startswith("_skel_")]
            print(f"[TRACE bfs] fg_nlist (skeletons): {skel_nlist}", file=sys.stderr)
        _bfs_trace = len(bfs_nodes) > 20

        if _bfs_trace:
            print(f"[TRACE bfs] sources: {sources}", file=sys.stderr)

        queue: deque[str] = deque()
        for s in sources:
            if s in visited:
                continue
            visited.add(s)
            queue.append(s)
            while queue:
                n0 = queue.popleft()
                if n0 in child_skel_set:
                    # CLUSTER node → install_cluster (cluster.c:393-407)
                    child_name = skel_to_child.get(n0, "")
                    if child_name and child_name not in installed_children:
                        installed_children.add(child_name)
                        if _bfs_trace:
                            print(f"[TRACE bfs] install_cluster {child_name}", file=sys.stderr)
                        rleaders = child_skel_ranks[child_name]
                        # install all rank leaders (cluster.c:399-404)
                        for r in sorted(rleaders.keys()):
                            result[r].append(rleaders[r])
                        # enqueue neighbors (cluster.c:405-406)
                        for sn in rleaders.values():
                            for nbr in fg_out.get(sn, []):
                                if nbr not in visited:
                                    visited.add(nbr)
                                    queue.append(nbr)
                                    if _bfs_trace:
                                        nbr_cl = skel_to_child.get(nbr, "")
                                        print(f"[TRACE bfs]   enqueue {nbr} (cl={nbr_cl}) from {sn} of {child_name}", file=sys.stderr)
                else:
                    # Regular node → install_in_rank (mincross.c:1308)
                    result[self.lnodes[n0].rank].append(n0)
                    if _bfs_trace:
                        print(f"[TRACE bfs] install {n0} rank={self.lnodes[n0].rank}", file=sys.stderr)
                    # enqueue_neighbors (mincross.c:1341-1351)
                    for nbr in fg_out.get(n0, []):
                        if nbr not in visited:
                            visited.add(nbr)
                            queue.append(nbr)

        # Handle unreached nodes (disconnected components).
        for n in sorted(bfs_nodes):
            if n in visited:
                continue
            if n in child_skel_set:
                child_name = skel_to_child.get(n, "")
                if child_name and child_name not in installed_children:
                    installed_children.add(child_name)
                    for r in sorted(child_skel_ranks[child_name].keys()):
                        result[r].append(child_skel_ranks[child_name][r])
            elif n in self.lnodes:
                result[self.lnodes[n].rank].append(n)

        # Note: C build_ranks (mincross.c:1326-1332) reverses each rank
        # when GD_flip is set.  However, the C expand_cluster trace
        # shows the POST-build_ranks order which includes this reversal.
        # Our comparison target IS the post-reversal order, so we apply
        # the reversal here to match.
        # TODO: verify whether GD_flip applies to cluster subgraphs
        # if self.rankdir in ("LR", "RL"):
        #     for r in result:
        #         result[r].reverse()

        return result, fg_out, fg_in

    def _cluster_transpose(self, rank: int, cl_nodes: set[str],
                           child_cl_map: dict[str, str] | None = None):
        """Adjacent-swap transpose restricted to cluster nodes.

        Mirrors C ``transpose_step()`` with ``left2right()`` enforcement:
        nodes in different child clusters cannot be swapped, UNLESS one
        is a virtual (skeleton) node.  This preserves child-cluster
        grouping while allowing skeleton nodes to move freely.
        """
        nodes = self.ranks.get(rank, [])
        if len(nodes) < 2:
            return
        improved = True
        while improved:
            improved = False
            for i in range(len(nodes) - 1):
                v, w = nodes[i], nodes[i + 1]
                if v not in cl_nodes or w not in cl_nodes:
                    continue
                # left2right check: block swaps between different
                # child clusters unless one is a skeleton/virtual node
                if child_cl_map:
                    v_cl = child_cl_map.get(v)
                    w_cl = child_cl_map.get(w)
                    if v_cl and w_cl and v_cl != w_cl:
                        # Both in different child clusters — check if
                        # either is a virtual/skeleton node (can swap)
                        v_virt = v in self.lnodes and self.lnodes[v].virtual
                        w_virt = w in self.lnodes and self.lnodes[w].virtual
                        if not v_virt and not w_virt:
                            continue  # block swap
                c_before = self._count_crossings_for_pair(v, w)
                c_after = self._count_crossings_for_pair(w, v)
                if c_after < c_before:
                    nodes[i], nodes[i + 1] = w, v
                    self.lnodes[w].order = i
                    self.lnodes[v].order = i + 1
                    improved = True

    def _order_by_weighted_median(self, rank: int, adj_rank: int):
        nodes = self.ranks.get(rank, [])
        if not nodes:
            return
        adj_set = set(self.ranks.get(adj_rank, []))

        medians: dict[str, float] = {}
        for name in nodes:
            positions = []
            for le in self.ledges:
                neighbor = None
                w = le.weight
                if le.tail_name == name and le.head_name in adj_set:
                    neighbor = le.head_name
                elif le.head_name == name and le.tail_name in adj_set:
                    neighbor = le.tail_name
                if neighbor is not None:
                    pos = self.lnodes[neighbor].order
                    for _ in range(max(1, w)):
                        positions.append(pos)
            if positions:
                positions.sort()
                m = len(positions)
                if m % 2 == 1:
                    medians[name] = positions[m // 2]
                else:
                    medians[name] = (positions[m // 2 - 1] + positions[m // 2]) / 2.0
            else:
                medians[name] = self.lnodes[name].order

        if self._node_to_cluster:
            # Group-aware sort: sort within contiguous cluster runs
            # but never interleave nodes from different clusters.
            # Mirrors Graphviz reorder() which respects left2right.
            groups: list[tuple[str | None, list[str]]] = []
            for name in nodes:
                cl = self._node_to_cluster.get(name)
                if groups and groups[-1][0] == cl:
                    groups[-1][1].append(name)
                else:
                    groups.append((cl, [name]))
            result: list[str] = []
            for _, group_nodes in groups:
                group_nodes.sort(key=lambda n: medians[n])
                result.extend(group_nodes)
            nodes[:] = result
        else:
            nodes.sort(key=lambda n: medians[n])
        for i, name in enumerate(nodes):
            self.lnodes[name].order = i
        self.ranks[rank] = nodes

    def _transpose_rank(self, rank: int):
        nodes = self.ranks.get(rank, [])
        if len(nodes) < 2:
            return
        has_clusters = bool(self._clusters)
        improved = True
        while improved:
            improved = False
            for i in range(len(nodes) - 1):
                # Block swaps between nodes of different clusters
                # (Graphviz mincross.c left2right).
                if has_clusters and self._left2right(nodes[i], nodes[i + 1]):
                    continue
                c_before = self._count_crossings_for_pair(nodes[i], nodes[i + 1])
                c_after = self._count_crossings_for_pair(nodes[i + 1], nodes[i])
                if c_after < c_before:
                    nodes[i], nodes[i + 1] = nodes[i + 1], nodes[i]
                    self.lnodes[nodes[i]].order = i
                    self.lnodes[nodes[i + 1]].order = i + 1
                    improved = True

    def _count_crossings_for_pair(self, u: str, v: str) -> int:
        u_rank = self.lnodes[u].rank
        crossings = 0
        for adj_rank in (u_rank - 1, u_rank + 1):
            if adj_rank not in self.ranks:
                continue
            u_neighbors = []
            v_neighbors = []
            for le in self.ledges:
                h_ln = self.lnodes.get(le.head_name)
                t_ln = self.lnodes.get(le.tail_name)
                if le.tail_name == u and h_ln and h_ln.rank == adj_rank:
                    u_neighbors.append(h_ln.order)
                elif le.head_name == u and t_ln and t_ln.rank == adj_rank:
                    u_neighbors.append(t_ln.order)
                if le.tail_name == v and h_ln and h_ln.rank == adj_rank:
                    v_neighbors.append(h_ln.order)
                elif le.head_name == v and t_ln and t_ln.rank == adj_rank:
                    v_neighbors.append(t_ln.order)
            for un in u_neighbors:
                for vn in v_neighbors:
                    if un > vn:
                        crossings += 1
        return crossings

    def _count_cluster_crossings(self, cl_nodes: set[str],
                                    min_r: int, max_r: int) -> int:
        """Count crossings involving edges with at least one endpoint in cl_nodes."""
        total = 0
        for r in range(min_r, max_r):
            if r not in self.ranks or r + 1 not in self.ranks:
                continue
            upper = self.ranks[r]
            lower = self.ranks[r + 1]
            upper_set = set(upper)
            lower_set = set(lower)
            edges_between = []
            for le in self.ledges:
                t, h = le.tail_name, le.head_name
                if t in upper_set and h in lower_set:
                    if t in cl_nodes or h in cl_nodes:
                        edges_between.append((self.lnodes[t].order,
                                              self.lnodes[h].order))
                elif h in upper_set and t in lower_set:
                    if t in cl_nodes or h in cl_nodes:
                        edges_between.append((self.lnodes[h].order,
                                              self.lnodes[t].order))
            for i in range(len(edges_between)):
                for j in range(i + 1, len(edges_between)):
                    o1_t, o1_h = edges_between[i]
                    o2_t, o2_h = edges_between[j]
                    if (o1_t - o2_t) * (o1_h - o2_h) < 0:
                        total += 1
        return total

    def _count_all_crossings(self) -> int:
        total = 0
        max_rank = max(self.ranks.keys()) if self.ranks else 0
        for r in range(max_rank):
            if r not in self.ranks or r + 1 not in self.ranks:
                continue
            upper_set = set(self.ranks[r])
            lower_set = set(self.ranks[r + 1])
            edges_between = []
            for le in self.ledges:
                if le.tail_name in upper_set and le.head_name in lower_set:
                    edges_between.append((self.lnodes[le.tail_name].order,
                                          self.lnodes[le.head_name].order))
                elif le.head_name in upper_set and le.tail_name in lower_set:
                    edges_between.append((self.lnodes[le.head_name].order,
                                          self.lnodes[le.tail_name].order))
            for i in range(len(edges_between)):
                for j in range(i + 1, len(edges_between)):
                    o1_t, o1_h = edges_between[i]
                    o2_t, o2_h = edges_between[j]
                    if (o1_t - o2_t) * (o1_h - o2_h) < 0:
                        total += 1
        return total

    def _count_scoped_crossings(self, fg_out: dict[str, list[str]],
                                 min_r: int, max_r: int) -> int:
        """Count crossings using only edges in the given fast graph.

        Mirrors C mincross.c:1617-1632 ncross() which iterates
        ND_out(n) — the subgraph's scoped edge list.  At cluster
        mincross time, this excludes intra-child-cluster edges
        (class2.c:199) so reorderings at the parent cluster level
        are judged only by inter-child crossings.
        """
        total = 0
        for r in range(min_r, max_r):
            if r not in self.ranks or r + 1 not in self.ranks:
                continue
            upper_set = set(self.ranks[r])
            lower_set = set(self.ranks[r + 1])
            edges_between = []
            for t in self.ranks[r]:
                for h in fg_out.get(t, []):
                    if h in lower_set:
                        edges_between.append((self.lnodes[t].order,
                                              self.lnodes[h].order))
            for t in self.ranks[r + 1]:
                for h in fg_out.get(t, []):
                    if h in upper_set:
                        edges_between.append((self.lnodes[h].order,
                                              self.lnodes[t].order))
            for i in range(len(edges_between)):
                for j in range(i + 1, len(edges_between)):
                    o1_t, o1_h = edges_between[i]
                    o2_t, o2_h = edges_between[j]
                    if (o1_t - o2_t) * (o1_h - o2_h) < 0:
                        total += 1
        return total

    def _save_ordering(self) -> dict[str, int]:
        return {name: ln.order for name, ln in self.lnodes.items()}

    def _restore_ordering(self, ordering: dict[str, int]):
        for name, order in ordering.items():
            self.lnodes[name].order = order
        for rank_val in self.ranks:
            self.ranks[rank_val].sort(key=lambda n: self.lnodes[n].order)
            for i, name in enumerate(self.ranks[rank_val]):
                self.lnodes[name].order = i

    # ── Phase 3: Coordinate assignment ───────────

    _CL_OFFSET = 8.0  # Graphviz CL_OFFSET constant (points)

    def _phase3_position(self):
        """Phase 3 entry point — delegates to position module.

        The implementation lives in ``gvpy/engines/dot/position.py``
        (C analogue: ``lib/dotgen/position.c``).  Other Phase 3 helpers
        (``_set_ycoords``, ``_expand_leaves``, etc.) still live on this
        class and are called by the module via ``layout._xxx()``.  See
        ``TODO_core_refactor.md`` step 4 for the full extraction plan.
        """
        from gvpy.engines.dot import position
        position.phase3_position(self)

    def _expand_leaves(self):
        """Delegates to gvpy.engines.dot.position.expand_leaves."""
        from gvpy.engines.dot import position
        return position.expand_leaves(self)

    def _insert_flat_label_nodes(self) -> bool:
        """Delegates to gvpy.engines.dot.position.insert_flat_label_nodes."""
        from gvpy.engines.dot import position
        return position.insert_flat_label_nodes(self)

    def _set_ycoords(self):
        """Delegates to gvpy.engines.dot.position.set_ycoords."""
        from gvpy.engines.dot import position
        return position.set_ycoords(self)

    def _simple_x_position(self):
        """Delegates to gvpy.engines.dot.position.simple_x_position."""
        from gvpy.engines.dot import position
        return position.simple_x_position(self)

    def _median_x_improvement(self):
        """Delegates to gvpy.engines.dot.position.median_x_improvement."""
        from gvpy.engines.dot import position
        return position.median_x_improvement(self)

    def _bottomup_ns_x_position(self):
        """Delegates to gvpy.engines.dot.position.bottomup_ns_x_position."""
        from gvpy.engines.dot import position
        return position.bottomup_ns_x_position(self)

    def _ns_x_position(self) -> bool:
        """Delegate to position.ns_x_position — see that module."""
        from gvpy.engines.dot import position
        return position.ns_x_position(self)

    def _resolve_cluster_overlaps(self):
        """Delegates to gvpy.engines.dot.position.resolve_cluster_overlaps."""
        from gvpy.engines.dot import position
        return position.resolve_cluster_overlaps(self)

    def _post_rankdir_keepout(self):
        """Delegates to gvpy.engines.dot.position.post_rankdir_keepout."""
        from gvpy.engines.dot import position
        return position.post_rankdir_keepout(self)

    def _center_ranks(self):
        """Delegates to gvpy.engines.dot.position.center_ranks."""
        from gvpy.engines.dot import position
        return position.center_ranks(self)

    def _apply_rankdir(self):
        """Delegates to gvpy.engines.dot.position.apply_rankdir."""
        from gvpy.engines.dot import position
        return position.apply_rankdir(self)

    def _apply_size(self):
        """Scale layout to fit within graph size attribute if set."""
        if not self.graph_size or not self.lnodes:
            return
        target_w, target_h = self.graph_size
        real = [ln for ln in self.lnodes.values() if not ln.virtual]
        if not real:
            return
        min_x = min(ln.x - ln.width / 2 for ln in real)
        max_x = max(ln.x + ln.width / 2 for ln in real)
        min_y = min(ln.y - ln.height / 2 for ln in real)
        max_y = max(ln.y + ln.height / 2 for ln in real)
        cur_w = max_x - min_x
        cur_h = max_y - min_y
        if cur_w < 0.1 or cur_h < 0.1:
            return
        sx = target_w / cur_w
        sy = target_h / cur_h
        if self.ratio == "compress":
            pass  # non-uniform: use sx, sy as-is
        elif self.ratio == "fill":
            s = max(sx, sy)
            sx = sy = s
        else:
            s = min(sx, sy)
            sx = sy = s
        # Only scale down, never up (unless size has !)
        if sx >= 1.0 and sy >= 1.0:
            return
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        for ln in self.lnodes.values():
            ln.x = cx + (ln.x - cx) * sx
            ln.y = cy + (ln.y - cy) * sy

    def _concentrate_edges(self):
        """Merge parallel edges that share the same tail and head."""
        all_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges
        seen: dict[tuple[str, str], list[float]] = {}
        for le in all_edges:
            t, h = le.tail_name, le.head_name
            if le.reversed:
                t, h = h, t
            key = (t, h)
            if key in seen:
                le.points = seen[key]
            elif le.points:
                seen[key] = le.points

    def _apply_quantum(self):
        """Snap all node coordinates to a grid with spacing = quantum."""
        q = self.quantum
        if q <= 0:
            return
        for ln in self.lnodes.values():
            ln.x = round(ln.x / q) * q
            ln.y = round(ln.y / q) * q

    def _apply_normalize(self):
        """Shift all coordinates so the minimum is at the origin."""
        if not self.lnodes:
            return
        real = [ln for ln in self.lnodes.values() if not ln.virtual]
        if not real:
            return
        min_x = min(ln.x - ln.width / 2 for ln in real)
        min_y = min(ln.y - ln.height / 2 for ln in real)
        if min_x == 0 and min_y == 0:
            return
        for ln in self.lnodes.values():
            ln.x -= min_x
            ln.y -= min_y

    def _apply_fixed_positions(self):
        """Apply pos= fixed positions, overriding computed coordinates."""
        for name, ln in self.lnodes.items():
            if ln.fixed_pos is not None:
                ln.x, ln.y = ln.fixed_pos

    # _apply_rotation inherited from LayoutEngine

    def _apply_center(self):
        """Shift layout so the center of the bounding box is at the origin."""
        real = [ln for ln in self.lnodes.values() if not ln.virtual]
        if not real:
            return
        min_x = min(ln.x - ln.width / 2 for ln in real)
        max_x = max(ln.x + ln.width / 2 for ln in real)
        min_y = min(ln.y - ln.height / 2 for ln in real)
        max_y = max(ln.y + ln.height / 2 for ln in real)
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        for ln in self.lnodes.values():
            ln.x -= cx
            ln.y -= cy

    # ── Label placement with collision avoidance ───
    #
    # Port of Graphviz lib/label (xlabels.c).  Uses a simple spatial
    # index (list-based; R-tree unnecessary for typical graph sizes)
    # and a 9-position grid search with edge-sliding fallback.

    # _estimate_label_size and _overlap_area inherited from LayoutEngine

    def _compute_xlabel_positions(self):
        """Compute positions for xlabel, headlabel, taillabel, and graph label.

        Uses a 9-position grid search around each object with collision
        avoidance.  Placement priority: right, below-right, above-right,
        below, above, left, below-left, above-left, center.  If all
        positions collide, the position with minimum overlap is chosen.

        Based on the algorithm in Graphviz lib/label/xlabels.c.
        """
        # Build obstacle list: all real nodes and cluster boxes
        obstacles: list[tuple[float, float, float, float]] = []  # (cx, cy, w, h)
        for name, ln in self.lnodes.items():
            if not ln.virtual:
                obstacles.append((ln.x, ln.y, ln.width, ln.height))
        for cl in self._clusters:
            if cl.bb and cl.nodes:
                cx = (cl.bb[0] + cl.bb[2]) / 2
                cy = (cl.bb[1] + cl.bb[3]) / 2
                cw = cl.bb[2] - cl.bb[0]
                ch = cl.bb[3] - cl.bb[1]
                obstacles.append((cx, cy, cw, ch))

        # Placed labels also become obstacles
        placed: list[tuple[float, float, float, float]] = []

        def _find_best_position(anchor_x, anchor_y, obj_w, obj_h,
                                lbl_w, lbl_h, pad=4.0):
            """Try 9 positions around an anchor object, return best (x, y).

            Positions tried (relative to object center):
              0: right-center    1: below-right     2: above-right
              3: below-center    4: above-center     5: left-center
              6: below-left      7: above-left       8: centered
            """
            half_ow = obj_w / 2.0
            half_oh = obj_h / 2.0
            candidates = [
                (anchor_x + half_ow + pad + lbl_w / 2, anchor_y),                    # right
                (anchor_x + half_ow + pad + lbl_w / 2, anchor_y + half_oh + pad + lbl_h / 2),  # below-right
                (anchor_x + half_ow + pad + lbl_w / 2, anchor_y - half_oh - pad - lbl_h / 2),  # above-right
                (anchor_x, anchor_y + half_oh + pad + lbl_h / 2),                    # below
                (anchor_x, anchor_y - half_oh - pad - lbl_h / 2),                    # above
                (anchor_x - half_ow - pad - lbl_w / 2, anchor_y),                    # left
                (anchor_x - half_ow - pad - lbl_w / 2, anchor_y + half_oh + pad + lbl_h / 2),  # below-left
                (anchor_x - half_ow - pad - lbl_w / 2, anchor_y - half_oh - pad - lbl_h / 2),  # above-left
                (anchor_x, anchor_y),                                                 # center (last resort)
            ]

            best_pos = candidates[0]
            best_overlap = float("inf")

            for cx, cy in candidates:
                total_overlap = 0.0
                for ox, oy, ow, oh in obstacles:
                    total_overlap += self._overlap_area(cx, cy, lbl_w, lbl_h,
                                                       ox, oy, ow, oh)
                for px, py, pw, ph in placed:
                    total_overlap += self._overlap_area(cx, cy, lbl_w, lbl_h,
                                                       px, py, pw, ph)
                if total_overlap == 0.0:
                    # No overlap — take it immediately
                    return (cx, cy)
                if total_overlap < best_overlap:
                    best_overlap = total_overlap
                    best_pos = (cx, cy)

            # Sliding fallback: try shifting along the right edge
            for offset in range(1, 6):
                shift = offset * lbl_h * 0.6
                for cx, cy in [(anchor_x + half_ow + pad + lbl_w / 2, anchor_y + shift),
                               (anchor_x + half_ow + pad + lbl_w / 2, anchor_y - shift)]:
                    total_overlap = 0.0
                    for ox, oy, ow, oh in obstacles:
                        total_overlap += self._overlap_area(cx, cy, lbl_w, lbl_h,
                                                           ox, oy, ow, oh)
                    for px, py, pw, ph in placed:
                        total_overlap += self._overlap_area(cx, cy, lbl_w, lbl_h,
                                                           px, py, pw, ph)
                    if total_overlap == 0.0:
                        return (cx, cy)
                    if total_overlap < best_overlap:
                        best_overlap = total_overlap
                        best_pos = (cx, cy)

            return best_pos

        # ── Node xlabels ─────────────────────────────
        for name, ln in self.lnodes.items():
            if ln.virtual or not ln.node:
                continue
            xlabel = ln.node.attributes.get("xlabel", "")
            if not xlabel:
                continue
            try:
                fs = float(ln.node.attributes.get("fontsize", "14"))
            except ValueError:
                fs = 14.0
            lw, lh = self._estimate_label_size(xlabel, fs)
            bx, by = _find_best_position(ln.x, ln.y, ln.width, ln.height, lw, lh)
            ln.node.attributes["_xlabel_pos_x"] = str(round(bx, 2))
            ln.node.attributes["_xlabel_pos_y"] = str(round(by, 2))
            placed.append((bx, by, lw, lh))

        # ── Edge head/tail labels ────────────────────
        all_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges
        for le in all_edges:
            if not le.edge or not le.points:
                continue
            try:
                fs = float(le.edge.attributes.get("labelfontsize",
                           le.edge.attributes.get("fontsize", "14")))
            except ValueError:
                fs = 14.0

            headlabel = le.edge.attributes.get("headlabel", "")
            if headlabel:
                lw, lh = self._estimate_label_size(headlabel, fs)
                hp = le.points[-1]
                # Use small anchor box at head endpoint
                bx, by = _find_best_position(hp[0], hp[1], 2, 2, lw, lh, pad=6.0)
                le.edge.attributes["_headlabel_pos_x"] = str(round(bx, 2))
                le.edge.attributes["_headlabel_pos_y"] = str(round(by, 2))
                placed.append((bx, by, lw, lh))

            taillabel = le.edge.attributes.get("taillabel", "")
            if taillabel:
                lw, lh = self._estimate_label_size(taillabel, fs)
                tp = le.points[0]
                bx, by = _find_best_position(tp[0], tp[1], 2, 2, lw, lh, pad=6.0)
                le.edge.attributes["_taillabel_pos_x"] = str(round(bx, 2))
                le.edge.attributes["_taillabel_pos_y"] = str(round(by, 2))
                placed.append((bx, by, lw, lh))

        # ── Graph-level label ────────────────────────
        graph_label = self.graph.get_graph_attr("label")
        if graph_label:
            try:
                gfs = float(self.graph.get_graph_attr("fontsize") or "14")
            except ValueError:
                gfs = 14.0
            lw, lh = self._estimate_label_size(graph_label, gfs)
            labelloc = (self.graph.get_graph_attr("labelloc") or "b").lower()
            labeljust = (self.graph.get_graph_attr("labeljust") or "c").lower()

            # Compute graph bounding box
            real = [ln for ln in self.lnodes.values() if not ln.virtual]
            if real:
                gbb_x1 = min(ln.x - ln.width / 2 for ln in real)
                gbb_x2 = max(ln.x + ln.width / 2 for ln in real)
                gbb_y1 = min(ln.y - ln.height / 2 for ln in real)
                gbb_y2 = max(ln.y + ln.height / 2 for ln in real)
            else:
                gbb_x1 = gbb_y1 = 0
                gbb_x2 = gbb_y2 = 100

            gcx = (gbb_x1 + gbb_x2) / 2
            if labeljust == "l":
                gx = gbb_x1 + lw / 2
            elif labeljust == "r":
                gx = gbb_x2 - lw / 2
            else:
                gx = gcx

            if labelloc == "t":
                gy = gbb_y1 - lh / 2 - 8
            else:
                gy = gbb_y2 + lh / 2 + 8

            self.graph.set_graph_attr("_label_pos_x", str(round(gx, 2)))
            self.graph.set_graph_attr("_label_pos_y", str(round(gy, 2)))

    # ── Phase 4: Edge routing ────────────────────

    def _phase4_routing(self):
        print(f"[TRACE spline] phase4 begin: splines={self.splines} compound={self.compound}", file=sys.stderr)
        # Pre-compute rank bounding info for obstacle-aware routing
        self._rank_ht1: dict[int, float] = {}  # bottom half-height per rank
        self._rank_ht2: dict[int, float] = {}  # top half-height per rank
        for ln in self.lnodes.values():
            r = ln.rank
            hh = ln.height / 2.0
            self._rank_ht1[r] = max(self._rank_ht1.get(r, 0), hh)
            self._rank_ht2[r] = max(self._rank_ht2.get(r, 0), hh)

        # Compute graph-wide left/right bounds with padding
        if self.lnodes:
            all_x = [ln.x for ln in self.lnodes.values()]
            all_hw = [ln.width / 2 for ln in self.lnodes.values()]
            self._left_bound = min(x - w for x, w in zip(all_x, all_hw)) - 16
            self._right_bound = max(x + w for x, w in zip(all_x, all_hw)) + 16
        else:
            self._left_bound = -16
            self._right_bound = 16

        # Route regular (non-virtual, non-chain) edges
        for le in self.ledges:
            if le.virtual:
                continue
            tail = self.lnodes.get(le.tail_name)
            head = self.lnodes.get(le.head_name)
            if tail is None or head is None:
                continue
            if le.tail_name == le.head_name:
                le.points = self._self_loop_points(tail)
            elif tail.rank == head.rank and not le.virtual:
                le.points = self._flat_edge_route(le, tail, head)
            elif self.splines == "ortho":
                le.points = self._ortho_route(le, tail, head)
            elif self.splines == "line":
                p1 = self._edge_start_point(le, tail, head)
                p2 = self._edge_end_point(le, head, tail)
                le.points = [p1, p2]
            else:
                le.points = self._route_regular_edge(le, tail, head)
            self._compute_label_pos(le)

        # Route chain edges through virtual nodes
        for le in self._chain_edges:
            tail = self.lnodes.get(le.tail_name)
            head = self.lnodes.get(le.head_name)
            if self.splines == "line" and tail and head:
                # Line mode: direct start-to-end, ignore virtual nodes
                p1 = self._edge_start_point(le, tail, head)
                p2 = self._edge_end_point(le, head, tail)
                le.points = [p1, p2]
            elif self.splines == "ortho" and tail and head:
                le.points = self._ortho_route(le, tail, head)
            else:
                key = (le.tail_name, le.head_name)
                chain = self._vnode_chains.get(key, [])
                le.points = self._route_through_chain(le.tail_name, chain, le.head_name)
            self._compute_label_pos(le)

        # Apply samehead/sametail: merge endpoints for grouped edges
        self._apply_sameport()

        # Compound edge clipping: clip to cluster bounding boxes
        if self.compound:
            self._clip_compound_edges()

        # Convert to Bezier curves if splines mode requests it.
        # Skip edges already marked as bezier (e.g. from _flat_edge_route).
        use_bezier = self.splines in ("", "spline", "curved", "true")
        if use_bezier:
            all_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges
            for le in all_edges:
                if le.points and len(le.points) >= 2 and le.spline_type != "bezier":
                    le.points = self._to_bezier(le.points)
                    le.spline_type = "bezier"

        # Log edge routing results
        all_routed = [le for le in self.ledges if not le.virtual] + self._chain_edges
        for le in all_routed:
            if le.points:
                pts_str = " ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in le.points[:4])
                print(f"[TRACE spline] edge {le.tail_name}->{le.head_name}: npts={len(le.points)} type={le.spline_type} pts={pts_str}{'...' if len(le.points)>4 else ''}", file=sys.stderr)

    def _clip_compound_edges(self):
        """Clip edges with lhead/ltail to their target cluster bounding box."""
        cluster_map = {cl.name: cl for cl in self._clusters}
        all_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges
        for le in all_edges:
            if not le.points or len(le.points) < 2:
                continue
            if le.ltail and le.ltail in cluster_map:
                cl = cluster_map[le.ltail]
                if len(le.points) >= 2:
                    clipped = self._clip_to_bb(le.points[0], le.points[1], cl.bb)
                    if clipped:
                        le.points[0] = clipped
            if le.lhead and le.lhead in cluster_map:
                cl = cluster_map[le.lhead]
                if len(le.points) >= 2:
                    clipped = self._clip_to_bb(le.points[-1], le.points[-2], cl.bb)
                    if clipped:
                        le.points[-1] = clipped

    @staticmethod
    def _clip_to_bb(inside: tuple, outside: tuple, bb: tuple) -> tuple | None:
        """Find intersection of line segment (outside->inside) with rectangle bb.

        bb = (min_x, min_y, max_x, max_y). Returns the intersection point,
        or None if no intersection found.
        """
        x1, y1 = outside
        x2, y2 = inside
        bx1, by1, bx2, by2 = bb
        dx, dy = x2 - x1, y2 - y1
        best_t = None
        # Check each of the 4 edges of the rectangle
        for edge_val, is_x in [(bx1, True), (bx2, True), (by1, False), (by2, False)]:
            if is_x:
                if abs(dx) < 1e-9:
                    continue
                t = (edge_val - x1) / dx
                y_at_t = y1 + t * dy
                if 0 <= t <= 1 and by1 <= y_at_t <= by2:
                    if best_t is None or t > best_t:
                        best_t = t
            else:
                if abs(dy) < 1e-9:
                    continue
                t = (edge_val - y1) / dy
                x_at_t = x1 + t * dx
                if 0 <= t <= 1 and bx1 <= x_at_t <= bx2:
                    if best_t is None or t > best_t:
                        best_t = t
        if best_t is not None:
            return (x1 + best_t * dx, y1 + best_t * dy)
        return None

    @staticmethod
    def _to_bezier(pts: list[tuple]) -> list[tuple]:
        """Convert a polyline to smooth cubic Bezier control points.

        Uses Schneider's recursive curve-fitting algorithm:
        1. Parameterize points by chord-length fraction.
        2. Estimate end tangents from neighboring points.
        3. Fit a cubic Bezier via least-squares tangent scaling.
        4. If max deviation > tolerance, split at worst point and recurse.

        Mirrors Graphviz ``routespl.c:mkspline()`` / ``reallyroutespline()``.

        Input:  [P0, P1, ..., Pn]  (polyline waypoints)
        Output: [P0, C1, C2, P1, C3, C4, P2, ...]  (cubic Bezier segments)
        """
        import math

        n = len(pts)
        if n <= 1:
            return list(pts)
        if n == 2:
            p0, p1 = pts
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            return [p0, (p0[0] + dx / 3, p0[1] + dy / 3),
                    (p0[0] + 2 * dx / 3, p0[1] + 2 * dy / 3), p1]

        def _dist(a, b):
            return math.hypot(b[0] - a[0], b[1] - a[1])

        def _normalize(v):
            d = math.hypot(v[0], v[1])
            return (v[0] / d, v[1] / d) if d > 1e-9 else (0.0, 0.0)

        def _bezier_pt(p0, p1, p2, p3, t):
            s = 1 - t
            return (s*s*s*p0[0] + 3*s*s*t*p1[0] + 3*s*t*t*p2[0] + t*t*t*p3[0],
                    s*s*s*p0[1] + 3*s*s*t*p1[1] + 3*s*t*t*p2[1] + t*t*t*p3[1])

        def _fit_cubic(points, t_params, ev0, ev1):
            """Schneider least-squares cubic fit with fixed tangent dirs."""
            p0 = points[0]
            p3 = points[-1]
            n = len(points)

            # Build normal equations for tangent scale factors
            c00 = c01 = c10 = c11 = 0.0
            x0 = x1 = 0.0
            for i in range(n):
                t = t_params[i]
                s = 1 - t
                b1 = 3 * s * s * t
                b2 = 3 * s * t * t
                a1 = (ev0[0] * b1, ev0[1] * b1)
                a2 = (ev1[0] * b2, ev1[1] * b2)
                c00 += a1[0]*a1[0] + a1[1]*a1[1]
                c01 += a1[0]*a2[0] + a1[1]*a2[1]
                c11 += a2[0]*a2[0] + a2[1]*a2[1]
                b0 = s*s*s
                b3 = t*t*t
                tmp = (points[i][0] - b0*p0[0] - b3*p3[0],
                       points[i][1] - b0*p0[1] - b3*p3[1])
                x0 += a1[0]*tmp[0] + a1[1]*tmp[1]
                x1 += a2[0]*tmp[0] + a2[1]*tmp[1]
            c10 = c01

            det = c00*c11 - c01*c10
            if abs(det) < 1e-12:
                d = _dist(p0, p3) / 3.0
                return (p0, (p0[0]+ev0[0]*d, p0[1]+ev0[1]*d),
                        (p3[0]+ev1[0]*d, p3[1]+ev1[1]*d), p3)

            alpha0 = (x0*c11 - x1*c01) / det
            alpha1 = (c00*x1 - c10*x0) / det

            d = _dist(p0, p3)
            eps = d * 1e-6
            if alpha0 < eps or alpha1 < eps:
                alpha0 = alpha1 = d / 3.0

            return (p0,
                    (p0[0]+ev0[0]*alpha0, p0[1]+ev0[1]*alpha0),
                    (p3[0]+ev1[0]*alpha1, p3[1]+ev1[1]*alpha1),
                    p3)

        def _max_error(points, t_params, bezier):
            """Return (max_dist, index_of_worst)."""
            worst_d = 0.0
            worst_i = 0
            for i in range(len(points)):
                bp = _bezier_pt(*bezier, t_params[i])
                d = _dist(points[i], bp)
                if d > worst_d:
                    worst_d = d
                    worst_i = i
            return worst_d, worst_i

        def _fit_recursive(points, ev0, ev1, depth=0):
            """Recursively fit cubics, splitting at worst-fit point."""
            n = len(points)
            if n <= 2:
                p0, p1 = points[0], points[-1]
                dx, dy = p1[0]-p0[0], p1[1]-p0[1]
                return [p0, (p0[0]+dx/3, p0[1]+dy/3),
                        (p0[0]+2*dx/3, p0[1]+2*dy/3), p1]

            # Chord-length parameterization
            dists = [0.0]
            for i in range(1, n):
                dists.append(dists[-1] + _dist(points[i-1], points[i]))
            total = dists[-1]
            if total < 1e-9:
                return [points[0], points[0], points[-1], points[-1]]
            t_params = [d / total for d in dists]

            bezier = _fit_cubic(points, t_params, ev0, ev1)
            err, split_i = _max_error(points, t_params, bezier)

            tolerance = 4.0  # 4pt tolerance
            if err <= tolerance or depth > 8 or n <= 3:
                return list(bezier)

            # Split at worst point and recurse
            split_i = max(1, min(split_i, n - 2))
            sp = points[split_i]
            # Tangent at split point: direction between neighbors
            if split_i > 0 and split_i < n - 1:
                mid_tan = _normalize((points[split_i+1][0] - points[split_i-1][0],
                                      points[split_i+1][1] - points[split_i-1][1]))
            else:
                mid_tan = _normalize((points[-1][0] - points[0][0],
                                      points[-1][1] - points[0][1]))
            neg_tan = (-mid_tan[0], -mid_tan[1])

            left = _fit_recursive(points[:split_i+1], ev0, neg_tan, depth+1)
            right = _fit_recursive(points[split_i:], mid_tan, ev1, depth+1)
            return left + right[1:]  # skip duplicate split point

        # Estimate end tangents
        ev0 = _normalize((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
        ev1 = _normalize((pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1]))

        return _fit_recursive(list(pts), ev0, ev1)

    def _edge_start_point(self, le: LayoutEdge, tail: LayoutNode,
                          head: LayoutNode) -> tuple[float, float]:
        """Get edge start point — uses tailport if set, else boundary intersection."""
        if le.tailport:
            # Check record port first, then compass
            pt = self._record_port_point(le.tail_name, le.tailport, tail,
                                         is_tail=True)
            if pt is not None:
                return pt
            compass = le.tailport.split(":")[-1] if ":" in le.tailport else le.tailport
            pt = self._port_point(tail, compass)
            if pt is not None:
                return pt
        if not le.tailclip:
            return (tail.x, tail.y)
        return self._boundary_point(tail, head.x, head.y)

    def _edge_end_point(self, le: LayoutEdge, head: LayoutNode,
                        tail: LayoutNode) -> tuple[float, float]:
        """Get edge end point — uses headport if set, else boundary intersection."""
        if le.headport:
            pt = self._record_port_point(le.head_name, le.headport, head,
                                         is_tail=False)
            if pt is not None:
                return pt
            compass = le.headport.split(":")[-1] if ":" in le.headport else le.headport
            pt = self._port_point(head, compass)
            if pt is not None:
                return pt
        if not le.headclip:
            return (head.x, head.y)
        return self._boundary_point(head, tail.x, tail.y)

    def _record_port_point(self, node_name: str, port: str,
                           ln: LayoutNode,
                           is_tail: bool = True) -> tuple[float, float] | None:
        """Get attachment point for a record port on the node boundary.

        For TB/BT mode the port fraction runs along the X axis (fields
        left-to-right) and the edge attaches at the top or bottom boundary.
        For LR/RL mode the port fraction runs along the Y axis (fields
        top-to-bottom) and the edge attaches at the left or right boundary.

        ``is_tail`` determines which boundary: tails attach at the
        bottom/right edge (toward the next rank), heads at the top/left.
        """
        # Look up port fraction from Node.record_fields (source of truth)
        port_name = port.split(":")[0] if ":" in port else port
        ln_obj = self.lnodes.get(node_name)
        if not ln_obj or not ln_obj.node or ln_obj.node.record_fields is None:
            return None
        frac = ln_obj.node.record_fields.port_fraction(
            port_name, rankdir=self._rankdir_int())
        if frac is None:
            return None

        if self.rankdir in ("LR", "RL"):
            # LR/RL: port fraction → Y position, boundary on X
            y = ln.y - ln.height / 2.0 + frac * ln.height
            if is_tail:
                x = ln.x + ln.width / 2.0   # right edge (toward next rank)
            else:
                x = ln.x - ln.width / 2.0   # left edge (from prev rank)
        else:
            # TB/BT: port fraction → X position, boundary on Y
            x = ln.x - ln.width / 2.0 + frac * ln.width
            if is_tail:
                y = ln.y + ln.height / 2.0   # bottom edge (toward next rank)
            else:
                y = ln.y - ln.height / 2.0   # top edge (from prev rank)

        return (x, y)

    @staticmethod
    def _port_point(ln: LayoutNode, compass: str):
        """Return point on node boundary for a compass direction, or None."""
        offsets = _COMPASS.get(compass)
        if offsets is None:
            return None
        dx, dy = offsets
        return (ln.x + dx * ln.width / 2.0, ln.y + dy * ln.height / 2.0)

    @staticmethod
    def _compute_label_pos(le: LayoutEdge):
        """Set label_pos at the midpoint of the edge polyline, offset by labelangle/labeldistance."""
        if not le.label or not le.points:
            return
        n = len(le.points)
        mid = n // 2
        if n % 2 == 0 and n >= 2:
            x = (le.points[mid - 1][0] + le.points[mid][0]) / 2.0
            y = (le.points[mid - 1][1] + le.points[mid][1]) / 2.0
        else:
            x, y = le.points[mid]

        # Apply labelangle and labeldistance if set on the edge
        if le.edge:
            import math
            angle_str = le.edge.attributes.get("labelangle", "")
            dist_str = le.edge.attributes.get("labeldistance", "")
            if angle_str or dist_str:
                angle = math.radians(float(angle_str)) if angle_str else 0.0
                dist = float(dist_str) * 14.0 if dist_str else 0.0  # scale by font size
                x += dist * math.cos(angle)
                y += dist * math.sin(angle)

        le.label_pos = (round(x, 2), round(y, 2))

    def _apply_sameport(self):
        """Merge endpoints for edges with samehead or sametail attributes."""
        all_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges

        # samehead: edges arriving at the same node with same samehead value share endpoint
        head_groups: dict[tuple[str, str], tuple] = {}  # (head_name, samehead) -> point
        for le in all_edges:
            if le.samehead and le.points:
                key = (le.head_name, le.samehead)
                if key not in head_groups:
                    head_groups[key] = le.points[-1]
                else:
                    le.points[-1] = head_groups[key]

        # sametail: edges leaving the same node with same sametail value share startpoint
        tail_groups: dict[tuple[str, str], tuple] = {}
        for le in all_edges:
            if le.sametail and le.points:
                key = (le.tail_name, le.sametail)
                if key not in tail_groups:
                    tail_groups[key] = le.points[0]
                else:
                    le.points[0] = tail_groups[key]

    def _ortho_route(self, le: LayoutEdge, tail: LayoutNode,
                     head: LayoutNode) -> list[tuple[float, float]]:
        """Route with right-angle bends only (Z-shaped or L-shaped path)."""
        # Exit point from tail
        p_start = self._edge_start_point(le, tail, head)
        # Entry point into head
        p_end = self._edge_end_point(le, head, tail)

        mid_y = (p_start[1] + p_end[1]) / 2.0

        if abs(p_start[0] - p_end[0]) < 0.5:
            # Vertically aligned — straight vertical line
            return [p_start, p_end]

        # Z-shaped: vertical from tail, horizontal, vertical into head
        return [
            p_start,
            (p_start[0], mid_y),
            (p_end[0], mid_y),
            p_end,
        ]

    def _route_through_chain(self, tail_name: str, chain: list[str],
                             head_name: str) -> list[tuple[float, float]]:
        """Route an edge through a chain of virtual nodes."""
        tail = self.lnodes[tail_name]
        head = self.lnodes[head_name]

        if not chain:
            p1 = self._boundary_point(tail, head.x, head.y)
            p2 = self._boundary_point(head, tail.x, tail.y)
            return [p1, p2]

        # First virtual node
        first_v = self.lnodes[chain[0]]
        points = [self._boundary_point(tail, first_v.x, first_v.y)]

        # Intermediate virtual nodes
        for vname in chain:
            vn = self.lnodes[vname]
            points.append((vn.x, vn.y))

        # Last point: boundary of head node
        last_v = self.lnodes[chain[-1]]
        points.append(self._boundary_point(head, last_v.x, last_v.y))

        return points

    @staticmethod
    def _boundary_point(ln: LayoutNode, tx: float, ty: float) -> tuple[float, float]:
        cx, cy = ln.x, ln.y
        dx, dy = tx - cx, ty - cy
        if dx == 0 and dy == 0:
            return (cx, cy - ln.height / 2.0)
        hw, hh = ln.width / 2.0, ln.height / 2.0
        adx, ady = abs(dx), abs(dy)
        if adx * hh > ady * hw:
            scale = hw / adx if adx != 0 else 1.0
        else:
            scale = hh / ady if ady != 0 else 1.0
        return (cx + dx * scale, cy + dy * scale)

    @staticmethod
    def _self_loop_points(ln: LayoutNode) -> list[tuple[float, float]]:
        hw = ln.width / 2.0
        loop = 20.0
        return [
            (ln.x + hw, ln.y),
            (ln.x + hw + loop, ln.y - loop),
            (ln.x + hw + loop, ln.y + loop),
            (ln.x + hw, ln.y),
        ]

    def _maximal_bbox(self, ln: LayoutNode) -> tuple[float, float, float, float]:
        """Compute the available bounding box around a node for edge routing.

        X extent: halfway to each neighbor in the same rank (or to graph
        bounds if no neighbor).  Y extent: the rank's height band.
        Mirrors Graphviz ``dotsplines.c:maximal_bbox()``.
        """
        r = ln.rank
        rank_nodes = self.ranks.get(r, [])
        idx = ln.order

        # X extent: halfway to neighbors
        left_x = self._left_bound
        right_x = self._right_bound
        if idx > 0:
            left_ln = self.lnodes[rank_nodes[idx - 1]]
            left_x = (left_ln.x + left_ln.width / 2 + ln.x - ln.width / 2) / 2
        if idx < len(rank_nodes) - 1:
            right_ln = self.lnodes[rank_nodes[idx + 1]]
            right_x = (ln.x + ln.width / 2 + right_ln.x - right_ln.width / 2) / 2

        # Y extent: rank band
        top_y = ln.y - self._rank_ht2.get(r, ln.height / 2)
        bot_y = ln.y + self._rank_ht1.get(r, ln.height / 2)

        return (left_x, top_y, right_x, bot_y)

    def _rank_box(self, r: int) -> tuple[float, float, float, float]:
        """Inter-rank corridor between rank r and rank r+1.

        Full graph width, from bottom of rank r nodes to top of rank r+1.
        Mirrors Graphviz ``dotsplines.c:rank_box()``.
        """
        # rank r nodes' Y center
        r_nodes = self.ranks.get(r, [])
        r1_nodes = self.ranks.get(r + 1, [])
        if r_nodes:
            r_y = self.lnodes[r_nodes[0]].y
        else:
            r_y = r * self.ranksep
        if r1_nodes:
            r1_y = self.lnodes[r1_nodes[0]].y
        else:
            r1_y = (r + 1) * self.ranksep

        top_y = r_y + self._rank_ht1.get(r, 18)     # bottom edge of rank r
        bot_y = r1_y - self._rank_ht2.get(r + 1, 18) # top edge of rank r+1

        return (self._left_bound, top_y, self._right_bound, bot_y)

    def _route_regular_edge(self, le: LayoutEdge, tail: LayoutNode,
                             head: LayoutNode) -> list[tuple[float, float]]:
        """Route an edge between nodes on different ranks using corridor boxes.

        Builds a sequence of bounding boxes (tail node → inter-rank
        corridors → head node) and fits a cubic Bezier through the
        corridor center line.  Mirrors the box-corridor approach of
        Graphviz ``dotsplines.c:make_regular_edge()``.
        """
        p1 = self._edge_start_point(le, tail, head)
        p2 = self._edge_end_point(le, head, tail)

        rank_diff = abs(head.rank - tail.rank)
        is_lr = self.rankdir in ("LR", "RL")

        # Compute the perpendicular extension distance for control points.
        # This makes the edge leave and enter the node at 90 degrees.
        if is_lr:
            gap = abs(p2[0] - p1[0])
        else:
            gap = abs(p2[1] - p1[1])
        ext = max(gap * 0.3, 20.0)  # at least 20pt extension

        if rank_diff <= 1:
            # Simple 4-point cubic Bezier with perpendicular tangents.
            le.spline_type = "bezier"
            if is_lr:
                # LR: edges flow left-to-right (increasing X).
                # Control points extend horizontally from each endpoint.
                return [
                    p1,
                    (p1[0] + ext, p1[1]),
                    (p2[0] - ext, p2[1]),
                    p2,
                ]
            else:
                # TB: edges flow top-to-bottom (increasing Y).
                # Control points extend vertically from each endpoint.
                return [
                    p1,
                    (p1[0], p1[1] + ext),
                    (p2[0], p2[1] - ext),
                    p2,
                ]

        # Multi-rank: build waypoints at inter-rank crossings,
        # then fit a Bezier through them.
        waypoints = [p1]
        lower_r = min(tail.rank, head.rank)
        upper_r = max(tail.rank, head.rank)

        for r in range(lower_r, upper_r):
            t = (r - lower_r + 0.5) / rank_diff
            if is_lr:
                ix = p1[0] + t * (p2[0] - p1[0])
                iy = p1[1] + t * (p2[1] - p1[1])
            else:
                ix = p1[0] + t * (p2[0] - p1[0])
                rbox = self._rank_box(r)
                iy = (rbox[1] + rbox[3]) / 2.0
            waypoints.append((ix, iy))

        waypoints.append(p2)

        # For multi-rank, _to_bezier will convert to smooth cubics.
        # Override first and last control points for perpendicular entry/exit.
        if len(waypoints) >= 4:
            le.spline_type = "bezier"
            if is_lr:
                # Force perpendicular tangents at endpoints
                waypoints[1] = (p1[0] + ext, waypoints[1][1])
                waypoints[-2] = (p2[0] - ext, waypoints[-2][1])
            else:
                waypoints[1] = (waypoints[1][0], p1[1] + ext)
                waypoints[-2] = (waypoints[-2][0], p2[1] - ext)

        return waypoints

    def _classify_flat_edge(self, le: LayoutEdge, tail: LayoutNode,
                            head: LayoutNode) -> str:
        """Classify a flat edge into a routing variant.

        Returns one of: 'adjacent', 'labeled', 'bottom', 'top' (default).
        Mirrors Graphviz ``dotsplines.c:make_flat_edge()`` dispatch.
        """
        is_adjacent = abs(tail.order - head.order) == 1

        if is_adjacent and not le.tailport and not le.headport:
            return "adjacent"

        if le.label and hasattr(le, '_flat_label_vnode'):
            return "labeled"

        # Check port sides for bottom routing
        for port in (le.tailport, le.headport):
            if port:
                compass = port.split(":")[-1] if ":" in port else port
                if compass in ("s", "sw", "se"):
                    return "bottom"

        return "top"

    def _count_flat_edge_index(self, le: LayoutEdge) -> int:
        """Count how many flat edges between the same pair come before this one."""
        idx = 0
        for other in self.ledges:
            if other is le:
                return idx
            if other.virtual:
                continue
            t = self.lnodes.get(other.tail_name)
            h = self.lnodes.get(other.head_name)
            if t and h and t.rank == h.rank:
                if ((other.tail_name == le.tail_name and
                     other.head_name == le.head_name) or
                    (other.tail_name == le.head_name and
                     other.head_name == le.tail_name)):
                    idx += 1
        return idx

    def _flat_edge_route(self, le: LayoutEdge, tail: LayoutNode,
                         head: LayoutNode) -> list[tuple[float, float]]:
        """Route a same-rank edge using the appropriate variant.

        Dispatches to one of four routing strategies matching Graphviz
        ``dotsplines.c:make_flat_edge()``:

        1. **adjacent** — straight bezier for nodes next to each other
        2. **labeled** — route through the label dummy node
        3. **bottom** — arc below the rank (south ports)
        4. **top** (default) — arc above the rank with multi-edge staggering
        """
        variant = self._classify_flat_edge(le, tail, head)
        p1 = self._edge_start_point(le, tail, head)
        p2 = self._edge_end_point(le, head, tail)
        le.spline_type = "bezier"

        if variant == "adjacent":
            return self._flat_adjacent(le, p1, p2, tail, head)
        elif variant == "labeled":
            return self._flat_labeled(le, p1, p2, tail, head)
        elif variant == "bottom":
            return self._flat_arc(le, p1, p2, tail, head, direction=1)
        else:  # "top"
            return self._flat_arc(le, p1, p2, tail, head, direction=-1)

    def _flat_adjacent(self, le: LayoutEdge, p1, p2,
                       tail: LayoutNode, head: LayoutNode):
        """Route a flat edge between adjacent nodes as a straight bezier.

        For multi-edges between the same pair, distributes y-offsets
        across the node height (Graphviz ``makeSimpleFlat``).
        """
        idx = self._count_flat_edge_index(le)
        if idx == 0:
            # Single or first edge: straight line
            return [
                p1,
                ((2 * p1[0] + p2[0]) / 3, p1[1]),
                ((p1[0] + 2 * p2[0]) / 3, p2[1]),
                p2,
            ]
        # Multi-edge: offset y by distributing across node height
        max_h = min(tail.height, head.height) / 2
        dy = max_h * (idx / (idx + 1)) * (-1 if idx % 2 == 0 else 1)
        return [
            (p1[0], p1[1] + dy),
            ((2 * p1[0] + p2[0]) / 3, p1[1] + dy),
            ((p1[0] + 2 * p2[0]) / 3, p2[1] + dy),
            (p2[0], p2[1] + dy),
        ]

    def _flat_labeled(self, le: LayoutEdge, p1, p2,
                      tail: LayoutNode, head: LayoutNode):
        """Route a flat edge through its label dummy node.

        The label node was inserted in the rank above by
        ``_insert_flat_label_nodes``.  The edge routes up to the label
        node's Y, across, and back down.
        """
        vn_name = getattr(le, '_flat_label_vnode', None)
        if not vn_name or vn_name not in self.lnodes:
            # Fallback to top arc
            return self._flat_arc(le, p1, p2, tail, head, direction=-1)

        vn = self.lnodes[vn_name]
        label_y = vn.y
        return [
            p1,
            (p1[0], label_y),
            (p2[0], label_y),
            p2,
        ]

    def _flat_arc(self, le: LayoutEdge, p1, p2,
                  tail: LayoutNode, head: LayoutNode,
                  direction: int):
        """Route a flat edge as an arc above (direction=-1) or below (+1).

        Multi-edge staggering uses ``stepx`` and ``stepy`` proportional
        to ``Multisep`` (= nodesep) and available vertical space.
        Mirrors Graphviz 3-box corridor approach.
        """
        dx = abs(p2[0] - p1[0])
        r = tail.rank

        # Compute available vertical space to the adjacent rank
        if direction < 0:
            # Above: space to rank r-1
            prev_r = r - 1
            if prev_r in self.ranks and self.ranks[prev_r]:
                prev_y = self.lnodes[self.ranks[prev_r][0]].y
                vspace = abs(tail.y - prev_y) - self._rank_ht1.get(prev_r, 18)
            else:
                vspace = self.ranksep
        else:
            # Below: space to rank r+1
            next_r = r + 1
            if next_r in self.ranks and self.ranks[next_r]:
                next_y = self.lnodes[self.ranks[next_r][0]].y
                vspace = abs(next_y - tail.y) - self._rank_ht2.get(next_r, 18)
            else:
                vspace = self.ranksep

        vspace = max(vspace, 20.0)

        # Multi-edge staggering
        idx = self._count_flat_edge_index(le)
        # Count total parallel flat edges for this pair
        total = idx + 1
        for other in self.ledges:
            if other is le or other.virtual:
                continue
            if ((other.tail_name == le.tail_name and
                 other.head_name == le.head_name) or
                (other.tail_name == le.head_name and
                 other.head_name == le.tail_name)):
                ot = self.lnodes.get(other.tail_name)
                oh = self.lnodes.get(other.head_name)
                if ot and oh and ot.rank == oh.rank:
                    total += 1

        multisep = self.nodesep
        stepx = multisep / (total + 1)
        stepy = vspace / (total + 1)

        # Arc height based on index and available space
        arc_height = max(dx * 0.22, 20.0) + (idx + 1) * stepy
        arc_height = min(arc_height, vspace * 0.8)

        arc_y = p1[1] + direction * arc_height

        return [
            p1,
            (p1[0] + direction * (idx + 1) * stepx * 0.5, arc_y),
            (p2[0] - direction * (idx + 1) * stepx * 0.5, arc_y),
            p2,
        ]

    # ── Write-back and output ────────────────────

    def _write_back(self):
        """Write layout results back to graph object attributes.

        Sets ``pos``, ``width``, ``height`` on each node so that the
        graph can be serialized with embedded layout coordinates
        (matching Graphviz ``attach_attrs()`` behavior).
        """
        for name, ln in self.lnodes.items():
            if ln.virtual:
                continue
            ln.node.compound_node_data.x = ln.x
            ln.node.compound_node_data.y = ln.y
            ln.node.compound_node_data.rank = ln.rank
            # Write layout coords back to DOT attributes
            ln.node.agset("pos", f"{round(ln.x, 2)},{round(ln.y, 2)}")
            ln.node.agset("width", str(round(ln.width / 72.0, 4)))
            ln.node.agset("height", str(round(ln.height / 72.0, 4)))

        # Write edge spline points back
        all_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges
        for le in all_edges:
            if le.edge and le.points:
                parts = []
                for i, pt in enumerate(le.points):
                    if i == 0:
                        parts.append(f"s,{round(pt[0], 2)},{round(pt[1], 2)}")
                    elif i == len(le.points) - 1:
                        parts.append(f"e,{round(pt[0], 2)},{round(pt[1], 2)}")
                    else:
                        parts.append(f"{round(pt[0], 2)},{round(pt[1], 2)}")
                le.edge.agset("pos", " ".join(parts))

        # Write graph bounding box
        real = [ln for ln in self.lnodes.values() if not ln.virtual]
        if real:
            bb = (
                round(min(ln.x - ln.width / 2 for ln in real), 2),
                round(min(ln.y - ln.height / 2 for ln in real), 2),
                round(max(ln.x + ln.width / 2 for ln in real), 2),
                round(max(ln.y + ln.height / 2 for ln in real), 2),
            )
            self.graph.set_graph_attr("bb", f"{bb[0]},{bb[1]},{bb[2]},{bb[3]}")

    def _to_json(self) -> dict:
        real_nodes = {n: ln for n, ln in self.lnodes.items() if not ln.virtual}
        if real_nodes:
            min_x = min(ln.x - ln.width / 2 for ln in real_nodes.values())
            min_y = min(ln.y - ln.height / 2 for ln in real_nodes.values())
            max_x = max(ln.x + ln.width / 2 for ln in real_nodes.values())
            max_y = max(ln.y + ln.height / 2 for ln in real_nodes.values())
        else:
            min_x = min_y = max_x = max_y = 0

        # Expand bb to include cluster bounding boxes (which include margins)
        for cl in self._clusters:
            if cl.bb:
                cx1, cy1, cx2, cy2 = cl.bb
                min_x = min(min_x, cx1)
                min_y = min(min_y, cy1)
                max_x = max(max_x, cx2)
                max_y = max(max_y, cy2)

        # Expand bb to include edge routing points and arrowheads
        for le in self.ledges:
            if le.points:
                for px, py in le.points:
                    min_x = min(min_x, px)
                    min_y = min(min_y, py)
                    max_x = max(max_x, px)
                    max_y = max(max_y, py)

        # Expand bb to include xlabel / label positions
        for le in self.ledges:
            if le.label_pos:
                lx, ly = le.label_pos
                # Rough estimate for label extent
                lw = len(le.label or "") * 4.0
                lh = 10.0
                min_x = min(min_x, lx - lw)
                min_y = min(min_y, ly - lh)
                max_x = max(max_x, lx + lw)
                max_y = max(max_y, ly + lh)

        nodes_json = []
        for name, ln in real_nodes.items():
            entry: dict = {
                "name": name,
                "x": round(ln.x, 2),
                "y": round(ln.y, 2),
                "width": round(ln.width, 2),
                "height": round(ln.height, 2),
            }
            if ln.node:
                # Pass through visual and layout attributes for rendering
                for attr in ("shape", "label", "color", "fillcolor", "fontcolor",
                             "fontname", "fontsize", "style", "penwidth",
                             "fixedsize", "orientation", "sides", "distortion",
                             "skew", "regular", "peripheries", "nojustify",
                             "labelloc", "xlabel", "image", "imagescale", "imagepos",
                             "_xlabel_pos_x", "_xlabel_pos_y",
                             "tooltip", "URL", "href", "target", "id", "class",
                             "comment", "colorscheme", "gradientangle"):
                    val = ln.node.attributes.get(attr)
                    if val:
                        entry[attr] = val
            # Pass rankdir so the renderer knows record field orientation
            entry["_rankdir"] = self.rankdir
            # Include record port positions from Node.record_fields
            if ln.node and ln.node.record_fields is not None:
                rf = ln.node.record_fields
                ports_dict = {}
                rd_int = self._rankdir_int()
                def _collect_port_fracs(f):
                    if f.port:
                        frac = rf.port_fraction(f.port, rankdir=rd_int)
                        if frac is not None:
                            ports_dict[f.port] = frac
                    for c in f.children:
                        _collect_port_fracs(c)
                _collect_port_fracs(rf)
                if ports_dict:
                    entry["record_ports"] = ports_dict
            nodes_json.append(entry)

        edges_json = []
        all_output_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges
        for le in all_output_edges:
            t, h = le.tail_name, le.head_name
            if le.reversed:
                t, h = h, t
            edge_entry: dict = {
                "tail": t,
                "head": h,
                "points": [[round(x, 2), round(y, 2)] for x, y in le.points],
            }
            if le.label:
                edge_entry["label"] = le.label
            if le.label_pos:
                edge_entry["label_pos"] = list(le.label_pos)
            if le.lhead:
                edge_entry["lhead"] = le.lhead
            if le.ltail:
                edge_entry["ltail"] = le.ltail
            if le.spline_type != "polyline":
                edge_entry["spline_type"] = le.spline_type
            # Pass through visual and layout attributes for rendering
            if le.edge:
                for attr in ("color", "fontcolor", "fontname", "fontsize",
                             "style", "penwidth", "arrowhead", "arrowtail", "dir",
                             "arrowsize", "decorate", "headlabel", "taillabel",
                             "labelfloat", "labelfontcolor", "labelfontname",
                             "labelfontsize", "nojustify",
                             "_headlabel_pos_x", "_headlabel_pos_y",
                             "_taillabel_pos_x", "_taillabel_pos_y",
                             "tooltip", "URL", "href", "target", "id", "class",
                             "comment", "colorscheme",
                             "edgeURL", "edgehref", "edgetarget", "edgetooltip",
                             "headURL", "headhref", "headtarget", "headtooltip",
                             "labelURL", "labelhref", "labeltarget", "labeltooltip",
                             "tailURL", "tailhref", "tailtarget", "tailtooltip"):
                    val = le.edge.attributes.get(attr)
                    if val:
                        edge_entry[attr] = val
            edges_json.append(edge_entry)

        clusters_json = []
        for cl in self._clusters:
            if cl.nodes:
                cl_entry: dict = {
                    "name": cl.name,
                    "label": cl.label,
                    "bb": [round(v, 2) for v in cl.bb],
                    "nodes": cl.nodes,
                }
                cl_entry.update(cl.attrs)
                clusters_json.append(cl_entry)

        graph_meta: dict = {
            "name": self.graph.name,
            "directed": self.graph.directed,
            "bb": [round(min_x, 2), round(min_y, 2),
                   round(max_x, 2), round(max_y, 2)],
        }
        if self.ratio:
            graph_meta["ratio"] = self.ratio
        if self.graph_size:
            graph_meta["size"] = [round(v, 2) for v in self.graph_size]
        if self.dpi != 96.0:
            graph_meta["dpi"] = self.dpi
        if self.pad != 4.0:
            graph_meta["pad"] = round(self.pad, 2)
        if self.outputorder != "breadthfirst":
            graph_meta["outputorder"] = self.outputorder
        # Pass through graph-level visual attributes
        for attr in ("bgcolor", "label", "labelloc", "labeljust",
                     "fontname", "fontsize", "fontcolor", "stylesheet",
                     "tooltip", "URL", "href", "target", "id", "class",
                     "comment", "colorscheme", "gradientangle",
                     "_label_pos_x", "_label_pos_y"):
            val = self.graph.get_graph_attr(attr)
            if val:
                graph_meta[attr] = val

        result: dict = {
            "graph": graph_meta,
            "nodes": nodes_json,
            "edges": edges_json,
        }
        if clusters_json:
            result["clusters"] = clusters_json
        return result


# ── Backward-compatibility alias ─────────────────────────────────
# ``DotLayout`` was the original class name; ``DotGraphInfo`` is the
# new name matching C's Agraphinfo_t convention and the GraphView
# architecture (gvpy/core/graph_view.py).  Keep the alias so existing
# imports ``from gvpy.engines.dot import DotLayout`` continue to work.
DotLayout = DotGraphInfo
