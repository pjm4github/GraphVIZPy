"""
Osage layout engine — recursive cluster packing.

Arranges nodes within nested rectangular clusters using a bottom-up
packing algorithm.  Each cluster becomes a rectangular region with
its children (nodes and subclusters) packed inside.

Reference: Graphviz lib/osage/
"""
from .osage_layout import OsageLayout

__all__ = ["OsageLayout"]
