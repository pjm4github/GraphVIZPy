from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph

from .node import Node
from .edge import Edge
from .error import agerr, Agerrlevel
from .defines import ObjectType, EdgeType
from .headers import GraphEvent

_logger = logging.getLogger(__name__)


class EdgeMixin:
    """Mixin providing edge management methods for Graph."""

    def create_edge(self, tail, head, eid: int):
        """
        Creates a new pair of edges in a directed enclosed_node (AGOUTEDGE + AGINEDGE),
        or just one edge if you like. The snippet code uses an Agedgepair_t.
        We can store only the 'out' edge as the official reference (like core).
        """
        # We'll mimic the snippet: create two edge objects: in-edge, out-edge.
        # Return the 'out-edge' (AGOUTEDGE) as the primary handle.
        out_seq = self.get_next_sequence(ObjectType.AGEDGE)
        in_seq = self.get_next_sequence(ObjectType.AGEDGE)
        out_e = Edge(graph=self, name=f"{out_seq}", tail=tail, head=head, id_=eid, seq=out_seq, etype=EdgeType.AGOUTEDGE)
        in_e = Edge(graph=self, name=f"{out_seq}", tail=tail, head=head, id_=eid, seq=in_seq, etype=EdgeType.AGINEDGE)
        # We can link them if we want, but let's keep it simple.

        # Insert them into adjacency:
        tail.outedges.append(out_e)
        head.inedges.append(in_e)

        # We'll store only the 'out_e' in the dictionary as the "canonical" edge
        key = (tail.name, head.name, None)  # we don't have a textual name
        self.edges[key] = out_e
        return out_e

    def add_edge(self, tail_name: str, head_name: str, edge_name: Optional[str] = None, cflag: bool = True) -> Optional["Edge"]:
        """
        Equivalent to agedge(g, tail, head, edge_name, cflag).
        edge_name is the same as the key

        In standard core (the core Graphviz library) and most "compound node" designs, edges that cross between a
        parent graph and its subgraph follow this general policy:

        An edge belongs to a subgraph only if both of its endpoints are also in that subgraph.

        In other words, if tail and head nodes both live inside the subgraph, that edge can appear in the subgraph's
        edge dictionary.

        If one endpoint is outside (i.e., belongs to the parent graph), the edge does not appear in the subgraph.
        Crossing edges remain at the parent (or root) level.

        Because only one endpoint is inside the subgraph, the edge is tracked by the parent graph's (or the root
        graph's) .edges. The subgraph's .edges does not duplicate it.

        In a "compound node" scenario (like Graphviz's cmpnd.c code), you can optionally "splice" or "hide" crossing
        edges when collapsing a subgraph. For example:

            Splicing: Re-route the crossing edge so it connects to the compound node instead of the internal subgraph
            node, effectively collapsing those subgraph nodes behind a single node placeholder.

            Hiding: Remove or move the crossing edge into a "hidden set" so it vanishes from the parent's visible edges
            while the subgraph is collapsed.

        No replication of the edge in both parent and subgraph.**

        Graphviz/core does not store the same physical edge at two levels (parent and subgraph). Each edge is in
        exactly one scope—the lowest subgraph that actually owns both endpoints, or if only one endpoint is there,
        the edge remains at a higher (parent) scope.

        :param tail_name: Name of the tail node.
        :param head_name: Name of the head node.
        :param edge_name: Optional name for the edge.
        :param cflag: If True, create nodes if they do not exist.
        :return: The created Edge object if successful, else None.

        """
        if self.strict and tail_name == head_name:
            # No loops allowed in strict graphs
            agerr(Agerrlevel.AGERR, f"Error: Loops are not allowed in strict graphs (attempted to add edge from '{tail_name}' to itself).")
            return None
        tail = self.add_node(tail_name, create=cflag)  # source
        head = self.add_node(head_name, create=cflag)  # destination

        if not tail or not head:
            agerr(Agerrlevel.AGWARN, f"Failed to create edge from '{tail_name}' to '{head_name}'.")
            return None

        # Determine the owner graph for the edge:
        # If both endpoints have a parent (i.e. they belong to some subgraph), find their lowest common subgraph.
        if tail.parent is not None and head.parent is not None:
            lcs = self.lowest_common_subgraph(tail, head)
            edge_graph = lcs if lcs is not None else self
        else:
            # At least one node belongs directly to the current graph.
            edge_graph = self

        key = (tail_name, head_name, edge_name)
        # Check both the current subgraph AND the target edge_graph for
        # existing edges to avoid overwriting parallel edges.
        existing_in = self.edges.get(key) or edge_graph.edges.get(key)
        if existing_in is not None:
            if edge_name is not None:
                return existing_in
            # Auto-generate unique name for multi-edges
            i = 1
            while ((tail_name, head_name, f"_e{i}") in self.edges or
                   (tail_name, head_name, f"_e{i}") in edge_graph.edges):
                i += 1
            edge_name = f"_e{i}"
            key = (tail_name, head_name, edge_name)

        tail_in_subgraph = tail.compound_node_data.is_compound
        head_in_subgraph = head.compound_node_data.is_compound

        # check for existing edge if strict
        if self.strict:
            for e_key, e in self.edges.items():
                if e.tail == tail and e.head == head:
                    agerr(Agerrlevel.AGWARN, f"Warning: Edge from '{tail_name}' to '{head_name}' already exists in strict enclosed_node '{self.name}'.")
                    return e

        # Assign an anonymous ID (odd number) or named ID
        edge_id = self.disc.map(self.clos, ObjectType.AGEDGE, edge_name, createflag=True)
        if edge_id is None:
            agerr(Agerrlevel.AGWARN, f"Failed to allocate ID for edge from '{tail_name}' to '{head_name}'.")
            return None

        new_edge = Edge(graph=edge_graph, name=edge_name, tail=tail, head=head, id_=edge_id, key=edge_name)
        edge_graph.edges[key] = new_edge

        self.disc.idregister(self.clos, ObjectType.AGEDGE, new_edge)
        # agregister(self, ObjectType.AGEDGE, edge)
        # Insert into adjacency
        tail.outedges.append(new_edge)
        head.inedges.append(new_edge)

        # Update comparison data metrics
        tail.set_compound_data("centrality", self.compute_centrality(tail))
        head.set_compound_data("centrality", self.compute_centrality(head))
        tail.compound_node_data.update_degree(tail.outedges, tail.inedges)
        head.compound_node_data.update_degree(head.outedges, head.inedges)

        # Invoke edge added callbacks
        self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, new_edge)

        return new_edge

    def delete_edge(self, e: 'Edge') -> bool:
        """
        Deletes an edge from the enclosed_node.

        :param e: The Edge object to delete.
        """
        key = (e.tail.name, e.head.name, e.name)
        edge_to_delete = self.edges.get(key)
        if not edge_to_delete:
            agerr(Agerrlevel.AGWARN, f"Edge ({e.name}) from '{e.tail.name}' to '{e.head.name}' does not exist in enclosed_node '{self.name}'.")
            return False

        # Remove the edge from the adjacency lists using Node methods
        edge_to_delete.tail.remove_outedge(edge_to_delete)
        edge_to_delete.head.remove_inedge(edge_to_delete)

        # Remove the edge from the enclosed_node's edge dictionary
        del self.edges[key]

        # Free the edge's ID using the ID discipline
        self.disc.free(self.clos, ObjectType.AGEDGE, edge_to_delete.id)

        # agfreeid(self, ObjectType.AGEDGE, edge.id)
        # Also remove from adjacency lists

        # Update comparison data metrics if necessary
        edge_to_delete.tail.set_compound_data("centrality", self.compute_centrality(edge_to_delete.tail))
        edge_to_delete.head.set_compound_data("centrality", self.compute_centrality(edge_to_delete.head))
        # These should not be True because the edge_to_delete.tail.remove_outedge(edge_to_delete) call above
        if edge_to_delete in edge_to_delete.tail.outedges:
            edge_to_delete.tail.outedges.remove(edge_to_delete)
        if edge_to_delete in edge_to_delete.head.inedges:
            edge_to_delete.head.inedges.remove(edge_to_delete)

        # Invoke edge deleted callbacks
        self.clos.invoke_callbacks(GraphEvent.EDGE_DELETED, edge_to_delete)
        agerr(Agerrlevel.AGINFO, f"Edge '{edge_to_delete.name}' from '{edge_to_delete.tail.name}' to "
              f"'{edge_to_delete.head.name}' has been deleted successfully.")
        return True

    def find_edge_by_id_tail_head(self, tail, head, eid: int):
        """
        Like 'agfindedge_by_id', tries to find an edge by numeric ID in this enclosed_node
        or (if undirected) by flipping tail/head if not found.
        We'll just do a simple search in self.edges. In real core, you do dtsearch.
        """
        # We'll rummage through edges to see if any have the same ID.
        # Real Graphviz uses a node-based dictionary; here we do a linear search for demo.
        for e in self.edges.values():
            if e.id == eid and ((e.tail == tail and e.head == head) or
                                (not self.desc.directed and e.tail == head and e.head == tail)):
                return e
        return None

    def find_edge_by_id(self, eid: int):
        """
        Like 'agfindedge_by_id', tries to find an edge by numeric ID in this enclosed_node
        or (if undirected) by flipping tail/head if not found.
        We'll just do a simple search in self.edges. In real core, you do dtsearch.
        """
        # We'll rummage through edges to see if any have the same ID.
        # Real Graphviz uses a node-based dictionary; here we do a linear search for demo.
        for e in self.edges.values():
            if e.id == eid:
                return e
        return None

    def find_edge_by_name(self, name: str) -> Optional['Edge']:  # from /core/node.c
        """
        Equivalent to agfindnode_by_name in C.

        :param name: The name of the edge to find.
        :return: The Node object if found, else None.
        """
        id_ = self.disc.map(self.clos, ObjectType.AGNODE, name, createflag=False)
        # id_ = agmapnametoid(self, ObjectType.AGNODE, name, createflag=False)
        if id_ is not None:
            return self.find_edge_by_id(id_)
        return None

    def splice_edge(self, edge: 'Edge', new_tail: Optional['Node'] = None, new_head: Optional['Node'] = None):
        """
        Reassigns the tail and/or head of an edge, effectively moving its endpoints.

        :param edge: The Edge to splice.
        :param new_tail: The new tail node. If None, the tail remains unchanged.
        :param new_head: The new head node. If None, the head remains unchanged.
        """
        # Validate that new_tail and new_head exist within the enclosed_node
        if new_tail and new_tail.name not in self.nodes:
            agerr(Agerrlevel.AGWARN, f"New tail node '{new_tail.name}' does not exist in the enclosed_node.")
            return
        if new_head and new_head.name not in self.nodes:
            agerr(Agerrlevel.AGWARN, f"New head node '{new_head.name}' does not exist in the enclosed_node.")
            return

        if not isinstance(edge, Edge):
            agerr(Agerrlevel.AGWARN, "splice_edge can only be applied to Edge instances.")
            return
        if new_tail and not isinstance(new_tail, Node):
            agerr(Agerrlevel.AGWARN, "new_tail must be an Node instance or None.")
            return
        if new_head and not isinstance(new_head, Node):
            agerr(Agerrlevel.AGWARN, "new_head must be an Node instance or None.")
            return

        if new_tail:
            # Remove edge from current tail's outedges
            edge.tail.remove_outedge(edge)
            # Assign new tail
            edge.tail = new_tail
            # Add edge to new tail's outedges
            new_tail.add_outedge(edge)

        if new_head:
            # Remove edge from current head's inedges
            edge.head.remove_inedge(edge)
            # Assign new head
            edge.head = new_head
            # Add edge to new head's inedges
            new_head.add_inedge(edge)

        # Optionally, update comparison data
        if new_tail:
            new_tail.set_compound_data("centrality", self.compute_centrality(new_tail))
        if new_head:
            new_head.set_compound_data("centrality", self.compute_centrality(new_head))


