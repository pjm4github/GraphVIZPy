"""Tests for gvpy.engines.layout.ortho.fpq + sgraph (Phase 2 port).

:func:`short_path` correctness is cross-checked against NetworkX's
Dijkstra on the same edge set.  sgraph edges are undirected for
traversal purposes (each edge index is added to both endpoints'
``adj_edge_list``), which matches NetworkX's default :class:`Graph`.
"""

from __future__ import annotations

import networkx as nx
import pytest

from gvpy.engines.layout.ortho import fpq, sgraph
from gvpy.engines.layout.ortho.sgraph import (
    UNSEEN,
    create_sedge,
    create_sgraph,
    create_snode,
    gsave,
    reset,
    short_path,
)


# ---------- PQ primitives ----------


class TestPq:
    def test_gen_then_empty(self):
        pq = fpq.pq_gen(10)
        assert pq.cnt == 0
        assert pq.size == 10
        assert fpq.pq_remove(pq) is None

    def test_insert_pops_in_max_val_order(self):
        # Build 4 snodes with distinct n_val; expect descending pops.
        g = create_sgraph(4)
        nodes = [create_snode(g) for _ in range(4)]
        for n, v in zip(nodes, [-5, -1, -10, -3]):
            n.n_val = v
        pq = fpq.pq_gen(4)
        for n in nodes:
            assert fpq.pq_insert(pq, n) == 0
        popped = []
        while True:
            n = fpq.pq_remove(pq)
            if n is None:
                break
            popped.append(n.n_val)
        assert popped == [-1, -3, -5, -10]

    def test_update_repositions(self):
        g = create_sgraph(3)
        a, b, c = (create_snode(g) for _ in range(3))
        a.n_val, b.n_val, c.n_val = -10, -5, -1
        pq = fpq.pq_gen(3)
        for n in (a, b, c):
            fpq.pq_insert(pq, n)
        # Improve a so it should pop first.
        fpq.pq_update(pq, a, 0)
        assert fpq.pq_remove(pq) is a
        assert a.n_val == 0

    def test_n_idx_invariant_holds_through_inserts(self):
        g = create_sgraph(5)
        nodes = [create_snode(g) for _ in range(5)]
        for n, v in zip(nodes, [-7, -2, -9, -4, -1]):
            n.n_val = v
        pq = fpq.pq_gen(5)
        for n in nodes:
            fpq.pq_insert(pq, n)
        # Every entry at index i should have node.n_idx == i.
        for i in range(1, pq.cnt + 1):
            assert pq.pq[i].n_idx == i


# ---------- sgraph construction ----------


class TestSgraphConstruction:
    def test_create_snode_assigns_index(self):
        g = create_sgraph(3)
        a = create_snode(g)
        b = create_snode(g)
        assert a.index == 0
        assert b.index == 1
        assert g.nnodes == 2

    def test_create_sedge_hooks_both_endpoints(self):
        g = create_sgraph(3)
        a, b, c = (create_snode(g) for _ in range(3))
        e = create_sedge(g, a, b, 1.5)
        assert e.v1 == 0 and e.v2 == 1
        assert a.adj_edge_list == [0]
        assert b.adj_edge_list == [0]
        assert c.adj_edge_list == []
        assert a.n_adj == 1 and b.n_adj == 1

    def test_capacity_exhausted_raises(self):
        g = create_sgraph(2)
        create_snode(g)
        create_snode(g)
        with pytest.raises(IndexError):
            create_snode(g)


# ---------- gsave / reset ----------


class TestGsaveReset:
    def test_roundtrip_preserves_structure(self):
        g = create_sgraph(10)
        a, b, c = (create_snode(g) for _ in range(3))
        create_sedge(g, a, b, 1.0)
        gsave(g)

        # Simulate a per-edge routing: add 2 terminal snodes + edges.
        t1 = create_snode(g)
        t2 = create_snode(g)
        create_sedge(g, a, t1, 2.0)
        create_sedge(g, t1, t2, 3.0)

        assert g.nnodes == 5
        assert g.nedges == 3
        assert a.n_adj == 2  # original + new edge to t1

        reset(g)

        assert g.nnodes == 3
        assert g.nedges == 1
        assert a.n_adj == 1
        assert a.adj_edge_list == [0]  # only the pre-gsave edge
        # Terminals (if the slots still exist) should have empty adj.
        for i in range(g.nnodes, min(g.nnodes + 2, len(g.nodes))):
            assert g.nodes[i].n_adj == 0


# ---------- short_path correctness ----------


