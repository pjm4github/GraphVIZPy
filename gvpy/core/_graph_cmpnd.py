"""Compound-node helper data and lookup.

No direct C analogue in the current reference Graphviz repo — earlier
Graphviz versions shipped ``lib/cgraph/cmpnd.c`` with the compound-
node machinery (``Agcmpnode_t`` / ``Agcmpgraph_t`` / ``Agcmpedge_t``
records + ``agfindhidden`` lookup), but that file has since been
removed.  This module preserves the gvpy-side semantics: a
:class:`Agcmpgraph` record attached to every ``Graph`` instance as
``graph.cmp_graph_data`` plus the :func:`agfindhidden` lookup that
fetches a hidden node by name from a graph's hidden-node set.

Extracted from ``graph.py`` as part of the core refactor (TODO
``TODO_core_refactor.md`` step 6).  ``graph.py`` re-exports both
names so existing imports keep working.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .node import Node
    from .edge import Edge


class Agcmpgraph:
    """Per-graph compound-node record.

    No direct C analogue — earlier Graphviz defined ``Agcmpgraph_t``
    in ``lib/cgraph/cmpnd.c``; that file is gone from the current
    reference.  gvpy keeps an equivalent record shape plus additional
    centrality / position fields that layout engines write onto the
    same object.

    Tracks the associated compound node (if any), the dictionaries of
    hidden nodes/edges that belong to a collapsed compound subgraph,
    and a few derived metrics (degree, centrality, position) that
    layout/analysis engines write directly onto the record.
    """

    def __init__(self, node=None, hidden_node_set=None,
                 hidden_edge_set=None, collapsed=False):
        """
        :param node:  the associated compound node (if any)
        :param hidden_node_set: a dictionary or set for "hidden" nodes
        :param hidden_edge_set: a dictionary or set for "hidden" edges
        :param collapsed:  whether compound graph is collapsed
        """
        self.node = node
        self.hidden_node_set: Dict[str, "Node"] = (
            hidden_node_set if hidden_node_set else {}
        )
        self.hidden_edge_set: Dict[Tuple[str, str, Optional[str]], "Edge"] = (
            hidden_edge_set if hidden_edge_set else {}
        )
        self.collapsed = collapsed

        # Centrality / degree metrics computed by analysis routines.
        self.degree: int = 0
        self.centrality: float = 0.0
        self.degree_centrality: float = 0.0
        self.betweenness_centrality: float = 0.0
        self.closeness_centrality: float = 0.0
        self.degree_centrality_normalized = 0.0
        self.rank: int = 0  # hierarchical layout rank

        # Position used by layout engines.
        self.x: float = 0.0
        self.y: float = 0.0


def agfindhidden(g, name):
    """Look up a hidden node by name in ``g``'s compound-node record.

    No direct C analogue — earlier Graphviz exposed ``agfindhidden``
    from ``lib/cgraph/cmpnd.c``; removed from the current reference
    repo.  Equivalent: dict lookup on the graph's ``hidden_node_set``.
    """
    graphrec = g.cmp_graph_data
    return graphrec.hidden_node_set.get(name)
