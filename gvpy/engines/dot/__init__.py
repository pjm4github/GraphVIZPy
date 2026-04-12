"""
Dot layout engine — hierarchical layout for directed graphs.

Implements the Sugiyama framework: rank assignment, crossing minimization,
coordinate assignment, and edge routing.

The engine state container is :class:`DotGraphInfo` (C analogue:
``Agraphinfo_t`` in ``lib/dotgen/dot.h``).  ``DotLayout`` is a
backward-compatibility alias pointing at the same class.
"""
from .dot_layout import DotGraphInfo, DotLayout

__all__ = ["DotGraphInfo", "DotLayout"]
