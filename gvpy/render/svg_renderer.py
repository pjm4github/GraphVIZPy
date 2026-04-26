"""
SVG renderer for dot layout results.

Converts the JSON layout dict produced by DotLayout.layout() into SVG markup.
Supports node shapes, colors, fill styles, fonts, edge colors, and styles.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Union
from xml.sax.saxutils import escape


_SVG_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<svg width="{w}pt" height="{h}pt" viewBox="{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}"
     xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink">
<style type="text/css"><![CDATA[
a {{ cursor: pointer; }}
a text, a tspan {{ text-decoration: underline; }}
]]></style>
<g id="graph0" class="graph"{zoom_attr}>
<title>{title}</title>
"""

# Default colour applied to text inside an ``<a xlink:href>`` wrapper
# when the author didn't set an explicit ``<FONT COLOR="…">``.  Matches
# common browser / editor conventions for hyperlinks.  The `<style>`
# block above contributes the underline via ``text-decoration``
# inheritance; this constant provides the colour via the HTML-label
# renderer passing it down as ``default_color`` for any cell with
# ``HREF``.
_LINK_COLOR = "#0066cc"

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


# ── HTML label rendering ────────────────────────────────────────────


# Margin between an edge label's visual bottom and the edge it sits
# on.  Matches C's ``lib/common/labels.c`` placement — labels float a
# few points above the edge so the stroke doesn't cut through text.
_EDGE_LABEL_MARGIN = 3.0

# Corner radius applied when STYLE="rounded" is set on a TABLE or TD.
_HTML_ROUNDED_R = 4.0

# Global gradient counter — reset at the start of each ``render_svg``
# call so IDs stay stable across identical inputs while remaining
# unique across nodes within a single SVG document.
_GRADIENT_COUNTER: list[int] = [0]


def _next_gradient_id() -> str:
    gid = f"gvpyg{_GRADIENT_COUNTER[0]}"
    _GRADIENT_COUNTER[0] += 1
    return gid


def _apply_imagepath(raw: str) -> None:
    """Parse a graph-level ``imagepath`` attribute and hand it to the
    HTML-label image probe.

    Accepts Windows (``;``) or Unix (``:``) separators; empty tokens
    are dropped.  ``"."`` is always included at the front so CWD
    resolves without the user having to list it explicitly — matches
    C ``lib/common/usershape.c``'s search order.
    """
    from gvpy.grammar.html_label import set_image_search_paths
    parts = [p.strip() for p in re.split(r"[;:]", raw or "") if p.strip()]
    set_image_search_paths(["."] + parts)


def _parse_bgcolor_pair(bg: str | None) -> tuple[str | None, str | None]:
    """Split a Graphviz-style ``c1:c2`` colour pair.

    Returns ``(c1, c2)`` when ``bg`` contains a colon, otherwise
    ``(bg, None)``.  Empty strings are normalised to ``None``.
    """
    if not bg:
        return None, None
    if ":" in bg:
        a, b = bg.split(":", 1)
        return (a.strip() or None), (b.strip() or None)
    return bg, None


def _gradient_def(gid: str, c1: str, c2: str, style: str,
                  angle: float) -> str:
    """Build a ``<linearGradient>`` or ``<radialGradient>`` ``<defs>``.

    ``style == "radial"`` emits a radial gradient centered on the shape
    (approximated by bounding-box coordinates 0..1).  Any other style
    emits a linear gradient along ``angle`` degrees, measured
    counter-clockwise from the positive X axis (matches Graphviz's
    GRADIENTANGLE convention).
    """
    if style == "radial":
        return (f'<radialGradient id="{gid}" cx="0.5" cy="0.5" r="0.5">'
                f'<stop offset="0%" stop-color="{c1}"/>'
                f'<stop offset="100%" stop-color="{c2}"/>'
                f'</radialGradient>')
    a = math.radians(angle)
    x1 = 0.5 - 0.5 * math.cos(a)
    y1 = 0.5 + 0.5 * math.sin(a)
    x2 = 0.5 + 0.5 * math.cos(a)
    y2 = 0.5 - 0.5 * math.sin(a)
    return (f'<linearGradient id="{gid}" '
            f'x1="{x1:.3f}" y1="{y1:.3f}" '
            f'x2="{x2:.3f}" y2="{y2:.3f}">'
            f'<stop offset="0%" stop-color="{c1}"/>'
            f'<stop offset="100%" stop-color="{c2}"/>'
            f'</linearGradient>')


def _resolve_fill(bgcolor: str | None, style: str | None,
                  gradientangle: float,
                  ctx: dict) -> tuple[str, str | None]:
    """Return ``(fill_attr_value, gradient_defs_str_or_None)``.

    Plain colour: returns the colour, no defs.  Colon-pair or
    ``style in {"radial"}`` with a single colour: fabricates a
    gradient and registers it in ``ctx["defs"]`` via a unique id.
    """
    if not bgcolor:
        return "none", None
    c1, c2 = _parse_bgcolor_pair(bgcolor)
    is_gradient = (style == "radial") or (c2 is not None)
    if not is_gradient:
        return c1 or "none", None
    if c2 is None:
        # STYLE="radial" with a single colour — fade to white.
        c2 = "white"
    gid = _next_gradient_id()
    return f"url(#{gid})", _gradient_def(gid, c1, c2, style or "", gradientangle)


