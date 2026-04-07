"""
Abstract base class for all GraphvizPy layout engines.

Provides shared utilities used by multiple engines: node sizing,
post-processing (normalize, rotate, center), label placement,
edge boundary clipping, component detection/packing, write-back,
and JSON output generation.

These correspond to Graphviz ``lib/common/`` shared functions
(postproc.c, utils.c, geomprocs.h).
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from collections import deque, defaultdict
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.core.node import Node


class LayoutEngine(ABC):
    """Base class for graph layout engines.

    Subclasses must:
      - Set ``self.lnodes: dict[str, LayoutNodeBase]`` with objects having
        ``.x``, ``.y``, ``.width``, ``.height``, ``.node``, ``.pinned``
      - Implement ``layout()``

    Shared methods provided:
      - Node sizing: ``_compute_node_size()``
      - Post-processing: ``_apply_normalize()``, ``_apply_rotation()``,
        ``_apply_center()``
      - Label placement: ``_compute_label_positions()``,
        ``_estimate_label_size()``, ``_overlap_area()``
      - Edge clipping: ``_clip_to_boundary()``
      - Components: ``_find_components()``, ``_pack_components()``
      - Output: ``_write_back()``, ``_to_json()``
    """

    # Node sizing constants
    _MIN_WIDTH = 54.0    # 0.75in * 72dpi
    _MIN_HEIGHT = 36.0   # 0.50in * 72dpi
    _H_PAD = 36.0
    _V_PAD = 18.0

    # Node attribute passthrough list for JSON output
    _NODE_PASSTHROUGH = (
        "shape", "label", "color", "fillcolor", "fontcolor",
        "fontname", "fontsize", "style", "penwidth",
        "fixedsize", "orientation", "sides", "distortion",
        "skew", "regular", "peripheries", "nojustify",
        "labelloc", "xlabel", "image", "imagescale", "imagepos",
        "_xlabel_pos_x", "_xlabel_pos_y",
        "tooltip", "URL", "href", "target", "id", "class",
        "comment", "colorscheme", "gradientangle",
    )

    # Edge attribute passthrough list for JSON output
    _EDGE_PASSTHROUGH = (
        "label", "color", "fontcolor", "fontname", "fontsize",
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
        "tailURL", "tailhref", "tailtarget", "tailtooltip",
    )

    # Graph attribute passthrough list for JSON output
    _GRAPH_PASSTHROUGH = (
        "bgcolor", "label", "labelloc", "labeljust",
        "fontname", "fontsize", "fontcolor", "stylesheet",
        "tooltip", "URL", "href", "target", "id", "class",
        "comment", "colorscheme", "gradientangle",
        "_label_pos_x", "_label_pos_y", "rankdir",
    )

    def __init__(self, graph: "Graph"):
        self.graph = graph
        self.lnodes: dict = {}  # name → layout node (engine-specific dataclass)
        # Common graph-level settings
        self.pad = 4.0
        self.dpi = 96.0
        self.ratio = ""
        self.graph_size: tuple[float, float] | None = None
        self.rotate_deg = 0
        self.landscape = False
        self.center = False
        self.normalize = False
        self.outputorder = "breadthfirst"
        self.forcelabels = True

    @abstractmethod
    def layout(self) -> dict:
        """Compute layout and return a JSON-serializable result dict."""
        ...

    # ── Common graph attribute initialization ────

    def _init_common_attrs(self):
        """Read graph attributes shared across all engines.

        Call this from ``_init_from_graph()`` in subclasses.
        """
        self.ratio = (self.graph.get_graph_attr("ratio") or "").lower()
        self.normalize = (self.graph.get_graph_attr("normalize") or "").lower() \
                         in ("true", "1", "yes")
        self.center = (self.graph.get_graph_attr("center") or "").lower() \
                      in ("true", "1", "yes")
        self.landscape = (self.graph.get_graph_attr("landscape") or "").lower() \
                         in ("true", "1", "yes")
        self.forcelabels = (self.graph.get_graph_attr("forcelabels") or "true").lower() \
                           not in ("false", "0", "no")
        self.outputorder = (self.graph.get_graph_attr("outputorder") or "breadthfirst").lower()

        pad_str = self.graph.get_graph_attr("pad")
        if pad_str:
            try:
                self.pad = float(pad_str) * 72.0
            except ValueError:
                pass

        dpi_str = self.graph.get_graph_attr("dpi") or \
                  self.graph.get_graph_attr("resolution")
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
                self.graph_size = (float(parts[0]) * 72.0,
                                   float(parts[1]) * 72.0)
            except (ValueError, IndexError):
                pass

    # ── Node sizing ──────────────────────────────

    def _compute_node_size(self, name: str, node) -> tuple[float, float]:
        """Compute node dimensions from label text, shape, and attributes."""
        attrs = node.attributes if node else {}

        fixedsize = attrs.get("fixedsize", "false").lower() in \
                    ("true", "1", "yes", "shape")
        explicit_w = attrs.get("width")
        explicit_h = attrs.get("height")

        if fixedsize:
            w = float(explicit_w) * 72.0 if explicit_w else self._MIN_WIDTH
            h = float(explicit_h) * 72.0 if explicit_h else self._MIN_HEIGHT
            return w, h
        if explicit_w and explicit_h:
            return float(explicit_w) * 72.0, float(explicit_h) * 72.0

        label = attrs.get("label", name)
        try:
            fontsize = float(attrs.get("fontsize", "14"))
        except ValueError:
            fontsize = 14.0
        char_w = fontsize * 0.52

        # Strip HTML tags for sizing
        if label.startswith("<") and label.endswith(">"):
            import re
            label = re.sub(r"<[^>]+>", "", label)

        lines = label.replace("\\n", "\n").split("\n")
        max_len = max(len(line) for line in lines) if lines else len(name)
        w = max_len * char_w + self._H_PAD
        h = len(lines) * fontsize * 1.2 + self._V_PAD

        if explicit_w:
            w = float(explicit_w) * 72.0
        if explicit_h:
            h = float(explicit_h) * 72.0

        return max(w, self._MIN_WIDTH), max(h, self._MIN_HEIGHT)

    # ── Post-processing ──────────────────────────

    def _apply_normalize(self):
        """Translate so minimum coordinates are at origin.

        Skips normalization if any nodes are pinned.
        """
        real = list(self.lnodes.values())
        if not real:
            return
        if any(getattr(ln, "pinned", False) for ln in real):
            return
        min_x = min(ln.x - ln.width / 2 for ln in real)
        min_y = min(ln.y - ln.height / 2 for ln in real)
        for ln in real:
            ln.x -= min_x
            ln.y -= min_y

    def _apply_rotation(self):
        """Rotate layout by ``rotate`` attribute or landscape mode."""
        angle = self.rotate_deg
        if self.landscape and angle == 0:
            angle = 90
        if angle == 0:
            return
        rad = math.radians(angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        for ln in self.lnodes.values():
            x, y = ln.x, ln.y
            ln.x = x * cos_a - y * sin_a
            ln.y = x * sin_a + y * cos_a
            if angle in (90, 270, -90):
                ln.width, ln.height = ln.height, ln.width

    def _apply_center(self):
        """Center the layout at the origin."""
        real = list(self.lnodes.values())
        if not real:
            return
        min_x = min(ln.x - ln.width / 2 for ln in real)
        max_x = max(ln.x + ln.width / 2 for ln in real)
        min_y = min(ln.y - ln.height / 2 for ln in real)
        max_y = max(ln.y + ln.height / 2 for ln in real)
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        for ln in real:
            ln.x -= cx
            ln.y -= cy

    # ── Label placement ──────────────────────────

    @staticmethod
    def _estimate_label_size(text: str, font_size: float = 14.0) -> tuple[float, float]:
        """Estimate label bounding box in points (width, height)."""
        lines = text.replace("\\n", "\n").split("\n")
        max_chars = max(len(line) for line in lines) if lines else len(text)
        return (max(max_chars * font_size * 0.6, 20.0),
                len(lines) * font_size * 1.2)

    @staticmethod
    def _overlap_area(ax, ay, aw, ah, bx, by, bw, bh) -> float:
        """Compute overlap area between two center-based rectangles."""
        dx = min(ax + aw / 2, bx + bw / 2) - max(ax - aw / 2, bx - bw / 2)
        dy = min(ay + ah / 2, by + bh / 2) - max(ay - ah / 2, by - bh / 2)
        return dx * dy if dx > 0 and dy > 0 else 0.0

    def _compute_label_positions(self):
        """Compute positions for xlabel, headlabel, taillabel, graph label.

        Uses collision-aware 6-position search around each anchor object.
        """
        obstacles = [(ln.x, ln.y, ln.width, ln.height)
                     for ln in self.lnodes.values()]
        placed: list[tuple[float, float, float, float]] = []

        def _find_best(ax, ay, ow, oh, lw, lh, pad=4.0):
            half_ow, half_oh = ow / 2, oh / 2
            candidates = [
                (ax + half_ow + pad + lw / 2, ay),
                (ax + half_ow + pad + lw / 2, ay + half_oh + pad + lh / 2),
                (ax + half_ow + pad + lw / 2, ay - half_oh - pad - lh / 2),
                (ax, ay + half_oh + pad + lh / 2),
                (ax, ay - half_oh - pad - lh / 2),
                (ax - half_ow - pad - lw / 2, ay),
            ]
            best_pos, best_ov = candidates[0], float("inf")
            for cx, cy in candidates:
                total = sum(self._overlap_area(cx, cy, lw, lh, *o)
                            for o in obstacles)
                total += sum(self._overlap_area(cx, cy, lw, lh, *p)
                             for p in placed)
                if total == 0:
                    return (cx, cy)
                if total < best_ov:
                    best_ov, best_pos = total, (cx, cy)
            return best_pos

        # Node xlabels
        for name, ln in self.lnodes.items():
            if not ln.node:
                continue
            xlabel = ln.node.attributes.get("xlabel", "")
            if not xlabel:
                continue
            try:
                fs = float(ln.node.attributes.get("fontsize", "14"))
            except ValueError:
                fs = 14.0
            lw, lh = self._estimate_label_size(xlabel, fs)
            bx, by = _find_best(ln.x, ln.y, ln.width, ln.height, lw, lh)
            ln.node.attributes["_xlabel_pos_x"] = str(round(bx, 2))
            ln.node.attributes["_xlabel_pos_y"] = str(round(by, 2))
            placed.append((bx, by, lw, lh))

        # Edge head/tail labels
        for key, edge in self.graph.edges.items():
            t_ln = self.lnodes.get(edge.tail.name)
            h_ln = self.lnodes.get(edge.head.name)
            if not t_ln or not h_ln:
                continue
            try:
                fs = float(edge.attributes.get("labelfontsize",
                           edge.attributes.get("fontsize", "14")))
            except ValueError:
                fs = 14.0

            for attr_name, ref_ln in [("headlabel", h_ln), ("taillabel", t_ln)]:
                lbl = edge.attributes.get(attr_name, "")
                if lbl:
                    lw, lh = self._estimate_label_size(lbl, fs)
                    bx, by = _find_best(ref_ln.x, ref_ln.y, 2, 2, lw, lh, 6)
                    prefix = "_headlabel" if "head" in attr_name else "_taillabel"
                    edge.attributes[f"{prefix}_pos_x"] = str(round(bx, 2))
                    edge.attributes[f"{prefix}_pos_y"] = str(round(by, 2))
                    placed.append((bx, by, lw, lh))

        # Graph label
        graph_label = self.graph.get_graph_attr("label")
        if graph_label:
            try:
                gfs = float(self.graph.get_graph_attr("fontsize") or "14")
            except ValueError:
                gfs = 14.0
            lw, lh = self._estimate_label_size(graph_label, gfs)
            labelloc = (self.graph.get_graph_attr("labelloc") or "b").lower()
            labeljust = (self.graph.get_graph_attr("labeljust") or "c").lower()
            real = list(self.lnodes.values())
            if real:
                gbb_x1 = min(ln.x - ln.width / 2 for ln in real)
                gbb_x2 = max(ln.x + ln.width / 2 for ln in real)
                gbb_y1 = min(ln.y - ln.height / 2 for ln in real)
                gbb_y2 = max(ln.y + ln.height / 2 for ln in real)
            else:
                gbb_x1 = gbb_y1 = 0
                gbb_x2 = gbb_y2 = 100
            gcx = (gbb_x1 + gbb_x2) / 2
            gx = {"l": gbb_x1 + lw / 2, "r": gbb_x2 - lw / 2}.get(labeljust, gcx)
            gy = gbb_y1 - lh / 2 - 8 if labelloc == "t" else gbb_y2 + lh / 2 + 8
            self.graph.set_graph_attr("_label_pos_x", str(round(gx, 2)))
            self.graph.set_graph_attr("_label_pos_y", str(round(gy, 2)))

    # ── Edge boundary clipping ───────────────────

    @staticmethod
    def _clip_to_boundary(cx, cy, w, h, tx, ty, shape="ellipse"):
        """Clip a line from (tx,ty) toward (cx,cy) to the node boundary."""
        dx, dy = tx - cx, ty - cy
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            return (cx, cy)
        hw, hh = w / 2, h / 2
        if shape in ("box", "record", "Mrecord", "rect", "rectangle",
                      "house", "invhouse", "folder", "component", "tab",
                      "note", "box3d", "cds"):
            if abs(dx) * hh > abs(dy) * hw:
                t = hw / abs(dx)
            else:
                t = hh / abs(dy)
            return (cx + dx * t, cy + dy * t)
        else:
            angle = math.atan2(dy, dx)
            return (cx + hw * math.cos(angle), cy + hh * math.sin(angle))

    # ── Connected components ─────────────────────

    def _find_components(self, adj: dict[str, list[str]]) -> list[set[str]]:
        """Find connected components using BFS."""
        visited: set[str] = set()
        components: list[set[str]] = []
        for node in adj:
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
                for nb in adj.get(n, []):
                    if nb not in visited:
                        queue.append(nb)
            components.append(comp)
        return components

    def _pack_components_lr(self, components: list[set[str]],
                            gap: float = 36.0):
        """Pack multiple laid-out components left-to-right."""
        x_offset = 0.0
        for comp in components:
            comp_lns = [self.lnodes[n] for n in comp if n in self.lnodes]
            if not comp_lns:
                continue
            min_x = min(ln.x - ln.width / 2 for ln in comp_lns)
            max_x = max(ln.x + ln.width / 2 for ln in comp_lns)
            dx = x_offset - min_x
            for ln in comp_lns:
                ln.x += dx
            x_offset += (max_x - min_x) + gap

    # ── Write-back ───────────────────────────────

    def _write_back(self):
        """Write layout results back to graph node/edge attributes."""
        for name, ln in self.lnodes.items():
            if ln.node:
                ln.node.agset("pos", f"{round(ln.x, 2)},{round(ln.y, 2)}")
                ln.node.agset("width", str(round(ln.width / 72.0, 4)))
                ln.node.agset("height", str(round(ln.height / 72.0, 4)))

        for key, edge in self.graph.edges.items():
            t_ln = self.lnodes.get(edge.tail.name)
            h_ln = self.lnodes.get(edge.head.name)
            if t_ln and h_ln:
                t_shape = (edge.tail.attributes.get("shape", "ellipse")
                           if edge.tail else "ellipse")
                h_shape = (edge.head.attributes.get("shape", "ellipse")
                           if edge.head else "ellipse")
                p1 = self._clip_to_boundary(
                    t_ln.x, t_ln.y, t_ln.width, t_ln.height,
                    h_ln.x, h_ln.y, t_shape)
                p2 = self._clip_to_boundary(
                    h_ln.x, h_ln.y, h_ln.width, h_ln.height,
                    t_ln.x, t_ln.y, h_shape)
                edge.agset("pos",
                           f"s,{round(p1[0], 2)},{round(p1[1], 2)} "
                           f"e,{round(p2[0], 2)},{round(p2[1], 2)}")

        real = list(self.lnodes.values())
        if real:
            bb = (
                round(min(ln.x - ln.width / 2 for ln in real), 2),
                round(min(ln.y - ln.height / 2 for ln in real), 2),
                round(max(ln.x + ln.width / 2 for ln in real), 2),
                round(max(ln.y + ln.height / 2 for ln in real), 2),
            )
            self.graph.set_graph_attr("bb", f"{bb[0]},{bb[1]},{bb[2]},{bb[3]}")

    # ── JSON output ──────────────────────────────

    def _to_json(self) -> dict:
        """Convert layout results to a JSON-serializable dict."""
        nodes_json = []
        for name, ln in self.lnodes.items():
            entry = {
                "name": name,
                "x": round(ln.x, 2),
                "y": round(ln.y, 2),
                "width": round(ln.width, 2),
                "height": round(ln.height, 2),
            }
            if ln.node:
                for attr in self._NODE_PASSTHROUGH:
                    val = ln.node.attributes.get(attr)
                    if val:
                        entry[attr] = val
            nodes_json.append(entry)

        edges_json = []
        for key, edge in self.graph.edges.items():
            t_name, h_name = edge.tail.name, edge.head.name
            t_ln, h_ln = self.lnodes.get(t_name), self.lnodes.get(h_name)
            if not t_ln or not h_ln:
                continue

            t_shape = (edge.tail.attributes.get("shape", "ellipse")
                       if edge.tail else "ellipse")
            h_shape = (edge.head.attributes.get("shape", "ellipse")
                       if edge.head else "ellipse")
            p1 = self._clip_to_boundary(
                t_ln.x, t_ln.y, t_ln.width, t_ln.height,
                h_ln.x, h_ln.y, t_shape)
            p2 = self._clip_to_boundary(
                h_ln.x, h_ln.y, h_ln.width, h_ln.height,
                t_ln.x, t_ln.y, h_shape)

            points = [[round(p1[0], 2), round(p1[1], 2)],
                      [round(p2[0], 2), round(p2[1], 2)]]
            edge_entry = {"tail": t_name, "head": h_name, "points": points}

            for attr in self._EDGE_PASSTHROUGH:
                val = edge.attributes.get(attr)
                if val:
                    edge_entry[attr] = val

            if edge_entry.get("label"):
                edge_entry["label_pos"] = [
                    round((points[0][0] + points[1][0]) / 2, 2),
                    round((points[0][1] + points[1][1]) / 2, 2),
                ]
            edges_json.append(edge_entry)

        if nodes_json:
            min_x = min(n["x"] - n["width"] / 2 for n in nodes_json)
            min_y = min(n["y"] - n["height"] / 2 for n in nodes_json)
            max_x = max(n["x"] + n["width"] / 2 for n in nodes_json)
            max_y = max(n["y"] + n["height"] / 2 for n in nodes_json)
        else:
            min_x = min_y = max_x = max_y = 0

        graph_meta = {
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

        for attr in self._GRAPH_PASSTHROUGH:
            val = self.graph.get_graph_attr(attr)
            if val:
                graph_meta[attr] = val

        return {"graph": graph_meta, "nodes": nodes_json, "edges": edges_json}
