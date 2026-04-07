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
    from gvpy.engines.dot import DotLayout

    # From a file
    graph = read_gv_file("input.gv")
    result = DotLayout(graph).layout()   # returns a JSON-serializable dict

    # From a string
    graph = read_gv('digraph G { a -> b -> c; }')
    result = DotLayout(graph).layout()

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

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

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
    """Network simplex algorithm for optimal ranking / positioning."""

    SEARCH_LIMIT = 30

    def __init__(self, node_names: list[str], edges: list[tuple[str, str, int, int]]):
        """edges: list of (tail, head, minlen, weight)"""
        self.node_names = list(node_names)
        self.edges = list(edges)  # [(tail, head, minlen, weight), ...]
        self.rank: dict[str, int] = {}
        self._tree: set[int] = set()  # edge indices in spanning tree
        self._cut: dict[int, int] = {}  # edge index -> cut value
        self._par: dict[str, int] = {}  # node -> parent edge index
        self._low: dict[str, int] = {}
        self._lim: dict[str, int] = {}
        self._si = 0  # search start index for leave_edge

        # Precompute adjacency
        self._out: dict[str, list[int]] = defaultdict(list)
        self._inc: dict[str, list[int]] = defaultdict(list)
        for i, (t, h, ml, w) in enumerate(self.edges):
            self._out[t].append(i)
            self._inc[h].append(i)

    def _slack(self, ei: int) -> int:
        t, h, ml, w = self.edges[ei]
        return self.rank[h] - self.rank[t] - ml

    def _in_tree(self, ei: int) -> bool:
        return ei in self._tree

    # ── Initial feasible ranking ─────────────────

    def _init_rank(self):
        in_deg = {n: 0 for n in self.node_names}
        for t, h, ml, w in self.edges:
            in_deg[h] += 1
        self.rank = {n: 0 for n in self.node_names}
        queue = deque(n for n in self.node_names if in_deg[n] == 0)
        if not queue:
            queue = deque(self.node_names)
        visited = set()
        while queue:
            u = queue.popleft()
            if u in visited:
                continue
            visited.add(u)
            for ei in self._out[u]:
                t, h, ml, w = self.edges[ei]
                nr = self.rank[u] + ml
                if nr > self.rank[h]:
                    self.rank[h] = nr
                in_deg[h] -= 1
                if in_deg[h] <= 0 and h not in visited:
                    queue.append(h)
        for n in self.node_names:
            if n not in visited:
                self.rank[n] = 0

    # ── Spanning tree construction ───────────────

    def _feasible_tree(self):
        self._tree.clear()
        in_tree = set()  # nodes in tree

        # Add all tight edges (slack=0) greedily via BFS
        if self.node_names:
            start = self.node_names[0]
            in_tree.add(start)
            changed = True
            while changed:
                changed = False
                for ei in range(len(self.edges)):
                    if self._in_tree(ei):
                        continue
                    t, h, ml, w = self.edges[ei]
                    if self._slack(ei) == 0:
                        if t in in_tree and h not in in_tree:
                            self._tree.add(ei)
                            in_tree.add(h)
                            changed = True
                        elif h in in_tree and t not in in_tree:
                            self._tree.add(ei)
                            in_tree.add(t)
                            changed = True

        # If tree doesn't span, add minimum-slack edges and adjust ranks
        while len(in_tree) < len(self.node_names):
            best_ei = None
            best_slack = None
            for ei in range(len(self.edges)):
                if self._in_tree(ei):
                    continue
                t, h, ml, w = self.edges[ei]
                t_in = t in in_tree
                h_in = h in in_tree
                if t_in != h_in:  # exactly one endpoint in tree
                    s = abs(self._slack(ei))
                    if best_slack is None or s < best_slack:
                        best_slack = s
                        best_ei = ei

            if best_ei is None:
                # Disconnected component — add an isolated node
                for n in self.node_names:
                    if n not in in_tree:
                        in_tree.add(n)
                        break
                continue

            t, h, ml, w = self.edges[best_ei]
            delta = self._slack(best_ei)
            if t in in_tree and h not in in_tree:
                # h needs to come closer: decrease rank[h] by delta
                # Actually adjust the component not in tree
                self.rank[h] -= delta
            elif h in in_tree and t not in in_tree:
                self.rank[t] += delta
            self._tree.add(best_ei)
            in_tree.add(t)
            in_tree.add(h)

            # Try adding more tight edges
            changed = True
            while changed:
                changed = False
                for ei in range(len(self.edges)):
                    if self._in_tree(ei):
                        continue
                    t2, h2, ml2, w2 = self.edges[ei]
                    if self._slack(ei) == 0:
                        if t2 in in_tree and h2 not in in_tree:
                            self._tree.add(ei)
                            in_tree.add(h2)
                            changed = True
                        elif h2 in in_tree and t2 not in in_tree:
                            self._tree.add(ei)
                            in_tree.add(t2)
                            changed = True

    # ── DFS range for subtree queries ────────────

    def _dfs_range(self):
        if not self.node_names:
            return
        # Build tree adjacency
        tree_adj: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for ei in self._tree:
            t, h, ml, w = self.edges[ei]
            tree_adj[t].append((ei, h))
            tree_adj[h].append((ei, t))

        root = self.node_names[0]
        self._par = {root: -1}
        self._low = {}
        self._lim = {}
        counter = [0]

        stack = [(root, None, False)]
        while stack:
            node, parent_edge, returning = stack[-1]
            if not returning:
                self._low[node] = counter[0]
                counter[0] += 1
                stack[-1] = (node, parent_edge, True)
                for ei, nbr in tree_adj[node]:
                    if nbr not in self._par or (ei != self._par.get(node, -1) and nbr not in self._lim):
                        self._par[nbr] = ei
                        stack.append((nbr, ei, False))
            else:
                self._lim[node] = counter[0]
                counter[0] += 1
                stack.pop()

    def _in_subtree(self, u: str, root: str) -> bool:
        return self._low[root] <= self._low[u] <= self._lim[root]

    # ── Cut values ───────────────────────────────

    def _init_cutvalues(self):
        self._dfs_range()
        self._cut.clear()
        for ei in self._tree:
            self._cut[ei] = self._compute_cut_value(ei)

    def _compute_cut_value(self, tree_ei: int) -> int:
        t, h, ml, w = self.edges[tree_ei]
        # Determine which side is the "tail component" vs "head component"
        # The head side is the subtree rooted at the node farther from root
        if self._lim.get(t, 0) < self._lim.get(h, 0):
            sub_root = t  # t's subtree is the smaller component
            direction = 1
        else:
            sub_root = h
            direction = -1

        cv = 0
        for ei in range(len(self.edges)):
            et, eh, eml, ew = self.edges[ei]
            t_in = self._in_subtree(et, sub_root)
            h_in = self._in_subtree(eh, sub_root)
            if t_in != h_in:
                # Edge crosses the cut
                if t_in:
                    cv += ew * direction
                else:
                    cv -= ew * direction
        return cv

    # ── Pivot operations ─────────────────────────

    def _leave_edge(self) -> Optional[int]:
        best = None
        best_cv = 0
        count = 0
        tree_list = list(self._tree)
        n = len(tree_list)
        if n == 0:
            return None
        start = self._si % n
        for offset in range(n):
            idx = (start + offset) % n
            ei = tree_list[idx]
            cv = self._cut.get(ei, 0)
            if cv < best_cv:
                best_cv = cv
                best = ei
                count += 1
                if count >= self.SEARCH_LIMIT:
                    self._si = (start + offset + 1) % n
                    return best
        self._si = 0
        return best

    def _enter_edge(self, leaving_ei: int) -> Optional[int]:
        t, h, ml, w = self.edges[leaving_ei]
        if self._lim.get(t, 0) < self._lim.get(h, 0):
            sub_root = t
        else:
            sub_root = h

        best = None
        best_slack = None
        for ei in range(len(self.edges)):
            if self._in_tree(ei):
                continue
            et, eh, eml, ew = self.edges[ei]
            t_in = self._in_subtree(et, sub_root)
            h_in = self._in_subtree(eh, sub_root)
            if t_in != h_in:
                s = self._slack(ei)
                if s >= 0 and (best_slack is None or s < best_slack):
                    best_slack = s
                    best = ei
        return best

    def _update(self, leaving_ei: int, entering_ei: int):
        # Adjust ranks
        delta = self._slack(entering_ei)
        if delta != 0:
            et, eh, eml, ew = self.edges[leaving_ei]
            if self._lim.get(et, 0) < self._lim.get(eh, 0):
                sub_root = et
            else:
                sub_root = eh
            for n in self.node_names:
                if self._in_subtree(n, sub_root):
                    self.rank[n] -= delta

        # Exchange tree edges
        self._tree.discard(leaving_ei)
        self._tree.add(entering_ei)

        # Recompute DFS ranges and cut values
        self._init_cutvalues()

    # ── Normalize ────────────────────────────────

    def _normalize(self):
        if not self.rank:
            return
        min_r = min(self.rank.values())
        if min_r != 0:
            for n in self.rank:
                self.rank[n] -= min_r

    # ── Main entry point ─────────────────────────

    def solve(self, max_iter: int = 200) -> dict[str, int]:
        if not self.node_names:
            return {}
        self._init_rank()
        if len(self.node_names) <= 1:
            self._normalize()
            return dict(self.rank)
        # Connect disconnected components with zero-weight edges
        self._connect_components()
        if not self.edges:
            self._normalize()
            return dict(self.rank)
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
        return dict(self.rank)

    def _connect_components(self):
        """Add zero-weight edges between disconnected components."""
        adj: dict[str, set[str]] = defaultdict(set)
        for t, h, ml, w in self.edges:
            adj[t].add(h)
            adj[h].add(t)
        visited = set()
        components = []
        for n in self.node_names:
            if n in visited:
                continue
            comp = []
            queue = deque([n])
            while queue:
                u = queue.popleft()
                if u in visited:
                    continue
                visited.add(u)
                comp.append(u)
                for v in adj[u]:
                    if v not in visited:
                        queue.append(v)
            components.append(comp)
        # Link components with dummy edges
        for i in range(1, len(components)):
            t = components[i - 1][0]
            h = components[i][0]
            dummy = (t, h, 0, 0)
            self.edges.append(dummy)
            idx = len(self.edges) - 1
            self._out[t].append(idx)
            self._inc[h].append(idx)


