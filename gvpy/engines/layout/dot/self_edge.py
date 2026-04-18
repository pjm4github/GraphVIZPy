"""Self-loop edge routing.

C analogue: ``lib/common/splines.c`` — ``makeSelfEdge`` and its
helpers ``selfRight``, ``selfLeft``, ``selfTop``, ``selfBottom``,
``selfRightSpace``.

Phase F of the splines port.

All functions produce 7-point cubic Bezier curves (two cubic
segments sharing a middle control point) that are then clipped
to the node boundary by :func:`clip.clip_and_install`.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from gvpy.engines.layout.dot.clip import clip_and_install
from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint
from gvpy.engines.layout.dot.path import BOTTOM, TOP, LEFT, RIGHT
from gvpy.engines.layout.dot.regular_edge import _node_shape, _install_points

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import LayoutEdge, LayoutNode

SELF_EDGE_SIZE = 18


def self_right_space(le) -> float:
    """Return extra horizontal space needed for a right-side self-loop.

    C analogue: ``splines.c:selfRightSpace`` lines 1139-1157.
    """
    tside = _port_side(le.tailport)
    hside = _port_side(le.headport)
    if ((not le.tailport and not le.headport) or
        (not (tside & LEFT) and not (hside & LEFT) and
         (tside != hside or not (tside & (TOP | BOTTOM))))):
        sw = SELF_EDGE_SIZE
        if le.label:
            sw += 10  # approximate label width
        return sw
    return 0.0


def make_self_edge(layout, le, tail) -> None:
    """Route a self-loop edge and install on the LayoutEdge.

    C analogue: ``splines.c:makeSelfEdge`` lines 1164-1202.
    """
    tside = _port_side(le.tailport)
    hside = _port_side(le.headport)

    if ((not le.tailport and not le.headport) or
        (not (tside & LEFT) and not (hside & LEFT) and
         (tside != hside or not (tside & (TOP | BOTTOM))))):
        _self_right(layout, [le], tail)
    elif (tside & LEFT) or (hside & LEFT):
        if (tside & RIGHT) or (hside & RIGHT):
            _self_top(layout, [le], tail)
        else:
            _self_left(layout, [le], tail)
    elif tside & TOP:
        _self_top(layout, [le], tail)
    elif tside & BOTTOM:
        _self_bottom(layout, [le], tail)
    else:
        _self_right(layout, [le], tail)


def _self_right(layout, edges: list, n) -> None:
    """Route self-loop extending to the right of the node.

    C analogue: ``splines.c:selfRight`` lines 986-1055.
    Y-down adjustment: vertical offsets are negated so the loop
    extends upward (visually above the center line).
    """
    cnt = len(edges)
    hw = n.width / 2
    hh = n.height / 2
    sizey = n.height
    stepx = max(hw / cnt, 2.0)

    e0 = edges[0]
    np_x, np_y = n.x, n.y
    tp_x, tp_y = np_x + hw, np_y
    hp_x, hp_y = np_x + hw, np_y

    sgn = 1 if tp_y >= hp_y else -1
    dx = hw
    dy = 0.0
    stepy = max(sizey / 2.0 / cnt, 2.0)
    tx = min(dx, 3 * (np_x + dx - tp_x))
    hx = min(dx, 3 * (np_x + dx - hp_x))

    for i, le in enumerate(edges):
        dx += stepx
        tx += stepx
        hx += stepx
        dy += sgn * stepy
        pts = [
            Ppoint(tp_x, tp_y),
            Ppoint(tp_x + tx / 3, tp_y - dy),
            Ppoint(np_x + dx, tp_y - dy),
            Ppoint(np_x + dx, (tp_y + hp_y) / 2),
            Ppoint(np_x + dx, hp_y + dy),
            Ppoint(hp_x + hx / 3, hp_y + dy),
            Ppoint(hp_x, hp_y),
        ]
        clipped = clip_and_install(
            pts,
            tail_x=np_x, tail_y=np_y,
            tail_hw=hw, tail_hh=hh, tail_shape=_node_shape(n),
            head_x=np_x, head_y=np_y,
            head_hw=hw, head_hh=hh, head_shape=_node_shape(n),
        )
        _install_points(le, clipped)


def _self_left(layout, edges: list, n) -> None:
    """Route self-loop extending to the left of the node.

    C analogue: ``splines.c:selfLeft`` lines 1057-1130.
    """
    cnt = len(edges)
    hw = n.width / 2
    hh = n.height / 2
    sizey = n.height
    stepx = max(hw / cnt, 2.0)

    np_x, np_y = n.x, n.y
    tp_x, tp_y = np_x - hw, np_y
    hp_x, hp_y = np_x - hw, np_y

    sgn = 1 if tp_y >= hp_y else -1
    dx = hw
    dy = 0.0
    stepy = max(sizey / 2.0 / cnt, 2.0)
    tx = min(dx, 3 * (tp_x + dx - np_x))
    hx = min(dx, 3 * (hp_x + dx - np_x))

    for i, le in enumerate(edges):
        dx += stepx
        tx += stepx
        hx += stepx
        dy += sgn * stepy
        pts = [
            Ppoint(tp_x, tp_y),
            Ppoint(tp_x - tx / 3, tp_y - dy),
            Ppoint(np_x - dx, tp_y - dy),
            Ppoint(np_x - dx, (tp_y + hp_y) / 2),
            Ppoint(np_x - dx, hp_y + dy),
            Ppoint(hp_x - hx / 3, hp_y + dy),
            Ppoint(hp_x, hp_y),
        ]
        clipped = clip_and_install(
            pts,
            tail_x=np_x, tail_y=np_y,
            tail_hw=hw, tail_hh=hh, tail_shape=_node_shape(n),
            head_x=np_x, head_y=np_y,
            head_hw=hw, head_hh=hh, head_shape=_node_shape(n),
        )
        _install_points(le, clipped)


def _self_top(layout, edges: list, n) -> None:
    """Route self-loop extending above the node (smaller y in y-down).

    C analogue: ``splines.c:selfTop`` lines 879-984.
    """
    cnt = len(edges)
    hw = n.width / 2
    hh = n.height / 2
    sizex = n.width
    stepy = max(sizex / 2.0 / cnt, 2.0)

    np_x, np_y = n.x, n.y
    tp_x, tp_y = np_x, np_y - hh
    hp_x, hp_y = np_x, np_y - hh

    sgn = 1 if tp_x >= hp_x else -1
    dy = hh
    dx = 0.0
    stepx = max(sizex / 2.0 / cnt, 2.0)
    ty = min(dy, 3 * (np_y - dy - tp_y) if (np_y - dy) > tp_y else dy)
    hy = min(dy, 3 * (np_y - dy - hp_y) if (np_y - dy) > hp_y else dy)

    for i, le in enumerate(edges):
        dy += stepy
        ty += stepy
        hy += stepy
        dx += sgn * stepx
        pts = [
            Ppoint(tp_x, tp_y),
            Ppoint(tp_x + dx, tp_y - ty / 3),
            Ppoint(tp_x + dx, np_y - dy),
            Ppoint((tp_x + hp_x) / 2, np_y - dy),
            Ppoint(hp_x - dx, np_y - dy),
            Ppoint(hp_x - dx, hp_y - hy / 3),
            Ppoint(hp_x, hp_y),
        ]
        clipped = clip_and_install(
            pts,
            tail_x=np_x, tail_y=np_y,
            tail_hw=hw, tail_hh=hh, tail_shape=_node_shape(n),
            head_x=np_x, head_y=np_y,
            head_hw=hw, head_hh=hh, head_shape=_node_shape(n),
        )
        _install_points(le, clipped)


def _self_bottom(layout, edges: list, n) -> None:
    """Route self-loop extending below the node (larger y in y-down).

    C analogue: ``splines.c:selfBottom`` lines 809-877.
    """
    cnt = len(edges)
    hw = n.width / 2
    hh = n.height / 2
    sizex = n.width
    stepy = max(sizex / 2.0 / cnt, 2.0)

    np_x, np_y = n.x, n.y
    tp_x, tp_y = np_x, np_y + hh
    hp_x, hp_y = np_x, np_y + hh

    sgn = 1 if tp_x >= hp_x else -1
    dy = hh
    dx = 0.0
    stepx = max(sizex / 2.0 / cnt, 2.0)
    ty = min(dy, 3 * abs(tp_y - (np_y + dy)))
    hy = min(dy, 3 * abs(hp_y - (np_y + dy)))

    for i, le in enumerate(edges):
        dy += stepy
        ty += stepy
        hy += stepy
        dx += sgn * stepx
        pts = [
            Ppoint(tp_x, tp_y),
            Ppoint(tp_x + dx, tp_y + ty / 3),
            Ppoint(tp_x + dx, np_y + dy),
            Ppoint((tp_x + hp_x) / 2, np_y + dy),
            Ppoint(hp_x - dx, np_y + dy),
            Ppoint(hp_x - dx, hp_y + hy / 3),
            Ppoint(hp_x, hp_y),
        ]
        clipped = clip_and_install(
            pts,
            tail_x=np_x, tail_y=np_y,
            tail_hw=hw, tail_hh=hh, tail_shape=_node_shape(n),
            head_x=np_x, head_y=np_y,
            head_hw=hw, head_hh=hh, head_shape=_node_shape(n),
        )
        _install_points(le, clipped)


def _port_side(port_str: str) -> int:
    """Map a compass port string to a side bitmask for self-edge dispatch."""
    if not port_str:
        return 0
    c = port_str.split(":")[-1] if ":" in port_str else port_str
    c = c.strip().lower()
    _MAP = {
        "n": TOP, "ne": TOP | RIGHT, "e": RIGHT,
        "se": BOTTOM | RIGHT, "s": BOTTOM, "sw": BOTTOM | LEFT,
        "w": LEFT, "nw": TOP | LEFT,
    }
    return _MAP.get(c, 0)
