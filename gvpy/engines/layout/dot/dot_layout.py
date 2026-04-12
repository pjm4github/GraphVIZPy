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
    from gvpy.engines.layout.dot import DotGraphInfo  # or the DotLayout alias

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
from gvpy.engines.layout.base import LayoutEngine


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

# Network Simplex (extracted) ----------------------
# The _NetworkSimplex class lives in gvpy/engines/dot/ns_solver.py.
# Re-exported here so existing
#   from gvpy.engines.layout.dot.dot_layout import _NetworkSimplex
# imports continue to work without modification.
from gvpy.engines.layout.dot.ns_solver import _NetworkSimplex  # noqa: E402



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
    ``from gvpy.engines.layout.dot import DotLayout`` imports continue to
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
        # Per-rank obstacle bounds — populated by phase4 spline routing.
        # Declared here so PyCharm / mypy see proper type information
        # when the splines module assigns to ``layout._rank_ht1`` etc.
        self._rank_ht1: dict[int, float] = {}  # bottom half-height per rank
        self._rank_ht2: dict[int, float] = {}  # top half-height per rank
        self._left_bound: float = 0.0
        self._right_bound: float = 0.0
        # Mincross caches — populated lazily by mincross.cluster_medians
        # and mincross.mark_low_clusters.  Pre-declared so PyCharm /
        # mypy see them as proper instance attributes.
        self._edge_port_lookup: dict[tuple[str, str], tuple[str, str]] = {}
        self._node_to_cluster: dict[str, str | None] = {}
        # Per-cluster X bounds set by position.ns_x_position after the
        # NS solve, used by compute_cluster_boxes.
        self._cl_ln_x: dict[str, float] = {}
        self._cl_rn_x: dict[str, float] = {}

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

    def _init_from_graph(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.dotinit.init_from_graph."""
        from gvpy.engines.layout.dot import dotinit
        return dotinit.init_from_graph(self, *args, **kwargs)


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

    def _collect_rank_constraints(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.dotinit.collect_rank_constraints."""
        from gvpy.engines.layout.dot import dotinit
        return dotinit.collect_rank_constraints(self, *args, **kwargs)


    def _scan_subgraphs(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.dotinit.scan_subgraphs."""
        from gvpy.engines.layout.dot import dotinit
        return dotinit.scan_subgraphs(self, *args, **kwargs)


    def _collect_edges(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.dotinit.collect_edges."""
        from gvpy.engines.layout.dot import dotinit
        return dotinit.collect_edges(self, *args, **kwargs)


    def _collect_edges_recursive(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.dotinit.collect_edges_recursive."""
        from gvpy.engines.layout.dot import dotinit
        return dotinit.collect_edges_recursive(self, *args, **kwargs)


    def _collect_clusters(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.cluster.collect_clusters."""
        from gvpy.engines.layout.dot import cluster
        return cluster.collect_clusters(self, *args, **kwargs)


    def _all_nodes_recursive(self, sub) -> list[str]:
        """Collect all unique node names from a subgraph and its descendants."""
        seen: set[str] = set()
        self._collect_nodes_into(sub, seen)
        return sorted(seen)

    def _collect_nodes_into(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.cluster.collect_nodes_into."""
        from gvpy.engines.layout.dot import cluster
        return cluster.collect_nodes_into(self, *args, **kwargs)


    def _scan_clusters(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.cluster.scan_clusters."""
        from gvpy.engines.layout.dot import cluster
        return cluster.scan_clusters(self, *args, **kwargs)


    def _dedup_cluster_nodes(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.cluster.dedup_cluster_nodes."""
        from gvpy.engines.layout.dot import cluster
        return cluster.dedup_cluster_nodes(self, *args, **kwargs)


    def _compute_cluster_boxes(self):
        """Delegates to gvpy.engines.layout.dot.position.compute_cluster_boxes."""
        from gvpy.engines.layout.dot import position
        return position.compute_cluster_boxes(self)

    def _separate_sibling_clusters(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.cluster.separate_sibling_clusters."""
        from gvpy.engines.layout.dot import cluster
        return cluster.separate_sibling_clusters(self, *args, **kwargs)


    def _shift_cluster_nodes_y(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.cluster.shift_cluster_nodes_y."""
        from gvpy.engines.layout.dot import cluster
        return cluster.shift_cluster_nodes_y(self, *args, **kwargs)


    def _shift_cluster_nodes_x(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.cluster.shift_cluster_nodes_x."""
        from gvpy.engines.layout.dot import cluster
        return cluster.shift_cluster_nodes_x(self, *args, **kwargs)


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

    def _phase1_rank(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.phase1_rank."""
        from gvpy.engines.layout.dot import rank
        return rank.phase1_rank(self, *args, **kwargs)


    def _inject_same_rank_edges(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.inject_same_rank_edges."""
        from gvpy.engines.layout.dot import rank
        return rank.inject_same_rank_edges(self, *args, **kwargs)


    def _classify_flat_edges(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.classify_flat_edges."""
        from gvpy.engines.layout.dot import rank
        return rank.classify_flat_edges(self, *args, **kwargs)


    def _classify_edges(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.classify_edges."""
        from gvpy.engines.layout.dot import rank
        return rank.classify_edges(self, *args, **kwargs)


    def _cluster_aware_rank(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.cluster_aware_rank."""
        from gvpy.engines.layout.dot import rank
        return rank.cluster_aware_rank(self, *args, **kwargs)


    def _break_cycles(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.break_cycles."""
        from gvpy.engines.layout.dot import rank
        return rank.break_cycles(self, *args, **kwargs)


    def _network_simplex_rank(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.network_simplex_rank."""
        from gvpy.engines.layout.dot import rank
        return rank.network_simplex_rank(self, *args, **kwargs)


    def _apply_rank_constraints(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.apply_rank_constraints."""
        from gvpy.engines.layout.dot import rank
        return rank.apply_rank_constraints(self, *args, **kwargs)


    def _compact_ranks(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.compact_ranks."""
        from gvpy.engines.layout.dot import rank
        return rank.compact_ranks(self, *args, **kwargs)


    def _add_virtual_nodes(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.add_virtual_nodes."""
        from gvpy.engines.layout.dot import rank
        return rank.add_virtual_nodes(self, *args, **kwargs)


    def _build_ranks(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.rank.build_ranks."""
        from gvpy.engines.layout.dot import rank
        return rank.build_ranks(self, *args, **kwargs)


    # ── Phase 2: Crossing minimization ───────────

    _CL_CROSS = 1000  # Graphviz CL_CROSS: penalty weight for crossing cluster borders

    def _mark_low_clusters(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.mark_low_clusters."""
        from gvpy.engines.layout.dot import mincross
        return mincross.mark_low_clusters(self, *args, **kwargs)


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

    def _phase2_ordering(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.phase2_ordering."""
        from gvpy.engines.layout.dot import mincross
        return mincross.phase2_ordering(self, *args, **kwargs)


    def _run_mincross(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.run_mincross."""
        from gvpy.engines.layout.dot import mincross
        return mincross.run_mincross(self, *args, **kwargs)


    def _remincross_full(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.remincross_full."""
        from gvpy.engines.layout.dot import mincross
        return mincross.remincross_full(self, *args, **kwargs)


    def _skeleton_mincross(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.skeleton_mincross."""
        from gvpy.engines.layout.dot import mincross
        return mincross.skeleton_mincross(self, *args, **kwargs)


    def _flat_reorder(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.flat_reorder."""
        from gvpy.engines.layout.dot import mincross
        return mincross.flat_reorder(self, *args, **kwargs)




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

    def _mval_edge(self, *args, **kwargs) -> int:
        """Delegates to gvpy.engines.layout.dot.mincross.mval_edge."""
        from gvpy.engines.layout.dot import mincross
        return mincross.mval_edge(self, *args, **kwargs)


    # _port_order_from_label and _split_record_fields removed �
    # port.order now comes from Node.record_fields.port_fraction()
    # (ANTLR4 RecordParser, sized at layout start).


    def _cluster_medians(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.cluster_medians."""
        from gvpy.engines.layout.dot import mincross
        return mincross.cluster_medians(self, *args, **kwargs)


    def _cluster_reorder(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.cluster_reorder."""
        from gvpy.engines.layout.dot import mincross
        return mincross.cluster_reorder(self, *args, **kwargs)


    def _cluster_build_ranks(self, *args, **kwargs) -> dict[int, list[str]]:
        """Delegates to gvpy.engines.layout.dot.mincross.cluster_build_ranks."""
        from gvpy.engines.layout.dot import mincross
        return mincross.cluster_build_ranks(self, *args, **kwargs)


    def _cluster_transpose(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.cluster_transpose."""
        from gvpy.engines.layout.dot import mincross
        return mincross.cluster_transpose(self, *args, **kwargs)


    def _order_by_weighted_median(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.order_by_weighted_median."""
        from gvpy.engines.layout.dot import mincross
        return mincross.order_by_weighted_median(self, *args, **kwargs)


    def _transpose_rank(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.transpose_rank."""
        from gvpy.engines.layout.dot import mincross
        return mincross.transpose_rank(self, *args, **kwargs)


    def _count_crossings_for_pair(self, *args, **kwargs) -> int:
        """Delegates to gvpy.engines.layout.dot.mincross.count_crossings_for_pair."""
        from gvpy.engines.layout.dot import mincross
        return mincross.count_crossings_for_pair(self, *args, **kwargs)


    def _count_all_crossings(self, *args, **kwargs) -> int:
        """Delegates to gvpy.engines.layout.dot.mincross.count_all_crossings."""
        from gvpy.engines.layout.dot import mincross
        return mincross.count_all_crossings(self, *args, **kwargs)


    def _count_scoped_crossings(self, *args, **kwargs) -> int:
        """Delegates to gvpy.engines.layout.dot.mincross.count_scoped_crossings."""
        from gvpy.engines.layout.dot import mincross
        return mincross.count_scoped_crossings(self, *args, **kwargs)


    def _save_ordering(self, *args, **kwargs) -> dict[str, int]:
        """Delegates to gvpy.engines.layout.dot.mincross.save_ordering."""
        from gvpy.engines.layout.dot import mincross
        return mincross.save_ordering(self, *args, **kwargs)


    def _restore_ordering(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.restore_ordering."""
        from gvpy.engines.layout.dot import mincross
        return mincross.restore_ordering(self, *args, **kwargs)


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
        from gvpy.engines.layout.dot import position
        position.phase3_position(self)

    def _expand_leaves(self):
        """Delegates to gvpy.engines.layout.dot.position.expand_leaves."""
        from gvpy.engines.layout.dot import position
        return position.expand_leaves(self)

    def _insert_flat_label_nodes(self) -> bool:
        """Delegates to gvpy.engines.layout.dot.position.insert_flat_label_nodes."""
        from gvpy.engines.layout.dot import position
        return position.insert_flat_label_nodes(self)

    def _set_ycoords(self):
        """Delegates to gvpy.engines.layout.dot.position.set_ycoords."""
        from gvpy.engines.layout.dot import position
        return position.set_ycoords(self)

    def _simple_x_position(self):
        """Delegates to gvpy.engines.layout.dot.position.simple_x_position."""
        from gvpy.engines.layout.dot import position
        return position.simple_x_position(self)

    def _median_x_improvement(self):
        """Delegates to gvpy.engines.layout.dot.position.median_x_improvement."""
        from gvpy.engines.layout.dot import position
        return position.median_x_improvement(self)

    def _bottomup_ns_x_position(self):
        """Delegates to gvpy.engines.layout.dot.position.bottomup_ns_x_position."""
        from gvpy.engines.layout.dot import position
        return position.bottomup_ns_x_position(self)

    def _ns_x_position(self) -> bool:
        """Delegate to position.ns_x_position — see that module."""
        from gvpy.engines.layout.dot import position
        return position.ns_x_position(self)

    def _resolve_cluster_overlaps(self):
        """Delegates to gvpy.engines.layout.dot.position.resolve_cluster_overlaps."""
        from gvpy.engines.layout.dot import position
        return position.resolve_cluster_overlaps(self)

    def _post_rankdir_keepout(self):
        """Delegates to gvpy.engines.layout.dot.position.post_rankdir_keepout."""
        from gvpy.engines.layout.dot import position
        return position.post_rankdir_keepout(self)

    def _center_ranks(self):
        """Delegates to gvpy.engines.layout.dot.position.center_ranks."""
        from gvpy.engines.layout.dot import position
        return position.center_ranks(self)

    def _apply_rankdir(self):
        """Delegates to gvpy.engines.layout.dot.position.apply_rankdir."""
        from gvpy.engines.layout.dot import position
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

    def _phase4_routing(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.phase4_routing."""
        from gvpy.engines.layout.dot import splines
        return splines.phase4_routing(self, *args, **kwargs)


    def _clip_compound_edges(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.clip_compound_edges."""
        from gvpy.engines.layout.dot import splines
        return splines.clip_compound_edges(self, *args, **kwargs)


    @staticmethod
    def _clip_to_bb(self, *args, **kwargs) -> tuple | None:
        """Delegates to gvpy.engines.layout.dot.splines.clip_to_bb."""
        from gvpy.engines.layout.dot import splines
        return splines.clip_to_bb(self, *args, **kwargs)


    @staticmethod
    def _to_bezier(self, *args, **kwargs) -> list[tuple]:
        """Delegates to gvpy.engines.layout.dot.splines.to_bezier."""
        from gvpy.engines.layout.dot import splines
        return splines.to_bezier(self, *args, **kwargs)


    def _edge_start_point(self, *args, **kwargs) -> tuple[float, float]:
        """Delegates to gvpy.engines.layout.dot.splines.edge_start_point."""
        from gvpy.engines.layout.dot import splines
        return splines.edge_start_point(self, *args, **kwargs)


    def _edge_end_point(self, *args, **kwargs) -> tuple[float, float]:
        """Delegates to gvpy.engines.layout.dot.splines.edge_end_point."""
        from gvpy.engines.layout.dot import splines
        return splines.edge_end_point(self, *args, **kwargs)


    def _record_port_point(self, *args, **kwargs) -> tuple[float, float] | None:
        """Delegates to gvpy.engines.layout.dot.splines.record_port_point."""
        from gvpy.engines.layout.dot import splines
        return splines.record_port_point(self, *args, **kwargs)


    @staticmethod
    def _port_point(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.port_point."""
        from gvpy.engines.layout.dot import splines
        return splines.port_point(self, *args, **kwargs)


    @staticmethod
    def _compute_label_pos(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.compute_label_pos."""
        from gvpy.engines.layout.dot import splines
        return splines.compute_label_pos(self, *args, **kwargs)


    def _apply_sameport(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.apply_sameport."""
        from gvpy.engines.layout.dot import splines
        return splines.apply_sameport(self, *args, **kwargs)


    def _ortho_route(self, *args, **kwargs) -> list[tuple[float, float]]:
        """Delegates to gvpy.engines.layout.dot.splines.ortho_route."""
        from gvpy.engines.layout.dot import splines
        return splines.ortho_route(self, *args, **kwargs)


    def _route_through_chain(self, *args, **kwargs) -> list[tuple[float, float]]:
        """Delegates to gvpy.engines.layout.dot.splines.route_through_chain."""
        from gvpy.engines.layout.dot import splines
        return splines.route_through_chain(self, *args, **kwargs)


    @staticmethod
    def _boundary_point(self, *args, **kwargs) -> tuple[float, float]:
        """Delegates to gvpy.engines.layout.dot.splines.boundary_point."""
        from gvpy.engines.layout.dot import splines
        return splines.boundary_point(self, *args, **kwargs)


    @staticmethod
    def _self_loop_points(self, *args, **kwargs) -> list[tuple[float, float]]:
        """Delegates to gvpy.engines.layout.dot.splines.self_loop_points."""
        from gvpy.engines.layout.dot import splines
        return splines.self_loop_points(self, *args, **kwargs)


    def _maximal_bbox(self, *args, **kwargs) -> tuple[float, float, float, float]:
        """Delegates to gvpy.engines.layout.dot.splines.maximal_bbox."""
        from gvpy.engines.layout.dot import splines
        return splines.maximal_bbox(self, *args, **kwargs)


    def _rank_box(self, *args, **kwargs) -> tuple[float, float, float, float]:
        """Delegates to gvpy.engines.layout.dot.splines.rank_box."""
        from gvpy.engines.layout.dot import splines
        return splines.rank_box(self, *args, **kwargs)


    def _route_regular_edge(self, *args, **kwargs) -> list[tuple[float, float]]:
        """Delegates to gvpy.engines.layout.dot.splines.route_regular_edge."""
        from gvpy.engines.layout.dot import splines
        return splines.route_regular_edge(self, *args, **kwargs)


    def _classify_flat_edge(self, *args, **kwargs) -> str:
        """Delegates to gvpy.engines.layout.dot.splines.classify_flat_edge."""
        from gvpy.engines.layout.dot import splines
        return splines.classify_flat_edge(self, *args, **kwargs)


    def _count_flat_edge_index(self, *args, **kwargs) -> int:
        """Delegates to gvpy.engines.layout.dot.splines.count_flat_edge_index."""
        from gvpy.engines.layout.dot import splines
        return splines.count_flat_edge_index(self, *args, **kwargs)


    def _flat_edge_route(self, *args, **kwargs) -> list[tuple[float, float]]:
        """Delegates to gvpy.engines.layout.dot.splines.flat_edge_route."""
        from gvpy.engines.layout.dot import splines
        return splines.flat_edge_route(self, *args, **kwargs)


    def _flat_adjacent(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.flat_adjacent."""
        from gvpy.engines.layout.dot import splines
        return splines.flat_adjacent(self, *args, **kwargs)


    def _flat_labeled(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.flat_labeled."""
        from gvpy.engines.layout.dot import splines
        return splines.flat_labeled(self, *args, **kwargs)


    def _flat_arc(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.splines.flat_arc."""
        from gvpy.engines.layout.dot import splines
        return splines.flat_arc(self, *args, **kwargs)


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
# imports ``from gvpy.engines.layout.dot import DotLayout`` continue to work.
DotLayout = DotGraphInfo