def _render_cell_rect(cx0: float, cy0: float, w: float, h: float,
                      sides: str, rounded: bool, fill: str,
                      stroke: str, stroke_width: float) -> str:
    """Emit the cell background + border geometry.

    When ``sides == "LTRB"`` (all four borders) we emit a single
    ``<rect>``; otherwise the rect has ``stroke="none"`` (for fill
    only) and each border segment present in ``sides`` is emitted as
    its own ``<line>``.  ``rounded`` only applies to the full-rect
    case — partial borders don't attempt rounded corners.
    """
    # Emit integral stroke widths as ints (``stroke-width="3"`` not
    # ``"3.0"``) — some downstream test assertions compare literals.
    if stroke_width == int(stroke_width):
        sw_attr = f' stroke-width="{int(stroke_width)}"'
    else:
        sw_attr = f' stroke-width="{stroke_width}"'
    rx_attr = (f' rx="{_HTML_ROUNDED_R}" ry="{_HTML_ROUNDED_R}"'
               if rounded else "")
    if stroke_width <= 0:
        stroke = "none"
    full = (sides == "LTRB") or not sides
    if full:
        return (f'<rect x="{cx0:.2f}" y="{cy0:.2f}" '
                f'width="{w:.2f}" height="{h:.2f}"{rx_attr} '
                f'fill="{fill}" stroke="{stroke}"{sw_attr}/>')
    # Partial sides: fill rect with no stroke + per-side lines.
    out = [
        f'<rect x="{cx0:.2f}" y="{cy0:.2f}" '
        f'width="{w:.2f}" height="{h:.2f}" '
        f'fill="{fill}" stroke="none"/>'
    ]
    if stroke == "none" or stroke_width <= 0:
        return out[0]
    x1, y1, x2, y2 = cx0, cy0, cx0 + w, cy0 + h
    seg_attrs = f'stroke="{stroke}"{sw_attr}'
    if "T" in sides:
        out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" '
                   f'x2="{x2:.2f}" y2="{y1:.2f}" {seg_attrs}/>')
    if "B" in sides:
        out.append(f'<line x1="{x1:.2f}" y1="{y2:.2f}" '
                   f'x2="{x2:.2f}" y2="{y2:.2f}" {seg_attrs}/>')
    if "L" in sides:
        out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" '
                   f'x2="{x1:.2f}" y2="{y2:.2f}" {seg_attrs}/>')
    if "R" in sides:
        out.append(f'<line x1="{x2:.2f}" y1="{y1:.2f}" '
                   f'x2="{x2:.2f}" y2="{y2:.2f}" {seg_attrs}/>')
    return "".join(out)


def _wrap_link_title_id(body: str, href: str | None, target: str | None,
                         title: str | None, element_id: str | None) -> str:
    """Wrap ``body`` in the interactive-attribute envelope used by
    HTML-label TABLE / TD.

    Adds, in order (innermost to outermost):

    1. A ``<title>`` child when ``title`` is set.  Graphviz treats
       ``TITLE`` and ``TOOLTIP`` as aliases for the same hover hint.
    2. An ``<a xlink:href="…" target="…">`` wrapper when ``href`` is
       set.  ``target`` only applies when ``href`` is present.
    3. A ``<g id="…">`` wrapper when ``element_id`` is set so the
       id propagates even without a hyperlink.
    """
    out = body
    if title:
        out = f'<title>{escape(title)}</title>' + out
    if href:
        target_attr = (f' target="{escape(target)}"'
                       if target else "")
        out = (f'<a xlink:href="{escape(href)}"{target_attr}>'
               + out + "</a>")
    if element_id:
        out = f'<g id="{escape(element_id)}">' + out + "</g>"
    return out


def _render_image(img, inner_x: float, inner_y: float,
                   inner_w: float, inner_h: float) -> str:
    """Emit an SVG ``<image>`` element sized per Graphviz's SCALE mode.

    - ``false`` (default) — use the image's natural pixel size,
      centred in the cell's inner area.
    - ``true`` — scale preserving aspect ratio to fit the cell.
    - ``both`` — stretch to fill the cell (no aspect ratio).
    - ``width`` — scale so width fills the cell; height proportional.
    - ``height`` — scale so height fills the cell; width proportional.
    """
    scale = (img.scale or "false").lower()
    src_attr = f'xlink:href="{escape(img.src)}"'
    nw = img.natural_w
    nh = img.natural_h
    if scale == "both":
        return (f'<image x="{inner_x:.2f}" y="{inner_y:.2f}" '
                f'width="{inner_w:.2f}" height="{inner_h:.2f}" '
                f'preserveAspectRatio="none" {src_attr}/>')
    if scale == "true":
        return (f'<image x="{inner_x:.2f}" y="{inner_y:.2f}" '
                f'width="{inner_w:.2f}" height="{inner_h:.2f}" '
                f'preserveAspectRatio="xMidYMid meet" {src_attr}/>')
    if scale == "width":
        # Fit width to the cell; scale height proportionally.  If the
        # proportional height would exceed the cell's inner height,
        # fall back to fitting the height instead (preserves aspect
        # ratio and guarantees the image never spills past the cell
        # bounds — matches dot.exe's behaviour on cells whose aspect
        # ratio forces the chosen axis to overflow).
        if nw > 0 and nh > 0:
            ratio = inner_w / nw
            if nh * ratio > inner_h:
                ratio = inner_h / nh
            sw = nw * ratio
            sh = nh * ratio
        else:
            sw, sh = inner_w, inner_h
        x = inner_x + (inner_w - sw) / 2
        y = inner_y + (inner_h - sh) / 2
        return (f'<image x="{x:.2f}" y="{y:.2f}" '
                f'width="{sw:.2f}" height="{sh:.2f}" '
                f'{src_attr}/>')
    if scale == "height":
        # Symmetric to the width branch.
        if nw > 0 and nh > 0:
            ratio = inner_h / nh
            if nw * ratio > inner_w:
                ratio = inner_w / nw
            sw = nw * ratio
            sh = nh * ratio
        else:
            sw, sh = inner_w, inner_h
        x = inner_x + (inner_w - sw) / 2
        y = inner_y + (inner_h - sh) / 2
        return (f'<image x="{x:.2f}" y="{y:.2f}" '
                f'width="{sw:.2f}" height="{sh:.2f}" '
                f'{src_attr}/>')
    # scale == "false": use natural size, centre in cell.
    use_w = nw if nw > 0 else inner_w
    use_h = nh if nh > 0 else inner_h
    x = inner_x + (inner_w - use_w) / 2
    y = inner_y + (inner_h - use_h) / 2
    return (f'<image x="{x:.2f}" y="{y:.2f}" '
            f'width="{use_w:.2f}" height="{use_h:.2f}" '
            f'{src_attr}/>')


