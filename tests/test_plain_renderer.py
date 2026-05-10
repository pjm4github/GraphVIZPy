"""Tests for the Graphviz plain-format renderer."""
from __future__ import annotations

from gvpy.engines.layout.dot import DotLayout
from gvpy.grammar.gv_reader import read_gv
from gvpy.render.plain_renderer import _q, render_plain


class TestPlainQuoting:
    """Token quoting rules — strings with whitespace, quotes, or
    backslashes get double-quoted; simple identifiers don't."""

    def test_simple_identifier_unquoted(self):
        assert _q("foo") == "foo"

    def test_empty_string_emits_double_quotes(self):
        assert _q("") == '""'

    def test_none_emits_double_quotes(self):
        assert _q(None) == '""'

    def test_whitespace_quoted(self):
        assert _q("hello world") == '"hello world"'

    def test_embedded_quote_escaped(self):
        assert _q('say "hi"') == '"say \\"hi\\""'

    def test_embedded_backslash_escaped(self):
        assert _q("a\\b") == '"a\\\\b"'


class TestPlainHeader:
    """Top-level ``graph`` line."""

    def test_graph_line_format(self):
        result = {
            "graph": {"bb": [0.0, 0.0, 144.0, 72.0]},  # 2in × 1in
            "nodes": [],
            "edges": [],
        }
        out = render_plain(result)
        first = out.splitlines()[0]
        assert first == "graph 1 2 1"

    def test_default_scale_is_1(self):
        result = {
            "graph": {"bb": [0.0, 0.0, 72.0, 36.0]},
            "nodes": [],
            "edges": [],
        }
        out = render_plain(result)
        assert out.splitlines()[0].split()[1] == "1"

    def test_terminator(self):
        result = {
            "graph": {"bb": [0, 0, 0, 0]},
            "nodes": [],
            "edges": [],
        }
        assert render_plain(result).rstrip().endswith("stop")


class TestPlainNodes:
    """``node`` line format + coord conversion."""

    def test_node_pt_to_inch(self):
        """Pt-space coords convert to inches (÷ 72)."""
        result = {
            "graph": {"bb": [0.0, 0.0, 144.0, 144.0]},
            "nodes": [
                {"name": "a", "x": 36.0, "y": 36.0,
                 "width": 54.0, "height": 36.0},
            ],
            "edges": [],
        }
        out = render_plain(result)
        node_line = [l for l in out.splitlines() if l.startswith("node ")][0]
        toks = node_line.split()
        # node NAME X Y W H ...
        assert toks[1] == "a"
        # x = 36/72 = 0.5
        assert toks[2] == "0.5"
        # y is flipped: (144 - 36) / 72 = 1.5
        assert toks[3] == "1.5"
        # w = 54/72 = 0.75
        assert toks[4] == "0.75"
        # h = 36/72 = 0.5
        assert toks[5] == "0.5"

    def test_node_default_attrs(self):
        """Unset attrs use Graphviz plain defaults: solid /
        ellipse / black / lightgrey."""
        result = {
            "graph": {"bb": [0, 0, 72, 72]},
            "nodes": [
                {"name": "n", "x": 0, "y": 0,
                 "width": 54, "height": 36},
            ],
            "edges": [],
        }
        out = render_plain(result)
        node_line = [l for l in out.splitlines() if l.startswith("node ")][0]
        toks = node_line.split()
        # node NAME X Y W H LABEL STYLE SHAPE COLOR FILLCOLOR
        assert toks[7] == "solid"
        assert toks[8] == "ellipse"
        assert toks[9] == "black"
        assert toks[10] == "lightgrey"

    def test_node_explicit_attrs(self):
        result = {
            "graph": {"bb": [0, 0, 72, 72]},
            "nodes": [
                {"name": "n", "x": 0, "y": 0,
                 "width": 54, "height": 36,
                 "label": "Node 1", "style": "dashed",
                 "shape": "box", "color": "red",
                 "fillcolor": "yellow"},
            ],
            "edges": [],
        }
        out = render_plain(result)
        node_line = [l for l in out.splitlines() if l.startswith("node ")][0]
        # Label has whitespace so it's quoted.
        assert '"Node 1"' in node_line
        assert "dashed" in node_line
        assert "box" in node_line
        assert "red" in node_line
        assert "yellow" in node_line


class TestPlainEdges:
    """``edge`` line format."""

    def test_edge_point_count(self):
        result = {
            "graph": {"bb": [0, 0, 72, 72]},
            "nodes": [],
            "edges": [
                {"tail": "a", "head": "b",
                 "points": [[0, 0], [36, 36]]},
            ],
        }
        out = render_plain(result)
        edge_line = [l for l in out.splitlines() if l.startswith("edge ")][0]
        toks = edge_line.split()
        # edge TAIL HEAD N x1 y1 x2 y2 STYLE COLOR
        assert toks[1] == "a"
        assert toks[2] == "b"
        assert toks[3] == "2"

    def test_edge_default_style_color(self):
        result = {
            "graph": {"bb": [0, 0, 72, 72]},
            "nodes": [],
            "edges": [
                {"tail": "a", "head": "b",
                 "points": [[0, 0], [36, 36]]},
            ],
        }
        out = render_plain(result)
        edge_line = [l for l in out.splitlines()
                     if l.startswith("edge ")][0]
        toks = edge_line.split()
        assert toks[-2] == "solid"
        assert toks[-1] == "black"

    def test_edge_label_with_position(self):
        """An edge with both label and lp position emits the
        optional ``label LX LY`` segment between points and
        style/color."""
        result = {
            "graph": {"bb": [0, 0, 144, 144]},
            "nodes": [],
            "edges": [
                {"tail": "a", "head": "b",
                 "points": [[0, 0], [36, 36]],
                 "label": "weight", "_label_pos_x": 18,
                 "_label_pos_y": 18},
            ],
        }
        out = render_plain(result)
        edge_line = [l for l in out.splitlines()
                     if l.startswith("edge ")][0]
        assert "weight" in edge_line


class TestPlainViaCli:
    """End-to-end through the CLI dispatch — ``-Tplain`` should
    produce the canonical text format, not JSON."""

    def test_cli_plain_format_canonical(self):
        graph = read_gv("graph G { a -- b; }")
        result = DotLayout(graph).layout()
        out = render_plain(result)
        assert out.startswith("graph ")
        assert out.rstrip().endswith("stop")
        # Should NOT be JSON.
        assert not out.lstrip().startswith("{")
        # Has node lines for both a and b.
        assert "node a " in out
        assert "node b " in out
