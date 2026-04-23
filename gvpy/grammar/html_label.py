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

import os
import re
import struct
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
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
    overline: bool = False
    strike: bool = False
    sub: bool = False
    sup: bool = False


@dataclass
class HtmlLine:
    """One text line — all runs between two ``<BR/>`` tags (or the
    start/end of the label).  ``align`` is inherited from the preceding
    ``<BR ALIGN=…/>``; the first line uses ``"center"``.

    ``is_hr`` marks a line emitted from ``<HR/>`` — it carries no runs
    and renders as a horizontal rule instead of text.  The ``height``
    field is used only for HR lines; text lines compute their height
    from their run font sizes.
    """
    runs: list[TextRun] = field(default_factory=list)
    align: str = "center"  # "left" | "center" | "right"
    is_hr: bool = False
    height: float = 0.0    # explicit height for HR rows


# ── Image probing ───────────────────────────────────────────────────


# Search directories checked when an IMG SRC is relative and the file
# isn't at CWD.  Matches Graphviz's ``imagepath`` graph attribute
# (``;``-separated on Windows, ``:`` elsewhere).  Layout / render
# entry points call :func:`set_image_search_paths` with the graph's
# imagepath before sizing; probe falls back to ``["."]`` otherwise.
_IMAGE_SEARCH_PATHS: list[str] = ["."]


def set_image_search_paths(paths: list[str] | None) -> None:
    """Install the directories consulted by :func:`_probe_image_size`
    when an IMG SRC is relative.

    Accepts a list of directory strings or ``None`` to reset to
    ``["."]`` (CWD only).  The first directory that contains the
    SRC wins — matches Graphviz's imagepath semantics.  Absolute
    paths in SRC bypass the search entirely.
    """
    global _IMAGE_SEARCH_PATHS
    if paths is None:
        _IMAGE_SEARCH_PATHS = ["."]
    else:
        _IMAGE_SEARCH_PATHS = list(paths) or ["."]


def _env_image_paths() -> list[str]:
    """Return directories from the ``GV_FILE_PATH`` environment
    variable — Graphviz's secondary image-search path mechanism,
    consulted after the graph-level ``imagepath`` attribute and
    before the CWD fallback.  Accepts ``;`` (Windows) or ``:``
    (Unix) separators and ignores empty tokens.
    """
    raw = os.environ.get("GV_FILE_PATH", "") or ""
    return [p.strip() for p in re.split(r"[;:]", raw) if p.strip()]


def _resolve_image_path(src: str) -> Optional[Path]:
    """Return the first existing file for ``src`` across the search
    paths, or ``None`` when unfound.

    Search order (first match wins):

    1. Absolute path (short-circuits the search).
    2. ``imagepath``-configured directories (set via
       :func:`set_image_search_paths`).
    3. ``GV_FILE_PATH`` environment variable directories.
    4. CWD as-given.
    """
    if not src:
        return None
    p = Path(src)
    if p.is_absolute():
        return p if p.is_file() else None
    for base in _IMAGE_SEARCH_PATHS:
        candidate = Path(base) / src
        if candidate.is_file():
            return candidate
    for base in _env_image_paths():
        candidate = Path(base) / src
        if candidate.is_file():
            return candidate
    # Final fallback: as-given relative to CWD (covers the case where
    # neither imagepath nor GV_FILE_PATH was configured).
    if p.is_file():
        return p
    return None


def _probe_image_size(path: str) -> tuple[float, float]:
    """Return ``(width, height)`` in pixels for the image at ``path``.

    Supports PNG, JPEG, and GIF by reading their file headers — no
    external dependency.  ``path`` may be relative; callers can set
    search directories via :func:`set_image_search_paths` so the
    probe walks them in order (first match wins).  Returns
    ``(0, 0)`` when the file is missing, truncated, or uses an
    unsupported format; callers use that sentinel to fall back to
    the cell's declared WIDTH/HEIGHT or a default.
    """
    resolved = _resolve_image_path(path)
    if resolved is None:
        return 0.0, 0.0
    try:
        with resolved.open("rb") as fh:
            head = fh.read(32)
    except OSError:
        return 0.0, 0.0
    if len(head) < 24:
        return 0.0, 0.0
    # PNG: 8-byte signature + IHDR (width/height at offsets 16/20,
    # big-endian uint32 each).
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            w, h = struct.unpack(">II", head[16:24])
            return float(w), float(h)
        except struct.error:
            return 0.0, 0.0
    # GIF87a / GIF89a: width/height at offsets 6/8, little-endian
    # uint16 each.
    if head[:6] in (b"GIF87a", b"GIF89a"):
        try:
            w, h = struct.unpack("<HH", head[6:10])
            return float(w), float(h)
        except struct.error:
            return 0.0, 0.0
    # JPEG: scan segments looking for SOF0 (0xFFC0) / SOF2 (0xFFC2).
    if head[:3] == b"\xff\xd8\xff":
        return _probe_jpeg_size(str(resolved))
    return 0.0, 0.0


