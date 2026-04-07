"""
SVG renderer for dot layout results.

Converts the JSON layout dict produced by DotLayout.layout() into SVG markup.
Supports node shapes, colors, fill styles, fonts, edge colors, and styles.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Union
from xml.sax.saxutils import escape


_SVG_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<svg width="{w}pt" height="{h}pt" viewBox="{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}"
     xmlns="http://www.w3.org/2000/svg">
<g id="graph0" class="graph">
<title>{title}</title>
"""

_SVG_FOOTER = "</g>\n</svg>\n"

_ARROW_SIZE = 8.0
_DEF_FONT_SIZE = 14.0
_DEF_FONT_FAMILY = "sans-serif"
_DEF_CLUSTER_FILL = "#f5f5f5"
_DEF_CLUSTER_STROKE = "#999999"
_DEF_NODE_FILL = "#ffffff"
_DEF_NODE_STROKE = "#000000"
_DEF_EDGE_STROKE = "#000000"

# SVG stroke-dasharray for DOT style names
_STYLE_DASH = {
    "dashed": "7,3",
    "dotted": "2,2",
    "bold": None,   # handled via stroke-width
    "invis": None,  # handled via visibility
}


def _node_attrs(node: dict) -> tuple[str, str, str, float, str, float]:
    """Extract (fill, stroke, font_family, font_size, font_color, penwidth) from node dict."""
    style = node.get("style", "")
    fill = node.get("fillcolor", node.get("color", ""))
    stroke = node.get("color", _DEF_NODE_STROKE)
    if not fill:
        fill = _DEF_NODE_FILL if "filled" not in style else stroke
    if "filled" in style and not node.get("fillcolor"):
        fill = node.get("color", "#d3d3d3")
    if node.get("fillcolor"):
        fill = node["fillcolor"]
    font_family = node.get("fontname", _DEF_FONT_FAMILY)
    try:
        font_size = float(node.get("fontsize", _DEF_FONT_SIZE))
    except ValueError:
        font_size = _DEF_FONT_SIZE
    font_color = node.get("fontcolor", "#000000")
    try:
        penwidth = float(node.get("penwidth", "1"))
    except ValueError:
        penwidth = 1.0
    if "bold" in style:
        penwidth = max(penwidth, 2.0)
    return fill, stroke, font_family, font_size, font_color, penwidth


def _edge_attrs(edge: dict) -> tuple[str, float, str, str, float]:
    """Extract (stroke, penwidth, dasharray, font_color, font_size) from edge dict."""
    stroke = edge.get("color", _DEF_EDGE_STROKE)
    try:
        penwidth = float(edge.get("penwidth", "1"))
    except ValueError:
        penwidth = 1.0
    style = edge.get("style", "")
    dasharray = ""
    if "bold" in style:
        penwidth = max(penwidth, 2.5)
    if style in _STYLE_DASH and _STYLE_DASH[style]:
        dasharray = _STYLE_DASH[style]
    font_color = edge.get("fontcolor", "#000000")
    try:
        font_size = float(edge.get("fontsize", _DEF_FONT_SIZE - 2))
    except ValueError:
        font_size = _DEF_FONT_SIZE - 2
    return stroke, penwidth, dasharray, font_color, font_size


def _style_dasharray(style: str) -> str:
    if style in _STYLE_DASH and _STYLE_DASH[style]:
        return f' stroke-dasharray="{_STYLE_DASH[style]}"'
    return ""


def _regular_polygon(cx: float, cy: float, r: float, n: int,
                     fill: str = _DEF_NODE_FILL, stroke: str = _DEF_NODE_STROKE,
                     penwidth: float = 1.0) -> str:
    pts = []
    for i in range(n):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        px = cx + r * math.cos(angle)
        py = cy + r * math.sin(angle)
        pts.append(f"{px:.2f},{py:.2f}")
    return (f'<polygon points="{" ".join(pts)}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{penwidth}"/>')


