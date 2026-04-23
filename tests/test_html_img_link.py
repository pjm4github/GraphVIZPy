"""Tests for HTML-label IMG + hyperlink attributes.

Covers compatibility-table items:

- #3 ``<IMG SRC="…" SCALE="…"/>`` inside TD (natural-size probe,
  FALSE / TRUE / BOTH / WIDTH / HEIGHT modes, SVG emission).
- #4 HREF / TARGET / TITLE / TOOLTIP / ID on TABLE and TD (wraps
  in ``<a xlink:href>``, emits ``<title>``, sets ``<g id>``).

Structure mirrors ``tests/test_html_style.py`` — module-level
``_render`` helper, per-feature classes, and an end-to-end class
that renders ``test_data/html_img_link.dot``.  A shared fixture
generates the 40×40 solid-blue PNG at ``test_data/test_img.png``
so the fixture is self-contained even on a fresh checkout.
"""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

import pytest

from gvpy.grammar.html_label import (
    HtmlImage,
    _probe_image_size,
    parse_html_label,
    set_image_search_paths,
    size_html_table,
)
from gvpy.render.svg_renderer import _render_html_text


# ── Helpers ─────────────────────────────────────────────────────────


REPO = Path(__file__).resolve().parents[1]
# Use a dedicated filename for the generated 40×40 blue PNG so it
# can't collide with a user-supplied ``test_img.png`` (e.g. swapped
# in while rendering a real graph).  ``test_img.png`` stays the
# canonical name in the .dot fixture; it resolves via Graphviz's
# imagepath attribute and may legitimately differ between runs.
TEST_PNG_PATH = REPO / "test_data" / "_py_test_img.png"


def _write_40x40_blue_png(path: Path) -> None:
    W = H = 40
    row = bytes([0]) + bytes([32, 82, 217]) * W
    raw = row * H

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_image():
    """Write a 40×40 solid-blue PNG to ``test_data/_py_test_img.png``
    before any tests run.

    The file is (re)generated every session so a divergent image
    (e.g. someone replaced the test_data copy with a real asset)
    can't silently corrupt the size assertions — we own this file.
    """
    _write_40x40_blue_png(TEST_PNG_PATH)


def _render(label: str) -> str:
    return _render_html_text(
        100.0, 100.0, label,
        default_face="Times-Roman", default_size=14.0,
        default_color="#000000",
    )


# ── Image probing ───────────────────────────────────────────────────


class TestImageProbe:
    def test_probe_png_returns_pixel_size(self):
        w, h = _probe_image_size(str(TEST_PNG_PATH))
        assert (w, h) == (40.0, 40.0)

    def test_probe_missing_returns_zero(self):
        assert _probe_image_size(
            str(REPO / "test_data" / "does_not_exist.png")
        ) == (0.0, 0.0)

    def test_probe_unknown_format_returns_zero(self, tmp_path):
        p = tmp_path / "not_an_image.bin"
        p.write_bytes(b"This is just text, not a real image file.")
        assert _probe_image_size(str(p)) == (0.0, 0.0)


