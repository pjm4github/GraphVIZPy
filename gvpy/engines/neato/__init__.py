"""
Neato layout engine — spring-model force-directed layout.

Uses stress majorization (default), Kamada-Kawai gradient descent,
or stochastic gradient descent to position nodes by minimizing a
stress function based on graph-theoretic distances.

Best for undirected graphs up to ~1000 nodes.

Reference: Graphviz lib/neatogen/
"""
from .neato_layout import NeatoLayout

__all__ = ["NeatoLayout"]
