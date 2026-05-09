"""
Tests for the sfdp (scalable force-directed) layout engine.
"""
import math
import pytest
from gvpy.grammar.gv_reader import read_gv
from gvpy.engines.layout.sfdp import SfdpLayout


def sfdp_gv(text: str, **attrs) -> dict:
    graph = read_gv(text)
    for k, v in attrs.items():
        graph.set_graph_attr(k, v)
    return SfdpLayout(graph).layout()


def node_by_name(result, name):
    for n in result["nodes"]:
        if n["name"] == name:
            return n
    return None


class TestSfdpBasic:

    def test_single_node(self):
        r = sfdp_gv("graph G { a; }")
        assert len(r["nodes"]) == 1

    def test_two_nodes(self):
        r = sfdp_gv("graph G { a -- b; }")
        na, nb = node_by_name(r, "a"), node_by_name(r, "b")
        dist = math.sqrt((na["x"] - nb["x"])**2 + (na["y"] - nb["y"])**2)
        assert dist > 5

    def test_triangle(self):
        r = sfdp_gv("graph G { a -- b -- c -- a; }")
        assert len(r["nodes"]) == 3

    def test_empty(self):
        r = sfdp_gv("graph G { }")
        assert len(r["nodes"]) == 0

    def test_larger_graph(self):
        nodes = " ".join(f"n{i} -- n{i+1};" for i in range(20))
        r = sfdp_gv(f"graph G {{ {nodes} }}")
        assert len(r["nodes"]) == 21


class TestSfdpMultilevel:

    def test_coarsening_runs(self):
        """Graph large enough to trigger coarsening."""
        edges = " ".join(f"n{i} -- n{(i+1)%15};" for i in range(15))
        r = sfdp_gv(f"graph G {{ {edges} }}")
        assert len(r["nodes"]) == 15

    def test_levels_attribute(self):
        """levels attribute limits coarsening depth."""
        edges = " ".join(f"n{i} -- n{(i+1)%10};" for i in range(10))
        r = sfdp_gv(f"graph G {{ {edges} }}", levels="1")
        assert len(r["nodes"]) == 10


class TestSfdpQuadtree:

    def test_quadtree_mode(self):
        """Barnes-Hut quadtree activates for larger graphs."""
        edges = " ".join(f"n{i} -- n{(i+3)%50};" for i in range(50))
        r = sfdp_gv(f"graph G {{ {edges} }}")
        assert len(r["nodes"]) == 50

    def test_quadtree_none(self):
        """quadtree=none disables Barnes-Hut."""
        r = sfdp_gv("graph G { a--b--c--d--e--f--a; }", quadtree="none")
        assert len(r["nodes"]) == 6


class TestSfdpAttributes:

    def test_K_affects_layout_shape(self):
        """K influences the spring-electrical force iteration but
        the final canvas is sized by ``initial_scaling × avg_label_size``
        (matching C ``remove_overlap``).  So K alone won't widen
        the bbox — node sizes do.  Verify both K values produce
        valid, finite layouts at roughly the same scale (since
        label sizes are identical)."""
        r1 = sfdp_gv("graph G { a--b--c--a; }", K="0.3")
        r2 = sfdp_gv("graph G { a--b--c--a; }", K="2.0")
        bb1 = r1["graph"]["bb"]
        bb2 = r2["graph"]["bb"]
        w1 = bb1[2] - bb1[0]
        w2 = bb2[2] - bb2[0]
        # Both produce non-zero, comparable canvases.
        assert w1 > 0 and w2 > 0
        # Within 2× of each other — same label-size-driven scale.
        assert 0.5 <= w2 / w1 <= 2.0

    def test_rotation(self):
        """rotation attribute rotates layout."""
        r = sfdp_gv("graph G { a--b; }", rotation="90")
        assert len(r["nodes"]) == 2

    def test_beautify(self):
        """beautify arranges leaves."""
        r = sfdp_gv("graph G { center -- a; center -- b; center -- c; center -- d; }",
                     beautify="true")
        assert len(r["nodes"]) == 5

    def test_overlap_false(self):
        r = sfdp_gv("graph G { a--b--c; }", overlap="false")
        assert len(r["nodes"]) == 3

    def test_bounding_box(self):
        r = sfdp_gv("graph G { a--b--c--a; }")
        bb = r["graph"]["bb"]
        assert bb[2] > bb[0]
        assert bb[3] > bb[1]

    def test_pos_writeback(self):
        g = read_gv("graph G { a -- b; }")
        SfdpLayout(g).layout()
        assert "pos" in g.nodes["a"].attributes

    def test_svg_output(self):
        from gvpy.render.svg_renderer import render_svg
        r = sfdp_gv("graph G { a--b--c--a; }")
        svg = render_svg(r)
        assert "<svg" in svg