# ── Module-level C-API functions ────────────────────────────────────
# These are the C-style free functions that mirror the Graphviz
# ``lib/cgraph/edge.c`` API.  They are kept as the authoritative
# C-porting reference; the EdgeMixin methods above are the Pythonic
# facade and (for the iterator family) thin wrappers around these.
#
# Extracted from ``graph.py`` as part of the core refactor (TODO
# ``TODO_core_refactor.md`` step 6).  ``graph.py`` re-exports them so
# the old ``from gvpy.core.graph import agedge`` imports keep working.


def agsubrep(g: "Graph", n: "Node") -> Optional["Node"]:
    """Return ``n`` if it belongs to graph ``g``, else None.

    C analogue: ``lib/cgraph/edge.c:agsubrep()``.  In C this looks up
    the ``Agsubnode_t`` adjacency record for ``n`` in ``g``.  Here we
    just check that ``g.nodes[n.name] is n``.
    """
    if n.name in g.nodes and g.nodes[n.name] is n:
        return n
    return None


def agfstout(g: "Graph", n: "Node") -> Optional["Edge"]:
    """First out-edge of ``n`` in ``g``.

    C analogue: ``lib/cgraph/edge.c:agfstout()``.
    """
    if agsubrep(g, n) is None:
        return None
    return n.outedges[0] if n.outedges else None


