"""Whole-hierarchy traversal helpers (no direct C analogue).

These four functions are gvpy-specific conveniences that walk the
graph + subgraph tree and gather every node, edge, or subgraph in
the hierarchy.  Graphviz C does not expose equivalents because the
``agfst*``/``agnxt*`` family already lets callers iterate within a
single graph; gvpy chose to materialise full lists for ease of use
in higher-level code (DOT writer, JSON I/O, layout engines).

Extracted from ``graph.py`` as part of the core refactor (TODO
``TODO_core_refactor.md`` step 6).  ``graph.py`` re-exports the
same names so existing imports continue to work.
"""
from __future__ import annotations

from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph
    from .node import Node
    from .edge import Edge


def gather_all_subgraphs(g) -> List["Graph"]:
    """Return ``g`` plus every nested subgraph (depth-first).

    No C analogue — Graphviz C uses ``agfstsubg``/``agnxtsubg`` to
    iterate the immediate children of a graph and recursive calls
    happen at the call site.
    """
    result = [g]
    for sg in g.subgraphs.values():
        result.extend(gather_all_subgraphs(sg))
    return result


def gather_all_nodes(g) -> List["Node"]:
    """Return every node in ``g`` plus every subgraph node.

    No C analogue — convenience wrapper around
    :func:`gather_all_subgraphs`.
    """
    nodes: List["Node"] = []
    for graph in gather_all_subgraphs(g):
        nodes.extend(graph.nodes.values())
    return nodes


def gather_all_edges(g) -> List["Edge"]:
    """Return every edge in ``g`` plus every subgraph edge.

    No C analogue — convenience wrapper around
    :func:`gather_all_subgraphs`.
    """
    edges: List["Edge"] = []
    for graph in gather_all_subgraphs(g):
        edges.extend(graph.edges.values())
    return edges


def get_root_graph(g) -> "Graph":
    """Climb the parent chain to the root ``Graph``.

    No C analogue — Graphviz C uses ``agroot(g)`` which is a single
    field read.  In gvpy the parent chain may need to be walked, and
    callers may pass either a Graph or any object with a ``parent``
    attribute (Node/Edge), so we duck-type via ``isinstance(Graph)``
    with a lazy import to avoid a graph<->traversal import cycle.
    """
    # Lazy import — Graph lives in graph.py, which itself imports
    # this module via re-export.
    from .graph import Graph
    if isinstance(g, Graph):
        while g.parent:
            g = g.parent
        return g
    return get_root_graph(g.parent)