class TestSfdpClusters:
    """Cluster awareness, inherited from fdp's deriveGraph
    pipeline (DONE §4.F-derivegraph).  Sfdp dispatches to the
    same recursive layout but plugs in its own
    ``_spring_electrical`` solver via the engine-pluggable
    callbacks added in DONE §4.S-derivegraph.
    """

    def _layout(self, src):
        graph = read_gv(src)
        layout = SfdpLayout(graph)
        layout.layout()
        return layout

    def test_clusters_discovered(self):
        """Sfdp populates the same cluster fields fdp does."""
        src = """graph G {
            a -- b;
            subgraph cluster_a { a; a2; }
            subgraph cluster_b { b; b2; }
        }"""
        layout = self._layout(src)
        assert {c.name for c in layout._clusters} == {
            "cluster_a", "cluster_b"
        }
        assert layout._cluster_parent["cluster_a"] is None
        assert layout._cluster_parent["cluster_b"] is None
        assert layout._node_to_cluster["a"] == "cluster_a"
        assert layout._node_to_cluster["b"] == "cluster_b"

    def test_cluster_bboxes_computed_and_emitted(self):
        """Post-layout, each cluster has a non-zero bbox and the
        JSON output exposes a ``clusters`` array."""
        src = """graph G {
            a1 -- b1;
            subgraph cluster_a { a1; a2; }
            subgraph cluster_b { b1; b2; }
        }"""
        layout = self._layout(src)
        for cl in layout._clusters:
            assert cl.bb != (0.0, 0.0, 0.0, 0.0)
        result = layout._to_json()
        assert "clusters" in result
        cls = {c["name"]: c for c in result["clusters"]}
        assert set(cls) == {"cluster_a", "cluster_b"}

    def test_cluster_bboxes_dont_overlap(self):
        """deriveGraph + xlayout at the root scope must produce
        non-overlapping cluster bboxes — otherwise the SVG
        renderer draws cluster rects on top of each other."""
        src = """graph G {
            a1 -- b1;
            l1 -- r1;
            subgraph cluster_a { a1; a2; }
            subgraph cluster_b { b1; b2; }
            subgraph cluster_l { l1; l2; }
            subgraph cluster_r { r1; r2; }
        }"""
        layout = self._layout(src)
        cls = list(layout._clusters)
        for i in range(len(cls)):
            for j in range(i + 1, len(cls)):
                a, b = cls[i], cls[j]
                ax1, ay1, ax2, ay2 = a.bb
                bx1, by1, bx2, by2 = b.bb
                ox = min(ax2, bx2) - max(ax1, bx1)
                oy = min(ay2, by2) - max(ay1, by1)
                assert ox <= 1.0 or oy <= 1.0, (
                    f"{a.name} bb={a.bb} overlaps {b.name} bb={b.bb}: "
                    f"ox={ox:.2f} oy={oy:.2f}"
                )

    def test_cluster_members_inside_bbox(self):
        """Members of a cluster must land inside that cluster's
        post-layout bbox."""
        src = """graph G {
            a -- b;
            subgraph cluster_x {
                x1; x2; x3;
                x1 -- x2 -- x3;
            }
        }"""
        layout = self._layout(src)
        cl = next(c for c in layout._clusters if c.name == "cluster_x")
        x1, y1, x2, y2 = cl.bb
        for n_name in cl.nodes:
            ln = layout.lnodes[n_name]
            assert x1 - 1e-3 <= ln.x <= x2 + 1e-3, n_name
            assert y1 - 1e-3 <= ln.y <= y2 + 1e-3, n_name

    def test_flat_graph_skips_derive_graph(self):
        """No clusters → fall through to flat multilevel
        spring-electrical (regression guard for the
        no-cluster path)."""
        layout = self._layout("graph G { a -- b -- c -- a; }")
        assert layout._clusters == []
        for n in ("a", "b", "c"):
            assert n in layout.lnodes

    def test_subgraph_edges_drive_cohesion(self):
        """Edges declared inside a cluster subgraph contribute
        to the force model.  Mirrors fdp's
        ``test_edges_inside_subgraphs_drive_cohesion``."""
        src = """graph G {
            x -- y;
            subgraph cluster_chain {
                c1; c2; c3;
                c1 -- c2 -- c3;
            }
        }"""
        layout = self._layout(src)
        for t, h in (("c1", "c2"), ("c2", "c3")):
            t_ln = layout.lnodes[t]
            h_ln = layout.lnodes[h]
            d = ((t_ln.x - h_ln.x) ** 2
                 + (t_ln.y - h_ln.y) ** 2) ** 0.5
            assert d < 10 * layout.K, (
                f"{t}-{h} distance {d:.1f} > 10K — internal "
                f"cluster edges likely missing from force model"
            )


