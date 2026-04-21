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
from gvpy.engines.layout.dot.edge_route import EdgeRoute
from gvpy.engines.layout.dot.trace import trace

# Module-level imports for satellite phase modules.  These modules use
# TYPE_CHECKING guards on their DotGraphInfo references to avoid
# circular-import failures at load time.
from gvpy.engines.layout.dot import cluster  # noqa: E402
from gvpy.engines.layout.dot import dotinit  # noqa: E402
from gvpy.engines.layout.dot import mincross  # noqa: E402
from gvpy.engines.layout.dot import position  # noqa: E402
from gvpy.engines.layout.dot import rank  # noqa: E402
from gvpy.engines.layout.dot import dotsplines  # noqa: E402


# ── Internal data structures ─────────────────────


def _record_field_to_svg_dict(field, parent_lr: bool) -> dict:
    """Convert an ANTLR-parsed :class:`RecordField` tree to the dict
    format consumed by :mod:`gvpy.render.svg_renderer`.

    The svg_renderer's legacy ``_parse_record_label`` produced
    ``{"text", "port", "children", "flipped"}`` where ``flipped``
    means "this container flips orientation from its parent".
    :class:`RecordField` carries an absolute ``LR`` flag instead.
    ``flipped`` is then simply ``LR != parent_lr`` for containers;
    leaves ignore the flag.

    Part of divergence D7's record-port fix (2026-04-20): the
    renderer was re-parsing the label string with its own
    hand-written parser, which could place port cells at slightly
    different positions than the layout engine's ANTLR parser
    computed.  Emitting the tree here routes both the layout and
    render sides through a single parse.
    """
    if not field.children:
        return {
            "text": field.text,
            "port": field.port,
            "children": [],
            "flipped": False,
        }
    return {
        "text": field.text,
        "port": field.port,
        "children": [_record_field_to_svg_dict(c, field.LR)
                     for c in field.children],
        "flipped": field.LR != parent_lr,
    }


@dataclass
class LayoutNode:
    node: Optional[Node] = None
    name: str = ""
    rank: int = 0
    order: int = 0
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0   # 0.75 in * 72 dpi
    height: float = 36.0  # 0.50 in * 72 dpi
    virtual: bool = False
    pinned: bool = False
    fixed_pos: tuple | None = None  # (x, y) from pos attribute
    mval: float = 0.0
    """Median value — mirrors C ``ND_mval(n)`` in ``dot.h``.  Used by
    ``resetRW`` in phase 4 to restore a node's pre-inflation right
    half-width: when a node carries self-loops, the position phase
    inflates ``ND_rw`` and stashes the original value in ``mval`` so
    the splines phase can swap them back via :func:`dotsplines.resetRW`.
    Default ``0.0`` means uninflated (current Python behaviour — real
    self-loop inflation lands in Phase F)."""


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
    constraint: bool = True
    label: str = ""
    tailport: str = ""
    headport: str = ""
    lhead: str = ""
    ltail: str = ""
    headclip: bool = True
    tailclip: bool = True
    samehead: str = ""
    sametail: str = ""
    edge_type: str = "normal"  # normal, flat, reversed, self, virtual
    tree_index: int = 0
    """Equivalence-class and direction flags, bitwise OR of the constants
    in :mod:`gvpy.engines.layout.dot.path` — one edge-type bit
    (``REGULAREDGE`` / ``FLATEDGE`` / ``SELFWPEDGE`` / ``SELFNPEDGE``),
    one direction bit (``FWDEDGE`` / ``BWDEDGE``), and one graph-type
    bit (``MAINGRAPH`` / ``AUXGRAPH``).  See: ``ED_tree_index(e)``
    via the ``setflags`` helper in ``dotsplines.c``."""
    route: EdgeRoute = field(default_factory=EdgeRoute)

    @property
    def points(self) -> list:
        return self.route.points

    @points.setter
    def points(self, value: list) -> None:
        self.route.points = value

    @property
    def spline_type(self) -> str:
        return self.route.spline_type

    @spline_type.setter
    def spline_type(self, value: str) -> None:
        self.route.spline_type = value

    @property
    def label_pos(self) -> tuple:
        return self.route.label_pos

    @label_pos.setter
    def label_pos(self, value: tuple) -> None:
        self.route.label_pos = value