class TestImagePath:
    """The ``imagepath`` graph attribute lets the probe find relative
    SRC files outside CWD — matches Graphviz ``lib/common/usershape.c``.
    """

    def teardown_method(self):
        # Each test sets search paths; reset so the rest of the
        # suite sees the default CWD-only behaviour.
        set_image_search_paths(None)

    def test_search_path_allows_bare_src(self):
        """With ``test_data`` in the search path, ``test_img.png``
        resolves without a directory prefix."""
        set_image_search_paths([".", str(REPO / "test_data")])
        assert _probe_image_size("_py_test_img.png") == (40.0, 40.0)

    def test_missing_search_path_probe_fails(self):
        """Without the search path configured, a bare SRC can't be
        found."""
        set_image_search_paths(["."])
        # Run from a CWD that doesn't contain test_img.png.
        import os
        cwd = os.getcwd()
        try:
            os.chdir(REPO)
            assert _probe_image_size("_py_test_img.png") == (0.0, 0.0)
        finally:
            os.chdir(cwd)

    def test_absolute_src_ignores_search_path(self):
        """An absolute SRC should resolve even with a wrong / empty
        imagepath — the probe short-circuits the search."""
        set_image_search_paths([str(REPO / "does_not_exist")])
        assert _probe_image_size(str(TEST_PNG_PATH)) == (40.0, 40.0)

    def test_none_resets_to_cwd(self):
        """Passing ``None`` resets to the default ``['.']``."""
        set_image_search_paths([str(REPO / "test_data")])
        set_image_search_paths(None)
        # From the repo root CWD, ``test_img.png`` isn't at CWD —
        # probe should now fail.
        import os
        cwd = os.getcwd()
        try:
            os.chdir(REPO)
            assert _probe_image_size("_py_test_img.png") == (0.0, 0.0)
        finally:
            os.chdir(cwd)

    def test_gv_file_path_env_var_resolves_src(self, monkeypatch):
        """With ``imagepath`` empty, ``GV_FILE_PATH`` is the fallback
        search path — matches Graphviz's ``lib/common/usershape.c``
        behaviour."""
        set_image_search_paths(None)   # imagepath = just "."
        monkeypatch.setenv("GV_FILE_PATH", str(REPO / "test_data"))
        assert _probe_image_size("_py_test_img.png") == (40.0, 40.0)

    def test_gv_file_path_accepts_semicolon_separator(self, monkeypatch):
        """Multiple directories separated by ``;`` (Windows) or ``:``
        (Unix) — first match wins."""
        set_image_search_paths(None)
        monkeypatch.setenv(
            "GV_FILE_PATH",
            f"/no/such/dir;{REPO / 'test_data'}",
        )
        assert _probe_image_size("_py_test_img.png") == (40.0, 40.0)

    def test_imagepath_takes_precedence_over_env(self, monkeypatch):
        """If both imagepath and ``GV_FILE_PATH`` supply a match,
        the imagepath-configured directory wins (first one in the
        search list)."""
        # Put the real test_data on imagepath; a different (invalid)
        # dir on GV_FILE_PATH — imagepath should resolve first.
        set_image_search_paths([str(REPO / "test_data")])
        monkeypatch.setenv("GV_FILE_PATH", "/no/such/dir")
        assert _probe_image_size("_py_test_img.png") == (40.0, 40.0)

    def test_render_svg_applies_graph_imagepath(self):
        """``render_svg`` should read the ``imagepath`` graph attr and
        install the search paths so a relative IMG SRC in a later
        label parse resolves."""
        from gvpy.render.svg_renderer import render_svg
        # Minimal layout dict — no labels needed for this call; we
        # only want render_svg's side-effect of applying imagepath.
        render_svg({
            "graph": {
                "name": "G",
                "bb": [0, 0, 100, 100],
                "imagepath": str(REPO / "test_data"),
            },
            "nodes": [],
            "edges": [],
        })
        # Now a bare SRC resolves via the installed search path.
        assert _probe_image_size("_py_test_img.png") == (40.0, 40.0)


# ── IMG parsing ─────────────────────────────────────────────────────


class TestParseImg:
    def test_img_attaches_to_cell(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD><IMG SRC="a.png"/></TD></TR></TABLE>>'
        )
        cell = lbl.table.rows[0].cells[0]
        assert isinstance(cell.image, HtmlImage)
        assert cell.image.src == "a.png"
        # SCALE defaults to "false".
        assert cell.image.scale == "false"

    def test_img_scale_normalised_lowercase(self):
        lbl = parse_html_label(
            '<<TABLE><TR><TD><IMG SRC="a.png" SCALE="BOTH"/></TD></TR></TABLE>>'
        )
        assert lbl.table.rows[0].cells[0].image.scale == "both"

    def test_img_outside_td_ignored(self):
        """An IMG outside any TD shouldn't crash or attach anywhere."""
        lbl = parse_html_label('<<TABLE><IMG SRC="x.png"/></TABLE>>')
        # Table parsed, no image anywhere.
        assert lbl.table is not None
        for row in lbl.table.rows:
            for cell in row.cells:
                assert cell.image is None


