"""
Patchwork layout engine — squarified treemap.

Port of Graphviz ``lib/patchwork/``.  Lays out graphs as nested
rectangles where each node's area is proportional to its ``area``
attribute (default 1.0).

Algorithm (Bruls, Huizing, van Wijk — "Squarified Treemaps"):
  1. Build tree from cluster hierarchy
  2. Compute areas: node area from attribute, cluster area = sum of children
  3. Sort children by area (descending) for better aspect ratios
  4. Squarify: greedily add items to current row/column, commit when
     aspect ratio worsens, recurse on remaining space
  5. Recursively layout nested clusters within their allocated rectangle

Command-line::

    python gvcli.py -Kpatchwork input.gv -Tsvg -o output.svg

Attributes::

    area   — node area weight (default 1.0)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.base import LayoutEngine


_SCALE = 1000.0  # scale areas for numerical precision
_DFLT_INSET = 8.0  # cluster border inset in points


@dataclass
class TreeNode:
    """Internal tree node for treemap layout."""
    name: str
    area: float = 1.0
    is_leaf: bool = True
    children: list["TreeNode"] = field(default_factory=list)
    # Assigned rectangle (after layout)
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    # For cluster nodes
    label: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    graph_node: Optional[Node] = None


@dataclass
class LayoutNode:
    """Node with layout metadata for LayoutEngine compatibility."""
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False


class PatchworkLayout(LayoutEngine):
    """Squarified treemap layout engine."""

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self._clusters: list[dict] = []

    def layout(self) -> dict:
        self._init_common_attrs()

        # Build tree from graph hierarchy
        root = self._build_tree()

        # Compute areas bottom-up
        self._compute_areas(root)

        # Layout: assign rectangles top-down
        total_area = root.area
        side = math.sqrt(total_area)
        root.x, root.y, root.w, root.h = 0, 0, side, side
        self._squarify_tree(root)

        # Extract node positions from tree
        self._extract_positions(root)

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

    # ── Tree construction ────────────────────────

    def _build_tree(self) -> TreeNode:
        """Build tree from graph's cluster hierarchy."""
        assigned: set[str] = set()

        def _build_sub(subgraph) -> TreeNode:
            label = subgraph.get_graph_attr("label") or \
                    subgraph.attr_record.get("label", "")
            node = TreeNode(name=subgraph.name, is_leaf=False,
                            label=label)
            for attr in ("color", "fillcolor", "style", "penwidth",
                         "fontname", "fontsize", "fontcolor", "bgcolor"):
                val = subgraph.get_graph_attr(attr) or \
                      subgraph.attr_record.get(attr)
                if val:
                    node.attrs[attr] = val

            # Recurse into subclusters
            for sub_name, sub in subgraph.subgraphs.items():
                child = _build_sub(sub)
                node.children.append(child)
                self._mark_assigned(child, assigned)

            # Direct leaf nodes
            for nname in subgraph.nodes:
                if nname not in assigned:
                    assigned.add(nname)
                    gnode = self.graph.nodes.get(nname)
                    try:
                        area = float(gnode.attributes.get("area", "1")) \
                               if gnode else 1.0
                    except ValueError:
                        area = 1.0
                    area = max(area, 0.01) * _SCALE
                    leaf = TreeNode(name=nname, area=area, is_leaf=True,
                                   graph_node=gnode)
                    node.children.append(leaf)

            return node

        root = TreeNode(name=self.graph.name, is_leaf=False)

        for sub_name, sub in self.graph.subgraphs.items():
            child = _build_sub(sub)
            root.children.append(child)

        # Unassigned nodes go to root
        for nname, gnode in self.graph.nodes.items():
            if nname not in assigned:
                try:
                    area = float(gnode.attributes.get("area", "1")) * _SCALE
                except ValueError:
                    area = _SCALE
                area = max(area, 0.01)
                leaf = TreeNode(name=nname, area=area, is_leaf=True,
                                graph_node=gnode)
                root.children.append(leaf)

        return root

    @staticmethod
    def _mark_assigned(node: TreeNode, assigned: set[str]):
        if node.is_leaf:
            assigned.add(node.name)
        for c in node.children:
            PatchworkLayout._mark_assigned(c, assigned)

    # ── Area computation ─────────────────────────

    def _compute_areas(self, node: TreeNode):
        """Bottom-up: compute cluster areas as sum of children."""
        if node.is_leaf:
            return
        for child in node.children:
            self._compute_areas(child)
        child_area = sum(c.area for c in node.children)
        # Add inset margin around cluster
        inset = _DFLT_INSET
        side = math.sqrt(max(child_area, 1))
        node.area = (2 * inset + side) ** 2

    # ── Squarified treemap ───────────────────────

    def _squarify_tree(self, node: TreeNode):
        """Recursively squarify: assign rectangles to all children."""
        if node.is_leaf or not node.children:
            return

        # Sort children by area descending (better squarification)
        children = sorted(node.children, key=lambda c: -c.area)

        # Inner rectangle (accounting for inset)
        inset = _DFLT_INSET
        label_h = 0.0
        if node.label:
            try:
                fs = float(node.attrs.get("fontsize", "14"))
            except ValueError:
                fs = 14.0
            label_h = fs * 1.2

        ix = node.x + inset
        iy = node.y + inset + label_h
        iw = max(node.w - 2 * inset, 1)
        ih = max(node.h - 2 * inset - label_h, 1)

        # Squarify the children into (ix, iy, iw, ih)
        self._squarify(children, ix, iy, iw, ih)

        # Recurse into cluster children
        for child in children:
            if not child.is_leaf:
                self._squarify_tree(child)

    def _squarify(self, items: list[TreeNode],
                  x: float, y: float, w: float, h: float):
        """Squarified treemap: assign rectangles to items within (x,y,w,h).

        Port of squarify() from tree_map.c.
        """
        if not items:
            return

        total_area = sum(c.area for c in items)
        if total_area <= 0:
            return

        # Scale areas to fit the available rectangle
        scale = (w * h) / total_area
        areas = [c.area * scale for c in items]

        self._layout_row(items, areas, x, y, w, h)

    def _layout_row(self, items: list[TreeNode], areas: list[float],
                    x: float, y: float, w: float, h: float):
        """Lay out items using the squarified treemap algorithm."""
        if not items:
            return

        N = len(items)
        if N == 1:
            items[0].x, items[0].y = x, y
            items[0].w, items[0].h = w, h
            return

        # Determine layout direction (along shorter side)
        vertical = (w >= h)

        row: list[int] = []
        row_area = 0.0
        side = min(w, h)
        remaining = list(range(N))
        best_aspect = float("inf")

        cx, cy = x, y
        rem_w, rem_h = w, h

        i = 0
        while i < N:
            # Try adding item i to current row
            test_area = row_area + areas[i]
            test_count = len(row) + 1

            if side <= 0:
                # Degenerate: just stack remaining
                for j in range(i, N):
                    items[j].x, items[j].y = cx, cy
                    items[j].w, items[j].h = max(rem_w, 1), max(rem_h, 1)
                break

            row_length = test_area / side
            if row_length <= 0:
                row.append(i)
                row_area = test_area
                i += 1
                continue

            # Compute worst aspect ratio in the row
            min_item = min(areas[j] for j in row + [i]) if row else areas[i]
            max_item = max(areas[j] for j in row + [i]) if row else areas[i]
            item_w = min_item / row_length if row_length > 0 else 1
            item_w2 = max_item / row_length if row_length > 0 else 1
            aspect = max(row_length / item_w if item_w > 0 else 999,
                         item_w2 / row_length if row_length > 0 else 999)

            if aspect <= best_aspect or not row:
                # Aspect improves (or first item): add to row
                row.append(i)
                row_area = test_area
                best_aspect = aspect
                i += 1
            else:
                # Aspect worsens: commit current row, start new one
                cx, cy, rem_w, rem_h = self._commit_row(
                    items, areas, row, row_area, cx, cy, rem_w, rem_h, vertical)
                row = []
                row_area = 0.0
                best_aspect = float("inf")
                vertical = (rem_w >= rem_h)
                side = min(rem_w, rem_h)
                # Don't increment i — retry this item in new row

        # Commit final row
        if row:
            self._commit_row(items, areas, row, row_area,
                             cx, cy, rem_w, rem_h, vertical)

    def _commit_row(self, items, areas, row, row_area,
                    x, y, w, h, vertical) -> tuple:
        """Commit a row of items and return the remaining rectangle."""
        if not row or row_area <= 0:
            return x, y, w, h

        side = min(w, h)
        row_thickness = row_area / side if side > 0 else h

        if vertical:
            # Lay out vertically (items stacked top-to-bottom)
            cy = y
            for idx in row:
                item_h = areas[idx] / row_thickness if row_thickness > 0 else h / len(row)
                items[idx].x = x
                items[idx].y = cy
                items[idx].w = row_thickness
                items[idx].h = item_h
                cy += item_h
            return x + row_thickness, y, w - row_thickness, h
        else:
            # Lay out horizontally (items side-by-side)
            cx = x
            for idx in row:
                item_w = areas[idx] / row_thickness if row_thickness > 0 else w / len(row)
                items[idx].x = cx
                items[idx].y = y
                items[idx].w = item_w
                items[idx].h = row_thickness
                cx += item_w
            return x, y + row_thickness, w, h - row_thickness

    # ── Position extraction ──────────────────────

    def _extract_positions(self, node: TreeNode):
        """Walk tree and create LayoutNode entries for all leaf nodes."""
        if node.is_leaf:
            gnode = node.graph_node or self.graph.nodes.get(node.name)
            ln = LayoutNode(
                name=node.name,
                node=gnode,
                x=node.x + node.w / 2,
                y=node.y + node.h / 2,
                width=max(node.w, 1),
                height=max(node.h, 1),
            )
            self.lnodes[node.name] = ln
        else:
            # Record cluster
            if node.name != self.graph.name:
                cluster_nodes = []
                self._collect_leaf_names(node, cluster_nodes)
                self._clusters.append({
                    "name": node.name,
                    "label": node.label,
                    "bb": [round(node.x, 2), round(node.y, 2),
                           round(node.x + node.w, 2),
                           round(node.y + node.h, 2)],
                    "nodes": cluster_nodes,
                    **node.attrs,
                })
            for child in node.children:
                self._extract_positions(child)

    @staticmethod
    def _collect_leaf_names(node: TreeNode, out: list[str]):
        if node.is_leaf:
            out.append(node.name)
        for c in node.children:
            PatchworkLayout._collect_leaf_names(c, out)

    # ── Output ───────────────────────────────────

    def _build_result(self) -> dict:
        result = self._to_json()
        if self._clusters:
            result["clusters"] = self._clusters
        return result

    # Shared from LayoutEngine: _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _compute_label_positions, _write_back, _to_json
