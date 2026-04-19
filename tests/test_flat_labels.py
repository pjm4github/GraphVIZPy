"""Tests for E+.1 adjacent flat-edge label stacking."""
import pytest

from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
from gvpy.engines.layout.dot.flat_edge import (
    LBL_SPACE,
    edge_label_key,
    make_simple_flat_labels,
)
from gvpy.grammar.gv_reader import read_dot


def _layout(src):
    g = read_dot(src)
    layout = DotGraphInfo(g)
    layout.layout()
    return layout


def _all_edges(layout):
    return [le for le in (layout.ledges + layout._chain_edges)
            if not le.virtual]


class TestEdgeLabelKey:

    def test_unlabeled_sorts_after_labeled(self):
        layout = _layout('digraph { a -> b [label="hi"]; c -> d }')
        lab = next(le for le in _all_edges(layout) if le.label)
        unlab = next(le for le in _all_edges(layout) if not le.label)
        assert edge_label_key(layout, lab) < edge_label_key(layout, unlab)

    def test_wider_label_sorts_first(self):
        layout = _layout(
            'digraph { rankdir=LR; '
            'a -> b [label="xxxxxxxxxxxxxxxxxx"]; '
            'c -> d [label="y"] }'
        )
        wide = next(le for le in _all_edges(layout)
                    if le.label == "xxxxxxxxxxxxxxxxxx")
        narrow = next(le for le in _all_edges(layout) if le.label == "y")
        assert edge_label_key(layout, wide) < edge_label_key(layout, narrow)


class TestMakeSimpleFlatLabels:

    def test_first_edge_gets_straight_spline(self):
        # Two adjacent flat edges a->b with labels, forced same rank.
        layout = _layout(
            'digraph { {rank=same; a; b} '
            'a -> b [label="L1"]; '
            'a -> b [label="L2"]; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        assert len(edges) == 2
        for le in edges:
            assert le.route.points, f"{le} lost route"
            assert le.label_pos, f"{le} missing label_pos"

    def test_labels_are_vertically_separated(self):
        layout = _layout(
            'digraph { {rank=same; a; b} '
            'a -> b [label="L1"]; '
            'a -> b [label="L2"]; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        y_positions = [le.label_pos[1] for le in edges if le.label_pos]
        assert len(y_positions) == 2
        # Labels should be on opposite sides of the edge line
        # (one above, one below tail.y).
        tail_y = layout.lnodes["a"].y
        above = [y for y in y_positions if y < tail_y]
        below = [y for y in y_positions if y > tail_y]
        assert len(above) == 1 and len(below) == 1, (
            f"expected one label above and one below tail.y={tail_y}, "
            f"got positions {y_positions}")

    def test_label_vertical_gap_at_least_lbl_space(self):
        layout = _layout(
            'digraph { {rank=same; a; b} '
            'a -> b [label="Hello"]; '
            'a -> b [label="World"]; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        ys = sorted(le.label_pos[1] for le in edges if le.label_pos)
        assert ys[1] - ys[0] >= LBL_SPACE


class TestUnlabeledFallthrough:

    def test_adjacent_no_labels_still_routes(self):
        # Regression: no-label adjacent case must still go through
        # make_simple_flat, not make_simple_flat_labels.
        layout = _layout(
            'digraph { {rank=same; a; b} a -> b; a -> b; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        assert len(edges) == 2
        for le in edges:
            assert le.route.points

    def test_single_labeled_still_routes(self):
        # Single labeled adjacent edge goes to make_flat_labeled_edge,
        # not make_simple_flat_labels (cnt == 1).
        layout = _layout(
            'digraph { {rank=same; a; b} a -> b [label="x"]; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        assert len(edges) == 1
        assert edges[0].route.points
