"""Graphviz plain-format renderer.

Emits the canonical text format documented at
https://graphviz.org/docs/outputs/plain/, matching the output
of ``dot -Tplain`` line-for-line:

::

    graph SCALE WIDTH HEIGHT
    node NAME X Y W H LABEL STYLE SHAPE COLOR FILLCOLOR
    edge TAIL HEAD N X1 Y1 X2 Y2 ... XN YN [label XL YL] STYLE COLOR
    stop

Coordinate convention: Graphviz's plain format uses **math-y**
(y up, origin at the bottom-left of the bounding box) with all
units in **inches**.  GraphvizPy's layout dicts use SVG-y
(y down) in **pt**, so this renderer flips y and divides by 72
during the conversion.

Strings (NAMEs, LABELs) get double-quoted iff they contain
whitespace or other delimiter-sensitive characters.  Empty
labels are emitted as ``""``.

Earlier versions of GraphvizPy emitted JSON for the ``-Tplain``
flag (a Python-specific structural dump).  That was useful
for programmatic consumers but broke standard pipelines that
expect the canonical line format.  As of 2026-05-09, the JSON
output is reachable via ``-Tjson`` (already supported) or
``-Tjson0`` (structural-only), and ``-Tplain`` produces the
text format below.
"""
from __future__ import annotations

import re
from typing import Any


# ─────────────────────────────────────────────────────────────────
# Defaults — match what C ``dot -Tplain`` emits for unset attrs
# ─────────────────────────────────────────────────────────────────

# Graphviz plain format uses these as sentinels when the node /
# edge didn't have the attribute set.  ``lightgrey`` for fillcolor
# is documented behaviour: "If the value is 'lightgrey', then the
# node's fillcolor was not set".
_DEF_NODE_STYLE: str = "solid"
_DEF_NODE_SHAPE: str = "ellipse"
_DEF_NODE_COLOR: str = "black"
_DEF_NODE_FILLCOLOR: str = "lightgrey"
_DEF_EDGE_STYLE: str = "solid"
_DEF_EDGE_COLOR: str = "black"


# Whitespace + control / quote characters that force token
# quoting.  Matches the conservative behaviour of C's
# ``write_plain`` (lib/common/output.c).
_QUOTE_CHARS = re.compile(r"[\s\"\\]")


def _q(s: str | None) -> str:
    """Quote a token if it contains whitespace / quote / backslash.

    Empty strings render as the bare two-character literal
    ``""``.  Non-empty unquoted simple identifiers stay bare.
    Mirrors C ``aagstrcanon`` / Graphviz's plain emitter.
    """
    if s is None or s == "":
        return '""'
    if _QUOTE_CHARS.search(s):
        # Escape embedded quotes / backslashes.
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _fmt(value: float) -> str:
    """Format a numeric value the way C's plain emitter does:
    fixed-point with up to 5 significant digits, trailing zeros
    trimmed.  C uses ``%.5g``.
    """
    return f"{value:.5g}"


# ─────────────────────────────────────────────────────────────────
# render_plain — public entry
# ─────────────────────────────────────────────────────────────────


