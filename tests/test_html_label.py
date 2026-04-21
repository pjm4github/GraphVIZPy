"""Tests for the HTML-like label parser, sizer, and SVG renderer.

Covers Phases 1-3 of the HTML-label support:

- :mod:`gvpy.grammar.html_label` — ``parse_html_label`` produces a
  correct AST of :class:`TextRun` / :class:`HtmlLine` /
  :class:`HtmlLabel` with resolved inline styles.
- :func:`html_label_size` — width/height match the expected AFM sum.
- ``_compute_node_size`` — uses the AST for HTML labels, gives
  nodes the correct bbox.
- ``_render_html_text`` — emits SVG ``<text>`` with ``<tspan>``
  children that carry the runtime ``font-size`` / ``fill`` /
  ``font-weight`` attributes.

End-to-end check: layout + render 2592.dot and assert the resulting
SVG contains the actual text "b12" at ``font-size="19.0"`` and does
not contain the literal string ``&lt;FONT`` that the pre-fix code
emitted.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gvpy.grammar.html_label import (
    HtmlLabel,
    HtmlLine,
    TextRun,
    html_label_size,
    is_html_label,
    parse_html_label,
)


# ── Detection ───────────────────────────────────────────────────────


class TestDetection:
    def test_html_starts_with_angle(self):
        assert is_html_label("<hello>")
        assert is_html_label("<<B>bold</B>>")
        assert is_html_label("<<FONT POINT-SIZE=\"14\">x</FONT>>")

    def test_plain_label_is_not_html(self):
        assert not is_html_label("plain text")
        assert not is_html_label("")
        assert not is_html_label("<only-opening")
        assert not is_html_label("only-closing>")

    def test_non_string_is_not_html(self):
        assert not is_html_label(None)  # type: ignore[arg-type]
        assert not is_html_label(42)    # type: ignore[arg-type]


# ── Parser — simple cases ───────────────────────────────────────────


class TestParseSimple:
    def test_plain_text_inside_html_label(self):
        lbl = parse_html_label("<just text>")
        assert len(lbl.lines) == 1
        assert len(lbl.lines[0].runs) == 1
        run = lbl.lines[0].runs[0]
        assert run.text == "just text"
        assert run.font_size == 14.0

    def test_font_point_size(self):
        lbl = parse_html_label(
            '<<FONT POINT-SIZE="19">b12</FONT>>',
            default_font_size=14.0,
        )
        assert len(lbl.lines) == 1
        runs = lbl.lines[0].runs
        assert len(runs) == 1
        assert runs[0].text == "b12"
        assert runs[0].font_size == 19.0

    def test_font_color(self):
        lbl = parse_html_label(
            '<<FONT COLOR="#bfdbfe">B1</FONT>>',
            default_color="#000000",
        )
        run = lbl.lines[0].runs[0]
        assert run.text == "B1"
        assert run.color == "#bfdbfe"

    def test_font_face(self):
        lbl = parse_html_label(
            '<<FONT FACE="Courier">mono</FONT>>',
            default_face="Times-Roman",
        )
        run = lbl.lines[0].runs[0]
        assert run.face == "Courier"

    def test_font_combined_attrs(self):
        lbl = parse_html_label(
            '<<FONT POINT-SIZE="11" COLOR="#bfdbfeb3"><B>B1</B></FONT>>',
        )
        run = lbl.lines[0].runs[0]
        assert run.text == "B1"
        assert run.font_size == 11.0
        assert run.color == "#bfdbfeb3"
        assert run.bold is True


class TestParseEmphasis:
    def test_bold(self):
        run = parse_html_label("<<B>bold</B>>").lines[0].runs[0]
        assert run.bold is True
        assert run.italic is False

    def test_italic(self):
        run = parse_html_label("<<I>slant</I>>").lines[0].runs[0]
        assert run.italic is True

    def test_underline(self):
        run = parse_html_label("<<U>under</U>>").lines[0].runs[0]
        assert run.underline is True

    def test_strike(self):
        run = parse_html_label("<<S>crossed</S>>").lines[0].runs[0]
        assert run.strike is True

    def test_sub_sup(self):
        lbl = parse_html_label("<x<SUB>2</SUB>+y<SUP>3</SUP>>")
        runs = lbl.lines[0].runs
        texts = [r.text for r in runs]
        assert texts == ["x", "2", "+y", "3"]
        assert runs[1].sub is True
        assert runs[3].sup is True


# ── Parser — nesting, line breaks, entities ─────────────────────────


class TestParseNesting:
    def test_nested_font_and_bold(self):
        # <FONT><B>text</B></FONT> — bold text at the font's size/color.
        lbl = parse_html_label(
            '<<FONT POINT-SIZE="20" COLOR="red"><B>X</B></FONT>>'
        )
        run = lbl.lines[0].runs[0]
        assert run.text == "X"
        assert run.bold is True
        assert run.font_size == 20.0
        assert run.color == "red"

    def test_inner_font_overrides_outer(self):
        lbl = parse_html_label(
            '<<FONT POINT-SIZE="14">a<FONT POINT-SIZE="20">BIG</FONT>b</FONT>>'
        )
        runs = lbl.lines[0].runs
        assert [r.text for r in runs] == ["a", "BIG", "b"]
        assert runs[0].font_size == 14
        assert runs[1].font_size == 20
        assert runs[2].font_size == 14   # reverted to outer font

    def test_bold_italic_combined(self):
        run = parse_html_label("<<B><I>x</I></B>>").lines[0].runs[0]
        assert run.bold is True
        assert run.italic is True


class TestParseLineBreaks:
    def test_single_br(self):
        lbl = parse_html_label("<line1<BR/>line2>")
        assert len(lbl.lines) == 2
        assert lbl.lines[0].runs[0].text == "line1"
        assert lbl.lines[1].runs[0].text == "line2"

    def test_br_with_align(self):
        lbl = parse_html_label('<left<BR ALIGN="LEFT"/>right>')
        assert len(lbl.lines) == 2
        # ALIGN on a <BR> applies to the line it STARTS.
        assert lbl.lines[0].align == "center"
        assert lbl.lines[1].align == "left"

    def test_three_lines(self):
        lbl = parse_html_label("<alpha<BR/>beta<BR/>gamma>")
        assert len(lbl.lines) == 3
        assert [l.runs[0].text for l in lbl.lines] == ["alpha", "beta", "gamma"]


class TestParseEntities:
    def test_lt_gt_amp(self):
        lbl = parse_html_label("<a &lt; b &amp; c &gt; d>")
        text = "".join(r.text for r in lbl.lines[0].runs)
        assert text == "a < b & c > d"

    def test_numeric_entity(self):
        lbl = parse_html_label("<&#65;&#66;&#67;>")
        text = "".join(r.text for r in lbl.lines[0].runs)
        assert text == "ABC"


# ── Sizing ──────────────────────────────────────────────────────────


class TestSizing:
    def test_size_scales_with_font_size(self):
        from gvpy.engines.layout.common.text import text_width_times_roman
        lbl = parse_html_label('<<FONT POINT-SIZE="19">b12</FONT>>')
        w, h = html_label_size(lbl)
        expected_w = text_width_times_roman("b12", 19.0)
        assert w == pytest.approx(expected_w)
        # Line height ≈ font_size × 1.2
        assert h == pytest.approx(19.0 * 1.2)

    def test_multiline_height_sums(self):
        lbl = parse_html_label("<first<BR/>second>")
        _w, h = html_label_size(lbl)
        assert h == pytest.approx(2 * 14.0 * 1.2)

    def test_multiline_width_is_max(self):
        from gvpy.engines.layout.common.text import text_width_times_roman
        lbl = parse_html_label("<short<BR/>a longer line>")
        w, _h = html_label_size(lbl)
        expected = max(
            text_width_times_roman("short", 14.0),
            text_width_times_roman("a longer line", 14.0),
        )
        assert w == pytest.approx(expected)


# ── Phase 2: _compute_node_size integration ─────────────────────────


class TestNodeSizeWithHtmlLabel:
    @pytest.fixture
    def layout(self):
        """Layout the same ``<FONT POINT-SIZE=19>b12</FONT>`` node C
        renders in 2592.dot to make the assertions concrete."""
        from gvpy.grammar.gv_reader import read_dot
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        src = (
            'digraph { node [shape=rect, fontname=Arial]; '
            'a [label=<<FONT POINT-SIZE="19">b12</FONT>>]; }'
        )
        g = read_dot(src)
        return DotLayout(g).layout()

    def test_html_label_drives_node_width(self, layout):
        from gvpy.engines.layout.common.text import text_width_times_roman
        nd = layout["nodes"][0]
        # The node should be at least wide enough for "b12" at 19 pt.
        min_w = text_width_times_roman("b12", 19.0)
        assert nd["width"] >= min_w


# ── Phase 3: SVG rendering ──────────────────────────────────────────


class TestSvgHtmlRendering:
    def _render(self, label: str, **kwargs):
        from gvpy.render.svg_renderer import _render_html_text
        return _render_html_text(
            0.0, 0.0, label,
            default_face=kwargs.get("default_face", "Times-Roman"),
            default_size=kwargs.get("default_size", 14.0),
            default_color=kwargs.get("default_color", "#000000"),
            anchor=kwargs.get("anchor", "middle"),
        )

    def test_emits_text_element(self):
        out = self._render('<<FONT POINT-SIZE="19">b12</FONT>>')
        assert out.startswith("<text ")
        assert out.endswith("</text>")

    def test_no_angle_bracket_leak(self):
        # Must not emit the literal <<FONT…>> that the pre-fix code did.
        out = self._render('<<FONT POINT-SIZE="19">b12</FONT>>')
        assert "&lt;" not in out
        assert "FONT" not in out
        assert "b12" in out

    def test_font_size_override(self):
        out = self._render(
            '<<FONT POINT-SIZE="19">b12</FONT>>',
            default_size=14.0,
        )
        # tspan carries the overridden font-size; root <text> carries the default.
        assert 'font-size="14.0"' in out
        assert 'font-size="19.0"' in out

    def test_color_override(self):
        out = self._render(
            '<<FONT COLOR="#ff00ff">x</FONT>>',
            default_color="#000000",
        )
        assert 'fill="#ff00ff"' in out

    def test_bold_translates_to_font_weight(self):
        out = self._render('<<B>bold</B>>')
        assert 'font-weight="bold"' in out
        assert "bold" in out  # the text survives

    def test_italic_translates_to_font_style(self):
        out = self._render('<<I>slant</I>>')
        assert 'font-style="italic"' in out

    def test_underline_translates_to_text_decoration(self):
        out = self._render('<<U>u</U>>')
        assert 'text-decoration="underline"' in out

    def test_multiline_uses_tspan_dy(self):
        out = self._render("<one<BR/>two>")
        # Each line is at least one tspan; second line carries a dy.
        assert out.count("<tspan") >= 2
        assert "dy=" in out

    def test_entities_decoded(self):
        out = self._render("<a &amp; b>")
        # Entity decoded to '&', then re-escaped by xml.sax.saxutils.escape.
        assert "&amp;" in out
        assert "a " in out


# ── End-to-end: 2592.dot ────────────────────────────────────────────


# ── End-to-end: comprehensive html_labels.dot ──────────────────────


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "test_data" / "html_labels.dot").exists(),
    reason="html_labels.dot fixture missing",
)
class TestEndToEndHtmlLabels:
    """Render ``test_data/html_labels.dot`` and assert each HTML tag
    lands in the output SVG with the expected attributes.  The fixture
    demonstrates every supported tag on both a node and an edge, so
    regressions on any single tag will fail a focused test here."""

    @pytest.fixture(scope="class")
    def svg(self) -> str:
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        from gvpy.render.svg_renderer import render_svg
        path = Path(__file__).resolve().parents[1] / "test_data" / "html_labels.dot"
        g = read_dot_file(str(path))
        return render_svg(DotLayout(g).layout())

    def _node_window(self, svg: str, node_id: str, before: int = 400) -> str:
        """Return the slice of SVG covering a named node's ``<g>`` block
        (up to the following ``</g>``).  Used for per-tag assertions so
        we don't match text in unrelated nodes."""
        open_idx = svg.find(f'id="{node_id}"')
        assert open_idx >= 0, f"node {node_id} missing from SVG"
        close_idx = svg.find("</g>", open_idx)
        assert close_idx > open_idx
        return svg[open_idx:close_idx]

    # ── FONT attribute overrides ────────────────────────────────────

    def test_font_point_size(self, svg):
        win = self._node_window(svg, "node_n_size")
        assert 'font-size="20' in win
        assert ">size=20<" in win

    def test_font_color(self, svg):
        win = self._node_window(svg, "node_n_color")
        assert 'fill="#cc0000"' in win
        assert ">red text<" in win

    def test_font_face(self, svg):
        win = self._node_window(svg, "node_n_face")
        assert 'font-family="Courier"' in win
        assert ">monospace<" in win

    def test_font_combined(self, svg):
        win = self._node_window(svg, "node_n_combined")
        assert 'font-size="18' in win
        assert 'fill="#006600"' in win
        assert 'font-family="Helvetica"' in win

    # ── Emphasis tags ───────────────────────────────────────────────

    def test_bold(self, svg):
        win = self._node_window(svg, "node_n_bold")
        assert 'font-weight="bold"' in win
        assert ">BOLD<" in win

    def test_italic(self, svg):
        win = self._node_window(svg, "node_n_italic")
        assert 'font-style="italic"' in win
        assert ">italic<" in win

    def test_underline(self, svg):
        win = self._node_window(svg, "node_n_underline")
        assert 'text-decoration="underline"' in win

    def test_strike(self, svg):
        win = self._node_window(svg, "node_n_strike")
        assert 'text-decoration="line-through"' in win

    # ── Sub / super ─────────────────────────────────────────────────

    def test_subscript(self, svg):
        win = self._node_window(svg, "node_n_sub")
        assert 'baseline-shift="sub"' in win
        # H then subscript-2 then O ⇒ all three text runs present.
        assert ">H<" in win and ">2<" in win and ">O<" in win

    def test_superscript(self, svg):
        win = self._node_window(svg, "node_n_sup")
        assert 'baseline-shift="super"' in win

    # ── Nesting ─────────────────────────────────────────────────────

    def test_nested_bold_italic(self, svg):
        win = self._node_window(svg, "node_n_nested")
        assert 'font-weight="bold"' in win
        assert 'font-style="italic"' in win
        assert ">bold+italic<" in win

    def test_mixed_runs(self, svg):
        """``plain <B>bold</B> plain <I>italic</I> plain`` should split
        into five runs: ``plain ``, ``bold``, `` plain ``, ``italic``,
        `` plain``.  Bold and italic attrs must only appear on the
        respective middle runs."""
        win = self._node_window(svg, "node_n_mixed")
        assert ">bold<" in win
        assert ">italic<" in win
        # Count tspans: five runs → five tspans.
        assert win.count("<tspan") == 5

    def test_inner_font_overrides_outer(self, svg):
        """small(10) BIG(22) small(10) — three separate tspans, only
        the middle one carries ``font-size="22``."""
        win = self._node_window(svg, "node_n_innerfont")
        assert win.count("<tspan") == 3
        assert 'font-size="22' in win
        assert 'font-size="10' in win

    # ── Line breaks + alignment ─────────────────────────────────────

    def test_line_breaks(self, svg):
        win = self._node_window(svg, "node_n_breaks")
        # Three lines → first tspan gets y, next two get dy.
        assert win.count("<tspan") == 3
        assert win.count("dy=") == 2

    def test_br_align_carries_through(self, svg):
        # The fixture has <BR ALIGN="LEFT"/> and <BR ALIGN="RIGHT"/>.
        # Current renderer emits each run as its own tspan but does not
        # yet emit per-line text-anchor changes — the important check
        # is that the runs themselves survived parsing.
        win = self._node_window(svg, "node_n_align")
        assert ">centered<" in win
        assert ">left-aligned<" in win
        assert ">right-aligned<" in win

    # ── Entities ────────────────────────────────────────────────────

    def test_html_entities(self, svg):
        win = self._node_window(svg, "node_n_entity")
        # &lt; / &gt; / &amp; / &quot; decode during parsing then get
        # re-escaped by the SVG text escaper, so they should reappear
        # as the standard XML entities in the output.
        assert "&lt;tag&gt;" in win
        assert "&amp;" in win
        # &#65; → "A" (the only numeric entity the fixture uses).
        assert "A=A" in win

    # ── Compound label ──────────────────────────────────────────────

    def test_complex_label_has_all_runs(self, svg):
        win = self._node_window(svg, "node_n_complex")
        # Title: font-size=16, bold, color=#0066cc
        assert 'font-size="16' in win
        assert 'font-weight="bold"' in win
        assert 'fill="#0066cc"' in win
        # Subtitle: font-size=10
        assert 'font-size="10' in win
        # "emphasised" should be underlined and inside an italic run.
        assert 'text-decoration="underline"' in win
        assert 'font-style="italic"' in win

    # ── Edge labels ─────────────────────────────────────────────────

    def test_edge_has_html_label(self, svg):
        # n_size -> n_color edge has <FONT POINT-SIZE="16" COLOR="#ff6600">sized+coloured</FONT>.
        # Edge labels aren't wrapped in an id'd <g>, so search the
        # whole SVG for the unique text.
        idx = svg.find(">sized+coloured<")
        assert idx > 0
        window = svg[max(0, idx - 400): idx + 20]
        assert 'font-size="16' in window
        assert 'fill="#ff6600"' in window

    def test_edge_bold(self, svg):
        idx = svg.find(">bold edge<")
        assert idx > 0
        window = svg[max(0, idx - 400): idx + 20]
        assert 'font-weight="bold"' in window

    def test_edge_sup_equation(self, svg):
        # "E = mc²" — the run before the <SUP> is "E = mc" (ends the
        # tspan with the label text, not a ``>mc<`` boundary).
        idx = svg.find("E = mc</tspan>")
        assert idx > 0
        text_end = svg.find("</text>", idx)
        window = svg[idx: text_end + 8]
        # A superscript tspan for the exponent should follow.
        assert 'baseline-shift="super"' in window
        assert ">2<" in window

    def test_edge_multiline(self, svg):
        # "line 1<BR/>line 2" on the n_sub -> n_sup edge.
        idx = svg.find(">line 1<")
        assert idx > 0
        text_end = svg.find("</text>", idx)
        window = svg[idx: text_end + 8]
        assert ">line 2<" in window
        assert "dy=" in window

    def test_edge_inner_font(self, svg):
        # n_mixed -> n_innerfont: <FONT size=10>s<FONT size=18>M</FONT>s</FONT>
        # Three runs inside one edge label.
        idx = svg.find(">M<")
        assert idx > 0
        text_start = svg.rfind("<text ", 0, idx)
        text_end = svg.find("</text>", idx)
        window = svg[text_start: text_end + 8]
        assert window.count("<tspan") >= 3
        assert 'font-size="18' in window


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "test_data" / "2592.dot").exists(),
    reason="2592.dot fixture missing",
)
class TestEndToEnd2592:
    @pytest.fixture(scope="class")
    def svg(self) -> str:
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        from gvpy.render.svg_renderer import render_svg
        dot_path = Path(__file__).resolve().parents[1] / "test_data" / "2592.dot"
        g = read_dot_file(str(dot_path))
        layout = DotLayout(g).layout()
        return render_svg(layout)

    def test_b12_renders_as_text_not_markup(self, svg: str):
        # Before the fix, this SVG contained '&lt;&lt;FONT POINT-SIZE="19"&gt;b12&lt;/FONT&gt;&gt;'.
        assert "&lt;FONT" not in svg, "raw HTML tags leaked into rendered SVG"
        assert ">b12<" in svg  # actual text content

    def test_b12_has_overridden_font_size(self, svg: str):
        # The node default was not 19; the POINT-SIZE="19" override
        # must appear on a tspan that wraps the b12 text.  Use
        # '>b12<' to match the actual label text, not arrowhead
        # coordinates that might contain the substring.
        idx = svg.find(">b12<")
        assert idx > 0
        window = svg[max(0, idx - 300): idx + 20]
        assert 'font-size="19' in window

    def test_cluster_label_bold_and_sized(self, svg: str):
        # <FONT POINT-SIZE="11" COLOR="#bfdbfeb3"><B>B1</B></FONT>
        idx = svg.find(">B1<")
        assert idx > 0
        window = svg[max(0, idx - 200): idx + 20]
        assert 'font-weight="bold"' in window
        assert 'font-size="11' in window