@dataclass
class LayoutCluster:
    """Per-cluster layout state.

    See: ``graph_t`` with ``GD_cluster_data`` in ``lib/dotgen/dot.h``
    for cluster subgraphs.  C accesses cluster fields via ``GD_label``,
    ``GD_bb``, ``GD_border`` macros on the cluster's ``graph_t``; Python
    hoists these into a dedicated dataclass.
    """
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

    See: ``Agraphinfo_t`` in ``lib/dotgen/dot.h``.  Holds all
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
        # Phase-4 routing context.  See: the ``sd`` local in
        # ``dot_splines_`` (``lib/dotgen/dotsplines.c``).  Allocated
        # by ``phase4_routing`` at the top of the pass and reused by
        # every spline router helper.  None outside that pass.
        from gvpy.engines.layout.dot.path import SplineInfo
        self._spline_info: "SplineInfo | None" = None
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
        """Run the full layout pipeline and return a JSON-serializable dict.

        Mirrors C ``lib/dotgen/dotinit.c: dot_layout() @ 510``: the entire graph
        is laid out as a single unit.  Network simplex (Phase 1) handles
        weakly-disconnected components naturally — they end up on
        adjacent ranks within the unified rank structure, and Phase 3
        positions them side by side without any special-case packing.
        See ``TODO_dot_layout.md`` history for the prior buggy
        ``_find_components``/``_pack_components`` short-circuit that was
        removed in favour of this C-aligned flow.
        """
        self._init_from_graph()

        trace("rank", f"begin layout: nodes={len(self.lnodes)} edges={len(self.ledges)} clusters={len(self._clusters)}")
        # [TRACE phase] — phase-level timing (gated on GV_TRACE=phase).
        import time as _time_phase
        from gvpy.engines.layout.dot.trace import trace_on as _ph_on, trace as _ph_tr
        _ph_t = _ph_on("phase")
        def _ph_mark(name, fn):
            if not _ph_t:
                return fn()
            _t0 = _time_phase.perf_counter()
            r = fn()
            _dt = _time_phase.perf_counter() - _t0
            _ph_tr("phase", f"{name} elapsed={_dt:.2f}s nodes={len(self.lnodes)} edges={len(self.ledges)}")
            return r
        _ph_mark("phase1_rank", self._phase1_rank)
        _ph_mark("phase2_ordering", self._phase2_ordering)
        _ph_mark("phase3_position", self._phase3_position)
        self._apply_fixed_positions()
        self._apply_size()
        self._compute_cluster_boxes()
        _ph_mark("phase4_routing", self._phase4_routing)
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
        """Build LayoutNode/LayoutEdge maps from the graph.

        See: ``lib/dotgen/dotinit.c: dot_init_node_edge() @ 89`` combined
        with the graph-walk portion of ``dot_layout()``.  C populates
        ``ND_*`` and ``ED_*`` fields directly on the cgraph objects;
        Python builds parallel ``lnodes`` / ``ledges`` dataclasses.

        Delegates to :func:`dotinit.init_from_graph`.
        """
        return dotinit.init_from_graph(self, *args, **kwargs)


    def _orient_undirected(self):
        """Orient undirected-graph edges so each has a consistent tail→head.

        See: ``lib/common/emit.c: undirectedDfs()`` / the undirected-graph
        handling in ``lib/dotgen/dotinit.c: dot_init_node_edge() @ 89``.  C walks the
        graph and assigns a direction to each edge based on DFS order; the
        Python implementation is a straight DFS that picks the first visit
        as the tail.
        """
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
        """Parse ``rank=same/min/max/source/sink`` constraints from subgraphs.

        See: ``lib/dotgen/rank.c: rank1() @ 449`` + ``collapse_sets() @ 349``.

        Delegates to :func:`dotinit.collect_rank_constraints`.
        """
        return dotinit.collect_rank_constraints(self, *args, **kwargs)


    def _scan_subgraphs(self, *args, **kwargs):
        """Walk subgraph tree, collecting cluster membership and attributes.

        See: ``lib/dotgen/dotinit.c`` subgraph iteration via
        ``agfstsubg()`` / ``agnxtsubg()``.

        Delegates to :func:`dotinit.scan_subgraphs`.
        """
        return dotinit.scan_subgraphs(self, *args, **kwargs)


    def _collect_edges(self, *args, **kwargs):
        """Gather all edges into ``layout.ledges``.

        See: edge iteration in ``lib/dotgen/dotinit.c`` via
        ``agfstout()`` / ``agnxtout()`` over every node.

        Delegates to :func:`dotinit.collect_edges`.
        """
        return dotinit.collect_edges(self, *args, **kwargs)


    def _collect_edges_recursive(self, *args, **kwargs):
        """Recursively collect edges from subgraphs.

        See: subgraph-scoped edge walks in ``lib/cgraph`` +
        ``lib/dotgen/dotinit.c``.

        Delegates to :func:`dotinit.collect_edges_recursive`.
        """
        return dotinit.collect_edges_recursive(self, *args, **kwargs)


    def _collect_clusters(self, *args, **kwargs):
        """Build the LayoutCluster list from subgraphs whose name starts with ``cluster``.

        See: ``lib/dotgen/dotinit.c`` cluster detection logic that
        walks subgraphs and populates ``GD_clust`` arrays on the parent
        graph.

        Delegates to :func:`cluster.collect_clusters`.
        """
        return cluster.collect_clusters(self, *args, **kwargs)


    def _all_nodes_recursive(self, sub) -> list[str]:
        """Collect all unique node names from a subgraph and its descendants.

        See: ``lib/cgraph/subg.c: agnodes()`` combined with recursive
        descent via ``agfstsubg()`` — C does this inline wherever needed.
        """
        seen: set[str] = set()
        self._collect_nodes_into(sub, seen)
        return sorted(seen)

    def _collect_nodes_into(self, *args, **kwargs):
        """Recursive helper for :meth:`_all_nodes_recursive`.

        See: inline recursion in C; no single named C function.

        Delegates to :func:`cluster.collect_nodes_into`.
        """
        return cluster.collect_nodes_into(self, *args, **kwargs)


    def _scan_clusters(self, *args, **kwargs):
        """Walk clusters to initialize per-cluster state.

        See: cluster initialization in ``lib/dotgen/dotinit.c``
        and ``lib/dotgen/cluster.c``.

        Delegates to :func:`cluster.scan_clusters`.
        """
        return cluster.scan_clusters(self, *args, **kwargs)


    def _dedup_cluster_nodes(self, *args, **kwargs):
        """Remove duplicate node entries from cluster membership lists.

        See: none direct — C's ``GD_clust`` arrays are
        populated without duplicates by construction.  This is a
        Python-side cleanup pass.

        Delegates to :func:`cluster.dedup_cluster_nodes`.
        """
        return cluster.dedup_cluster_nodes(self, *args, **kwargs)


    def _compute_cluster_boxes(self):
        """Compute cluster bounding boxes from member-node positions.

        See: ``lib/dotgen/position.c: dot_compute_bb() @ 882``.

        Delegates to :func:`position.compute_cluster_boxes`.
        """
        return position.compute_cluster_boxes(self)

    def _separate_sibling_clusters(self, *args, **kwargs):
        """Nudge sibling clusters apart to avoid overlap.

        See: cluster-separation logic inside ``lib/dotgen/position.c``
        after the ``ns_x_position`` phase.

        Delegates to :func:`cluster.separate_sibling_clusters`.
        """
        return cluster.separate_sibling_clusters(self, *args, **kwargs)


    def _shift_cluster_nodes_y(self, *args, **kwargs):
        """Shift all nodes in a cluster by a dy offset.

        See: ``lib/dotgen/position.c`` cluster-positioning pass;
        no standalone C function — inlined at cluster-adjust sites.

        Delegates to :func:`cluster.shift_cluster_nodes_y`.
        """
        return cluster.shift_cluster_nodes_y(self, *args, **kwargs)


    def _shift_cluster_nodes_x(self, *args, **kwargs):
        """Shift all nodes in a cluster by a dx offset.

        See: same as :meth:`_shift_cluster_nodes_y` — cluster
        adjustment in ``lib/dotgen/position.c``, x-axis variant.

        Delegates to :func:`cluster.shift_cluster_nodes_x`.
        """
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

    # Shape geometry table — mirrors the ``polygon_t`` builtins in
    # C's ``lib/common/shapes.c`` (``p_box``, ``p_ellipse``,
    # ``p_hexagon``, etc.).  Each entry is
    # ``(sides, orientation_deg, distortion, skew)``.  ``sides == 1``
    # means "ellipse-family" in C's padding branch (full SQRT2 stretch
    # without the 1/cos(π/n) post-scale).  ``sides == 4`` with all
    # zeros is ``isBox`` (exact label fit, no extra shape pad).
    _SHAPE_GEOM: "dict[str, tuple[int, float, float, float]]" = {
        "box":            (4,   0.0,  0.0,  0.0),
        "rect":           (4,   0.0,  0.0,  0.0),
        "rectangle":      (4,   0.0,  0.0,  0.0),
        "square":         (4,   0.0,  0.0,  0.0),
        "plaintext":      (4,   0.0,  0.0,  0.0),
        "plain":          (4,   0.0,  0.0,  0.0),
        "none":           (4,   0.0,  0.0,  0.0),
        "note":           (4,   0.0,  0.0,  0.0),
        "tab":            (4,   0.0,  0.0,  0.0),
        "folder":         (4,   0.0,  0.0,  0.0),
        "box3d":          (4,   0.0,  0.0,  0.0),
        "component":      (4,   0.0,  0.0,  0.0),
        "cds":            (4,   0.0,  0.0,  0.0),
        "ellipse":        (1,   0.0,  0.0,  0.0),
        "oval":           (1,   0.0,  0.0,  0.0),
        "circle":         (1,   0.0,  0.0,  0.0),
        "doublecircle":   (1,   0.0,  0.0,  0.0),
        "Mcircle":        (1,   0.0,  0.0,  0.0),
        "point":          (1,   0.0,  0.0,  0.0),
        "egg":            (1,   0.0, -0.3,  0.0),
        "diamond":        (4,  45.0,  0.0,  0.0),
        "Mdiamond":       (4,  45.0,  0.0,  0.0),
        "Msquare":        (4,   0.0,  0.0,  0.0),
        "trapezium":      (4,   0.0, -0.4,  0.0),
        "invtrapezium":   (4, 180.0, -0.4,  0.0),
        "parallelogram":  (4,   0.0,  0.0,  0.6),
        "triangle":       (3,   0.0,  0.0,  0.0),
        "invtriangle":    (3, 180.0,  0.0,  0.0),
        "house":          (5,   0.0, -0.64, 0.0),
        "invhouse":       (5, 180.0, -0.64, 0.0),
        "pentagon":       (5,   0.0,  0.0,  0.0),
        "hexagon":        (6,   0.0,  0.0,  0.0),
        "septagon":       (7,   0.0,  0.0,  0.0),
        "octagon":        (8,   0.0,  0.0,  0.0),
        "doubleoctagon":  (8,   0.0,  0.0,  0.0),
        "tripleoctagon":  (8,   0.0,  0.0,  0.0),
        "cylinder":       (19,  0.0,  0.0,  0.0),
        "star":           (10,  0.0,  0.0,  0.0),
    }

    def _shape_geometry(self, shape: str) -> tuple[int, float, float, float]:
        """Return ``(sides, orientation, distortion, skew)`` for a shape.

        Unknown shapes fall back to ellipse geometry (matches
        C's ``shapes.c``: ``Shapes`` table default).
        """
        return self._SHAPE_GEOM.get(shape, (1, 0.0, 0.0, 0.0))

    def _compute_node_size(self, name: str, node) -> tuple[float, float]:
        """Compute node dimensions from label text, shape, and explicit width/height.

        See: ``lib/common/shapes.c: poly_init() @ 1934`` +
        ``shapes.c:record_init()`` — C dispatches through shape-specific
        ``init_fn`` callbacks that size the node based on its label and
        shape.  Python consolidates the common cases (ellipse, box,
        record) here; shape-specific callbacks live in
        :mod:`gvpy.render.svg_renderer`.
        """
        attrs = node.attributes if node else {}

        fixedsize = attrs.get("fixedsize", "false").lower() in ("true", "1", "yes", "shape")
        explicit_w = attrs.get("width")
        explicit_h = attrs.get("height")
        # fixedsize=true: use explicit dimensions exactly, ignore label.
        # This is the only path that treats width/height as a hard cap;
        # C's lib/common/shapes.c: poly_init @ 2034 does the same
        # (``N_fixed`` → ``lw = rw = w/2; ht = h``, no label grow).
        if fixedsize:
            w = float(explicit_w) * 72.0 if explicit_w else self._MIN_WIDTH
            h = float(explicit_h) * 72.0 if explicit_h else self._MIN_HEIGHT
            if self.rankdir in ("LR", "RL"):
                w, h = h, w
            return w, h

        shape = attrs.get("shape", "ellipse")
        label = attrs.get("label", name)
        try:
            fontsize = float(attrs.get("fontsize", "14"))
        except ValueError:
            fontsize = 14.0
        char_w = fontsize * 0.52  # avg estimate, only used by record_size

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

            # Per-glyph Times-Roman AFM widths — matches C's
            # ``lib/common/labels.c: make_label()`` textspan callback.
            from gvpy.engines.layout.common.text import (
                text_width_times_roman,
            )
            lines = label.replace("\\n", "\n").split("\n")
            if not lines:
                lines = [name]
            num_lines = len(lines)
            text_w = max(text_width_times_roman(line, fontsize)
                         for line in lines)
            text_h = num_lines * fontsize * 1.2

            # C's ``poly_init`` at ``lib/common/shapes.c @ 1934``:
            # 1. ``dimen`` = (text_w + XPAD, text_h + YPAD) where
            #    XPAD = 4 × GAP = 16 pt and YPAD = 2 × GAP = 8 pt
            #    (``lib/common/const.h: GAP = 4``,
            #    ``macros.h: XPAD/YPAD``).  Python previously used
            #    ``_H_PAD=36`` / ``_V_PAD=18`` which over-padded every
            #    label by ~20 pt in each axis.
            # 2. For non-``isBox`` shapes (sides ≠ 4, or with
            #    orientation / distortion / skew), scale ``bb`` to the
            #    smallest ellipse containing the label, then scale up
            #    further by ``1 / cos(π / sides)`` so an N-gon
            #    circumscribes that ellipse.  This is what gives
            #    hexagons / octagons / diamonds their visible "pointy
            #    end" padding beyond the label.  On 2620.dot the
            #    scheduler hexagon was 222 pt under Python's prior
            #    unpadded path vs 322.7 pt in C; with this block it
            #    matches C to <0.1 %.
            bb_x = text_w + 16.0
            bb_y = text_h + 8.0
            sides, orient, disto, skew = self._shape_geometry(shape)
            is_box = (sides == 4 and abs(orient % 90) < 0.5
                      and disto == 0 and skew == 0)
            if not is_box and sides > 0:
                # User's declared height in points (explicit or MIN).
                user_h = (float(explicit_h) * 72.0 if explicit_h
                          else self._MIN_HEIGHT)
                import math as _m
                temp = bb_y * _m.sqrt(2.0)
                if user_h > temp:
                    # valign=center (default) branch: stretch x only.
                    ratio = bb_y / user_h
                    bb_x *= _m.sqrt(1.0 / max(1.0 - ratio * ratio, 1e-9))
                else:
                    bb_x *= _m.sqrt(2.0)
                    bb_y = temp
                if sides > 2:
                    k = _m.cos(_m.pi / sides)
                    if k > 1e-9:
                        bb_x /= k
                        bb_y /= k
            w = bb_x
            h = bb_y

        # Explicit width/height act as MINIMUMS — the node grows to fit
        # the label when the label is bigger.  Matches C's
        # shapes.c: poly_init @ ``sz.x = MAX(sz.x, INCH2PS(ND_width))``
        # behavior for non-fixedsize shapes.  Previously Python treated
        # these as hard overrides, which capped long-label nodes at the
        # ``node [width=2]`` default (144 pt) even when the label
        # needed 300+ pt — visible on 2620.dot where 94 scheduler
        # nodes with ~30-char labels were forced to 144 pt each,
        # collapsing the rank-direction spacing.
        if explicit_w:
            w = max(w, float(explicit_w) * 72.0)
        if explicit_h:
            h = max(h, float(explicit_h) * 72.0)

        # Default-size floor: apply ``_MIN_WIDTH`` / ``_MIN_HEIGHT`` in
        # the user's frame (before any LR pre-swap) so a node with a
        # wide-short label (e.g. a single-line scheduler name) keeps its
        # natural thin height.  Applying the floor AFTER the pre-swap
        # would push the rank-direction axis back up to 54 pt,
        # incorrectly fattening the node vertically in LR output — on
        # 2620.dot this made single-line scheduler nodes 54 pt tall when
        # C keeps them at 36 pt.
        w = max(w, self._MIN_WIDTH)
        h = max(h, self._MIN_HEIGHT)

        # Pre-swap node dimensions for LR/RL so the TB-internal layout
        # pipeline sees the user's height as the cross-rank (x) extent
        # and the user's width as the rank (y) extent — matches C's
        # ``gv_nodesize(n, GD_flip(g))`` in ``lib/dotgen/dotinit.c @ 49``.
        # ``_apply_rankdir`` swaps positions AND (w, h) back at the end
        # of phase 3, restoring the user's original dimensions in the
        # LR-final output.  ``_record_size`` already pre-swaps record
        # dimensions; this covers every other shape (box, ellipse,
        # hexagon, octagon, diamond, …).
        if self.rankdir in ("LR", "RL"):
            w, h = h, w
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
            # For LR/RL, measure with horizontal=False so the outer
            # {} in labels like {A|B|C} flips to horizontal, producing
            # content-proportional field widths.  The returned (w, h)
            # is in LR-rendered coordinates (w = LR-final X-extent
            # along the rank axis, h = LR-final Y-extent across
            # ranks).  Pre-swap to TB-internal coordinates so the
            # rest of the layout pipeline (which always works in
            # TB-internal mode) sees w = cross-rank extent and h =
            # rank extent — _apply_rankdir will swap them back at
            # the end of phase 3.
            w, h = self._measure_record_tree(tree, False, fontsize, char_w)
            w, h = h, w  # convert LR-rendered → TB-internal (w=cross-rank, h=rank)
            # Clamp using the constants that match each axis in
            # TB-internal coordinates: cross-rank (w) ≥ MIN_HEIGHT
            # (the LR-final default Y-extent = 36), rank (h) ≥
            # MIN_WIDTH (the LR-final default X-extent = 54).  These
            # constants used to be reversed, which made the cross-
            # rank extent of every record collapse to ≥ 54pt and
            # caused the NS X solver to see all nodes as identically
            # sized, producing a degenerate single-column solution.
            return max(w, self._MIN_HEIGHT), max(h, self._MIN_WIDTH)
        else:
            w, h = self._measure_record_tree(tree, True, fontsize, char_w)
        return max(w, self._MIN_WIDTH), max(h, self._MIN_HEIGHT)

    def _measure_record_tree(self, node: dict, horizontal: bool,
                             fontsize: float, char_w: float) -> tuple[float, float]:
        """Recursively measure a record tree node, returning (width, height).

        See: ``lib/common/shapes.c: size_reclbl() @ 3539`` / ``place_rec()``
        — C recursively walks the field tree computing widths and heights,
        flipping orientation at each ``{`` / ``}`` boundary.
        """
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
        """Phase 1 driver: rank assignment via network simplex.

        See: ``lib/dotgen/rank.c: dot_rank() @ 545`` — the top-level rank
        assignment pass that calls ``rank1() @ 449`` then ``collapse_sets() @ 349``
        and finally ``rank3()`` to produce a feasible tree.

        Delegates to :func:`rank.phase1_rank`.
        """
        return rank.phase1_rank(self, *args, **kwargs)


    def _inject_same_rank_edges(self, *args, **kwargs):
        """Add zero-minlen constraint edges between ``rank=same`` nodes.

        See: ``lib/dotgen/rank.c: collapse_sets() @ 349`` which unions
        same-rank constraint sets and adds constraint edges before the
        network simplex solve.

        Delegates to :func:`rank.inject_same_rank_edges`.
        """
        return rank.inject_same_rank_edges(self, *args, **kwargs)


    def _classify_flat_edges(self, *args, **kwargs):
        """Tag edges between same-rank nodes as flat.

        See: ``lib/dotgen/flat.c: flat_edges() @ 259`` — classifies edges
        whose endpoints end up on the same rank after network simplex.

        Delegates to :func:`rank.classify_flat_edges`.
        """
        return rank.classify_flat_edges(self, *args, **kwargs)


    def _classify_edges(self, *args, **kwargs):
        """Set edge-type tags (normal / flat / self / virtual).

        See: edge-type classification in ``lib/dotgen/rank.c`` and
        ``lib/dotgen/dotinit.c`` — C sets ``ED_edge_type`` based on rank
        relationships.

        Delegates to :func:`rank.classify_edges`.
        """
        return rank.classify_edges(self, *args, **kwargs)


    def _cluster_aware_rank(self, *args, **kwargs):
        """Run network simplex with cluster boundary constraints.

        See: ``lib/dotgen/cluster.c`` + ``lib/dotgen/rank.c`` —
        cluster skeleton construction followed by per-cluster and
        outer-graph rank solves.

        Delegates to :func:`rank.cluster_aware_rank`.
        """
        return rank.cluster_aware_rank(self, *args, **kwargs)


    def _break_cycles(self, *args, **kwargs):
        """Reverse back-edges so the graph is acyclic.

        See: ``lib/dotgen/acyclic.c: acyclic() @ 58`` — DFS-based
        back-edge reversal.

        Delegates to :func:`rank.break_cycles`.
        """
        return rank.break_cycles(self, *args, **kwargs)


    def _network_simplex_rank(self, *args, **kwargs):
        """Solve the integer rank assignment via network simplex.

        See: ``lib/common/ns.c: rank() @ 1029`` — the generic network
        simplex solver (also used by the X-coordinate phase).  Called
        from ``lib/dotgen/rank.c: dot_rank() @ 545``.

        Delegates to :func:`rank.network_simplex_rank`.
        """
        return rank.network_simplex_rank(self, *args, **kwargs)


    def _apply_rank_constraints(self, *args, **kwargs):
        """Enforce ``rank=min/max/source/sink`` constraints post-NS.

        See: ``lib/dotgen/rank.c: rank1() @ 449`` + scan passes in
        ``acyclic.c`` that clamp constrained nodes to the top/bottom rank.

        Delegates to :func:`rank.apply_rank_constraints`.
        """
        return rank.apply_rank_constraints(self, *args, **kwargs)


    def _compact_ranks(self, *args, **kwargs):
        """Remove gaps in rank numbering (renumber 0..N-1).

        See: implicit in ``lib/dotgen/rank.c`` — C tracks
        ``GD_minrank`` / ``GD_maxrank`` and iterates the actual range.

        Delegates to :func:`rank.compact_ranks`.
        """
        return rank.compact_ranks(self, *args, **kwargs)


    def _add_virtual_nodes(self, *args, **kwargs):
        """Insert virtual nodes on long edges to make them unit-length.

        See: ``lib/dotgen/class2.c: make_chain() @ 70`` — replaces a
        multi-rank edge with a chain of virtual nodes and single-rank edges.

        Delegates to :func:`rank.add_virtual_nodes`.
        """
        return rank.add_virtual_nodes(self, *args, **kwargs)


    def _build_ranks(self, *args, **kwargs):
        """Populate ``layout.ranks`` dict from node rank assignments.

        See: ``lib/dotgen/mincross.c: build_ranks() @ 1277`` — groups nodes by
        rank into ``GD_rank(g)[r].v[i]`` arrays.

        Delegates to :func:`rank.build_ranks`.
        """
        return rank.build_ranks(self, *args, **kwargs)


    # ── Phase 2: Crossing minimization ───────────

    _CL_CROSS = 1000  # Graphviz CL_CROSS: penalty weight for crossing cluster borders

    def _mark_low_clusters(self, *args, **kwargs):
        """Delegates to gvpy.engines.layout.dot.mincross.mark_low_clusters."""
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
        """Phase 2 driver: crossing minimization.

        See: ``lib/dotgen/mincross.c: dot_mincross() @ 332`` — top-level
        crossing-minimization pass that runs ``mincross_step() @ 1540`` iterations
        with ``mincross_order`` and ``mincross_transpose`` sweeps.

        Delegates to :func:`mincross.phase2_ordering`.
        """
        return mincross.phase2_ordering(self, *args, **kwargs)


    def _run_mincross(self, *args, **kwargs):
        """Inner loop of ordering + transpose sweeps.

        See: ``lib/dotgen/mincross.c: mincross_step() @ 1540`` /
        ``mincross_core()`` — one pass of the median-based reordering
        followed by adjacent-swap transpose.

        Delegates to :func:`mincross.run_mincross`.
        """
        return mincross.run_mincross(self, *args, **kwargs)


    def _remincross_full(self, *args, **kwargs):
        """Re-run mincross after inserting flat-label virtual nodes.

        See: second ``dot_mincross()`` call after flat-label node
        insertion in ``lib/dotgen/dotinit.c``.

        Delegates to :func:`mincross.remincross_full`.
        """
        return mincross.remincross_full(self, *args, **kwargs)


    def _skeleton_mincross(self, *args, **kwargs):
        """Cluster-skeleton mincross (outer graph with clusters as units).

        See: ``lib/dotgen/mincross.c: mincross_clust() @ 584`` /
        the skeleton pass in ``dot_mincross()``.

        Delegates to :func:`mincross.skeleton_mincross`.
        """
        return mincross.skeleton_mincross(self, *args, **kwargs)


    def _flat_reorder(self, *args, **kwargs):
        """Reorder same-rank nodes via flat-edge constraints.

        See: ``lib/dotgen/flat.c: flat_edges() @ 259`` post-processing
        that reorders nodes based on flat-edge adjacency.

        Delegates to :func:`mincross.flat_reorder`.
        """
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
        """Scaled median-value computation for an edge's endpoint.

        See: ``lib/dotgen/mincross.c: mval()`` / the ``VAL`` macro
        in ``const.h:99`` — multiplies by MC_SCALE (256) for integer
        median arithmetic.

        Delegates to :func:`mincross.mval_edge`.
        """
        return mincross.mval_edge(self, *args, **kwargs)


    # _port_order_from_label and _split_record_fields removed �
    # port.order now comes from Node.record_fields.port_fraction()
    # (ANTLR4 RecordParser, sized at layout start).


    def _cluster_medians(self, *args, **kwargs):
        """Compute per-cluster median ordering for skeleton mincross.

        See: ``lib/dotgen/mincross.c: medians() @ 1699`` (line 1687).

        Delegates to :func:`mincross.cluster_medians`.
        """
        return mincross.cluster_medians(self, *args, **kwargs)


    def _cluster_reorder(self, *args, **kwargs):
        """Reorder cluster nodes by median values.

        See: ``lib/dotgen/mincross.c: reorder() @ 1488`` (line 1476).

        Delegates to :func:`mincross.cluster_reorder`.
        """
        return mincross.cluster_reorder(self, *args, **kwargs)


    def _cluster_build_ranks(self, *args, **kwargs) -> dict[int, list[str]]:
        """Build cluster-scoped rank arrays for skeleton mincross.

        See: ``lib/dotgen/mincross.c`` cluster skeleton rank
        construction (around ``mincross_clust``).

        Delegates to :func:`mincross.cluster_build_ranks`.
        """
        return mincross.cluster_build_ranks(self, *args, **kwargs)


    def _cluster_transpose(self, *args, **kwargs):
        """Transpose sweep within a cluster.

        See: ``lib/dotgen/mincross.c: transpose() @ 726`` called on
        cluster skeleton.

        Delegates to :func:`mincross.cluster_transpose`.
        """
        return mincross.cluster_transpose(self, *args, **kwargs)


    def _order_by_weighted_median(self, *args, **kwargs):
        """Reorder a rank by weighted-median of neighbor positions.

        See: ``lib/dotgen/mincross.c: reorder() @ 1488`` using ``mval`` /
        ``median()`` — one half of the barycentric crossing-min heuristic.

        Delegates to :func:`mincross.order_by_weighted_median`.
        """
        return mincross.order_by_weighted_median(self, *args, **kwargs)


    def _transpose_rank(self, *args, **kwargs):
        """Adjacent-swap transpose sweep on a single rank.

        See: ``lib/dotgen/mincross.c: transpose_step() @ 685`` —
        the inner swap loop of ``transpose() @ 726``.

        Delegates to :func:`mincross.transpose_rank`.
        """
        return mincross.transpose_rank(self, *args, **kwargs)


    def _count_crossings_for_pair(self, *args, **kwargs) -> int:
        """Count crossings between two adjacent ranks.

        See: ``lib/dotgen/mincross.c: in_cross() @ 634`` /
        ``out_cross() @ 653`` — counts inversions between adjacent rank pairs.

        Delegates to :func:`mincross.count_crossings_for_pair`.
        """
        return mincross.count_crossings_for_pair(self, *args, **kwargs)


    def _count_all_crossings(self, *args, **kwargs) -> int:
        """Sum edge crossings across all rank pairs.

        See: ``lib/dotgen/mincross.c: ncross() @ 1629`` — total graph
        crossing count used as the mincross objective.

        Delegates to :func:`mincross.count_all_crossings`.
        """
        return mincross.count_all_crossings(self, *args, **kwargs)


    def _count_scoped_crossings(self, *args, **kwargs) -> int:
        """Count crossings within a rank-range scope (for cluster mincross).

        See: scoped variant of ``ncross() @ 1629`` used by cluster-level
        mincross in ``lib/dotgen/mincross.c``.

        Delegates to :func:`mincross.count_scoped_crossings`.
        """
        return mincross.count_scoped_crossings(self, *args, **kwargs)


    def _save_ordering(self, *args, **kwargs) -> dict[str, int]:
        """Snapshot the current node-order array.

        See: ``lib/dotgen/mincross.c: save_best() @ 836`` — saves the
        best ordering seen so far during mincross iterations.

        Delegates to :func:`mincross.save_ordering`.
        """
        return mincross.save_ordering(self, *args, **kwargs)


    def _restore_ordering(self, *args, **kwargs):
        """Restore a previously-saved ordering snapshot.

        See: ``lib/dotgen/mincross.c: restore_best() @ 818``.

        Delegates to :func:`mincross.restore_ordering`.
        """
        return mincross.restore_ordering(self, *args, **kwargs)


    # ── Phase 3: Coordinate assignment ───────────

    _CL_OFFSET = 8.0  # Graphviz CL_OFFSET constant (points)

    # Settable routing-channel width.  This is the minimum clearance
    # the channel router maintains between edges and any non-endpoint
    # (cluster or node) — it controls the stub length, bridge column
    # margin, row-detour margin, and parallel-edge separation, and is
    # also the floor enforced by the position phase on node-to-node,
    # node-to-cluster-border, and sibling-cluster separations.
    #
    # Defaulting to ``_CL_OFFSET`` keeps behaviour unchanged; users
    # who want wider corridors can bump this single value instead of
    # editing the separate constants the router used to read.
    _routing_channel: float = _CL_OFFSET

    # Arrow-head budget at edge endpoints.  The channel router adds
    # this to ``_routing_channel`` when picking the stub length at
    # each endpoint, so the arrow (drawn backwards from the tip
    # along the final segment) fits in the outer half of the stub
    # and the inner half is free routing clearance.  Defaults to
    # the svg_renderer's ``_ARROW_SIZE`` so the standard 8pt arrow
    # always has room to draw without eating into the routing
    # corridor.
    _arrow_len: float = 8.0

    def _phase3_position(self):
        """Phase 3 entry point — delegates to position module.

        The implementation lives in ``gvpy/engines/dot/position.py``
        (See: ``lib/dotgen/position.c``).  Other Phase 3 helpers
        (``_set_ycoords``, ``_expand_leaves``, etc.) still live on this
        class and are called by the module via ``layout._xxx()``.  See
        ``TODO_core_refactor.md`` step 4 for the full extraction plan.
        """
        position.phase3_position(self)

    def _expand_leaves(self):
        """Expand leaf subgraphs (single-node clusters) into full clusters.

        See: ``lib/dotgen/position.c: expand_leaves() @ 1066``.

        Delegates to :func:`position.expand_leaves`.
        """
        return position.expand_leaves(self)

    def _insert_flat_label_nodes(self) -> bool:
        """Insert virtual label nodes for labeled flat edges.

        See: ``lib/dotgen/flat.c: flat_edges() @ 259`` +
        ``flat_node()`` — adds virtual label nodes to the rank above
        for labeled non-adjacent flat edges.

        Delegates to :func:`position.insert_flat_label_nodes`.
        """
        return position.insert_flat_label_nodes(self)

    def _set_ycoords(self):
        """Assign Y coordinates to each rank.

        See: ``lib/dotgen/position.c: set_ycoords() @ 781`` —
        sets ``ND_coord.y`` based on ranksep and per-rank heights.

        Delegates to :func:`position.set_ycoords`.
        """
        return position.set_ycoords(self)

    def _simple_x_position(self):
        """Quick X positioning: place nodes at their mincross order index.

        See: ``lib/dotgen/position.c`` simple fallback used before
        the network simplex X solve.

        Delegates to :func:`position.simple_x_position`.
        """
        return position.simple_x_position(self)

    def _median_x_improvement(self):
        """Refine X coordinates by moving nodes toward the median of neighbors.

        See: ``lib/dotgen/position.c`` median-improvement pass
        (``dot_position`` iterative refinement).

        Delegates to :func:`position.median_x_improvement`.
        """
        return position.median_x_improvement(self)

    def _bottomup_ns_x_position(self):
        """Cluster-inside-out network simplex X solve.

        See: ``lib/dotgen/position.c: dot_position() @ 128`` cluster-by-
        cluster NS-X solve that starts with innermost clusters.

        Delegates to :func:`position.bottomup_ns_x_position`.
        """
        return position.bottomup_ns_x_position(self)

    def _ns_x_position(self) -> bool:
        """Run the network simplex X-coordinate solver.

        See: ``lib/dotgen/position.c: dot_position() @ 128`` — runs
        network simplex (``lib/common/ns.c: rank() @ 1029``) on the auxiliary
        graph whose edges encode nodesep and edge-length constraints.

        Delegates to :func:`position.ns_x_position`.
        """
        return position.ns_x_position(self)

    def _resolve_cluster_overlaps(self):
        """Nudge overlapping clusters apart after the X solve.

        See: cluster-overlap cleanup in ``lib/dotgen/position.c``
        post-NS-X phase.

        Delegates to :func:`position.resolve_cluster_overlaps`.
        """
        return position.resolve_cluster_overlaps(self)

    def _post_rankdir_keepout(self):
        """Enforce minimum separation after rankdir rotation.

        See: post-rotation sanity pass in ``lib/dotgen/position.c``.

        Delegates to :func:`position.post_rankdir_keepout`.
        """
        return position.post_rankdir_keepout(self)

    def _center_ranks(self):
        """Center each rank horizontally within the graph bounding box.

        See: rank-centering logic inside ``dot_position`` when
        the NS-X solve under-constrains a rank's position.

        Delegates to :func:`position.center_ranks`.
        """
        return position.center_ranks(self)

    def _apply_rankdir(self):
        """Rotate coordinates based on rankdir (TB/LR/BT/RL).

        See: ``lib/dotgen/postproc.c: dot_sameports()`` +
        coord-rotation pass that applies ``GD_rankdir`` to the computed
        y-down TB-internal coordinates.

        Delegates to :func:`position.apply_rankdir`.
        """
        return position.apply_rankdir(self)

    def _apply_size(self):
        """Scale layout to fit within graph size attribute if set.

        See: ``lib/common/input.c: graph_init() @ 599`` +
        ``lib/common/emit.c: resize()`` — implements the ``size="W,H"``
        attribute including the ``!`` suffix for forcing upscale.
        """
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
        """Merge parallel edges that share the same tail and head.

        See: ``lib/dotgen/class1.c:class1()`` +
        ``lib/dotgen/class2.c:class2()`` — C's edge-concentration pass
        detects duplicate edges during ranking and uses a single spline
        for the group (``GD_concentrate``).
        """
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
        """Snap all node coordinates to a grid with spacing = quantum.

        See: ``lib/common/postproc.c: dotneato_postprocess() @ 691`` uses
        ``GD_drawing(g)->quantum`` to round positions — same algorithm.
        """
        q = self.quantum
        if q <= 0:
            return
        for ln in self.lnodes.values():
            ln.x = round(ln.x / q) * q
            ln.y = round(ln.y / q) * q

    def _apply_normalize(self):
        """Shift all coordinates so the minimum is at the origin.

        See: ``lib/common/postproc.c: translate_bb() @ 127`` — translates
        the graph bounding box so ``(LL.x, LL.y) == (0, 0)``.
        """
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
        """Apply pos= fixed positions, overriding computed coordinates.

        See: ``lib/common/input.c`` parses the ``pos`` attribute
        into ``ND_coord``; the layout engines honor the flag via
        ``ND_pinned`` during ranking/positioning.
        """
        for name, ln in self.lnodes.items():
            if ln.fixed_pos is not None:
                ln.x, ln.y = ln.fixed_pos

    # _apply_rotation inherited from LayoutEngine

    def _apply_center(self):
        """Shift layout so the center of the bounding box is at the origin.

        See: ``lib/common/postproc.c`` center-on-page logic
        honoring the ``center=true`` graph attribute.
        """
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
        # If the edge sets ``labelangle`` or ``labeldistance``, the C
        # path is ``place_portlabel`` (angle-based) rather than external
        # label placement.  Python mirrors this: F+.2's
        # :func:`label_place.make_port_labels` writes the same
        # ``_headlabel_pos_{x,y}`` / ``_taillabel_pos_{x,y}`` slots.
        # Without those attrs we keep the legacy grid-search path.
        from gvpy.engines.layout.dot.label_place import make_port_labels
        all_edges = [le for le in self.ledges if not le.virtual] + self._chain_edges
        for le in all_edges:
            if not le.edge or not le.points:
                continue
            try:
                fs = float(le.edge.attributes.get("labelfontsize",
                           le.edge.attributes.get("fontsize", "14")))
            except ValueError:
                fs = 14.0

            attrs = le.edge.attributes
            angle_based = bool(attrs.get("labelangle", "")) \
                        or bool(attrs.get("labeldistance", ""))

            if angle_based:
                # C-matching path: place_portlabel writes positions into
                # the same attribute slots.  Record in ``placed`` so
                # subsequent grid-searched labels avoid overlap.
                make_port_labels(self, le)
                for key in ("headlabel", "taillabel"):
                    txt = attrs.get(key, "")
                    if not txt:
                        continue
                    lw, lh = self._estimate_label_size(txt, fs)
                    prefix = "_headlabel_pos" if key == "headlabel" else "_taillabel_pos"
                    try:
                        bx = float(attrs.get(f"{prefix}_x", ""))
                        by = float(attrs.get(f"{prefix}_y", ""))
                    except ValueError:
                        continue
                    placed.append((bx, by, lw, lh))
                continue

            headlabel = attrs.get("headlabel", "")
            if headlabel:
                lw, lh = self._estimate_label_size(headlabel, fs)
                hp = le.points[-1]
                # Use small anchor box at head endpoint
                bx, by = _find_best_position(hp[0], hp[1], 2, 2, lw, lh, pad=6.0)
                attrs["_headlabel_pos_x"] = str(round(bx, 2))
                attrs["_headlabel_pos_y"] = str(round(by, 2))
                placed.append((bx, by, lw, lh))

            taillabel = attrs.get("taillabel", "")
            if taillabel:
                lw, lh = self._estimate_label_size(taillabel, fs)
                tp = le.points[0]
                bx, by = _find_best_position(tp[0], tp[1], 2, 2, lw, lh, pad=6.0)
                attrs["_taillabel_pos_x"] = str(round(bx, 2))
                attrs["_taillabel_pos_y"] = str(round(by, 2))
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
        """Phase 4 driver: edge routing.

        See: ``lib/dotgen/dotsplines.c: dot_splines() @ 503`` +
        ``dot_splines_() @ 229`` — the top-level spline routing entry point
        that dispatches each edge to ``make_regular_edge`` /
        ``make_flat_edge`` / ``makeSelfEdge`` based on edge type.

        Delegates to :func:`dotsplines.phase4_routing`.
        """
        return dotsplines.phase4_routing(self, *args, **kwargs)


    def _clip_compound_edges(self, *args, **kwargs):
        """Clip compound (cluster-to-cluster) edges to cluster boundaries.

        See: ``lib/common/dotsplines.c`` compound-edge clipping logic
        triggered by ``lhead`` / ``ltail`` attributes.

        Delegates to :func:`dotsplines.clip_compound_edges`.
        """
        return dotsplines.clip_compound_edges(self, *args, **kwargs)


    @staticmethod
    def _clip_to_bb(inside, *args, **kwargs) -> tuple | None:
        """Clip a point/line to a bounding box.

        Class-callable alias to module function ``dotsplines.clip_to_bb``.
        Staticmethod (not instance method) — the first arg is the
        ``inside`` point, not ``self``.

        See: geometry helpers in ``lib/common/geomprocs.c`` —
        ``lineToBox`` / equivalent.
        """
        return dotsplines.clip_to_bb(inside, *args, **kwargs)


    @staticmethod
    def _to_bezier(pts, *args, **kwargs) -> list[tuple]:
        """Convert a polyline to a smooth cubic Bezier control sequence.

        Class-callable alias to module function ``dotsplines.to_bezier``.
        Staticmethod — the first arg is the point list, not ``self``.

        See: ``lib/pathplan/util.c: make_polyline() @ 44`` +
        B-spline fitting in ``lib/dotgen/dotsplines.c``.
        """
        return dotsplines.to_bezier(pts, *args, **kwargs)


    def _edge_start_point(self, *args, **kwargs) -> tuple[float, float]:
        """Compute the starting point on the tail node's boundary.

        See: port-resolution logic in ``lib/common/dotsplines.c``
        that combines ``ND_coord`` + ``ED_tail_port.p`` into the
        edge's anchor point.

        Delegates to :func:`dotsplines.edge_start_point`.
        """
        return dotsplines.edge_start_point(self, *args, **kwargs)


    def _edge_end_point(self, *args, **kwargs) -> tuple[float, float]:
        """Compute the ending point on the head node's boundary.

        See: mirror of :meth:`_edge_start_point` using
        ``ED_head_port``.

        Delegates to :func:`dotsplines.edge_end_point`.
        """
        return dotsplines.edge_end_point(self, *args, **kwargs)


    def _record_port_point(self, *args, **kwargs) -> tuple[float, float] | None:
        """Look up a record-shape port's anchor point by name.

        See: ``lib/common/shapes.c: record_port() @ 3810`` — walks the
        record field tree to find a named port's bounding box center.

        Delegates to :func:`dotsplines.record_port_point`.
        """
        return dotsplines.record_port_point(self, *args, **kwargs)


    @staticmethod
    def _port_point(ln, *args, **kwargs):
        """Resolve a compass port string to an offset on the node boundary.

        Class-callable alias to module function ``dotsplines.port_point``.
        Staticmethod — the first arg is a ``LayoutNode``, not ``self``.

        See: ``lib/common/shapes.c: compassPort() @ 2699`` +
        ``lib/common/shapes.c: poly_port() @ 2893``.
        """
        return dotsplines.port_point(ln, *args, **kwargs)


    @staticmethod
    def _compute_label_pos(le, *args, **kwargs):
        """Position an edge label at the midpoint of its spline.

        Class-callable alias to module function ``dotsplines.compute_label_pos``.
        Staticmethod — the first arg is a ``LayoutEdge``, not ``self``.

        See: ``lib/common/dotsplines.c: edgeMidpoint() @ 1283`` /
        ``addEdgeLabels() @ 1307``.
        """
        return dotsplines.compute_label_pos(le, *args, **kwargs)


    def _apply_sameport(self, *args, **kwargs):
        """Merge edge endpoints sharing ``samehead`` / ``sametail``.

        See: ``lib/dotgen/sameport.c: dot_sameports() @ 41`` —
        coalesces multiple edges meeting at the same port so they
        share a common anchor point.

        Delegates to :func:`dotsplines.apply_sameport`.
        """
        return dotsplines.apply_sameport(self, *args, **kwargs)


    def _ortho_route(self, *args, **kwargs) -> list[tuple[float, float]]:
        """Route an edge as a rectilinear polyline for ``splines=ortho``.

        See: ``lib/ortho/ortho.c: orthoEdges() @ 1162`` — orthogonal edge
        router based on the Sander / Eades algorithm.

        Delegates to :func:`dotsplines.ortho_route`.
        """
        return dotsplines.ortho_route(self, *args, **kwargs)


    @staticmethod
    def _boundary_point(ln, *args, **kwargs) -> tuple[float, float]:
        """Intersect a line from node center outward with the node boundary.

        Class-callable alias to module function ``dotsplines.boundary_point``.
        Staticmethod — the first arg is a ``LayoutNode``, not ``self``.

        See: ``lib/common/shapes.c`` shape-specific boundary
        intersection (``poly_path`` / ``ellipse_path``).
        """
        return dotsplines.boundary_point(ln, *args, **kwargs)


    @staticmethod
    def _self_loop_points(ln, *args, **kwargs) -> list[tuple[float, float]]:
        """Route a self-loop edge (simple heuristic fallback).

        Class-callable alias to module function ``dotsplines.self_loop_points``.
        Staticmethod — the first arg is a ``LayoutNode``, not ``self``.

        See: ``lib/common/dotsplines.c: makeSelfEdge() @ 1164`` +
        ``selfRight`` / ``selfLeft`` / ``selfTop`` / ``selfBottom``.
        The C-matching port lives in :mod:`self_edge`.
        """
        return dotsplines.self_loop_points(ln, *args, **kwargs)


    def _maximal_bbox(self, vn_ln, ie=None, oe=None):
        """Compute maximum bbox a virtual node can claim on its rank.

        See: ``lib/dotgen/dotsplines.c: maximal_bbox() @ 2204``
        (lines 2170-2226) — computes the cross-rank extent a virtual
        node can occupy without hitting same-rank neighbours or
        non-member clusters.

        Requires ``self._spline_info`` to be populated (phase-4 only).
        Returns a :class:`Box`.

        Delegates to :func:`dotsplines.maximal_bbox`.
        """
        return dotsplines.maximal_bbox(self, self._spline_info, vn_ln, ie, oe)


    def _rank_box(self, r: int):
        """Return the inter-rank corridor box between ranks r and r+1.

        See: ``lib/dotgen/dotsplines.c: rank_box() @ 2045`` (lines 2011-2024)
        — full-graph-width box from the bottom of rank r to the top of
        rank r+1, cached in ``sp.Rank_box[r]``.

        Requires ``self._spline_info`` to be populated (only true during
        a phase-4 routing pass).  Returns a :class:`Box`.

        Delegates to :func:`dotsplines.rank_box`.
        """
        return dotsplines.rank_box(self, self._spline_info, r)




    def _classify_flat_edge(self, *args, **kwargs) -> str:
        """Classify a flat edge as adjacent / labeled / bottom / top.

        See: dispatch logic inside
        ``lib/dotgen/dotsplines.c: make_flat_edge() @ 1538``.

        Delegates to :func:`dotsplines.classify_flat_edge`.
        """
        return dotsplines.classify_flat_edge(self, *args, **kwargs)


    def _count_flat_edge_index(self, *args, **kwargs) -> int:
        """Return the multi-edge index among parallel flat edges.

        See: the ``cnt`` counter in
        ``lib/dotgen/dotsplines.c: make_flat_edge() @ 1538`` loop that offsets
        parallel flat edges.

        Delegates to :func:`dotsplines.count_flat_edge_index`.
        """
        return dotsplines.count_flat_edge_index(self, *args, **kwargs)


    def _flat_edge_route(self, *args, **kwargs) -> list[tuple[float, float]]:
        """Legacy heuristic flat-edge dispatcher (replaced in Phase E).

        See: ``lib/dotgen/dotsplines.c: make_flat_edge() @ 1538``.
        The C-matching port lives in :mod:`flat_edge`.

        Delegates to :func:`dotsplines.flat_edge_route` (legacy fallback).
        """
        return dotsplines.flat_edge_route(self, *args, **kwargs)


    def _flat_adjacent(self, *args, **kwargs):
        """Legacy heuristic for adjacent flat edges.

        See: ``lib/dotgen/dotsplines.c: makeSimpleFlat() @ 1111``.
        The C-matching port lives in :mod:`flat_edge`.

        Delegates to :func:`dotsplines.flat_adjacent` (legacy fallback).
        """
        return dotsplines.flat_adjacent(self, *args, **kwargs)


    def _flat_labeled(self, *args, **kwargs):
        """Legacy heuristic for labeled flat edges.

        See: ``lib/dotgen/dotsplines.c: make_flat_labeled_edge() @ 1350``.
        The C-matching port lives in :mod:`flat_edge`.

        Delegates to :func:`dotsplines.flat_labeled` (legacy fallback).
        """
        return dotsplines.flat_labeled(self, *args, **kwargs)


    def _flat_arc(self, *args, **kwargs):
        """Legacy heuristic for arc-routed flat edges.

        See: ``lib/dotgen/dotsplines.c: make_flat_bottom_edges() @ 1454``
        and the top-arc corridor in ``make_flat_edge()``.  The C-matching
        port lives in :mod:`flat_edge`.

        Delegates to :func:`dotsplines.flat_arc` (legacy fallback).
        """
        return dotsplines.flat_arc(self, *args, **kwargs)


    # ── Write-back and output ────────────────────

    def _write_back(self):
        """Write layout results back to graph object attributes.

        Sets ``pos``, ``width``, ``height`` on each node so that the
        graph can be serialized with embedded layout coordinates.

        See: ``lib/common/output.c: attach_attrs_and_arrows() @ 254``
        which writes ``pos``/``width``/``height``/``bb``/etc. attributes
        back onto the ``cgraph`` objects for emission.
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
        """Serialize the computed layout to a JSON-friendly dict.

        See: ``lib/common/output.c: write_json()`` +
        ``-Tjson`` output format — produces a dict with
        ``name`` / ``bb`` / ``nodes`` / ``edges`` / ``clusters`` keys.
        """
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
            # Include record port positions from Node.record_fields.
            # Emitted as a linear fraction [0..1] along the node's
            # cross-rank face — the same convention used by
            # dotsplines.record_port_point for edge attach points, so
            # downstream renderers (pictosync) can reproduce the exact
            # attach coordinates the layout engine used.  We do NOT
            # emit port_fraction() here because that returns C's
            # compassPort angle-based order (used internally by
            # mincross for port ordering), which a downstream renderer
            # would misinterpret as a linear fraction and collapse
            # middle ports to the top of the node.
            if ln.node and ln.node.record_fields is not None:
                rf = ln.node.record_fields
                ports_dict = {}
                is_lr = self.rankdir in ("LR", "RL")
                rec_extent = max(rf.height if is_lr else rf.width, 1e-9)
                def _collect_port_fracs(f):
                    if f.port:
                        pp = rf.port_position(f.port)
                        if pp is not None:
                            cr = pp[1] if is_lr else pp[0]
                            frac = max(0.0, min(1.0, cr / rec_extent))
                            ports_dict[f.port] = frac
                    for c in f.children:
                        _collect_port_fracs(c)
                _collect_port_fracs(rf)
                if ports_dict:
                    entry["record_ports"] = ports_dict

                # D7 — emit the ANTLR4-parsed field tree so svg_renderer
                # uses the same structure the layout engine computed
                # port.order from, instead of re-parsing the label
                # string with its own hand-written parser.  The two
                # parsers produce structurally equivalent trees in the
                # common case, but any divergence would place ports
                # visually differently from where the layout put them.
                # Base orientation: TB/BT → LR fields (horizontal=True);
                # LR/RL → TB fields (horizontal=False).
                base_lr = not is_lr
                entry["record_tree"] = _record_field_to_svg_dict(
                    rf, base_lr)
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
