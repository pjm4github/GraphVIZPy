"""Tests for HTML-label Phase 4+ style extensions.

Covers TODO §9 items #2 (STYLE="rounded" / "radial" + GRADIENTANGLE),
#5 (SIDES on TD), #7 (BALIGN + ALIGN="TEXT" on TD), and #8 (HR
inside cells).  Structure mirrors ``tests/test_html_table.py``:

- ``TestParseStyle`` — AST attributes carried from the HTML parser.
- ``TestRenderStyle`` — STYLE → rounded rect / gradient defs.
- ``TestRenderSides`` — SIDES → partial border line segments.
- ``TestRenderBalign`` — BALIGN propagation + cell-vs-line precedence.
- ``TestRenderHr`` — ``<HR/>`` emits a ``<line>`` element.
- ``TestEndToEndHtmlStyle`` — loads ``test_data/html_style.dot``.
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


# ── Parser ──────────────────────────────────────────────────────────


class TestParseStyle:
    def test_table_style_rounded(self):
        lbl = parse_html_label(
            '<<TABLE STYLE="rounded"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.style == "rounded"

    def test_table_style_radial(self):
        lbl = parse_html_label(
            '<<TABLE STYLE="radial" BGCOLOR="red:blue">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.style == "radial"

    def test_gradientangle_parsed_as_float(self):
        lbl = parse_html_label(
            '<<TABLE GRADIENTANGLE="45" BGCOLOR="a:b">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.gradientangle == 45.0

    def test_unknown_style_ignored(self):
        """``STYLE="filled,dashed"`` (none of rounded/radial/solid)
        should parse to None, not raise."""
        lbl = parse_html_label(
            '<<TABLE STYLE="filled,dashed"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.style is None

    def test_cell_style_and_sides(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD STYLE="rounded" SIDES="TB">x</TD></TR></TABLE>>'
        )
        cell = lbl.table.rows[0].cells[0]
        assert cell.style == "rounded"
        assert cell.sides == "TB"

    def test_sides_default_full(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>x</TD></TR></TABLE>>"
        )
        assert lbl.table.rows[0].cells[0].sides == "LTRB"

    def test_sides_empty_string_defaults_to_full(self):
        """An empty SIDES attribute falls back to the default rather
        than silently turning off every border (the fixture uses
        ``SIDES=""`` as the explicit "no borders" case, but semantically
        that's the same sentinel Graphviz emits when the attribute
        isn't there — default wins)."""
        lbl = parse_html_label(
            '<<TABLE><TR><TD SIDES="">x</TD></TR></TABLE>>'
        )
        assert lbl.table.rows[0].cells[0].sides == "LTRB"

    def test_sides_normalised_to_uppercase_subset(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD SIDES="tRxB">x</TD></TR></TABLE>>'
        )
        # Drops 'x', uppercases 't' and 'b'.
        assert set(lbl.table.rows[0].cells[0].sides) == {"T", "R", "B"}

    def test_cell_balign_parsed(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD BALIGN="LEFT">a<BR/>b</TD></TR></TABLE>>'
        )
        cell = lbl.table.rows[0].cells[0]
        assert cell.balign == "left"
        # Line after <BR/> inherits balign when no explicit ALIGN.
        assert cell.lines[1].align == "left"

    def test_br_explicit_align_wins_over_balign(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD BALIGN="LEFT">'
            'a<BR ALIGN="RIGHT"/>b</TD></TR></TABLE>>'
        )
        cell = lbl.table.rows[0].cells[0]
        assert cell.lines[1].align == "right"

    def test_hr_emits_is_hr_line(self):
        lbl = parse_html_label(
            "<<TABLE><TR><TD>top<HR/>bottom</TD></TR></TABLE>>"
        )
        lines = lbl.table.rows[0].cells[0].lines
        assert any(l.is_hr for l in lines)
        # text before, rule, text after — at least 3 entries.
        assert len(lines) >= 3

    def test_hr_height_contributes_to_cell_size(self):
        """An HR line bumps the cell's natural content height by its
        stored ``height``."""
        without = parse_html_label(
            "<<TABLE><TR><TD>top<BR/>bottom</TD></TR></TABLE>>"
        )
        with_hr = parse_html_label(
            "<<TABLE><TR><TD>top<HR/>bottom</TD></TR></TABLE>>"
        )
        size_html_table(without.table)
        size_html_table(with_hr.table)
        assert with_hr.table.height > without.table.height


# ── Renderer: STYLE ─────────────────────────────────────────────────


class TestRenderStyle:
    def test_rounded_table_adds_rx_ry(self):
        out = _render(
            '<<TABLE STYLE="rounded" BORDER="1"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert 'rx="4.0" ry="4.0"' in out

    def test_plain_table_has_no_rx_ry(self):
        out = _render(
            "<<TABLE BORDER=\"1\"><TR><TD>x</TD></TR></TABLE>>"
        )
        assert 'rx=' not in out

    def test_rounded_cell_adds_rx_ry(self):
        out = _render(
            '<<TABLE CELLBORDER="1" CELLSPACING="0">'
            '<TR><TD STYLE="rounded">c</TD></TR></TABLE>>'
        )
        # Cell rect carries rx/ry — two rects (outer + cell); at least
        # one of them (the cell) is rounded.
        assert 'rx="4.0"' in out

    def test_radial_gradient_defs_emitted(self):
        out = _render(
            '<<TABLE STYLE="radial" BGCOLOR="#ff0000">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        assert '<radialGradient' in out
        assert 'fill="url(#' in out
        # Single colour radial fades to white.
        assert 'stop-color="white"' in out

    def test_linear_gradient_with_pair_and_angle(self):
        out = _render(
            '<<TABLE BGCOLOR="#fde68a:#f97316" GRADIENTANGLE="90">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        assert '<linearGradient' in out
        assert 'stop-color="#fde68a"' in out
        assert 'stop-color="#f97316"' in out

    def test_gradient_ids_unique_within_table(self):
        """A table with one gradient on the outer frame and one per
        cell must emit distinct gradient ids."""
        from gvpy.render.svg_renderer import _GRADIENT_COUNTER
        _GRADIENT_COUNTER[0] = 0
        out = _render(
            '<<TABLE STYLE="radial" BGCOLOR="#abcdef"><TR>'
            '<TD STYLE="radial" BGCOLOR="red:white">a</TD>'
            '<TD STYLE="radial" BGCOLOR="#112233">b</TD>'
            '</TR></TABLE>>'
        )
        ids = re.findall(r'id="(gvpyg\d+)"', out)
        assert len(ids) == len(set(ids)) >= 3


# ── Renderer: SIDES ─────────────────────────────────────────────────


class TestRenderSides:
    def test_full_sides_emits_single_rect(self):
        out = _render(
            '<<TABLE CELLBORDER="1" CELLSPACING="0">'
            '<TR><TD>x</TD></TR></TABLE>>'
        )
        # 1 outer + 1 cell rect; no <line> elements for borders.
        assert out.count("<rect") == 2
        assert out.count("<line") == 0

    def test_partial_sides_emits_line_segments(self):
        out = _render(
            '<<TABLE CELLBORDER="1" CELLSPACING="0">'
            '<TR><TD SIDES="TB">x</TD></TR></TABLE>>'
        )
        # Cell still has a rect (for fill/no-stroke), plus two lines
        # for top and bottom edges.
        assert out.count("<line") == 2

    def test_sides_r_only_emits_one_line(self):
        out = _render(
            '<<TABLE CELLBORDER="1" CELLSPACING="0">'
            '<TR><TD SIDES="R">x</TD></TR></TABLE>>'
        )
        assert out.count("<line") == 1

    def test_sides_missing_border_suppresses_line(self):
        """``SIDES="R"`` on a cell with ``CELLBORDER=1``: only the
        right edge draws a line; top/left/bottom are absent."""
        out = _render(
            '<<TABLE CELLBORDER="1" CELLSPACING="0">'
            '<TR><TD SIDES="R">x</TD></TR></TABLE>>'
        )
        # One and only one line — the right edge.  Check it's vertical
        # (x1 == x2) by matching the line attributes.
        m = re.search(
            r'<line x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)" y2="[\d.]+"',
            out)
        assert m and m.group(1) == m.group(2)


# ── Renderer: BALIGN ────────────────────────────────────────────────


class TestRenderBalign:
    def test_balign_left_uses_start_anchor(self):
        out = _render(
            '<<TABLE CELLBORDER="1" CELLSPACING="0">'
            '<TR><TD BALIGN="LEFT">a<BR/>b</TD></TR></TABLE>>'
        )
        # Both lines should anchor at start (left).  Expect at least
        # two distinct <text> elements with text-anchor="start".
        assert out.count('text-anchor="start"') >= 2

    def test_br_explicit_align_overrides_cell_align(self):
        """TD ALIGN="RIGHT" gives the cell right alignment; an inner
        BR ALIGN="LEFT" overrides that for the following line."""
        out = _render(
            '<<TABLE CELLBORDER="1" CELLSPACING="0">'
            '<TR><TD ALIGN="RIGHT">a<BR ALIGN="LEFT"/>b</TD>'
            '</TR></TABLE>>'
        )
        assert 'text-anchor="end"' in out
        assert 'text-anchor="start"' in out


# ── Renderer: HR ────────────────────────────────────────────────────


class TestRenderHr:
    def test_hr_emits_line_element(self):
        out = _render(
            "<<TABLE><TR><TD>top<HR/>bottom</TD></TR></TABLE>>"
        )
        # The only <line> in the output is the HR — there's no cell
        # border (default CELLBORDER inherits from BORDER=1, but a
        # SIDES="LTRB" full rect path doesn't emit <line>).
        assert out.count("<line") == 1
        assert ">top<" in out and ">bottom<" in out

    def test_hr_positioned_between_text_baselines(self):
        """The HR line's y should sit between the y of 'top' and
        the y of 'bottom'."""
        out = _render(
            "<<TABLE><TR><TD>top<HR/>bottom</TD></TR></TABLE>>"
        )
        m_top = re.search(r'y="([\d.]+)"[^>]*>top', out)
        m_bot = re.search(r'y="([\d.]+)"[^>]*>bottom', out)
        m_hr = re.search(r'<line [^>]*y1="([\d.]+)"', out)
        assert m_top and m_bot and m_hr
        yt, yb, yh = (float(m_top.group(1)),
                      float(m_bot.group(1)),
                      float(m_hr.group(1)))
        assert yt < yh < yb


# ── End-to-end fixture ──────────────────────────────────────────────


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "test_data"
         / "html_style.dot").exists(),
    reason="html_style.dot fixture missing",
)
class TestEndToEndHtmlStyle:
    @pytest.fixture(scope="class")
    def svg(self) -> str:
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        from gvpy.render.svg_renderer import render_svg
        path = (Path(__file__).resolve().parents[1]
                / "test_data" / "html_style.dot")
        g = read_dot_file(str(path))
        return render_svg(DotLayout(g).layout())

    def _node(self, svg: str, node_id: str) -> str:
        open_idx = svg.find(f'id="{node_id}"')
        assert open_idx >= 0, f"node {node_id} missing from SVG"
        close_idx = svg.find("</g>", open_idx)
        assert close_idx > open_idx
        return svg[open_idx:close_idx]

    def test_rounded_table_node(self, svg):
        win = self._node(svg, "node_t_rounded")
        assert 'rx="4.0"' in win

    def test_radial_node_has_gradient_ref(self, svg):
        win = self._node(svg, "node_t_radial")
        assert 'fill="url(#gvpyg' in win
        # The <defs> live inside this node's <g>.
        assert "<radialGradient" in win

    def test_linear_node_has_linear_gradient(self, svg):
        win = self._node(svg, "node_t_linear")
        assert "<linearGradient" in win

    def test_cell_radial_node_has_gradient(self, svg):
        win = self._node(svg, "node_t_cell_radial")
        assert "<radialGradient" in win
        assert 'stop-color="#0ea5e9"' in win

    def test_sides_node_emits_line_segments(self, svg):
        win = self._node(svg, "node_t_sides")
        # Row 1 cells: full, TB, R → 0 + 2 + 1 = 3 border lines.
        # Row 2 cells: L, none, B → 1 + 0 + 1 = 2 border lines.
        # Total: 5 border-line segments.
        assert win.count("<line") == 5
        # The "none" cell is still represented (fill rect even with
        # empty sides) — its text should appear.
        assert ">none<" in win

    def test_balign_node_has_left_and_right_anchors(self, svg):
        win = self._node(svg, "node_t_balign")
        # BALIGN="LEFT" (cell 1) + BALIGN="RIGHT" (cell 2) + mix cell.
        assert 'text-anchor="start"' in win
        assert 'text-anchor="end"' in win

    def test_hr_node_emits_horizontal_rules(self, svg):
        win = self._node(svg, "node_t_hr")
        # Two cells each have one <HR/>.  CELLBORDER=0 so the only
        # <line> elements are HRs.
        assert win.count("<line") == 2
        assert ">Heading<" in win
        assert ">fine print<" in win

    def test_combo_node_has_rounded_sides_balign_hr(self, svg):
        win = self._node(svg, "node_t_combo")
        assert 'rx="4.0"' in win           # rounded table
        assert "<line" in win              # HR + SIDES=B segments
        assert 'text-anchor="start"' in win  # BALIGN="LEFT"
        assert ">Title<" in win
