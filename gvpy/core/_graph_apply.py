"""Object lookup helpers used by ``Graph.agapply``.

See: /lib/cgraph/apply.c @ 23

These three functions implement the ``objsearch`` callback table that
``agapply`` uses to walk a graph hierarchy and find the per-subgraph
image of a given node / edge / subgraph.

In Graphviz C, ``agapply`` selects one of three search functions
based on the object type and uses it to find the corresponding
object in each visited subgraph.  Here we expose the three searches
as plain free functions and let ``Graph.agapply`` pick one based on
``obj_type``.

Extracted from ``graph.py`` as part of the core refactor (TODO
``TODO_core_refactor.md`` step 6).  ``graph.py`` re-exports the same
names so the old ``from gvpy.core.graph import subnode_search``
imports continue to work.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph
    from .node import Node
    from .edge import Edge


def subnode_search(sub: "Graph", node_obj: "Node") -> Optional["Node"]:
    """Find ``node_obj``'s image in subgraph ``sub``.

    See: /lib/cgraph/apply.c @ 23

    If ``node_obj`` was created in ``sub`` directly, return it;
    otherwise look it up by name in ``sub.nodes``.
    """
    if node_obj.parent is sub:
        return node_obj
    return sub.nodes.get(node_obj.name, None)


def subedge_search(sub: "Graph", edge_obj: "Edge") -> Optional["Edge"]:
    """Find ``edge_obj``'s image in subgraph ``sub``.

    See: /lib/cgraph/apply.c @ 30

    If ``edge_obj`` belongs to ``sub`` directly, return it; otherwise
    look up the matching ``(tail, head, name)`` key in ``sub.edges``.
    """
    if edge_obj.graph is sub:
        return edge_obj
    key = (edge_obj.tail.name, edge_obj.head.name, edge_obj.name)
    return sub.edges.get(key, None)


def subgraph_search(sub: "Graph", graph_obj: "Graph") -> Optional["Graph"]:
    """Identity check used by ``agapply`` for subgraph traversal.

    See: /lib/cgraph/apply.c @ 37

    A subgraph is its own image, so return ``sub`` iff it is the same
    object as ``graph_obj``.
    """
    return sub if sub is graph_obj else None
