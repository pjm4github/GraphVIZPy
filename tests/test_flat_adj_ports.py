"""Tests for E+.2-B port-aware adjacent-flat routing + A-gap warnings."""
import warnings

import pytest

from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
from gvpy.engines.layout.dot.flat_edge import (
    UnsupportedPortRoutingWarning,
    _is_compass_only_port,
    _port_parts,
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


# ═══════════════════════════════════════════════════════════════
#  Port string parsing
# ═══════════════════════════════════════════════════════════════

class TestPortParts:

    def test_empty(self):
        assert _port_parts("") == ("", "")

    def test_pure_compass(self):
        assert _port_parts("n") == ("", "n")
        assert _port_parts("SE") == ("", "se")

    def test_record_field_only(self):
        assert _port_parts("field1") == ("field1", "")

    def test_record_field_plus_compass(self):
        assert _port_parts("field1:n") == ("field1", "n")

    def test_is_compass_only(self):
        assert _is_compass_only_port("")
        assert _is_compass_only_port("n")
        assert _is_compass_only_port("se")
        assert not _is_compass_only_port("field1")
        assert not _is_compass_only_port("field1:n")


# ═══════════════════════════════════════════════════════════════
#  Port-aware routing produces distinct splines
# ═══════════════════════════════════════════════════════════════

class TestCompassPortsRouteDistinctly:

    def test_east_west_vs_south_north_differ(self):
        layout = _layout(
            'digraph { {rank=same; a; b} a:e -> b:w; a:s -> b:n; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        assert len(edges) == 2
        # Both should have routes.
        for le in edges:
            assert le.route.points, f"{le} lost its spline"
        # Start points must differ (ports compute different attach points).
        starts = {le.route.points[0] for le in edges}
        assert len(starts) == 2, (
            f"port attach points collapsed: {starts}")


class TestNoPortsStillWorks:

    def test_adjacent_unlabeled_unchanged(self):
        layout = _layout(
            'digraph { {rank=same; a; b} a -> b; a -> b; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        assert len(edges) == 2
        for le in edges:
            assert le.route.points

    def test_adjacent_labeled_still_stacks(self):
        layout = _layout(
            'digraph { {rank=same; a; b} '
            'a -> b [label="L1"]; '
            'a -> b [label="L2"]; }'
        )
        edges = [le for le in _all_edges(layout)
                 if le.tail_name == "a" and le.head_name == "b"]
        ys = sorted(le.label_pos[1] for le in edges if le.label_pos)
        assert len(ys) == 2
        tail_y = layout.lnodes["a"].y
        assert any(y < tail_y for y in ys)
        assert any(y > tail_y for y in ys)


# ═══════════════════════════════════════════════════════════════
#  A-gap warning — fires on record-field / non-compass ports
# ═══════════════════════════════════════════════════════════════

class TestAGapWarning:

    def test_record_field_port_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _layout(
                'digraph { {rank=same; '
                'a [shape=record, label="<f1>x|<f2>y"]; '
                'b [shape=record, label="<g1>p|<g2>q"]; } '
                'a:f1 -> b:g2; a:f2 -> b:g1; }'
            )
            port_warnings = [w for w in caught
                             if issubclass(w.category, UnsupportedPortRoutingWarning)]
        assert port_warnings, "expected UnsupportedPortRoutingWarning"
        msg = str(port_warnings[0].message)
        assert "E+.2-A" in msg
        assert "record-field port" in msg or "non-compass port" in msg

    def test_compass_only_no_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _layout('digraph { {rank=same; a; b} a:e -> b:w }')
            port_warnings = [w for w in caught
                             if issubclass(w.category, UnsupportedPortRoutingWarning)]
        assert not port_warnings, (
            f"unexpected warning for pure compass ports: "
            f"{[str(w.message) for w in port_warnings]}"
        )

    def test_no_ports_no_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _layout('digraph { {rank=same; a; b} a -> b }')
            port_warnings = [w for w in caught
                             if issubclass(w.category, UnsupportedPortRoutingWarning)]
        assert not port_warnings
