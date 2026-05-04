"""
Tests for the neato (spring-model) layout engine.
"""
import math
import pytest

from gvpy.core.graph import Graph
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.neato import NeatoLayout


def neato_gv(text: str, **attrs) -> dict:
    """Parse GV text and run neato layout."""
    graph = read_gv(text)
    for k, v in attrs.items():
        graph.set_graph_attr(k, v)
    return NeatoLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestNeatoBasic:

    def test_single_node(self):
        r = neato_gv("graph G { a; }")
        assert len(r["nodes"]) == 1

    def test_two_nodes(self):
        r = neato_gv("graph G { a -- b; }")
        na = node_by_name(r, "a")
        nb = node_by_name(r, "b")
        dist = math.sqrt((na["x"] - nb["x"])**2 + (na["y"] - nb["y"])**2)
        assert dist > 10  # they should be separated

    def test_triangle(self):
        r = neato_gv("graph G { a -- b -- c -- a; }")
        assert len(r["nodes"]) == 3
        assert len(r["edges"]) == 3

    def test_square(self):
        r = neato_gv("graph G { a -- b -- c -- d -- a; }")
        assert len(r["nodes"]) == 4

    def test_directed(self):
        r = neato_gv("digraph G { a -> b -> c; }")
        assert r["graph"]["directed"] is True
        assert len(r["nodes"]) == 3

    def test_undirected(self):
        r = neato_gv("graph G { a -- b; }")
        assert r["graph"]["directed"] is False

    def test_isolated_nodes(self):
        r = neato_gv("graph G { a; b; c; }")
        assert len(r["nodes"]) == 3
        for n in r["nodes"]:
            assert "x" in n
            assert "y" in n

    def test_empty_graph(self):
        r = neato_gv("graph G { }")
        assert len(r["nodes"]) == 0


class TestNeatoModes:

    def test_majorization_default(self):
        r = neato_gv("graph G { a -- b -- c -- a; }")
        assert len(r["nodes"]) == 3

    def test_kk_mode(self):
        r = neato_gv("graph G { a -- b -- c -- a; }", mode="KK")
        assert len(r["nodes"]) == 3
        # Nodes should be at distinct positions
        positions = [(n["x"], n["y"]) for n in r["nodes"]]
        assert len(set(positions)) == 3

    def test_sgd_mode(self):
        r = neato_gv("graph G { a -- b -- c -- a; }", mode="sgd")
        assert len(r["nodes"]) == 3

    def test_edge_length(self):
        """Edges with 'len' attribute affect distances."""
        r1 = neato_gv('graph G { a -- b [len=1]; }')
        r2 = neato_gv('graph G { a -- b [len=3]; }')
        d1 = math.sqrt((node_by_name(r1, "a")["x"] - node_by_name(r1, "b")["x"])**2 +
                       (node_by_name(r1, "a")["y"] - node_by_name(r1, "b")["y"])**2)
        d2 = math.sqrt((node_by_name(r2, "a")["x"] - node_by_name(r2, "b")["x"])**2 +
                       (node_by_name(r2, "a")["y"] - node_by_name(r2, "b")["y"])**2)
        assert d2 > d1 * 1.5  # longer len = farther apart


class TestNeatoDistanceModels:

    def test_shortpath_default(self):
        r = neato_gv("graph G { a -- b -- c; }")
        assert len(r["nodes"]) == 3

    def test_circuit_model(self):
        r = neato_gv("graph G { a -- b -- c -- a; }", model="circuit")
        assert len(r["nodes"]) == 3


