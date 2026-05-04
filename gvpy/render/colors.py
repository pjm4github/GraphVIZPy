"""X11 / Graphviz color name resolution.

Graphviz supports the full X11 color name table including the
numbered variants (``lightcyan2``, ``red4``, ``gray37``, etc.) which
are *not* part of the SVG / CSS color specification.  Browsers
silently fall back to ``black`` for unrecognised fill names, so
emitting raw Graphviz color names from the renderer produces
black-on-black blobs in any user with a non-Graphviz SVG viewer.

This module loads the same color table the C engine ships
(``lib/common/color_names`` — 679 entries) and provides
:func:`resolve_color` to map any Graphviz-accepted color spec to a
form an SVG renderer can pass straight through:

- standard SVG names (``red``, ``lightcyan``, ``blue``) — kept as-is
- numbered X11 variants (``lightcyan2``, ``red4``) — converted to hex
- ``#rrggbb`` / ``#rrggbbaa`` literals — kept as-is
- ``hsv`` triples (``"0.6 0.8 0.9"``) — converted to hex
- ``"none"`` — kept as-is

The C reference is ``lib/common/color.c::colorxlate``.
"""
from __future__ import annotations

import os
from functools import lru_cache


_TABLE_PATH = os.path.join(os.path.dirname(__file__), "_x11_colors.txt")

# SVG / CSS named colors — these don't need conversion.  Browsers
# resolve them natively.
_SVG_NAMED = frozenset({
    "aliceblue", "antiquewhite", "aqua", "aquamarine", "azure",
    "beige", "bisque", "black", "blanchedalmond", "blue", "blueviolet",
    "brown", "burlywood", "cadetblue", "chartreuse", "chocolate",
    "coral", "cornflowerblue", "cornsilk", "crimson", "cyan",
    "darkblue", "darkcyan", "darkgoldenrod", "darkgray", "darkgreen",
    "darkgrey", "darkkhaki", "darkmagenta", "darkolivegreen",
    "darkorange", "darkorchid", "darkred", "darksalmon", "darkseagreen",
    "darkslateblue", "darkslategray", "darkslategrey", "darkturquoise",
    "darkviolet", "deeppink", "deepskyblue", "dimgray", "dimgrey",
    "dodgerblue", "firebrick", "floralwhite", "forestgreen", "fuchsia",
    "gainsboro", "ghostwhite", "gold", "goldenrod", "gray", "green",
    "greenyellow", "grey", "honeydew", "hotpink", "indianred",
    "indigo", "ivory", "khaki", "lavender", "lavenderblush", "lawngreen",
    "lemonchiffon", "lightblue", "lightcoral", "lightcyan",
    "lightgoldenrodyellow", "lightgray", "lightgreen", "lightgrey",
    "lightpink", "lightsalmon", "lightseagreen", "lightskyblue",
    "lightslategray", "lightslategrey", "lightsteelblue", "lightyellow",
    "lime", "limegreen", "linen", "magenta", "maroon",
    "mediumaquamarine", "mediumblue", "mediumorchid", "mediumpurple",
    "mediumseagreen", "mediumslateblue", "mediumspringgreen",
    "mediumturquoise", "mediumvioletred", "midnightblue", "mintcream",
    "mistyrose", "moccasin", "navajowhite", "navy", "oldlace",
    "olive", "olivedrab", "orange", "orangered", "orchid",
    "palegoldenrod", "palegreen", "paleturquoise", "palevioletred",
    "papayawhip", "peachpuff", "peru", "pink", "plum", "powderblue",
    "purple", "rebeccapurple", "red", "rosybrown", "royalblue",
    "saddlebrown", "salmon", "sandybrown", "seagreen", "seashell",
    "sienna", "silver", "skyblue", "slateblue", "slategray",
    "slategrey", "snow", "springgreen", "steelblue", "tan",
    "teal", "thistle", "tomato", "transparent", "turquoise", "violet",
    "wheat", "white", "whitesmoke", "yellow", "yellowgreen",
})


@lru_cache(maxsize=1)
def _x11_table() -> dict[str, str]:
    """Load and cache the X11 color table as ``name -> "#rrggbb"``."""
    table: dict[str, str] = {}
    try:
        with open(_TABLE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                name = parts[0].lower()
                try:
                    r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
                except ValueError:
                    continue
                table[name] = f"#{r:02x}{g:02x}{b:02x}"
    except OSError:
        pass
    return table


def _hsv_to_hex(spec: str) -> str | None:
    """Convert ``"H S V"`` triple (each in [0, 1]) to ``#rrggbb``.

    Returns None on parse failure so the caller can fall back.
    """
    parts = spec.replace(",", " ").split()
    if len(parts) != 3:
        return None
    try:
        h, s, v = float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None
    if not (0 <= h <= 1 and 0 <= s <= 1 and 0 <= v <= 1):
        return None
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def resolve_color(spec: str | None) -> str:
    """Return an SVG-safe color string for any Graphviz color spec.

    - ``None`` / ``""`` → ``"none"``
    - ``#rrggbb`` / ``#rrggbbaa`` → returned unchanged
    - SVG named color → returned unchanged
    - X11 numbered variant (e.g. ``lightcyan2``) → ``#rrggbb``
    - HSV triple → ``#rrggbb``
    - Unknown → returned unchanged (last-resort fallback to let
      callers preserve untranslatable input)
    """
    if not spec:
        return "none"
    s = spec.strip()
    if not s:
        return "none"

    # Already a hex literal (with or without alpha) — pass through.
    if s.startswith("#"):
        return s

    low = s.lower()

    # SVG-native names need no translation.
    if low in _SVG_NAMED:
        return low

    # X11 numbered variants and other Graphviz extensions.
    table = _x11_table()
    if low in table:
        return table[low]

    # ``"H S V"`` numeric triple — Graphviz convention.
    hex_from_hsv = _hsv_to_hex(s)
    if hex_from_hsv is not None:
        return hex_from_hsv

    # Last-resort: pass through unchanged.  Some renderers may
    # accept it; if not, the caller sees the original input.
    return s