# ── IMG sizing ──────────────────────────────────────────────────────


class TestImgSize:
    def _table(self, label: str):
        lbl = parse_html_label(label)
        size_html_table(lbl.table)
        return lbl.table

    def test_natural_size_drives_cell_content(self):
        """SCALE="FALSE" (default) + no WIDTH/HEIGHT on TD: the cell's
        content size comes from the image's natural dimensions plus
        the cell's padding."""
        t = self._table(
            f'<<TABLE CELLPADDING="0"><TR>'
            f'<TD><IMG SRC="{TEST_PNG_PATH}"/></TD>'
            f'</TR></TABLE>>'
        )
        cell = t.rows[0].cells[0]
        # 40×40 image + 0 pad → content = 40.
        assert cell.content_w == pytest.approx(40.0)
        assert cell.content_h == pytest.approx(40.0)

    def test_natural_size_plus_padding(self):
        t = self._table(
            f'<<TABLE CELLPADDING="4"><TR>'
            f'<TD><IMG SRC="{TEST_PNG_PATH}"/></TD>'
            f'</TR></TABLE>>'
        )
        cell = t.rows[0].cells[0]
        # 40 image + 2×4 pad = 48.
        assert cell.content_w == pytest.approx(48.0)

    def test_missing_image_falls_back_to_default(self):
        t = self._table(
            '<<TABLE CELLPADDING="0"><TR>'
            '<TD><IMG SRC="nope.png"/></TD>'
            '</TR></TABLE>>'
        )
        cell = t.rows[0].cells[0]
        # Default 50×50 when probe fails.
        assert cell.content_w == pytest.approx(50.0)
        assert cell.content_h == pytest.approx(50.0)

    def test_fixedsize_overrides_image_dims(self):
        """A TD with WIDTH/HEIGHT + FIXEDSIZE=TRUE clamps the cell
        regardless of the image's natural size."""
        t = self._table(
            f'<<TABLE CELLPADDING="0"><TR>'
            f'<TD WIDTH="80" HEIGHT="20" FIXEDSIZE="TRUE">'
            f'<IMG SRC="{TEST_PNG_PATH}"/>'
            f'</TD></TR></TABLE>>'
        )
        cell = t.rows[0].cells[0]
        assert cell.content_w == 80.0
        assert cell.content_h == 20.0


# ── IMG rendering ───────────────────────────────────────────────────