def _render_html_table(tbl, origin_x: float, origin_y: float,
                       default_face: str, default_size: float,
                       default_color: str | None,
                       _gradient_ctx: dict | None = None) -> str:
    """Render a parsed :class:`HtmlTable` as SVG.

    ``origin_x``, ``origin_y`` are the top-left corner of the outer
    border in absolute SVG coordinates.  The table's cells are already
    placed at (cell.x, cell.y) relative to that origin by
    :func:`html_label.size_html_table`.

    Output order:

    1. Outer ``<rect>`` for the table bgcolor + outermost border.
    2. For each cell: a ``<rect>`` for the cell background / cell
       border (when CELLBORDER / per-cell BORDER > 0).
    3. For each cell: its text runs via :func:`_render_cell_paragraph`,
       OR a recursively-rendered nested table.

    Gradient fills produced by ``STYLE="radial"`` or ``BGCOLOR="c1:c2"``
    share a single ``<defs>`` block prepended at the outermost call —
    nested-table recursion threads a ``_gradient_ctx`` dict so all
    gradient definitions collect into one place.
    """
    is_root = _gradient_ctx is None
    if is_root:
        _gradient_ctx = {"defs": []}

    # Table-level HREF: cells inherit the link colour by default so
    # anchor-wrapped text shows as blue without needing every author
    # to wrap content in ``<FONT COLOR="#0066cc">``.  Cell-level HREF
    # overrides per-cell below.  Explicit ``<FONT COLOR>`` inside the
    # cell still wins — we only override the cell's default.
    eff_default_color = (_LINK_COLOR if tbl.href else default_color)

    parts: list[str] = []

    # Outer frame: fill + border.
    tw, th = tbl.width, tbl.height
    t_fill, t_grad = _resolve_fill(
        tbl.bgcolor, tbl.style, tbl.gradientangle, _gradient_ctx)
    if t_grad:
        _gradient_ctx["defs"].append(t_grad)
    t_stroke = tbl.color or "black"
    t_rounded = (tbl.style == "rounded")
    t_sides = tbl.sides or "LTRB"
    if tbl.border > 0 or tbl.bgcolor:
        parts.append(_render_cell_rect(
            origin_x, origin_y, tw, th,
            sides=t_sides, rounded=t_rounded,
            fill=t_fill,
            stroke=t_stroke if tbl.border > 0 else "none",
            stroke_width=float(tbl.border) if tbl.border > 0 else 0.0,
        ))

    # Cells.
    for row in tbl.rows:
        for cell in row.cells:
            cx0 = origin_x + cell.x
            cy0 = origin_y + cell.y
            # Cell fill + border.  Per-cell border override falls back
            # to the table's CELLBORDER.
            cb = cell.border if cell.border is not None else tbl.cellborder
            c_fill, c_grad = _resolve_fill(
                cell.bgcolor, cell.style, cell.gradientangle, _gradient_ctx)
            if c_grad:
                _gradient_ctx["defs"].append(c_grad)
            c_stroke = cell.color or tbl.color or "black"
            c_rounded = (cell.style == "rounded")
            # Collect this cell's rendered parts into a local buffer so
            # we can wrap them in the interactive-attribute envelope
            # (<a xlink:href>, <title>, <g id="">) as a unit.
            cell_buf: list[str] = []
            if cb > 0 or cell.bgcolor:
                cell_buf.append(_render_cell_rect(
                    cx0, cy0, cell.width, cell.height,
                    sides=cell.sides, rounded=c_rounded,
                    fill=c_fill,
                    stroke=c_stroke if cb > 0 else "none",
                    stroke_width=float(cb) if cb > 0 else 0.0,
                ))

            # Cell content.
            pad = (cell.cellpadding if cell.cellpadding is not None
                   else tbl.cellpadding)
            # Cell-level HREF promotes the default text color to link
            # blue; falls back to the table-level default computed
            # above (which honours table-level HREF).
            cell_default_color = (
                _LINK_COLOR if cell.href else eff_default_color)
            from gvpy.grammar.html_label import _cell_is_mixed
            if _cell_is_mixed(cell):
                cell_buf.append(_render_cell_mixed(
                    cell, cx0, cy0, pad,
                    default_face=default_face,
                    default_size=default_size,
                    default_color=cell_default_color,
                    _gradient_ctx=_gradient_ctx,
                ))
            elif cell.image is not None:
                cell_buf.append(_render_image(
                    cell.image,
                    cx0 + pad, cy0 + pad,
                    cell.width - 2 * pad, cell.height - 2 * pad,
                ))
            elif cell.nested is not None:
                # Nested tables: centre in the cell's inner area.
                inner_x = cx0 + pad + (cell.width - 2 * pad - cell.nested.width) / 2
                inner_y = cy0 + pad + (cell.height - 2 * pad - cell.nested.height) / 2
                cell_buf.append(_render_html_table(
                    cell.nested, inner_x, inner_y,
                    default_face=default_face,
                    default_size=default_size,
                    default_color=cell_default_color,
                    _gradient_ctx=_gradient_ctx,
                ))
            elif cell.lines:
                cell_buf.append(_render_cell_paragraph(
                    cell, cx0, cy0, pad,
                    default_face=default_face,
                    default_size=default_size,
                    default_color=cell_default_color,
                ))
            parts.append(_wrap_link_title_id(
                "".join(cell_buf),
                cell.href, cell.target, cell.title, cell.element_id,
            ))
    # ── Rules: VR between cells, HR between rows ────────────────────
    # Per-cell ``vr_after`` or table-level ``columns_rule`` triggers
    # a vertical rule centred in the cellspacing gap at the cell's
    # right edge.  Per-row ``hr_before`` or ``rows_rule`` triggers a
    # horizontal rule above the row, stroked from the left outer
    # border to the right.  Skipped for the first row (nothing
    # above) regardless of flags.
    s = tbl.cellspacing
    rule_stroke = tbl.color or "black"
    for row in tbl.rows:
        if not row.cells:
            continue
        last_cell = row.cells[-1]
        for cell in row.cells:
            is_last = (cell is last_cell)
            draw_vr = cell.vr_after or (
                tbl.columns_rule and not is_last)
            if not draw_vr:
                continue
            vx = origin_x + cell.x + cell.width + s / 2.0
            y1 = origin_y + cell.y
            y2 = y1 + cell.height
            parts.append(
                f'<line x1="{vx:.2f}" y1="{y1:.2f}" '
                f'x2="{vx:.2f}" y2="{y2:.2f}" '
                f'stroke="{rule_stroke}" stroke-width="1"/>'
            )
    if tbl.row_y:
        hr_x1 = origin_x + tbl.border
        hr_x2 = origin_x + tbl.width - tbl.border
        for i in range(1, len(tbl.rows)):
            row = tbl.rows[i]
            draw_hr = row.hr_before or tbl.rows_rule
            if not draw_hr:
                continue
            hy = origin_y + tbl.row_y[i] - s / 2.0
            parts.append(
                f'<line x1="{hr_x1:.2f}" y1="{hy:.2f}" '
                f'x2="{hr_x2:.2f}" y2="{hy:.2f}" '
                f'stroke="{rule_stroke}" stroke-width="1"/>'
            )

    body = "".join(parts)
    body = _wrap_link_title_id(
        body, tbl.href, tbl.target, tbl.title, tbl.element_id)
    if is_root and _gradient_ctx["defs"]:
        return "<defs>" + "".join(_gradient_ctx["defs"]) + "</defs>" + body
    return body


