"""
Sfdp layout engine — scalable force-directed placement.

Extends fdp with multilevel coarsening and Barnes-Hut quadtree
approximation for O(n log n) repulsive force computation.

Reference: Graphviz lib/sfdpgen/
"""
from .sfdp_layout import SfdpLayout

__all__ = ["SfdpLayout"]
