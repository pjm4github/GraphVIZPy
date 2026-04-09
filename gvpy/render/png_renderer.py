"""
PNG renderer for dot layout results.

Converts the JSON layout dict produced by DotLayout.layout() into a PNG
image using Pillow (PIL).  Mirrors the SVG renderer's visual output for
quick comparison with Graphviz ``dot -Tpng`` output.
"""
from __future__ import annotations

import math
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


# ── Defaults ────────────────────────────────────────

_SCALE = 1.0          # points → pixels (1:1 at 72 DPI)
_PAD = 4.0            # padding around graph bounding box
_BG = (255, 255, 255, 255)
_DEF_FONT_SIZE = 14.0
_ARROW_SIZE = 8.0

# ── Color helpers ───────────────────────────────────

_NAMED_COLORS: dict[str, tuple[int, ...]] = {
    "black": (0, 0, 0), "white": (255, 255, 255),
    "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "gray": (128, 128, 128), "grey": (128, 128, 128),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169),
    "darkgreen": (0, 100, 0), "darkblue": (0, 0, 139),
    "darkred": (139, 0, 0), "orange": (255, 165, 0),
    "purple": (128, 0, 128), "brown": (165, 42, 42),
    "pink": (255, 192, 203), "indigo": (75, 0, 130),
    "gold": (255, 215, 0), "navy": (0, 0, 128),
    "crimson": (220, 20, 60), "coral": (255, 127, 80),
    "transparent": (0, 0, 0, 0), "none": (0, 0, 0, 0),
}


def _parse_color(name: str) -> tuple[int, ...]:
    """Convert a color name or #hex to an RGBA tuple."""
    if not name:
        return (0, 0, 0, 255)
    name_lower = name.strip().lower()
    if name_lower in _NAMED_COLORS:
        c = _NAMED_COLORS[name_lower]
        return c if len(c) == 4 else (*c, 255)
    if name.startswith("#"):
        h = name.lstrip("#")
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16),
                    int(h[4:6], 16), int(h[6:8], 16))
    # Fallback
    return (0, 0, 0, 255)


def _opaque(c: tuple[int, ...]) -> bool:
    """Return True if the color is not fully transparent."""
    return len(c) < 4 or c[3] > 0


