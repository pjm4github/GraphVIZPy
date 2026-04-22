"""Tests for HTML-like-label spec-completeness items.

Covers the spec-gap cleanup picked up in the 2026-04-21 pass:

- ``<O>`` renders as overline, not underline (#1 in the compat table).
- ``<VR/>`` between cells + inter-row ``<HR/>`` + ROWS/COLUMNS auto
  rules (#2).
- ``WIDTH`` / ``HEIGHT`` / ``FIXEDSIZE`` on TABLE and TD (#5).
- ``SIDES`` on TABLE for partial outer borders (#7).
- ``ALIGN="TEXT"`` on TD preserves per-line alignment (#8).
- COLSPAN / ROWSPAN proportional / weighted growth (#11).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gvpy.grammar.html_label import (
    parse_html_label,
    size_html_table,
)
from gvpy.render.svg_renderer import _render_html_text


# ── Helpers ─────────────────────────────────────────────────────────


def _render(label: str) -> str:
    return _render_html_text(
        100.0, 100.0, label,
        default_face="Times-Roman", default_size=14.0,
        default_color="#000000",
    )


# ── 1. <O> overline ─────────────────────────────────────────────────


class TestOverline:
    def test_o_tag_parsed_as_overline(self):
        lbl = parse_html_label("<<O>top</O>>")
        run = lbl.lines[0].runs[0]
        assert run.overline is True
        assert run.underline is False

    def test_overline_renders_as_text_decoration(self):
        out = _render("<<TABLE><TR><TD><O>x</O></TD></TR></TABLE>>")
        assert 'text-decoration="overline"' in out

    def test_combined_o_and_u_emits_both_decorations(self):
        out = _render("<<TABLE><TR><TD><O><U>x</U></O></TD></TR></TABLE>>")
        # SVG accepts space-separated decoration values.
        m = re.search(r'text-decoration="([^"]+)"', out)
        assert m is not None
        decos = set(m.group(1).split())
        assert {"underline", "overline"} <= decos

    def test_overline_does_not_emit_underline(self):
        out = _render("<<TABLE><TR><TD><O>x</O></TD></TR></TABLE>>")
        # Regression: an <O> label with no <U> must not quietly fall
        # through to underline.
        assert 'text-decoration="underline"' not in out


# ── 2. VR / HR / ROWS=* / COLUMNS=* ─────────────────────────────────


class TestRules:
    def _table(self, label: str):
        lbl = parse_html_label(label)
        size_html_table(lbl.table)
        return lbl.table

    def test_vr_marks_preceding_cell(self):
        t = self._table(
            "<<TABLE><TR><TD>a</TD><VR/><TD>b</TD></TR></TABLE>>"
        )
        cells = t.rows[0].cells
        assert cells[0].vr_after is True
        assert cells[1].vr_after is False

    def test_inter_row_hr_flags_next_tr(self):
        t = self._table(
            "<<TABLE>"
            "<TR><TD>a</TD></TR>"
            "<HR/>"
            "<TR><TD>b</TD></TR>"
            "</TABLE>>"
        )
        assert t.rows[0].hr_before is False
        assert t.rows[1].hr_before is True

    def test_rows_star_sets_rows_rule(self):
        t = self._table(
            '<<TABLE ROWS="*"><TR><TD>a</TD></TR>'
            '<TR><TD>b</TD></TR></TABLE>>'
        )
        assert t.rows_rule is True

    def test_columns_star_sets_columns_rule(self):
        t = self._table(
            '<<TABLE COLUMNS="*"><TR><TD>a</TD><TD>b</TD></TR></TABLE>>'
        )
        assert t.columns_rule is True

    def test_vr_emits_line_in_svg(self):
        out = _render(
            "<<TABLE CELLBORDER=\"0\"><TR>"
            "<TD>a</TD><VR/><TD>b</TD></TR></TABLE>>"
        )
        assert out.count("<line") == 1
        # VR is vertical — x1 == x2.
        m = re.search(
            r'<line x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', out)
        assert m and m.group(1) == m.group(2)

    def test_hr_between_rows_emits_horizontal_line(self):
        out = _render(
            "<<TABLE CELLBORDER=\"0\">"
            "<TR><TD>a</TD></TR><HR/>"
            "<TR><TD>b</TD></TR></TABLE>>"
        )
        assert "<line" in out
        # HR is horizontal — y1 == y2.
        m = re.search(
            r'<line x1="[\d.]+" y1="([\d.]+)" x2="[\d.]+" y2="([\d.]+)"',
            out)
        assert m and m.group(1) == m.group(2)

    def test_columns_star_draws_vr_between_every_cell(self):
        out = _render(
            '<<TABLE COLUMNS="*" CELLBORDER="0" CELLSPACING="4">'
            '<TR><TD>a</TD><TD>b</TD><TD>c</TD></TR></TABLE>>'
        )
        # 3 cells → 2 VR boundaries.
        assert out.count("<line") == 2

    def test_rows_star_draws_hr_between_every_row(self):
        out = _render(
            '<<TABLE ROWS="*" CELLBORDER="0">'
            '<TR><TD>a</TD></TR>'
            '<TR><TD>b</TD></TR>'
            '<TR><TD>c</TD></TR></TABLE>>'
        )
        # 3 rows → 2 HR boundaries.
        assert out.count("<line") == 2


# ── 5. WIDTH / HEIGHT / FIXEDSIZE ───────────────────────────────────


class TestFixedSize:
    def _table(self, label: str):
        lbl = parse_html_label(label)
        size_html_table(lbl.table)
        return lbl.table

    def test_width_parsed_as_float(self):
        t = self._table(
            '<<TABLE><TR><TD WIDTH="80">x</TD></TR></TABLE>>'
        )
        assert t.rows[0].cells[0].width_min == 80.0

    def test_height_parsed_as_float(self):
        t = self._table(
            '<<TABLE><TR><TD HEIGHT="60">x</TD></TR></TABLE>>'
        )
        assert t.rows[0].cells[0].height_min == 60.0

    def test_fixedsize_true_parsed(self):
        t = self._table(
            '<<TABLE><TR><TD FIXEDSIZE="TRUE">x</TD></TR></TABLE>>'
        )
        assert t.rows[0].cells[0].fixedsize is True

    def test_min_width_expands_short_content(self):
        """A ``WIDTH="200"`` cell whose natural content is much
        narrower should still have content_w >= 200."""
        t = self._table(
            '<<TABLE><TR><TD WIDTH="200">x</TD></TR></TABLE>>'
        )
        assert t.rows[0].cells[0].content_w >= 200.0

    def test_min_height_expands_short_content(self):
        t = self._table(
            '<<TABLE><TR><TD HEIGHT="80">x</TD></TR></TABLE>>'
        )
        assert t.rows[0].cells[0].content_h >= 80.0

    def test_min_width_does_not_shrink_wide_content(self):
        """When natural content is wider than WIDTH, content_w should
        use the natural size (min acts as a lower bound)."""
        wide_text = "x" * 60
        t = self._table(
            f'<<TABLE><TR><TD WIDTH="10">{wide_text}</TD></TR></TABLE>>'
        )
        cell = t.rows[0].cells[0]
        # Content is far wider than 10pt — cell follows natural.
        assert cell.content_w > 50.0

    def test_fixedsize_clamps_to_declared_width(self):
        """With FIXEDSIZE=TRUE the cell's content_w becomes exactly
        WIDTH regardless of natural content size."""
        t = self._table(
            '<<TABLE><TR><TD WIDTH="40" HEIGHT="20" FIXEDSIZE="TRUE">'
            'very long content that would normally take up much more space'
            '</TD></TR></TABLE>>'
        )
        cell = t.rows[0].cells[0]
        assert cell.content_w == 40.0
        assert cell.content_h == 20.0

    def test_table_width_minimum_expands_columns(self):
        """``TABLE WIDTH="500"`` should grow the computed table width
        to at least 500 points, regardless of cell content."""
        t = self._table(
            '<<TABLE WIDTH="500"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert t.width >= 500.0


# ── 7. SIDES on TABLE ───────────────────────────────────────────────


class TestTableSides:
    def test_table_sides_parsed(self):
        lbl = parse_html_label(
            '<<TABLE SIDES="TB"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert set(lbl.table.sides) == {"T", "B"}

    def test_table_sides_renders_only_named_segments(self):
        """With ``SIDES="TB"`` the outer frame emits the fill rect
        plus two line segments — top and bottom."""
        out = _render(
            '<<TABLE BORDER="2" SIDES="TB" CELLBORDER="0">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        # 1 table rect (fill, no stroke) + 2 outer-side lines (T, B).
        # No cell border (CELLBORDER=0), no cell bgcolor — no cell rect.
        assert out.count("<line") == 2

    def test_table_sides_r_only_emits_one_outer_line(self):
        out = _render(
            '<<TABLE BORDER="2" SIDES="R" CELLBORDER="0">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        assert out.count("<line") == 1


# ── 8. ALIGN="TEXT" ─────────────────────────────────────────────────


class TestAlignText:
    def test_align_text_preserves_per_line_alignment(self):
        """Cell ALIGN="TEXT" should not override line.align when line
        is implicitly center — each line keeps its own.  With a
        BR ALIGN="LEFT" and BR ALIGN="RIGHT", the output must carry
        both ``text-anchor="start"`` and ``text-anchor="end"``.
        """
        out = _render(
            '<<TABLE CELLBORDER="1"><TR>'
            '<TD ALIGN="TEXT">default'
            '<BR ALIGN="LEFT"/>left'
            '<BR ALIGN="RIGHT"/>right'
            '</TD></TR></TABLE>>'
        )
        assert 'text-anchor="start"' in out
        assert 'text-anchor="end"' in out
        # The first line (no explicit align) stays centre — middle
        # anchor inherited from the root element.
        assert 'text-anchor="middle"' in out

    def test_align_text_distinct_from_align_center(self):
        """With ALIGN="CENTER" all lines anchor centre (start/end
        text-anchors should still appear for the explicit BR lines)."""
        out = _render(
            '<<TABLE CELLBORDER="1"><TR>'
            '<TD ALIGN="CENTER">default'
            '<BR ALIGN="LEFT"/>left'
            '</TD></TR></TABLE>>'
        )
        assert 'text-anchor="start"' in out

    def test_align_right_forces_default_lines_to_right(self):
        """Baseline: without ALIGN="TEXT" and no BALIGN, a non-BR-
        aligned line in an ``ALIGN="RIGHT"`` cell should anchor end."""
        out = _render(
            '<<TABLE CELLBORDER="1"><TR>'
            '<TD ALIGN="RIGHT">default'
            '</TD></TR></TABLE>>'
        )
        assert 'text-anchor="end"' in out


# ── 11. Weighted COLSPAN / ROWSPAN growth ───────────────────────────


class TestWeightedGrowth:
    def _table(self, label: str):
        lbl = parse_html_label(label)
        size_html_table(lbl.table)
        return lbl.table

    def test_wide_colspan_distributes_proportionally(self):
        """When the spanning cell's natural width exceeds the sum of
        the two columns it covers, the extra is split proportionally
        to existing column widths — the wider column absorbs more."""
        t = self._table(
            '<<TABLE CELLSPACING="0"><TR>'
            '<TD COLSPAN="2">'
            'this header is much wider than the cells below combined'
            '</TD></TR>'
            '<TR>'
            '<TD>x</TD>'          # narrow
            '<TD>much wider column content than the first cell</TD>'
            '</TR></TABLE>>'
        )
        # The wider second column absorbs more of the span extra
        # than the narrow first.
        c0_w, c1_w = t.col_widths[0], t.col_widths[1]
        assert c1_w > c0_w
        # Sanity: c1 is at least ~1.5× c0, reflecting the proportional
        # split (and the second column's larger natural content).
        assert c1_w > c0_w * 1.5

    def test_all_zero_columns_fall_back_to_even_split(self):
        """When every spanned column has zero natural width, the
        extra is split evenly (guards a zero-division in the
        proportional formula)."""
        # A table where row-2 cells are non-existent — only the
        # spanning cell itself drives column widths.  Both columns
        # have 0 natural width before the span distributes.
        t = self._table(
            '<<TABLE CELLSPACING="0"><TR>'
            '<TD COLSPAN="2">hdr</TD>'
            '</TR></TABLE>>'
        )
        # Each column gets half the span's content width.
        assert abs(t.col_widths[0] - t.col_widths[1]) < 0.01


# ── End-to-end fixture ──────────────────────────────────────────────


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "test_data"
         / "html_spec.dot").exists(),
    reason="html_spec.dot fixture missing",
)
class TestEndToEndHtmlSpec:
    @pytest.fixture(scope="class")
    def svg(self) -> str:
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        from gvpy.render.svg_renderer import render_svg
        path = (Path(__file__).resolve().parents[1]
                / "test_data" / "html_spec.dot")
        g = read_dot_file(str(path))
        return render_svg(DotLayout(g).layout())

    def _node(self, svg: str, node_id: str) -> str:
        open_idx = svg.find(f'id="{node_id}"')
        assert open_idx >= 0, f"node {node_id} missing from SVG"
        close_idx = svg.find("</g>", open_idx)
        assert close_idx > open_idx
        return svg[open_idx:close_idx]

    def test_overline_node_emits_overline(self, svg):
        win = self._node(svg, "node_t_overline")
        assert 'text-decoration="overline"' in win

    def test_rules_node_emits_both_vr_and_hr(self, svg):
        win = self._node(svg, "node_t_rules")
        # 2 VRs per row × 2 rows + 1 HR between rows = 5 <line>s.
        assert win.count("<line") == 5

    def test_starstar_node_emits_grid_of_rules(self, svg):
        win = self._node(svg, "node_t_starstar")
        # ROWS="*" on a 3-row table → 2 HR; COLUMNS="*" on 3-col ×
        # 3 rows → 6 VRs.  Total 8.
        assert win.count("<line") == 8

    def test_minsize_node_has_wide_cell(self, svg):
        win = self._node(svg, "node_t_minsize")
        # The first cell has WIDTH=80 — find rects and verify at
        # least one is ≥ 80 wide.
        widths = [float(m) for m in
                  re.findall(r'<rect [^>]*\swidth="([\d.]+)"', win)]
        assert any(w >= 80.0 for w in widths)

    def test_fixed_node_clamps_content_cell(self, svg):
        """The FIXEDSIZE cell has WIDTH=50 but content that would
        normally take much more space — verify its rect is ≤ 60pt
        wide (allowing a bit of cellpadding slack)."""
        win = self._node(svg, "node_t_fixed")
        # Find the <rect> with the smallest non-outer width ≥ 40;
        # that's the fixedsize cell.
        widths = [float(m) for m in
                  re.findall(r'<rect [^>]*\swidth="([\d.]+)"', win)]
        # The fixedsize cell should be ~50pt.
        small = [w for w in widths if w < 80]
        assert any(abs(w - 50.0) < 5.0 for w in small)

    def test_outer_sides_node_has_no_vertical_frame(self, svg):
        win = self._node(svg, "node_t_outer_sides")
        # SIDES="TB" on TABLE → 2 outer lines.  CELLBORDER=0 and no
        # VR/HR → no extra lines.
        assert win.count("<line") == 2

    def test_align_text_node_carries_mixed_anchors(self, svg):
        win = self._node(svg, "node_t_align_text")
        assert 'text-anchor="start"' in win
        assert 'text-anchor="end"' in win

    def test_weighted_node_renders(self, svg):
        win = self._node(svg, "node_t_weighted")
        # Sanity — the header text and row-2 texts are all present.
        assert ">x<" in win
        # The header is a COLSPAN=2 cell whose rect spans both cols.
        assert "<rect" in win
