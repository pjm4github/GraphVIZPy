"""Tests for HTML-label PORT support and mixed-content cells.

TODO §9 #6 (``PORT`` on TABLE and TD — cells addressable via
``node:port`` from edges) and §9 #4 (text + nested table + text in
one cell).  End-to-end fixture lives at
``test_data/html_port_mixed.dot``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gvpy.grammar.html_label import (
    HtmlImage,
    HtmlTable,
    HtmlLine,
    _cell_is_mixed,
    _iter_paragraph_groups,
    find_html_port,
    html_port_center,
    html_port_fraction,
    parse_html_label,
    size_html_table,
)


REPO = Path(__file__).resolve().parents[1]


# ── PORT parse ──────────────────────────────────────────────────────


class TestParsePort:
    def test_td_port_attribute_captured(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD PORT="p0">x</TD></TR></TABLE>>'
        )
        assert lbl.table.rows[0].cells[0].port == "p0"

    def test_table_port_attribute_captured(self):
        lbl = parse_html_label(
            '<<TABLE PORT="self"><TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.port == "self"

    def test_missing_port_defaults_to_none(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD>x</TD></TR></TABLE>>'
        )
        assert lbl.table.rows[0].cells[0].port is None


# ── PORT lookup / fraction ──────────────────────────────────────────


class TestFindPort:
    def _sized(self, label: str):
        lbl = parse_html_label(label)
        size_html_table(lbl.table)
        return lbl.table

    def test_find_port_returns_named_cell(self):
        t = self._sized(
            '<<TABLE><TR>'
            '<TD PORT="a">A</TD>'
            '<TD PORT="b">B</TD></TR></TABLE>>'
        )
        cell = find_html_port(t, "b")
        assert cell is not None and cell.lines[0].runs[0].text == "B"

    def test_find_port_in_nested_subtable(self):
        t = self._sized(
            '<<TABLE><TR>'
            '<TD>outer</TD>'
            '<TD><TABLE><TR><TD PORT="inner">deep</TD></TR></TABLE></TD>'
            '</TR></TABLE>>'
        )
        cell = find_html_port(t, "inner")
        assert cell is not None and cell.lines[0].runs[0].text == "deep"

    def test_find_port_missing_returns_none(self):
        t = self._sized('<<TABLE><TR><TD>x</TD></TR></TABLE>>')
        assert find_html_port(t, "nope") is None

    def test_port_center_inside_cell_bounds(self):
        t = self._sized(
            '<<TABLE><TR><TD PORT="p">hello</TD>'
            '<TD PORT="q">world</TD></TR></TABLE>>'
        )
        cx, cy = html_port_center(t, "p")
        # Centre is inside the table's bbox.
        assert 0 <= cx <= t.width and 0 <= cy <= t.height
        # Two distinct ports on the same row have different x.
        cx2, _ = html_port_center(t, "q")
        assert cx2 != cx

    def test_port_fraction_ordered_left_to_right_rankdir_lr(self):
        """With LR rankdir (1), cells laid out horizontally in the
        HTML table end up with increasing fraction values — matches
        the mincross port ordering convention."""
        t = self._sized(
            '<<TABLE><TR>'
            '<TD PORT="a">A</TD>'
            '<TD PORT="b">B</TD>'
            '<TD PORT="c">C</TD></TR></TABLE>>'
        )
        fa = html_port_fraction(t, "a", rankdir=1)
        fb = html_port_fraction(t, "b", rankdir=1)
        fc = html_port_fraction(t, "c", rankdir=1)
        assert fa is not None and fb is not None and fc is not None
        # All fractions in [0, 1).
        for f in (fa, fb, fc):
            assert 0.0 <= f < 1.0

    def test_port_fraction_unknown_returns_none(self):
        t = self._sized('<<TABLE><TR><TD PORT="a">x</TD></TR></TABLE>>')
        assert html_port_fraction(t, "nope") is None


# ── PORT wired into mincross ───────────────────────────────────────


class TestPortInLayout:
    """Layout integration — the parsed HTML table must be stashed on
    the Node so mincross can look up port fractions during ordering.
    """

    def test_html_table_stored_on_node_after_layout(self):
        from gvpy.grammar.gv_reader import read_dot
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        g = read_dot(
            'digraph G { '
            'n [shape=plaintext, label=<'
            '<TABLE><TR><TD PORT="a">A</TD>'
            '<TD PORT="b">B</TD></TR></TABLE>>]; '
            'x [label="x"]; '
            'x -> n:a; '
            '}'
        )
        DotLayout(g).layout()
        node = g.nodes["n"]
        assert node.html_table is not None
        assert find_html_port(node.html_table, "a") is not None


# ── Mixed-content cells ─────────────────────────────────────────────


class TestMixedContent:
    def _sized(self, label: str):
        lbl = parse_html_label(label)
        size_html_table(lbl.table)
        return lbl.table

    def test_cell_blocks_populated_for_text_only(self):
        t = self._sized(
            "<<TABLE><TR><TD>a<BR/>b</TD></TR></TABLE>>"
        )
        cell = t.rows[0].cells[0]
        # Two HtmlLine blocks.
        assert len(cell.blocks) == 2
        assert all(isinstance(b, HtmlLine) for b in cell.blocks)
        # Single-kind content → not "mixed".
        assert not _cell_is_mixed(cell)

    def test_cell_blocks_populated_for_nested_table(self):
        t = self._sized(
            "<<TABLE><TR><TD><TABLE><TR><TD>inner</TD></TR></TABLE></TD></TR></TABLE>>"
        )
        cell = t.rows[0].cells[0]
        # Just the subtable.
        assert len(cell.blocks) == 1
        assert isinstance(cell.blocks[0], HtmlTable)
        assert not _cell_is_mixed(cell)

    def test_mixed_cell_detected(self):
        t = self._sized(
            "<<TABLE><TR><TD>caption<TABLE><TR><TD>inner</TD></TR></TABLE>footer</TD></TR></TABLE>>"
        )
        cell = t.rows[0].cells[0]
        assert _cell_is_mixed(cell)

    def test_iter_paragraph_groups_folds_contiguous_lines(self):
        t = self._sized(
            "<<TABLE><TR><TD>a<BR/>b<TABLE><TR><TD>x</TD></TR></TABLE>c</TD></TR></TABLE>>"
        )
        groups = _iter_paragraph_groups(t.rows[0].cells[0].blocks)
        kinds = [g[0] for g in groups]
        # caption (a + BR + b) + inner table + footer (c).
        assert kinds == ["paragraph", "table", "paragraph"]

    def test_mixed_cell_sizing_includes_all_blocks(self):
        """A mixed cell's content_h must be at least the sum of its
        block heights (caption height + subtable height + footer
        height) — not just the caption or the subtable alone."""
        t = self._sized(
            '<<TABLE><TR><TD>'
            'caption'
            '<TABLE BORDER="0" CELLBORDER="0"><TR><TD>A</TD></TR>'
            '<TR><TD>B</TD></TR><TR><TD>C</TD></TR></TABLE>'
            'footer'
            '</TD></TR></TABLE>>'
        )
        cell = t.rows[0].cells[0]
        # Bigger than a single-line paragraph would be.
        assert cell.content_h > 60.0

    def test_mixed_cell_renders_all_blocks(self):
        """The renderer should emit text for ``caption``, the sub-
        table cells, and ``footer`` — all within a single TD's SVG."""
        from gvpy.render.svg_renderer import _render_html_text
        out = _render_html_text(
            100.0, 100.0,
            '<<TABLE><TR><TD>caption'
            '<TABLE BORDER="0" CELLBORDER="1"><TR><TD>x</TD><TD>y</TD></TR></TABLE>'
            'footer</TD></TR></TABLE>>',
            default_face="Times-Roman", default_size=14.0,
            default_color="#000000",
        )
        assert ">caption<" in out
        assert ">x<" in out and ">y<" in out
        assert ">footer<" in out