def _try_font(size: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Attempt to load a TrueType font; fall back to default."""
    sz = max(6, int(size))
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
                 "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, sz)
        except OSError:
            continue
    return ImageFont.load_default()


# ── Coordinate transform ───────────────────────────

class _Ctx:
    """Rendering context with coordinate transform."""

    def __init__(self, bb: Sequence[float], scale: float, dpi: float):
        self.scale = scale * (dpi / 72.0)
        self.ox = -bb[0] + _PAD
        self.oy = -bb[1] + _PAD
        w = int(math.ceil((bb[2] - bb[0] + 2 * _PAD) * self.scale))
        h = int(math.ceil((bb[3] - bb[1] + 2 * _PAD) * self.scale))
        self.img = Image.new("RGBA", (w, h), _BG)
        self.draw = ImageDraw.Draw(self.img)

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return ((x + self.ox) * self.scale,
                (y + self.oy) * self.scale)


# ── Cluster ─────────────────────────────────────────

def _draw_cluster(ctx: _Ctx, cl: dict):
    bb = cl.get("bb", [0, 0, 0, 0])
    style = cl.get("style", "")
    if "invis" in style:
        return

    fill_c = _parse_color(cl.get("fillcolor") or cl.get("bgcolor") or "none")
    stroke_c = _parse_color(cl.get("pencolor") or cl.get("color") or "black")
    try:
        pw = max(1, int(float(cl.get("penwidth", "1"))))
    except ValueError:
        pw = 1

    x0, y0 = ctx.pt(bb[0], bb[1])
    x1, y1 = ctx.pt(bb[2], bb[3])
    rect = [x0, y0, x1, y1]

    if _opaque(fill_c):
        ctx.draw.rectangle(rect, fill=fill_c)
    if _opaque(stroke_c):
        ctx.draw.rectangle(rect, outline=stroke_c, width=pw)

    label = cl.get("label", "")
    if label:
        try:
            fsz = float(cl.get("fontsize", _DEF_FONT_SIZE - 2))
        except ValueError:
            fsz = _DEF_FONT_SIZE - 2
        font = _try_font(fsz * ctx.scale)
        fc = _parse_color(cl.get("fontcolor", "black"))
        tx = (x0 + x1) / 2
        ty = y0 + 4 * ctx.scale
        ctx.draw.text((tx, ty), label, fill=fc, font=font, anchor="mt")


# ── Node ────────────────────────────────────────────

def _draw_node(ctx: _Ctx, node: dict):
    x, y = node["x"], node["y"]
    w, h = node["width"], node["height"]
    style = node.get("style", "")
    shape = node.get("shape", "ellipse")

    if "invis" in style:
        return

    fill_c = _parse_color(node.get("fillcolor") or node.get("color") or "white")
    stroke_c = _parse_color(node.get("color") or "black")
    if node.get("fillcolor"):
        stroke_c = _parse_color(node.get("color") or "black")
    try:
        pw = max(1, int(float(node.get("penwidth", "1"))))
    except ValueError:
        pw = 1

    cx, cy = ctx.pt(x, y)
    hw = w / 2 * ctx.scale
    hh = h / 2 * ctx.scale
    rect = [cx - hw, cy - hh, cx + hw, cy + hh]

    if shape in ("box", "rect", "rectangle", "record", "Mrecord",
                 "square", "component", "tab", "folder", "note"):
        ctx.draw.rectangle(rect, fill=fill_c, outline=stroke_c, width=pw)
    elif shape in ("diamond", "Mdiamond"):
        pts = [(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)]
        ctx.draw.polygon(pts, fill=fill_c, outline=stroke_c, width=pw)
    elif shape in ("point", "circle", "doublecircle"):
        ctx.draw.ellipse(rect, fill=fill_c, outline=stroke_c, width=pw)
    else:
        # Default: ellipse
        ctx.draw.ellipse(rect, fill=fill_c, outline=stroke_c, width=pw)

    # Label
    label = node.get("label", node.get("name", ""))
    # Strip record port syntax for display
    if shape in ("record", "Mrecord"):
        # Show simplified — full record parsing is complex
        label = label.replace("{", "").replace("}", "").replace("|", " | ")
    if label and "invis" not in style:
        try:
            fsz = float(node.get("fontsize", _DEF_FONT_SIZE))
        except ValueError:
            fsz = _DEF_FONT_SIZE
        font = _try_font(fsz * ctx.scale)
        fc = _parse_color(node.get("fontcolor", "black"))
        ctx.draw.text((cx, cy), label, fill=fc, font=font, anchor="mm")


# ── Edge ────────────────────────────────────────────

def _draw_edge(ctx: _Ctx, edge: dict, directed: bool):
    pts = edge.get("points", [])
    if not pts:
        return
    style = edge.get("style", "")
    if "invis" in style:
        return

    stroke_c = _parse_color(edge.get("color") or "black")
    try:
        pw = max(1, int(float(edge.get("penwidth", "1"))))
    except ValueError:
        pw = 1

    # Draw line segments
    screen_pts = [ctx.pt(p[0], p[1]) for p in pts]

    spline_type = edge.get("spline_type", "polyline")
    if spline_type == "bezier" and len(screen_pts) >= 4:
        # Approximate cubic Bezier segments as polylines
        approx = [screen_pts[0]]
        i = 1
        while i + 2 < len(screen_pts):
            p0 = approx[-1]
            p1 = screen_pts[i]
            p2 = screen_pts[i + 1]
            p3 = screen_pts[i + 2]
            for t_step in range(1, 11):
                t = t_step / 10.0
                u = 1 - t
                bx = (u**3 * p0[0] + 3*u**2*t * p1[0]
                      + 3*u*t**2 * p2[0] + t**3 * p3[0])
                by = (u**3 * p0[1] + 3*u**2*t * p1[1]
                      + 3*u*t**2 * p2[1] + t**3 * p3[1])
                approx.append((bx, by))
            i += 3
        # Any remaining points
        while i < len(screen_pts):
            approx.append(screen_pts[i])
            i += 1
        screen_pts = approx

    if len(screen_pts) >= 2:
        ctx.draw.line(screen_pts, fill=stroke_c, width=pw)

    # Arrowhead
    dir_attr = edge.get("dir", "forward" if directed else "none")
    if dir_attr in ("forward", "both") and len(screen_pts) >= 2:
        _draw_arrow(ctx, screen_pts[-2], screen_pts[-1], stroke_c, pw)
    if dir_attr in ("back", "both") and len(screen_pts) >= 2:
        _draw_arrow(ctx, screen_pts[1], screen_pts[0], stroke_c, pw)

    # Edge label
    label = edge.get("label", "")
    if label:
        mid = screen_pts[len(screen_pts) // 2]
        try:
            fsz = float(edge.get("fontsize", "10"))
        except ValueError:
            fsz = 10
        font = _try_font(fsz * ctx.scale)
        fc = _parse_color(edge.get("fontcolor") or "black")
        ctx.draw.text(mid, label, fill=fc, font=font, anchor="mm")


def _draw_arrow(ctx: _Ctx, p_from: tuple, p_to: tuple,
                color: tuple, pw: int):
    """Draw a simple arrowhead at p_to pointing away from p_from."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    dx /= length
    dy /= length
    sz = _ARROW_SIZE * ctx.scale
    bx = p_to[0] - dx * sz
    by = p_to[1] - dy * sz
    nx, ny = -dy, dx
    pts = [
        p_to,
        (bx + nx * sz * 0.4, by + ny * sz * 0.4),
        (bx - nx * sz * 0.4, by - ny * sz * 0.4),
    ]
    ctx.draw.polygon(pts, fill=color)


# ── Public API ──────────────────────────────────────

def render_png(layout: dict, dpi: float = 72.0) -> bytes:
    """Convert a layout result dict to PNG bytes.

    Parameters
    ----------
    layout : dict
        Layout result from ``DotLayout.layout()`` (same dict the SVG
        renderer consumes).
    dpi : float
        Output resolution (default 72 matches Graphviz ``-Gdpi=72``).

    Returns
    -------
    bytes
        PNG image data.
    """
    graph = layout.get("graph", {})
    bb = graph.get("bb", [0, 0, 100, 100])

    ctx = _Ctx(bb, _SCALE, dpi)

    # Draw order: clusters (background) → edges → nodes (foreground)
    for cl in layout.get("clusters", []):
        _draw_cluster(ctx, cl)
    for edge in layout.get("edges", []):
        _draw_edge(ctx, edge, graph.get("directed", True))
    for node in layout.get("nodes", []):
        _draw_node(ctx, node)

    import io
    buf = io.BytesIO()
    ctx.img.save(buf, format="PNG")
    return buf.getvalue()
