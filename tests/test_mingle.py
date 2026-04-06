"""
Tests for the mingle edge bundling post-processor.
"""
import math
import pytest

from gvpy.tools.mingle import MingleBundler
from gvpy.tools.mingle import (
    _Edge, _edge_compatibility, _angle_compat, _scale_compat,
    _position_compat, _ink_single, _ink_bundled, _agglomerative_bundle,
)


class TestEdgeCompatibility:

    def test_parallel_edges(self):
        """Parallel edges have high compatibility."""
        e1 = _Edge(0, 0, 0, 10, 0)
        e2 = _Edge(1, 0, 1, 10, 1)
        assert _edge_compatibility(e1, e2) > 0.8

    def test_perpendicular_edges(self):
        """Perpendicular edges have low compatibility."""
        e1 = _Edge(0, 0, 0, 10, 0)
        e2 = _Edge(1, 5, -5, 5, 5)
        assert _edge_compatibility(e1, e2) < 0.2

    def test_same_edge(self):
        """An edge is fully compatible with itself."""
        e = _Edge(0, 0, 0, 10, 0)
        assert _edge_compatibility(e, e) > 0.99

    def test_distant_edges(self):
        """Far-apart edges have low compatibility."""
        e1 = _Edge(0, 0, 0, 10, 0)
        e2 = _Edge(1, 0, 100, 10, 100)
        assert _edge_compatibility(e1, e2) < 0.3

    def test_angle_compat_parallel(self):
        e1 = _Edge(0, 0, 0, 1, 0)
        e2 = _Edge(1, 0, 0, 1, 0)
        assert _angle_compat(e1, e2) == pytest.approx(1.0)

    def test_angle_compat_antiparallel(self):
        e1 = _Edge(0, 0, 0, 1, 0)
        e2 = _Edge(1, 1, 0, 0, 0)
        assert _angle_compat(e1, e2) == pytest.approx(1.0)

    def test_scale_compat_same(self):
        e1 = _Edge(0, 0, 0, 10, 0)
        e2 = _Edge(1, 0, 0, 10, 0)
        assert _scale_compat(e1, e2) == pytest.approx(1.0, abs=0.01)

    def test_scale_compat_different(self):
        e1 = _Edge(0, 0, 0, 1, 0)
        e2 = _Edge(1, 0, 0, 100, 0)
        assert _scale_compat(e1, e2) < 0.1


class TestInk:

    def test_single_edge_ink(self):
        e = _Edge(0, 0, 0, 10, 0)
        assert _ink_single(e) == pytest.approx(10.0)

    def test_bundled_ink_less(self):
        """Bundling parallel edges that are far apart saves ink."""
        e1 = _Edge(0, 0, 0, 100, 0)
        e2 = _Edge(1, 0, 50, 100, 50)
        separate = _ink_single(e1) + _ink_single(e2)
        bundled, _, _ = _ink_bundled(e1, e2)
        assert bundled < separate  # bundling should save ink


class TestAgglomerativeBundling:

    def test_no_edges(self):
        result = _agglomerative_bundle([])
        assert result == []

    def test_single_edge(self):
        e = _Edge(0, 0, 0, 10, 0)
        result = _agglomerative_bundle([e])
        assert len(result) == 1

    def test_parallel_edges_bundled(self):
        """Two parallel edges far apart get bundled."""
        e1 = _Edge(0, 0, 0, 100, 0)
        e2 = _Edge(1, 0, 50, 100, 50)
        _agglomerative_bundle([e1, e2], compat_threshold=0.3)
        has_bundle = any(len(e.points) > 2 for e in [e1, e2])
        assert has_bundle

    def test_incompatible_not_bundled(self):
        """Perpendicular edges stay separate."""
        e1 = _Edge(0, 0, 0, 100, 0)
        e2 = _Edge(1, 50, -50, 50, 50)
        _agglomerative_bundle([e1, e2], compat_threshold=0.8)
        # Both should still have 2 points (no bundling)
        assert len(e1.points) == 2
        assert len(e2.points) == 2


class TestBundleResult:

    def test_bundle_result_basic(self):
        """bundle_result modifies edge points for far-apart parallel edges."""
        result = {
            "graph": {"name": "G", "directed": False, "bb": [0, 0, 100, 100]},
            "nodes": [
                {"name": "a", "x": 0, "y": 0, "width": 10, "height": 10},
                {"name": "b", "x": 100, "y": 0, "width": 10, "height": 10},
                {"name": "c", "x": 0, "y": 50, "width": 10, "height": 10},
                {"name": "d", "x": 100, "y": 50, "width": 10, "height": 10},
            ],
            "edges": [
                {"tail": "a", "head": "b", "points": [[0, 0], [100, 0]]},
                {"tail": "c", "head": "d", "points": [[0, 50], [100, 50]]},
            ],
        }
        bundled = MingleBundler.bundle_result(result, compat_threshold=0.3)
        assert "edges" in bundled
        has_extra = any(len(e.get("points", [])) > 2
                        for e in bundled["edges"])
        assert has_extra

    def test_bundle_result_preserves_nodes(self):
        """Bundling doesn't modify node positions."""
        result = {
            "graph": {"name": "G", "directed": False, "bb": [0, 0, 100, 10]},
            "nodes": [
                {"name": "a", "x": 0, "y": 0, "width": 10, "height": 10},
                {"name": "b", "x": 100, "y": 0, "width": 10, "height": 10},
            ],
            "edges": [
                {"tail": "a", "head": "b", "points": [[0, 0], [100, 0]]},
            ],
        }
        bundled = MingleBundler.bundle_result(result)
        assert bundled["nodes"] == result["nodes"]

    def test_bundle_result_single_edge(self):
        """Single edge stays unchanged."""
        result = {
            "graph": {"name": "G", "directed": False, "bb": [0, 0, 100, 10]},
            "nodes": [
                {"name": "a", "x": 0, "y": 0, "width": 10, "height": 10},
                {"name": "b", "x": 100, "y": 0, "width": 10, "height": 10},
            ],
            "edges": [
                {"tail": "a", "head": "b", "points": [[0, 0], [100, 0]]},
            ],
        }
        bundled = MingleBundler.bundle_result(result)
        assert len(bundled["edges"][0]["points"]) == 2


class TestMingleNotLayoutEngine:

    def test_layout_raises(self):
        """MingleBundler.layout() raises NotImplementedError."""
        from gvpy.grammar.gv_reader import read_gv
        g = read_gv("graph G { a -- b; }")
        bundler = MingleBundler(g)
        with pytest.raises(NotImplementedError, match="not a layout engine"):
            bundler.layout()