def render_plain(result: dict[str, Any], scale: float = 1.0) -> str:
    """Render a layout result dict as Graphviz plain-format text.

    Parameters
    ----------
    result : dict
        The output of ``LayoutEngine.layout()`` — must have at
        least ``"nodes"``, ``"edges"``, and ``"graph"`` (with a
        ``"bb"`` four-tuple) keys.
    scale : float
        First field on the ``graph`` line.  C dot always emits
        ``1`` here regardless of dpi or zoom; we honour any
        caller override but default to ``1.0`` to match.

    Returns
    -------
    str
        The full plain-format output, terminated by ``"stop\\n"``.
    """
    out: list[str] = []

    graph = result.get("graph", {}) or {}
    bb = graph.get("bb", [0.0, 0.0, 0.0, 0.0])
    bb_x0 = float(bb[0]) if len(bb) > 0 else 0.0
    bb_y0 = float(bb[1]) if len(bb) > 1 else 0.0
    bb_x1 = float(bb[2]) if len(bb) > 2 else 0.0
    bb_y1 = float(bb[3]) if len(bb) > 3 else 0.0
    width_pt = bb_x1 - bb_x0
    height_pt = bb_y1 - bb_y0
    width_in = width_pt / 72.0
    height_in = height_pt / 72.0

    # Coord conversion: pt SVG-y → inch math-y.
    # ``bb_y1`` is the SVG-bottom (largest y in pt-space); the
    # plain format's origin is the bottom-left of the bbox in
    # math-y, so we flip via ``(bb_y1 - svg_y) / 72``.  X just
    # offsets by bb_x0.
    def to_math(svg_x: float, svg_y: float) -> tuple[float, float]:
        return (
            (svg_x - bb_x0) / 72.0,
            (bb_y1 - svg_y) / 72.0,
        )

    # 1. graph line.
    out.append(
        f"graph {_fmt(scale)} {_fmt(width_in)} {_fmt(height_in)}"
    )

    # 2. node lines.
    for n in result.get("nodes", []) or []:
        name = str(n.get("name", ""))
        sx = float(n.get("x", 0.0))
        sy = float(n.get("y", 0.0))
        x_in, y_in = to_math(sx, sy)
        w_in = float(n.get("width", 54.0)) / 72.0
        h_in = float(n.get("height", 36.0)) / 72.0
        label = n.get("label", name) or name
        style = n.get("style", "") or _DEF_NODE_STYLE
        # Graphviz plain emitter normalises ``style="filled"`` /
        # multi-token styles by emitting the *first* primary
        # style token; ``solid`` is the default sentinel.  We
        # take a conservative approach: pass through unchanged
        # if non-empty, else ``solid``.  (Tools that consume
        # this format treat the field as opaque.)
        shape = n.get("shape", "") or _DEF_NODE_SHAPE
        color = n.get("color", "") or _DEF_NODE_COLOR
        fillcolor = n.get("fillcolor", "") or _DEF_NODE_FILLCOLOR
        out.append(
            f"node {_q(name)} {_fmt(x_in)} {_fmt(y_in)} "
            f"{_fmt(w_in)} {_fmt(h_in)} "
            f"{_q(label)} {style} {shape} {color} {fillcolor}"
        )

    # 3. edge lines.
    for e in result.get("edges", []) or []:
        tail = str(e.get("tail", ""))
        head = str(e.get("head", ""))
        # ``points`` is a list of [x, y] pairs in pt-space.
        # Some layout engines emit ``[x, y]`` lists; others emit
        # ``(x, y)`` tuples — handle both via ``[0]/[1]``.
        pts = e.get("points", []) or []
        n_pts = len(pts)
        pt_strs: list[str] = []
        for p in pts:
            try:
                px = float(p[0])
                py = float(p[1])
            except (KeyError, TypeError, IndexError):
                continue
            pmx, pmy = to_math(px, py)
            pt_strs.append(f"{_fmt(pmx)} {_fmt(pmy)}")
        # Optional label (with position) goes between the
        # control points and the style.  Plain format:
        # ``... xn yn label "<text>" lx ly style color``.
        # We emit it only when both label text and a position
        # are present on the edge dict.
        label_part = ""
        elabel = e.get("label", "") or ""
        elabel_x = e.get("_label_pos_x", e.get("lp_x", ""))
        elabel_y = e.get("_label_pos_y", e.get("lp_y", ""))
        if elabel and elabel_x != "" and elabel_y != "":
            try:
                lx = float(elabel_x)
                ly = float(elabel_y)
                lmx, lmy = to_math(lx, ly)
                label_part = f" {_q(elabel)} {_fmt(lmx)} {_fmt(lmy)}"
            except (TypeError, ValueError):
                pass
        style = e.get("style", "") or _DEF_EDGE_STYLE
        color = e.get("color", "") or _DEF_EDGE_COLOR
        out.append(
            f"edge {_q(tail)} {_q(head)} {n_pts} "
            + " ".join(pt_strs)
            + label_part
            + f" {style} {color}"
        )

    # 4. terminator.
    out.append("stop")

    return "\n".join(out) + "\n"
