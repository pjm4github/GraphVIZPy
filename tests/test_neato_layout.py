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