class TestNeatoPinning:

    def test_pinned_node(self):
        """Pinned nodes keep their position."""
        r = neato_gv('graph G { a [pos="1,1!"]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na["x"] == pytest.approx(72.0, abs=1)
        assert na["y"] == pytest.approx(72.0, abs=1)

    def test_initial_pos(self):
        """Nodes with pos (no !) are used as initial positions."""
        r = neato_gv('graph G { a [pos="0,0"]; b [pos="2,0"]; a -- b; }')
        assert len(r["nodes"]) == 2


class TestNeatoComponents:

    def test_disconnected(self):
        """Disconnected components are packed."""
        r = neato_gv("graph G { a -- b; c -- d; }")
        na = node_by_name(r, "a")
        nc = node_by_name(r, "c")
        assert abs(na["x"] - nc["x"]) > 10 or abs(na["y"] - nc["y"]) > 10

    def test_many_components(self):
        r = neato_gv("graph G { a; b; c; d; e; }")
        assert len(r["nodes"]) == 5


class TestNeatoOverlap:

    def test_overlap_false(self):
        """overlap=false removes overlaps."""
        r = neato_gv("graph G { a -- b -- c; }", overlap="false")
        nodes = r["nodes"]
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dx = abs(nodes[i]["x"] - nodes[j]["x"])
                dy = abs(nodes[i]["y"] - nodes[j]["y"])
                min_sep = (nodes[i]["width"] + nodes[j]["width"]) / 4
                # At least some separation
                assert dx > 1 or dy > 1


class TestNeatoAttributes:

    def test_node_attrs_preserved(self):
        r = neato_gv('graph G { a [shape=box, color=red]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na["shape"] == "box"
        assert na["color"] == "red"

    def test_edge_attrs_preserved(self):
        r = neato_gv('graph G { a -- b [label="test", color=blue]; }')
        e = r["edges"][0]
        assert e["label"] == "test"
        assert e["color"] == "blue"

    def test_edge_label_pos(self):
        r = neato_gv('graph G { a -- b [label="mid"]; }')
        e = r["edges"][0]
        assert "label_pos" in e

    def test_bounding_box(self):
        r = neato_gv("graph G { a -- b -- c -- a; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]
        assert bb[3] > bb[1]

    def test_pos_writeback(self):
        g = read_gv("graph G { a -- b; }")
        NeatoLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes
        assert "," in g.nodes["a"].attributes["pos"]

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = neato_gv("graph G { a -- b -- c -- a; }")
        svg = render_svg(r)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_graph_label(self):
        r = neato_gv('graph G { label="Test"; a -- b; }')
        assert r["graph"].get("label") == "Test"

    def test_xlabel(self):
        r = neato_gv('graph G { a [xlabel="extra"]; b; a -- b; }')
        na = node_by_name(r, "a")
        assert na.get("xlabel") == "extra"
        assert "_xlabel_pos_x" in na


class TestNeatoStressKernel:
    """§4.N.2.1 — verify the CG-based stress majorization kernel."""

    def test_packed_laplacian_indexing(self):
        """packed_index round-trips correctly across the upper-tri."""
        from gvpy.engines.layout.common.laplacian import (
            packed_index,
            packed_length,
        )
        n = 5
        L = packed_length(n)
        assert L == n * (n + 1) // 2
        # Diagonal indices increment by row-length (n, n-1, ...).
        assert packed_index(n, 0, 0) == 0
        assert packed_index(n, 1, 1) == n
        assert packed_index(n, 2, 2) == n + (n - 1)
        # Symmetric: packed_index(i, j) == packed_index(j, i).
        assert packed_index(n, 1, 3) == packed_index(n, 3, 1)
        # Last entry is the bottom-right diagonal.
        assert packed_index(n, n - 1, n - 1) == L - 1

    def test_right_mult_packed_matches_dense(self):
        """Packed-form matrix-vector product matches the dense form."""
        import numpy as np
        from gvpy.engines.layout.common.laplacian import (
            packed_index,
            packed_length,
            right_mult_packed,
        )
        n = 4
        # Build a known symmetric matrix and its packed form.
        dense = np.array([
            [4.0, -1.0, -2.0, 0.0],
            [-1.0, 5.0, -1.0, -3.0],
            [-2.0, -1.0, 6.0, -2.0],
            [0.0, -3.0, -2.0, 5.0],
        ])
        packed = np.zeros(packed_length(n))
        for i in range(n):
            for j in range(i, n):
                packed[packed_index(n, i, j)] = dense[i, j]
        x = np.array([1.0, 2.0, 3.0, 4.0])
        expected = dense @ x
        actual = right_mult_packed(packed, n, x)
        np.testing.assert_allclose(actual, expected, atol=1e-12)

    def test_cg_solves_laplacian_system(self):
        """Conjugate gradient converges on a small Laplacian."""
        import numpy as np
        from gvpy.engines.layout.common.conjgrad import (
            conjugate_gradient_mkernel,
        )
        from gvpy.engines.layout.common.laplacian import (
            packed_index,
            packed_length,
            right_mult_packed,
        )
        n = 4
        # Build a path Laplacian (a-b-c-d): L = D - A.
        L = packed_length(n)
        lap = np.zeros(L)
        for i, j in [(0, 1), (1, 2), (2, 3)]:
            lap[packed_index(n, i, j)] = -1.0
        for i, deg in enumerate([1, 2, 2, 1]):
            lap[packed_index(n, i, i)] = float(deg)
        # Pick a target X (centred so it's in the column space).
        x_target = np.array([1.0, 2.0, 3.0, 4.0])
        x_target -= x_target.mean()
        b = right_mult_packed(lap, n, x_target)
        # Solve with CG starting from zero.
        x = np.zeros(n)
        rv = conjugate_gradient_mkernel(lap, x, b, n, 1e-8, n * 4)
        assert rv == 0
        np.testing.assert_allclose(x, x_target, atol=1e-6)

    def test_gauss_solve_2x2(self):
        """Gauss-elimination solver mirrors solve.c on a 2x2 system."""
        from gvpy.engines.layout.common.matrix import gauss_solve
        # [2 1; 1 3] x = [4; 5]  ->  x = [1, 4/3]
        a = [2.0, 1.0, 1.0, 3.0]
        c = [4.0, 5.0]
        x = gauss_solve(a, c, 2)
        assert x is not None
        assert abs(x[0] - 1.4) < 1e-9
        assert abs(x[1] - 1.2) < 1e-9
        # Inputs must not be mutated.
        assert a == [2.0, 1.0, 1.0, 3.0]
        assert c == [4.0, 5.0]

    def test_gauss_solve_singular(self):
        """Singular system returns None instead of raising."""
        from gvpy.engines.layout.common.matrix import gauss_solve
        # [1 2; 2 4] is rank-1 singular.
        x = gauss_solve([1.0, 2.0, 2.0, 4.0], [3.0, 6.0], 2)
        assert x is None

    def test_kk_diffeq_init_consistency(self):
        """diffeq_model produces force tensors whose row-sums match.

        The invariant ``sum_t[i] = sum_j t[i][j]`` must hold after
        :func:`diffeq_model` (both the i-row sum and the j-column
        sum are maintained incrementally).
        """
        import numpy as np
        from gvpy.engines.layout.neato.kkutils import diffeq_model

        N = 4
        coords = np.array([[0.0, 0.0], [72.0, 0.0],
                           [36.0, 60.0], [108.0, 60.0]],
                          dtype=np.float64)
        dist = [[0.0, 72.0, 72.0, 144.0],
                [72.0, 0.0, 144.0, 72.0],
                [72.0, 144.0, 0.0, 72.0],
                [144.0, 72.0, 72.0, 0.0]]
        K, t, sum_t = diffeq_model(coords, dist, N, edge_factor={})
        for i in range(N):
            row_sum = t[i].sum(axis=0)
            np.testing.assert_allclose(sum_t[i], row_sum, atol=1e-12)

    def test_sgd_step_cap(self):
        """SGD step factor mu must be capped at 1.0.

        Mirrors C ``sgd.c:221``: ``mu = fmin(eta * w, 1)``.  Without
        the cap, early-iteration eta * w can fling nodes far past
        their target.  We can't directly inspect mu, but a synthetic
        test passing extreme eta indirectly validates the cap.
        """
        import math
        # K3 — three nodes forming a tight cluster.  With aggressive
        # SGD (epsilon very small to maximise eta_max/eta_min ratio)
        # the step cap is what keeps positions finite.
        r = neato_gv("graph G { mode=sgd; a -- b -- c -- a; }",
                     epsilon="0.0001")
        for n in r["nodes"]:
            assert math.isfinite(n["x"])
            assert math.isfinite(n["y"])
            # Positions should also be reasonably bounded — a runaway
            # SGD without the cap can produce values in the millions.
            assert abs(n["x"]) < 1e6
            assert abs(n["y"]) < 1e6

    def test_smart_init_unblocks_kk_y_shape(self):
        """Smart-init lets KK escape the Y-shape saddle.

        Random init + KK gets stuck (forces ≈ 0 but layout is off);
        PivotMDS init places nodes near the analytical optimum and
        KK's Newton steps then close the residual.

        Smart-init is opt-in via ``start=self`` (matches C
        ``setSeed`` semantics where ``self`` prefix selects
        INIT_SELF / smart init).
        """
        import math
        r = neato_gv("graph G { mode=KK; start=self; "
                     "root -- a; root -- b; root -- c; }")
        positions = {n["name"]: (n["x"], n["y"]) for n in r["nodes"]}
        for leaf in ("a", "b", "c"):
            d = math.hypot(positions["root"][0] - positions[leaf][0],
                           positions["root"][1] - positions[leaf][1])
            assert 70.0 < d < 85.0, (
                f"KK+smart-init: root-{leaf}={d:.1f}, "
                f"expected near analytical optimum 76.8"
            )

    def test_smart_init_k5_pentagon(self):
        """Smart-init + SGD on K5 finds the regular-pentagon
        global optimum.

        K5 has 10 pairwise distances; the regular pentagon
        partitions them into 5 sides of length s and 5 diagonals
        of length s × φ where φ = (1 + √5) / 2 ≈ 1.618.
        """
        import math
        phi = (1 + math.sqrt(5)) / 2
        r = neato_gv(
            "graph G { mode=sgd; "
            "a -- b; a -- c; a -- d; a -- e; "
            "b -- c; b -- d; b -- e; "
            "c -- d; c -- e; d -- e; }"
        )
        positions = {n["name"]: (n["x"], n["y"]) for n in r["nodes"]}
        names = list(positions)
        dists = sorted(
            math.hypot(positions[a][0] - positions[b][0],
                       positions[a][1] - positions[b][1])
            for i, a in enumerate(names) for b in names[i + 1:]
        )
        short5 = sum(dists[:5]) / 5
        long5 = sum(dists[5:]) / 5
        ratio = long5 / short5
        # Allow 5% off φ for stochastic SGD noise.
        assert abs(ratio - phi) / phi < 0.05, (
            f"K5 ratio {ratio:.3f} not within 5% of golden ratio "
            f"{phi:.3f} — smart-init isn't reaching the pentagon optimum"
        )

    def test_adjust_dispatcher_modes(self):
        """Overlap mode parser maps strings to canonical constants."""
        from gvpy.engines.layout.common.adjust import (
            _parse_adjust_mode, AM_NONE, AM_NSCALE, AM_SCALEXY,
            AM_PRISM, AM_VOR,
        )
        # Boolean shortcuts.
        assert _parse_adjust_mode("")[0] == AM_NONE
        assert _parse_adjust_mode("true")[0] == AM_NONE
        assert _parse_adjust_mode("True")[0] == AM_NONE
        assert _parse_adjust_mode("1")[0] == AM_NONE
        assert _parse_adjust_mode("false")[0] == AM_PRISM
        assert _parse_adjust_mode("0")[0] == AM_PRISM
        # Named modes.
        assert _parse_adjust_mode("scale")[0] == AM_NSCALE
        assert _parse_adjust_mode("scalexy")[0] == AM_SCALEXY
        assert _parse_adjust_mode("voronoi")[0] == AM_VOR
        assert _parse_adjust_mode("prism")[0] == AM_PRISM
        # Prism with iteration count suffix.
        assert _parse_adjust_mode("prism100")[0] == AM_PRISM
        # Unknown -> treat as false (PRISM fallback).
        assert _parse_adjust_mode("garbage")[0] == AM_PRISM

    def test_scale_adjust_separates_overlap(self):
        """Uniform scaling clears overlap on a 2-node case."""
        from gvpy.engines.layout.common.adjust import (
            scale_adjust, _has_overlap,
        )

        class FakeLN:
            def __init__(self, x, y, w, h):
                self.x = x
                self.y = y
                self.width = w
                self.height = h
                self.pinned = False

        class FakeLayout:
            def __init__(self):
                self.lnodes = {
                    "a": FakeLN(10.0, 10.0, 200.0, 200.0),
                    "b": FakeLN(60.0, 10.0, 200.0, 200.0),
                }
                self.sep = 0.0
                self.overlap = "scale"

        layout = FakeLayout()
        assert _has_overlap(layout)
        iters = scale_adjust(layout)
        assert iters > 0
        assert not _has_overlap(layout)

    def test_voronoi_adjust_clears_grid_overlap(self):
        """Voronoi-cell-centroid iteration clears overlapping
        grid layout."""
        from gvpy.engines.layout.common.adjust import _has_overlap
        from gvpy.engines.layout.common.voronoi import voronoi_adjust

        class FakeLN:
            def __init__(self, x, y, w, h):
                self.x = x
                self.y = y
                self.width = w
                self.height = h
                self.pinned = False

        class FakeLayout:
            def __init__(self):
                # 3×3 grid spaced 30pt with 60×60 boxes — heavily overlapping.
                self.lnodes = {
                    f"n{i}{j}": FakeLN(i * 30.0, j * 30.0, 60.0, 60.0)
                    for i in range(3) for j in range(3)
                }
                self.sep = 0.0
                self.overlap = "voronoi"

        layout = FakeLayout()
        assert _has_overlap(layout)
        iters = voronoi_adjust(layout, max_iter=30)
        assert iters > 0
        assert not _has_overlap(layout)

    def test_scale_adjust_marriott_closed_form(self):
        """Marriott closed-form scale picks a single optimal factor.

        Two nodes overlap horizontally with dx=50 and 200×200 boxes.
        Optimal uniform scale = 200/50 = 4.0.  After applying, the
        x-distance becomes 50×4 = 200 = sum of half-widths, no overlap.
        """
        from gvpy.engines.layout.common.adjust import (
            scale_adjust, _has_overlap,
        )

        class FakeLN:
            def __init__(self, x, y, w, h):
                self.x, self.y = x, y
                self.width, self.height = w, h
                self.pinned = False

        class FakeLayout:
            def __init__(self):
                self.lnodes = {
                    "a": FakeLN(10.0, 10.0, 200.0, 200.0),
                    "b": FakeLN(60.0, 10.0, 200.0, 200.0),
                }
                self.sep = 0.0
                self.overlap = "scale"

        layout = FakeLayout()
        assert _has_overlap(layout)
        applied = scale_adjust(layout)
        assert applied == 1  # Marriott applies once, not iteratively.
        assert not _has_overlap(layout)
        # Check uniform 4× scale: a.x went 10 → 40, b.x went 60 → 240.
        assert abs(layout.lnodes["a"].x - 40.0) < 1e-6
        assert abs(layout.lnodes["b"].x - 240.0) < 1e-6

    def test_scalexy_horizontal_overlap_uses_x_only(self):
        """scalexy should scale only X for a horizontally-aligned pair."""
        from gvpy.engines.layout.common.adjust import (
            scalexy_adjust, _has_overlap,
        )

        class FakeLN:
            def __init__(self, x, y, w, h):
                self.x, self.y = x, y
                self.width, self.height = w, h
                self.pinned = False

        class FakeLayout:
            def __init__(self):
                # dy = 0 → optimal solution scales x only.
                self.lnodes = {
                    "a": FakeLN(10.0, 10.0, 200.0, 200.0),
                    "b": FakeLN(60.0, 10.0, 200.0, 200.0),
                }
                self.sep = 0.0
                self.overlap = "scalexy"

        layout = FakeLayout()
        assert scalexy_adjust(layout) == 1
        assert not _has_overlap(layout)
        # Y unchanged.
        assert layout.lnodes["a"].y == 10.0
        assert layout.lnodes["b"].y == 10.0

    def test_compress_skips_when_overlap_present(self):
        """``compress_adjust`` returns 0 if the layout has overlap."""
        from gvpy.engines.layout.common.adjust import compress_adjust

        class FakeLN:
            def __init__(self, x, y, w, h):
                self.x, self.y = x, y
                self.width, self.height = w, h
                self.pinned = False

        class FakeLayout:
            def __init__(self):
                self.lnodes = {
                    "a": FakeLN(0.0, 0.0, 50.0, 50.0),
                    "b": FakeLN(20.0, 0.0, 50.0, 50.0),
                }
                self.sep = 0.0
                self.overlap = "compress"

        layout = FakeLayout()
        assert compress_adjust(layout) == 0  # overlap present → no-op.

    def test_compress_shrinks_when_clear(self):
        """``compress_adjust`` shrinks an over-spaced layout uniformly."""
        from gvpy.engines.layout.common.adjust import (
            compress_adjust, _has_overlap,
        )

        class FakeLN:
            def __init__(self, x, y, w, h):
                self.x, self.y = x, y
                self.width, self.height = w, h
                self.pinned = False

        class FakeLayout:
            def __init__(self):
                self.lnodes = {
                    "a": FakeLN(0.0, 0.0, 50.0, 50.0),
                    "b": FakeLN(200.0, 0.0, 50.0, 50.0),
                }
                self.sep = 0.0
                self.overlap = "compress"

        layout = FakeLayout()
        assert compress_adjust(layout) == 1
        # Pair touch-scale = 50 / 200 = 0.25; b.x → 50, just touching.
        assert abs(layout.lnodes["b"].x - 50.0) < 1e-6
        assert not _has_overlap(layout)

    def test_ortho_clears_overlap(self):
        """``ortho_adjust`` clears overlap by sliding pairs apart."""
        from gvpy.engines.layout.common.adjust import (
            ortho_adjust, _has_overlap,
        )

        class FakeLN:
            def __init__(self, x, y, w, h):
                self.x, self.y = x, y
                self.width, self.height = w, h
                self.pinned = False

        class FakeLayout:
            def __init__(self):
                self.lnodes = {
                    "a": FakeLN(0.0, 0.0, 100.0, 50.0),
                    "b": FakeLN(50.0, 0.0, 100.0, 50.0),
                }
                self.sep = 0.0
                self.overlap = "ortho"

        layout = FakeLayout()
        assert _has_overlap(layout)
        ortho_adjust(layout, axes="both")
        assert not _has_overlap(layout)

    def test_voronoi_dispatches_via_overlap_attr(self):
        """``overlap=voronoi`` and ``overlap=false`` both route to
        the Voronoi-based remover."""
        # End-to-end smoke: the dispatcher must select the Voronoi
        # path for both AM_VOR and AM_PRISM and not crash.
        for ov in ("voronoi", "false", "prism"):
            r = neato_gv(
                f"graph G {{ overlap={ov}; "
                f"node [shape=box, width=2.0, height=1.5]; "
                f"a -- b; a -- c; b -- c; a -- d; b -- d; c -- d; }}"
            )
            assert len(r["nodes"]) == 4

    def test_polygon_centroid_unit_square(self):
        """Centroid of unit square is (0.5, 0.5), area 1."""
        import numpy as np
        from gvpy.engines.layout.common.voronoi import _polygon_centroid
        verts = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        cx, cy, area = _polygon_centroid(verts)
        assert abs(cx - 0.5) < 1e-9
        assert abs(cy - 0.5) < 1e-9
        assert abs(area - 1.0) < 1e-9

    def test_splines_default_is_bezier(self):
        """Default ``splines`` produces 4-point cubic Bezier routes."""
        r = neato_gv("graph G { a -- b -- c -- a; }")
        for e in r["edges"]:
            assert e.get("spline_type") == "bezier"
            assert len(e["points"]) >= 4
            # Bezier control point count must satisfy 3k + 1.
            assert (len(e["points"]) - 1) % 3 == 0

    def test_splines_polyline_mode(self):
        """``splines=polyline`` produces polyline routes."""
        r = neato_gv("graph G { splines=polyline; a -- b -- c -- a; }")
        for e in r["edges"]:
            assert e.get("spline_type") == "polyline"
            assert len(e["points"]) >= 2

    def test_splines_line_mode(self):
        """``splines=line`` produces straight lines (no obstacle avoidance)."""
        r = neato_gv("graph G { splines=line; a -- b -- c -- a; }")
        for e in r["edges"]:
            assert e.get("spline_type") == "line"
            assert len(e["points"]) == 2

    def test_splines_none_falls_back(self):
        """``splines=false`` keeps the base 2-point straight-line edges."""
        r = neato_gv("graph G { splines=false; a -- b; }")
        # spline_type may not be set when no routing was performed.
        e = r["edges"][0]
        assert len(e["points"]) == 2

    def test_pivot_mds_smoke(self):
        """PivotMDS produces finite N×dim coordinates."""
        import numpy as np
        from gvpy.engines.layout.common.pivot_mds import pivot_mds
        # Path-style distance matrix
        N = 6
        dist = [[float(abs(i - j)) for j in range(N)] for i in range(N)]
        coords = pivot_mds(dist, N, n_pivots=4, dim=2, seed=42)
        assert coords.shape == (N, 2)
        assert np.all(np.isfinite(coords))

    def test_sgd_y_shape_near_optimal(self):
        """SGD on Y-shape converges to the analytical optimum r≈76.8.

        For a star with 3 leaves, distances root-leaf=72, leaf-leaf=144,
        the energy minimum (computed analytically) is at radius r ≈
        76.8 — slightly above 72 because leaf-leaf springs pull leaves
        outward.  SGD should land within a few percent of that.
        """
        import math
        r = neato_gv("graph G { mode=sgd; root -- a; root -- b; root -- c; }")
        positions = {n["name"]: (n["x"], n["y"]) for n in r["nodes"]}
        for leaf in ("a", "b", "c"):
            d = math.hypot(positions["root"][0] - positions[leaf][0],
                           positions["root"][1] - positions[leaf][1])
            # Analytical optimum r ≈ 76.8; allow ±15% for SGD noise.
            assert 65.0 < d < 88.0, (
                f"root-{leaf}: {d:.1f} outside expected range "
                f"[65, 88] (analytical optimum 76.8)"
            )

    def test_kk_path_5_uniform_spacing(self):
        """KK on a 5-path produces near-uniform adjacent spacing.

        Asymmetric topologies are robust to KK's local-minimum
        pitfalls (no symmetric saddle).  Adjacent spans should
        agree to within ~3% after convergence.
        """
        import math
        r = neato_gv("graph G { mode=KK; a -- b -- c -- d -- e; }")
        positions = {n["name"]: (n["x"], n["y"]) for n in r["nodes"]}
        adj = [
            math.hypot(positions[u][0] - positions[v][0],
                       positions[u][1] - positions[v][1])
            for u, v in [("a", "b"), ("b", "c"),
                         ("c", "d"), ("d", "e")]
        ]
        assert min(adj) > 0
        ratio = max(adj) / min(adj)
        assert ratio < 1.05, f"Adjacent path spans should be uniform, got {ratio:.3f}"

    def test_stress_monotonically_decreases(self):
        """SMACOF stress sequence is monotonically non-increasing.

        Captures the iteration trace via GVPY_TRACE_NEATO=1 and
        verifies each step decreases (or holds) the stress.
        """
        import os
        import io
        import sys
        from gvpy.engines.layout.neato import NeatoLayout
        from gvpy.grammar.gv_reader import read_gv

        old_env = os.environ.get("GVPY_TRACE_NEATO", "")
        os.environ["GVPY_TRACE_NEATO"] = "1"
        old_stderr = sys.stderr
        try:
            buf = io.StringIO()
            sys.stderr = buf
            g = read_gv("graph G { a -- b -- c -- a; b -- d; c -- e; }")
            NeatoLayout(g).layout()
            output = buf.getvalue()
        finally:
            sys.stderr = old_stderr
            if old_env:
                os.environ["GVPY_TRACE_NEATO"] = old_env
            else:
                os.environ.pop("GVPY_TRACE_NEATO", None)

        stresses = []
        for line in output.splitlines():
            if "stress=" not in line:
                continue
            tok = line.split("stress=")[1].split()[0]
            try:
                stresses.append(float(tok))
            except ValueError:
                continue
        assert len(stresses) >= 2
        for i in range(1, len(stresses)):
            assert stresses[i] <= stresses[i - 1] + 1e-6, (
                f"Stress increased at step {i}: "
                f"{stresses[i - 1]:.6f} -> {stresses[i]:.6f}"
            )