def _render_cell_mixed(cell, cx0: float, cy0: float, pad: float,
                        default_face: str, default_size: float,
                        default_color: str | None,
                        _gradient_ctx: dict) -> str:
    """Render a cell whose ``blocks`` list mixes paragraphs with
    nested tables and/or images.

    Blocks stack vertically from the top of the cell's inner area.
    Each paragraph fragment renders with its own in-line valign/align
    logic inside a ``(block_w, block_h)`` sub-rectangle; nested
    tables render centred horizontally; images honour SCALE.  We
    skip cell-level VALIGN for mixed cells — matches Graphviz's
    behaviour where mixed content is always top-anchored.
    """
    from gvpy.grammar.html_label import (
        _iter_paragraph_groups, _paragraph_size, size_html_table,
    )

    inner_w = cell.width - 2 * pad
    cursor_y = cy0 + pad
    parts: list[str] = []

    for kind, obj in _iter_paragraph_groups(cell.blocks):
        if kind == "paragraph":
            lines: list = obj  # type: ignore[assignment]
            _, h = _paragraph_size(lines, 1.2)
            # Build a lightweight fragment cell so we can reuse
            # ``_render_cell_paragraph``'s line-walking logic with
            # this paragraph's lines only, placed at cursor_y.
            class _Frag:
                pass
            frag = _Frag()
            frag.lines = lines
            frag.width = cell.width
            frag.height = h + 2 * pad
            frag.align = cell.align
            frag.valign = "top"
            parts.append(_render_cell_paragraph(
                frag, cx0, cursor_y - pad, pad,
                default_face=default_face,
                default_size=default_size,
                default_color=default_color,
            ))
            cursor_y += h
        elif kind == "table":
            sub = obj  # type: ignore[assignment]
            size_html_table(sub)
            # Centre horizontally within the cell's inner width.
            inner_x = cx0 + pad + (inner_w - sub.width) / 2
            parts.append(_render_html_table(
                sub, inner_x, cursor_y,
                default_face=default_face,
                default_size=default_size,
                default_color=default_color,
                _gradient_ctx=_gradient_ctx,
            ))
            cursor_y += sub.height
        elif kind == "image":
            img = obj  # type: ignore[assignment]
            from gvpy.grammar.html_label import _image_natural_size
            iw, ih = _image_natural_size(img)
            # Fit image into the cell's inner width while keeping
            # aspect; stack below previous block.
            scale_ratio = (inner_w / iw) if iw > 0 and iw > inner_w else 1.0
            draw_w = iw * scale_ratio
            draw_h = ih * scale_ratio
            inner_x = cx0 + pad + (inner_w - draw_w) / 2
            parts.append(_render_image(
                img, inner_x, cursor_y, draw_w, draw_h,
            ))
            cursor_y += draw_h
    return "".join(parts)


