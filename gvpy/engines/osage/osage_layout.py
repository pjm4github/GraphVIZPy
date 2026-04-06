"""
Osage layout engine — recursive cluster packing.

Port of Graphviz ``lib/osage/osageinit.c``.  Lays out graphs by
recursively packing nodes and subclusters into rectangular regions.

Algorithm:
  1. Build cluster hierarchy from subgraphs
  2. Bottom-up: for each cluster, pack its children (nodes + subclusters)
     into a rectangular array
  3. Top-down: translate packed positions to global coordinates
  4. Route edges as straight lines

Unlike dot, osage does NOT use hierarchical ranking.  It treats the
graph as a containment hierarchy where each cluster is a rectangle.

Command-line::

    python gvcli.py -Kosage input.gv -Tsvg -o output.svg

Attributes::

    pack / packmode — packing algorithm (default: array)
    pad            — extra space around graph
    sortv          — sort value for array ordering (graph/node)
    margin         — cluster margin
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.base import LayoutEngine


_DFLT_MARGIN = 18.0  # points


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


@dataclass
class ClusterBox:
    """A rectangle representing a cluster or node for packing."""
    name: str
    width: float
    height: float
    x: float = 0.0          # position after packing (lower-left)
    y: float = 0.0
    is_cluster: bool = False
    children: list[str] = field(default_factory=list)  # node names in this cluster
    sub_clusters: list["ClusterBox"] = field(default_factory=list)
    sortv: int = 0
    label: str = ""
    # Cluster visual attributes
    attrs: dict[str, str] = field(default_factory=dict)


class OsageLayout(LayoutEngine):
    """Recursive cluster packing layout engine.

    Usage::

        from gvpy.engines.osage import OsageLayout
        result = OsageLayout(graph).layout()
    """

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.margin = _DFLT_MARGIN
        self._clusters: list[dict] = []  # for JSON output

    def layout(self) -> dict:
        self._init_from_graph()

        # Build cluster hierarchy
        root_box = self._build_hierarchy()

        # Bottom-up: pack each cluster
        self._pack_cluster(root_box)

        # Top-down: assign global positions
        self._position_cluster(root_box, 0.0, 0.0)

        # Post-processing
        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        self._compute_label_positions()
        self._write_back()
        return self._build_result()

    # ── Initialization ───────────────────────────

    def _init_from_graph(self):
        self._init_common_attrs()

        margin_str = self.graph.get_graph_attr("margin") or \
                     self.graph.get_graph_attr("pad")
        if margin_str:
            try:
                self.margin = float(margin_str) * 72.0
            except ValueError:
                pass

        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)
            try:
                ln.sortv = int(node.attributes.get("sortv", "0"))
            except ValueError:
                pass
            self.lnodes[name] = ln

    # ── Cluster hierarchy ────────────────────────

    def _build_hierarchy(self) -> ClusterBox:
        """Build a tree of ClusterBox objects from the graph's subgraphs."""
        # Track which nodes belong to which subgraph
        assigned: set[str] = set()

        def _build_sub(subgraph, depth=0) -> ClusterBox:
            # Read label from get_graph_attr (checks attr_dict_g)
            # then fall back to attr_record
            sub_label = subgraph.get_graph_attr("label") or \
                        subgraph.attr_record.get("label", "")
            box = ClusterBox(
                name=subgraph.name,
                width=0, height=0,
                is_cluster=True,
                label=sub_label or "",
            )
            # Collect cluster visual attrs
            for attr in ("color", "fillcolor", "style", "penwidth",
                         "fontname", "fontsize", "fontcolor",
                         "bgcolor", "label", "labelloc", "labeljust"):
                val = subgraph.get_graph_attr(attr) or \
                      subgraph.attr_record.get(attr)
                if val:
                    box.attrs[attr] = val

            try:
                sv = subgraph.get_graph_attr("sortv") or \
                     subgraph.attr_record.get("sortv", "0")
                box.sortv = int(sv)
            except (ValueError, TypeError):
                pass

            # Recurse into subclusters
            for sub_name, sub in subgraph.subgraphs.items():
                child_box = _build_sub(sub, depth + 1)
                box.sub_clusters.append(child_box)
                # Mark nodes in subclusters as assigned
                for n in child_box.children:
                    assigned.add(n)
                # Also mark nodes assigned by deeper recursion
                def _mark_all(cb):
                    for n in cb.children:
                        assigned.add(n)
                    for sc in cb.sub_clusters:
                        _mark_all(sc)
                _mark_all(child_box)

            # Nodes directly in this subgraph (not in deeper subclusters)
            for node_name in subgraph.nodes:
                if node_name not in assigned:
                    box.children.append(node_name)
                    assigned.add(node_name)

            return box

        # Build from root graph
        root = ClusterBox(name=self.graph.name, width=0, height=0,
                          is_cluster=True)

        for sub_name, sub in self.graph.subgraphs.items():
            child_box = _build_sub(sub)
            root.sub_clusters.append(child_box)

        # Add unassigned nodes to root
        for name in self.lnodes:
            if name not in assigned:
                root.children.append(name)

        return root

    # ── Packing algorithm ────────────────────────

    def _pack_cluster(self, box: ClusterBox):
        """Bottom-up: recursively pack all children, then pack this cluster."""
        # First, pack all subclusters (post-order)
        for sub in box.sub_clusters:
            self._pack_cluster(sub)

        # Collect items to pack: subclusters + direct nodes
        items: list[tuple[float, float, int, str, bool]] = []

        for sub in box.sub_clusters:
            items.append((sub.width, sub.height, sub.sortv, sub.name, True))

        for node_name in box.children:
            ln = self.lnodes[node_name]
            items.append((ln.width, ln.height, ln.sortv, node_name, False))

        if not items:
            box.width = self.margin * 2
            box.height = self.margin * 2
            return

        # Sort by sortv, then by name for stability
        items.sort(key=lambda t: (t[2], t[3]))

        # Pack into array layout (rows of items)
        positions = self._array_pack(items)

        # Assign positions to children
        for (w, h, sv, name, is_clust), (px, py) in zip(items, positions):
            if is_clust:
                # Find the sub-cluster and set its position
                for sub in box.sub_clusters:
                    if sub.name == name:
                        sub.x = px
                        sub.y = py
                        break
            else:
                ln = self.lnodes[name]
                # Store position relative to cluster origin
                ln.x = px + w / 2  # center
                ln.y = py + h / 2

        # Compute cluster bounding box
        max_x = max(px + w for (w, h, _, _, _), (px, py) in zip(items, positions))
        max_y = max(py + h for (w, h, _, _, _), (px, py) in zip(items, positions))

        # Add margin and label space
        label_height = 0.0
        if box.label:
            try:
                fs = float(box.attrs.get("fontsize", "14"))
            except ValueError:
                fs = 14.0
            label_height = fs * 1.5

        box.width = max_x + self.margin * 2
        box.height = max_y + self.margin * 2 + label_height

    def _array_pack(self, items: list[tuple]) -> list[tuple[float, float]]:
        """Pack items into a roughly square array of rows.

        Returns list of (x, y) positions for each item's lower-left corner.
        """
        N = len(items)
        if N == 0:
            return []

        # Determine number of columns for roughly square layout
        total_area = sum(w * h for w, h, *_ in items)
        avg_w = sum(w for w, *_ in items) / N
        avg_h = sum(items[i][1] for i in range(N)) / N
        cols = max(1, int(math.ceil(math.sqrt(N * avg_w / max(avg_h, 1)))))

        positions: list[tuple[float, float]] = []
        x, y = self.margin, self.margin
        row_height = 0.0
        col_count = 0

        for w, h, *_ in items:
            if col_count >= cols and col_count > 0:
                # New row
                x = self.margin
                y += row_height + self.margin
                row_height = 0.0
                col_count = 0

            positions.append((x, y))
            x += w + self.margin
            row_height = max(row_height, h)
            col_count += 1

        return positions

    # ── Position assignment ──────────────────────

    def _position_cluster(self, box: ClusterBox, offset_x: float, offset_y: float):
        """Top-down: translate all positions to global coordinates."""
        # Add label space at top
        label_offset = 0.0
        if box.label:
            try:
                fs = float(box.attrs.get("fontsize", "14"))
            except ValueError:
                fs = 14.0
            label_offset = fs * 1.5

        # Translate direct nodes
        for node_name in box.children:
            ln = self.lnodes[node_name]
            ln.x += offset_x
            ln.y += offset_y + label_offset

        # Translate and recurse into subclusters
        for sub in box.sub_clusters:
            self._position_cluster(
                sub,
                offset_x + sub.x,
                offset_y + sub.y + label_offset,
            )

        # Record cluster info for JSON output
        if box.is_cluster and box.name != self.graph.name:
            x1 = offset_x
            y1 = offset_y
            x2 = offset_x + box.width
            y2 = offset_y + box.height
            cluster_info = {
                "name": box.name,
                "label": box.label,
                "bb": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "nodes": list(self._all_nodes_in(box)),
            }
            cluster_info.update(box.attrs)
            self._clusters.append(cluster_info)

    @staticmethod
    def _all_nodes_in(box: ClusterBox) -> set[str]:
        """Gather all node names in a cluster and its subclusters."""
        result = set(box.children)
        for sub in box.sub_clusters:
            result.update(OsageLayout._all_nodes_in(sub))
        return result

    # ── Output ───────────────────────────────────

    def _build_result(self) -> dict:
        """Build JSON result with cluster information."""
        result = self._to_json()
        if self._clusters:
            result["clusters"] = self._clusters
        return result

    # Shared methods inherited from LayoutEngine base class:
    # _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _compute_label_positions, _clip_to_boundary,
    # _write_back, _to_json
