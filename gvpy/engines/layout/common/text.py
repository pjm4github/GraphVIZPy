"""Text sizing and label placement.

See: /lib/common/labels.c  (C counterpart: make_label, label size)
See: /lib/common/shapes.c  (record field width computation)

Holds three concerns:

- **Font width tables** (Times-Roman AFM metrics, tkinter fallback) —
  used whenever a layout engine needs to size a text string without
  calling into a render-time font engine.
- **Label bounding-box estimate** — ``estimate_label_size``.
- **Collision-aware external-label placement** — search over six
  candidate anchors around a node/edge and pick the lowest-overlap
  position (used for ``xlabel``, ``headlabel`` / ``taillabel``, and
  graph-level ``label``).

Functions are free-standing (take ``layout`` rather than ``self``)
so any engine — or external tooling — can call them.
"""
from __future__ import annotations


# Times-Roman character widths in 1/1000 of font size.
# Source: Adobe AFM file for Times-Roman (standard PostScript metrics).
# These are the same values used by PostScript interpreters worldwide.
TIMES_ROMAN_WIDTHS: dict[str, int] = {
    ' ': 250, '!': 333, '"': 408, '#': 500, '$': 500,
    '%': 833, '&': 778, "'": 333, '(': 333, ')': 333,
    '*': 500, '+': 564, ',': 250, '-': 333, '.': 250,
    '/': 278, '0': 500, '1': 500, '2': 500, '3': 500,
    '4': 500, '5': 500, '6': 500, '7': 500, '8': 500,
    '9': 500, ':': 278, ';': 278, '<': 564, '=': 564,
    '>': 564, '?': 444, '@': 921, 'A': 722, 'B': 667,
    'C': 667, 'D': 722, 'E': 611, 'F': 556, 'G': 722,
    'H': 722, 'I': 333, 'J': 389, 'K': 722, 'L': 611,
    'M': 889, 'N': 722, 'O': 722, 'P': 556, 'Q': 722,
    'R': 667, 'S': 556, 'T': 611, 'U': 722, 'V': 722,
    'W': 944, 'X': 722, 'Y': 722, 'Z': 611, '[': 333,
    '\\': 278, ']': 333, '^': 469, '_': 500, '`': 333,
    'a': 444, 'b': 500, 'c': 444, 'd': 500, 'e': 444,
    'f': 333, 'g': 500, 'h': 500, 'i': 278, 'j': 278,
    'k': 500, 'l': 278, 'm': 778, 'n': 500, 'o': 500,
    'p': 500, 'q': 500, 'r': 333, 's': 389, 't': 278,
    'u': 500, 'v': 500, 'w': 722, 'x': 500, 'y': 500,
    'z': 444, '{': 480, '|': 200, '}': 480, '~': 541,
}

TIMES_ROMAN_DEFAULT_WIDTH = 500


def text_width_times_roman(text: str, fontsize: float) -> float:
    """Compute text width in points using Times-Roman metrics."""
    if not text:
        return 0.0
    total = sum(TIMES_ROMAN_WIDTHS.get(ch, TIMES_ROMAN_DEFAULT_WIDTH)
                for ch in text)
    return total * fontsize / 1000.0


_tk_root = None
_tk_font_cache: dict[tuple[str, int], tuple] = {}


def text_width_system(text: str, fontsize: float,
                      family: str = "Times New Roman") -> float | None:
    """Compute text width using the system font engine (tkinter).

    Uses the same font engine as Windows Graphviz (GDI+).  Returns
    width in points, or ``None`` if tkinter is unavailable.  Caches
    the Tk root and Font for performance.
    """
    global _tk_root
    try:
        import tkinter as tk
        from tkinter.font import Font
    except ImportError:
        return None

    key = (family, int(fontsize))
    if key not in _tk_font_cache:
        try:
            if _tk_root is None:
                _tk_root = tk.Tk()
                _tk_root.withdraw()
            dpi = _tk_root.winfo_fpixels('1i')
            f = Font(family=family, size=int(fontsize))
            _tk_font_cache[key] = (f, dpi)
        except Exception:
            return None

    f, dpi = _tk_font_cache[key]
    try:
        w_px = f.measure(text)
        return w_px * 72.0 / dpi
    except Exception:
        return None


def avg_char_width_times_roman(fontsize: float) -> float:
    """Average character width for Times-Roman at the given font size."""
    widths = list(TIMES_ROMAN_WIDTHS.values())
    avg = sum(widths) / len(widths) if widths else 500
    return avg * fontsize / 1000.0


def estimate_label_size(text: str, font_size: float = 14.0) -> tuple[float, float]:
    """Estimate label bounding box in points (width, height)."""
    lines = text.replace("\\n", "\n").split("\n")
    max_chars = max(len(line) for line in lines) if lines else len(text)
    return (max(max_chars * font_size * 0.6, 20.0),
            len(lines) * font_size * 1.2)