def _render_cell_paragraph(cell, cx0: float, cy0: float, pad: float,
                            default_face: str, default_size: float,
                            default_color: str | None) -> str:
    """Render the text content of one :class:`TableCell` as a mix of
    ``<text>`` and ``<line>`` elements.

    Horizontal placement per line follows ``line.align`` when explicitly
    set (via ``<BR ALIGN="…"/>`` or cell ``BALIGN``); otherwise the
    cell-wide ``ALIGN`` governs.  Vertical placement follows
    ``VALIGN`` (top / middle / bottom).  ``<HR/>`` lines render as a
    thin horizontal rule spanning the cell's inner width.
    """
    from gvpy.grammar.html_label import _paragraph_size

    _, content_h = _paragraph_size(cell.lines, 1.2)

    # Per-line heights.  HR lines have a fixed stored height; text
    # lines scale with the tallest run's font size.
    line_heights: list[float] = []
    for line in cell.lines:
        if line.is_hr:
            line_heights.append(line.height)
        elif not line.runs:
            line_heights.append(default_size * 1.2)
        else:
            line_heights.append(max(r.font_size for r in line.runs) * 1.2)

    # ``strip_y`` [i] = top of line i's vertical strip (before any
    # ascent shift for baseline).
    if cell.valign == "top":
        strip0 = cy0 + pad
    elif cell.valign == "bottom":
        strip0 = cy0 + cell.height - pad - content_h
    else:  # middle
        strip0 = cy0 + (cell.height - content_h) / 2

    # Resolve each line's anchor x + text-anchor.  The cell-wide
    # ALIGN governs lines whose own align is ``center`` (the
    # implicit default) EXCEPT when cell.align is ``text``, which
    # tells the renderer "preserve each line's own alignment"
    # (i.e. don't override center).  Per-line alignment from
    # ``<BR ALIGN=…/>`` / BALIGN always wins over cell.align.
    cell_block_align = (cell.align or "center").lower()

    def _align_x(line_align: str) -> tuple[float, str]:
        if cell_block_align == "text":
            eff = (line_align or "center").lower()
        else:
            eff = (line_align if line_align != "center"
                   else cell_block_align)
            eff = (eff or "center").lower()
        if eff == "left":
            return cx0 + pad, "start"
        if eff == "right":
            return cx0 + cell.width - pad, "end"
        # center / unknown → centre
        return cx0 + cell.width / 2.0, "middle"

    out: list[str] = []
    cursor_y = strip0
    for i, line in enumerate(cell.lines):
        lh = line_heights[i]
        if line.is_hr:
            x1 = cx0 + pad
            x2 = cx0 + cell.width - pad
            y = cursor_y + lh / 2.0
            out.append(
                f'<line x1="{x1:.2f}" y1="{y:.2f}" '
                f'x2="{x2:.2f}" y2="{y:.2f}" '
                f'stroke="{default_color or "black"}" stroke-width="1"/>'
            )
            cursor_y += lh
            continue

        if not line.runs:
            cursor_y += lh
            continue

        line_font = max(r.font_size for r in line.runs)
        baseline_y = cursor_y + line_font * 0.85
        line_x, line_anchor = _align_x(line.align)

        root = [
            f'<text text-anchor="{line_anchor}"',
            f' font-family="{default_face}"',
            f' font-size="{default_size}"',
        ]
        if default_color:
            root.append(f' fill="{default_color}"')
        root.append(">")
        out.append("".join(root))
        for j, run in enumerate(line.runs):
            tattrs: list[str] = []
            if j == 0:
                tattrs.append(f'x="{line_x:.2f}"')
                tattrs.append(f'y="{baseline_y:.2f}"')
            if run.font_size != default_size:
                tattrs.append(f'font-size="{run.font_size}"')
            if run.color and run.color != default_color:
                tattrs.append(f'fill="{run.color}"')
            if run.face and run.face != default_face:
                tattrs.append(f'font-family="{run.face}"')
            if run.bold:
                tattrs.append('font-weight="bold"')
            if run.italic:
                tattrs.append('font-style="italic"')
            deco: list[str] = []
            if run.underline:
                deco.append("underline")
            if run.overline:
                deco.append("overline")
            if run.strike:
                deco.append("line-through")
            if deco:
                tattrs.append(f'text-decoration="{" ".join(deco)}"')
            if run.sub:
                tattrs.append('baseline-shift="sub"')
            elif run.sup:
                tattrs.append('baseline-shift="super"')
            text = escape(run.text)
            out.append(
                f'<tspan {" ".join(tattrs)}>{text}</tspan>'
                if tattrs else f'<tspan>{text}</tspan>'
            )
        out.append("</text>")
        cursor_y += lh

    return "".join(out)