def agnxtout(g: "Graph", e: "Edge") -> Optional["Edge"]:
    """Next out-edge after ``e`` in ``g``.

    C analogue: ``lib/cgraph/edge.c:agnxtout()``.
    """
    t = e.tail
    if agsubrep(g, t) is None:
        return None
    outlist = t.outedges
    i = outlist.index(e)
    if i < len(outlist) - 1:
        return outlist[i + 1]
    return None


def agfstin(g: "Graph", n: "Node") -> Optional["Edge"]:
    """First in-edge of ``n`` in ``g``.

    C analogue: ``lib/cgraph/edge.c:agfstin()``.
    """
    if agsubrep(g, n) is None:
        return None
    return n.inedges[0] if n.inedges else None


def agnxtin(g: "Graph", e: "Edge") -> Optional["Edge"]:
    """Next in-edge after ``e`` in ``g``.

    C analogue: ``lib/cgraph/edge.c:agnxtin()``.
    """
    h = e.head
    if agsubrep(g, h) is None:
        return None
    inlist = h.inedges
    i = inlist.index(e)
    if i < len(inlist) - 1:
        return inlist[i + 1]
    return None


def agfstedge(g: "Graph", n: "Node") -> Optional["Edge"]:
    """First edge (out then in) of ``n`` in ``g``.

    C analogue: ``lib/cgraph/edge.c:agfstedge()``.
    """
    e = agfstout(g, n)
    if e:
        return e
    return agfstin(g, n)


