"""Top-level layout initialization for the dot engine.

C analogue: ``lib/dotgen/dotinit.c`` and the ``class1.c`` /
``class2.c`` initialization paths.  In C this is the
``dot_init_node`` / ``dot_init_edge`` / ``dot_init_graph`` family
of functions that walk the cgraph tree and populate the per-node /
per-edge / per-graph engine info structs.

In Python the equivalent work is reading the parsed
:class:`gvpy.core.graph.Graph` (which the ANTLR4 reader produced)
and populating ``DotGraphInfo``'s ``lnodes``, ``ledges``,
``ranks``, ``_clusters``, and ``_rank_constraints`` containers
along with all the graph-attribute defaults (rankdir, ranksep,
nodesep, splines, etc.).

Responsibilities
----------------
- :func:`init_from_graph` — top-level init.  Reads graph
  attributes, builds ``layout.lnodes`` from the parsed graph,
  collects edges and clusters, deduplicates cluster membership,
  and reads rank constraints.

- :func:`collect_rank_constraints` — read ``rank=same`` /
  ``rank=min`` / ``rank=max`` / ``rank=source`` / ``rank=sink``
  attributes from subgraphs and record them on
  ``layout._rank_constraints`` for Phase 1.

- :func:`scan_subgraphs` — recursive helper for
  ``collect_rank_constraints``.

- :func:`collect_edges` and :func:`collect_edges_recursive` —
  walk the parsed graph (and all its subgraphs) and create one
  LayoutEdge per real edge in ``layout.ledges``.

Extracted functions
-------------------
All 5 init methods moved from ``DotGraphInfo`` in ``dot_layout.py``
as free functions taking ``layout`` as the first argument.

Related modules
---------------
- :mod:`gvpy.engines.dot.cluster` — :func:`init_from_graph` calls
  ``layout._collect_clusters()`` (which now lives in cluster.py)
  to populate ``layout._clusters``.
- :mod:`gvpy.engines.dot.rank` — Phase 1 reads the populated
  ``layout.lnodes`` / ``layout.ledges`` / ``layout._clusters``.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.engines.dot.dot_layout import DotGraphInfo, LayoutNode, LayoutEdge


def init_from_graph(layout):
    """Top-level layout init.

    C analogue: ``lib/dotgen/dotinit.c:dot_init_node()`` and the
    associated ``dot_init_*`` family.  Reads graph attributes,
    builds LayoutNode entries from each parsed graph node (sizing
    record fields, capturing pin/pos), collects edges, and reads
    cluster + rank constraint metadata.
    """
    # Lazy imports — both classes live in dot_layout.py.
    from gvpy.engines.dot.dot_layout import LayoutNode
    rd = layout.graph.get_graph_attr("rankdir")
    if rd:
        layout.rankdir = rd.upper()

    rs = layout.graph.get_graph_attr("ranksep")
    if rs:
        try:
            layout.ranksep = float(rs) * 72.0
        except ValueError:
            pass

    ns = layout.graph.get_graph_attr("nodesep")
    if ns:
        try:
            layout.nodesep = float(ns) * 72.0
        except ValueError:
            pass

    layout.splines = (layout.graph.get_graph_attr("splines") or "").lower()
    layout.ordering = (layout.graph.get_graph_attr("ordering") or "").lower()
    layout.concentrate = (layout.graph.get_graph_attr("concentrate") or "").lower() == "true"
    layout.compound = (layout.graph.get_graph_attr("compound") or "").lower() == "true"
    layout.ratio = (layout.graph.get_graph_attr("ratio") or "").lower()

    # Optimization parameters
    for attr, field, conv in [
        ("nslimit", "nslimit", int), ("nslimit1", "nslimit1", int),
        ("searchsize", "searchsize", int),
        ("mclimit", "mclimit", float), ("quantum", "quantum", float),
    ]:
        val = layout.graph.get_graph_attr(attr)
        if val:
            try:
                setattr(layout, field, conv(val))
            except ValueError:
                pass
    layout.remincross = (layout.graph.get_graph_attr("remincross") or "").lower() in ("true", "1", "yes")
    layout.normalize = (layout.graph.get_graph_attr("normalize") or "").lower() in ("true", "1", "yes")
    layout.clusterrank = (layout.graph.get_graph_attr("clusterrank") or "local").lower()
    layout.newrank = (layout.graph.get_graph_attr("newrank") or "").lower() in ("true", "1", "yes")
    layout.center = (layout.graph.get_graph_attr("center") or "").lower() in ("true", "1", "yes")
    layout.landscape = (layout.graph.get_graph_attr("landscape") or "").lower() in ("true", "1", "yes")
    layout.forcelabels = (layout.graph.get_graph_attr("forcelabels") or "true").lower() not in ("false", "0", "no")
    layout.outputorder = (layout.graph.get_graph_attr("outputorder") or "breadthfirst").lower()

    pad_str = layout.graph.get_graph_attr("pad")
    if pad_str:
        try:
            layout.pad = float(pad_str) * 72.0
        except ValueError:
            pass

    dpi_str = layout.graph.get_graph_attr("dpi") or layout.graph.get_graph_attr("resolution")
    if dpi_str:
        try:
            layout.dpi = float(dpi_str)
        except ValueError:
            pass

    rot_str = layout.graph.get_graph_attr("rotate")
    if rot_str:
        try:
            layout.rotate_deg = int(rot_str)
        except ValueError:
            pass

    size_str = layout.graph.get_graph_attr("size")
    if size_str:
        try:
            parts = size_str.rstrip("!").split(",")
            layout.graph_size = (float(parts[0]) * 72.0, float(parts[1]) * 72.0)
        except (ValueError, IndexError):
            pass

    for name, node in layout.graph.nodes.items():
        w, h = layout._compute_node_size(name, node)
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
            if layout.rankdir in ("LR", "RL"):
                layout._flip_record_lr(node.record_fields)
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
        layout.lnodes[name] = ln

    layout._collect_edges(layout.graph)

    # Read pack attribute
    pack_str = layout.graph.get_graph_attr("pack")
    layout.pack = pack_str is None or pack_str.lower() not in ("false", "0", "no")
    pack_sep = layout.graph.get_graph_attr("packmode") or ""
    layout.pack_sep = 16.0  # default gap between components
    if pack_str:
        try:
            layout.pack_sep = float(pack_str)
        except ValueError:
            pass

    if not layout.graph.directed:
        layout._orient_undirected()

    layout._collect_rank_constraints()
    layout._collect_clusters()


def collect_rank_constraints(layout):
    """Read ``rank=same|min|max|source|sink`` constraints from subgraphs.

    C analogue: ``lib/dotgen/rank.c:collapse_sets()`` (and the
    ``rank=...`` handling in ``class1.c``/``class2.c``).  C walks the
    subgraph tree looking for ``GD_set_type(sg)`` and records the
    node-set so the rank assignment phase can collapse them onto one
    rank (or pin them to source/sink).
    """
    layout._rank_constraints = []
    layout._scan_subgraphs(layout.graph)


def scan_subgraphs(layout, g: Graph):
    """Recursive helper for :func:`collect_rank_constraints`.

    C analogue: the recursive subgraph walk inside
    ``lib/dotgen/rank.c:collapse_sets()`` that descends through
    ``GD_clust(g)`` / nested subgraphs gathering each subgraph's
    ``rank=...`` attribute.
    """
    for sub_name, sub in g.subgraphs.items():
        rank_attr = sub.get_graph_attr("rank")
        if rank_attr and rank_attr in ("same", "min", "max", "source", "sink"):
            node_names = [n for n in sub.nodes if n in layout.lnodes]
            if node_names:
                layout._rank_constraints.append((rank_attr, node_names))
        layout._scan_subgraphs(sub)


def collect_edges(layout, g: Graph):
    """Recursively collect edges from graph and all subgraphs.

    C analogue: ``lib/dotgen/dotinit.c:dot_init_edge()`` and the
    cgraph walk in ``class2.c`` that visits every edge in the root
    graph plus all subgraphs.  In C, edges are visited via
    ``agfstedge``/``agnxtedge``; here we use ``g.edges`` plus a
    recursive descent into ``g.subgraphs`` with an ``id()``-based
    seen-set to avoid double-counting shared edges.
    """
    seen = set()  # avoid duplicates from shared edges
    layout._collect_edges_recursive(g, seen)


def collect_edges_recursive(layout, g: Graph, seen: set):
    # Lazy import — LayoutEdge lives in dot_layout.py.
    from gvpy.engines.dot.dot_layout import LayoutEdge
    for key, edge in g.edges.items():
        if id(edge) in seen:
            continue
        seen.add(id(edge))
        tail_name, head_name, _ = key
        if tail_name not in layout.lnodes or head_name not in layout.lnodes:
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
        layout.ledges.append(LayoutEdge(
            edge=edge, tail_name=tail_name, head_name=head_name,
            minlen=ml, weight=wt, constraint=has_constraint,
            label=label, tailport=tp, headport=hp,
            lhead=lh, ltail=lt, headclip=hc, tailclip=tc,
            samehead=sh, sametail=st,
        ))
    for sub in g.subgraphs.values():
        layout._collect_edges_recursive(sub, seen)