def _render_html_text(cx: float, cy: float, raw_label: str,
                      default_face: str, default_size: float,
                      default_color: str | None,
                      anchor: str = "middle",
                      italic: bool = False,
                      bottom_above_y: float | None = None) -> str:
    """Render a Graphviz HTML-like label as SVG.

    Parses the label; if the label body is a ``<TABLE>`` the output is
    a group of ``<rect>`` + ``<text>`` elements laid out as a grid
    (see :func:`_render_html_table`).  Otherwise it's a single
    ``<text>`` with per-run ``<tspan>`` children (see the branch
    below).

    Position modes:

    - Default: ``cy`` is the label's visual vertical centre.  Used for
      node labels, cluster labels, xlabels.
    - ``bottom_above_y`` set: the label's visual BOTTOM is placed
      ``_EDGE_LABEL_MARGIN`` points above ``bottom_above_y``, ``cy`` is
      ignored.  Used for edge labels so the label floats just above
      the edge stroke.

    Per-line alignment (``<BR ALIGN="LEFT|CENTER|RIGHT"/>``) emits
    ``text-anchor`` + ``x=`` on each line's first ``<tspan>`` so
    LEFT / RIGHT lines actually anchor to the label's left / right
    edge rather than falling back to the root text-anchor.
    """
    from gvpy.grammar.html_label import parse_html_label, html_label_size

    ast = parse_html_label(
        raw_label,
        default_font_size=default_size,
        default_color=default_color,
        default_face=default_face,
    )

    # Table-labeled path: dispatch to the grid renderer.
    if ast.table is not None:
        # Compute table size + cell placements (fills cell.x/.y/.w/.h).
        from gvpy.grammar.html_label import size_html_table
        size_html_table(ast.table)
        tw, th = ast.table.width, ast.table.height
        if bottom_above_y is not None:
            origin_x = cx - tw / 2.0
            origin_y = bottom_above_y - _EDGE_LABEL_MARGIN - th
        else:
            origin_x = cx - tw / 2.0
            origin_y = cy - th / 2.0
        return _render_html_table(
            ast.table, origin_x, origin_y,
            default_face=default_face,
            default_size=default_size,
            default_color=default_color,
        )

    # Per-line height = max(run.font_size) × 1.2; empty lines
    # (``<BR/><BR/>``) still contribute the default line height.
    line_heights: list[float] = []
    for line in ast.lines:
        if not line.runs:
            line_heights.append(default_size * 1.2)
        else:
            line_heights.append(max(run.font_size for run in line.runs) * 1.2)
    total_h = sum(line_heights)
    # Total label width (max of line widths) — needed for per-line
    # LEFT / RIGHT alignment x positions.
    label_w, _ = html_label_size(ast)

    first_runs = next((l.runs for l in ast.lines if l.runs), None)
    first_font = first_runs[0].font_size if first_runs else default_size

    if bottom_above_y is not None:
        # Edge-label mode: position LAST visible line's baseline so
        # the descent sits ``_EDGE_LABEL_MARGIN`` above ``bottom_above_y``.
        # Previous centre-based formula over-estimated total_h because
        # the 1.2 line-height factor includes leading, not actual
        # descent — on the mixed-size ``sMs`` label (max=18) this put
        # the visual bottom ~12 pt above the edge instead of 3 pt.
        last_visible_runs = None
        for line in reversed(ast.lines):
            if line.runs:
                last_visible_runs = line.runs
                break
        last_font = (max(r.font_size for r in last_visible_runs)
                     if last_visible_runs else default_size)
        last_descent = last_font * 0.2  # Times-Roman descent ≈ 0.2 × em
        visible_heights = [
            lh for lh, line in zip(line_heights, ast.lines) if line.runs
        ]
        dy_total = sum(visible_heights[1:])  # lines 2..N dy advance
        last_baseline_y = (bottom_above_y - _EDGE_LABEL_MARGIN
                           - last_descent)
        first_baseline_y = last_baseline_y - dy_total
    else:
        first_baseline_y = cy - total_h / 2 + first_font * 0.85

    root_attrs = [
        f'text-anchor="{anchor}"',
        f'font-family="{default_face}"',
        f'font-size="{default_size}"',
    ]
    if default_color:
        root_attrs.append(f'fill="{default_color}"')
    if italic:
        root_attrs.append('font-style="italic"')
    out = [f'<text {" ".join(root_attrs)}>']

    emitted_first_line = False
    for i, line in enumerate(ast.lines):
        if not line.runs:
            continue
        # Per-line anchor + x based on line.align.  ``<BR ALIGN=…/>``
        # sets this on the line following the break; the first line
        # inherits the label's default alignment (middle).
        line_align = (line.align or "center").lower()
        if line_align == "left":
            line_x = cx - label_w / 2
            line_anchor_attr = 'text-anchor="start"'
        elif line_align == "right":
            line_x = cx + label_w / 2
            line_anchor_attr = 'text-anchor="end"'
        else:
            line_x = cx
            # Inherit middle from root — no attribute needed.
            line_anchor_attr = ""

        for j, run in enumerate(line.runs):
            tattrs: list[str] = []
            if j == 0:
                tattrs.append(f'x="{line_x:.2f}"')
                if not emitted_first_line:
                    tattrs.append(f'y="{first_baseline_y:.2f}"')
                    emitted_first_line = True
                else:
                    tattrs.append(f'dy="{line_heights[i]:.2f}"')
                if line_anchor_attr:
                    tattrs.append(line_anchor_attr)
            if run.font_size != default_size:
                tattrs.append(f'font-size="{run.font_size}"')
            if run.color and run.color != default_color:
                tattrs.append(f'fill="{run.color}"')
            if run.face and run.face != default_face:
                tattrs.append(f'font-family="{run.face}"')
            if run.bold:
                tattrs.append('font-weight="bold"')
            if run.italic:
                tattrs.append('font-style="italic"')
            deco: list[str] = []
            if run.underline:
                deco.append("underline")
            if run.overline:
                deco.append("overline")
            if run.strike:
                deco.append("line-through")
            if deco:
                tattrs.append(f'text-decoration="{" ".join(deco)}"')
            if run.sub:
                tattrs.append('baseline-shift="sub"')
            elif run.sup:
                tattrs.append('baseline-shift="super"')
            text = escape(run.text)
            if tattrs:
                out.append(f'<tspan {" ".join(tattrs)}>{text}</tspan>')
            else:
                out.append(f'<tspan>{text}</tspan>')
    out.append("</text>")
    return "".join(out)


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