class TestImgRender:
    def test_img_emits_svg_image(self):
        out = _render(
            f'<<TABLE CELLBORDER="0"><TR>'
            f'<TD><IMG SRC="{TEST_PNG_PATH}"/></TD>'
            f'</TR></TABLE>>'
        )
        assert "<image" in out
        assert 'xlink:href="' in out
        # The src path appears verbatim (absolute in this rendered
        # test — the end-to-end fixture uses the relative ``test_img.png``
        # form with ``imagepath`` instead).
        assert TEST_PNG_PATH.as_posix() in out or str(TEST_PNG_PATH) in out

    def test_scale_both_sets_preserveaspectratio_none(self):
        out = _render(
            f'<<TABLE CELLBORDER="0"><TR>'
            f'<TD WIDTH="100" HEIGHT="20" FIXEDSIZE="TRUE">'
            f'<IMG SRC="{TEST_PNG_PATH}" SCALE="BOTH"/>'
            f'</TD></TR></TABLE>>'
        )
        assert 'preserveAspectRatio="none"' in out

    def test_scale_true_preserves_aspect(self):
        out = _render(
            f'<<TABLE CELLBORDER="0"><TR>'
            f'<TD WIDTH="80" HEIGHT="80" FIXEDSIZE="TRUE">'
            f'<IMG SRC="{TEST_PNG_PATH}" SCALE="TRUE"/>'
            f'</TD></TR></TABLE>>'
        )
        assert 'preserveAspectRatio="xMidYMid meet"' in out

    def test_scale_width_clamps_to_cell_height(self):
        """40×40 image in an 80×40 cell with SCALE="WIDTH": filling
        the width would make the image 80×80, exceeding the cell's
        40-pt inner height.  The renderer falls back to fitting
        the height so the image never overflows — the output is
        40×40, centred horizontally."""
        out = _render(
            f'<<TABLE CELLBORDER="0" CELLPADDING="0"><TR>'
            f'<TD WIDTH="80" HEIGHT="40" FIXEDSIZE="TRUE">'
            f'<IMG SRC="{TEST_PNG_PATH}" SCALE="WIDTH"/>'
            f'</TD></TR></TABLE>>'
        )
        m = re.search(r'<image [^>]*width="([\d.]+)" height="([\d.]+)"', out)
        assert m
        w, h = float(m.group(1)), float(m.group(2))
        assert w == pytest.approx(40.0)
        assert h == pytest.approx(40.0)

    def test_scale_width_fills_when_aspect_fits(self):
        """40×40 image in an 80×80 cell with SCALE="WIDTH": width
        scaling to 80 yields 80×80 which fits — no clamp needed."""
        out = _render(
            f'<<TABLE CELLBORDER="0" CELLPADDING="0"><TR>'
            f'<TD WIDTH="80" HEIGHT="80" FIXEDSIZE="TRUE">'
            f'<IMG SRC="{TEST_PNG_PATH}" SCALE="WIDTH"/>'
            f'</TD></TR></TABLE>>'
        )
        m = re.search(r'<image [^>]*width="([\d.]+)" height="([\d.]+)"', out)
        assert m
        w, h = float(m.group(1)), float(m.group(2))
        assert w == pytest.approx(80.0)
        assert h == pytest.approx(80.0)

    def test_scale_height_clamps_to_cell_width(self):
        """Symmetric to the width case: 40×40 image in a 40×80 cell
        with SCALE="HEIGHT" — height scaling would yield 80×80,
        exceeding the cell's 40-pt inner width.  Clamp to 40×40."""
        out = _render(
            f'<<TABLE CELLBORDER="0" CELLPADDING="0"><TR>'
            f'<TD WIDTH="40" HEIGHT="80" FIXEDSIZE="TRUE">'
            f'<IMG SRC="{TEST_PNG_PATH}" SCALE="HEIGHT"/>'
            f'</TD></TR></TABLE>>'
        )
        m = re.search(r'<image [^>]*width="([\d.]+)" height="([\d.]+)"', out)
        assert m
        w, h = float(m.group(1)), float(m.group(2))
        assert w == pytest.approx(40.0)
        assert h == pytest.approx(40.0)

    def test_scale_false_uses_natural_size(self):
        out = _render(
            f'<<TABLE CELLBORDER="0" CELLPADDING="0"><TR>'
            f'<TD><IMG SRC="{TEST_PNG_PATH}" SCALE="FALSE"/></TD>'
            f'</TR></TABLE>>'
        )
        m = re.search(r'<image [^>]*width="([\d.]+)" height="([\d.]+)"', out)
        assert m and float(m.group(1)) == pytest.approx(40.0)


# ── HREF / TARGET / TITLE / TOOLTIP / ID ────────────────────────────


