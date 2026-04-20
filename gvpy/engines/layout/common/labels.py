"""Label-related utilities shared across layout engines.

See: /lib/common/labels.c

Thin for now — only the attribute-parsing helper that replaces C's
``late_double`` idiom.  Future additions (label bounding-box rotation,
label-anchor offsets, etc.) belong here rather than in the
dot-specific ``label_place.py``.
"""
from __future__ import annotations


def late_double(attr_str: str, default: float, minimum: float) -> float:
    """Parse a numeric attribute with fallback default + floor clamp.

    See: /lib/common/utils.c @ 55

    An empty, missing, or unparseable string yields *default*;
    otherwise the parsed value is clamped up to *minimum*.  Mirrors
    Graphviz C's ``late_double(obj, attr, default, minimum)`` idiom
    but drops the obj/attr lookup (callers pass the string value
    directly).
    """
    if not attr_str:
        return default
    try:
        v = float(attr_str)
    except ValueError:
        return default
    return max(v, minimum)
