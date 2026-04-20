"""
Abstract base classes for all GraphvizPy layout engines.

Two-level hierarchy:

- ``LayoutView`` — abstract intermediate base that extends ``GraphView``
  with the common layout query API (positions, dimensions, edge routes,
  bounding boxes).  Layout engines inherit from this so they plug into
  ``graph.views`` alongside simulation / analysis / rendering views.
- ``LayoutEngine`` — concrete algorithm-runner base extending
  ``LayoutView``.  Adds shared algorithm utilities: node sizing,
  post-processing (normalize/rotate/center), label placement, edge
  boundary clipping, component detection/packing, write-back, and
  legacy JSON output generation.

These correspond to Graphviz ``lib/common/`` shared functions
(postproc.c, utils.c, geomprocs.h).
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from collections import deque, defaultdict
from typing import TYPE_CHECKING, Any, Optional

from gvpy.core.graph_view import GraphView

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.core.node import Node
    from gvpy.core.edge import Edge


class LayoutView(GraphView, ABC):
    """Abstract base class for layout views.

    Extends :class:`GraphView` with the common query API that any layout
    engine (dot, neato, fdp, circo, twopi, sfdp, osage, patchwork,
    pictosync) must provide.  Concrete subclasses hold the per-node and
    per-edge layout state and expose it through these read methods.

    C Graphviz analogue
    -------------------
    In C, each layout engine has its own ``Agraphinfo_t`` extension
    struct and a set of ``GD_*``/``ND_*``/``ED_*`` macros to access
    positions and dimensions.  ``LayoutView`` is the Python equivalent
    of those macros promoted to a method-based API so consumers can
    query layout state without knowing the engine internals.

    Required per-subclass state
    ---------------------------
    Subclasses must populate a ``self.lnodes: dict[str, LayoutNode]``
    dict where each entry has ``.x``, ``.y``, ``.width``, ``.height``,
    and ``.node`` (the underlying Graph node reference, or ``None``
    for virtual nodes).

    Round-trip contract
    -------------------
    The ``to_json``/``from_json`` pair serializes and restores the layout
    state — node positions, node dimensions, edge routes, cluster boxes.
    This is the canonical contract for pictosync's round-trip between
    the JSON editor and the graphical canvas.
    """

    view_name: str = "layout"

    # Node sizing constants (inherited by LayoutEngine).
    _MIN_WIDTH = 54.0    # 0.75in * 72dpi
    _MIN_HEIGHT = 36.0   # 0.50in * 72dpi
    _H_PAD = 36.0
    _V_PAD = 18.0

    # ── Layout query API ──────────────────────────────────────────

    def get_node_position(self, name: str) -> Optional[tuple[float, float]]:
        """Return ``(x, y)`` center position of node ``name``, or None."""
        ln = getattr(self, "lnodes", {}).get(name)
        if ln is None:
            return None
        return (ln.x, ln.y)

    def get_node_dimensions(self, name: str) -> Optional[tuple[float, float]]:
        """Return ``(width, height)`` of node ``name``, or None."""
        ln = getattr(self, "lnodes", {}).get(name)
        if ln is None:
            return None
        return (ln.width, ln.height)

    def get_bounding_box(self) -> tuple[float, float, float, float]:
        """Return the axis-aligned bounding box of all real nodes.

        Returns ``(min_x, min_y, max_x, max_y)``.  Virtual nodes and
        nodes without positions are excluded.  Empty layouts return
        ``(0, 0, 0, 0)``.
        """
        lnodes = getattr(self, "lnodes", {})
        real = [ln for ln in lnodes.values()
                if getattr(ln, "node", None) is not None]
        if not real:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(ln.x - ln.width / 2.0 for ln in real),
            min(ln.y - ln.height / 2.0 for ln in real),
            max(ln.x + ln.width / 2.0 for ln in real),
            max(ln.y + ln.height / 2.0 for ln in real),
        )

    def get_edge_route(self, edge: "Edge") -> list[tuple[float, float]]:
        """Return the list of route points for ``edge``.

        Default implementation returns a two-point straight line from
        tail center to head center.  Subclasses override to return
        spline control points or routed polyline points.
        """
        lnodes = getattr(self, "lnodes", {})
        t = lnodes.get(edge.tail.name) if edge.tail else None
        h = lnodes.get(edge.head.name) if edge.head else None
        if t is None or h is None:
            return []
        return [(t.x, t.y), (h.x, h.y)]

    def get_cluster_bbox(self, cl_name: str) \
            -> Optional[tuple[float, float, float, float]]:
        """Return cluster bounding box ``(min_x, min_y, max_x, max_y)``.

        Default implementation returns ``None``.  Engines that support
        clusters override this.
        """
        return None

    # ── Round-trip serialization (pictosync contract) ────────────

    def to_json(self) -> dict[str, Any]:
        """Serialize layout state to a JSON-compatible dict.

        Produces ``{"view_name", "nodes": [...], "edges": [...], "bb"}``
        suitable for persisting to disk or sending to a graphic editor.
        The ``from_json`` counterpart restores positions/dimensions onto
        an existing view.

        Subclasses with engine-specific state (ranks, clusters, etc.)
        may extend this by adding extra keys alongside the standard
        ``nodes``/``edges``/``bb`` fields.
        """
        lnodes = getattr(self, "lnodes", {})
        nodes_data = []
        for name, ln in lnodes.items():
            if getattr(ln, "node", None) is None:
                continue  # skip virtual nodes
            nodes_data.append({
                "name": name,
                "x": round(ln.x, 4),
                "y": round(ln.y, 4),
                "width": round(ln.width, 4),
                "height": round(ln.height, 4),
            })

        edges_data = []
        for edge in getattr(self.graph, "edges", {}).values():
            route = self.get_edge_route(edge)
            if not route:
                continue
            edges_data.append({
                "tail": edge.tail.name if edge.tail else None,
                "head": edge.head.name if edge.head else None,
                "points": [[round(x, 4), round(y, 4)] for x, y in route],
            })

        bb = self.get_bounding_box()
        return {
            "view_name": self.view_name,
            "nodes": nodes_data,
            "edges": edges_data,
            "bb": [round(v, 4) for v in bb],
        }

    def from_json(self, data: dict[str, Any]) -> None:
        """Restore layout state from a JSON-compatible dict.

        Updates positions and dimensions on existing ``self.lnodes``
        entries whose names appear in ``data["nodes"]``.  Does NOT
        create new lnodes — the view must already have its lnode
        skeleton (either from a prior ``layout()`` call or from an
        explicit initializer that walks the graph).

        To round-trip a fresh view:

            info = DotGraphInfo(g)
            info.layout()                       # populate lnodes + positions
            saved = info.to_json()              # capture state
            info2 = DotGraphInfo(g)
            info2.layout()                      # new lnodes, new positions
            info2.from_json(saved)              # replace positions
            assert info2.to_json() == saved     # round-trip holds
        """
        lnodes = getattr(self, "lnodes", None)
        if lnodes is None:
            return
        for entry in data.get("nodes", []):
            name = entry.get("name")
            ln = lnodes.get(name)
            if ln is None:
                continue
            if "x" in entry:
                ln.x = float(entry["x"])
            if "y" in entry:
                ln.y = float(entry["y"])
            if "width" in entry:
                ln.width = float(entry["width"])
            if "height" in entry:
                ln.height = float(entry["height"])


class LayoutEngine(LayoutView):
    """Concrete base class for graph layout engines.

    Extends :class:`LayoutView` with algorithm-runner scaffolding:
    node sizing, post-processing, label placement, edge clipping,
    component handling, write-back and legacy JSON output.

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

    Node sizing constants (``_MIN_WIDTH``, ``_MIN_HEIGHT``, ``_H_PAD``,
    ``_V_PAD``) are inherited from :class:`LayoutView`.
    """

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
        # Chain through LayoutView → GraphView so view-level state
        # (self.graph) is initialized cleanly.
        super().__init__(graph)
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
        """Delegate to :func:`common.postproc.apply_normalize`."""
        from gvpy.engines.layout.common import postproc
        postproc.apply_normalize(self)

    def _apply_rotation(self):
        """Delegate to :func:`common.postproc.apply_rotation`."""
        from gvpy.engines.layout.common import postproc
        postproc.apply_rotation(self)

    def _apply_center(self):
        """Delegate to :func:`common.postproc.apply_center`."""
        from gvpy.engines.layout.common import postproc
        postproc.apply_center(self)

    # ── Label placement ──────────────────────────
    # Delegate to common.text; keep method shims for subclass / caller compat.

    @staticmethod
    def _estimate_label_size(text: str, font_size: float = 14.0) -> tuple[float, float]:
        from gvpy.engines.layout.common import text as _text
        return _text.estimate_label_size(text, font_size)

    @staticmethod
    def _overlap_area(ax, ay, aw, ah, bx, by, bw, bh) -> float:
        from gvpy.engines.layout.common import text as _text
        return _text.overlap_area(ax, ay, aw, ah, bx, by, bw, bh)

    def _compute_label_positions(self):
        from gvpy.engines.layout.common import text as _text
        _text.compute_label_positions(self)

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
        """Delegate to :func:`common.postproc.find_components`."""
        from gvpy.engines.layout.common import postproc
        return postproc.find_components(adj)

    def _pack_components_lr(self, components: list[set[str]],
                            gap: float = 36.0):
        """Delegate to :func:`common.postproc.pack_components_lr`."""
        from gvpy.engines.layout.common import postproc
        postproc.pack_components_lr(self, components, gap)

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
