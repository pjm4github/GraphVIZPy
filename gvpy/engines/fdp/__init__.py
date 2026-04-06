"""
Fdp layout engine — force-directed placement (Fruchterman-Reingold).

Uses a spring-electrical model with grid-accelerated repulsive forces
and linear cooling.  Supports clusters and overlap removal.

Reference: Graphviz lib/fdpgen/
"""
from .fdp_layout import FdpLayout

__all__ = ["FdpLayout"]