# ── End-to-end fixture ──────────────────────────────────────────────


@pytest.mark.skipif(
    not (REPO / "test_data" / "html_port_mixed.dot").exists(),
    reason="html_port_mixed.dot fixture missing",
)
class TestEndToEndHtmlPortMixed:
    @pytest.fixture(scope="class")
    def svg(self) -> str:
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        from gvpy.render.svg_renderer import render_svg
        g = read_dot_file(str(REPO / "test_data" / "html_port_mixed.dot"))
        return render_svg(DotLayout(g).layout())

    def _node(self, svg: str, node_id: str) -> str:
        open_idx = svg.find(f'id="{node_id}"')
        assert open_idx >= 0, f"node {node_id} missing from SVG"
        depth = 1
        i = svg.index(">", open_idx) + 1
        while depth > 0 and i < len(svg):
            a = svg.find("<g", i)
            b = svg.find("</g>", i)
            if b < 0:
                break
            if 0 <= a < b:
                depth += 1
                i = a + 2
            else:
                depth -= 1
                i = b + 4
        return svg[open_idx:i]

    def test_form_node_has_all_three_cells(self, svg):
        win = self._node(svg, "node_form")
        # name + age + submit.
        for t in ("name", "age", "submit"):
            assert f">{t}<" in win

    def test_port_cells_carry_bgcolor(self, svg):
        win = self._node(svg, "node_form")
        assert 'fill="#f0fdf4"' in win   # name
        assert 'fill="#eff6ff"' in win   # age
        assert 'fill="#fef3c7"' in win   # submit

    def test_form_html_table_has_ports_on_node(self):
        """Load the DOT directly and verify ``Node.html_table``
        persists the PORT metadata after layout."""
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        g = read_dot_file(str(REPO / "test_data" / "html_port_mixed.dot"))
        DotLayout(g).layout()
        node = g.nodes["form"]
        assert node.html_table is not None
        for name in ("in_name", "in_age", "out_ok"):
            assert find_html_port(node.html_table, name) is not None

    def test_card_node_shows_mixed_content(self, svg):
        """The ``card`` node has caption + sub-table + footer inside
        one TD — all three pieces must render."""
        win = self._node(svg, "node_card")
        assert ">Project Status<" in win
        assert ">Task<" in win and ">State<" in win
        assert ">design<" in win and ">done<" in win
        assert ">review<" in win and ">wip<" in win
        assert ">updated 2026-04-22<" in win

    def test_card_subtable_cells_carry_bgcolors(self, svg):
        win = self._node(svg, "node_card")
        assert 'fill="#dcfce7"' in win   # done cell
        assert 'fill="#fef3c7"' in win   # wip cell
