"""Compound-node helper data and lookup.

C analogue: ``lib/cgraph/cmpnd.c``.  In Graphviz C, a "compound
node" is a node that has been associated with a subgraph (so the
subgraph can be collapsed/expanded behind a single node icon).  The
machinery is split into three records: ``Agcmpnode_t`` (per-node),
``Agcmpgraph_t`` (per-graph) and ``Agcmpedge_t`` (per-edge stack of
splice records).

This module exposes the **graph-side** half: the
:class:`Agcmpgraph` record (attached to every ``Graph`` instance as
``graph.cmp_graph_data``) and the :func:`agfindhidden` lookup that
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

    C analogue: ``Agcmpgraph_t`` from ``lib/cgraph/cmpnd.c`` plus the
    centrality / position fields that gvpy attaches to the same
    record for layout-engine convenience.

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

    C analogue: ``lib/cgraph/cmpnd.c:agfindhidden()``::

        Agnode_t *agfindhidden(Agraph_t *g, char *name)
        {
            Agcmpgraph_t *graphrec = ...;
            return dtsearch(graphrec->hidden_node_set, &key);
        }
    """
    graphrec = g.cmp_graph_data
    return graphrec.hidden_node_set.get(name)