def render_svg(layout: dict) -> str:
    """Convert a layout result dict to an SVG string."""
    graph = layout.get("graph", {})
    bb = graph.get("bb", [0, 0, 100, 100])
    pad = 4.0
    vx, vy = bb[0] - pad, bb[1] - pad
    vw = bb[2] - bb[0] + 2 * pad
    vh = bb[3] - bb[1] + 2 * pad
    title = escape(graph.get("name", ""))
    directed = graph.get("directed", True)

    parts = [_SVG_HEADER.format(
        w=round(vw), h=round(vh), vx=vx, vy=vy, vw=vw, vh=vh, title=title,
    )]

    for cl in layout.get("clusters", []):
        parts.append(_render_cluster(cl))
    for edge in layout.get("edges", []):
        parts.append(_render_edge(edge, directed))
    for node in layout.get("nodes", []):
        parts.append(_render_node(node))

    # Graph-level label
    graph_label = graph.get("label", "")
    graph_label_x = graph.get("_label_pos_x", "")
    graph_label_y = graph.get("_label_pos_y", "")
    if graph_label and graph_label_x and graph_label_y:
        gfont = graph.get("fontname", _DEF_FONT_FAMILY)
        try:
            gfsize = float(graph.get("fontsize", _DEF_FONT_SIZE))
        except ValueError:
            gfsize = _DEF_FONT_SIZE
        gfcolor = graph.get("fontcolor", "black")
        parts.append(
            f'<text x="{graph_label_x}" y="{graph_label_y}" '
            f'text-anchor="middle" font-family="{gfont}" '
            f'font-size="{gfsize}" fill="{gfcolor}">'
            f'{escape(graph_label)}</text>\n'
        )

    parts.append(_SVG_FOOTER)
    return "".join(parts)


def render_svg_file(layout: dict, filepath: Union[str, Path]):
    Path(filepath).write_text(render_svg(layout), encoding="utf-8")


# ── Cluster ──────────────────────────────────────

def _render_cluster(cl: dict) -> str:
    bb = cl.get("bb", [0, 0, 0, 0])
    x, y, w, h = bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]
    label = escape(cl.get("label", ""))
    style = cl.get("style", "")

    if "invis" in style:
        return ""

    fill = cl.get("fillcolor") or cl.get("bgcolor") or "none"
    if fill == "transparent":
        fill = "none"
    stroke = cl.get("pencolor") or cl.get("color") or "black"
    try:
        pw = float(cl.get("penwidth", "1"))
    except ValueError:
        pw = 1.0
    dash = ""
    if "dashed" in style:
        dash = ' stroke-dasharray="5,2"'
    if "dotted" in style:
        dash = ' stroke-dasharray="2,2"'
    if "bold" in style:
        pw = max(pw, 2.0)
    sw = f' stroke-width="{pw}"' if pw != 1.0 else ""

    font_family = cl.get("fontname", _DEF_FONT_FAMILY)
    try:
        font_size = float(cl.get("fontsize", _DEF_FONT_SIZE - 2))
    except ValueError:
        font_size = _DEF_FONT_SIZE - 2
    font_color = cl.get("fontcolor", "#000000")

    # Tooltip and URL
    tooltip_attr = ""
    if cl.get("tooltip"):
        tooltip_attr = f'<title>{escape(cl["tooltip"])}</title>\n'
    url_open = url_close = ""
    url = cl.get("URL") or cl.get("href")
    if url:
        target = cl.get("target", "_blank")
        url_open = f'<a xlink:href="{escape(url)}" target="{target}">\n'
        url_close = "</a>\n"

    cl_id = cl.get("id") or cl.get("name", "")
    cl_class = cl.get("class", "cluster")

    lines = [
        f'{url_open}<g id="{escape(cl_id)}" class="{cl_class}">',
        tooltip_attr,
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
        f'fill="{fill}" stroke="{stroke}"{sw}{dash}/>',
    ]
    if "filled" in style and fill == _DEF_CLUSTER_FILL:
        # Default filled style uses color as fill
        c = cl.get("color", "#d3d3d3")
        lines[-1] = (
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="{c}" stroke="{stroke}"{sw}{dash}/>'
        )
    if label:
        tx = x + w / 2
        ty = y + 12
        lines.append(
            f'<text x="{tx:.2f}" y="{ty:.2f}" text-anchor="middle" '
            f'font-family="{font_family}" font-size="{font_size}" '
            f'fill="{font_color}">{label}</text>'
        )
    lines.append(f"</g>{url_close}")
    return "\n".join(lines) + "\n"


# ── Node ─────────────────────────────────────────

# ── Record shape parsing and rendering ────────────