# ── Record label parsing ─────────────────────────

def _parse_record_fields(label: str) -> list[dict]:
    """Parse a record label into a list of field dicts.

    Each field has: {"text": str, "port": str, "children": list[dict]}
    Handles | separators and {} sub-grouping.
    Example: "<p1> A|{<p2> B|<p3> C}|D"
    """
    fields = []
    depth = 0
    current = ""
    # Split on | at top level only (not inside {})
    for ch in label:
        if ch == "{":
            depth += 1
            current += ch
        elif ch == "}":
            depth -= 1
            current += ch
        elif ch == "|" and depth == 0:
            fields.append(_parse_one_field(current.strip()))
            current = ""
        else:
            current += ch
    if current.strip():
        fields.append(_parse_one_field(current.strip()))
    return fields


def _parse_one_field(text: str) -> dict:
    """Parse a single record field, which may contain {sub|fields}."""
    port = ""
    children = []

    # Check for port: "<portname> text"
    if text.startswith("<"):
        end = text.find(">")
        if end > 0:
            port = text[1:end].strip()
            text = text[end + 1:].strip()

    # Check for sub-fields: {a|b|c}
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1]
        children = _parse_record_fields(inner)
        text = ""

    return {"text": text, "port": port, "children": children}


def _parse_record_ports(label: str) -> dict[str, float]:
    """Parse record label and return port positions as x-fractions [0..1].

    Returns {port_name: x_fraction} for each port defined with <portname>.
    """
    fields = _parse_record_fields(label)
    if not fields:
        return {}
    ports = {}
    n = len(fields)
    for i, f in enumerate(fields):
        frac = (i + 0.5) / n  # center of field
        if f["port"]:
            ports[f["port"]] = frac
        # Also scan children for ports
        if f["children"]:
            for j, child in enumerate(f["children"]):
                if child["port"]:
                    ports[child["port"]] = frac
    return ports


# ── Layout engine ────────────────────────────────