def agnxtedge(g: "Graph", e: "Edge", n: "Node") -> Optional["Edge"]:
    """Next edge for ``n`` after ``e``, walking out-edges then in-edges.

    C analogue: ``lib/cgraph/edge.c:agnxtedge()``.  Self-loops appear
    only on the out-edge side, so when switching from out- to in-edge
    iteration we skip any edge that is a loop on ``n``.
    """
    if e.etype == EdgeType.AGOUTEDGE:
        rv = agnxtout(g, e)
        if rv is not None:
            return rv
        next_in = agfstin(g, n)
        while next_in and next_in.head == n and next_in.tail == n:
            next_in = agnxtin(g, next_in)
        return next_in
    else:
        rv = agnxtin(g, e)
        while rv and rv.tail == n and rv.head == n:
            rv = agnxtin(g, rv)
        return rv


def ok_to_make_edge(g: "Graph", t: "Node", h: "Node") -> bool:
    """Validate that an edge ``t -> h`` may be created in ``g``.

    C analogue: ``lib/cgraph/edge.c:ok_to_make_edge()``.  Rejects a
    duplicate parallel edge if ``g.strict`` is set, and rejects a
    self-loop if ``g.no_loop`` is set.
    """
    if g.strict:
        for e in t.outedges:
            if e.head == h:
                return False
    if g.no_loop and t == h:
        return False
    return True


def agedge(g: "Graph", tail_name: str, head_name: str,
           name: Optional[str], cflag: bool) -> Optional["Edge"]:
    """Find or create the edge ``tail_name -> head_name`` in ``g``.

    C analogue: ``lib/cgraph/edge.c:agedge()``.  If an edge with the
    given ``(tail, head, name)`` key already exists, return it.
    Otherwise, when ``cflag`` is true and ``ok_to_make_edge`` allows
    it, create a new ``AGOUTEDGE`` and wire it into the adjacency
    lists.
    """
    tail = g.add_node(tail_name)
    head = g.add_node(head_name)

    key = (tail_name, head_name, name)
    e = g.edges.get(key)
    if e:
        return e

    if not ok_to_make_edge(g, tail, head):
        return None

    eid = g.get_next_sequence(ObjectType.AGEDGE)
    out_e = Edge(tail=tail, head=head, name=name, graph=g, id_=eid,
                 seq=g.get_next_sequence(ObjectType.AGEDGE),
                 etype=EdgeType.AGOUTEDGE)
    tail.outedges.append(out_e)
    head.inedges.append(out_e)
    g.edges[key] = out_e
    return out_e


def agidedge(g: "Graph", tail_name, head_name, eid: int,
             cflag: Optional[bool] = False) -> Optional["Edge"]:
    """Find-or-create variant keyed by numeric ID.

    C analogue: ``lib/cgraph/edge.c:agidedge()``.  Looks up an
    existing edge by id (forward, plus reversed for undirected
    graphs).  If none exists and ``cflag`` is true, allocates a new
    edge with the given ID via :meth:`EdgeMixin.create_edge`.
    """
    tail = tail_name if isinstance(tail_name, Node) else g.add_node(tail_name)
    head = head_name if isinstance(head_name, Node) else g.add_node(head_name)

    e = g.find_edge_by_id_tail_head(tail, head, eid)
    if not e and not g.directed:
        e = g.find_edge_by_id_tail_head(head, tail, eid)
    if e:
        return e
    if cflag and ok_to_make_edge(g, tail, head):
        return g.create_edge(tail, head, eid)
    return None


def agdeledge(g: "Graph", e: "Edge") -> bool:
    """Delete an edge from ``g``'s edge dict and adjacency lists.

    C analogue: ``lib/cgraph/edge.c:agdeledge()``.  Removes ``e`` from
    ``tail.outedges``, ``head.inedges`` and the graph's edge
    dictionary.  Returns False if ``e`` is not in ``g``.
    """
    tail, head = e.tail, e.head
    found_key = None
    for (tname, hname, ename), edge_obj in list(g.edges.items()):
        if edge_obj is e:
            found_key = (tname, hname, ename)
            break
    if not found_key:
        return False

    if e in tail.outedges:
        tail.outedges.remove(e)
    if e in head.inedges:
        head.inedges.remove(e)
    del g.edges[found_key]
    return True