def _fit_polygon(cx: float, cy: float, hw: float, hh: float, sides: int,
                 orientation_deg: float = 0.0,
                 fill: str = _DEF_NODE_FILL, stroke: str = _DEF_NODE_STROKE,
                 penwidth: float = 1.0) -> str:
    """Render an N-gon inscribed in the (2·hw × 2·hh) bbox.

    Mirrors C's ``lib/common/shapes.c: poly_init`` vertex generation
    (lines 2222-2290): build a unit regular polygon, then stretch so
    its horizontal extremes touch ±hw and vertical extremes touch
    ±hh.  For a squashed hexagon (w ≫ h) this produces a flat-top
    shape with pointy L/R ends — which is how C renders it — rather
    than the old ``r = max(hw, hh)`` circle-inscribed polygon which
    was always square-aspect regardless of the node's actual bbox.
    """
    sector = 2 * math.pi / sides
    side_len = math.sin(sector / 2)
    # Accumulator walks the edges of the unit polygon; matches C's
    # loop at shapes.c:2229-2241.
    a0 = (sector - math.pi) / 2
    rx = 0.5 * math.cos(a0)
    ry = 0.5 * math.sin(a0)
    angle = 0.0
    orient = math.radians(orientation_deg)
    raw: list[tuple[float, float]] = []
    for _ in range(sides):
        angle += sector
        rx += side_len * math.cos(angle)
        ry += side_len * math.sin(angle)
        # Apply orientation rotation (zero for default shapes).
        alpha = orient + math.atan2(ry, rx)
        r = math.hypot(rx, ry)
        raw.append((r * math.cos(alpha), r * math.sin(alpha)))
    xmax = max(abs(x) for x, _ in raw) or 1e-9
    ymax = max(abs(y) for _, y in raw) or 1e-9
    sx = hw / xmax
    sy = hh / ymax
    pts = " ".join(f"{cx + x*sx:.2f},{cy + y*sy:.2f}" for x, y in raw)
    return (f'<polygon points="{pts}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{penwidth}"/>')