def _parse_record_label(label: str) -> dict:
    """Parse a record label into a tree following the Graphviz grammar.

    Grammar::

        rlabel  = field ( '|' field )*
        field   = fieldId | '{' rlabel '}'
        fieldId = [ '<' portname '>' ] [ text ]

    Returns a dict tree::

        {"text": str, "port": str, "children": list[dict], "flipped": bool}

    ``flipped`` is True when the field was wrapped in ``{}``, which
    flips the orientation from horizontal to vertical or vice versa.
    """
    if not label:
        return {"text": "", "port": "", "children": [], "flipped": False}

    def _parse_rlabel(s: str) -> list[dict]:
        """Parse an rlabel: field ( '|' field )*"""
        fields = []
        i = 0
        while i <= len(s):
            field, i = _parse_field(s, i)
            fields.append(field)
            if i < len(s) and s[i] == "|":
                i += 1  # skip separator
            else:
                break
        return fields

    def _parse_field(s: str, i: int) -> tuple[dict, int]:
        """Parse a single field: fieldId or '{' rlabel '}'"""
        # Skip whitespace
        while i < len(s) and s[i] == " ":
            i += 1
        if i >= len(s):
            return {"text": "", "port": "", "children": [], "flipped": False}, i

        if s[i] == "{":
            # Flipped sub-fields
            i += 1  # skip '{'
            # Find matching '}'
            level = 1
            start = i
            while i < len(s) and level > 0:
                if s[i] == "{":
                    level += 1
                elif s[i] == "}":
                    level -= 1
                elif s[i] == "\\":
                    i += 1  # skip escaped char
                i += 1
            inner = s[start:i - 1]
            children = _parse_rlabel(inner)
            return {"text": "", "port": "", "children": children,
                    "flipped": True}, i

        # fieldId: [ '<' portname '>' ] [ text ]
        port = ""
        text = ""
        if i < len(s) and s[i] == "<":
            j = s.index(">", i + 1) if ">" in s[i + 1:] else len(s)
            port = s[i + 1:j]
            i = j + 1

        # Read text until |, {, or end
        while i < len(s) and s[i] not in ("|", "{", "}"):
            if s[i] == "\\":
                i += 1
                if i < len(s):
                    text += s[i]
            else:
                text += s[i]
            i += 1

        return {"text": text.strip(), "port": port, "children": [],
                "flipped": False}, i

    # If the entire label is wrapped in {}, unwrap and mark as flipped
    stripped = label.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        # Check that these braces match (not two separate groups)
        level = 0
        matched = False
        for ci, ch in enumerate(stripped):
            if ch == "{":
                level += 1
            elif ch == "}":
                level -= 1
            if ch == "\\":
                continue
            if level == 0 and ci == len(stripped) - 1:
                matched = True
        if matched:
            children = _parse_rlabel(stripped[1:-1])
            return {"text": "", "port": "", "children": children,
                    "flipped": True}

    # Not wrapped — parse as rlabel at top level
    children = _parse_rlabel(stripped)
    if len(children) == 1:
        return children[0]
    return {"text": "", "port": "", "children": children, "flipped": False}


def _render_record(root: dict, x: float, y: float, w: float, h: float,
                   horizontal: bool, stroke: str, fill: str,
                   font_family: str, font_size: float, font_color: str,
                   penwidth: float, rounded: bool = False) -> list[str]:
    """Render a parsed record label tree as SVG.

    Parameters
    ----------
    root : dict
        Parsed record tree from ``_parse_record_label()``.
    horizontal : bool
        Base orientation.  For ``rankdir=TB/BT`` the default is True
        (fields left-to-right).  For ``rankdir=LR/RL`` it's False
        (fields top-to-bottom).  Each ``{...}`` in the label flips it.
    """
    lines = []
    sw = f' stroke-width="{penwidth}"' if penwidth != 1.0 else ""

    # Outer rectangle
    rx = ' rx="4" ry="4"' if rounded else ""
    lines.append(
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" '
        f'height="{h:.2f}"{rx} fill="{fill}" stroke="{stroke}"{sw}/>')

    # Determine effective orientation for this node
    # If root is flipped, flip the base orientation
    effective_h = not horizontal if root.get("flipped") else horizontal

    if root.get("children"):
        _render_fields(root["children"], x, y, w, h, effective_h,
                       stroke, font_family, font_size, font_color,
                       penwidth, lines)
    elif root.get("text") or root.get("port"):
        text = root.get("text") or " "
        tx = x + w / 2
        ty = y + h / 2 + font_size * 0.35
        lines.append(
            f'<text x="{tx:.2f}" y="{ty:.2f}" '
            f'text-anchor="middle" font-family="{font_family}" '
            f'font-size="{font_size}" fill="{font_color}">'
            f'{escape(text)}</text>')

    return lines


