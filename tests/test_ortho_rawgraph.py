"""Tests for gvpy.engines.layout.ortho.rawgraph (Phase 1 port).

Expected topsort orders are derived by hand-tracing C's DFS in
``lib/ortho/rawgraph.c::top_sort`` on identical inputs.  Adjacency
lists preserve insertion order, so the DFS visit order is fully
determined by the sequence of :func:`insert_edge` calls.
"""

from __future__ import annotations

import pytest

from gvpy.engines.layout.ortho.rawgraph import (
    SCANNED,
    SCANNING,
    UNSCANNED,
    Rawgraph,
    edge_exists,
    free_graph,
    insert_edge,
    make_graph,
    remove_redge,
    top_sort,
)


class TestMakeGraph:
    def test_empty_graph(self):
        g = make_graph(0)
        assert g.nvs == 0
        assert g.vertices == []

    def test_six_nodes_zero_edges(self):
        g = make_graph(6)
        assert g.nvs == 6
        assert len(g.vertices) == 6
        for v in g.vertices:
            assert v.color == UNSCANNED
            assert v.adj_list == []


class TestInsertEdge:
    def test_insert_appends_to_adj_list(self):
        g = make_graph(3)
        insert_edge(g, 0, 1)
        insert_edge(g, 0, 2)
        assert g.vertices[0].adj_list == [1, 2]
        assert g.vertices[1].adj_list == []
        assert g.vertices[2].adj_list == []

    def test_insert_is_idempotent(self):
        g = make_graph(2)
        insert_edge(g, 0, 1)
        insert_edge(g, 0, 1)
        insert_edge(g, 0, 1)
        assert g.vertices[0].adj_list == [1]

    def test_insert_preserves_order(self):
        g = make_graph(4)
        insert_edge(g, 0, 3)
        insert_edge(g, 0, 1)
        insert_edge(g, 0, 2)
        assert g.vertices[0].adj_list == [3, 1, 2]


class TestEdgeExists:
    def test_directed_check(self):
        g = make_graph(2)
        insert_edge(g, 0, 1)
        assert edge_exists(g, 0, 1) is True
        assert edge_exists(g, 1, 0) is False

    def test_missing_vertex(self):
        g = make_graph(3)
        assert edge_exists(g, 0, 1) is False
        assert edge_exists(g, 2, 0) is False


class TestRemoveRedge:
    def test_bidirectional_removal(self):
        g = make_graph(3)
        insert_edge(g, 0, 1)
        insert_edge(g, 1, 0)
        insert_edge(g, 0, 2)
        remove_redge(g, 0, 1)
        assert g.vertices[0].adj_list == [2]
        assert g.vertices[1].adj_list == []

    def test_removes_all_occurrences(self):
        # C's LIST_REMOVE removes every occurrence.  insert_edge dedups,
        # but we can still construct duplicates manually via adj_list.
        g = make_graph(2)
        g.vertices[0].adj_list.extend([1, 1, 1])
        remove_redge(g, 0, 1)
        assert g.vertices[0].adj_list == []

    def test_absent_edge_is_noop(self):
        g = make_graph(3)
        insert_edge(g, 0, 1)
        remove_redge(g, 0, 2)
        assert g.vertices[0].adj_list == [1]


class TestTopSort:
    def test_empty_graph_is_noop(self):
        g = make_graph(0)
        top_sort(g)  # must not raise

    def test_single_vertex_gets_order_zero(self):
        g = make_graph(1)
        top_sort(g)
        assert g.vertices[0].topsort_order == 0
        assert g.vertices[0].color == UNSCANNED  # single-node fast path skips coloring

    def test_two_node_chain(self):
        g = make_graph(2)
        insert_edge(g, 0, 1)
        top_sort(g)
        # DFS(0) → visit 1 → push 1 → push 0; pop 0→0, 1→1.
        assert g.vertices[0].topsort_order == 0
        assert g.vertices[1].topsort_order == 1

    def test_six_node_dag(self):
        # 0->1, 0->2, 1->3, 2->3, 3->4, with 5 isolated.
        # DFS sequence pushes [4, 3, 1, 2, 0, 5]; popping in reverse
        # gives 5, 0, 2, 1, 3, 4 — assigned orders 0..5 respectively.
        g = make_graph(6)
        insert_edge(g, 0, 1)
        insert_edge(g, 0, 2)
        insert_edge(g, 1, 3)
        insert_edge(g, 2, 3)
        insert_edge(g, 3, 4)
        top_sort(g)
        expected = {0: 1, 1: 3, 2: 2, 3: 4, 4: 5, 5: 0}
        for idx, order in expected.items():
            assert g.vertices[idx].topsort_order == order, (
                f"vertex {idx}: expected order {order}, "
                f"got {g.vertices[idx].topsort_order}"
            )

    def test_cycle_does_not_raise(self):
        # C's top_sort does not detect cycles — it just assigns some
        # order.  Verify we match that permissive behavior.
        g = make_graph(3)
        insert_edge(g, 0, 1)
        insert_edge(g, 1, 2)
        insert_edge(g, 2, 0)
        top_sort(g)  # must not raise
        # All three vertices got some order in [0, 2].
        orders = {v.topsort_order for v in g.vertices}
        assert orders == {0, 1, 2}

    def test_all_vertices_end_scanned_after_topsort(self):
        g = make_graph(3)
        insert_edge(g, 0, 1)
        insert_edge(g, 0, 2)
        top_sort(g)
        for v in g.vertices:
            assert v.color == SCANNED


class TestTraceEmission:
    def test_topsort_trace_line(self, capsys, monkeypatch):
        # Trace is gated on GV_TRACE=ortho_rawgraph as of 2026-04-24.
        # Patch the cached frozenset directly since trace.py reads
        # the env once at import time.
        from gvpy.engines.layout.dot import trace as _trace_mod
        monkeypatch.setattr(_trace_mod, "_enabled",
                            frozenset({"ortho_rawgraph"}))
        g = make_graph(3)
        insert_edge(g, 0, 1)
        insert_edge(g, 1, 2)
        top_sort(g)
        captured = capsys.readouterr()
        assert "[TRACE ortho_rawgraph] topsort n=3" in captured.err
        assert "order=0,1,2" in captured.err


class TestFreeGraph:
    def test_free_graph_is_noop(self):
        g = make_graph(3)
        insert_edge(g, 0, 1)
        free_graph(g)  # no-op; must not raise
        # Graph is still usable in Python (we don't actually free).
        assert g.nvs == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