# Back-compat alias for any external callers.
def _regular_polygon(cx: float, cy: float, r: float, n: int,
                     fill: str = _DEF_NODE_FILL, stroke: str = _DEF_NODE_STROKE,
                     penwidth: float = 1.0) -> str:
    """Deprecated: callers should use :func:`_fit_polygon` with the
    node's actual (hw, hh) so squashed bboxes render correctly."""
    return _fit_polygon(cx, cy, r, r, n, 0.0, fill, stroke, penwidth)


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

    # Gradient IDs within one render must be globally unique.  Reset
    # the module-level counter so IDs stay deterministic across runs.
    _GRADIENT_COUNTER[0] = 0

    # Install graph-level imagepath so the HTML IMG probe can find
    # relative SRCs.  Graphviz allows ``;`` (Windows) or ``:`` (Unix)
    # separators; we accept either and always include ``"."`` so CWD
    # is searched first — matches C's behaviour.
    _apply_imagepath(graph.get("imagepath", ""))

    # ── Viewport zoom (size="W,H") ─────────────────────────────
    # ``DotLayout._apply_size`` records the C-style emit-time zoom
    # factor when the graph's declared ``size`` is smaller than the
    # natural canvas.  We apply it as a single ``transform="scale(z)"``
    # on the graph0 group and scale the outer ``width``/``height``/
    # ``viewBox`` to match.  Internal coords stay in layout units so
    # text, HTML tables, and edges all scale together.
    try:
        zoom = float(graph.get("zoom", 1.0))
    except (TypeError, ValueError):
        zoom = 1.0
    if zoom != 1.0 and zoom > 0.0:
        vx_o, vy_o = vx * zoom, vy * zoom
        vw_o, vh_o = vw * zoom, vh * zoom
        zoom_attr = f' transform="scale({zoom:.6f})"'
    else:
        vx_o, vy_o, vw_o, vh_o = vx, vy, vw, vh
        zoom_attr = ""

    parts = [_SVG_HEADER.format(
        w=round(vw_o), h=round(vh_o),
        vx=vx_o, vy=vy_o, vw=vw_o, vh=vh_o,
        title=title, zoom_attr=zoom_attr,
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
        labeljust = cl.get("labeljust", "c")
        labelloc = cl.get("labelloc", "t")
        cl_margin = 8.0  # default cluster margin
        try:
            cl_margin = float(cl.get("margin", "8"))
        except (ValueError, TypeError):
            pass
        label_pad = 4.0  # extra padding between label and border

        # Vertical position: baseline y
        # The SVG text y is the baseline.  For top placement, the
        # baseline sits at  top_of_box + margin + font_ascent.
        # Approximate ascent as 0.75 * font_size.
        ascent = font_size * 0.75
        if labelloc == "b":
            ty = y + h - label_pad
        else:
            # top (default)
            ty = y + label_pad + ascent

        # Horizontal position
        if labeljust == "l":
            tx = x + cl_margin + label_pad
            anchor = "start"
        elif labeljust == "r":
            tx = x + w - cl_margin - label_pad
            anchor = "end"
        else:
            tx = x + w / 2
            anchor = "middle"

        from gvpy.grammar.html_label import is_html_label as _is_html
        raw_label = cl.get("label", "")
        if _is_html(raw_label):
            lines.append(_render_html_text(
                tx, ty, raw_label,
                default_face=font_family,
                default_size=font_size,
                default_color=font_color,
                anchor=anchor,
            ))
        else:
            lines.append(
                f'<text x="{tx:.2f}" y="{ty:.2f}" text-anchor="{anchor}" '
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


def _measure_field(field: dict, horizontal: bool,
                   font_size: float) -> float:
    """Return the natural width (if horizontal) or height of a field.

    Uses the same metrics as the layout engine's ``_measure_record_tree``
    so that the renderer's proportional sizing matches the layout's total.
    """
    char_w = font_size * 0.52
    field_pad = 8.0
    min_cell = 20.0
    cell_h = font_size * 1.4 + 4.0

    effective = not horizontal if field.get("flipped") else horizontal

    if not field.get("children"):
        text = field.get("text") or ""
        if horizontal:
            return max(len(text) * char_w + field_pad * 2, min_cell)
        else:
            return cell_h

    child_sizes = [
        _measure_field(c, effective, font_size)
        for c in field["children"]
    ]
    if effective:
        # Children are horizontal → their widths sum for the parent's width
        return sum(child_sizes) if horizontal else max(child_sizes)
    else:
        # Children are vertical → their heights sum for the parent's height
        return max(child_sizes) if horizontal else sum(child_sizes)


def _render_fields(fields: list[dict], x: float, y: float,
                   w: float, h: float, horizontal: bool,
                   stroke: str, font_family: str, font_size: float,
                   font_color: str, penwidth: float,
                   lines: list[str]):
    """Render a list of record fields within the given rectangle.

    Fields are sized proportionally to their text content rather than
    divided equally, matching the Graphviz C renderer.
    """
    n = len(fields)
    if n == 0:
        return
    sw = f' stroke-width="{penwidth}"' if penwidth != 1.0 else ""

    if horizontal:
        # Compute natural widths and scale to fill available space
        natural = [_measure_field(f, horizontal, font_size) for f in fields]
        total_nat = sum(natural)
        if total_nat > 0:
            widths = [nw / total_nat * w for nw in natural]
        else:
            widths = [w / n] * n

        cx = x
        for i, field in enumerate(fields):
            cell_w = widths[i]
            # Vertical divider between fields
            if i > 0:
                lines.append(
                    f'<line x1="{cx:.2f}" y1="{y:.2f}" '
                    f'x2="{cx:.2f}" y2="{y + h:.2f}" '
                    f'stroke="{stroke}"{sw}/>')
            if field.get("children"):
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
            cx += cell_w
    else:
        # Compute natural heights and scale to fill available space
        natural = [_measure_field(f, horizontal, font_size) for f in fields]
        total_nat = sum(natural)
        if total_nat > 0:
            heights = [nh / total_nat * h for nh in natural]
        else:
            heights = [h / n] * n

        cy = y
        for i, field in enumerate(fields):
            cell_h = heights[i]
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
            cy += cell_h


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
        # Record shape: parse label into fields, render with dividers.
        # D7 — prefer the field tree that the layout engine computed
        # via the ANTLR4 record parser (emitted as ``record_tree`` on
        # the node dict).  Falls back to the legacy in-renderer
        # string parser only when the layout didn't emit a tree
        # (e.g. a node dict produced by an older layout or an
        # upstream consumer that hand-built the dict).  Single-parser
        # consistency avoids visual/layout port-placement drift — see
        # the comment next to :func:`_record_field_to_svg_dict` in
        # ``dot_layout.py``.
        fields = node.get("record_tree")
        if fields is None:
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
        lines.append(_fit_polygon(x, y, hw, hh, 5, 0.0, fill, stroke, penwidth))
    elif shape == "hexagon":
        lines.append(_fit_polygon(x, y, hw, hh, 6, 0.0, fill, stroke, penwidth))
    elif shape in ("septagon", "heptagon"):
        lines.append(_fit_polygon(x, y, hw, hh, 7, 0.0, fill, stroke, penwidth))
    elif shape == "octagon":
        lines.append(_fit_polygon(x, y, hw, hh, 8, 0.0, fill, stroke, penwidth))
    elif shape == "doubleoctagon":
        # Inner octagon inset by 3 pt on each axis to visually nest
        # within the outer — preserves the old "max(hw,hh)-3" offset.
        lines.append(_fit_polygon(x, y, hw, hh, 8, 0.0, fill, stroke, penwidth))
        if hw > 3 and hh > 3:
            lines.append(_fit_polygon(x, y, hw - 3, hh - 3, 8, 0.0,
                                      "none", stroke, penwidth))
    elif shape == "point":
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{stroke}" stroke="{stroke}"/>')
    elif shape in ("plaintext", "plain", "none"):
        pass
    else:
        lines.append(
            f'<ellipse cx="{x:.2f}" cy="{y:.2f}" rx="{hw:.2f}" ry="{hh:.2f}" {base}/>')

    # Label (skip for record shapes — text already rendered by field renderer)
    if shape not in ("point", "record", "Mrecord"):
        raw_label = node.get("label", name)
        from gvpy.grammar.html_label import is_html_label
        if is_html_label(raw_label):
            lines.append(_render_html_text(
                x, y, raw_label,
                default_face=font_family,
                default_size=font_size,
                default_color=font_color,
                anchor="middle",
            ))
        else:
            label = escape(raw_label)
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
        from gvpy.grammar.html_label import is_html_label as _is_html
        try:
            xl_x = float(xlabel_x); xl_y = float(xlabel_y)
        except (TypeError, ValueError):
            xl_x = xl_y = None
        if _is_html(xlabel) and xl_x is not None:
            lines.append(_render_html_text(
                xl_x, xl_y, xlabel,
                default_face=font_family,
                default_size=font_size,
                default_color=font_color,
                anchor="middle",
                italic=True,
            ))
        else:
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

        from gvpy.grammar.html_label import is_html_label as _is_html
        if _is_html(label):
            # Edge labels float above the edge line: bottom sits
            # ``_EDGE_LABEL_MARGIN`` points above ``label_pos[1]``
            # (the edge crossing).  See :func:`_render_html_text`.
            label_svg = _render_html_text(
                label_pos[0], label_pos[1], label,
                default_face=font_family,
                default_size=font_size,
                default_color=font_color,
                anchor="middle",
                bottom_above_y=label_pos[1],
            )
            # html_text path doesn't carry a <title> tooltip — for now
            # the tooltip is only applied to plain labels.
        else:
            # Plain text edge label: shift baseline so the visual
            # bottom (baseline + descent ≈ 0.2·F Times-Roman) sits
            # ``_EDGE_LABEL_MARGIN`` above the edge line.
            try:
                _fs = float(font_size)
            except (ValueError, TypeError):
                _fs = _DEF_FONT_SIZE
            _baseline_y = label_pos[1] - _EDGE_LABEL_MARGIN - _fs * 0.2
            label_svg = (
                f'<text x="{label_pos[0]:.2f}" y="{_baseline_y:.2f}" '
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
