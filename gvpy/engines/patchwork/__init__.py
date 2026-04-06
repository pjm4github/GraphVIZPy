"""
Patchwork layout engine — squarified treemap visualization.

Visualizes hierarchical data as nested rectangles where each node's
area is proportional to its ``area`` attribute.

Reference: Graphviz lib/patchwork/
"""
from .patchwork_layout import PatchworkLayout

__all__ = ["PatchworkLayout"]
