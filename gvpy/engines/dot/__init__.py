"""
Dot layout engine — hierarchical layout for directed graphs.

Implements the Sugiyama framework: rank assignment, crossing minimization,
coordinate assignment, and edge routing.
"""
from .dot_layout import DotLayout

__all__ = ["DotLayout"]