def _render_fields(fields: list[dict], x: float, y: float,
                   w: float, h: float, horizontal: bool,
                   stroke: str, font_family: str, font_size: float,
                   font_color: str, penwidth: float,
                   lines: list[str]):
    """Render a list of record fields within the given rectangle."""
    n = len(fields)
    if n == 0:
        return
    sw = f' stroke-width="{penwidth}"' if penwidth != 1.0 else ""

    if horizontal:
        cell_w = w / n
        for i, field in enumerate(fields):
            cx = x + i * cell_w
            # Vertical divider between fields
            if i > 0:
                lines.append(
                    f'<line x1="{cx:.2f}" y1="{y:.2f}" '
                    f'x2="{cx:.2f}" y2="{y + h:.2f}" '
                    f'stroke="{stroke}"{sw}/>')
            if field.get("children"):
                # Flipped sub-fields: flip orientation
                effective = not horizontal if field.get("flipped") else horizontal
                _render_fields(field["children"], cx, y, cell_w, h,
                               effective, stroke, font_family, font_size,
                               font_color, penwidth, lines)
            else:
                text = field.get("text") or " "
                tx = cx + cell_w / 2
                ty = y + h / 2 + font_size * 0.35
                lines.append(
                    f'<text x="{tx:.2f}" y="{ty:.2f}" '
                    f'text-anchor="middle" font-family="{font_family}" '
                    f'font-size="{font_size}" fill="{font_color}">'
                    f'{escape(text)}</text>')
    else:
        cell_h = h / n
        for i, field in enumerate(fields):
            cy = y + i * cell_h
            # Horizontal divider between fields
            if i > 0:
                lines.append(
                    f'<line x1="{x:.2f}" y1="{cy:.2f}" '
                    f'x2="{x + w:.2f}" y2="{cy:.2f}" '
                    f'stroke="{stroke}"{sw}/>')
            if field.get("children"):
                effective = not horizontal if field.get("flipped") else horizontal
                _render_fields(field["children"], x, cy, w, cell_h,
                               effective, stroke, font_family, font_size,
                               font_color, penwidth, lines)
            else:
                text = field.get("text") or " "
                tx = x + w / 2
                ty = cy + cell_h / 2 + font_size * 0.35
                lines.append(
                    f'<text x="{tx:.2f}" y="{ty:.2f}" '
                    f'text-anchor="middle" font-family="{font_family}" '
                    f'font-size="{font_size}" fill="{font_color}">'
                    f'{escape(text)}</text>')