def _probe_jpeg_size(path: str) -> tuple[float, float]:
    """Walk JPEG markers until hitting a SOF frame; extract dims."""
    try:
        with Path(path).open("rb") as fh:
            # Skip the 0xFFD8 SOI marker.
            fh.read(2)
            while True:
                byte = fh.read(1)
                if not byte:
                    return 0.0, 0.0
                if byte != b"\xff":
                    continue
                # Eat padding 0xFF bytes.
                marker = fh.read(1)
                while marker == b"\xff":
                    marker = fh.read(1)
                if not marker:
                    return 0.0, 0.0
                m = marker[0]
                if m == 0xD9 or m == 0xDA:  # EOI or SOS — no dims found
                    return 0.0, 0.0
                # Segment length (incl. the 2 length bytes themselves).
                seg_len_bytes = fh.read(2)
                if len(seg_len_bytes) < 2:
                    return 0.0, 0.0
                seg_len = struct.unpack(">H", seg_len_bytes)[0]
                if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    # SOF frame: data is 1 precision byte + H + W.
                    data = fh.read(seg_len - 2)
                    if len(data) < 5:
                        return 0.0, 0.0
                    h = struct.unpack(">H", data[1:3])[0]
                    w = struct.unpack(">H", data[3:5])[0]
                    return float(w), float(h)
                fh.seek(seg_len - 2, 1)
    except OSError:
        return 0.0, 0.0


# ── Images (Phase 4) ────────────────────────────────────────────────


@dataclass
class HtmlImage:
    """An ``<IMG SRC="…" SCALE="…"/>`` element inside a TD.

    ``src`` is the image file path as written in the DOT (absolute or
    relative to the DOT directory).  ``scale`` is one of Graphviz's
    enum values — ``FALSE`` / ``TRUE`` / ``WIDTH`` / ``HEIGHT`` /
    ``BOTH`` — controlling how the image fits its enclosing cell.
    ``natural_w`` / ``natural_h`` are the image's intrinsic pixel
    dimensions, probed from the file header during sizing; they stay
    at 0 when the file is missing or the format isn't recognised.
    """
    src: str = ""
    scale: str = "false"
    natural_w: float = 0.0
    natural_h: float = 0.0


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
    image: "Optional[HtmlImage]" = None
    # Ordered block list — the canonical content when a cell mixes
    # text with a nested table or image in any arrangement.  Each
    # entry is an :class:`HtmlLine`, :class:`HtmlTable`, or
    # :class:`HtmlImage`.  When only a single block kind is present
    # (the common case) sizer/renderer fall back to ``lines`` /
    # ``nested`` / ``image`` for the simpler code paths.
    blocks: list = field(default_factory=list)
    align: str = "center"      # ALIGN: left | center | right | text
    valign: str = "middle"     # VALIGN: top | middle | bottom
    balign: Optional[str] = None  # default <BR> alignment within cell
    bgcolor: Optional[str] = None
    color: Optional[str] = None  # cell border color override
    border: Optional[int] = None  # overrides table CELLBORDER
    cellpadding: Optional[int] = None
    cellspacing: Optional[int] = None
    colspan: int = 1
    rowspan: int = 1
    href: Optional[str] = None
    # Hyperlink companion attributes (interpreted by the SVG renderer).
    # ``target`` — anchor target window (_blank / _self / named frame).
    # ``title`` / ``tooltip`` — hover-text; Graphviz treats them as
    # aliases.  ``element_id`` becomes ``id="…"`` on the outer element.
    target: Optional[str] = None
    title: Optional[str] = None
    element_id: Optional[str] = None
    # PORT name — makes this cell addressable as ``node:port`` by
    # edges.  Resolved via :meth:`HtmlTable.find_port` during layout.
    port: Optional[str] = None
    # STYLE = "rounded" | "radial" | "solid" | None.  Only "rounded"
    # and "radial" have visual effect; "solid" is accepted for Graphviz
    # compatibility and renders like None.
    style: Optional[str] = None
    gradientangle: float = 0.0
    # SIDES = subset of "LTRB" (Left/Top/Right/Bottom) controlling
    # which cell border segments render.  "LTRB" (default) means the
    # full rect outline; "TB" would draw only the top + bottom edges.
    sides: str = "LTRB"
    # Minimum width/height (points) — content expands the cell beyond
    # these, unless ``fixedsize=True`` in which case the cell is
    # clamped to exactly (width_min, height_min).
    width_min: float = 0.0
    height_min: float = 0.0
    fixedsize: bool = False
    # When True, a ``<VR/>`` marker appeared after this cell in its
    # row — the renderer draws a vertical rule at the cell's right
    # edge.  Mutually independent from ``HtmlTable.columns_rule``
    # which forces VRs after every (non-last) cell.
    vr_after: bool = False
    # Computed during sizing:
    width: float = 0.0
    height: float = 0.0
    # Computed during placement (absolute within the table's coord frame):
    x: float = 0.0
    y: float = 0.0
    # Grid position assigned by the sizer's occupancy walk.  ``grid_col``
    # and ``grid_row`` are the top-left slot this cell occupies; with
    # ``colspan`` / ``rowspan`` > 1 the cell covers a rectangular region
    # starting at (grid_col, grid_row).  Set to ``-1`` until sized.
    grid_col: int = -1
    grid_row: int = -1
    # Natural content size, before any span-driven column / row growth
    # applies.  Kept separate from ``width`` / ``height`` (which after
    # sizing hold the SPAN-ADJUSTED dimensions) so the renderer can
    # place content relative to the span box while respecting the
    # underlying content size.
    content_w: float = 0.0
    content_h: float = 0.0


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)
    height: float = 0.0   # computed: max cell height
    # True when an ``<HR/>`` at TABLE level (between TR siblings)
    # precedes this row — renderer draws a horizontal rule above
    # the row.  Independent from ``HtmlTable.rows_rule``.
    hr_before: bool = False


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
    # Hyperlink companion attributes — same semantics as TableCell.
    target: Optional[str] = None
    title: Optional[str] = None
    element_id: Optional[str] = None
    # PORT on the TABLE makes the whole table addressable as a port
    # (the port refers to the outer frame's centre).
    port: Optional[str] = None
    # STYLE on the TABLE itself (same semantics as TableCell.style).
    style: Optional[str] = None
    gradientangle: float = 0.0
    # Outer-border SIDES subset (Graphviz spec allows SIDES on TABLE
    # as well as TD).
    sides: str = "LTRB"
    # ROWS="*" / COLUMNS="*" — auto-insert a horizontal / vertical
    # rule at every row / cell boundary.
    rows_rule: bool = False
    columns_rule: bool = False
    # Minimum outer dimensions; content expands beyond them, unless
    # ``fixedsize=True`` in which case the table clamps to exactly
    # (width_min, height_min).
    width_min: float = 0.0
    height_min: float = 0.0
    fixedsize: bool = False
    # Computed during sizing:
    col_widths: list[float] = field(default_factory=list)
    row_heights: list[float] = field(default_factory=list)
    # Origin of each column / row in the table's internal coord frame.
    # ``col_x[c]`` is the left edge of column c's content area; the
    # cellspacing gap to the left of it is centred at
    # ``col_x[c] - cellspacing/2``.  Saved by the sizer so the
    # renderer can draw VR / HR rules at the gap midpoints without
    # re-deriving them.
    col_x: list[float] = field(default_factory=list)
    row_y: list[float] = field(default_factory=list)
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


