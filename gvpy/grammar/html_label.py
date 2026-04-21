"""HTML-like label parser for Graphviz DOT labels.

Graphviz accepts two label syntaxes:

- **Plain string** (``label="text"``): displayed verbatim, sized with a
  single font size / color.
- **HTML-like label** (``label=<...>``): a small, strict subset of HTML
  with inline font/size/color/weight changes and optional table layout.

The gv_visitor in :mod:`gvpy.grammar.gv_visitor` reconstructs HTML
labels as strings bracketed by ``<...>``.  Before this module, downstream
code treated those strings as literal text — tags and all — so a label
like ``<<FONT POINT-SIZE="19">b12</FONT>>`` rendered as raw text rather
than "b12" at 19pt.

This module parses the HTML body between the outer ``<...>`` into an
AST of :class:`HtmlLabel` → :class:`HtmlLine` → :class:`TextRun`, each
run carrying its resolved font size / color / face / bold / italic /
underline / strike / sub / sup attributes.  Sizing and rendering code
walks the AST to produce SVG ``<text>`` elements with ``<tspan>``
children for the style changes.

Supported tags:

- ``<FONT POINT-SIZE="N" COLOR="#..." FACE="name">…</FONT>`` — inline
  font size / color / family override.  Applies to all nested runs
  until the matching ``</FONT>``.
- ``<B>``/``<I>``/``<U>``/``<S>`` — bold / italic / underline / strike.
- ``<SUB>``/``<SUP>`` — subscript / superscript hints (rendered as
  ``baseline-shift`` in SVG).
- ``<BR ALIGN="LEFT|CENTER|RIGHT"/>`` — line break.  Align sets the
  anchor for the NEXT line; defaults to ``CENTER``.
- HTML character entities (``&lt;``, ``&gt;``, ``&amp;``, ``&quot;``,
  ``&apos;``, ``&#NN;``) are decoded by :mod:`html.parser`.
- ``<TABLE>`` / ``<TR>`` / ``<TD>`` — **not supported yet**.  Runs
  inside a TABLE are ignored; the whole label falls back to a single
  placeholder text run so the node still renders.  Tracked as Phase 4.

See C counterpart: ``lib/common/htmlparse.y`` (~530 lines) +
``lib/common/htmltable.c`` (~1900 lines).  Python's Phase 1 is
intentionally narrower — covers the tags used by real-world DOT
graphs like 2592.dot without the table-layout machinery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional


# ── AST ─────────────────────────────────────────────────────────────


@dataclass
class TextRun:
    """One run of text with a fully resolved style.

    All style attributes reflect the cumulative effect of enclosing
    ``<FONT>`` / ``<B>`` / etc. tags at the time the text appears.
    The renderer emits one ``<tspan>`` per :class:`TextRun`; the
    sizer walks the runs to compute per-line widths.
    """
    text: str
    font_size: float = 14.0
    color: Optional[str] = None
    face: Optional[str] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    sub: bool = False
    sup: bool = False


@dataclass
class HtmlLine:
    """One text line — all runs between two ``<BR/>`` tags (or the
    start/end of the label).  ``align`` is inherited from the preceding
    ``<BR ALIGN=…/>``; the first line uses ``"center"``.
    """
    runs: list[TextRun] = field(default_factory=list)
    align: str = "center"  # "left" | "center" | "right"


# ── Tables (Phase 4) ────────────────────────────────────────────────


@dataclass
class TableCell:
    """One ``<TD>…</TD>`` cell.

    A cell's content is either a list of text lines (``lines``) OR a
    nested :class:`HtmlTable` (``nested``).  Mixing text + nested
    tables in one cell is not yet supported; nested tables parse
    correctly but any sibling text is ignored.

    Attributes mirror the Graphviz TD-attribute set most graphs use.
    Sizing and placement fill in the ``width``/``height``/``x``/``y``
    fields during :func:`html_label_size`.
    """
    lines: list[HtmlLine] = field(default_factory=list)
    nested: "Optional[HtmlTable]" = None
    align: str = "center"      # ALIGN: left | center | right
    valign: str = "middle"     # VALIGN: top | middle | bottom
    bgcolor: Optional[str] = None
    color: Optional[str] = None  # cell border color override
    border: Optional[int] = None  # overrides table CELLBORDER
    cellpadding: Optional[int] = None
    cellspacing: Optional[int] = None
    colspan: int = 1   # not yet honoured in layout; parsed for forward-compat
    rowspan: int = 1
    href: Optional[str] = None
    # Computed during sizing:
    width: float = 0.0
    height: float = 0.0
    # Computed during placement (absolute within the table's coord frame):
    x: float = 0.0
    y: float = 0.0


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)
    height: float = 0.0   # computed: max cell height


@dataclass
class HtmlTable:
    """A ``<TABLE>`` element.

    Layout: cells arranged in a grid.  Column widths = max cell width
    per column.  Row heights = max cell height per row.  Total table
    size = Σ col / Σ row + (N+1) × cellspacing where N is the count
    on that axis.  COLSPAN / ROWSPAN are parsed onto the cell but
    not yet applied in layout (Phase 4 follow-up).
    """
    rows: list[TableRow] = field(default_factory=list)
    border: int = 1
    cellborder: int = 0
    cellpadding: int = 2
    cellspacing: int = 2
    bgcolor: Optional[str] = None
    color: Optional[str] = None  # border color
    align: str = "center"
    valign: str = "middle"
    href: Optional[str] = None
    # Computed during sizing:
    col_widths: list[float] = field(default_factory=list)
    row_heights: list[float] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0


@dataclass
class HtmlLabel:
    """Root of a parsed HTML-like label.

    Either ``table`` is set (the label is a table) or ``lines`` is
    used (the label is a paragraph of runs).  ``table`` takes
    precedence during sizing / rendering when both happen to be
    non-empty.
    """
    lines: list[HtmlLine] = field(default_factory=list)
    table: Optional[HtmlTable] = None

    @property
    def is_empty(self) -> bool:
        if self.table is not None and self.table.rows:
            return False
        return all(not line.runs for line in self.lines)


# ── Detection ───────────────────────────────────────────────────────


def is_html_label(label: str) -> bool:
    """Return True if ``label`` is a Graphviz HTML-like label.

    The parser wraps HTML-label strings in outer angle brackets, so
    detection is a simple check.  Plain strings never start with
    ``<`` because the visitor writes quoted strings verbatim.
    """
    return (isinstance(label, str)
            and len(label) >= 2
            and label.startswith("<")
            and label.endswith(">"))


# ── Parser ──────────────────────────────────────────────────────────


_DEFAULT_FONT_SIZE = 14.0


def parse_html_label(
    label: str,
    default_font_size: float = _DEFAULT_FONT_SIZE,
    default_color: Optional[str] = None,
    default_face: Optional[str] = None,
) -> HtmlLabel:
    """Parse a Graphviz HTML-like label into an :class:`HtmlLabel` AST.

    Parameters:
        label: The label as stored by the DOT visitor — either the
            raw HTML body or the body wrapped in outer ``<...>``.
        default_font_size: Font size for text outside any ``<FONT>``.
            Usually the node / edge / graph ``fontsize`` attribute.
        default_color: Default text color (``fontcolor``).
        default_face: Default font family (``fontname``).

    Returns an :class:`HtmlLabel` whose lines + runs carry fully
    resolved styles ready for sizing and rendering.  Tables are
    silently skipped — the TABLE body becomes ``[TABLE]`` placeholder
    text so the label still has at least one run.
    """
    body = label
    if body.startswith("<") and body.endswith(">"):
        body = body[1:-1]
    builder = _LabelBuilder(default_font_size, default_color, default_face)
    builder.feed(body)
    builder.close()
    # Drop trailing empty lines.
    while len(builder.label.lines) > 1 and not builder.label.lines[-1].runs:
        builder.label.lines.pop()
    return builder.label


def _int_attr(val: str, default: int) -> int:
    """Parse an integer-valued HTML attribute, swallowing junk."""
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


class _LabelBuilder(HTMLParser):
    """HTMLParser subclass that builds an :class:`HtmlLabel` on the fly.

    Maintains two stacks:

    - ``_style_stack`` — cumulative text style for any run emitted at
      the current point (pushed by ``<FONT>`` / ``<B>`` / etc.,
      popped by the matching close tag).
    - ``_container_stack`` — the current "text sink" where incoming
      runs + line breaks land.  Normally this is the label's
      ``lines`` list.  Inside a ``<TD>`` it becomes the cell's own
      ``lines``.  Inside ``<TABLE>`` / ``<TR>`` but outside any
      ``<TD>`` there is no active sink — stray text is ignored
      (matches Graphviz's whitespace-between-tags behaviour).

    Supports one level of nested ``<TABLE>`` inside a ``<TD>``; a
    cell's nested table is stored on ``TableCell.nested``.
    """

    def __init__(self, default_font_size: float,
                 default_color: Optional[str],
                 default_face: Optional[str]) -> None:
        # convert_charrefs=True: let html.parser decode &lt;/&gt;/&amp; etc.
        super().__init__(convert_charrefs=True)
        self.label = HtmlLabel()
        self._current_line = HtmlLine()
        self.label.lines.append(self._current_line)
        # Style stack — last entry is the active style.
        self._style_stack: list[dict] = [{
            "font_size": default_font_size,
            "color": default_color,
            "face": default_face,
            "bold": False,
            "italic": False,
            "underline": False,
            "strike": False,
            "sub": False,
            "sup": False,
        }]
        # Container stack: each entry is a dict describing where the
        # parser is currently writing:
        #   {"kind": "label"|"table"|"tr"|"td", "obj": …}
        # "label" has ``lines`` attr; "td" has ``lines`` attr.  "table"
        # and "tr" are just navigational waypoints — text while in
        # them but outside a TD is discarded.
        self._container_stack: list[dict] = [
            {"kind": "label", "obj": self.label}
        ]

    # ── Helpers ─────────────────────────────────────────────────────

    def _style(self) -> dict:
        return self._style_stack[-1]

    def _active_td(self) -> Optional[TableCell]:
        """Return the innermost open TD, or None if we aren't in one."""
        for frame in reversed(self._container_stack):
            if frame["kind"] == "td":
                return frame["obj"]
        return None

    def _active_tr(self) -> Optional[TableRow]:
        for frame in reversed(self._container_stack):
            if frame["kind"] == "tr":
                return frame["obj"]
        return None

    def _active_table(self) -> Optional[HtmlTable]:
        for frame in reversed(self._container_stack):
            if frame["kind"] == "table":
                return frame["obj"]
        return None

    def _text_sink_lines(self) -> Optional[list[HtmlLine]]:
        """Return the ``lines`` list that should receive the next run,
        or None if we're in TABLE/TR without a TD (stray text)."""
        top = self._container_stack[-1]
        if top["kind"] == "label":
            return top["obj"].lines
        if top["kind"] == "td":
            return top["obj"].lines
        return None

    def _current_sink_line(self) -> Optional[HtmlLine]:
        lines = self._text_sink_lines()
        if lines is None:
            return None
        if not lines:
            lines.append(HtmlLine())
        return lines[-1]

    # ── Tag handlers ────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_l = tag.lower()
        attrs_d = {k.lower(): (v or "") for k, v in attrs}

        if tag_l == "br":
            sink = self._text_sink_lines()
            if sink is not None:
                align = attrs_d.get("align", "").lower() or "center"
                new_line = HtmlLine(align=align)
                sink.append(new_line)
                # Update _current_line if this was the top-level label.
                top = self._container_stack[-1]
                if top["kind"] == "label":
                    self._current_line = new_line
            return

        if tag_l == "table":
            border = _int_attr(attrs_d.get("border", ""), 1)
            # CELLBORDER defaults to BORDER (Graphviz docs:
            # https://graphviz.org/doc/info/shapes.html#html — "If
            # not specified, the value of BORDER is used").  Without
            # this inheritance a default-styled TABLE rendered as
            # only the outer frame, missing the grid lines that C
            # draws between cells.
            cellborder = _int_attr(attrs_d.get("cellborder", ""), border)
            table = HtmlTable(
                border=border,
                cellborder=cellborder,
                cellpadding=_int_attr(attrs_d.get("cellpadding", ""), 2),
                cellspacing=_int_attr(attrs_d.get("cellspacing", ""), 2),
                bgcolor=attrs_d.get("bgcolor") or None,
                color=attrs_d.get("color") or None,
                align=(attrs_d.get("align") or "center").lower(),
                valign=(attrs_d.get("valign") or "middle").lower(),
                href=attrs_d.get("href") or None,
            )
            # Attach to the enclosing container.  Top-level → label.table.
            # Inside a TD → TableCell.nested.
            top = self._container_stack[-1]
            if top["kind"] == "label":
                # Label's .lines text is abandoned in favour of the
                # table; if both exist the table wins in rendering.
                self.label.table = table
            elif top["kind"] == "td":
                top["obj"].nested = table
            # else: <TABLE> inside <TR> not in <TD> is invalid — attach
            # to the first-met TD if any, otherwise ignore.
            self._container_stack.append({"kind": "table", "obj": table})
            return

        if tag_l == "tr":
            tbl = self._active_table()
            if tbl is None:
                return
            row = TableRow()
            tbl.rows.append(row)
            self._container_stack.append({"kind": "tr", "obj": row})
            return

        if tag_l == "td":
            tr = self._active_tr()
            if tr is None:
                return
            cell = TableCell(
                align=(attrs_d.get("align") or "center").lower(),
                valign=(attrs_d.get("valign") or "middle").lower(),
                bgcolor=attrs_d.get("bgcolor") or None,
                color=attrs_d.get("color") or None,
                border=_int_attr(attrs_d.get("border", ""), -1) if attrs_d.get("border") else None,
                cellpadding=_int_attr(attrs_d.get("cellpadding", ""), -1) if attrs_d.get("cellpadding") else None,
                cellspacing=_int_attr(attrs_d.get("cellspacing", ""), -1) if attrs_d.get("cellspacing") else None,
                colspan=_int_attr(attrs_d.get("colspan", ""), 1),
                rowspan=_int_attr(attrs_d.get("rowspan", ""), 1),
                href=attrs_d.get("href") or None,
            )
            tr.cells.append(cell)
            self._container_stack.append({"kind": "td", "obj": cell})
            return

        # Style tags — push onto the style stack.
        parent = self._style()
        new = dict(parent)
        if tag_l == "font":
            ps = attrs_d.get("point-size") or attrs_d.get("pointsize")
            if ps:
                try:
                    new["font_size"] = float(ps)
                except (ValueError, TypeError):
                    pass
            if "color" in attrs_d and attrs_d["color"]:
                new["color"] = attrs_d["color"]
            if "face" in attrs_d and attrs_d["face"]:
                new["face"] = attrs_d["face"]
        elif tag_l == "b":
            new["bold"] = True
        elif tag_l == "i":
            new["italic"] = True
        elif tag_l == "u":
            new["underline"] = True
        elif tag_l == "s":
            new["strike"] = True
        elif tag_l == "sub":
            new["sub"] = True
        elif tag_l == "sup":
            new["sup"] = True
        elif tag_l == "o":
            # <O> is used by some tools as overline; treat as underline.
            new["underline"] = True
        # Unknown tags: still push a matching state so the end tag
        # pops something, keeping the stack in sync.
        self._style_stack.append(new)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l == "br":
            return
        if tag_l in ("table", "tr", "td"):
            # Pop until we find the matching frame.  Normally it's the
            # top of the stack; only ill-formed input needs the walk.
            for i in range(len(self._container_stack) - 1, -1, -1):
                if self._container_stack[i]["kind"] == tag_l:
                    del self._container_stack[i:]
                    break
            return
        if len(self._style_stack) > 1:
            self._style_stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        # Self-closing tags: <BR/>, <IMG/>, etc.
        tag_l = tag.lower()
        if tag_l == "br":
            self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if not data:
            return
        line = self._current_sink_line()
        if line is None:
            # Inside <TABLE>/<TR> but not in a <TD> — stray whitespace
            # between row/cell tags.  Silently discard (matches C).
            return
        s = self._style()
        line.runs.append(TextRun(
            text=data,
            font_size=s["font_size"],
            color=s["color"],
            face=s["face"],
            bold=s["bold"],
            italic=s["italic"],
            underline=s["underline"],
            strike=s["strike"],
            sub=s["sub"],
            sup=s["sup"],
        ))


# ── Sizing ──────────────────────────────────────────────────────────


def html_label_size(lbl: HtmlLabel, line_height_factor: float = 1.2) -> tuple[float, float]:
    """Return ``(width, height)`` in points for a parsed HTML label.

    For paragraph-style labels: width = max line width
    (Σ ``text_width_times_roman(run.text, run.font_size)`` over the
    line's runs); height = Σ line heights.

    For table labels: delegates to :func:`size_html_table`, which
    computes per-column / per-row dimensions and fills in the
    ``width`` / ``height`` / ``x`` / ``y`` fields on every
    :class:`TableCell` in the tree so the renderer can lay them out
    directly.
    """
    if lbl.table is not None:
        size_html_table(lbl.table, line_height_factor=line_height_factor)
        return lbl.table.width, lbl.table.height

    return _paragraph_size(lbl.lines, line_height_factor)


def _paragraph_size(lines: list["HtmlLine"], line_height_factor: float) -> tuple[float, float]:
    """Return ``(width, height)`` in points for a list of paragraph
    lines.  Shared by the top-level label path and per-cell content."""
    from gvpy.engines.layout.common.text import text_width_times_roman
    max_w = 0.0
    total_h = 0.0
    for line in lines:
        if not line.runs:
            line_w = 0.0
            line_font = _DEFAULT_FONT_SIZE
        else:
            line_w = sum(text_width_times_roman(run.text, run.font_size)
                         for run in line.runs)
            line_font = max(run.font_size for run in line.runs)
        max_w = max(max_w, line_w)
        total_h += line_font * line_height_factor
    return max_w, total_h


def size_html_table(tbl: "HtmlTable", line_height_factor: float = 1.2) -> tuple[float, float]:
    """Size an :class:`HtmlTable` tree in-place.

    Algorithm:

    1. For each cell, compute content dimensions (paragraph text or
       recursed nested table) + ``2 × cellpadding`` for the cell's
       padding border.
    2. Column widths = max cell width per column.
    3. Row heights = max cell height per row.
    4. Cells are placed at ``(x, y)`` relative to the table's
       top-left.  Table origin ``(0, 0)`` = top-left corner of the
       outer border.

    Table dimensions::

        width  = 2·border + Σ col_widths + (ncols + 1) · cellspacing
        height = 2·border + Σ row_heights + (nrows + 1) · cellspacing

    ``cellspacing`` contributes the gap BETWEEN cells AND between
    the outer border and the first/last cell — matching Graphviz
    and classic HTML table box model.

    COLSPAN / ROWSPAN are not yet applied here; cells with
    ``colspan/rowspan > 1`` occupy a single grid slot for now.
    """
    if not tbl.rows:
        tbl.width = tbl.height = 2 * tbl.border
        return tbl.width, tbl.height

    ncols = max(len(r.cells) for r in tbl.rows)

    # Phase 1: natural cell dims.
    for row in tbl.rows:
        for cell in row.cells:
            pad = cell.cellpadding if cell.cellpadding is not None else tbl.cellpadding
            if cell.nested is not None:
                cw, ch = size_html_table(cell.nested, line_height_factor)
            else:
                cw, ch = _paragraph_size(cell.lines, line_height_factor)
            cell.width = cw + 2 * pad
            cell.height = ch + 2 * pad

    # Phase 2: column widths / row heights from grid maxima.
    col_widths = [0.0] * ncols
    row_heights = []
    for row in tbl.rows:
        row_h = 0.0
        for ci, cell in enumerate(row.cells):
            if ci < ncols:
                col_widths[ci] = max(col_widths[ci], cell.width)
            row_h = max(row_h, cell.height)
        row.height = row_h
        row_heights.append(row_h)
    tbl.col_widths = col_widths
    tbl.row_heights = row_heights

    # Phase 3: place each cell.  Grid coords start at the top-left
    # inside the outer border.  Cellspacing separates every cell from
    # its neighbour AND from the border.
    b = tbl.border
    s = tbl.cellspacing
    cur_y = b + s
    for row, row_h in zip(tbl.rows, row_heights):
        cur_x = b + s
        for ci, cell in enumerate(row.cells):
            if ci < ncols:
                # Expand cell to its column / row slot so backgrounds
                # fill the grid cleanly — content is placed within
                # by the renderer using ALIGN / VALIGN.
                cell.width = col_widths[ci]
                cell.height = row_h
                cell.x = cur_x
                cell.y = cur_y
                cur_x += col_widths[ci] + s
        cur_y += row_h + s

    tbl.width = 2 * b + sum(col_widths) + (ncols + 1) * s
    tbl.height = 2 * b + sum(row_heights) + (len(tbl.rows) + 1) * s
    return tbl.width, tbl.height