def _render_node(node: dict) -> str:
    x, y = node["x"], node["y"]
    w, h = node["width"], node["height"]
    hw, hh = w / 2, h / 2
    name = escape(node["name"])
    shape = node.get("shape", "ellipse")
    style = node.get("style", "")

    if "invis" in style:
        return ""

    fill, stroke, font_family, font_size, font_color, penwidth = _node_attrs(node)
    node_dash = _style_dasharray(style)
    sw = f' stroke-width="{penwidth}"' if penwidth != 1.0 else ""
    base = f'fill="{fill}" stroke="{stroke}"{sw}{node_dash}'

    node_id = node.get("id") or f"node_{name}"
    node_class = node.get("class", "node")
    tooltip = node.get("tooltip", "")
    url = node.get("URL") or node.get("href", "")

    url_open = url_close = ""
    if url:
        target = node.get("target", "_blank")
        url_open = f'<a xlink:href="{escape(url)}" target="{target}">'
        url_close = "</a>"

    lines = [f'{url_open}<g id="{escape(node_id)}" class="{node_class}">']
    if tooltip:
        lines.append(f'<title>{escape(tooltip)}</title>')

    if shape in ("record", "Mrecord"):
        # Record shape: parse label into fields, render with dividers
        label_text = node.get("label", name)
        fields = _parse_record_label(label_text)
        is_rounded = shape == "Mrecord" or "rounded" in style
        # TB/BT => horizontal (fields left-to-right), LR/RL => vertical
        rankdir = node.get("_rankdir", "TB")
        rec_horizontal = rankdir in ("TB", "BT")
        record_lines = _render_record(
            fields, x - hw, y - hh, w, h,
            horizontal=rec_horizontal,
            stroke=stroke, fill=fill,
            font_family=font_family, font_size=font_size,
            font_color=font_color, penwidth=penwidth,
            rounded=is_rounded)
        lines.extend(record_lines)
    elif shape in ("box", "rect", "rectangle", "square"):
        rnd = ' rx="8" ry="8"' if "rounded" in style else ""
        lines.append(
            f'<rect x="{x - hw:.2f}" y="{y - hh:.2f}" '
            f'width="{w:.2f}" height="{h:.2f}"{rnd} {base}/>'
        )
    elif shape == "circle":
        r = max(hw, hh)
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" {base}/>')
    elif shape == "doublecircle":
        r = max(hw, hh)
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" {base}/>')
        lines.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r - 3:.2f}" '
            f'fill="none" stroke="{stroke}"{sw}/>')
    elif shape == "diamond":
        pts = f"{x:.2f},{y-hh:.2f} {x+hw:.2f},{y:.2f} {x:.2f},{y+hh:.2f} {x-hw:.2f},{y:.2f}"
        lines.append(f'<polygon points="{pts}" {base}/>')
    elif shape == "triangle":
        pts = f"{x:.2f},{y-hh:.2f} {x+hw:.2f},{y+hh:.2f} {x-hw:.2f},{y+hh:.2f}"
        lines.append(f'<polygon points="{pts}" {base}/>')
    elif shape in ("invtriangle", "invhouse"):
        pts = f"{x-hw:.2f},{y-hh:.2f} {x+hw:.2f},{y-hh:.2f} {x:.2f},{y+hh:.2f}"
        lines.append(f'<polygon points="{pts}" {base}/>')
    elif shape == "house":
        pts = (f"{x:.2f},{y-hh:.2f} {x+hw:.2f},{y:.2f} "
               f"{x+hw:.2f},{y+hh:.2f} {x-hw:.2f},{y+hh:.2f} {x-hw:.2f},{y:.2f}")
        lines.append(f'<polygon points="{pts}" {base}/>')
    elif shape == "pentagon":
        lines.append(_regular_polygon(x, y, max(hw, hh), 5, fill, stroke, penwidth))
    elif shape == "hexagon":
        lines.append(_regular_polygon(x, y, max(hw, hh), 6, fill, stroke, penwidth))
    elif shape in ("septagon", "heptagon"):
        lines.append(_regular_polygon(x, y, max(hw, hh), 7, fill, stroke, penwidth))
    elif shape == "octagon":
        lines.append(_regular_polygon(x, y, max(hw, hh), 8, fill, stroke, penwidth))
    elif shape == "doubleoctagon":
        lines.append(_regular_polygon(x, y, max(hw, hh), 8, fill, stroke, penwidth))
        lines.append(_regular_polygon(x, y, max(hw, hh) - 3, 8, "none", stroke, penwidth))
    elif shape == "point":
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{stroke}" stroke="{stroke}"/>')
    elif shape in ("plaintext", "plain", "none"):
        pass
    else:
        lines.append(
            f'<ellipse cx="{x:.2f}" cy="{y:.2f}" rx="{hw:.2f}" ry="{hh:.2f}" {base}/>')

    # Label (skip for record shapes — text already rendered by field renderer)
    if shape not in ("point", "record", "Mrecord"):
        label = escape(node.get("label", name))
        lines.append(
            f'<text x="{x:.2f}" y="{y + font_size * 0.35:.2f}" '
            f'text-anchor="middle" font-family="{font_family}" '
            f'font-size="{font_size}" fill="{font_color}">{label}</text>'
        )
    # External label (xlabel) — positioned by collision-aware placement
    xlabel = node.get("xlabel", "")
    xlabel_x = node.get("_xlabel_pos_x", "")
    xlabel_y = node.get("_xlabel_pos_y", "")
    if xlabel and xlabel_x and xlabel_y:
        lines.append(
            f'<text x="{xlabel_x}" y="{xlabel_y}" '
            f'text-anchor="middle" font-family="{font_family}" '
            f'font-size="{font_size}" fill="{font_color}" '
            f'font-style="italic">{escape(xlabel)}</text>'
        )

    lines.append(f"</g>{url_close}")
    return "\n".join(lines) + "\n"


# ── Edge ─────────────────────────────────────────