class DotLayout(LayoutEngine):
    """Hierarchical (dot) layout for directed and undirected graphs."""

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
        self.remincross: bool = False
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
        self._record_ports: dict[str, dict[str, float]] = {}  # node -> {port: x_fraction}

    # ── Public API ───────────────────────────────

    def layout(self) -> dict:
        """Run the full layout pipeline and return a JSON-serializable dict."""
        self._init_from_graph()

        # Component packing: if graph has disconnected components,
        # lay out each one separately and pack them side by side.
        components = self._find_components()
        if len(components) > 1:
            return self._pack_components(components)

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

            result = DotLayout(sub_graph).layout()
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
        """Scan subgraphs for cluster_* names and record membership."""
        self._clusters = []
        if self.clusterrank != "none":
            self._scan_clusters(self.graph)

    def _all_nodes_recursive(self, sub) -> list[str]:
        """Collect all node names from a subgraph and its descendants."""
        names = [n for n in sub.nodes if n in self.lnodes]
        for child in sub.subgraphs.values():
            names.extend(self._all_nodes_recursive(child))
        return names

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

    def _compute_cluster_boxes(self):
        """Compute bounding boxes for clusters from positioned nodes."""
        for cl in self._clusters:
            members = [self.lnodes[n] for n in cl.nodes if n in self.lnodes]
            if not members:
                continue
            min_x = min(ln.x - ln.width / 2 for ln in members) - cl.margin
            min_y = min(ln.y - ln.height / 2 for ln in members) - cl.margin
            max_x = max(ln.x + ln.width / 2 for ln in members) + cl.margin
            max_y = max(ln.y + ln.height / 2 for ln in members) + cl.margin
            cl.bb = (min_x, min_y, max_x, max_y)

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

        is_lr = self.rankdir in ("LR", "RL")
        for _parent, siblings in children_of.items():
            leaf_sibs = [s for s in siblings if s not in has_children]
            if len(leaf_sibs) < 2:
                continue
            sib_cls = [cl_by_name[s] for s in leaf_sibs if cl_by_name[s].bb]
            if len(sib_cls) < 2:
                continue

            if is_lr:
                sib_cls.sort(key=lambda c: c.bb[1])
                for i in range(len(sib_cls) - 1):
                    c1 = sib_cls[i]
                    c2 = sib_cls[i + 1]
                    overlap_val = c1.bb[3] + gap - c2.bb[1]
                    if overlap_val > 0:
                        for sib in sib_cls[i + 1:]:
                            for name in node_sets.get(sib.name, set()):
                                if name in self.lnodes:
                                    self.lnodes[name].y += overlap_val
            else:
                sib_cls.sort(key=lambda c: c.bb[0])
                for i in range(len(sib_cls) - 1):
                    c1 = sib_cls[i]
                    c2 = sib_cls[i + 1]
                    overlap_val = c1.bb[2] + gap - c2.bb[0]
                    if overlap_val > 0:
                        for sib in sib_cls[i + 1:]:
                            for name in node_sets.get(sib.name, set()):
                                if name in self.lnodes:
                                    self.lnodes[name].x += overlap_val

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

        # Record shapes: parse fields to determine dimensions and store port info
        if shape in ("record", "Mrecord"):
            w, h = self._record_size(label, fontsize, char_w)
            # Parse and store port positions on the node
            self._record_ports[name] = _parse_record_ports(label)
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
        """
        from gvpy.render.svg_renderer import _parse_record_label
        tree = _parse_record_label(label)
        # Always compute in TB coordinates (horizontal=True).  The layout
        # engine works internally in TB space; _apply_rankdir swaps x/y
        # and w/h at the end for LR/RL/BT.
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
        self._break_cycles()
        self._classify_edges()
        if self.newrank or self.clusterrank == "none":
            # Global ranking: all nodes in one pass (ignores cluster boundaries)
            self._network_simplex_rank()
        else:
            # Per-cluster ranking: rank cluster nodes independently, then merge
            self._cluster_aware_rank()
        self._apply_rank_constraints()
        self._compact_ranks()
        self._add_virtual_nodes()
        self._build_ranks()
        self._classify_flat_edges()

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
        """Rank nodes with cluster-aware ordering.

        Nodes inside cluster subgraphs are ranked independently within
        their cluster first, then cluster ranks are mapped into the global
        ranking space. Nodes not in any cluster are ranked globally.
        """
        if not self._clusters:
            self._network_simplex_rank()
            return

        # When clusters are deeply nested (max depth > 2), the per-cluster
        # ranking + offset merging produces poor results because most edges
        # become "inter-cluster". Fall back to global ranking which handles
        # deeply nested structures correctly.
        max_depth = max(
            (n.count("/") + 1 if "/" in n else 1)
            for cl in self._clusters for n in cl.nodes
        ) if self._clusters else 0
        # Also fall back when many clusters share nodes (nested hierarchy)
        nodes_in_multiple = sum(
            1 for n in self.lnodes
            if sum(1 for cl in self._clusters if n in cl.nodes) > 1
        )
        if nodes_in_multiple > len(self.lnodes) * 0.3:
            self._network_simplex_rank()
            return

        # Identify which nodes belong to each cluster
        cluster_nodes: dict[str, set[str]] = {}
        node_to_cluster: dict[str, str] = {}
        for cl in self._clusters:
            cluster_nodes[cl.name] = set(cl.nodes)
            for n in cl.nodes:
                if n not in node_to_cluster:  # first cluster wins
                    node_to_cluster[n] = cl.name

        # Rank each cluster independently
        cluster_max_rank: dict[str, int] = {}
        for cl_name, cl_members in cluster_nodes.items():
            if not cl_members:
                continue
            # Get edges internal to this cluster
            cl_edges = [(le.tail_name, le.head_name, le.minlen, le.weight)
                        for le in self.ledges
                        if le.constraint and le.tail_name in cl_members and le.head_name in cl_members]
            ns = _NetworkSimplex(list(cl_members), cl_edges)
            ns.SEARCH_LIMIT = self.searchsize
            ranks = ns.solve(max_iter=self.nslimit1)
            for n, r in ranks.items():
                if n in self.lnodes:
                    self.lnodes[n].rank = r
            cluster_max_rank[cl_name] = max(ranks.values()) if ranks else 0

        # Rank non-cluster nodes globally
        non_cluster = [n for n in self.lnodes if n not in node_to_cluster]
        if non_cluster:
            nc_edges = [(le.tail_name, le.head_name, le.minlen, le.weight)
                        for le in self.ledges
                        if le.constraint and le.tail_name in non_cluster and le.head_name in non_cluster]
            ns = _NetworkSimplex(non_cluster, nc_edges)
            ns.SEARCH_LIMIT = self.searchsize
            ranks = ns.solve(max_iter=self.nslimit1)
            for n, r in ranks.items():
                if n in self.lnodes:
                    self.lnodes[n].rank = r

        # Merge cluster ranks into global space:
        # Assign each cluster a base rank offset based on inter-cluster edges
        # Simple approach: offset each cluster's ranks based on edges connecting
        # cluster nodes to non-cluster nodes
        self._merge_cluster_ranks(cluster_nodes, node_to_cluster)

    def _merge_cluster_ranks(self, cluster_nodes: dict[str, set[str]],
                             node_to_cluster: dict[str, str]):
        """Adjust cluster-internal ranks to fit into global ranking space."""
        # For each inter-cluster edge, determine the required offset
        # between the source and target clusters/nodes
        offsets: dict[str, int] = {}  # cluster_name -> rank offset

        for le in self.ledges:
            if not le.constraint:
                continue
            t_cl = node_to_cluster.get(le.tail_name)
            h_cl = node_to_cluster.get(le.head_name)
            if t_cl == h_cl:
                continue  # internal edge, already ranked

            t_rank = self.lnodes[le.tail_name].rank if le.tail_name in self.lnodes else 0
            h_rank = self.lnodes[le.head_name].rank if le.head_name in self.lnodes else 0

            # Need: (h_rank + h_offset) - (t_rank + t_offset) >= minlen
            t_off = offsets.get(t_cl, 0) if t_cl else 0
            h_off = offsets.get(h_cl, 0) if h_cl else 0
            needed = (t_rank + t_off) + le.minlen - h_rank
            if h_cl and needed > h_off:
                offsets[h_cl] = needed

        # Apply offsets to cluster nodes
        for cl_name, offset in offsets.items():
            if offset == 0:
                continue
            for n in cluster_nodes.get(cl_name, []):
                if n in self.lnodes:
                    self.lnodes[n].rank += offset

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
        self.ranks = defaultdict(list)
        for name, ln in self.lnodes.items():
            self.ranks[ln.rank].append(name)

    # ── Phase 2: Crossing minimization ───────────

    def _phase2_ordering(self):
        if not self.ranks:
            return

        for rank_nodes in self.ranks.values():
            for i, name in enumerate(rank_nodes):
                self.lnodes[name].order = i

        # ordering=out preserves input order — skip crossing minimization
        if self.ordering in ("out", "in"):
            return

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

        # Optional second pass (remincross)
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

        # Enforce flat-edge ordering: tails left of heads
        self._flat_reorder()

        # Recursively run mincross within each cluster (Graphviz
        # mincross_clust), then enforce cluster contiguity.
        self._cluster_group_ordering()
        self._mincross_within_clusters()
        self._cluster_group_ordering()  # restore contiguity after

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

    def _mincross_within_clusters(self):
        """Recursively run crossing minimization within each cluster.

        Mirrors Graphviz ``mincross_clust()``: for each cluster, restrict
        the median/transpose sweeps to the cluster's node subset within
        its rank range.  Processes depth-first so inner clusters are
        optimized before their parents.
        """
        if not self._clusters:
            return

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

        def _mincross_clust(cl_name: str):
            """Run mincross within a cluster, then recurse into children."""
            cl_nodes = node_sets[cl_name]
            if len(cl_nodes) < 2:
                # Recurse into children even for small clusters
                for child in children_of.get(cl_name, []):
                    _mincross_clust(child)
                return

            # Find the rank range this cluster spans
            cl_ranks = set()
            for n in cl_nodes:
                if n in self.lnodes:
                    cl_ranks.add(self.lnodes[n].rank)
            if not cl_ranks:
                return

            min_r, max_r = min(cl_ranks), max(cl_ranks)

            # Run median + transpose sweeps restricted to this cluster's
            # nodes within each rank
            for _ in range(4):
                improved = False
                for r in range(min_r + 1, max_r + 1):
                    if r not in self.ranks:
                        continue
                    if self._cluster_median_order(r, r - 1, cl_nodes):
                        improved = True
                    self._cluster_transpose(r, cl_nodes)
                for r in range(max_r - 1, min_r - 1, -1):
                    if r not in self.ranks:
                        continue
                    if self._cluster_median_order(r, r + 1, cl_nodes):
                        improved = True
                    self._cluster_transpose(r, cl_nodes)
                if not improved:
                    break

            # Recurse depth-first into child clusters
            for child in children_of.get(cl_name, []):
                _mincross_clust(child)

        # Start from top-level clusters
        for top_cl in children_of.get(None, []):
            _mincross_clust(top_cl)

    def _cluster_median_order(self, rank: int, adj_rank: int,
                               cl_nodes: set[str]) -> bool:
        """Reorder cluster nodes within a rank by median neighbor position.

        Only reorders nodes that belong to ``cl_nodes``; other nodes stay
        in place.  Returns True if any reordering occurred.
        """
        rank_nodes = self.ranks.get(rank, [])
        if not rank_nodes:
            return False

        adj_set = set(self.ranks.get(adj_rank, []))
        cl_in_rank = [(i, n) for i, n in enumerate(rank_nodes) if n in cl_nodes]
        if len(cl_in_rank) < 2:
            return False

        # Compute medians for cluster nodes only
        medians: dict[str, float] = {}
        for _, name in cl_in_rank:
            positions = []
            for le in self.ledges:
                neighbor = None
                if le.tail_name == name and le.head_name in adj_set:
                    neighbor = le.head_name
                elif le.head_name == name and le.tail_name in adj_set:
                    neighbor = le.tail_name
                if neighbor is not None:
                    positions.append(self.lnodes[neighbor].order)
            if positions:
                positions.sort()
                m = len(positions) // 2
                medians[name] = positions[m] if len(positions) % 2 else \
                    (positions[m - 1] + positions[m]) / 2.0
            else:
                medians[name] = self.lnodes[name].order

        # Sort cluster nodes by median while keeping their positions
        # (the slot indices they occupy in the rank)
        slots = [i for i, _ in cl_in_rank]
        cl_names_sorted = sorted([n for _, n in cl_in_rank],
                                  key=lambda n: medians[n])
        changed = False
        for slot, name in zip(slots, cl_names_sorted):
            if rank_nodes[slot] != name:
                changed = True
            rank_nodes[slot] = name
            self.lnodes[name].order = slot

        return changed

    def _cluster_transpose(self, rank: int, cl_nodes: set[str]):
        """Adjacent-swap transpose restricted to cluster nodes."""
        nodes = self.ranks.get(rank, [])
        if len(nodes) < 2:
            return
        improved = True
        while improved:
            improved = False
            for i in range(len(nodes) - 1):
                if nodes[i] not in cl_nodes or nodes[i + 1] not in cl_nodes:
                    continue
                c_before = self._count_crossings_for_pair(nodes[i], nodes[i + 1])
                c_after = self._count_crossings_for_pair(nodes[i + 1], nodes[i])
                if c_after < c_before:
                    nodes[i], nodes[i + 1] = nodes[i + 1], nodes[i]
                    self.lnodes[nodes[i]].order = i
                    self.lnodes[nodes[i + 1]].order = i + 1
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

        nodes.sort(key=lambda n: medians[n])
        for i, name in enumerate(nodes):
            self.lnodes[name].order = i
        self.ranks[rank] = nodes

    def _transpose_rank(self, rank: int):
        nodes = self.ranks.get(rank, [])
        if len(nodes) < 2:
            return
        improved = True
        while improved:
            improved = False
            for i in range(len(nodes) - 1):
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
        if not self.lnodes:
            return

        # Y coordinates following Graphviz position.c set_ycoords().
        self._set_ycoords()

        # Expand leaves: ensure degree-1 nodes have proper spacing
        # (Graphviz position.c expand_leaves).
        self._expand_leaves()

        # Insert virtual label nodes for labeled flat edges (Graphviz
        # position.c flat_edges).  If any were inserted, re-run Y coords.
        if self._insert_flat_label_nodes():
            self._set_ycoords()

        # X coordinates: network simplex on auxiliary constraint graph
        # (matching Graphviz position.c create_aux_edges + rank)
        if not self._ns_x_position():
            # Fallback to simple placement if NS fails
            self._simple_x_position()
            self._median_x_improvement()

        self._center_ranks()
        self._apply_rankdir()

    def _expand_leaves(self):
        """Ensure degree-1 (leaf) nodes have proper separation.

        In Graphviz, leaf nodes may have been collapsed during ranking
        and are re-inserted here with proper width.  In our implementation
        leaf nodes are never collapsed, but we ensure they have at least
        ``nodesep`` separation from their sole neighbor by adjusting their
        width if needed.  This prevents leaf nodes from being packed too
        tightly against their parent.

        Mirrors Graphviz ``position.c:expand_leaves()``.
        """
        # Build degree map
        degree: dict[str, int] = {}
        for le in self.ledges:
            if le.virtual:
                continue
            degree[le.tail_name] = degree.get(le.tail_name, 0) + 1
            degree[le.head_name] = degree.get(le.head_name, 0) + 1

        for name, ln in self.lnodes.items():
            if ln.virtual:
                continue
            if degree.get(name, 0) == 1:
                # Leaf node: ensure minimum width for spacing
                ln.width = max(ln.width, self.nodesep * 2)

    def _insert_flat_label_nodes(self) -> bool:
        """Insert virtual label nodes for labeled same-rank edges.

        For each labeled flat edge whose endpoints are not adjacent in
        the rank ordering, a virtual node is inserted into the rank
        above, sized to hold the label.  This reserves vertical space
        and allows ``_ns_x_position`` to add separation constraints.

        Returns True if any label nodes were inserted (caller should
        re-run ``_set_ycoords``).

        Mirrors Graphviz ``flat.c:flat_edges()`` + ``flat_node()``.
        """
        inserted = False

        for le in self.ledges:
            if le.virtual or not le.label:
                continue
            t = self.lnodes.get(le.tail_name)
            h = self.lnodes.get(le.head_name)
            if not t or not h or t.rank != h.rank:
                continue

            # Check if endpoints are adjacent
            if abs(t.order - h.order) == 1:
                # Adjacent: store label width as ED_dist on the edge for
                # the separation constraint in _ns_x_position
                le._flat_label_dist = self._estimate_label_size(
                    le.label, 14.0)[0]
                continue

            # Non-adjacent: insert a virtual label node in rank above
            target_rank = t.rank - 1
            if target_rank < 0:
                # Need to create rank -1 (shift all ranks up)
                # For simplicity, place it at rank 0 and shift existing
                # ranks up — this is rare, skip for now
                continue

            if target_rank not in self.ranks:
                self.ranks[target_rank] = []

            # Compute label dimensions
            try:
                fs = float(le.edge.attributes.get("fontsize", "14"))
            except (ValueError, AttributeError):
                fs = 14.0
            lw, lh = self._estimate_label_size(le.label, fs)

            # Create virtual label node
            vn_name = f"_flatlabel_{le.tail_name}_{le.head_name}_{id(le)}"
            vn = LayoutNode(name=vn_name)
            vn.virtual = True
            vn.width = lw
            vn.height = lh
            vn.rank = target_rank

            # Insert into rank at midpoint between tail and head order
            mid_order = (t.order + h.order) // 2
            rank_nodes = self.ranks[target_rank]
            insert_pos = min(mid_order, len(rank_nodes))
            rank_nodes.insert(insert_pos, vn_name)

            # Reassign orders
            for i, name in enumerate(rank_nodes):
                self.lnodes[name].order = i

            self.lnodes[vn_name] = vn
            vn.order = insert_pos

            # Store reference: edge → label node for NS constraints
            le._flat_label_vnode = vn_name

            # Create virtual edges from label node to endpoints
            # (these help the crossing minimization and NS positioning)
            from gvpy.engines.dot.dot_layout import LayoutEdge
            ve1 = LayoutEdge(edge=None, tail_name=vn_name,
                             head_name=le.tail_name, minlen=0, weight=1)
            ve1.virtual = True
            ve2 = LayoutEdge(edge=None, tail_name=vn_name,
                             head_name=le.head_name, minlen=0, weight=1)
            ve2.virtual = True
            self.ledges.extend([ve1, ve2])

            inserted = True

        return inserted

    def _set_ycoords(self):
        """Assign Y coordinates to each rank following Graphviz set_ycoords.

        Computes two sets of per-rank half-heights:
        - ``pht1/pht2``: primary (node-only) half-heights
        - ``ht1/ht2``: half-heights expanded by cluster margins and labels

        The inter-rank gap is ``max(pht-gap + ranksep, ht-gap + CL_OFFSET)``.
        """
        max_rank = max((ln.rank for ln in self.lnodes.values()), default=0)
        min_rank = min((ln.rank for ln in self.lnodes.values()), default=0)

        # Step 1: primary half-heights from nodes
        pht1: dict[int, float] = {}  # bottom half (toward higher rank index)
        pht2: dict[int, float] = {}  # top half (toward lower rank index)
        for r in range(min_rank, max_rank + 1):
            pht1[r] = 0.0
            pht2[r] = 0.0

        for ln in self.lnodes.values():
            r = ln.rank
            hh = ln.height / 2.0
            pht1[r] = max(pht1.get(r, 0), hh)
            pht2[r] = max(pht2.get(r, 0), hh)

        # Start with cluster-aware heights = primary heights
        ht1 = dict(pht1)
        ht2 = dict(pht2)

        # Step 2: expand ht1/ht2 for cluster boundaries
        if self._clusters:
            node_sets = {cl.name: set(cl.nodes) for cl in self._clusters}

            # Find each node's innermost cluster
            sorted_cls = sorted(self._clusters,
                                key=lambda c: len(c.nodes), reverse=True)
            node_cluster: dict[str, "LayoutCluster"] = {}
            cl_by_name = {cl.name: cl for cl in self._clusters}
            for cl in sorted_cls:
                for n in cl.nodes:
                    if n in self.lnodes:
                        node_cluster[n] = cl

            # Per-cluster ht1/ht2 (boundary half-heights)
            cl_ht1: dict[str, float] = {}
            cl_ht2: dict[str, float] = {}

            for name, ln in self.lnodes.items():
                if ln.virtual:
                    continue
                cl = node_cluster.get(name)
                if cl is None:
                    continue
                margin = cl.margin if cl.margin > 0 else self._CL_OFFSET
                hh = ln.height / 2.0 + margin

                # Cluster's min rank → ht2 (top boundary)
                cl_ranks = [self.lnodes[n].rank for n in cl.nodes
                            if n in self.lnodes]
                if not cl_ranks:
                    continue
                cl_min_r = min(cl_ranks)
                cl_max_r = max(cl_ranks)

                if ln.rank == cl_min_r:
                    cl_ht2[cl.name] = max(cl_ht2.get(cl.name, 0), hh)
                if ln.rank == cl_max_r:
                    cl_ht1[cl.name] = max(cl_ht1.get(cl.name, 0), hh)

            # Step 3: propagate cluster heights through nesting (clust_ht)
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

            def _clust_ht(cl_name: str):
                cl = cl_by_name[cl_name]
                cl_ranks = [self.lnodes[n].rank for n in cl.nodes
                            if n in self.lnodes]
                if not cl_ranks:
                    return
                cl_min_r = min(cl_ranks)
                cl_max_r = max(cl_ranks)
                margin = cl.margin if cl.margin > 0 else self._CL_OFFSET

                h1 = cl_ht1.get(cl_name, 0)
                h2 = cl_ht2.get(cl_name, 0)

                for child_name in children_of.get(cl_name, []):
                    _clust_ht(child_name)
                    child = cl_by_name[child_name]
                    child_ranks = [self.lnodes[n].rank for n in child.nodes
                                   if n in self.lnodes]
                    if not child_ranks:
                        continue
                    child_min_r = min(child_ranks)
                    child_max_r = max(child_ranks)
                    if child_max_r == cl_max_r:
                        h1 = max(h1, cl_ht1.get(child_name, 0) + margin)
                    if child_min_r == cl_min_r:
                        h2 = max(h2, cl_ht2.get(child_name, 0) + margin)

                # Add cluster label height
                if cl.label:
                    label_h = 14.0  # approximate label height
                    h2 += label_h

                cl_ht1[cl_name] = h1
                cl_ht2[cl_name] = h2

                # Propagate to global rank table
                ht1[cl_max_r] = max(ht1.get(cl_max_r, 0), h1)
                ht2[cl_min_r] = max(ht2.get(cl_min_r, 0), h2)

            for top_cl in children_of.get(None, []):
                _clust_ht(top_cl)

        # Step 4: assign Y coordinates
        rank_y: dict[int, float] = {}
        rank_y[min_rank] = ht1.get(min_rank, 0)

        for r in range(min_rank + 1, max_rank + 1):
            # Node-driven gap
            d0 = pht2.get(r, 0) + pht1.get(r - 1, 0) + self.ranksep
            # Cluster-driven gap
            d1 = ht2.get(r, 0) + ht1.get(r - 1, 0) + self._CL_OFFSET
            rank_y[r] = rank_y[r - 1] + max(d0, d1)

        for ln in self.lnodes.values():
            ln.y = rank_y.get(ln.rank, ln.rank * self.ranksep)

    def _simple_x_position(self):
        # Count edges incident to each node to estimate routing channel space
        edge_count: dict[str, int] = {}
        for le in self.ledges:
            edge_count[le.tail_name] = edge_count.get(le.tail_name, 0) + 1
            edge_count[le.head_name] = edge_count.get(le.head_name, 0) + 1

        # Build innermost cluster map for inter-cluster spacing
        node_cluster: dict[str, str] = {}
        if self._clusters:
            for cl in sorted(self._clusters, key=lambda c: len(c.nodes), reverse=True):
                for n in cl.nodes:
                    if n in self.lnodes:
                        node_cluster[n] = cl.name
        cluster_gap = self.nodesep * 2  # extra gap between different clusters

        for rank_val, rank_nodes in self.ranks.items():
            x = 0.0
            prev_cluster = None
            for name in rank_nodes:
                ln = self.lnodes[name]
                cur_cluster = node_cluster.get(name, "")

                # Add inter-cluster gap when crossing cluster boundaries
                if prev_cluster is not None and cur_cluster != prev_cluster:
                    x += cluster_gap

                ln.x = x + ln.width / 2.0
                # Add routing channel space proportional to edge count
                ec = edge_count.get(name, 0)
                channel_space = min(ec * 8.0, 80.0)  # up to 80pt extra
                x += ln.width + self.nodesep + channel_space
                prev_cluster = cur_cluster

    def _median_x_improvement(self):
        """Iteratively adjust X positions toward median of connected neighbors.

        Similar to the Graphviz median heuristic: for each node, compute
        the median X of its connected neighbors in adjacent ranks and shift
        toward it, subject to separation constraints.
        """
        # Build adjacency: for each node, connected nodes in adjacent ranks
        adj: dict[str, list[str]] = {}
        for le in self.ledges:
            adj.setdefault(le.tail_name, []).append(le.head_name)
            adj.setdefault(le.head_name, []).append(le.tail_name)

        for _iteration in range(8):
            moved = False
            for rank_val in sorted(self.ranks.keys()):
                rank_nodes = self.ranks[rank_val]
                for idx, name in enumerate(rank_nodes):
                    ln = self.lnodes[name]
                    neighbors = adj.get(name, [])
                    if not neighbors:
                        continue
                    # Median X of neighbors
                    neighbor_xs = sorted(self.lnodes[n].x for n in neighbors
                                         if n in self.lnodes)
                    if not neighbor_xs:
                        continue
                    mid = len(neighbor_xs) // 2
                    median_x = neighbor_xs[mid]

                    # Compute allowed range from separation constraints
                    min_x = -1e9
                    max_x = 1e9
                    if idx > 0:
                        left = self.lnodes[rank_nodes[idx - 1]]
                        min_x = left.x + left.width / 2.0 + self.nodesep + ln.width / 2.0
                    if idx < len(rank_nodes) - 1:
                        right = self.lnodes[rank_nodes[idx + 1]]
                        max_x = right.x - right.width / 2.0 - self.nodesep - ln.width / 2.0

                    target = max(min_x, min(max_x, median_x))
                    if abs(target - ln.x) > 0.5:
                        ln.x = target
                        moved = True
            if not moved:
                break

    def _ns_x_position(self) -> bool:
        """Assign X coordinates using network simplex on an auxiliary graph.

        Mirrors Graphviz ``position.c:create_aux_edges()``:

        1. **Separation edges** (``make_LR_constraints``): adjacent nodes in
           the same rank get a directed edge with
           ``minlen = (rw_left + lw_right + nodesep)`` and ``weight = 0``.

        2. **Alignment edges** (``make_edge_pairs``): for each real edge
           (tail → head) a virtual "slack" node is created with two edges
           pulling tail and head toward horizontal alignment.

        3. **Cluster boundary edges** (``pos_clusters``): virtual ``ln``/
           ``rn`` nodes per cluster enforce containment (all cluster members
           between ln and rn) and sibling separation (rn_left → ln_right).

        After building, network simplex is run and the resulting ranks are
        used directly as X coordinates.
        """
        real_nodes = [n for n in self.lnodes if not self.lnodes[n].virtual]
        if len(real_nodes) < 2:
            return False

        aux_nodes: list[str] = list(self.lnodes.keys())
        aux_edges: list[tuple[str, str, int, int]] = []
        _vn_counter = [0]

        def _vnode(prefix: str = "_xv") -> str:
            _vn_counter[0] += 1
            return f"{prefix}_{_vn_counter[0]}"

        # ── 1. Separation edges (make_LR_constraints) ──────────
        for rank_val, rank_nodes in self.ranks.items():
            for i in range(len(rank_nodes) - 1):
                left = rank_nodes[i]
                right = rank_nodes[i + 1]
                ln_l = self.lnodes[left]
                ln_r = self.lnodes[right]
                min_dist = int(ln_l.width / 2.0 + ln_r.width / 2.0
                               + self.nodesep)
                aux_edges.append((left, right, max(1, min_dist), 0))

        # ── 1b. Flat-edge separation constraints ──────────
        # Unlabeled non-adjacent flat edges: ensure minimum separation.
        # Labeled adjacent flat edges: include label width in separation.
        # Label virtual nodes: two edges from label node to endpoints.
        for le in self.ledges:
            if le.virtual or not le.constraint:
                continue
            t_ln = self.lnodes.get(le.tail_name)
            h_ln = self.lnodes.get(le.head_name)
            if not t_ln or not h_ln or t_ln.rank != h_ln.rank:
                continue

            # Determine left/right based on order
            if t_ln.order < h_ln.order:
                left_name, right_name = le.tail_name, le.head_name
                left_ln, right_ln = t_ln, h_ln
            else:
                left_name, right_name = le.head_name, le.tail_name
                left_ln, right_ln = h_ln, t_ln

            # Adjacent labeled: add label width to existing separation
            label_dist = getattr(le, '_flat_label_dist', 0)
            if label_dist > 0:
                min_dist = int(left_ln.width / 2 + right_ln.width / 2
                               + self.nodesep + label_dist)
                aux_edges.append((left_name, right_name,
                                  max(1, min_dist), le.weight))
            elif not le.label:
                # Unlabeled non-adjacent: minimum separation
                min_dist = int(le.minlen * self.nodesep
                               + left_ln.width / 2 + right_ln.width / 2)
                if min_dist > 0:
                    aux_edges.append((left_name, right_name,
                                      max(1, min_dist), le.weight))

            # Label virtual node: separation edges
            vn_name = getattr(le, '_flat_label_vnode', None)
            if vn_name and vn_name in self.lnodes:
                vn = self.lnodes[vn_name]
                aux_nodes.append(vn_name)
                m0 = int(le.minlen * self.nodesep / 2)
                # Left endpoint → label node
                sep_l = max(1, m0 + int(left_ln.width / 2 + vn.width / 2))
                aux_edges.append((left_name, vn_name, sep_l, le.weight))
                # Label node → right endpoint
                sep_r = max(1, m0 + int(vn.width / 2 + right_ln.width / 2))
                aux_edges.append((vn_name, right_name, sep_r, le.weight))

        # ── 2. Alignment edges (make_edge_pairs) ──────────
        # For each real edge, create a slack node that pulls tail and head
        # toward vertical alignment with weight proportional to edge weight.
        node_groups: dict[str, str] = {}
        for name, ln in self.lnodes.items():
            if ln.node:
                grp = ln.node.attributes.get("group", "")
                if grp:
                    node_groups[name] = grp

        for le in self.ledges:
            t_ln = self.lnodes.get(le.tail_name)
            h_ln = self.lnodes.get(le.head_name)
            if not t_ln or not h_ln:
                continue
            w = le.weight
            t_grp = node_groups.get(le.tail_name, "")
            h_grp = node_groups.get(le.head_name, "")
            if t_grp and t_grp == h_grp:
                w = max(w * 100, 100)
            sn = _vnode("_sn")
            aux_nodes.append(sn)
            # Pull slack toward both tail and head with minlen=1
            aux_edges.append((sn, le.tail_name, 0, w))
            aux_edges.append((sn, le.head_name, 0, w))

        # ── 3. Cluster boundary edges (pos_clusters) ──────────
        if self._clusters:
            node_sets = {cl.name: set(cl.nodes) for cl in self._clusters}

            # Build parent map (smallest containing cluster)
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

            cl_by_name = {cl.name: cl for cl in self._clusters}
            cl_ln: dict[str, str] = {}  # cluster → left boundary vnode
            cl_rn: dict[str, str] = {}  # cluster → right boundary vnode

            for cl in self._clusters:
                ln_name = _vnode("_cln")
                rn_name = _vnode("_crn")
                aux_nodes.extend([ln_name, rn_name])
                cl_ln[cl.name] = ln_name
                cl_rn[cl.name] = rn_name

                margin = int(cl.margin)

                # Contain cluster nodes: ln → node, node → rn
                for n in cl.nodes:
                    if n not in self.lnodes:
                        continue
                    nln = self.lnodes[n]
                    lw = int(nln.width / 2.0)
                    rw = int(nln.width / 2.0)
                    aux_edges.append((ln_name, n, max(1, lw + margin), 0))
                    aux_edges.append((n, rn_name, max(1, rw + margin), 0))

                # Compaction: ln → rn with high weight to keep cluster tight
                aux_edges.append((ln_name, rn_name, 1, 128))

            # Contain subclusters: parent.ln → child.ln, child.rn → parent.rn
            for cl in self._clusters:
                par = parent_of.get(cl.name)
                if par is None:
                    continue
                margin = int(cl_by_name[par].margin)
                aux_edges.append((cl_ln[par], cl_ln[cl.name],
                                  max(1, margin), 0))
                aux_edges.append((cl_rn[cl.name], cl_rn[par],
                                  max(1, margin), 0))

            # Separate sibling clusters: rn(left) → ln(right)
            for _parent, siblings in children_of.items():
                if len(siblings) < 2:
                    continue
                # Sort siblings by median node order to determine left→right
                def _median_order(cn):
                    orders = [self.lnodes[n].order for n in node_sets[cn]
                              if n in self.lnodes]
                    if not orders:
                        return 0
                    orders.sort()
                    return orders[len(orders) // 2]
                siblings_sorted = sorted(siblings, key=_median_order)
                margin = int(self.nodesep)
                for i in range(len(siblings_sorted) - 1):
                    left_cl = siblings_sorted[i]
                    right_cl = siblings_sorted[i + 1]
                    aux_edges.append((cl_rn[left_cl], cl_ln[right_cl],
                                      max(1, margin), 0))

            # Keep out other nodes: push non-cluster nodes outside
            # cluster boundaries (Graphviz pos_clusters keepout_othernodes).
            all_cluster_nodes: set[str] = set()
            for cl in self._clusters:
                all_cluster_nodes.update(cl.nodes)

            for rank_val, rank_nodes in self.ranks.items():
                for cl in self._clusters:
                    cl_nodes_in_rank = [n for n in rank_nodes
                                        if n in node_sets.get(cl.name, set())
                                        and n in self.lnodes]
                    if not cl_nodes_in_rank:
                        continue
                    cl_orders = [self.lnodes[n].order for n in cl_nodes_in_rank]
                    cl_min_order = min(cl_orders)
                    cl_max_order = max(cl_orders)
                    margin = int(cl.margin)

                    # First non-cluster node to the left
                    if cl_min_order > 0:
                        left_name = rank_nodes[cl_min_order - 1]
                        if left_name not in node_sets.get(cl.name, set()):
                            left_ln = self.lnodes[left_name]
                            sep = max(1, margin + int(left_ln.width / 2))
                            aux_edges.append((left_name, cl_ln[cl.name],
                                              sep, 0))

                    # First non-cluster node to the right
                    if cl_max_order < len(rank_nodes) - 1:
                        right_name = rank_nodes[cl_max_order + 1]
                        if right_name not in node_sets.get(cl.name, set()):
                            right_ln = self.lnodes[right_name]
                            sep = max(1, margin + int(right_ln.width / 2))
                            aux_edges.append((cl_rn[cl.name], right_name,
                                              sep, 0))

        if not aux_edges:
            return False

        try:
            ns = _NetworkSimplex(aux_nodes, aux_edges)
            ns.SEARCH_LIMIT = self.searchsize
            x_ranks = ns.solve(max_iter=self.nslimit)
            for name, xr in x_ranks.items():
                if name in self.lnodes:
                    self.lnodes[name].x = float(xr)
            return True
        except Exception:
            return False

    def _center_ranks(self):
        rank_widths = {}
        for rank_val, rank_nodes in self.ranks.items():
            if rank_nodes:
                first = self.lnodes[rank_nodes[0]]
                last = self.lnodes[rank_nodes[-1]]
                rank_widths[rank_val] = (last.x + last.width / 2.0) - (first.x - first.width / 2.0)
            else:
                rank_widths[rank_val] = 0

        max_width = max(rank_widths.values()) if rank_widths else 0

        for rank_val, rank_nodes in self.ranks.items():
            offset = (max_width - rank_widths[rank_val]) / 2.0
            for name in rank_nodes:
                self.lnodes[name].x += offset

    def _apply_rankdir(self):
        if self.rankdir == "TB":
            return
        elif self.rankdir == "BT":
            max_y = max(ln.y for ln in self.lnodes.values()) if self.lnodes else 0
            for ln in self.lnodes.values():
                ln.y = max_y - ln.y
        elif self.rankdir == "LR":
            for ln in self.lnodes.values():
                ln.x, ln.y = ln.y, ln.x
                ln.width, ln.height = ln.height, ln.width
        elif self.rankdir == "RL":
            max_y = max(ln.y for ln in self.lnodes.values()) if self.lnodes else 0
            for ln in self.lnodes.values():
                old_x, old_y = ln.x, ln.y
                ln.x = max_y - old_y
                ln.y = old_x
                ln.width, ln.height = ln.height, ln.width

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
        """Convert a polyline to cubic Bezier control points (Catmull-Rom).

        Input:  [P0, P1, ..., Pn]  (polyline waypoints)
        Output: [P0, C1, C2, P1, C3, C4, P2, ...]  (cubic Bezier segments)
        """
        n = len(pts)
        if n <= 1:
            return list(pts)
        if n == 2:
            # Single segment: gentle curve (control points at 1/3 and 2/3)
            p0, p1 = pts
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            c1 = (p0[0] + dx / 3, p0[1] + dy / 3)
            c2 = (p0[0] + 2 * dx / 3, p0[1] + 2 * dy / 3)
            return [p0, c1, c2, p1]

        # Catmull-Rom to cubic Bezier conversion
        # Extend endpoints by mirroring
        ext = [pts[0]] + list(pts) + [pts[-1]]
        result = [ext[1]]  # Start with first real point
        for i in range(1, len(ext) - 2):
            p_prev = ext[i - 1]
            p_curr = ext[i]
            p_next = ext[i + 1]
            p_next2 = ext[i + 2]
            c1 = (p_curr[0] + (p_next[0] - p_prev[0]) / 6.0,
                  p_curr[1] + (p_next[1] - p_prev[1]) / 6.0)
            c2 = (p_next[0] - (p_next2[0] - p_curr[0]) / 6.0,
                  p_next[1] - (p_next2[1] - p_curr[1]) / 6.0)
            result.extend([c1, c2, ext[i + 1]])
        return result

    def _edge_start_point(self, le: LayoutEdge, tail: LayoutNode,
                          head: LayoutNode) -> tuple[float, float]:
        """Get edge start point — uses tailport if set, else boundary intersection."""
        if le.tailport:
            # Check record port first, then compass
            pt = self._record_port_point(le.tail_name, le.tailport, tail)
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
            pt = self._record_port_point(le.head_name, le.headport, head)
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
                           ln: LayoutNode) -> tuple[float, float] | None:
        """Get attachment point for a record port. Returns None if not a record port."""
        ports = self._record_ports.get(node_name)
        if not ports:
            return None
        # Port name may include compass suffix: "port:n"
        port_name = port.split(":")[0] if ":" in port else port
        frac = ports.get(port_name)
        if frac is None:
            return None
        # x position: fraction of node width from left edge
        x = ln.x - ln.width / 2.0 + frac * ln.width
        # y position: top or bottom boundary depending on edge direction
        return (x, ln.y)

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

        # For edges spanning exactly 1 rank, build a 3-box corridor
        # and route a smooth bezier through it.
        rank_diff = abs(head.rank - tail.rank)

        if rank_diff == 1:
            # Simple: tail-box → inter-rank → head-box
            # Control points are at the inter-rank corridor center
            mid_y = (p1[1] + p2[1]) / 2.0

            le.spline_type = "bezier"
            return [
                p1,
                (p1[0], mid_y),
                (p2[0], mid_y),
                p2,
            ]

        # Multi-rank spanning: use virtual node chain waypoints if available
        # (chain edges are handled separately, but some edges may not have
        # virtual nodes if they were too short for the chain).
        # Build intermediate waypoints at each inter-rank crossing.
        waypoints = [p1]
        lower_r = min(tail.rank, head.rank)
        upper_r = max(tail.rank, head.rank)

        # Interpolate X linearly between tail and head at each rank crossing
        for r in range(lower_r, upper_r):
            t = (r - lower_r + 0.5) / rank_diff
            ix = p1[0] + t * (p2[0] - p1[0])
            # Y at the inter-rank midpoint
            rbox = self._rank_box(r)
            iy = (rbox[1] + rbox[3]) / 2.0
            waypoints.append((ix, iy))

        waypoints.append(p2)

        # The _to_bezier will convert these to a smooth cubic Bezier
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
            if name in self._record_ports:
                entry["record_ports"] = self._record_ports[name]
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
