"""
Pytest tests for the SVG renderer.
"""
import pytest
from pathlib import Path

from pycode.dot.dot_reader import read_dot
from pycode.dot.dot_layout import DotLayout
from pycode.dot.svg_renderer import render_svg, render_svg_file


def layout_and_render(src: str) -> str:
    """Parse DOT, run layout, render SVG."""
    g = read_dot(src)
    result = DotLayout(g).layout()
    return render_svg(result)


class TestSvgBasic:

    def test_produces_valid_svg(self):
        """Output is valid SVG with xml declaration and svg root."""
        svg = layout_and_render("digraph G { a -> b; }")
        assert svg.startswith("<?xml")
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_has_title(self):
        """SVG contains graph title."""
        svg = layout_and_render("digraph MyGraph { a -> b; }")
        assert "<title>MyGraph</title>" in svg

    def test_empty_graph(self):
        """Empty graph produces minimal valid SVG."""
        svg = layout_and_render("digraph G { }")
        assert "<svg" in svg
        assert "</svg>" in svg


class TestSvgNodes:

    def test_nodes_as_ellipses(self):
        """Default nodes render as ellipses."""
        svg = layout_and_render("digraph G { a; b; }")
        assert "<ellipse" in svg
        assert svg.count("<ellipse") == 2

    def test_box_nodes_as_rects(self):
        """Nodes with shape=box render as rects."""
        svg = layout_and_render('digraph G { a [shape=box]; }')
        assert "<rect" in svg

    def test_node_labels(self):
        """Nodes have text labels with their names."""
        svg = layout_and_render("digraph G { hello; world; }")
        assert ">hello</text>" in svg
        assert ">world</text>" in svg


class TestSvgEdges:

    def test_edges_rendered(self):
        """Edges produce path or polyline elements."""
        svg = layout_and_render("digraph G { a -> b; }")
        assert "<path" in svg or "<polyline" in svg

    def test_directed_has_arrowheads(self):
        """Directed graph edges have arrowhead polygons."""
        svg = layout_and_render("digraph G { a -> b; }")
        assert '<polygon fill="#000000"' in svg

    def test_undirected_no_arrowheads(self):
        """Undirected graph edges have no arrowheads."""
        svg = layout_and_render("graph G { a -- b; }")
        # Should not have arrowhead polygons in the edge group
        # (the only polygons should be from nodes if any)
        assert svg.count("<polygon") == 0

    def test_edge_labels(self):
        """Edge labels are rendered as text elements."""
        svg = layout_and_render('digraph G { a -> b [label="connects"]; }')
        assert ">connects</text>" in svg

    def test_bezier_path(self):
        """Default splines produce Bezier paths with C commands."""
        svg = layout_and_render("digraph G { a -> b; }")
        assert ' C ' in svg or '<path' in svg

    def test_ortho_polyline(self):
        """Ortho splines produce polyline elements."""
        svg = layout_and_render('digraph G { splines=ortho; a -> b; }')
        assert "<polyline" in svg


class TestSvgClusters:

    def test_clusters_rendered(self):
        """Clusters have background rects."""
        svg = layout_and_render("""
            digraph G {
                subgraph cluster_0 { a; b; }
            }
        """)
        assert 'class="cluster"' in svg
        assert 'stroke-dasharray' in svg

    def test_cluster_label(self):
        """Cluster labels are rendered."""
        svg = layout_and_render("""
            digraph G {
                subgraph cluster_0 {
                    label="My Group";
                    a; b;
                }
            }
        """)
        assert ">My Group</text>" in svg


class TestSvgFile:

    def test_render_to_file(self, tmp_path):
        """render_svg_file writes valid SVG to disk."""
        g = read_dot("digraph G { x -> y; }")
        result = DotLayout(g).layout()
        out = tmp_path / "test.svg"
        render_svg_file(result, out)
        content = out.read_text()
        assert content.startswith("<?xml")
        assert "<svg" in content

    def test_real_file(self):
        """Render a real .gv file to SVG."""
        path = Path(__file__).parent.parent / "test_data" / "example1.gv"
        if not path.exists():
            pytest.skip("example1.gv not found")
        from pycode.dot.dot_reader import read_dot_file
        g = read_dot_file(path)
        result = DotLayout(g).layout()
        svg = render_svg(result)
        assert "<ellipse" in svg
        assert svg.count("class=\"node\"") == 5


class TestSvgCLI:

    def test_cli_svg_output(self, tmp_path):
        """CLI with -Tsvg produces SVG."""
        import subprocess, sys
        dot_file = tmp_path / "test.gv"
        dot_file.write_text("digraph G { a -> b; }", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "dot.py", str(dot_file), "-Tsvg"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr
        assert "<svg" in result.stdout

    def test_cli_svg_to_file(self, tmp_path):
        """CLI with -Tsvg and output file writes SVG to disk."""
        import subprocess, sys
        dot_file = tmp_path / "test.gv"
        dot_file.write_text("digraph G { x -> y; }", encoding="utf-8")
        out_file = tmp_path / "out.svg"
        result = subprocess.run(
            [sys.executable, "dot.py", str(dot_file), "-Tsvg", "-o", str(out_file)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr
        assert out_file.exists()
        assert "<svg" in out_file.read_text()