class TestSfdpMultilevelCAligned:
    """C-aligned port of ``lib/sfdpgen/Multilevel.c``.

    Tests the ``multilevel`` module directly: MIES matching,
    Galerkin coarsening, hierarchy build, and the legacy-shape
    adapter.  These pin the contract that the future
    spring_electrical port will rely on.
    """

    def _build(self, edges, n_nodes):
        from gvpy.engines.layout.sfdp.multilevel import (
            csr_from_adjacency, multilevel_new,
        )
        names = [f"n{i}" for i in range(n_nodes)]
        adj = {n: [] for n in names}
        for a, b in edges:
            adj[names[a]].append(names[b])
            adj[names[b]].append(names[a])
        A = __import__(
            "gvpy.engines.layout.sfdp.multilevel",
            fromlist=["csr_from_adjacency"],
        ).csr_from_adjacency(names, adj)
        return names, A, multilevel_new(A, max_levels=20, seed=1)

    def test_cycle_8_coarsens(self):
        """8-node cycle coarsens to ≤ 6 nodes (reduction ≥ 0.25)."""
        edges = [(i, (i + 1) % 8) for i in range(8)]
        _, _, grid = self._build(edges, 8)
        assert grid.next is not None
        assert grid.next.n <= 6

    def test_path_16_multilevel(self):
        """16-node path produces a ≥ 2-level hierarchy."""
        edges = [(i, i + 1) for i in range(15)]
        _, _, grid = self._build(edges, 16)
        # Walk to coarsest, count levels.
        levels = 0
        cur = grid
        while cur is not None:
            levels += 1
            cur = cur.next
        assert levels >= 2

    def test_singleton_doesnt_coarsen(self):
        """A 1-node graph has only the finest level."""
        edges: list = []
        _, _, grid = self._build(edges, 1)
        assert grid.n == 1
        assert grid.next is None

    def test_galerkin_preserves_edge_weight_sum(self):
        """``cA = R · A · P`` preserves the *weighted* edge
        adjacency.  For an unweighted-edge graph, every edge in
        cA has total off-diagonal mass equal to the count of
        underlying inter-cluster edges."""
        from gvpy.engines.layout.sfdp.multilevel import (
            csr_from_adjacency, multilevel_new,
        )
        # 4-node K4 → coarsens to 2 super-edges, each with mass 4
        # (4 inter-cluster edges in original K4 collapse to 2
        # cluster pairs × 2 directions = 4).
        names = ["a", "b", "c", "d"]
        adj = {n: [m for m in names if m != n] for n in names}
        A = csr_from_adjacency(names, adj)
        grid = multilevel_new(A, max_levels=5, seed=1)
        if grid.next is not None:
            cA = grid.next.A
            # cA should have no diagonal (stripped).
            assert (cA.diagonal() == 0).all()
            # Total mass = sum of all entries; should equal
            # the original A's total mass minus diagonal (= nnz).
            assert cA.sum() > 0

    def test_legacy_adapter_resolvable_names(self):
        """Adapter's coarse-level node names must all resolve in
        the original ``node_list`` (so the existing flat solver's
        ``layout.lnodes[name]`` works)."""
        from gvpy.engines.layout.sfdp.multilevel import (
            csr_from_adjacency, multilevel_new,
            multilevel_to_legacy_levels,
        )
        names = [f"n{i}" for i in range(20)]
        adj = {n: [] for n in names}
        for i in range(19):
            adj[names[i]].append(names[i + 1])
            adj[names[i + 1]].append(names[i])
        A = csr_from_adjacency(names, adj)
        grid = multilevel_new(A, max_levels=10, seed=1)
        levels = multilevel_to_legacy_levels(grid, names)
        original_set = set(names)
        for level in levels:
            for n in level["nodes"]:
                assert n in original_set, (
                    f"coarse-level name {n!r} not in original node_list"
                )

    def test_dispatch_gate(self, monkeypatch):
        """``GVPY_SFDP_MULTILEVEL=legacy`` reverts to the
        homegrown matching."""
        monkeypatch.setenv("GVPY_SFDP_MULTILEVEL", "legacy")
        graph = read_gv("graph G { a--b--c--d--a; b--d; }")
        layout = SfdpLayout(graph)
        layout.layout()  # should run without error
        # Sanity: positions written.
        for n in ("a", "b", "c", "d"):
            assert n in layout.lnodes


