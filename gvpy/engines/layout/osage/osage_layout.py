"""C-aligned port of ``lib/osage/osageinit.c`` — recursive
cluster-packing layout.

Osage lays out a graph as a containment hierarchy: each cluster
subgraph becomes a rectangle that holds its direct-member nodes
plus the bboxes of its child clusters.  At every level, those
rectangles are arranged into a roughly-square grid via the
``packmode=array`` algorithm
(:mod:`gvpy.engines.layout.osage.pack`).

Algorithm (mirrors C ``osage_layout`` verbatim, ``osageinit.c:317``):

1. ``cluster_init_graph`` — set every edge to ``EDGETYPE_LINE``
   (osage doesn't do spline routing).
2. ``mkClusters`` — discover the cluster hierarchy.  A subgraph
   counts as a cluster iff its name starts with ``cluster``.
3. ``layout(g, depth=0)`` — bottom-up.  For each cluster:
   - Recurse into subclusters first.
   - Collect bboxes: subcluster ``bb`` + direct-node
     ``(width × height)``.
   - Call :func:`gvpy.engines.layout.osage.pack.put_rects` to
     position them.
   - Translate bboxes by their displacements; expand a running
     ``rootbb`` union.
   - Add label space at top if the cluster has a label.
   - Add per-side margin (depth > 0 only — root has no extra
     margin).
   - Translate so ``rootbb.LL == origin``.
4. ``reposition(g, depth=0)`` — top-down.  Translate every
   subcluster bbox and direct-node coord by the parent's
   ``bb.LL`` so positions become absolute.
5. Edge routing: straight lines (``spline_edges1`` with
   ``EDGETYPE_LINE``).

The ``pack`` (margin) and ``packmode`` (mode + flags + size)
graph attributes are honored — the ``pack.py`` parser handles
the full C grammar (``array_uXX``, ``array_cl5``, etc.).

Per-node ``sortv`` and per-cluster ``sortv`` are used when
``packmode=array_u`` is set (PK_USER_VALS); the array packer
sorts ascending by the sortv values so users can control the
reading order of the packed grid.

Differences from the legacy Python implementation (replaced
2026-05-09):

- Legacy ``_array_pack`` was an approximation that didn't match
  C's per-column / per-row max-size computation, didn't sort by
  ``width + height`` (it only sorted by ``sortv``), and didn't
  honor any of the alignment flags.
- Legacy treated the cluster bbox as ``(margin*2 + max_xy)``
  with a fixed margin everywhere; C uses depth-dependent margins
  (root has 0 margin, descendants have ``pinfo.margin / 2``).
- Legacy didn't run a separate ``reposition`` pass — it computed
  global positions inline during recursion which led to subtle
  off-by-one errors at deep nesting.
- Legacy had no support for the full ``packmode`` grammar —
  ``packmode=array_u`` wasn't recognized, so user-value sorting
  silently fell back to default sort.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine
from gvpy.engines.layout.osage.pack import (
    DFLT_MARGIN,
    PackInfo,
    PackMode,
    PK_USER_VALS,
    get_pack_info,
    put_rects,
)


# Default fallback size when a cluster has no children at all
# (osageinit.c:34 ``DFLT_SZ``).  Keeps degenerate empty clusters
# from collapsing to zero area.
_DFLT_SZ: float = 18.0


@dataclass
class LayoutNode:
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False
    sortv: int = 0
    # ``parent_cluster`` is the most-deeply-nested cluster that
    # owns this node, or None for a root-level free node.  Set
    # during ``mkClusters``.  Mirrors C ``ND_alg(n)``
    # (osageinit.c:35).
    parent_cluster: Optional["ClusterBox"] = None


@dataclass
class ClusterBox:
    """Recursive cluster container.

    Mirrors C's per-cluster state (``GD_clust``, ``GD_bb``,
    ``GD_label``, ``GD_n_cluster``).  Each cluster owns:

    - ``children`` — direct-member nodes (names) NOT in any
      deeper subcluster.
    - ``sub_clusters`` — direct child clusters.
    - ``bb`` — ``(LL_x, LL_y, UR_x, UR_y)`` after layout.
      Initially ``None``; set by :meth:`OsageLayout._layout_pass`.

    The label is rendered above the cluster's interior by
    reserving label-height pixels at the top.  We use a simple
    constant per-line height (the C label rendering machinery
    is in dotgen and would be a separate port).
    """
    name: str
    is_cluster: bool = True
    label: str = ""
    sortv: int = 0
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    sub_clusters: list["ClusterBox"] = field(default_factory=list)
    bb: Optional[tuple[float, float, float, float]] = None  # LLx, LLy, URx, URy
    label_height: float = 0.0


class OsageLayout(LayoutEngine):
    """Recursive cluster-packing layout engine.

    Use::

        from gvpy.engines.layout.osage import OsageLayout
        result = OsageLayout(graph).layout()

    The ``packmode`` graph attribute selects the packing
    algorithm (default ``array``).  See
    :mod:`gvpy.engines.layout.osage.pack` for the full grammar.
    The ``pack`` attribute sets the margin in pt (default 8).
    """

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self._root_box: Optional[ClusterBox] = None
        # Filled during reposition; consumed by ``_build_result``.
        self._cluster_records: list[dict] = []

    # ── Public entry ─────────────────────────────────────────

    def layout(self) -> dict:
        self._init_from_graph()
        # 1. Discover the cluster hierarchy.
        self._root_box = self._make_clusters()
        # 2. Bottom-up: pack each cluster, set its bb relative to
        #    its parent.
        self._layout_pass(self._root_box, depth=0)
        # 3. Top-down: translate everything to absolute coords.
        self._reposition_pass(self._root_box, depth=0)

        # Standard postprocessing.
        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        self._compute_label_positions()
        self._write_back()
        return self._build_result()

    # ── Initialization ───────────────────────────────────────

    def _init_from_graph(self) -> None:
        self._init_common_attrs()
        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)
            try:
                ln.sortv = int(node.attributes.get("sortv", "0"))
            except (TypeError, ValueError):
                pass
            self.lnodes[name] = ln

    # ── 1. Cluster hierarchy discovery ───────────────────────

    def _make_clusters(self) -> ClusterBox:
        """Mirrors C ``mkClusters`` (osageinit.c:280).

        Walks the subgraph tree.  A subgraph is a cluster iff
        its name starts with ``cluster``.  Non-cluster subgraphs
        are flattened into their nearest cluster ancestor (so
        e.g. ``subgraph S { node [shape=box]; a; b; }`` lifts
        ``a`` and ``b`` up to the parent cluster).

        Each node ends up assigned to exactly one ``ClusterBox``
        — either a real cluster or the synthetic root.  This is
        the ``ND_alg(n) = g`` step (osageinit.c:123).
        """
        assigned: set[str] = set()
        root = ClusterBox(name=self.graph.name, is_cluster=False)

        def walk(subgraph, parent_box: ClusterBox) -> None:
            for sg_name, sg in subgraph.subgraphs.items():
                if self._is_cluster_name(sg_name):
                    cl = ClusterBox(
                        name=sg_name,
                        is_cluster=True,
                        label=self._cluster_label(sg),
                    )
                    self._populate_cluster_attrs(sg, cl)
                    parent_box.sub_clusters.append(cl)
                    walk(sg, cl)
                else:
                    # Non-cluster subgraph — its nodes / nested
                    # clusters fold into ``parent_box``.
                    walk(sg, parent_box)
            # Direct-member nodes not yet assigned to a deeper
            # cluster join ``parent_box``.
            for node_name in subgraph.nodes:
                if node_name in assigned:
                    continue
                if node_name not in self.lnodes:
                    continue
                parent_box.children.append(node_name)
                assigned.add(node_name)
                self.lnodes[node_name].parent_cluster = parent_box

        walk(self.graph, root)

        # Any node not assigned to any subgraph (root-level free
        # node) joins ``root.children``.
        for name in self.lnodes:
            if name not in assigned:
                root.children.append(name)
                assigned.add(name)
                self.lnodes[name].parent_cluster = root

        return root

    @staticmethod
    def _is_cluster_name(name: str) -> bool:
        """Mirrors C ``is_a_cluster`` (lib/common/utils.c).

        A subgraph is a cluster iff its name starts with
        ``cluster``.  Case-sensitive — matches Graphviz.
        """
        return name.startswith("cluster")

    @staticmethod
    def _cluster_label(subgraph) -> str:
        return (
            subgraph.get_graph_attr("label")
            or subgraph.attr_record.get("label", "")
            or ""
        )

    def _populate_cluster_attrs(
        self, subgraph, cl: ClusterBox,
    ) -> None:
        """Read cluster visual attributes for SVG/JSON output."""
        for attr in (
            "color", "fillcolor", "style", "penwidth",
            "fontname", "fontsize", "fontcolor",
            "bgcolor", "label", "labelloc", "labeljust",
        ):
            val = (
                subgraph.get_graph_attr(attr)
                or subgraph.attr_record.get(attr)
            )
            if val:
                cl.attrs[attr] = val
        try:
            sv_str = (
                subgraph.get_graph_attr("sortv")
                or subgraph.attr_record.get("sortv", "0")
            )
            cl.sortv = int(sv_str)
        except (ValueError, TypeError):
            pass

    # ── 2. Bottom-up layout pass ─────────────────────────────

    def _layout_pass(self, box: ClusterBox, depth: int) -> None:
        """Mirrors C ``layout(g, depth)`` (osageinit.c:67).

        Bottom-up: lay out every subcluster, then pack
        ``(subclusters + direct nodes)`` into a grid via
        :func:`put_rects`.  Sets ``box.bb`` to the cluster's
        local bbox with ``LL = (0, 0)``.
        """
        # Recurse first.
        for sub in box.sub_clusters:
            self._layout_pass(sub, depth + 1)

        # Read packmode + margin attributes for this scope.
        pinfo = self._pack_info_for(box, depth)

        n_clusters = len(box.sub_clusters)
        n_direct = len(box.children)
        total = n_clusters + n_direct

        if total == 0 and not box.label:
            # Empty cluster with no label: degenerate placeholder
            # box (osageinit.c:91-94).
            box.bb = (0.0, 0.0, _DFLT_SZ, _DFLT_SZ)
            return

        # Build bbox list and parallel name/kind lists.  Order:
        # subclusters first, then direct nodes (matches C
        # osageinit.c:111-130).
        bbs: list[tuple[float, float, float, float]] = []
        kinds: list[str] = []      # "cluster" or "node"
        names: list[str] = []
        vals: list[int] = []

        want_user_vals = (
            pinfo.mode == PackMode.L_ARRAY
            and (pinfo.flags & PK_USER_VALS)
        )

        for sub in box.sub_clusters:
            assert sub.bb is not None
            bbs.append(sub.bb)
            kinds.append("cluster")
            names.append(sub.name)
            vals.append(sub.sortv)

        for node_name in box.children:
            ln = self.lnodes[node_name]
            bbs.append((0.0, 0.0, ln.width, ln.height))
            kinds.append("node")
            names.append(node_name)
            vals.append(ln.sortv)

        if want_user_vals:
            pinfo.vals = vals

        # Pack.  ``places[i]`` is the displacement to apply to
        # ``bbs[i].LL`` and ``.UR``.
        places = put_rects(bbs, pinfo)
        if places is None:
            # Unsupported mode — fall back to single-column
            # stacking so we still produce a valid layout.
            places = [(0.0, sum(bb[3] - bb[1] for bb in bbs[:i]))
                      for i in range(len(bbs))]

        # 3. Compute the running rootbb union and translate the
        # subcluster bboxes / record direct-node centers.
        rootbb_llx = float("inf")
        rootbb_lly = float("inf")
        rootbb_urx = float("-inf")
        rootbb_ury = float("-inf")

        # Per-item resolved positions (LL after shift).
        for i, ((llx, lly, urx, ury), (dx, dy)) in enumerate(
            zip(bbs, places)
        ):
            new_llx = llx + dx
            new_lly = lly + dy
            new_urx = urx + dx
            new_ury = ury + dy
            rootbb_llx = min(rootbb_llx, new_llx)
            rootbb_lly = min(rootbb_lly, new_lly)
            rootbb_urx = max(rootbb_urx, new_urx)
            rootbb_ury = max(rootbb_ury, new_ury)

            if kinds[i] == "cluster":
                # Replace the subcluster's own bb with the new
                # parent-relative one.  C does the same:
                # ``GD_bb(subg) = bb`` (osageinit.c:150).
                sub = next(
                    s for s in box.sub_clusters if s.name == names[i]
                )
                sub.bb = (new_llx, new_lly, new_urx, new_ury)
            else:
                # Node: store its center, parent-relative.
                ln = self.lnodes[names[i]]
                ln.x = (new_llx + new_urx) / 2.0
                ln.y = (new_lly + new_ury) / 2.0

        # 4. Add label space at top.  Mirrors C
        # osageinit.c:168-181.  Label height widens the bbox so
        # narrow clusters fit their label, and adds height that
        # gets accounted for in step 5's TOP_IX margin.
        if box.label:
            label_w, label_h = self._estimate_label_dims(box)
            box.label_height = label_h
            current_w = rootbb_urx - rootbb_llx
            if label_w > current_w and total > 0:
                d = (label_w - current_w) / 2.0
                rootbb_llx -= d
                rootbb_urx += d
            elif total == 0:
                # Empty-but-labelled cluster: bbox is just the
                # label dims (osageinit.c:172-174).
                rootbb_llx = 0.0
                rootbb_lly = 0.0
                rootbb_urx = label_w
                rootbb_ury = label_h

        # 5. Add per-side margins.  Root (depth 0) has no extra
        # margin; nested clusters get ``pinfo.margin / 2``
        # (osageinit.c:183-187).
        #
        # Label-space orientation note: GraphvizPy's downstream
        # consumers (SVG renderer, ``-Tdot`` writeback) read
        # ``bb[1]`` as the visual *top* of the cluster (SVG-y
        # convention, y increases downward).  So when
        # ``labelloc="t"`` (the default), the label sits near
        # ``bb[1]`` and we need to extend ``rootbb_lly``
        # (subtract from it) to leave room.  C does the
        # opposite (``rootbb.UR.y += margin + GD_border[TOP_IX].y``)
        # because Graphviz internally uses math-y (y up) and
        # flips at SVG output time — we don't have that flip,
        # so we reserve top space on the low-y side here.
        margin = (pinfo.margin / 2.0) if depth > 0 else 0.0
        rootbb_llx -= margin
        rootbb_urx += margin
        rootbb_lly -= margin + box.label_height
        rootbb_ury += margin

        # 6. Translate so rootbb.LL = (0, 0).  This makes step 3
        # (reposition) just a translation by parent.bb.LL.
        # Mirrors C osageinit.c:194-220.
        shift_x = -rootbb_llx
        shift_y = -rootbb_lly
        for sub in box.sub_clusters:
            llx, lly, urx, ury = sub.bb
            sub.bb = (
                llx + shift_x, lly + shift_y,
                urx + shift_x, ury + shift_y,
            )
        for node_name in box.children:
            ln = self.lnodes[node_name]
            ln.x += shift_x
            ln.y += shift_y

        box.bb = (
            0.0, 0.0,
            rootbb_urx - rootbb_llx,
            rootbb_ury - rootbb_lly,
        )

    def _pack_info_for(
        self, box: ClusterBox, depth: int,
    ) -> PackInfo:
        """Read ``pack`` and ``packmode`` for this scope.

        At depth 0, read from the root graph.  At deeper levels,
        we'd read from the cluster's own attributes — but since
        GraphvizPy currently doesn't propagate ``packmode``
        per-cluster (matches C: only the top-level graph's
        attribute is consulted), we always read root.
        """
        graph = self.graph
        return get_pack_info(
            pack_attr=graph.get_graph_attr("pack"),
            packmode_attr=graph.get_graph_attr("packmode"),
            default_mode=PackMode.L_ARRAY,
            default_margin=DFLT_MARGIN,
        )

    def _estimate_label_dims(
        self, box: ClusterBox,
    ) -> tuple[float, float]:
        """Estimate label width and height in pt.

        We don't have the C label-rendering machinery; fall back
        to a width-by-character heuristic plus 1.5× line height.
        Good enough that cluster labels fit and don't overlap
        their interior.
        """
        try:
            fs = float(box.attrs.get("fontsize", "14"))
        except (TypeError, ValueError):
            fs = 14.0
        # ~0.55 em per char — close to the average for
        # proportional sans-serif fonts.
        width = max(len(box.label) * fs * 0.55, fs * 2.0)
        height = fs * 1.5
        return width, height

    # ── 3. Top-down reposition ───────────────────────────────

    def _reposition_pass(
        self, box: ClusterBox, depth: int,
    ) -> None:
        """Mirrors C ``reposition(g, depth)`` (osageinit.c:236).

        Invariant: when ``_reposition_pass`` is entered, ``box.bb``
        is *already absolute* — the parent translated it before
        recursing.  Root's bb is absolute trivially since
        ``root.bb.LL == (0, 0)`` after :meth:`_layout_pass`.

        At each depth > 0:

        1. Translate ``box``'s direct nodes by ``box.bb.LL`` —
           they sit in ``box``'s internal ``(0, 0)``-anchored
           frame from :meth:`_layout_pass` and need to be lifted
           into ``box``'s absolute position.
        2. For each subcluster, translate its bb by *box*'s bb.LL
           (NOT by the subcluster's own bb.LL — that would
           double-translate).  This makes the subcluster bb
           absolute too, so when we recurse into it, step 1
           applies the correct shift.

        The earlier accumulating-offset version was buggy: it
        passed ``offset + sub.bb.LL`` to the recursion, which
        when combined with the in-recursion ``box.bb += offset``
        translation, ended up adding ``sub.bb.LL`` twice.
        """
        assert box.bb is not None
        bb_llx, bb_lly = box.bb[0], box.bb[1]

        if depth > 0:
            # Translate direct nodes by THIS box's bb.LL.
            for node_name in box.children:
                ln = self.lnodes[node_name]
                ln.x += bb_llx
                ln.y += bb_lly

        # Record cluster in the JSON output stream BEFORE
        # recursing into children.  Pre-order recording means
        # parents appear earlier in the cluster list than their
        # children, which the SVG renderer reads in document
        # order — so the parent's ``<rect>`` is drawn first and
        # the children's are drawn on top.  This is what makes
        # nested cluster fills look correct visually: outer ring
        # of parent's color stays visible around the child rect.
        # (Earlier post-order recording put parent rects on top
        # of their children, hiding the children's fillcolor.)
        if depth > 0 and box.is_cluster:
            self._record_cluster(box)

        # Translate each subcluster's bb by THIS box's bb.LL
        # (mirrors C osageinit.c:264-273).  Skipped at depth 0
        # because root.LL is always (0, 0) — the operation
        # would be a no-op.
        for sub in box.sub_clusters:
            assert sub.bb is not None
            if depth > 0:
                sllx, slly, surx, sury = sub.bb
                sub.bb = (
                    sllx + bb_llx, slly + bb_lly,
                    surx + bb_llx, sury + bb_lly,
                )
            self._reposition_pass(sub, depth + 1)

    def _record_cluster(self, box: ClusterBox) -> None:
        assert box.bb is not None
        x1, y1, x2, y2 = box.bb
        all_nodes = self._all_nodes_in(box)
        record: dict = {
            "name": box.name,
            "label": box.label,
            "bb": [round(x1, 2), round(y1, 2),
                   round(x2, 2), round(y2, 2)],
            "nodes": list(all_nodes),
        }
        record.update(box.attrs)
        self._cluster_records.append(record)

    @staticmethod
    def _all_nodes_in(box: ClusterBox) -> list[str]:
        """Recursive list of node names contained directly or
        transitively in ``box``.
        """
        out: list[str] = list(box.children)
        for sub in box.sub_clusters:
            out.extend(OsageLayout._all_nodes_in(sub))
        return out

    # ── Output ───────────────────────────────────────────────

    def _build_result(self) -> dict:
        """Build the JSON result dict, layering cluster info on
        top of the standard ``LayoutEngine._to_json`` output.
        """
        result = self._to_json()
        if self._cluster_records:
            result["clusters"] = self._cluster_records
            # Expand graph bb to enclose every cluster.  Mirrors
            # the same trick fdp/sfdp use so the SVG viewBox
            # doesn't clip cluster outlines.
            if "graph" in result and "bb" in result["graph"]:
                gx1, gy1, gx2, gy2 = result["graph"]["bb"]
                for cl in self._cluster_records:
                    cx1, cy1, cx2, cy2 = cl["bb"]
                    gx1 = min(gx1, cx1)
                    gy1 = min(gy1, cy1)
                    gx2 = max(gx2, cx2)
                    gy2 = max(gy2, cy2)
                result["graph"]["bb"] = [
                    round(gx1, 2), round(gy1, 2),
                    round(gx2, 2), round(gy2, 2),
                ]
        return result