def _render_edge(edge: dict, directed: bool) -> str:
    pts = edge.get("points", [])
    if not pts:
        return ""

    style = edge.get("style", "")
    if "invis" in style:
        return ""

    tail = escape(edge.get("tail", ""))
    head = escape(edge.get("head", ""))
    spline_type = edge.get("spline_type", "polyline")
    stroke, penwidth, dasharray, font_color, font_size = _edge_attrs(edge)

    extra = ""
    if dasharray:
        extra += f' stroke-dasharray="{dasharray}"'
    if penwidth != 1.0:
        extra += f' stroke-width="{penwidth}"'

    edge_id = edge.get("id") or f"edge_{tail}_{head}"
    edge_class = edge.get("class", "edge")
    tooltip = edge.get("tooltip", "")
    url = edge.get("URL") or edge.get("href", "")
    try:
        arrowsize = float(edge.get("arrowsize", "1.0"))
    except ValueError:
        arrowsize = 1.0

    # Edge body URL: edgeURL/edgehref overrides main URL for the line itself
    edge_url = edge.get("edgeURL") or edge.get("edgehref") or url
    edge_tooltip = edge.get("edgetooltip") or tooltip
    edge_target = edge.get("edgetarget") or edge.get("target", "_blank")

    url_open = url_close = ""
    if edge_url:
        url_open = f'<a xlink:href="{escape(edge_url)}" target="{edge_target}">'
        url_close = "</a>"

    lines = [f'{url_open}<g id="{escape(edge_id)}" class="{edge_class}">']
    if edge_tooltip:
        lines.append(f'<title>{escape(edge_tooltip)}</title>')

    if spline_type == "bezier" and len(pts) >= 4:
        lines.append(_bezier_path(pts, stroke, extra))
    else:
        lines.append(_polyline_path(pts, stroke, extra))

    # Arrows: head and/or tail based on dir attribute
    dir_attr = edge.get("dir", "forward" if directed else "none")
    head_type = edge.get("arrowhead", "normal")
    tail_type = edge.get("arrowtail", "")
    # If arrowtail not explicitly set, use arrowhead value for dir=back/both
    # (matches common user expectation)
    if not tail_type:
        tail_type = head_type if dir_attr in ("back", "both") else "normal"

    if len(pts) >= 2:
        # Head arrow
        if dir_attr in ("forward", "both"):
            tip = pts[-1]
            from_pt = _find_arrow_from(pts, -1)
            lines.append(_draw_arrow(from_pt, tip, head_type, stroke, arrowsize))

        # Tail arrow
        if dir_attr in ("back", "both"):
            tip = pts[0]
            from_pt = _find_arrow_from(pts, 0)
            lines.append(_draw_arrow(from_pt, tip, tail_type, stroke, arrowsize))

    # Edge label with optional labelURL/labeltooltip
    label = edge.get("label")
    label_pos = edge.get("label_pos")
    if label and label_pos:
        font_family = edge.get("fontname", _DEF_FONT_FAMILY)
        label_url = edge.get("labelURL") or edge.get("labelhref", "")
        label_target = edge.get("labeltarget", "_blank")
        label_tooltip = edge.get("labeltooltip", "")

        label_svg = (
            f'<text x="{label_pos[0]:.2f}" y="{label_pos[1]:.2f}" '
            f'text-anchor="middle" font-family="{font_family}" '
            f'font-size="{font_size}" fill="{font_color}">'
        )
        if label_tooltip:
            label_svg += f'<title>{escape(label_tooltip)}</title>'
        label_svg += f'{escape(label)}</text>'

        if label_url:
            label_svg = (f'<a xlink:href="{escape(label_url)}" '
                         f'target="{label_target}">{label_svg}</a>')
        lines.append(label_svg)

    # Head/tail labels
    hlabel_font = edge.get("labelfontname", _DEF_FONT_FAMILY)
    hlabel_color = edge.get("labelfontcolor", font_color)
    try:
        hlabel_size = float(edge.get("labelfontsize", font_size))
    except ValueError:
        hlabel_size = font_size
    headlabel = edge.get("headlabel", "")
    if headlabel:
        hx = edge.get("_headlabel_pos_x", "")
        hy = edge.get("_headlabel_pos_y", "")
        if hx and hy:
            head_url = edge.get("headURL") or edge.get("headhref", "")
            head_target = edge.get("headtarget", "_blank")
            head_tt = edge.get("headtooltip", "")
            h_svg = (
                f'<text x="{hx}" y="{hy}" text-anchor="start" '
                f'font-family="{hlabel_font}" font-size="{hlabel_size}" '
                f'fill="{hlabel_color}">'
            )
            if head_tt:
                h_svg += f'<title>{escape(head_tt)}</title>'
            h_svg += f'{escape(headlabel)}</text>'
            if head_url:
                h_svg = (f'<a xlink:href="{escape(head_url)}" '
                         f'target="{head_target}">{h_svg}</a>')
            lines.append(h_svg)

    taillabel = edge.get("taillabel", "")
    if taillabel:
        tx = edge.get("_taillabel_pos_x", "")
        ty = edge.get("_taillabel_pos_y", "")
        if tx and ty:
            tail_url = edge.get("tailURL") or edge.get("tailhref", "")
            tail_target = edge.get("tailtarget", "_blank")
            tail_tt = edge.get("tailtooltip", "")
            t_svg = (
                f'<text x="{tx}" y="{ty}" text-anchor="start" '
                f'font-family="{hlabel_font}" font-size="{hlabel_size}" '
                f'fill="{hlabel_color}">'
            )
            if tail_tt:
                t_svg += f'<title>{escape(tail_tt)}</title>'
            t_svg += f'{escape(taillabel)}</text>'
            if tail_url:
                t_svg = (f'<a xlink:href="{escape(tail_url)}" '
                         f'target="{tail_target}">{t_svg}</a>')
            lines.append(t_svg)

    lines.append(f"</g>{url_close}")
    return "\n".join(lines) + "\n"