def overlap_area(ax: float, ay: float, aw: float, ah: float,
                 bx: float, by: float, bw: float, bh: float) -> float:
    """Overlap area between two center-based rectangles."""
    dx = min(ax + aw / 2, bx + bw / 2) - max(ax - aw / 2, bx - bw / 2)
    dy = min(ay + ah / 2, by + bh / 2) - max(ay - ah / 2, by - bh / 2)
    return dx * dy if dx > 0 and dy > 0 else 0.0


def compute_label_positions(layout) -> None:
    """Compute positions for xlabel, headlabel, taillabel, and graph label.

    Searches six candidate anchors (N, S, NE, SE, E, W) around each
    reference object and picks the one with the least overlap against
    the node obstacles + already-placed labels.  Writes positions back
    into the underlying Graph attributes (``_xlabel_pos_x`` /
    ``_headlabel_pos_x`` / ``_label_pos_x`` etc.).
    """
    obstacles = [(ln.x, ln.y, ln.width, ln.height)
                 for ln in layout.lnodes.values()]
    placed: list[tuple[float, float, float, float]] = []

    def _find_best(ax, ay, ow, oh, lw, lh, pad=4.0):
        half_ow, half_oh = ow / 2, oh / 2
        candidates = [
            (ax + half_ow + pad + lw / 2, ay),
            (ax + half_ow + pad + lw / 2, ay + half_oh + pad + lh / 2),
            (ax + half_ow + pad + lw / 2, ay - half_oh - pad - lh / 2),
            (ax, ay + half_oh + pad + lh / 2),
            (ax, ay - half_oh - pad - lh / 2),
            (ax - half_ow - pad - lw / 2, ay),
        ]
        best_pos, best_ov = candidates[0], float("inf")
        for cx, cy in candidates:
            total = sum(overlap_area(cx, cy, lw, lh, *o) for o in obstacles)
            total += sum(overlap_area(cx, cy, lw, lh, *p) for p in placed)
            if total == 0:
                return (cx, cy)
            if total < best_ov:
                best_ov, best_pos = total, (cx, cy)
        return best_pos

    # Node xlabels
    for name, ln in layout.lnodes.items():
        if not ln.node:
            continue
        xlabel = ln.node.attributes.get("xlabel", "")
        if not xlabel:
            continue
        try:
            fs = float(ln.node.attributes.get("fontsize", "14"))
        except ValueError:
            fs = 14.0
        lw, lh = estimate_label_size(xlabel, fs)
        bx, by = _find_best(ln.x, ln.y, ln.width, ln.height, lw, lh)
        ln.node.attributes["_xlabel_pos_x"] = str(round(bx, 2))
        ln.node.attributes["_xlabel_pos_y"] = str(round(by, 2))
        placed.append((bx, by, lw, lh))

    # Edge head / tail labels
    for key, edge in layout.graph.edges.items():
        t_ln = layout.lnodes.get(edge.tail.name)
        h_ln = layout.lnodes.get(edge.head.name)
        if not t_ln or not h_ln:
            continue
        try:
            fs = float(edge.attributes.get("labelfontsize",
                       edge.attributes.get("fontsize", "14")))
        except ValueError:
            fs = 14.0

        for attr_name, ref_ln in [("headlabel", h_ln), ("taillabel", t_ln)]:
            lbl = edge.attributes.get(attr_name, "")
            if lbl:
                lw, lh = estimate_label_size(lbl, fs)
                bx, by = _find_best(ref_ln.x, ref_ln.y, 2, 2, lw, lh, 6)
                prefix = "_headlabel" if "head" in attr_name else "_taillabel"
                edge.attributes[f"{prefix}_pos_x"] = str(round(bx, 2))
                edge.attributes[f"{prefix}_pos_y"] = str(round(by, 2))
                placed.append((bx, by, lw, lh))

    # Graph-level label
    graph_label = layout.graph.get_graph_attr("label")
    if graph_label:
        try:
            gfs = float(layout.graph.get_graph_attr("fontsize") or "14")
        except ValueError:
            gfs = 14.0
        lw, lh = estimate_label_size(graph_label, gfs)
        labelloc = (layout.graph.get_graph_attr("labelloc") or "b").lower()
        labeljust = (layout.graph.get_graph_attr("labeljust") or "c").lower()
        real = list(layout.lnodes.values())
        if real:
            gbb_x1 = min(ln.x - ln.width / 2 for ln in real)
            gbb_x2 = max(ln.x + ln.width / 2 for ln in real)
            gbb_y1 = min(ln.y - ln.height / 2 for ln in real)
            gbb_y2 = max(ln.y + ln.height / 2 for ln in real)
        else:
            gbb_x1 = gbb_y1 = 0
            gbb_x2 = gbb_y2 = 100
        gcx = (gbb_x1 + gbb_x2) / 2
        gx = {"l": gbb_x1 + lw / 2, "r": gbb_x2 - lw / 2}.get(labeljust, gcx)
        gy = gbb_y1 - lh / 2 - 8 if labelloc == "t" else gbb_y2 + lh / 2 + 8
        layout.graph.set_graph_attr("_label_pos_x", str(round(gx, 2)))
        layout.graph.set_graph_attr("_label_pos_y", str(round(gy, 2)))
