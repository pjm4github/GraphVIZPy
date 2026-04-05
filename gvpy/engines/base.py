"""
Abstract base class for all GraphvizPy layout engines.

Every layout engine (dot, neato, circo, etc.) subclasses ``LayoutEngine``
and implements the ``layout()`` method, which takes a Graph and returns
a JSON-serializable dict with node positions, edge routes, and metadata.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.core.graph import Graph


class LayoutEngine(ABC):
    """Base class for graph layout engines.

    Subclasses must implement ``layout()`` which computes positions
    for all nodes and routes for all edges.

    Usage::

        engine = DotLayout(graph)
        result = engine.layout()
        # result is a JSON-serializable dict
    """

    def __init__(self, graph: "Graph"):
        self.graph = graph

    @abstractmethod
    def layout(self) -> dict:
        """Compute layout and return a JSON-serializable result dict.

        Returns
        -------
        dict
            A dict with keys:

            - ``graph``: ``{name, directed, bb, ...}``
            - ``nodes``: ``[{name, x, y, width, height, ...}, ...]``
            - ``edges``: ``[{tail, head, points, ...}, ...]``
            - ``clusters`` (optional): ``[{name, label, bb, nodes}, ...]``
        """
        ...
