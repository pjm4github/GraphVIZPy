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


@dataclass
class HtmlLabel:
    """Root of a parsed HTML-like label."""
    lines: list[HtmlLine] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
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


class _LabelBuilder(HTMLParser):
    """HTMLParser subclass that builds an :class:`HtmlLabel` on the fly.

    Maintains a style stack — pushed on every supported open tag,
    popped on the matching close tag.  ``<BR/>`` flushes the current
    line and starts a fresh one.  Inside ``<TABLE>``/``<TR>``/``<TD>``
    the parser buffers a single placeholder run so the label renders
    with legible text even though real table layout isn't done yet.
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
        self._stack: list[dict] = [{
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
        self._in_table = 0
        self._table_placeholder_emitted = False

    def _style(self) -> dict:
        return self._stack[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_l = tag.lower()
        attrs_d = {k.lower(): (v or "") for k, v in attrs}

        if tag_l == "br":
            align = attrs_d.get("align", "").lower() or "center"
            self._current_line = HtmlLine(align=align)
            self.label.lines.append(self._current_line)
            return

        if tag_l in ("table", "tr", "td"):
            self._in_table += 1
            if not self._table_placeholder_emitted:
                # Emit one "[TABLE]" run so the label isn't empty.
                s = self._style()
                self._current_line.runs.append(TextRun(
                    text="[TABLE]",
                    font_size=s["font_size"],
                    color=s["color"],
                    face=s["face"],
                ))
                self._table_placeholder_emitted = True
            return

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
        # pops something.  This makes the parser forgiving of stray
        # tags rather than desynchronising the stack.
        self._stack.append(new)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l == "br":
            return
        if tag_l in ("table", "tr", "td"):
            if self._in_table > 0:
                self._in_table -= 1
            return
        if len(self._stack) > 1:
            self._stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        # Self-closing tags: <BR/>, <IMG/>, etc.
        tag_l = tag.lower()
        if tag_l == "br":
            self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._in_table > 0:
            return
        if not data:
            return
        s = self._style()
        self._current_line.runs.append(TextRun(
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

    Width = max line width = Σ ``text_width_times_roman(run.text,
    run.font_size)`` over the line's runs.
    Height = Σ line heights = max(run.font_size × line_height_factor)
    per line.
    """
    from gvpy.engines.layout.common.text import text_width_times_roman
    max_w = 0.0
    total_h = 0.0
    for line in lbl.lines:
        if not line.runs:
            # Empty line — count its height as the default font size.
            line_w = 0.0
            line_font = _DEFAULT_FONT_SIZE
        else:
            line_w = sum(text_width_times_roman(run.text, run.font_size)
                         for run in line.runs)
            line_font = max(run.font_size for run in line.runs)
        max_w = max(max_w, line_w)
        total_h += line_font * line_height_factor
    return max_w, total_h