def _float_attr(val: str, default: float) -> float:
    """Parse a float-valued HTML attribute, swallowing junk."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _sides_attr(val: str, default: str = "LTRB") -> str:
    """Normalise a SIDES attribute to the uppercase subset of ``LTRB``.

    Unknown characters are dropped; an empty string after filtering
    falls back to the default (all four sides)."""
    if val is None or val == "":
        return default
    cleaned = "".join(c for c in val.upper() if c in "LTRB")
    return cleaned or default


def _bool_attr(val: str, default: bool = False) -> bool:
    """Parse a boolean-valued HTML attribute.

    Accepts ``true`` / ``false`` / ``1`` / ``0`` (case-insensitive).
    Any other value falls back to ``default``.
    """
    if val is None or val == "":
        return default
    v = val.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return default


def _star_attr(val: str) -> bool:
    """Graphviz's ROWS / COLUMNS attribute: the only legal value is
    ``"*"`` (draw a rule between every row / cell).  Anything else
    is ignored."""
    return val.strip() == "*"


def _style_attr(val: str) -> Optional[str]:
    """Normalise a STYLE attribute to a lower-case keyword.

    Only ``rounded``, ``radial``, and ``solid`` are recognised; other
    tokens (including dashed / invisible / combinations) are ignored
    and return ``None``.  Graphviz accepts comma-separated lists but
    the common HTML-label usage is a single keyword — we scan the
    list and pick the first match we know how to render.
    """
    if val is None or val == "":
        return None
    tokens = [t.strip().lower() for t in val.split(",")]
    for t in tokens:
        if t in ("rounded", "radial", "solid"):
            return t
    return None


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
        # Initial stack entries for ``color`` and ``face`` are None,
        # not the parse-time defaults.  That means runs without an
        # explicit ``<FONT COLOR="…">`` / ``FACE="…"`` carry color=None
        # and the renderer uses whatever ``default_color`` /
        # ``default_face`` is active AT RENDER TIME — crucial for the
        # hyperlink colour override (a cell wrapped in ``<a>`` inherits
        # the link blue at render time even though the label was
        # parsed with the graph's normal fontcolor).  ``font_size`` is
        # left as the parse-time default since it's also used by the
        # sizer for width / height computation and must be stable.
        self._style_stack: list[dict] = [{
            "font_size": default_font_size,
            "color": None,
            "face": None,
            "bold": False,
            "italic": False,
            "underline": False,
            "overline": False,
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
        # HRs that appear between TR siblings in a TABLE are staged
        # on this flag until the next TR opens, at which point the
        # TR receives ``hr_before=True``.
        self._pending_row_hr: bool = False
        # After a nested TABLE closes inside a TD, any subsequent
        # text data should start a fresh paragraph — not join the
        # pre-table line.  Flag set by the TABLE end-tag handler and
        # consumed by the next non-trivial ``handle_data`` in the TD.
        self._pending_paragraph_break: bool = False

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
            line = HtmlLine(align=self._default_line_align())
            lines.append(line)
            td = self._active_td()
            if td is not None and td.lines is lines:
                td.blocks.append(line)
        return lines[-1]

    def _default_line_align(self) -> str:
        """Return the default alignment for a newly-created line at the
        current point in the parse.  Inside a TD with BALIGN set, that
        becomes the cell's balign; otherwise ``"center"``.
        """
        td = self._active_td()
        if td is not None and td.balign:
            return td.balign
        return "center"

    # ── Tag handlers ────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_l = tag.lower()
        attrs_d = {k.lower(): (v or "") for k, v in attrs}

        if tag_l == "br":
            sink = self._text_sink_lines()
            if sink is not None:
                align = (attrs_d.get("align", "").lower()
                         or self._default_line_align())
                new_line = HtmlLine(align=align)
                sink.append(new_line)
                td = self._active_td()
                if td is not None and td.lines is sink:
                    td.blocks.append(new_line)
                # Update _current_line if this was the top-level label.
                top = self._container_stack[-1]
                if top["kind"] == "label":
                    self._current_line = new_line
            return

        if tag_l == "hr":
            # Two meanings depending on context:
            # (a) inside a TD (or top-level label): a paragraph-level
            #     horizontal rule — append an ``is_hr`` sentinel line.
            # (b) inside a TABLE/TR but outside any TD: a BETWEEN-ROW
            #     horizontal rule — stage it onto the next TR via
            #     ``_pending_row_hr``.
            td = self._active_td()
            tbl = self._active_table()
            if td is None and tbl is not None:
                self._pending_row_hr = True
                return
            sink = self._text_sink_lines()
            if sink is not None:
                hr_line = HtmlLine(is_hr=True, height=4.0)
                sink.append(hr_line)
                new_line = HtmlLine(align=self._default_line_align())
                sink.append(new_line)
                td = self._active_td()
                if td is not None and td.lines is sink:
                    td.blocks.append(hr_line)
                    td.blocks.append(new_line)
                top = self._container_stack[-1]
                if top["kind"] == "label":
                    self._current_line = new_line
            return

        if tag_l == "vr":
            # Vertical rule between cells of a TR.  Marks the most
            # recent cell in the current row with ``vr_after=True``.
            # A VR outside a TR (or before any TD) is silently
            # ignored — matches C's parse behaviour.
            tr = self._active_tr()
            if tr is not None and tr.cells:
                tr.cells[-1].vr_after = True
            return

        if tag_l == "img":
            # Image embedded inside a TD.  First IMG becomes the
            # canonical ``cell.image`` for simple lookups; additional
            # IMGs only appear in ``cell.blocks``.  Outside a TD, IMG
            # is ignored (no paragraph-level images in Graphviz's
            # HTML dialect).
            td = self._active_td()
            if td is None:
                return
            src = attrs_d.get("src") or ""
            scale = (attrs_d.get("scale") or "false").lower()
            img = HtmlImage(src=src, scale=scale)
            if td.image is None:
                td.image = img
            td.blocks.append(img)
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
            # Nested-table CELLSPACING inherits from the containing
            # TD when the TD supplied its own value and the nested
            # TABLE did not — matches Graphviz's per-cell spacing
            # override semantics in ``lib/common/htmltable.c``.
            cs_default = 2
            parent_td = self._active_td()
            if (parent_td is not None
                    and parent_td.cellspacing is not None
                    and parent_td.cellspacing >= 0):
                cs_default = parent_td.cellspacing
            table = HtmlTable(
                border=border,
                cellborder=cellborder,
                cellpadding=_int_attr(attrs_d.get("cellpadding", ""), 2),
                cellspacing=_int_attr(attrs_d.get("cellspacing", ""), cs_default),
                bgcolor=attrs_d.get("bgcolor") or None,
                color=attrs_d.get("color") or None,
                align=(attrs_d.get("align") or "center").lower(),
                valign=(attrs_d.get("valign") or "middle").lower(),
                href=attrs_d.get("href") or None,
                target=attrs_d.get("target") or None,
                title=(attrs_d.get("title")
                       or attrs_d.get("tooltip") or None),
                element_id=attrs_d.get("id") or None,
                port=attrs_d.get("port") or None,
                style=_style_attr(attrs_d.get("style", "")),
                gradientangle=_float_attr(attrs_d.get("gradientangle", ""), 0.0),
                sides=_sides_attr(attrs_d.get("sides", ""), "LTRB"),
                rows_rule=_star_attr(attrs_d.get("rows", "")),
                columns_rule=_star_attr(attrs_d.get("columns", "")),
                width_min=_float_attr(attrs_d.get("width", ""), 0.0),
                height_min=_float_attr(attrs_d.get("height", ""), 0.0),
                fixedsize=_bool_attr(attrs_d.get("fixedsize", ""), False),
            )
            # Attach to the enclosing container.  Top-level → label.table.
            # Inside a TD → TableCell.nested + block list.
            top = self._container_stack[-1]
            if top["kind"] == "label":
                # Label's .lines text is abandoned in favour of the
                # table; if both exist the table wins in rendering.
                self.label.table = table
            elif top["kind"] == "td":
                top_cell: TableCell = top["obj"]
                # Store as the cell's nested table only if none
                # already present (mixed-content cells put additional
                # tables only in ``blocks``).
                if top_cell.nested is None:
                    top_cell.nested = table
                top_cell.blocks.append(table)
            # else: <TABLE> inside <TR> not in <TD> is invalid — attach
            # to the first-met TD if any, otherwise ignore.
            self._container_stack.append({"kind": "table", "obj": table})
            return

        if tag_l == "tr":
            tbl = self._active_table()
            if tbl is None:
                return
            row = TableRow()
            # Pending HR between rows attaches to this TR.
            if self._pending_row_hr:
                row.hr_before = True
                self._pending_row_hr = False
            tbl.rows.append(row)
            self._container_stack.append({"kind": "tr", "obj": row})
            return

        if tag_l == "td":
            tr = self._active_tr()
            if tr is None:
                return
            # TABLE ALIGN / VALIGN act as per-cell defaults when the
            # TD doesn't supply its own — matches Graphviz's
            # attribute cascade.  Fall back to the structural
            # defaults ("center" / "middle") when neither is set.
            parent_table = self._active_table()
            table_align = (parent_table.align if parent_table else "center")
            table_valign = (parent_table.valign if parent_table else "middle")
            cell = TableCell(
                align=((attrs_d.get("align") or table_align)).lower(),
                valign=((attrs_d.get("valign") or table_valign)).lower(),
                balign=((attrs_d.get("balign") or "").lower() or None),
                bgcolor=attrs_d.get("bgcolor") or None,
                color=attrs_d.get("color") or None,
                border=_int_attr(attrs_d.get("border", ""), -1) if attrs_d.get("border") else None,
                cellpadding=_int_attr(attrs_d.get("cellpadding", ""), -1) if attrs_d.get("cellpadding") else None,
                cellspacing=_int_attr(attrs_d.get("cellspacing", ""), -1) if attrs_d.get("cellspacing") else None,
                colspan=_int_attr(attrs_d.get("colspan", ""), 1),
                rowspan=_int_attr(attrs_d.get("rowspan", ""), 1),
                href=attrs_d.get("href") or None,
                target=attrs_d.get("target") or None,
                title=(attrs_d.get("title")
                       or attrs_d.get("tooltip") or None),
                element_id=attrs_d.get("id") or None,
                port=attrs_d.get("port") or None,
                style=_style_attr(attrs_d.get("style", "")),
                gradientangle=_float_attr(attrs_d.get("gradientangle", ""), 0.0),
                sides=_sides_attr(attrs_d.get("sides", ""), "LTRB"),
                width_min=_float_attr(attrs_d.get("width", ""), 0.0),
                height_min=_float_attr(attrs_d.get("height", ""), 0.0),
                fixedsize=_bool_attr(attrs_d.get("fixedsize", ""), False),
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
            # <O> is overline — distinct from <U> (underline).  SVG
            # renders it via ``text-decoration="overline"``.
            new["overline"] = True
        # Unknown tags: still push a matching state so the end tag
        # pops something, keeping the stack in sync.
        self._style_stack.append(new)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l in ("br", "hr", "vr", "img"):
            return
        if tag_l in ("table", "tr", "td"):
            # Pop until we find the matching frame.  Normally it's the
            # top of the stack; only ill-formed input needs the walk.
            for i in range(len(self._container_stack) - 1, -1, -1):
                if self._container_stack[i]["kind"] == tag_l:
                    del self._container_stack[i:]
                    break
            # Closing a nested TABLE inside a TD: any following text
            # must start a fresh paragraph rather than joining the
            # last pre-table line.  We don't create the empty line
            # eagerly (that would pollute ``blocks``); instead we
            # flag the TD and have ``handle_data`` open a fresh line
            # lazily on the next non-whitespace data call.
            if tag_l == "table":
                td = self._active_td()
                if td is not None:
                    self._pending_paragraph_break = True
            else:
                # Leaving a TD or TR — the pending-paragraph flag was
                # scoped to the TD we just closed; drop it so it
                # doesn't leak into a sibling cell.
                self._pending_paragraph_break = False
            return
        if len(self._style_stack) > 1:
            self._style_stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        # Self-closing tags: <BR/>, <HR/>, <VR/>, <IMG/>, etc.
        tag_l = tag.lower()
        if tag_l in ("br", "hr", "vr", "img"):
            self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if not data:
            return
        # Consume any pending paragraph break: force a fresh line in
        # the active TD so text after a closed nested TABLE doesn't
        # merge with the pre-table text.  Pure-whitespace data that
        # arrives between the </TABLE> and the real text is treated
        # the same — if it makes it through, it starts a new line.
        if self._pending_paragraph_break:
            td = self._active_td()
            if td is not None:
                fresh = HtmlLine(align=self._default_line_align())
                td.lines.append(fresh)
                td.blocks.append(fresh)
            self._pending_paragraph_break = False
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
            overline=s["overline"],
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


_IMG_DEFAULT_SIZE = 50.0  # fallback when the image file can't be probed


def _image_natural_size(img: "HtmlImage") -> tuple[float, float]:
    """Return the natural content size contributed by an IMG cell.

    Probes the file once and caches the result on the image object.
    Returns ``(0, 0)`` when the file is missing and the cell has no
    WIDTH / HEIGHT declared — the caller's min-clamping will then
    supply the fallback.  When the file is unreadable but the cell
    has declared dims, those dims take over via ``width_min``/``height_min``.
    """
    if img.natural_w == 0.0 and img.natural_h == 0.0 and img.src:
        img.natural_w, img.natural_h = _probe_image_size(img.src)
    if img.natural_w <= 0 or img.natural_h <= 0:
        return _IMG_DEFAULT_SIZE, _IMG_DEFAULT_SIZE
    return img.natural_w, img.natural_h


def find_html_port(
    tbl: "HtmlTable", port_name: str,
) -> Optional["TableCell"]:
    """Return the :class:`TableCell` that carries ``port_name`` anywhere
    in the table tree (including nested subtables inside cells), or
    ``None`` when no match.  The first cell matched wins.
    """
    if not port_name:
        return None
    for row in tbl.rows:
        for cell in row.cells:
            if cell.port == port_name:
                return cell
            if cell.nested is not None:
                hit = find_html_port(cell.nested, port_name)
                if hit is not None:
                    return hit
            # Additional nested tables living in ``blocks`` (mixed-
            # content cells) also get searched.
            for block in cell.blocks:
                if isinstance(block, HtmlTable) and block is not cell.nested:
                    hit = find_html_port(block, port_name)
                    if hit is not None:
                        return hit
    return None


def html_port_center(tbl: "HtmlTable", port_name: str) -> Optional[tuple[float, float]]:
    """Return the centre point of the ported cell in the table's
    internal coordinate frame, or ``None`` when the port is unknown.

    Coordinates are relative to the table's top-left corner (``0,0``);
    callers offset by the table's placement in the enclosing node.
    """
    cell = find_html_port(tbl, port_name)
    if cell is None:
        return None
    return (cell.x + cell.width / 2.0,
            cell.y + cell.height / 2.0)


def html_port_fraction(
    tbl: "HtmlTable", port_name: str, rankdir: int = 0,
) -> Optional[float]:
    """Return a mincross-order fraction in ``[0, 1)`` for a port,
    compatible with C's ``compassPort`` (``lib/common/shapes.c:2856``).

    Mirrors :meth:`gvpy.grammar.record_parser.RecordField.port_fraction`:
    the cell's centre is rotated into math-convention coordinates
    (y-up), then the rankdir-specific clockwise rotation is applied,
    then ``atan2(y, x) + 1.5π`` (mod 2π) gives an angle ordered N=0,
    W=¼, S=½, E=¾ which the caller scales by ``MC_SCALE``.  Returns
    ``None`` if the port is unknown.
    """
    import math
    cell = find_html_port(tbl, port_name)
    if cell is None:
        return None
    root_cx = tbl.width / 2.0
    root_cy = tbl.height / 2.0
    px = (cell.x + cell.width / 2.0) - root_cx
    py = root_cy - (cell.y + cell.height / 2.0)
    # Clockwise rotation by 90° × rankdir.
    for _ in range(rankdir % 4):
        px, py = py, -px
    angle = math.atan2(py, px) + 1.5 * math.pi
    if angle >= 2 * math.pi:
        angle -= 2 * math.pi
    return angle / (2 * math.pi)


def _cell_is_mixed(cell: "TableCell") -> bool:
    """True when the cell's ``blocks`` list holds text AND a
    non-text block (table or image), or multiple non-text blocks.

    Simple cells (all text, or a single table, or a single image)
    use their existing specialised code paths; mixed cells use the
    generic block iterator.
    """
    if not cell.blocks:
        return False
    non_text = [b for b in cell.blocks if not isinstance(b, HtmlLine)]
    if len(non_text) > 1:
        return True
    has_text = any(isinstance(b, HtmlLine) and (b.is_hr or b.runs)
                   for b in cell.blocks)
    return bool(non_text) and has_text


def _iter_paragraph_groups(
    blocks: list,
) -> list[tuple[str, object]]:
    """Split ``cell.blocks`` into a flat sequence of
    ``("paragraph", list[HtmlLine])`` / ``("table", HtmlTable)`` /
    ``("image", HtmlImage)`` tuples.

    Contiguous :class:`HtmlLine` entries fold into a single
    "paragraph" group so the renderer can size and place them as
    one paragraph fragment inside a mixed-content cell.
    """
    out: list[tuple[str, object]] = []
    para: list[HtmlLine] = []
    for b in blocks:
        if isinstance(b, HtmlLine):
            para.append(b)
            continue
        if para:
            out.append(("paragraph", para))
            para = []
        if isinstance(b, HtmlTable):
            out.append(("table", b))
        elif isinstance(b, HtmlImage):
            out.append(("image", b))
    if para:
        out.append(("paragraph", para))
    return out


def _mixed_cell_natural_size(
    cell: "TableCell", line_height_factor: float,
) -> tuple[float, float]:
    """Return ``(width, height)`` for a mixed-content cell.

    Sizes each block with its own algorithm: text paragraphs via
    :func:`_paragraph_size`, nested tables via :func:`size_html_table`,
    images via :func:`_image_natural_size`.  Width is the max of
    block widths; height is the sum (blocks stack vertically).
    """
    max_w = 0.0
    total_h = 0.0
    for kind, obj in _iter_paragraph_groups(cell.blocks):
        if kind == "paragraph":
            w, h = _paragraph_size(obj, line_height_factor)  # type: ignore[arg-type]
        elif kind == "table":
            w, h = size_html_table(obj, line_height_factor)  # type: ignore[arg-type]
        else:  # image
            w, h = _image_natural_size(obj)  # type: ignore[arg-type]
        max_w = max(max_w, w)
        total_h += h
    return max_w, total_h


def _paragraph_size(lines: list["HtmlLine"], line_height_factor: float) -> tuple[float, float]:
    """Return ``(width, height)`` in points for a list of paragraph
    lines.  Shared by the top-level label path and per-cell content.

    HR lines contribute their stored ``height`` instead of a font-based
    line height, and don't affect the width.
    """
    from gvpy.engines.layout.common.text import text_width_times_roman
    max_w = 0.0
    total_h = 0.0
    for line in lines:
        if line.is_hr:
            total_h += line.height
            continue
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

    Four-phase algorithm, matching the classic HTML table model:

    1. **Grid occupancy walk** — assign ``grid_col`` / ``grid_row`` to
       every cell, skipping any slot already covered by an earlier
       cell's ``COLSPAN`` / ``ROWSPAN``.
    2. **Natural content size** — ``content_w`` / ``content_h`` =
       paragraph or nested-table size + ``2 × cellpadding``.
    3. **Column / row sizing** — simple cells
       (colspan == rowspan == 1) drive the base column widths and
       row heights; spanning cells then grow the covered columns /
       rows proportionally if their content doesn't fit.
    4. **Placement** — each cell's ``(x, y)`` is the top-left of its
       span region; ``width`` / ``height`` are the total spanned
       dimensions (content flows inside via ALIGN / VALIGN at render
       time).

    Table dimensions::

        width  = 2·border + Σ col_widths + (ncols + 1) · cellspacing
        height = 2·border + Σ row_heights + (nrows + 1) · cellspacing

    ``cellspacing`` contributes the gap between every pair of cells
    and between the outer border and the first/last cell — matching
    Graphviz and classic HTML table box model.
    """
    if not tbl.rows:
        tbl.width = tbl.height = 2 * tbl.border
        return tbl.width, tbl.height

    # ── Phase 1: grid occupancy walk ────────────────────────────────
    # Assign grid_col / grid_row to each cell, respecting COLSPAN /
    # ROWSPAN of earlier cells.  ``occupied`` tracks which (row, col)
    # slots are already claimed.
    occupied: set[tuple[int, int]] = set()
    nrows = len(tbl.rows)
    max_col_seen = 0
    for r, row in enumerate(tbl.rows):
        c = 0
        for cell in row.cells:
            # Skip over any slot already claimed by an earlier cell's
            # rowspan (from a previous row) or colspan (from a previous
            # cell in this row).
            while (r, c) in occupied:
                c += 1
            cell.grid_col = c
            cell.grid_row = r
            cs = max(1, cell.colspan)
            rs = max(1, cell.rowspan)
            for i in range(rs):
                for j in range(cs):
                    occupied.add((r + i, c + j))
            c += cs
            if c > max_col_seen:
                max_col_seen = c
    ncols = max_col_seen

    # ── Phase 2: natural content size ───────────────────────────────
    # Per-cell width/height clamping: a cell's minimum dimensions
    # honour its WIDTH / HEIGHT attributes (points).  ``fixedsize=True``
    # forces the cell to exactly those dimensions regardless of
    # content; ``fixedsize=False`` (default) treats them as a lower
    # bound.  IMG cells probe the image's pixel dimensions and pick
    # their natural size from the intersection of image size and
    # SCALE mode.
    for row in tbl.rows:
        for cell in row.cells:
            pad = (cell.cellpadding if cell.cellpadding is not None
                   else tbl.cellpadding)
            if _cell_is_mixed(cell):
                cw, ch = _mixed_cell_natural_size(cell, line_height_factor)
            elif cell.image is not None:
                cw, ch = _image_natural_size(cell.image)
            elif cell.nested is not None:
                cw, ch = size_html_table(cell.nested, line_height_factor)
            else:
                cw, ch = _paragraph_size(cell.lines, line_height_factor)
            nat_w = cw + 2 * pad
            nat_h = ch + 2 * pad
            if cell.fixedsize:
                cell.content_w = cell.width_min or nat_w
                cell.content_h = cell.height_min or nat_h
            else:
                cell.content_w = max(nat_w, cell.width_min)
                cell.content_h = max(nat_h, cell.height_min)

    s = tbl.cellspacing

    # ── Phase 3a: simple-cell driven column widths / row heights ────
    col_widths = [0.0] * ncols
    row_heights = [0.0] * nrows
    for r, row in enumerate(tbl.rows):
        for cell in row.cells:
            if cell.colspan == 1:
                col_widths[cell.grid_col] = max(
                    col_widths[cell.grid_col], cell.content_w)
            if cell.rowspan == 1:
                row_heights[cell.grid_row] = max(
                    row_heights[cell.grid_row], cell.content_h)

    # ── Phase 3b: grow columns / rows for spanning cells ────────────
    # If a spanning cell's natural size exceeds the sum of the
    # columns / rows it covers (plus the cellspacing between them),
    # distribute the extra proportionally to the columns' / rows'
    # existing sizes.  Narrow columns stay narrow; columns already
    # carrying wide content absorb most of the growth.  Matches C's
    # weighted allocation in ``htmltable.c``.  When every spanned
    # column has width 0 (all cells above are empty) we fall back to
    # an even split.
    for row in tbl.rows:
        for cell in row.cells:
            if cell.colspan > 1:
                c0 = cell.grid_col
                c1 = c0 + cell.colspan
                avail = sum(col_widths[c0:c1]) + (cell.colspan - 1) * s
                extra = cell.content_w - avail
                if extra > 0:
                    total = sum(col_widths[c0:c1])
                    if total > 0:
                        for c in range(c0, c1):
                            col_widths[c] += extra * col_widths[c] / total
                    else:
                        per = extra / cell.colspan
                        for c in range(c0, c1):
                            col_widths[c] += per
            if cell.rowspan > 1:
                r0 = cell.grid_row
                r1 = r0 + cell.rowspan
                avail = sum(row_heights[r0:r1]) + (cell.rowspan - 1) * s
                extra = cell.content_h - avail
                if extra > 0:
                    total = sum(row_heights[r0:r1])
                    if total > 0:
                        for rr in range(r0, r1):
                            row_heights[rr] += extra * row_heights[rr] / total
                    else:
                        per = extra / cell.rowspan
                        for rr in range(r0, r1):
                            row_heights[rr] += per

    # ── Phase 3c: honour TABLE WIDTH / HEIGHT minima ────────────────
    # Expand the column / row totals so the outer table meets the
    # TABLE-level WIDTH / HEIGHT minima (or fixed sizes).  Growth is
    # distributed proportionally; if every column / row is zero we
    # split evenly.  ``fixedsize=True`` on the TABLE overrides the
    # natural content size both up AND down (rare — content would
    # normally not fit — but we honour the spec).
    b = tbl.border
    cur_w = 2 * b + sum(col_widths) + (ncols + 1) * s
    cur_h = 2 * b + sum(row_heights) + (nrows + 1) * s
    target_w = (tbl.width_min if tbl.fixedsize
                else max(cur_w, tbl.width_min))
    target_h = (tbl.height_min if tbl.fixedsize
                else max(cur_h, tbl.height_min))
    if target_w > 0 and target_w != cur_w and ncols > 0:
        extra = target_w - cur_w
        total = sum(col_widths)
        if total > 0:
            col_widths = [w + extra * w / total for w in col_widths]
        else:
            col_widths = [w + extra / ncols for w in col_widths]
    if target_h > 0 and target_h != cur_h and nrows > 0:
        extra = target_h - cur_h
        total = sum(row_heights)
        if total > 0:
            row_heights = [h + extra * h / total for h in row_heights]
        else:
            row_heights = [h + extra / nrows for h in row_heights]

    tbl.col_widths = col_widths
    tbl.row_heights = row_heights

    # ── Phase 4: place cells ────────────────────────────────────────
    # Column X origins: col_x[c] = b + s + Σ col_widths[0..c] + c·s.
    b = tbl.border
    col_x = [b + s]
    for cw in col_widths[:-1]:
        col_x.append(col_x[-1] + cw + s)
    row_y = [b + s]
    for rh in row_heights[:-1]:
        row_y.append(row_y[-1] + rh + s)

    for row in tbl.rows:
        row_h = 0.0
        for cell in row.cells:
            c0 = cell.grid_col
            r0 = cell.grid_row
            cs = max(1, cell.colspan)
            rs = max(1, cell.rowspan)
            cell.x = col_x[c0]
            cell.y = row_y[r0]
            # Spanned cell dimensions include the cellspacing gap(s)
            # that fall WITHIN the span (one per extra col / row).
            cell.width = sum(col_widths[c0:c0 + cs]) + (cs - 1) * s
            cell.height = sum(row_heights[r0:r0 + rs]) + (rs - 1) * s
            row_h = max(row_h, cell.height)
        row.height = row_h

    tbl.col_x = col_x
    tbl.row_y = row_y
    tbl.width = 2 * b + sum(col_widths) + (ncols + 1) * s
    tbl.height = 2 * b + sum(row_heights) + (nrows + 1) * s
    return tbl.width, tbl.height