def _polyline_path(pts: list, stroke: str, extra: str) -> str:
    coords = " ".join(f"{p[0]:.2f},{p[1]:.2f}" for p in pts)
    return f'<polyline fill="none" stroke="{stroke}"{extra} points="{coords}"/>'


def _bezier_path(pts: list, stroke: str, extra: str) -> str:
    d = f"M {pts[0][0]:.2f},{pts[0][1]:.2f}"
    i = 1
    while i + 2 < len(pts):
        c1, c2, ep = pts[i], pts[i + 1], pts[i + 2]
        d += f" C {c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} {ep[0]:.2f},{ep[1]:.2f}"
        i += 3
    return f'<path fill="none" stroke="{stroke}"{extra} d="{d}"/>'


def _find_arrow_from(pts: list, end_idx: int) -> list:
    """Find a non-coincident point to determine arrow direction."""
    tip = pts[end_idx]
    if end_idx == -1 or end_idx == len(pts) - 1:
        # Head: search backwards
        for i in range(len(pts) - 2, -1, -1):
            dx = tip[0] - pts[i][0]
            dy = tip[1] - pts[i][1]
            if dx * dx + dy * dy > 0.5:
                return pts[i]
        return [tip[0], tip[1] - 10]
    else:
        # Tail: search forwards
        for i in range(1, len(pts)):
            dx = tip[0] - pts[i][0]
            dy = tip[1] - pts[i][1]
            if dx * dx + dy * dy > 0.5:
                return pts[i]
        return [tip[0], tip[1] + 10]