class TestLinksAndMetadata:
    def test_cell_href_wraps_in_anchor(self):
        out = _render(
            '<<TABLE><TR>'
            '<TD HREF="https://claude.ai">x</TD></TR></TABLE>>'
        )
        assert '<a xlink:href="https://claude.ai">' in out
        # Anchor closes around the cell content.
        assert out.count("<a ") == out.count("</a>") == 1

    def test_cell_target_passed_through(self):
        out = _render(
            '<<TABLE><TR>'
            '<TD HREF="https://claude.ai" TARGET="_blank">x</TD>'
            '</TR></TABLE>>'
        )
        assert 'target="_blank"' in out

    def test_cell_title_becomes_svg_title(self):
        out = _render(
            '<<TABLE><TR><TD TITLE="hover text">x</TD></TR></TABLE>>'
        )
        assert "<title>hover text</title>" in out

    def test_cell_tooltip_aliases_to_title(self):
        out = _render(
            '<<TABLE><TR><TD TOOLTIP="tooltip text">x</TD></TR></TABLE>>'
        )
        assert "<title>tooltip text</title>" in out

    def test_title_and_tooltip_title_wins_if_both(self):
        out = _render(
            '<<TABLE><TR><TD TITLE="t1" TOOLTIP="t2">x</TD></TR></TABLE>>'
        )
        assert "<title>t1</title>" in out
        assert "<title>t2</title>" not in out

    def test_cell_id_wraps_in_group(self):
        out = _render(
            '<<TABLE><TR><TD ID="mycell">x</TD></TR></TABLE>>'
        )
        assert '<g id="mycell">' in out

    def test_table_href_wraps_entire_body(self):
        out = _render(
            '<<TABLE HREF="https://claude.ai"><TR>'
            '<TD>a</TD><TD>b</TD></TR></TABLE>>'
        )
        # One anchor wrapping everything.
        assert out.count('<a ') >= 1
        # The cells' text appears inside the anchor.
        a_start = out.find('<a xlink:href="https://claude.ai"')
        a_end = out.find("</a>", a_start)
        inner = out[a_start:a_end]
        assert ">a<" in inner and ">b<" in inner

    def test_cell_href_text_uses_link_color(self):
        """The anchor-wrapped text inside a ``HREF`` cell should emit
        as link blue (``#0066cc``) so it's visually distinguishable
        as a hyperlink.  The text element's ``fill`` carries the
        link colour; the inner ``<tspan>`` should not override it
        unless the author explicitly set ``<FONT COLOR="…">``."""
        out = _render(
            '<<TABLE><TR>'
            '<TD HREF="https://claude.ai">link</TD>'
            '</TR></TABLE>>'
        )
        assert 'fill="#0066cc"' in out
        # The tspan for "link" inside the anchor shouldn't carry a
        # contradicting black fill.
        m = re.search(r'<tspan [^>]*>link</tspan>', out)
        assert m and 'fill="#000000"' not in m.group(0)

    def test_table_href_colors_all_cells(self):
        """A TABLE-level ``HREF`` makes every cell's text use link
        blue by default since the entire table is clickable."""
        out = _render(
            '<<TABLE HREF="https://claude.ai"><TR>'
            '<TD>a</TD><TD>b</TD></TR></TABLE>>'
        )
        # Both cells' text elements carry the link colour.
        assert out.count('fill="#0066cc"') >= 2

    def test_explicit_font_color_beats_link_default(self):
        """Even inside a HREF cell, an explicit ``<FONT COLOR="…">``
        should override the link-blue default."""
        out = _render(
            '<<TABLE><TR>'
            '<TD HREF="https://claude.ai">'
            '<FONT COLOR="red">override</FONT>'
            '</TD></TR></TABLE>>'
        )
        # The override colour appears on the tspan; link blue is the
        # text-element default but the inner run overrides it.
        assert 'fill="red"' in out

    def test_svg_root_carries_link_css(self):
        """``render_svg`` emits a style block that underlines any
        anchor descendants so browsers render links identifiably even
        without author styling."""
        from gvpy.render.svg_renderer import render_svg
        svg = render_svg({
            "graph": {"name": "G", "bb": [0, 0, 100, 100]},
            "nodes": [], "edges": [],
        })
        assert "text-decoration: underline" in svg
        assert "cursor: pointer" in svg

    def test_escape_in_href(self):
        """A href containing characters that must be XML-escaped
        should be escaped in the output."""
        out = _render(
            '<<TABLE><TR><TD HREF="?q=a&b=c">x</TD></TR></TABLE>>'
        )
        assert "&amp;" in out