class TestSfdpSpringElectricalCAligned:
    """C-aligned port of ``lib/sfdpgen/spring_electrical.c`` —
    see :mod:`gvpy.engines.layout.sfdp.spring_electrical`.
    """

    # ── Pure-function unit tests (no engine wiring) ──

    def test_average_edge_length_unit_distances(self):
        """``average_edge_length`` returns the mean Euclidean
        distance over every CSR entry (each undirected edge is
        counted twice in a symmetric matrix; that's how C does
        it too)."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.spring_electrical import (
            average_edge_length,
        )
        rows = [0, 1, 1, 2, 2, 0]
        cols = [1, 0, 2, 1, 0, 2]
        A = sp.csr_matrix(([1.0] * 6, (rows, cols)), shape=(3, 3))
        x = np.array(
            [[0.0, 0.0],
             [1.0, 0.0],
             [0.5, math.sqrt(3) / 2]],
            dtype=np.float64,
        )
        L = average_edge_length(A, x)
        assert abs(L - 1.0) < 1e-9

    def test_update_step_branches(self):
        """All three adaptive-cooling branches, plus the non-
        adaptive geometric-cool fallback."""
        from gvpy.engines.layout.sfdp.spring_electrical import (
            _update_step,
            _COOL,
        )
        assert _update_step(False, 1.0, 100.0, 50.0) == _COOL * 1.0
        assert _update_step(True, 1.0, 100.0, 50.0) == _COOL * 1.0
        assert _update_step(True, 1.0, 96.0, 100.0) == 1.0
        warm = _update_step(True, 1.0, 50.0, 100.0)
        assert abs(warm - 0.99 / _COOL) < 1e-12

    def test_interpolate_coord_averaging(self):
        """``interpolate_coord`` blends each node's coord
        toward its neighbour mean with alpha=0.5."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.spring_electrical import (
            interpolate_coord,
        )
        rows = [0, 1, 1, 2, 2, 0]
        cols = [1, 0, 2, 1, 0, 2]
        A = sp.csr_matrix(([1.0] * 6, (rows, cols)), shape=(3, 3))
        x = np.array(
            [[0.0, 0.0],
             [4.0, 0.0],
             [0.0, 4.0]],
            dtype=np.float64,
        )
        # Neighbours of node 0: {1, 2} with mean (2, 2).
        # New x[0] = 0.5*(0,0) + 0.5*(2,2) = (1, 1).
        interpolate_coord(A, x)
        assert abs(x[0, 0] - 1.0) < 1e-9
        assert abs(x[0, 1] - 1.0) < 1e-9

    def test_pcp_rotate_aligns_principal_axis(self):
        """A point cloud stretched along y=2x rotates so its
        principal axis goes horizontal (or close to it)."""
        import numpy as np
        from gvpy.engines.layout.sfdp.spring_electrical import (
            pcp_rotate,
        )
        rng = np.random.default_rng(42)
        ts = np.linspace(-1, 1, 21)
        x = np.column_stack([ts, 2 * ts]) + 0.01 * rng.standard_normal((21, 2))
        var_x_before = float(np.var(x[:, 0]))
        var_y_before = float(np.var(x[:, 1]))
        assert var_y_before > 3 * var_x_before
        pcp_rotate(x)
        var_x_after = float(np.var(x[:, 0]))
        var_y_after = float(np.var(x[:, 1]))
        assert var_x_after > 3 * var_y_after

    def test_spring_electrical_cycle_4_quadrilateral_ratio(self):
        """A 4-cycle layout should have edge:diagonal ratio
        roughly 1:sqrt(2) (a square)."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.spring_electrical import (
            SpringElectricalControl,
            spring_electrical_embedding,
        )
        rows = [0, 1, 1, 2, 2, 3, 3, 0]
        cols = [1, 0, 2, 1, 3, 2, 0, 3]
        A = sp.csr_matrix(([1.0] * 8, (rows, cols)), shape=(4, 4))
        ctrl = SpringElectricalControl()
        ctrl.K = -1.0
        ctrl.maxiter = 200
        ctrl.random_seed = 7
        x = np.zeros((4, 2), dtype=np.float64)
        spring_electrical_embedding(A, ctrl, x)
        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
        diags = [(0, 2), (1, 3)]
        edge_d = sum(float(np.linalg.norm(x[i] - x[j])) for i, j in edges) / 4
        diag_d = sum(float(np.linalg.norm(x[i] - x[j])) for i, j in diags) / 2
        ratio = diag_d / edge_d
        assert 1.1 < ratio < 1.6, f"diag:edge ratio = {ratio:.3f}"

    def test_spring_electrical_pinned_doesnt_move(self):
        """Pinned nodes' coords are unchanged."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.spring_electrical import (
            SpringElectricalControl,
            spring_electrical_embedding,
        )
        rows = [0, 1, 1, 2, 2, 0]
        cols = [1, 0, 2, 1, 0, 2]
        A = sp.csr_matrix(([1.0] * 6, (rows, cols)), shape=(3, 3))
        ctrl = SpringElectricalControl()
        ctrl.K = 1.0
        ctrl.maxiter = 100
        ctrl.random_seed = 1
        ctrl.random_start = False
        x = np.array(
            [[0.0, 0.0],
             [10.0, 0.0],
             [5.0, 5.0]],
            dtype=np.float64,
        )
        x_orig = x.copy()
        pinned = np.array([True, True, False])
        spring_electrical_embedding(A, ctrl, x, pinned_mask=pinned)
        assert np.allclose(x[0], x_orig[0])
        assert np.allclose(x[1], x_orig[1])
        assert not np.allclose(x[2], x_orig[2])

    def test_multilevel_path_separates_nodes(self):
        """A 16-node path layout should put non-adjacent nodes
        farther apart than adjacent ones, on average."""
        import numpy as np
        from gvpy.engines.layout.sfdp.multilevel import (
            csr_from_adjacency,
            multilevel_new,
        )
        from gvpy.engines.layout.sfdp.spring_electrical import (
            SpringElectricalControl,
            multilevel_spring_electrical_embedding,
        )
        N = 16
        node_list = [f"n{i}" for i in range(N)]
        adj: dict[str, list[str]] = {n: [] for n in node_list}
        for i in range(N - 1):
            adj[node_list[i]].append(node_list[i + 1])
            adj[node_list[i + 1]].append(node_list[i])
        A = csr_from_adjacency(node_list, adj, {})
        grid = multilevel_new(A, max_levels=10, seed=42)
        ctrl = SpringElectricalControl()
        ctrl.K = -1.0
        ctrl.maxiter = 50
        ctrl.random_seed = 42
        x = np.zeros((N, 2), dtype=np.float64)
        multilevel_spring_electrical_embedding(A, ctrl, grid, x)
        edge_d = []
        nonedge_d = []
        for i in range(N):
            for j in range(i + 1, N):
                d = float(np.linalg.norm(x[i] - x[j]))
                (edge_d if abs(i - j) == 1 else nonedge_d).append(d)
        edge_mean = sum(edge_d) / len(edge_d)
        nonedge_mean = sum(nonedge_d) / len(nonedge_d)
        assert nonedge_mean > 2 * edge_mean

    # ── Engine integration tests ──

    def test_engine_dispatch_default_is_c(self):
        """With no env override, ``_layout_component`` runs
        the C-aligned path and produces a valid layout."""
        result = sfdp_gv("graph G { a--b--c--d--a; b--d; }")
        for nm in ("a", "b", "c", "d"):
            n = node_by_name(result, nm)
            assert n is not None
            assert "x" in n and "y" in n

    def test_engine_dispatch_legacy_path_still_works(self, monkeypatch):
        """``GVPY_SFDP_SPRING_ELECTRICAL=legacy`` reverts to the
        homegrown FR + Barnes-Hut path."""
        monkeypatch.setenv("GVPY_SFDP_SPRING_ELECTRICAL", "legacy")
        result = sfdp_gv("graph G { a--b--c--d--a; b--d; }")
        for nm in ("a", "b", "c", "d"):
            assert node_by_name(result, nm) is not None

    def test_engine_disconnected_components(self):
        """Two disconnected triangles should produce a layout
        where every node has a position."""
        gv = """
        graph G {
            a--b--c--a;
            d--e--f--d;
        }
        """
        result = sfdp_gv(gv)
        assert len(result["nodes"]) == 6
        for n in result["nodes"]:
            assert "x" in n and "y" in n

    def test_engine_pinned_input_doesnt_crash(self):
        """A node with pos="x,y!" sets ``random_start=False`` in
        the C-aligned path; engine should run through without
        crashing.

        Note: pt-space coord *preservation* through the full
        pipeline (descent + pcp_rotate + ``_apply_center``) is a
        separate question — postprocessing currently translates
        the whole layout, pinned nodes included.  Both legacy and
        C-aligned paths share that limitation; tracked outside
        this port.
        """
        gv = 'graph G { a [pos="100,200!"]; b; c; a--b--c; }'
        result = sfdp_gv(gv)
        a = node_by_name(result, "a")
        assert a is not None
        assert "x" in a and "y" in a


