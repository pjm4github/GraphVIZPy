"""Tests for HTML-table label support (Phase 4a).

Covers the parser, sizing, and SVG rendering of ``<TABLE>`` /
``<TR>`` / ``<TD>`` labels.  Paragraph-style HTML labels (FONT / B /
I / BR etc.) are covered by ``tests/test_html_label.py``; this
module focuses on the table machinery.

Layout:

- ``TestParseTable`` — AST structure (rows, cells, attributes).
- ``TestTableSize`` — column widths / row heights / cell placement.
- ``TestTableRender`` — the SVG emitted for a small table.
- ``TestEndToEndHtmlTables`` — loads ``test_data/html_tables.dot``
  and asserts each fixture renders correctly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gvpy.grammar.html_label import (
    HtmlLabel,
    HtmlTable,
    TableCell,
    TableRow,
    html_label_size,
    parse_html_label,
    size_html_table,
)


# ── Parser ──────────────────────────────────────────────────────────


class TestParseTable:
    def test_minimal_2x2(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>A</TD><TD>B</TD></TR>"
            "<TR><TD>C</TD><TD>D</TD></TR></TABLE>>"
        )
        assert lbl.table is not None
        t = lbl.table
        assert len(t.rows) == 2
        assert len(t.rows[0].cells) == 2
        assert len(t.rows[1].cells) == 2
        texts = [[c.lines[0].runs[0].text for c in r.cells] for r in t.rows]
        assert texts == [["A", "B"], ["C", "D"]]

    def test_table_default_attrs(self):
        lbl = parse_html_label("<<TABLE><TR><TD>x</TD></TR></TABLE>>")
        t = lbl.table
        assert t.border == 1
        # CELLBORDER defaults to BORDER when unspecified (Graphviz
        # convention, gives the default "double line grid" look).
        assert t.cellborder == 1
        assert t.cellpadding == 2
        assert t.cellspacing == 2

    def test_cellborder_inherits_border(self):
        lbl = parse_html_label(
            '<<TABLE BORDER="3"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.border == 3
        assert lbl.table.cellborder == 3  # inherited

    def test_cellborder_explicit_overrides(self):
        lbl = parse_html_label(
            '<<TABLE BORDER="3" CELLBORDER="1"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.border == 3
        assert lbl.table.cellborder == 1  # explicit wins

    def test_cellborder_explicit_zero(self):
        lbl = parse_html_label(
            '<<TABLE BORDER="2" CELLBORDER="0"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.border == 2
        assert lbl.table.cellborder == 0  # explicit 0 wins over inherit

    def test_table_attrs_parsed(self):
        lbl = parse_html_label(
            '<<TABLE BORDER="2" CELLBORDER="1" CELLPADDING="6" '
            'CELLSPACING="0" BGCOLOR="#ff0000" COLOR="#00ff00">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        t = lbl.table
        assert t.border == 2
        assert t.cellborder == 1
        assert t.cellpadding == 6
        assert t.cellspacing == 0
        assert t.bgcolor == "#ff0000"
        assert t.color == "#00ff00"

    def test_cell_attrs_parsed(self):
        lbl = parse_html_label(
            '<<TABLE><TR>'
            '<TD ALIGN="LEFT" VALIGN="TOP" BGCOLOR="#abc" '
            'COLSPAN="2" ROWSPAN="3">x</TD>'
            '</TR></TABLE>>'
        )
        c = lbl.table.rows[0].cells[0]
        assert c.align == "left"
        assert c.valign == "top"
        assert c.bgcolor == "#abc"
        assert c.colspan == 2
        assert c.rowspan == 3

    def test_cell_default_align_valign(self):
        lbl = parse_html_label("<<TABLE><TR><TD>x</TD></TR></TABLE>>")
        c = lbl.table.rows[0].cells[0]
        assert c.align == "center"
        assert c.valign == "middle"

    def test_cell_with_inline_formatting(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>"
            "<FONT POINT-SIZE=\"18\"><B>Big</B></FONT>"
            "</TD></TR></TABLE>>"
        )
        c = lbl.table.rows[0].cells[0]
        run = c.lines[0].runs[0]
        assert run.text == "Big"
        assert run.font_size == 18
        assert run.bold is True

    def test_cell_with_br_creates_multiple_lines(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>one<BR/>two<BR/>three</TD></TR></TABLE>>"
        )
        c = lbl.table.rows[0].cells[0]
        # After BRs, the cell has three lines.
        texts = [l.runs[0].text for l in c.lines if l.runs]
        assert texts == ["one", "two", "three"]

    def test_nested_table(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>"
            "<TABLE><TR><TD>inner</TD></TR></TABLE>"
            "</TD></TR></TABLE>>"
        )
        outer = lbl.table
        assert outer is not None
        cell = outer.rows[0].cells[0]
        assert cell.nested is not None
        inner = cell.nested
        assert len(inner.rows) == 1
        assert inner.rows[0].cells[0].lines[0].runs[0].text == "inner"

    def test_whitespace_between_tags_is_ignored(self):
        """Stray whitespace between <TABLE>/<TR>/<TD> tags must not
        produce empty runs in the cells.  Real-world DOT files
        typically format tables with newlines for readability."""
        lbl = parse_html_label(
            "<<TABLE>\n"
            "  <TR>\n"
            "    <TD>A</TD>\n"
            "    <TD>B</TD>\n"
            "  </TR>\n"
            "</TABLE>>"
        )
        t = lbl.table
        assert len(t.rows) == 1
        for cell in t.rows[0].cells:
            texts = [r.text for r in cell.lines[0].runs]
            # Cell should contain exactly one non-whitespace run.
            non_ws = [t for t in texts if t.strip()]
            assert len(non_ws) == 1

    def test_label_not_table_does_not_set_table(self):
        lbl = parse_html_label("<just plain text>")
        assert lbl.table is None
        assert lbl.lines[0].runs[0].text == "just plain text"


# ── Sizing ──────────────────────────────────────────────────────────


class TestTableSize:
    def test_col_widths_are_per_column_maxima(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>x</TD><TD>longer text</TD></TR>"
            "<TR><TD>wider text here</TD><TD>y</TD></TR></TABLE>>"
        )
        size_html_table(lbl.table)
        t = lbl.table
        assert len(t.col_widths) == 2
        # Col 0 width is driven by "wider text here"; col 1 by "longer text".
        assert t.col_widths[0] > t.col_widths[1] or t.col_widths[0] > 40

    def test_row_heights_are_per_row_maxima(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD><FONT POINT-SIZE="8">small</FONT></TD>'
            '<TD><FONT POINT-SIZE="24">big</FONT></TD></TR></TABLE>>'
        )
        size_html_table(lbl.table)
        # Single row: row height driven by the largest cell (24 pt font).
        assert len(lbl.table.row_heights) == 1
        assert lbl.table.row_heights[0] > 24.0

    def test_cells_placed_left_to_right(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>A</TD><TD>B</TD><TD>C</TD></TR></TABLE>>"
        )
        size_html_table(lbl.table)
        xs = [c.x for c in lbl.table.rows[0].cells]
        assert xs[0] < xs[1] < xs[2]

    def test_cells_placed_top_to_bottom(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>A</TD></TR><TR><TD>B</TD></TR></TABLE>>"
        )
        size_html_table(lbl.table)
        y0 = lbl.table.rows[0].cells[0].y
        y1 = lbl.table.rows[1].cells[0].y
        assert y0 < y1

    def test_cellspacing_increases_total_size(self):
        small = parse_html_label(
            '<<TABLE CELLSPACING="0"><TR><TD>A</TD><TD>B</TD></TR></TABLE>>'
        )
        big = parse_html_label(
            '<<TABLE CELLSPACING="20"><TR><TD>A</TD><TD>B</TD></TR></TABLE>>'
        )
        w_s, _ = html_label_size(small)
        w_b, _ = html_label_size(big)
        assert w_b > w_s

    def test_border_included_in_total_size(self):
        b0 = parse_html_label(
            '<<TABLE BORDER="0"><TR><TD>A</TD></TR></TABLE>>'
        )
        b5 = parse_html_label(
            '<<TABLE BORDER="5"><TR><TD>A</TD></TR></TABLE>>'
        )
        w0, _ = html_label_size(b0)
        w5, _ = html_label_size(b5)
        assert w5 > w0

    def test_nested_table_sizes_cell(self):
        """A cell containing a nested 3×3 table should be at least as
        wide as the nested table itself."""
        lbl = parse_html_label(
            "<<TABLE><TR><TD>tiny</TD><TD>"
            "<TABLE><TR>"
            "<TD>aaaaaa</TD><TD>bbbbbb</TD><TD>cccccc</TD>"
            "</TR></TABLE>"
            "</TD></TR></TABLE>>"
        )
        size_html_table(lbl.table)
        outer = lbl.table
        # Second cell (with nested) is wider than first (with just "tiny").
        c0, c1 = outer.rows[0].cells
        assert c1.width > c0.width


# ── Rendering ───────────────────────────────────────────────────────


class TestTableRender:
    """Asserts the shape of the SVG emitted for a small table.

    Callers include node / cluster / edge / xlabel label paths; each
    wraps the output from :func:`_render_html_text`, so testing that
    function directly covers every site.
    """

    def _render(self, label: str, *, cx: float = 100.0, cy: float = 100.0,
                default_size: float = 14.0) -> str:
        from gvpy.render.svg_renderer import _render_html_text
        return _render_html_text(
            cx, cy, label,
            default_face="Times-Roman",
            default_size=default_size,
            default_color="#000000",
        )

    def test_emits_rect_per_cell(self):
        # Table has BORDER=1 (outer rect) + cells have CELLBORDER=1
        # (one rect each).  2×2 table → 1 outer + 4 cell = 5 rects.
        out = self._render(
            '<<TABLE CELLBORDER="1"><TR>'
            '<TD>A</TD><TD>B</TD></TR>'
            '<TR><TD>C</TD><TD>D</TD></TR></TABLE>>'
        )
        assert out.count("<rect") >= 5

    def test_emits_one_text_per_cell(self):
        out = self._render(
            "<<TABLE><TR><TD>A</TD><TD>B</TD></TR></TABLE>>"
        )
        assert out.count("<text") == 2

    def test_cell_bgcolor_appears_as_fill(self):
        out = self._render(
            '<<TABLE><TR><TD BGCOLOR="#ff00ff">x</TD></TR></TABLE>>'
        )
        assert 'fill="#ff00ff"' in out

    def test_table_bgcolor_appears_as_fill(self):
        out = self._render(
            '<<TABLE BGCOLOR="#00ffff"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert 'fill="#00ffff"' in out

    def test_border_stroke_width_emitted(self):
        out = self._render(
            '<<TABLE BORDER="3"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert 'stroke-width="3"' in out

    def test_left_align_uses_start_anchor(self):
        out = self._render(
            '<<TABLE CELLBORDER="0"><TR>'
            '<TD ALIGN="LEFT">L</TD></TR></TABLE>>'
        )
        assert 'text-anchor="start"' in out

    def test_right_align_uses_end_anchor(self):
        out = self._render(
            '<<TABLE CELLBORDER="0"><TR>'
            '<TD ALIGN="RIGHT">R</TD></TR></TABLE>>'
        )
        assert 'text-anchor="end"' in out

    def test_cell_inline_b_becomes_bold(self):
        out = self._render(
            "<<TABLE><TR><TD><B>bold</B></TD></TR></TABLE>>"
        )
        assert 'font-weight="bold"' in out

    def test_multi_line_cell_uses_dy(self):
        out = self._render(
            "<<TABLE><TR><TD>one<BR/>two</TD></TR></TABLE>>"
        )
        assert "dy=" in out


# ── End-to-end: html_tables.dot ─────────────────────────────────────


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "test_data"
         / "html_tables.dot").exists(),
    reason="html_tables.dot fixture missing",
)
class TestEndToEndHtmlTables:
    @pytest.fixture(scope="class")
    def svg(self) -> str:
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        from gvpy.render.svg_renderer import render_svg
        path = (Path(__file__).resolve().parents[1]
                / "test_data" / "html_tables.dot")
        g = read_dot_file(str(path))
        return render_svg(DotLayout(g).layout())

    def _node(self, svg: str, node_id: str, before: int = 1000) -> str:
        open_idx = svg.find(f'id="{node_id}"')
        assert open_idx >= 0, f"node {node_id} missing from SVG"
        close_idx = svg.find("</g>", open_idx)
        assert close_idx > open_idx
        return svg[open_idx:close_idx]

    def test_simple_table_emits_cells(self, svg):
        win = self._node(svg, "node_t_simple")
        # 4 cells × 1 text each = 4 texts.
        assert win.count("<text") == 4
        for letter in "ABCD":
            assert f">{letter}<" in win

    def test_header_cells_have_bgcolor(self, svg):
        win = self._node(svg, "node_t_header")
        assert 'fill="#d0d0d0"' in win
        # Bold wrap on header values.
        assert 'font-weight="bold"' in win

    def test_align_grid_emits_start_and_end_anchors(self, svg):
        win = self._node(svg, "node_t_align")
        # LEFT and RIGHT cells carry explicit anchors.
        assert 'text-anchor="start"' in win
        assert 'text-anchor="end"' in win

    def test_styled_table_carries_font_size_override(self, svg):
        win = self._node(svg, "node_t_styled")
        assert 'font-size="18' in win   # Title
        assert 'font-size="10' in win   # subtitle
        assert 'baseline-shift="super"' in win  # mc²

    def test_borderless_table_has_no_border_stroke(self, svg):
        """BORDER=0 / CELLBORDER=0 should not emit a stroked outer
        rect — only the cell texts survive."""
        win = self._node(svg, "node_t_borderless")
        assert ">key:<" in win
        assert ">value<" in win

    def test_nested_table_has_inner_cells(self, svg):
        win = self._node(svg, "node_t_nested")
        for t in ("outer-left", "in-a", "in-b", "in-c", "in-d"):
            assert f">{t}<" in win, f"{t} not rendered"

    def test_edge_label_can_be_a_table(self, svg):
        # The a1 -> a2 edge (t_simple -> t_header) has a table label.
        assert ">edge<" in svg
        assert ">label<" in svg
        # The edge-table has a BGCOLOR="#ffffcc" background.
        assert 'fill="#ffffcc"' in svg