# ── End-to-end fixture ──────────────────────────────────────────────


@pytest.mark.skipif(
    not (REPO / "test_data" / "html_img_link.dot").exists(),
    reason="html_img_link.dot fixture missing",
)
class TestEndToEndHtmlImgLink:
    @pytest.fixture(scope="class")
    def svg(self) -> str:
        from gvpy.grammar.gv_reader import read_dot_file
        from gvpy.engines.layout.dot.dot_layout import DotLayout
        from gvpy.render.svg_renderer import render_svg
        g = read_dot_file(str(REPO / "test_data" / "html_img_link.dot"))
        return render_svg(DotLayout(g).layout())

    def _node(self, svg: str, node_id: str) -> str:
        """Return the substring for the node's ``<g>`` block.

        Walks balanced ``<g>`` / ``</g>`` because cell-level ID
        wrapping (``<TD ID="…">`` → ``<g id="…">``) now nests inside
        the node's outer ``<g>``.  A naïve ``svg.find("</g>")`` would
        stop at the first inner ``</g>`` and miss everything after.
        """
        open_idx = svg.find(f'id="{node_id}"')
        assert open_idx >= 0, f"node {node_id} missing from SVG"
        # Start the balanced walk just after the node's opening '<g'.
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

    def test_plain_image_renders(self, svg):
        win = self._node(svg, "node_t_img_plain")
        assert "<image" in win
        assert "test_img.png" in win

    def test_scale_true_sets_preserveaspectratio(self, svg):
        win = self._node(svg, "node_t_img_scale_true")
        assert 'preserveAspectRatio="xMidYMid meet"' in win

    def test_scale_both_has_no_preserve_aspect(self, svg):
        win = self._node(svg, "node_t_img_scale_both")
        assert 'preserveAspectRatio="none"' in win

    def test_scale_axes_node_has_two_images(self, svg):
        win = self._node(svg, "node_t_img_scale_axes")
        assert win.count("<image") == 2

    def test_href_table_wraps_in_anchor_with_target(self, svg):
        win = self._node(svg, "node_t_href_table")
        assert '<a xlink:href="https://claude.ai"' in win
        assert 'target="_blank"' in win
        assert "<title>Open Claude</title>" in win

    def test_href_cell_wraps_only_that_cell(self, svg):
        win = self._node(svg, "node_t_href_cell")
        # One anchor around the first cell; the "plain" cell is
        # outside the anchor.
        a_start = win.find('<a xlink:href="https://claude.ai"')
        assert a_start >= 0
        a_end = win.find("</a>", a_start)
        inner = win[a_start:a_end]
        assert ">link-cell<" in inner
        assert ">plain<" not in inner

    def test_tooltip_cell_emits_title(self, svg):
        win = self._node(svg, "node_t_tooltip_cell")
        assert "<title>hover me</title>" in win
        # No href → no <a>.
        assert "<a xlink:href=" not in win

    def test_id_cell_emits_g_ids(self, svg):
        win = self._node(svg, "node_t_id_cell")
        assert '<g id="cellOne">' in win
        assert '<g id="cellTwo">' in win

    def test_img_link_has_image_inside_anchor(self, svg):
        """The combined image + href cell — the <image> element must
        live inside the <a xlink:href> wrapper."""
        win = self._node(svg, "node_t_img_link")
        a_start = win.find('<a xlink:href="https://claude.ai"')
        a_end = win.find("</a>", a_start)
        assert a_start >= 0 and a_end > a_start
        inner = win[a_start:a_end]
        assert "<image" in inner
        assert "test_img.png" in inner