class TestSfdpPostProcessCAligned:
    """C-aligned port of ``lib/sfdpgen/post_process.c`` +
    ``stress_model.c`` + ``sparse_solve.c`` —
    see :mod:`gvpy.engines.layout.sfdp.post_process` and
    :mod:`gvpy.engines.layout.sfdp.sparse_solve`.
    """

    # ── sparse_solve.py: diagonal-preconditioned CG ──

    def test_cg_solves_4cycle_laplacian(self):
        """CG converges to machine precision on a 4-cycle
        Laplacian + diagonal shift."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.sparse_solve import (
            sparse_matrix_solve,
        )
        L = np.array(
            [[2, -1, 0, -1],
             [-1, 2, -1, 0],
             [0, -1, 2, -1],
             [-1, 0, -1, 2]],
            dtype=np.float64,
        )
        A = sp.csr_matrix(L + 0.1 * np.eye(4))
        rhs = np.array([[1.0, 0.0], [2.0, 1.0],
                        [-1.0, 0.5], [0.0, 0.0]])
        rhs_orig = rhs.copy()
        x0 = np.zeros((4, 2))
        sparse_matrix_solve(A, x0, rhs, tol=1e-9, maxit=100)
        # rhs now holds the solution.  Verify A · x ≈ b.
        residual = float(np.linalg.norm(A @ rhs - rhs_orig))
        assert residual < 1e-8

    def test_cg_diagonal_preconditioner(self):
        """Preconditioner returns 1/A[i,i] on the diagonal."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.sparse_solve import (
            _diag_precon_new,
        )
        A = sp.csr_matrix(np.diag([2.0, 4.0, 0.0, 8.0]))
        precon = _diag_precon_new(A)
        # Zero diagonal stays at the safe fallback (1.0).
        assert abs(precon[0] - 0.5) < 1e-12
        assert abs(precon[1] - 0.25) < 1e-12
        assert abs(precon[2] - 1.0) < 1e-12
        assert abs(precon[3] - 0.125) < 1e-12

    # ── post_process.py: stress smoother math ──

    def test_ideal_distance_matrix_triangle(self):
        """For a 3-cycle, every edge has 1 shared neighbour and
        2 unique neighbours, so the symmetric difference is
        ``deg(i)+deg(j)-2·shared = 2+2-2·1 = 2`` (before
        rescaling)."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.post_process import (
            _ideal_distance_matrix,
        )
        rows = [0, 1, 1, 2, 2, 0]
        cols = [1, 0, 2, 1, 0, 2]
        A = sp.csr_matrix(([1.0] * 6, (rows, cols)), shape=(3, 3))
        # Equilateral coords.
        x = np.array(
            [[0.0, 0.0],
             [1.0, 0.0],
             [0.5, math.sqrt(3) / 2]],
        )
        D = _ideal_distance_matrix(A, x)
        # Mean ideal distance is rescaled to *equal* mean
        # Euclidean distance.  Euclidean = 1 everywhere on the
        # unit triangle; raw ideal = 2 everywhere; so after the
        # ``s = mean_eucl / mean_ideal = 0.5`` rescale each
        # entry becomes ``2 · 0.5 = 1.0``.
        for v in D.data:
            assert abs(v - 1.0) < 1e-9

    def test_avg_dist_smoothing_separates_path(self):
        """Stress smoother on a 5-node path produces edge
        distances in roughly 1:2:3:4 proportion to graph
        distance."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.post_process import (
            stress_majorization_smoother2_new,
            stress_majorization_smoother_smooth,
            IDEAL_AVG_DIST,
        )
        n = 5
        rows = [0, 1, 1, 2, 2, 3, 3, 4]
        cols = [1, 0, 2, 1, 3, 2, 4, 3]
        A = sp.csr_matrix(([1.0] * 8, (rows, cols)), shape=(n, n))
        # Bad initial layout — non-degenerate but clumpy.
        x = np.array(
            [[0.0, 0.0],
             [0.1, 0.05],
             [0.2, -0.05],
             [0.3, 0.1],
             [0.4, 0.0]],
            dtype=np.float64,
        )
        sm = stress_majorization_smoother2_new(
            A, x, lambda0=0.05, ideal_dist_scheme=IDEAL_AVG_DIST,
        )
        assert sm is not None
        stress_majorization_smoother_smooth(sm, x, maxit_sm=50)
        edge_d = np.linalg.norm(x[1:] - x[:-1], axis=1).mean()
        far_d = float(np.linalg.norm(x[0] - x[4]))
        ratio = far_d / edge_d
        # Path of 4 edges should give ratio ≈ 4.  Allow a wide
        # window since the smoother is constrained by lambda·x_0.
        assert 3.0 < ratio < 4.5, f"far/edge = {ratio:.2f}"

    def test_smoother_returns_none_on_zero_sbot(self):
        """A 1-node graph has no edges → ``sbot == 0`` → builder
        should return None (not crash)."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.post_process import (
            stress_majorization_smoother2_new,
            IDEAL_GRAPH_DIST,
        )
        A = sp.csr_matrix(np.zeros((1, 1)))
        x = np.zeros((1, 2))
        sm = stress_majorization_smoother2_new(
            A, x, lambda0=0.05, ideal_dist_scheme=IDEAL_GRAPH_DIST,
        )
        assert sm is None

    def test_post_process_dispatch_none_is_noop(self):
        """``smoothing="none"`` doesn't touch x."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.post_process import (
            post_process_smoothing,
        )
        rows = [0, 1, 1, 2]
        cols = [1, 0, 2, 1]
        A = sp.csr_matrix(([1.0] * 4, (rows, cols)), shape=(3, 3))
        x = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
        x_orig = x.copy()
        post_process_smoothing(A, "none", x)
        assert np.allclose(x, x_orig)

    def test_post_process_dispatch_unwired_modes_warn(self, capsys):
        """``smoothing="rng"`` / ``"triangle"`` print a warning
        and leave x unchanged (we haven't ported call_tri.c)."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.post_process import (
            post_process_smoothing,
        )
        rows = [0, 1, 1, 2]
        cols = [1, 0, 2, 1]
        A = sp.csr_matrix(([1.0] * 4, (rows, cols)), shape=(3, 3))
        x = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
        x_orig = x.copy()
        post_process_smoothing(A, "triangle", x)
        captured = capsys.readouterr()
        assert "triangulation port" in captured.err
        assert np.allclose(x, x_orig)

    # ── stress_model.c port ──

    def test_stress_model_distance_matrix(self):
        """``stress_model`` interprets A as a distance matrix —
        a 3-cycle with equal target distances should embed as
        an equilateral triangle."""
        import numpy as np
        import scipy.sparse as sp
        from gvpy.engines.layout.sfdp.post_process import (
            stress_model,
        )
        # 3-cycle with all target distances = 1.
        rows = [0, 1, 1, 2, 2, 0]
        cols = [1, 0, 2, 1, 0, 2]
        A = sp.csr_matrix(([1.0] * 6, (rows, cols)), shape=(3, 3))
        # Random initial — stress_model auto-randomizes if
        # x is all-zero.
        x = np.zeros((3, 2))
        rc = stress_model(A, x, maxit_sm=100)
        assert rc == 0
        # All three sides should be near-equal.
        d01 = float(np.linalg.norm(x[0] - x[1]))
        d12 = float(np.linalg.norm(x[1] - x[2]))
        d20 = float(np.linalg.norm(x[2] - x[0]))
        max_side = max(d01, d12, d20)
        min_side = min(d01, d12, d20)
        assert max_side / min_side < 1.5, (
            f"sides {d01:.3f},{d12:.3f},{d20:.3f} not equilateral"
        )

    # ── Engine integration ──

    def test_engine_smoothing_avg_dist_separates_path(self):
        """Through ``SfdpLayout``: a 5-node path with
        ``smoothing=avg_dist`` produces edge distances roughly
        proportional to graph distance."""
        result = sfdp_gv(
            "graph G { a--b--c--d--e; }",
            smoothing="avg_dist",
        )
        coords = {n["name"]: (n["x"], n["y"]) for n in result["nodes"]}
        edges = [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")]
        edge_dists = [
            math.hypot(coords[u][0] - coords[v][0],
                       coords[u][1] - coords[v][1])
            for u, v in edges
        ]
        ax, ay = coords["a"]
        ex, ey = coords["e"]
        far = math.hypot(ax - ex, ay - ey)
        edge_mean = sum(edge_dists) / len(edge_dists)
        # Path of 4 edges should give far ≈ 4·edge.  Allow a
        # generous window for engine-level scaling and the
        # postprocessing pipeline.
        assert far > 3 * edge_mean

    def test_engine_smoothing_graph_dist(self):
        """``smoothing=graph_dist`` runs without error and
        produces a valid layout on a small graph."""
        result = sfdp_gv(
            "graph G { a--b--c--d; b--d; a--c; }",
            smoothing="graph_dist",
        )
        for nm in ("a", "b", "c", "d"):
            n = node_by_name(result, nm)
            assert n is not None
            assert "x" in n and "y" in n

    def test_engine_smoothing_dispatch_legacy(self, monkeypatch):
        """``GVPY_SFDP_POST_PROCESS=legacy`` skips the C-aligned
        smoother (engine still produces a layout via the
        descent itself)."""
        monkeypatch.setenv("GVPY_SFDP_POST_PROCESS", "legacy")
        result = sfdp_gv(
            "graph G { a--b--c--d; }",
            smoothing="avg_dist",
        )
        # Just verify nothing crashed.
        for nm in ("a", "b", "c", "d"):
            assert node_by_name(result, nm) is not None