def _draw_arrow(p_from: list, p_to: list, arrow_type: str,
                color: str, scale: float = 1.0) -> str:
    """Draw an arrow of the specified type at p_to pointing away from p_from."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 0.01:
        return ""

    ux, uy = dx / length, dy / length  # unit vector in edge direction
    px, py = -uy, ux                    # perpendicular
    s = _ARROW_SIZE * scale
    tx, ty = p_to[0], p_to[1]          # tip position

    if arrow_type == "none":
        return ""

    elif arrow_type in ("normal", ""):
        # Filled triangle
        left = [tx - ux * s + px * s * 0.4, ty - uy * s + py * s * 0.4]
        right = [tx - ux * s - px * s * 0.4, ty - uy * s - py * s * 0.4]
        return (f'<polygon fill="{color}" points='
                f'"{tx:.2f},{ty:.2f} {left[0]:.2f},{left[1]:.2f} '
                f'{right[0]:.2f},{right[1]:.2f}"/>')

    elif arrow_type == "inv":
        # Inverted triangle (pointing backwards)
        base_x, base_y = tx - ux * s, ty - uy * s
        left = [tx + px * s * 0.4, ty + py * s * 0.4]
        right = [tx - px * s * 0.4, ty - py * s * 0.4]
        return (f'<polygon fill="{color}" points='
                f'"{base_x:.2f},{base_y:.2f} {left[0]:.2f},{left[1]:.2f} '
                f'{right[0]:.2f},{right[1]:.2f}"/>')

    elif arrow_type == "dot":
        # Filled circle
        cx, cy = tx - ux * s * 0.5, ty - uy * s * 0.5
        r = s * 0.35
        return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{color}"/>'

    elif arrow_type == "odot":
        # Open circle
        cx, cy = tx - ux * s * 0.5, ty - uy * s * 0.5
        r = s * 0.35
        return (f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
                f'fill="white" stroke="{color}"/>')

    elif arrow_type == "diamond":
        # Filled diamond
        mid_x, mid_y = tx - ux * s * 0.5, ty - uy * s * 0.5
        back_x, back_y = tx - ux * s, ty - uy * s
        left = [mid_x + px * s * 0.3, mid_y + py * s * 0.3]
        right = [mid_x - px * s * 0.3, mid_y - py * s * 0.3]
        return (f'<polygon fill="{color}" points='
                f'"{tx:.2f},{ty:.2f} {left[0]:.2f},{left[1]:.2f} '
                f'{back_x:.2f},{back_y:.2f} {right[0]:.2f},{right[1]:.2f}"/>')

    elif arrow_type == "odiamond":
        # Open diamond
        mid_x, mid_y = tx - ux * s * 0.5, ty - uy * s * 0.5
        back_x, back_y = tx - ux * s, ty - uy * s
        left = [mid_x + px * s * 0.3, mid_y + py * s * 0.3]
        right = [mid_x - px * s * 0.3, mid_y - py * s * 0.3]
        return (f'<polygon fill="white" stroke="{color}" points='
                f'"{tx:.2f},{ty:.2f} {left[0]:.2f},{left[1]:.2f} '
                f'{back_x:.2f},{back_y:.2f} {right[0]:.2f},{right[1]:.2f}"/>')

    elif arrow_type == "vee":
        # Open V shape (no fill)
        left = [tx - ux * s + px * s * 0.4, ty - uy * s + py * s * 0.4]
        right = [tx - ux * s - px * s * 0.4, ty - uy * s - py * s * 0.4]
        return (f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
                f'points="{left[0]:.2f},{left[1]:.2f} {tx:.2f},{ty:.2f} '
                f'{right[0]:.2f},{right[1]:.2f}"/>')

    elif arrow_type == "crow":
        # Crow's foot (three prongs)
        back_x, back_y = tx - ux * s, ty - uy * s
        left = [back_x + px * s * 0.5, back_y + py * s * 0.5]
        right = [back_x - px * s * 0.5, back_y - py * s * 0.5]
        return (f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
                f'points="{left[0]:.2f},{left[1]:.2f} {tx:.2f},{ty:.2f} '
                f'{right[0]:.2f},{right[1]:.2f}"/>'
                f'<line x1="{back_x:.2f}" y1="{back_y:.2f}" '
                f'x2="{tx:.2f}" y2="{ty:.2f}" stroke="{color}" stroke-width="1.5"/>')

    elif arrow_type == "tee":
        # T-shape perpendicular bar
        left = [tx + px * s * 0.4, ty + py * s * 0.4]
        right = [tx - px * s * 0.4, ty - py * s * 0.4]
        return (f'<line x1="{left[0]:.2f}" y1="{left[1]:.2f}" '
                f'x2="{right[0]:.2f}" y2="{right[1]:.2f}" '
                f'stroke="{color}" stroke-width="2"/>')

    elif arrow_type == "box":
        # Small filled square
        cx, cy = tx - ux * s * 0.5, ty - uy * s * 0.5
        hs = s * 0.3
        p1 = [cx - ux * hs + px * hs, cy - uy * hs + py * hs]
        p2 = [cx + ux * hs + px * hs, cy + uy * hs + py * hs]
        p3 = [cx + ux * hs - px * hs, cy + uy * hs - py * hs]
        p4 = [cx - ux * hs - px * hs, cy - uy * hs - py * hs]
        return (f'<polygon fill="{color}" points='
                f'"{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} '
                f'{p3[0]:.2f},{p3[1]:.2f} {p4[0]:.2f},{p4[1]:.2f}"/>')

    elif arrow_type == "obox":
        # Open square
        cx, cy = tx - ux * s * 0.5, ty - uy * s * 0.5
        hs = s * 0.3
        p1 = [cx - ux * hs + px * hs, cy - uy * hs + py * hs]
        p2 = [cx + ux * hs + px * hs, cy + uy * hs + py * hs]
        p3 = [cx + ux * hs - px * hs, cy + uy * hs - py * hs]
        p4 = [cx - ux * hs - px * hs, cy - uy * hs - py * hs]
        return (f'<polygon fill="white" stroke="{color}" points='
                f'"{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} '
                f'{p3[0]:.2f},{p3[1]:.2f} {p4[0]:.2f},{p4[1]:.2f}"/>')

    else:
        # Fallback: normal triangle for unknown types
        left = [tx - ux * s + px * s * 0.4, ty - uy * s + py * s * 0.4]
        right = [tx - ux * s - px * s * 0.4, ty - uy * s - py * s * 0.4]
        return (f'<polygon fill="{color}" points='
                f'"{tx:.2f},{ty:.2f} {left[0]:.2f},{left[1]:.2f} '
                f'{right[0]:.2f},{right[1]:.2f}"/>')
