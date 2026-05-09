"""C-aligned port of ``lib/patchwork/patchwork.c`` —
squarified-treemap layout.

Patchwork lays out a graph as a treemap: every leaf node becomes
a rectangle whose area is proportional to its ``area`` attribute
(default 1.0), and every cluster subgraph becomes a rectangle
that contains its children (recursively).  The squarification
keeps each rectangle's aspect ratio close to 1:1 for readability.

Algorithm (mirrors C ``patchworkLayout`` verbatim,
``patchwork.c:268``):

1. ``mkTree`` — recursively build a tree from the graph's
   cluster hierarchy.  Each leaf node's area comes from its
   ``area`` attribute (× SCALE=1000 for numerical headroom).
   Each cluster's area is ``(2·inset + sqrt(child_area))²``
   so its rectangle has room for an inset border around the
   child rectangles plus the children themselves.
2. Set the root rectangle to a square of side
   ``sqrt(total_area + 0.1)`` centered at origin.
3. ``layoutTree`` — recursively squarify each cluster's
   children:
   - Sort by area descending.
   - Compute the *inner* rectangle that holds the children:
     solve ``(w - m)·(h - m) = child_area`` for ``m``, where
     ``(w, h)`` is the cluster's outer size.  This gives a
     uniform inset on all sides regardless of aspect ratio.
   - Call :func:`tree_map` on the inner rectangle with the
     sorted areas.
   - Recurse into each cluster child.
4. ``walkTree`` — extract per-node positions and per-cluster
   bounding boxes.  Each leaf node ends up at the center of
   its assigned rectangle with width/height matching the
   rectangle's size; each cluster's bbox is the rectangle's
   LL/UR.

Coordinate system: the C algorithm uses math-y (y up) for the
recursion so the squarify "top of fillrec" semantics work
correctly.  The Python port keeps that internal convention but
flips at the very end (in :meth:`_walk_tree`) so downstream
GraphvizPy consumers (SVG renderer, ``-Tdot`` writeback) see
SVG-y coords matching the rest of the library.

Command-line::

    python gvcli.py -Kpatchwork input.gv -Tsvg -o output.svg

Attributes::

    area    — node / cluster area weight (default 1.0)
    inset   — cluster border inset (default 0)
    fontsize — used to estimate cluster label height
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine
from gvpy.engines.layout.patchwork.tree_map import (
    Rectangle,
    tree_map,
)


# Mirror C ``patchwork.c:36-37`` constants.
_DFLT_SZ: float = 1.0      # default area for nodes/clusters with none specified
_SCALE: float = 1000.0     # area multiplier for numerical headroom


@dataclass
class _TreeNode:
    """Mirrors C ``treenode_t`` (patchwork.c:23).

    The shape mirrors C's mix of leaf + cluster representation —
    ``kind`` distinguishes them.  ``area`` is the rectangle's
    weight (sum of children for clusters, attribute-derived for
    leaves).  ``r`` becomes the assigned :class:`Rectangle`
    after layout.
    """
    name: str
    kind: str                              # "node" or "cluster"
    area: float = 0.0
    child_area: float = 0.0
    rect: Rectangle = field(
        default_factory=lambda: Rectangle(0.0, 0.0, 0.0, 0.0)
    )
    children: list["_TreeNode"] = field(default_factory=list)
    # Back-references for output.
    node: Optional[Node] = None
    label: str = ""
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class LayoutNode:
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False


class PatchworkLayout(LayoutEngine):
    """Squarified-treemap layout engine.

    Use::

        from gvpy.engines.layout.patchwork import PatchworkLayout
        result = PatchworkLayout(graph).layout()
    """

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self._cluster_records: list[dict] = []

    # ── Public entry ─────────────────────────────────────────

    def layout(self) -> dict:
        self._init_common_attrs()

        # Mirror C ``patchwork_init_node`` (patchworkinit.c:74-77):
        # force every node's shape to ``box`` *unconditionally*.
        # The squarified-treemap layout assigns each leaf a
        # specific rectangular size; rendering a node as anything
        # but a box defeats the visualization.  C overwrites
        # whatever the author wrote, and so do we.
        for node in self.graph.nodes.values():
            node.attributes["shape"] = "box"

        # 1. Build the tree.
        root = self._make_tree(self.graph)

        # 2. Seed root rectangle.  C uses ``sqrt(total_area + 0.1)``
        # for the side length, centered at origin (patchwork.c:278).
        side = math.sqrt(root.area + 0.1)
        root.rect = Rectangle(
            cx=0.0, cy=0.0,
            sw=side, sh=side,
        )

        # 3. Recursively squarify.
        self._layout_tree(root)

        # 4. Walk the tree, extracting positions and bboxes.
        self._walk_tree(root)

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

    # ── 1. Tree construction (mirrors C mkTree, patchwork.c:91) ──

    def _make_tree(self, graph_or_sub) -> _TreeNode:
        """Build the recursive tree.  Mirrors C ``mkTree``.

        - For each subgraph that is a cluster (name starts with
          ``cluster``), recurse into it as a cluster node.
        - For each direct-member node not already assigned to a
          deeper cluster, create a leaf node.
        - Cluster area = ``(2·inset + sqrt(child_area))²`` per C
          ``fullArea`` (patchwork.c:57).
        """
        is_root = (graph_or_sub is self.graph)
        name = graph_or_sub.name
        node = _TreeNode(name=name, kind="cluster")

        if not is_root:
            # Read cluster visual attrs for SVG output.
            self._populate_cluster_attrs(graph_or_sub, node)

        assigned = self._assigned_set()
        total_child_area = 0.0

        # Subclusters first (matches C mkTree order: cluster
        # children precede direct nodes).
        for sg_name, sg in graph_or_sub.subgraphs.items():
            if self._is_cluster(sg_name):
                child = self._make_tree(sg)
                node.children.append(child)
                total_child_area += child.area
                # Mark all leaf-descendant names as assigned so a
                # later sibling subgraph or the root doesn't double
                # them up.
                self._mark_subtree_assigned(child)
            else:
                # Non-cluster subgraph: flatten its descendants up
                # into this scope.  C does this via SPARENT
                # bookkeeping; we walk it explicitly.
                self._flatten_into(sg, node, total_child_area_ref={
                    "v": 0.0,
                })
                # ``_flatten_into`` mutated total_child_area
                # via the ref-dict to avoid Python's lack of
                # nonlocal-write through nested helper calls.

        # Direct-member nodes that haven't been assigned yet.
        for nname in graph_or_sub.nodes:
            gnode = self.graph.nodes.get(nname)
            if gnode is None:
                continue
            if nname in assigned:
                continue
            assigned.add(nname)
            leaf = self._make_leaf(gnode, nname)
            node.children.append(leaf)
            total_child_area += leaf.area

        # Aggregate child areas + inset → cluster area.
        if node.children:
            node.child_area = total_child_area
            node.area = self._full_area(node)
        else:
            # Empty cluster (or empty root): use ``getArea``
            # default (DFLT_SZ * SCALE).
            node.area = self._get_default_area(graph_or_sub)

        return node

    def _flatten_into(
        self, subgraph, parent: _TreeNode,
        total_child_area_ref: dict,
    ) -> None:
        """Walk a non-cluster subgraph, lifting its leaf nodes /
        nested clusters into ``parent``.  Mirrors C's
        ``SPARENT`` continue-skipping loop in mkTree.
        """
        assigned = self._assigned_set()
        for sg_name, sg in subgraph.subgraphs.items():
            if self._is_cluster(sg_name):
                child = self._make_tree(sg)
                parent.children.append(child)
                total_child_area_ref["v"] = (
                    total_child_area_ref.get("v", 0.0) + child.area
                )
                self._mark_subtree_assigned(child)
            else:
                self._flatten_into(sg, parent, total_child_area_ref)
        for nname in subgraph.nodes:
            gnode = self.graph.nodes.get(nname)
            if gnode is None or nname in assigned:
                continue
            assigned.add(nname)
            leaf = self._make_leaf(gnode, nname)
            parent.children.append(leaf)
            total_child_area_ref["v"] = (
                total_child_area_ref.get("v", 0.0) + leaf.area
            )

    def _make_leaf(
        self, gnode: Node, name: str,
    ) -> _TreeNode:
        """Build a leaf tree node.  Mirrors C ``mkTreeNode``
        (patchwork.c:74)."""
        leaf = _TreeNode(
            name=name,
            kind="node",
            area=self._get_node_area(gnode),
            node=gnode,
        )
        return leaf

    def _populate_cluster_attrs(
        self, subgraph, cl: _TreeNode,
    ) -> None:
        cl.label = (
            subgraph.get_graph_attr("label")
            or subgraph.attr_record.get("label", "")
            or ""
        )
        for attr in (
            "color", "fillcolor", "style", "penwidth",
            "fontname", "fontsize", "fontcolor", "bgcolor",
            "labelloc", "labeljust",
        ):
            val = (
                subgraph.get_graph_attr(attr)
                or subgraph.attr_record.get(attr)
            )
            if val:
                cl.attrs[attr] = val

    @staticmethod
    def _is_cluster(name: str) -> bool:
        return name.startswith("cluster")

    def _assigned_set(self) -> set:
        """Per-instance memoised set of names already assigned to
        a cluster.  Lazily-initialized on first access.
        """
        if not hasattr(self, "_assigned"):
            self._assigned: set[str] = set()
        return self._assigned

    def _mark_subtree_assigned(self, tree: _TreeNode) -> None:
        if tree.kind == "node":
            self._assigned_set().add(tree.name)
        for c in tree.children:
            self._mark_subtree_assigned(c)

    def _get_node_area(self, gnode: Node) -> float:
        """Mirrors C ``getArea`` (patchwork.c:64).

        Reads the ``area`` attribute, defaults to ``DFLT_SZ=1``
        if missing or non-numeric, then multiplies by ``SCALE``.
        """
        try:
            v = float(gnode.attributes.get("area", _DFLT_SZ))
        except (TypeError, ValueError):
            v = _DFLT_SZ
        if v == 0.0:
            v = _DFLT_SZ
        return v * _SCALE

    def _get_default_area(self, graph_or_sub) -> float:
        """For empty clusters: read graph-level ``area`` or default
        to DFLT_SZ × SCALE.
        """
        v_str = graph_or_sub.get_graph_attr("area") if hasattr(
            graph_or_sub, "get_graph_attr"
        ) else None
        try:
            v = float(v_str) if v_str else _DFLT_SZ
        except (TypeError, ValueError):
            v = _DFLT_SZ
        if v == 0.0:
            v = _DFLT_SZ
        return v * _SCALE

    def _full_area(self, cluster: _TreeNode) -> float:
        """Mirrors C ``fullArea`` (patchwork.c:57).

        Cluster's outer area = ``(2·m + sqrt(child_area))²``
        where ``m`` is the inset border read from the cluster's
        ``inset`` attribute (default 0).
        """
        try:
            m = float(cluster.attrs.get("inset", "0"))
        except (TypeError, ValueError):
            m = 0.0
        wid = 2.0 * m + math.sqrt(cluster.child_area)
        return wid * wid

    # ── 3. Squarify tree (mirrors C layoutTree, patchwork.c:149) ──

    def _layout_tree(self, tree: _TreeNode) -> None:
        """Recursively squarify each cluster's children.

        At each cluster level:

        1. Sort children by area descending (matches C's
           ``LIST_SORT(&nodes, nodecmp)``).
        2. Compute the inner rectangle: solve
           ``(w - m)·(h - m) = child_area`` for ``m`` to get a
           uniform inset.  This gives the largest centered
           rectangle whose area equals the children's total
           weighted area.
        3. Call :func:`tree_map` to fill the inner rectangle.
        4. Recurse into each cluster child.
        """
        if not tree.children:
            return

        nc = len(tree.children)

        # Sort by area descending.  C uses ``nodecmp`` (-1 if x.area
        # > y.area, +1 if x.area < y.area, 0 ties).
        sorted_kids = sorted(
            tree.children, key=lambda c: -c.area,
        )
        areas_sorted = [c.area for c in sorted_kids]

        # Compute inset margin ``m`` so the inner rectangle's area
        # equals child_area.  Solving (w-m)(h-m) = child_area for
        # m gives a quadratic; C's closed-form (patchwork.c:169-171)
        # is:
        #     delta = h - w
        #     disc  = sqrt(delta² + 4·child_area)
        #     m     = (h + w - disc) / 2
        h = tree.rect.sh
        w = tree.rect.sw
        if tree.child_area > 0 and w > 0 and h > 0:
            delta = h - w
            disc = math.sqrt(delta * delta + 4.0 * tree.child_area)
            m = (h + w - disc) / 2.0
            m = max(m, 0.0)
        else:
            m = 0.0

        crec = Rectangle(
            cx=tree.rect.cx,
            cy=tree.rect.cy,
            sw=max(w - m, 0.0),
            sh=max(h - m, 0.0),
        )

        recs = tree_map(areas_sorted, crec)
        if recs is None:
            # Overflow — shouldn't happen if fullArea was computed
            # correctly, but degrade gracefully.
            return

        # Assign rectangles back to the original (unsorted) children
        # via the sorted reference list.
        for i, child in enumerate(sorted_kids):
            child.rect = recs[i]

        # Recurse into cluster children.
        for child in tree.children:
            if child.kind == "cluster":
                self._layout_tree(child)

    # ── 4. Walk + extract output (mirrors C walkTree) ─────────

    def _walk_tree(self, tree: _TreeNode) -> None:
        """Pre-order walk: record cluster bbox / leaf coord.

        The walk converts from C's center+size representation to
        GraphvizPy's lnodes (center) + cluster bbox (LL_x, LL_y,
        UR_x, UR_y) representation.

        Y-flip note: the squarify recursion uses math-y (y up).
        Downstream consumers expect SVG-y (y down).  We flip
        each y-coordinate here by negating it, which is the
        smallest possible coord-system seam.
        """
        for child in tree.children:
            self._walk_tree(child)

        if tree.kind == "cluster":
            # Cluster bbox.  Skip the synthetic root frame.
            if tree.name == self.graph.name:
                return
            cx, cy = tree.rect.cx, -tree.rect.cy  # flip y
            sw, sh = tree.rect.sw, tree.rect.sh
            x1 = cx - sw / 2.0
            x2 = cx + sw / 2.0
            y1 = cy - sh / 2.0
            y2 = cy + sh / 2.0
            self._cluster_records.append({
                "name": tree.name,
                "label": tree.label,
                "bb": [round(x1, 2), round(y1, 2),
                       round(x2, 2), round(y2, 2)],
                "nodes": self._all_leaf_names(tree),
                **tree.attrs,
            })
        else:
            # Leaf node — emit lnode entry.
            cx, cy = tree.rect.cx, -tree.rect.cy  # flip y
            sw, sh = tree.rect.sw, tree.rect.sh
            ln = LayoutNode(
                name=tree.name,
                node=tree.node,
                x=cx, y=cy,
                width=max(sw, 1.0),
                height=max(sh, 1.0),
            )
            self.lnodes[tree.name] = ln

    @staticmethod
    def _all_leaf_names(tree: _TreeNode) -> list[str]:
        out: list[str] = []
        if tree.kind == "node":
            out.append(tree.name)
        for c in tree.children:
            out.extend(PatchworkLayout._all_leaf_names(c))
        return out

    # ── Output ───────────────────────────────────────────────

    def _build_result(self) -> dict:
        result = self._to_json()
        if self._cluster_records:
            result["clusters"] = self._cluster_records
            # Expand graph bb to enclose clusters (mirrors fdp /
            # sfdp / osage).
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