def _build_triangle():
    """0-1 (w=1), 0-2 (w=4), 1-2 (w=2)."""
    g = create_sgraph(3)
    a, b, c = (create_snode(g) for _ in range(3))
    create_sedge(g, a, b, 1.0)
    create_sedge(g, a, c, 4.0)
    create_sedge(g, b, c, 2.0)
    return g, a, b, c


class TestShortPath:
    def test_direct_edge_shortest(self):
        g, a, b, c = _build_triangle()
        pq = fpq.pq_gen(g.nnodes)
        rc = short_path(pq, g, a, b)
        assert rc == 0
        assert b.n_val == 1
        assert b.n_dad is a

    def test_two_hop_beats_direct(self):
        g, a, b, c = _build_triangle()
        pq = fpq.pq_gen(g.nnodes)
        rc = short_path(pq, g, a, c)
        assert rc == 0
        # 0 -> 1 -> 2 (cost 3) beats 0 -> 2 (cost 4).
        assert c.n_val == 3
        assert c.n_dad is b
        assert b.n_dad is a

    def test_from_equals_to(self):
        g, a, _, _ = _build_triangle()
        pq = fpq.pq_gen(g.nnodes)
        rc = short_path(pq, g, a, a)
        assert rc == 0
        assert a.n_val == 0
        assert a.n_dad is None

    def test_unreachable_leaves_unseen(self):
        # 0 isolated; 1 -- 2 connected.
        g = create_sgraph(3)
        a, b, c = (create_snode(g) for _ in range(3))
        create_sedge(g, b, c, 1.0)
        pq = fpq.pq_gen(g.nnodes)
        rc = short_path(pq, g, a, c)
        assert rc == 0
        assert c.n_val == UNSEEN

    def test_trace_emissions(self, capsys):
        g, a, _, c = _build_triangle()
        pq = fpq.pq_gen(g.nnodes)
        short_path(pq, g, a, c)
        captured = capsys.readouterr()
        assert (
            "[TRACE ortho-sgraph] shortpath from=0 to=2 "
            "nnodes=3 nedges=3"
        ) in captured.err
        assert (
            "[TRACE ortho-sgraph] shortpath result cost=3 path=0,1,2"
        ) in captured.err


# ---------- NetworkX cross-check ----------


@pytest.fixture
def ten_node_graph():
    """A 10-node weighted undirected graph with a mix of path options."""
    edges = [
        (0, 1, 7),
        (0, 2, 9),
        (0, 5, 14),
        (1, 2, 10),
        (1, 3, 15),
        (2, 3, 11),
        (2, 5, 2),
        (3, 4, 6),
        (4, 5, 9),
        (5, 6, 1),
        (6, 7, 2),
        (7, 8, 3),
        (8, 9, 5),
        (4, 9, 4),
    ]
    g = create_sgraph(10)
    snodes = [create_snode(g) for _ in range(10)]
    for u, v, w in edges:
        create_sedge(g, snodes[u], snodes[v], float(w))
    nxg = nx.Graph()
    for u, v, w in edges:
        nxg.add_edge(u, v, weight=w)
    return g, snodes, nxg


class TestDijkstraVsNetworkX:
    @pytest.mark.parametrize("src,dst", [
        (0, 9), (0, 4), (3, 6), (1, 8), (9, 0),
    ])
    def test_cost_and_path_match_networkx(self, ten_node_graph, src, dst):
        g, snodes, nxg = ten_node_graph
        # Reset all node state between parametrized runs.
        for n in g.nodes[:g.nnodes]:
            n.n_val = 0
            n.n_dad = None
            n.n_edge = None

        pq = fpq.pq_gen(g.nnodes)
        rc = short_path(pq, g, snodes[src], snodes[dst])
        assert rc == 0

        nx_cost = nx.dijkstra_path_length(nxg, src, dst)
        nx_path = nx.dijkstra_path(nxg, src, dst)

        assert snodes[dst].n_val == nx_cost, (
            f"cost mismatch {src}->{dst}: "
            f"ortho={snodes[dst].n_val}, networkx={nx_cost}"
        )

        # Reconstruct our path by walking n_dad.
        path_indices: list[int] = []
        cursor = snodes[dst]
        while cursor is not None:
            path_indices.append(cursor.index)
            cursor = cursor.n_dad
        path_indices.reverse()
        # Multiple equal-cost paths may exist; just verify endpoints
        # and cost, plus that our path's weights sum to nx_cost.
        assert path_indices[0] == src
        assert path_indices[-1] == dst
        recomputed = sum(
            nxg[path_indices[i]][path_indices[i + 1]]["weight"]
            for i in range(len(path_indices) - 1)
        )
        assert recomputed == nx_cost


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
