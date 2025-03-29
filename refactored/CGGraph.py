# import threading
# from contextlib import contextmanager
# from enum import Enum
from copy import copy
from typing import Callable, Optional, List, Dict, Tuple, Union, Any, TYPE_CHECKING
from collections import deque
if TYPE_CHECKING:
    from .Headers import *
    from .Defines import *
    from .CGError import *
    from .CGNode import Node, CompoundNode, agsplice, save_stack_of, stackpush, NodeDict
    from .CGEdge import Edge

from .Agobj import Agobj
from .Headers import AgIdDisc, AgSym, Agdesc, GraphEvent, Agcbstack, Agcbdisc
from .Defines import ObjectType, EdgeType, LOCALNAMEPREFIX
from .CGNode import Node, CompoundNode, agsplice, save_stack_of, stackpush, NodeDict
from .CGEdge import Edge
from .CGError import agerr, Agerrlevel

class Agcmpgraph:  # from /cgraph/cmpnd.c  (compound enclosed_node functions)
    """
    Pythonic version of 'Agcmpgraph_t':
    """
    def __init__(self, node=None, hidden_node_set=None, hidden_edge_set=None, collapsed=False):
        """

        :param node:  the associated compound node (if any)
        :param hidden_node_set: a dictionary or set for "hidden" nodes
        :param hidden_edge_set: a dictionary or set for "hidden" edges
        :param collapsed:  whether compound graph is collapsed
        """
        self.node = node
        self.hidden_node_set: Dict[str, 'Node'] = hidden_node_set if hidden_node_set else {}  # or a dict, keyed by node name
        self.hidden_edge_set: Dict[Tuple[str, str, Optional[str]], 'Edge'] = hidden_edge_set if hidden_edge_set else {}  # or a dict, keyed by edge name
        self.collapsed = collapsed

        self.degree: int = 0  # Total number of connections (incoming + outgoing).
        self.centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.degree_centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.betweenness_centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.closeness_centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.degree_centrality_normalized = 0.0
        self.rank: int = 0  # Position in hierarchical layouts.

        # Example of positional data
        # x and y: Coordinates for node placement (useful for layout algorithms).
        self.x: float = 0.0
        self.y: float = 0.0


class GraphDict(dict):
    """
    Represents a dictionary with custom memory management.
    """
    def __init__(self,  seq=None, discipline: Optional[AgIdDisc] = None, method: Optional[Callable] = None, **kwargs):
        super().__init__(seq=seq, **kwargs)
        self.discipline = discipline
        self.method = method
        self.store: Dict[Any, Any] = {}

    def add(self, key: Any, value: Any):
        self.store[key] = value

    def delete(self, key: Any) -> bool:
        if key in self.store:
            del self.store[key]
            return True
        return False

    def close(self) -> bool:
        self.store.clear()
        return True



def gather_all_nodes(g) -> List['Node']:
    """Return a list of all nodes in g plus all subgraphs."""
    all_g = gather_all_subgraphs(g)
    nodes = []
    for graph in all_g:
        nodes.extend(graph.nodes.values())
    return nodes


def gather_all_edges(g) -> List['Edge']:
    """Return a list of all edges in g plus all subgraphs."""
    all_g = gather_all_subgraphs(g)
    edges = []
    for graph in all_g:
        edges.extend(graph.edges.values())
    return edges



def agattr(graph, kind, name, default_value) -> Optional[AgSym]:  # from /cgraph/attr.c
    raise NotImplementedError("use the enclosed_node.agattr method instead")
    # """
    # Pythonic version of 'agattr(g, kind, name, value)':
    # - 'enclosed_node' is presumably the root or local enclosed_node.
    # - If attribute 'name' doesn't exist for 'kind', create it with 'default_value'.
    # - Then ensure all existing objects of that kind have a slot for it.
    # Returns the newly created or existing AgSym.
    # In this pythonic version there are 3 different dictionaries maintained in the root enclosed_node.
    # When this method is called, the key is checked for existance in one of these 3 dictionaries and if it
    # exists, it is returned it is updated and the value is returned
    #
    # If the key doesn't exist, then a new key is added to that dictionary and the default_value assigned and returned.
    #
    # """
    # root = get_root_graph(enclosed_node)
    # if kind == AGTYPE_GRAPH:
    #     adict = root.attr_dict_g
    # elif kind == AGTYPE_NODE:
    #     adict = root.attr_dict_n
    # elif kind == AGTYPE_EDGE:
    #     adict = root.attr_dict_e
    # else:
    #     return None
    #
    # # Already declared?
    # if name in adict:
    #     value = adict[name]
    #     if default_value is not None:
    #         adict[name] = default_value
    #     return value
    # else:
    #     # Create new symbol
    #     adict[name] = default_value
    #
    #     # Now assign the default to all existing objects of that kind
    #     # in the root enclosed_node (and presumably subgraphs).
    #     if kind == AGTYPE_GRAPH:
    #         # For each enclosed_node in the hierarchy, set default if not present
    #         for g2 in gather_all_subgraphs(root):
    #             if g2.attr_record.get(name) is None:
    #                 g2.attr_record.set_value(name, default_value)
    #     elif kind == AGTYPE_NODE:
    #         for n2 in gather_all_nodes(root):
    #             if n2.attr_record.get_value(name) is None:
    #                 n2.attr_record.set_value(name, default_value)
    #     elif kind == AGTYPE_EDGE:
    #         for e2 in gather_all_edges(root):
    #             if e2.attr_record.get_value(name) is None:
    #                 e2.attr_record.set_value(name, default_value)
    #     return default_value




# 3.6 agnextseq(g, objtype)
# In C, it increments g->clos->seq[objtype]. In Python:
def agnextseq(g: 'Graph', objtype: ObjectType) -> int:
    seq = g.get_next_sequence(objtype)
    return seq



def subnode_search(sub: 'Graph', node_obj: 'Node') -> Optional['Node']:   # from cgraph/apply.c
    """
    If the given node_obj's enclosed_node is 'sub', return node_obj immediately.
    Otherwise, try to find a 'Node' with the same name in sub.
    """
    if node_obj.parent is sub:
        return node_obj
    # Look up by name in the subgraph's node dictionary
    return sub.nodes.get(node_obj.name, None)


def subedge_search(sub: 'Graph', edge_obj: 'Edge') -> Optional['Edge']:   # from cgraph/apply.c
    """
    If the edge_obj's enclosed_node is 'sub', return edge_obj.
    Otherwise, attempt to find an edge with the same (tail_name, head_name, edge_name).
    """
    if edge_obj.graph is sub:
        return edge_obj

    key = (edge_obj.tail.name, edge_obj.head.name, edge_obj.name)
    return sub.edges.get(key, None)


def subgraph_search(sub: 'Graph', graph_obj: 'Graph') -> Optional['Graph']:   # from cgraph/apply.c
    """
    If graph_obj is the same as 'sub' (the exact Python object), return it; else None.
    This matches the idea that a subgraph's 'image' is the subgraph itself.
    """
    return sub if sub is graph_obj else None


# 8. Finding Hidden Nodes: agfindhidden(g, name)
# The original code:
#  Agnode_t *agfindhidden(Agraph_t * g, char *name)
# {
#     Agcmpgraph_t *graphrec;
#     ...
#     return dtsearch(graphrec->hidden_node_set, &key);
# }
def agfindhidden(g, name):  # from /cgraph/cmpnd.c
    """
    Return the hidden node in g->cmp_graph_data->hidden_node_set if present.
    """
    graphrec = g.cmp_graph_data
    return graphrec.hidden_node_set.get(name)

# Summary
# We’ve augmented the Python Graph, Node, and Edge classes with:
#
# Compound node data (AgcmpnodeData) for subgraph association and a collapsed flag.
# Compound enclosed_node data (AgcmpgraphData) for linking back to the node and storing hidden nodes.
# Compound edge data (AgcmpedgeData) with stacks that track splicing.
# Functions that replicate the C code’s main operations: agcmpnode, agassociate, aghide, agexpose,
# agcmpgraph_of, agcmpnode_of, agsplice, etc.
# This design allows your Python enclosed_node objects to behave similarly to “compound nodes”
# in the provided C code, letting you hide/expose subgraph internals and track spliced edges.

# 2. Replicating the C Routines
# 2.1 agsubrep(g, n)
# In the C snippet, agsubrep(g, n) either returns &n->mainsub if g == n->root, or it looks up a
# “subnode” in g->n_id.
#
# For a simpler Python approach, we can interpret subrep as: “Return the adjacency record for node n
# within this enclosed_node.” If the node actually belongs to g, we just return n.
# Otherwise, (in actual cgraph), we might search a subgraph’s node dict.
def agsubrep(g: 'Graph', n: 'Node') -> Optional['Node']:  # from cgraph/edge.c
    """
    Return the node 'n' as it is in enclosed_node 'g', if it belongs to 'g',
    or None if not found. In the real cgraph, it might do dtsearch
    for the 'subnode' structure. We'll do a simpler check.

    (If you want sub-subgraph logic, you’d do more complex checks,
    but this is enough to replicate the spirit.)
    """
    if n.name in g.nodes and g.nodes[n.name] is n:
        return n
    return None

# 2.2 Edge Iterators: agfstout, agnxtout, agfstin, agnxtin, etc.
# We can mimic them by storing a cursor in the node’s adjacency list. But in pure Python,
# it’s simpler to do generators. However, to stay consistent with the snippet (which returns one edge at a time),
# we’ll track a “current index” in the adjacency list.
#
# One approach is to store these cursors in a dictionary. Another is to just replicate the pattern:
# “the first call returns the first edge; subsequent calls return the next.” We'll do a simple approach: each function
# returns an edge or None. If you want “the next” call to proceed, you store the last edge and do a python
# list index search. This approach is akin to the snippet, which does dtfirst(...) / dtnext(...).
def agfstout(g: 'Graph', n: 'Node') -> Optional['Edge']:  # from cgraph/edge.c
    """Return the first outedge of node n in enclosed_node g."""
    # Check that n is actually in g
    if agsubrep(g, n) is None:
        return None
    # Return the first edge in n.outedges or None
    return n.outedges[0] if n.outedges else None

def agnxtout(g: 'Graph', e: 'Edge') -> Optional['Edge']:   # from cgraph/edge.c
    """Return the next outedge of node tail(e) in enclosed_node g."""
    t = e.tail
    if agsubrep(g, t) is None:
        return None
    outlist = t.outedges
    # Find e in outlist, return the next item
    i = outlist.index(e)
    if i < len(outlist) - 1:
        return outlist[i+1]
    return None

def agfstin(g: 'Graph', n: 'Node') -> Optional['Edge']:   # from cgraph/edge.c
    """Return the first inedge of node n."""
    if agsubrep(g, n) is None:
        return None
    return n.inedges[0] if n.inedges else None

def agnxtin(g: 'Graph', e: 'Edge') -> Optional['Edge']:   # from cgraph/edge.c
    """Return the next inedge of node head(e)."""
    h = e.head
    if agsubrep(g, h) is None:
        return None
    inlist = h.inedges
    i = inlist.index(e)
    if i < len(inlist) - 1:
        return inlist[i+1]
    return None

# 2.3 agfstedge & agnxtedge
# They unify out-edges and in-edges in a single iteration. The snippet does:
#
# agfstedge(g, n) tries agfstout first; if None, tries agfstin.
# agnxtedge(g, e, n) continues out-edges. If it’s None, then moves to in-edges, skipping loops.

def agfstedge(g: 'Graph', n: 'Node') -> Optional['Edge']:   # from cgraph/edge.c
    """Return first edge (out or in) of n."""
    e = agfstout(g, n)
    if e:
        return e
    return agfstin(g, n)


def agnxtedge(g: 'Graph', e: 'Edge', n: 'Node') -> Optional['Edge']:   # from cgraph/edge.c
    """
    Return next edge for node n, continuing outedges if possible.
    If we exhaust outedges, switch to inedges (ignoring loops that appear as inedges).
    (This is a direct parallel to how the snippet handles loops as in-edges.)

    """
    if e.etype == EdgeType.AGOUTEDGE:
        # we were walking outedges
        rv = agnxtout(g, e)
        if rv is not None:
            return rv
        # done with outedges. move on to inedges,
        # but we skip loops as in-edges if e.node == n
        # so let's just get the first inedge or the next inedge from the last in.
        next_in = agfstin(g, n)
        while next_in and next_in.head == n and next_in.tail == n:
            # skip self-loop as in-edge
            next_in = agnxtin(g, next_in)
        return next_in
    else:
        # we were walking inedges
        # skip loops as in-edges
        rv = agnxtin(g, e)
        while rv and rv.tail == n and rv.head == n:
            rv = agnxtin(g, rv)
        return rv

# 2.4 Creating/Deleting Edges
# 2.4.1 ok_to_make_edge(g, t, h)
# Similar to ok_to_make_edge, check strictness and loops:
def ok_to_make_edge(g: 'Graph', t: 'Node', h: 'Node') -> bool:   # from cgraph/edge.c
    """Return True if we can create an edge from t to h in enclosed_node g."""
    # If strict and an edge t->h already exists, fail
    if g.strict:
        # check if any edge t->h already exists
        for e in t.outedges:
            if e.head == h:
                return False
    if g.no_loop and t == h:
        return False
    return True

# 2.4.2 agedge(g, t, h, name, cflag)
# Mimic the logic of the snippet:
#
# If name is provided, try to find an existing ID or existing edge.
# If none found, create a new one if cflag && ok_to_make_edge(...).
def agedge(g: 'Graph', tail_name: str, head_name: str, name: Optional[str], cflag: bool) -> Optional['Edge']:   # from cgraph/edge.c
    """
    Pythonic version of 'agedge(Agraph_t *g, Agnode_t *t, Agnode_t *h, char *name, int cflag)'.
    - If name is given, we might do ID-based logic. We'll keep it simpler here:
      we see if there's an existing edge with the same key. If yes, return it.
      If not, possibly create a new edge.
    - cflag: create edge if it doesn't exist
    """
    tail = g.add_node(tail_name)
    head = g.add_node(head_name)

    # In real cgraph, 'name' might map to an ID. Let's skip that and just store 'name' in the edge as a label.
    key = (tail_name, head_name, name)
    e = g.edges.get(key)
    if e:
        return e

    # If strict/no_loop checks fail, return None
    if not ok_to_make_edge(g, tail, head):
        if cflag:
            return None
        else:
            return None  # same result in either case

    # Otherwise, create a new edge
    eid = g.get_next_sequence(ObjectType.AGEDGE)
    # g._next_edge_id += 1
    # tail: Node, head: Node, name: str, enclosed_node: Graph, id=None, seq=None, etype: str=None):
    out_e = Edge(tail=tail, head=head, name=name, graph=g, id_=eid,
                 seq=g.get_next_sequence(ObjectType.AGEDGE), etype=EdgeType.AGOUTEDGE)

    # Insert adjacency
    tail.outedges.append(out_e)
    head.inedges.append(out_e)  # We'll store the same Edge object for in-edge too

    # Insert into the dictionary
    g.edges[key] = out_e
    return out_e

# 2.4.3 agidedge(g, t, h, id, cflag)
# If we want a direct ID-based creation:
def agidedge(g: 'Graph', tail_name: [str, 'Node'], head_name: [str, 'Node'], eid: int, cflag: Optional[bool] = False) -> Optional['Edge']:   # from cgraph/edge.c
    """
    Pythonic version of 'agidedge(Agraph_t *g, t, h, id, cflag)'
    - Attempt to find an edge with numeric id in 'g' or in undirected sense.
    - If not found and cflag is True and ok_to_make_edge is True, create it.
    """
    if isinstance(tail_name, Node):
        tail = tail_name
    else:
        tail = g.add_node(tail_name)
    if isinstance(head_name, Node):
        head = head_name
    else:
        head = g.add_node(head_name)

    # see if the edge by ID already exists
    e = g.find_edge_by_id_tail_head(tail, head, eid)

    if not e and not g.directed:
        # if undirected, check reversed as well
        e = g.find_edge_by_id_tail_head(head, tail, eid)
    if e:  # found existing
        return e
    if cflag and ok_to_make_edge(g, tail, head):
        # create a new edge with this ID
        # in real code, we do 'agallocid()' to see if ID is free
        out_e = g.create_edge(tail, head, eid)
        return out_e

    return None

#  2.4.4 agdeledge(g, e)
# Delete an edge from the enclosed_node’s dictionary and from adjacency lists:

def agdeledge(g: 'Graph', e: 'Edge') -> bool:   # from cgraph/edge.c
    """
    Pythonic version of 'agdeledge(Agraph_t *g, Agedge_t *e)'.
    - Must remove e from the adjacency of tail and head
    - Must remove from g.edges
    """
    # find the canonical out-edge object (the snippet uses AGMKOUT)
    # In our simpler design, 'e' might already be that object.
    tail, head = e.tail, e.head

    # check if edge 'e' actually belongs to 'g'
    # We'll do a dictionary scan:
    found_key = None
    for (tname, hname, ename), edge_obj in list(g.edges.items()):
        if edge_obj is e:
            found_key = (tname, hname, ename)
            break
    if not found_key:
        return False  # not in this enclosed_node

    # remove from adjacency
    if e in tail.outedges:
        tail.outedges.remove(e)
    if e in head.inedges:
        head.inedges.remove(e)

    # remove from dictionary
    del g.edges[found_key]
    # If the enclosed_node is root, also do attribute cleanups, free IDs, etc.
    return True

class Graph(Agobj):  # from cgraph/cgraph.c
    """
    Pythonic equivalent of 'Agraph_t', inheriting from 'Agobj'.
    Manages nodes, edges, and subgraphs
    Equivalent to: agopen(name, description, arg_disc)

    obj.c contains these add in functions that are included as class methods here:
    Summary of the following Graph class methods:

        agdelete: Deletes enclosed_node objects.
        agrename: Renames enclosed_node objects.
        agmethod_init: Initializes callback methods for objects.
        aginitcb: Initializes callbacks by traversing the callback stack.
        agmethod_upd: Updates callback methods based on symbols.
        agupdcb: Updates callbacks by traversing the callback stack.
        agmethod_delete: Deletes callback methods for objects.
        agdelcb: Deletes callbacks by traversing the callback stack.
        agroot: Retrieves the root enclosed_node of an object.
        agraphof: Retrieves the enclosed_node to which an object belongs.
        agpushdisc: Pushes a discipline onto the callback stack.
        agpopdisc: Pops a discipline from the callback stack.
        agcontains: Checks if a enclosed_node contains a specific object.
        agobjkind: Determines the type/kind of enclosed_node object.


    """

    def __init__(self, name: str,
                 description: Optional[Agdesc] = None,
                 disc: Optional[AgIdDisc] = None,
                 parent: Optional['Graph'] = None,
                 root: Optional['Graph'] = None,
                 directed=False,
                 strict=False,
                 no_loop=False):
        """
        Create a new main enclosed_node with the given descriptor (directed, strict, etc.).
            1) Make closure
            3) Set fields
            4) Call agmapnametoid(...) to get numeric ID
            5) Call agopen1(g)
            6) agregister(g, AGRAPH, g)
        :param name: String name of the enclosed_node
        :param description: A enclosed_node descriptor
        :param disc: Discipline holder (closure)
        :param parent: A enclosed_node of this enclosed_node (if any)
        :param directed: Whether the enclosed_node is directed
        :param strict: Whether the enclosed_node is strict or not
        :param no_loop: Whether there are loops or not
        """
        super().__init__(obj_type=ObjectType.AGGRAPH)  # AGTYPE_GRAPH)

        self.dict = None
        self.name = name
        # 1) Build the enclosed_node descriptor
        self.desc = description if description else (
            Agdesc(maingraph=(parent is None),
                   directed=directed,
                   strict=strict,
                   no_loop=no_loop,
                   ))
        # The 'description.flatlock' in C code is represented by a boolean here:
        # self.description.flatlock = False  # False => 'set' mode; True => 'list' mode (by default)

        self.disc = disc if disc else AgIdDisc()  # Use the default ID discipline
        self.parent = parent
        self.root: 'Graph' = root if root else self  # Reference to root enclosed_node
        self.directed = directed  # Initialize the directed attribute
        # Subgraphs, nodes, edges
        # The nodes are contained in a child class of a dict that tracks the enclosed_node.
        # This is needed to ensure that any node added directly to a subgraph will inherit the subgraph itself.
        # See the NodeDict class in the CGNode package.
        self.nodes: NodeDict[str, 'Node']= NodeDict(parent=parent)
        #self._nodes: NodeDict[str, 'Node'] = {}  # n_name -> 'Node'
        self.edges: Dict[Tuple[str, str, Optional[str]], 'Edge'] = {} # (tail_name, head_name, edge_name) -> 'Edge'
        self.subgraphs: Dict[str, Graph] = {}  # subgraph_name -> Graph
        self.id_to_subgraph: Dict[int, Graph] = {}  # Dictionary to store subgraphs by ID
        # This can be acheived by self.subgraphs[name].id
        # self.subgraph_name_to_id: Dict[str, int] = {}  # Mapping from subgraph names to IDs
        # self._id_counter: int = 1  # Starting ID counter


        # Whether we've "closed" or not
        self.closed = False

        # Initialize 'clos' using the Agclos class via AgIdDisc's open method
        self.clos = self.disc.open()
        # 3) Set descriptor fields
        # self.root = self
        # 4) open ID discipline
        # Map the enclosed_node name to an ID
        self.id = self.disc.map(self.clos, ObjectType.AGGRAPH, self.name, createflag=True)
        if self.id is None:
            agerr(Agerrlevel.AGWARN, f"Failed to allocate ID for enclosed_node '{self.name}'.")
        # The idregister should be done after the Graph init method by the caller
        # else:
        #     self.disc.idregister(self.clos, ObjectType.AGGRAPH, self)

        self.strict = strict
        self.no_loop = no_loop
        # ID fields

        self.seq = None

        self.is_main_graph = (parent is None)

        # If we're the root enclosed_node, these are truly ours.
        # If we're a subgraph, we might share or inherit from enclosed_node.
        if self.parent is None:
            self.attr_dict_g = {}
            self.attr_dict_n = {}
            self.attr_dict_e = {}
        else:
            # For simplicity, let's just reference the enclosed_node's dict.
            # A more faithful approach might do dtview/dtcopy, etc.
            if not hasattr(self.parent, "attr_dict_g"):
                self.parent.attr_dict_g = {}
            if not hasattr(self.parent, "attr_dict_n"):
                self.parent.attr_dict_n = {}
            if not hasattr(self.parent, "attr_dict_e"):
                self.parent.attr_dict_e = {}
            self.attr_dict_g = self.parent.attr_dict_g
            self.attr_dict_n = self.parent.attr_dict_n
            self.attr_dict_e = self.parent.attr_dict_e

        # Our own 'AgAttrRecord' for storing the enclosed_node's string values
        self.attr_record = {}

        # Initialize any default values declared at the root
        self.init_local_attr_values()

        # # Make sure we call the method initialization callback
        # agmethod_init(self, self)
        #
        # "Compound enclosed_node" data structure
        # In C, we might bindrec(g, Descriptor_id, ...)
        # Initialize compound_node_data as an instance of CompoundNode
        self.cmp_graph_data: Agcmpgraph = Agcmpgraph()
        #
        # self.id = agmapnametoid(self, objtype=ObjectType.AGGRAPH, name=name, createflag=True)
        # # Possibly more initialization or attribute logic...
        # # (like attr_dict_g, etc.) omitted for brevity.
        #
        # # A simple global edge ID counter:
        # self._next_edge_id = 1
        #
        self.has_cmpnd: bool = False  # Flag indicating presence of compound subgraphs
        # # Discipline stack (for managing callbacks and disciplines)
        # self.discipline_stack: Optional["Agcbstack"] = None
        self.initialized: bool = False  # Flag to check if method_init has been called
        self._strdict: Dict[str, Dict[str, Any]] = {}  # String dictionary for reference-counted strings

    def _getattr(self, kind: ['Graph', Node, Edge], name: str) -> Optional[AgSym]:
        if isinstance(kind, ObjectType):
            if kind == ObjectType.AGGRAPH:
                return self.attr_dict_g.get(name)
            elif kind == ObjectType.AGNODE:
                return self.attr_dict_n.get(name)
            elif kind == ObjectType.AGEDGE:
                return self.attr_dict_e.get(name)
            else:
                raise ValueError("Unknown attribute kind")
        else:

            if isinstance(kind, Graph):
                return self.attr_dict_g.get(name)
            elif isinstance(kind, Node):
                return self.attr_dict_n.get(name)
            elif isinstance(kind, Edge):
                return self.attr_dict_e.get(name)
            else:
                raise ValueError("Unknown attribute kind")

    def _setattr(self, kind: ['Graph', Node, Edge, ObjectType], name: str, value: str) -> AgSym:
        if isinstance(kind, ObjectType):
            if kind == ObjectType.AGGRAPH:
                attr_dict = self.attr_dict_g
            elif kind == ObjectType.AGNODE:
                attr_dict = self.attr_dict_n
            elif kind == ObjectType.AGEDGE:
                attr_dict = self.attr_dict_e
            else:
                raise ValueError("Unknown attribute kind")
        else:
            if isinstance(kind, Graph):
                attr_dict = self.attr_dict_g
            elif isinstance(kind, Node):
                attr_dict = self.attr_dict_n
            elif isinstance(kind, Edge):
                attr_dict = self.attr_dict_e
            else:
                raise ValueError("Unknown attribute kind")
        if name in attr_dict:
            # Update the default value of an existing attribute.
            attr_dict[name] = value
        else:
            # Create a new attribute.
            # (Here we use the current dictionary size as the new symbol's id.)
            attr_dict[name] = value
            # (In the original C code, this new global definition is propagated to all objects.)
        # (In a fuller implementation, one would invoke callbacks, update defaults, etc.)
        return attr_dict


    def agopen1(self):
        """
        # 3.3 agopen1(g)
        # In C: “initialize dictionaries, set seq, invoke init method of new enclosed_node.” In Python, we
        1) create dictionaries for nodes/edges/subgraphs
        2) if enclosed_node => set subgraph seq
        3) if root or has_attrs => agraphattr_init(g)
        4) agmethod_init(g, g)
        """
        parent = self.parent  # agparent(g)
        if parent is not None:
            # increment enclosed_node's seq for AGRAPH
            seq = agnextseq(parent, ObjectType.AGGRAPH)
            self.seq = seq
            # store subgraph in enclosed_node.subgraphs
            parent.subgraphs[self.name] = self
        else:
            # main enclosed_node
            self.seq = 0

        # we skip attribute logic for brevity

        # call agmethod_init(g, g)
        # no-op or minimal
        return self

    def agrecord_callback(self, obj: Union['Graph', 'Node', 'Edge'], callback_type: GraphEvent, state):
        """
        Records a callback of a specific type for an object.

        :param obj: The enclosed_node object to associate with the callback.
        :param callback_type: The type of the callback (e.g., 'initialize').
        :param state: The state associated with the callback.
        """
        # if callback_type == GraphEvent.INITIALIZE:
        #     if isinstance(obj, Graph):
        #         cb = lambda g: agerr(Agerrlevel.AGINFO, f"[Initialize Callback] Initializing enclosed_node '{obj.name}' with state '{state}'.")
        #     elif isinstance(obj, Node):
        #         cb = lambda g: agerr(Agerrlevel.AGINFO, f"[Initialize Callback] Initializing node '{obj.name}' in enclosed_node '{g.name}' with state '{state}'.")
        #     elif isinstance(obj, Edge):
        #         cb = lambda g: agerr(Agerrlevel.AGINFO, f"[Initialize Callback] Initializing edge '{obj.key}' from '{obj.tail.name}' to '{obj.head.name}' with state '{state}'.")
        #     else:
        #         cb = None
        # else:
        #     cb = None
        #
        # if cb:
        #     self.clos.register_callback(callback_type, cb)
        cb = None
        if callback_type == GraphEvent.INITIALIZE:
            if isinstance(obj,  Graph):
                cb = lambda:  print(f"[Initialize Callback] Initializing enclosed_node '{obj.name}' with state '{state}'.")
            elif isinstance(obj, Node):
                cb = lambda: print(f"[Initialize Callback] Initializing node '{obj.name}' in enclosed_node '{obj.parent.name}' with state '{state}'.")
            elif isinstance(obj, Edge):
                cb = lambda: print(f"[Initialize Callback] Initializing edge '{obj.key}' from '{obj.tail.name}' to '{obj.head.name}' with state '{state}'.")
        elif callback_type == GraphEvent.MODIFY:
            if isinstance(obj,  Graph):
                cb = lambda: print(f"[Modify Callback] Modifying enclosed_node '{obj.name}' with state '{state}'.")
            elif isinstance(obj, Node):
                cb = lambda: print(f"[Modify Callback] Modifying node '{obj.name}' in enclosed_node '{obj.parent.name}' with state '{state}'.")
            elif isinstance(obj, Edge):
                cb = lambda: print(f"[Modify Callback] Modifying edge '{obj.key}' from '{obj.tail.name}' to '{obj.head.name}' with state '{state}'.")
        elif callback_type == GraphEvent.DELETION:
            if isinstance(obj, Graph):
                cb = lambda: print(f"[Deletion Callback] Deleting enclosed_node '{obj.name}' with state '{state}'.")
            elif isinstance(obj, Node):
                cb = lambda: print(f"[Deletion Callback] Deleting node '{obj.name}' in enclosed_node '{obj.parent.name}' with state '{state}'.")
            elif isinstance(obj, Edge):
                cb = lambda: print(f"[Deletion Callback] Deleting edge '{obj.key}' from '{obj.tail.name}' to '{obj.head.name}' with state '{state}'.")
        if cb:
            self.clos.register_callback(callback_type, cb)

    def agmethod_init(self, obj: Union['Graph', 'Node', 'Edge']):  # from /cgraph/obj.c
        """
        Initializes callbacks for a enclosed_node object based on the callback system state.
        Equivalent to the C 'agmethod_init' function.

        :param obj: The enclosed_node object (Graph, Node, or Edge) to initialize.
        """
        if self.clos.callbacks_enabled:
            if self.clos.cb:
                self.aginitcb(obj, self.clos.cb)
            else:
                agerr(Agerrlevel.AGINFO, "[Graph] Callback stack 'cb' is not set.")
        else:
            # Record the initialize callback
            cb_initialize = GraphEvent.INITIALIZE
            self.agrecord_callback(obj, cb_initialize, None)

    def init_local_attr_values(self):
        """
        Like 'agmakeattrs' in the C code, ensure we have attribute
        storage for each declared symbol relevant to AGRAPH.
        """
        # For each sym in self.attr_dict_g, set to default if we have no value
        for name, value in self.attr_dict_g.items():
            if self.attr_record.get(name) is None:
                self.attr_record[name] = value

    def add_subgraph(self, name: str, create: bool = True) -> Optional['Graph']:
        if name in self.subgraphs:
            agerr(Agerrlevel.AGWARN, f"Subgraph with name '{name}' already exists in {self.name}.")
            return self.subgraphs[name]
        if create:
            sgr = Graph(name=name, description=self.desc,
                        disc=self.disc, directed=self.desc.directed,
                        strict=self.desc.strict, parent=self, no_loop=self.desc.no_loop)
            sgr.is_main_graph = False
            self.subgraphs[name] = sgr
            if sgr.id in self.id_to_subgraph.keys():
                agerr(Agerrlevel.AGWARN, f"Subgraph with name '{name}' already exists in self.id_to_subgraph.")
            self.id_to_subgraph[sgr.id] = sgr
            self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, sgr)
            # This is done in the enclosed_node init method
            # self.disc.idregister(self.clos, ObjectType.AGGRAPH, sgr)
            # agregister(self, ObjectType.AGGRAPH, sg)  # In C, they'd register the subgraph
            return sgr
        return None

    def agmapnametoid(self, n_name: str, reserve: bool = False) -> Optional[int]:

        # t: ObjectType, n_name, createflag=True):

        """
        Maps a subgraph name to a unique ID. If reserve is True, reserves the ID.

        :param n_name: The name of the subgraph.
        :param reserve: Flag indicating whether to reserve the ID.
        :return: The unique ID if mapping is successful, else None.
        """
        if n_name in self.subgraphs.keys():
            return self.subgraphs[n_name].id

        if reserve:
            id_ = self.disc.map(self.clos, ObjectType.AGGRAPH, n_name, createflag=False)

            self.subgraphs[n_name].id = id_
            # self.subgraph_name_to_id[n_name] = id_
            # self._id_counter = id_  #  + 1
            agerr(Agerrlevel.AGINFO, f"[Agraph] Reserved ID '{id_}' for subgraph '{n_name}'.")
            return id_
        else:
            return None

    def add_node(self, n_name: str, create: bool = True) -> Optional["Node"]:
        """
        Equivalent to agnode(g, name, createflag).
        :param n_name: The name of the node.
        :param create: If True, create the node if it does not exist.
        :return: The created or existing Node object if successful, else None.
        """
        if n_name in self.nodes:
            return_node = self.nodes[n_name]
        elif create:
            node_id = self.disc.map(self.clos, ObjectType.AGNODE, n_name, createflag=create)
            # node_id = agmapnametoid(self, ObjectType.AGNODE, n_name, createflag=True)
            if node_id is None:
                agerr(Agerrlevel.AGERR, f"Error: Failed to map name '{n_name}' to ID.")
                return None
            seq = self.get_next_sequence(ObjectType.AGNODE)

            new_n = Node(name=n_name, graph=self, id_=node_id, root=self.get_root(), seq=seq)

            if not self.is_main_graph:
                real_node = self.add_subgraph_node(self, new_n, create)

            self.nodes[n_name] = new_n
            self.disc.idregister(self.clos, ObjectType.AGNODE, new_n)
            new_n.set_compound_data("centrality", self.compute_centrality(new_n))
            new_n.set_compound_data("rank", 0)  # Example initialization
            # Invoke node added callbacks
            self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, new_n)

            return_node = self.nodes[n_name]
        else:
            return_node = None
        return return_node

    def agdelnode(self, nn):
        self.delete_node(nn)

    def delete_node(self, node_to_delete: 'Node'):
        """
        Deletes a node from the enclosed_node, along with its associated edges
        and subgraph if it's a compound node.
        It does not delete the node itself, just the linkage to the Graph

        :param node_to_delete: The Node object to delete.
        """
        # 1. Validate that the node exists in the enclosed_node

        if node_to_delete.name not in self.nodes:
            agerr(Agerrlevel.AGWARN, f"[Graph] Node '{node_to_delete}' does not exist in enclosed_node '{self.name}'.")
            return

        # Even though nodes.outedges and nodes.inedges are already lists there is a copy made for each here.
        # Using list(node.outedges) and list(node.inedges) creates copies of the edge lists which is crucial
        # because deleting edges modifies the original lists, preventing runtime errors like
        #  "list changed size during iteration."

        # 2. Delete all outgoing edges
        for edge_copy in list(node_to_delete.outedges):
            self.delete_edge(edge_copy)

        # 3. Delete all incoming edges
        for edge_copy in list(node_to_delete.inedges):
            self.delete_edge(edge_copy)

        # 4. If the node is a compound node, delete its subgraph
        # Purpose: Checks if the node is a compound node (i.e., it encapsulates a subgraph).
        #          If so, it proceeds to delete the subgraph.
        # Recursive Deletion: Calls the agclose method on the subgraph to ensure that
        #          all internal nodes and edges are also deleted.
        # Cleanup: Resets the subgraph reference and the is_compound flag to maintain data integrity.
        if node_to_delete.compound_node_data.is_compound and node_to_delete.compound_node_data.subgraph:
            if node_to_delete.compound_node_data.subgraph.name in self.subgraphs:
                agerr(Agerrlevel.AGINFO, f"Deleting subgraph {node_to_delete.name} from subgraphs in {self.name}.")
                del self.subgraphs[node_to_delete.compound_node_data.subgraph.name]
            agerr(Agerrlevel.AGINFO, f"Deleting subgraph associated with compound node '{node_to_delete.name}'.")
            node_to_delete.compound_node_data.subgraph.agclose()  # Recursively close the subgraph
            node_to_delete.compound_node_data.subgraph = None
            node_to_delete.compound_node_data.is_compound = False

        # 5. Remove the node from the enclosed_node's node dictionary
        del self.nodes[node_to_delete.name]

        # 6. Free the node's ID using the ID discipline
        self.disc.free(self.clos, ObjectType.AGNODE, node_to_delete.id)

        # 7. Reset the node's compound node to default
        node_to_delete.compound_node_data = CompoundNode()

        # 8. Invoke node deleted callbacks
        self.clos.invoke_callbacks(GraphEvent.NODE_DELETED, node_to_delete)

        agerr(Agerrlevel.AGINFO, f"[Graph] Node '{node_to_delete.name}' and its associated data have been deleted successfully.")
        return True

        # -------- Subgraph Management Methods --------

    def agfreeid(self, obj_type: ObjectType, old_id: int):  # from /cgraph/id.c
        """
        Frees an internal ID associated with a enclosed_node object.

        Not really needed in Python but added here for completeness.

        :param obj_type: The type of object ('AGRAPH', 'AGNODE', 'AGEDGE').
        :param old_id: The ID to free.
        """
        if obj_type == ObjectType.AGGRAPH:
            g = get_root_graph(self)
            sg_list = gather_all_subgraphs(g)
            for sgr in sg_list:
                if sgr.id == old_id:
                    self.delete_subgraph(sgr)
                    break
        elif obj_type == ObjectType.AGNODE:
            found_node = self.find_node_by_id(old_id)
            if found_node is None:
                agerr(Agerrlevel.AGWARN, f"The Node with id = {old_id} does not exist in enclosed_node '{self.name}'.")
            else:
                self.delete_node(found_node)
        elif obj_type == ObjectType.AGEDGE:
            found_edge = self.find_edge_by_id(old_id)
            if found_edge is None:
                agerr(Agerrlevel.AGWARN, f"The Edge with id = {old_id} does not exist in enclosed_node '{self.name}'.")
            else:
                self.delete_edge(found_edge)


    def agexpose(self, cmpnode: 'Node') -> bool:
        """
        Exposes a collapsed (hidden) compound node by reintegrating its subgraph into the parent graph.
        Steps:
          1. Reinsert the compound node's subgraph into the parent graph's subgraphs.
          2. Restore nodes from the parent's cmp_graph_data.hidden_node_set that belong to the subgraph.
          3. Restore any hidden edges from cmp_graph_data.hidden_edge_set.
          4. For each edge in the parent graph incident to cmpnode, check its compound edge stack.
             If the top connection points to cmpnode, pop it and re-splice the edge so that its endpoint is
             restored to its original node.
          5. Mark cmpnode as uncollapsed.

        :param cmpnode: The compound node to expose.
        :return: True if the operation succeeds; otherwise False.
        """
        if cmpnode.compound_node_data is None:
            agerr(Agerrlevel.AGERR, f"[Graph] Node '{cmpnode.name}' has no compound node data.")
            return False

        if not cmpnode.compound_node_data.is_compound or not cmpnode.compound_node_data.collapsed:
            agerr(Agerrlevel.AGERR, f"[Graph] Node '{cmpnode.name}' is not compound or is not collapsed.")
            return False

        subg: 'Graph' = cmpnode.compound_node_data.subgraph
        if subg is None:
            agerr(Agerrlevel.AGINFO, f"[Graph] Node '{cmpnode.name}' does not have an associated subgraph.")
            return False

        parent_graph: 'Graph' = cmpnode.parent

        # (1) Reinsert the subgraph into parent's subgraph dictionary.
        parent_graph.subgraphs[subg.name] = subg
        self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, subg)

        # (2) Restore nodes from the hidden set.
        for node_name in list(parent_graph.cmp_graph_data.hidden_node_set.keys()):
            node_obj = parent_graph.cmp_graph_data.hidden_node_set[node_name]
            if node_obj in subg.nodes.values():
                parent_graph.nodes[node_name] = node_obj
                del parent_graph.cmp_graph_data.hidden_node_set[node_name]
                self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, node_obj)
                agerr(Agerrlevel.AGINFO,
                      f"[Graph] Node '{node_name}' from subgraph '{subg.name}' restored to graph '{parent_graph.name}'.")

        # (3) Restore edges from the hidden edge set.
        for edge_key, edge_obj in list(parent_graph.cmp_graph_data.hidden_edge_set.items()):
            if edge_key in subg.edges:
                parent_graph.edges[edge_key] = edge_obj
                del parent_graph.cmp_graph_data.hidden_edge_set[edge_key]
                self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, edge_obj)
                head, tail, name = edge_key
                agerr(Agerrlevel.AGINFO,
                      f"[Graph] Edge '{name}' from subgraph '{subg.name}' restored to graph '{parent_graph.name}'.")

        # (4) Re-splice edges incident to cmpnode.
        for key, edge in list(parent_graph.edges.items()):
            if edge.tail == cmpnode or edge.head == cmpnode:
                # Process each stack (for in-edges and out-edges)
                for i in (0, 1):
                    stk = edge.cmp_edge_data.stack[i]
                    if stk.is_empty():
                        continue
                    top_item = stk.top()
                    if top_item.to_node == cmpnode:
                        # Determine which endpoint to restore:
                        if edge.head == cmpnode:
                            # cmpnode was used as the head; restore original head.
                            agsplice(edge, top_item.from_node)
                        elif edge.tail == cmpnode:
                            # cmpnode was used as the tail; restore original tail.
                            agsplice(edge, top_item.from_node)
                        stk.pop()
                        self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, edge)
                        agerr(Agerrlevel.AGINFO,
                              f"[Graph] Edge '{edge.name}' re-spliced to restore connection from '{top_item.from_node.name}'.")
        # (5) Mark the compound node as uncollapsed.
        cmpnode.compound_node_data.collapsed = False
        cmpnode.collapsed = False
        agerr(Agerrlevel.AGINFO, f"[Graph] Compound node '{cmpnode.name}' is now exposed.")
        return True


    #########################
    # This version uses a different method for collapse and expose
    # In this version the subgraph is carried in the node subgraph itself. It uses the root graph to
    # carry the node data that is to be exposed. In addition, it uses the following relation:
    # This node called 'cmpnode', has a subgraph associated with it carried in the field
    # cmpnode.subgraph  (reference to the subgraph that contains this node)
    # The main graph will contain the name of this subgraph in a dictionary of subgraphs. It's referenced by:
    # self.subgraphs[cmpnode.subgraph.name]  (The subgraph carried in the main graph)
    # Within that subgraph, the nodes that contained (have been moved) are in the dictionary
    # self.subgraphs[cmpnode.subgraph.name].nodes (Contains all the subgraph nodes)
    # To restore these nodes, they are checked to determine if they exist in the main graph and if not then they
    # are added back to the main graph.
    # The same process is repeated with the edges.
    # def agexpose(self, cmpnode: 'Node') -> bool:
    #     """
    #     Exposes a collapsed subgraph node, reintegrating its subgraph into the main enclosed_node.
    #
    #     :param cmpnode: The node representing the collapsed subgraph to expose.
    #     :return: True if exposure was successful, False otherwise.
    #     """
    #     # Validation: Check if cmpnode is a collapsed subgraph node
    #     rec = cmpnode.compound_node_data
    #     if rec is None or not rec.collapsed:
    #         agerr(Agerrlevel.AGINFO, f"[Graph] Node '{cmpnode.name}' is not a hidden/collapsed subgraph node.")
    #         return False  # Not collapsed
    #
    #     if cmpnode.subgraph is None:
    #         agerr(Agerrlevel.AGINFO, f"[Graph] Node '{cmpnode.name}' does not have a subgraph node.")
    #         return False  # Compound
    #
    #     parent_graph: 'Graph' = cmpnode.subgraph
    #
    #     # Integration: Add the subgraph to the main enclosed_node's subgraphs
    #     if parent_graph.name not in self.subgraphs:
    #         self.subgraphs[parent_graph.name] = parent_graph
    #         parent_graph.enclosed_node = self  # Set the enclosed_node reference
    #         self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, parent_graph)
    #         agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{parent_graph.name}' has been exposed and integrated into enclosed_node '{self.name}'.")
    #
    #     # Node Re-insertion: Add subgraph's nodes to the main enclosed_node
    #     for n_node in parent_graph.nodes.values():
    #         if n_node.name not in self.nodes:
    #             self.nodes[n_node.name] = n_node
    #             n_node.enclosed_node = self
    #             self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, n_node)
    #             agerr(Agerrlevel.AGINFO, f"[Graph] Node '{n_node.name}' from subgraph '{parent_graph.name}' has been added to enclosed_node '{self.name}'.")
    #
    #     # Edge Re-insertion: Add subgraph's edges to the main enclosed_node
    #     for n_edge in parent_graph.edges.values():
    #         key = (n_edge.tail.name, n_edge.head.name, n_edge.key)
    #         if key not in self.edges:
    #             self.edges[key] = n_edge
    #             self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, n_edge)
    #             agerr(Agerrlevel.AGINFO, f"[Graph] Edge '{n_edge.key}' from subgraph '{parent_graph.name}' has been added to enclosed_node '{self.name}'.")
    #
    #     # Edge Reconnection: Reconnect edges associated with the collapsed subgraph node
    #     # Assuming that cmpnode.saved_connections contains tuples of (other_node, edge)
    #     for other_node, n_edge in cmpnode.saved_connections:
    #         if n_edge.tail == cmpnode:
    #             # Reconnect tail to the saved 'from' node
    #             agerr(Agerrlevel.AGINFO, f"[Graph] Reconnecting edge '{n_edge.key}' from '{cmpnode.name}' to '{n_edge.head.name}' back to '{other_node.name}'.")
    #             # Remove the old edge from main enclosed_node
    #             old_key = (cmpnode.name, n_edge.head.name, n_edge.key)
    #             if old_key in self.edges:
    #                 del self.edges[old_key]
    #             # Update edge's tail to the original node
    #             n_edge.tail = other_node
    #             # Add the updated edge back to the main enclosed_node
    #             new_key = (other_node.name, n_edge.head.name, n_edge.key)
    #             self.edges[new_key] = n_edge
    #             self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, n_edge)
    #             agerr(Agerrlevel.AGINFO, f"[Graph] Edge '{n_edge.key}' has been reconnected from '{other_node.name}' to '{n_edge.head.name}'.")
    #
    #         elif n_edge.head == cmpnode:
    #             # Reconnect head to the saved 'to' node
    #             agerr(Agerrlevel.AGINFO, f"[Graph] Reconnecting edge '{n_edge.key}' from '{n_edge.tail.name}' to '{cmpnode.name}' back to '{other_node.name}'.")
    #             # Remove the old edge from main enclosed_node
    #             old_key = (n_edge.tail.name, cmpnode.name, n_edge.key)
    #             if old_key in self.edges:
    #                 del self.edges[old_key]
    #             # Update edge's head to the original node
    #             n_edge.head = other_node
    #             # Add the updated edge back to the main enclosed_node
    #             new_key = (n_edge.tail.name, other_node.name, n_edge.key)
    #             self.edges[new_key] = n_edge
    #             self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, n_edge)
    #             agerr(Agerrlevel.AGINFO, f"[Graph] Edge '{n_edge.key}' has been reconnected from '{n_edge.tail.name}' to '{other_node.name}'.")
    #
    #     # Clear saved connections as they have been restored
    #     cmpnode.saved_connections.clear()
    #
    #     # Update State: Mark the subgraph as uncollapsed
    #     cmpnode.collapsed = False
    #     agerr(Agerrlevel.AGINFO, f"[Graph] Node '{cmpnode.name}' has been marked as uncollapsed.")
    #
    #     return True


    def agecollapse(self, sgr_name: str) -> bool:
        """
        Collapses a subgraph, hiding its nodes and saving connections.

        :param sgr_name: The name of the subgraph to collapse.
        :return: True if collapse was successful, False otherwise.
        """
        if sgr_name not in self.subgraphs:
            agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{sgr_name}' does not exist.")
            return False

        subg = self.subgraphs[sgr_name]
        compound_node_name = f"{sgr_name}_cmp"
        cmpnode = self.add_node(compound_node_name)  # Node representing the subgraph
        # cmpnode = self.add_node(sgr_name)
        cmpnode.collapsed = True
        cmpnode.subgraph = subg

        # Save connections
        for n_edge in list(cmpnode.inedges + cmpnode.outedges):
            if n_edge.tail == cmpnode:
                other_node = n_edge.head
                cmpnode.saved_connections.append((other_node, n_edge))
            elif n_edge.head == cmpnode:
                other_node = n_edge.tail
                cmpnode.saved_connections.append((other_node, n_edge))
            # Remove the edge from the main enclosed_node
            self.delete_edge(n_edge)

        agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{sgr_name}' has been collapsed.")
        self.has_cmpnd = True
        return True

    # -------- Helper Method to Update 'has_cmpnd' Flag --------

    def update_has_cmpnd_flag(self):
        """
        Updates the 'has_cmpnd' flag based on the current state of subgraphs.
        """
        self.has_cmpnd = any(
            self.nodes.get(subg.name, Node(name=subg.name, graph=self)).collapsed
            for subg in self.subgraphs.values()
            if subg.name in self.nodes
        )
        agerr(Agerrlevel.AGINFO, f"[Graph] Graph '{self.name}' has compound subgraphs: {self.has_cmpnd}")

    def aghide(self, cmpnode: 'Node') -> bool:
        """
        Hides a collapsed subgraph node, reintegrating its subgraph into the graph enclosed_node.
        This involves:
          1. Splicing edges from external nodes so that edges incident to nodes of the subgraph
             now connect to the compound node.
          2. Moving the subgraph’s nodes into the graph enclosed_node’s hidden set.
          3. Removing the subgraph from the graph enclosed_node.
          4. Marking the compound node as collapsed.

        :param cmpnode: The node representing the collapsed subgraph to hide.
        :return: True if hiding was successful, False otherwise.
        :raises ValueError: If the provided node is invalid or not a collapsed compound node.
        """
        # 1) Validate 'cmpnode' is truly a compound node with a subgraph
        if not isinstance(cmpnode, Node):
            agerr(Agerrlevel.AGWARN, f"cmpnode must be a Node; got {type(cmpnode)}")
            return False
        rec = cmpnode.compound_node_data
        if rec is None:
            agerr(Agerrlevel.AGWARN, f"The Node '{cmpnode.name}' is does not have compound_node_data.")
            return False  # Not a compound node.

        if rec.subgraph is None:
            agerr(Agerrlevel.AGWARN, f"The Node '{cmpnode.name}' is not a compound node.")
            return False  # Not a compound node.

        # In our design, we expect the node to be NOT collapsed before hiding.
        # (Some designs use 'collapsed' to indicate that the subgraph is hidden.)
        if rec.collapsed:
            agerr(Agerrlevel.AGWARN, f"The Node '{cmpnode.name}' is already collapsed/ hidden subgraph node.")
            return False  # Already hidden/collapsed.

        # My subgraph
        subg = rec.subgraph
        # My immediate parent graph
        parent_graph = cmpnode.parent
        # The tippy top graph
        root = parent_graph.get_root(parent_graph)

        # 2) If cmpnode accidentally appears in its own subgraph, remove it
        if cmpnode.name in subg.nodes:
            del subg.nodes[cmpnode.name]

        # 3) For each node 'n' inside the subgraph, check if that node appears in the root.
        #    handle both "external" edges (splice them) and
        #    "internal" edges (fully hide them).

        # If so, then for each edge in the root that is incident to that node and is external to subg,
        # splice the edge so that it now connects to cmpnode.
        counter = 0
        for nname, rootn in list(root.nodes.items()):
            # rootn = root.nodes.get(nname)
            # if not rootn:
            #     continue
            # for key, edge in list(root.edges.items()):
            #     # Check if the edge is incident to the node.
            #     #  check for onde of these  -->(root)  or (root)-->
            #     if edge.tail == rootn or edge.head == rootn:
            #         # Check if the edge is external to the subgraph:
            #         # If it's "external" to subg, splice to cmpnode
            #         if (edge.tail.name not in subg.nodes) or (edge.head.name not in subg.nodes):
            #             # Save the original connection for potential later restoration.
            #             # (Assume stackpush and save_stack_of are helper functions defined elsewhere.)
            #             # For example:
            #             stack = save_stack_of(edge, rootn)
            #             stackpush(stack, rootn, cmpnode)
            #             # And splice the edge so that its endpoint becomes cmpnode.
            #             agsplice(edge, cmpnode)
            # We'll iterate over a snapshot of the root's edges
            for (tail_name, head_name, ekey), edge in list(root.edges.items()):
                # Check if this edge is incident on 'rootn'
                if edge.tail == rootn or edge.head == rootn:
                    # Is it an "external" edge? (One endpoint in subg, the other endpoint outside subg)
                    tail_in_subg = (edge.tail.name in subg.nodes)
                    head_in_subg = (edge.head.name in subg.nodes)
                    both_in_subg = (tail_in_subg and head_in_subg)
                    neither_in_subg = (not tail_in_subg and not head_in_subg)
                    if neither_in_subg:
                        print(f"Skipping splice of  {edge.name}, {edge.tail.name}, {edge.name}")
                        continue
                    # TODO Check whether to completely remove the edges that cross into the hidden node.
                    # If its to be hidden when crossing the delete it here.
                    parent_graph.cmp_graph_data.hidden_edge_set[(tail_name, head_name, ekey)] = edge
                    del root.edges[(tail_name, head_name, ekey)]

                    if both_in_subg:
                        # 3b) "internal" edge => hide it completely
                        # remove from root.edges, store in the subgraph hidden_edge_set
                        subg.cmp_graph_data.hidden_edge_set[(tail_name, head_name, ekey)] = edge
                        del root.edges[(tail_name, head_name, ekey)]
                    else:
                        # The edge crosses the subgraph boundary => splice to cmpnode
                        # Save original connection
                        counter += 1
                        # for k in self.edges.keys():
                        #     print(f"{counter}: {self.edges[k].head.name}, {self.edges[k].tail.name}, {self.edges[k].name}")
                        # if counter == 4:
                        #     pass
                        stack = save_stack_of(edge, rootn)
                        stackpush(stack, rootn, cmpnode)
                        agsplice(edge, cmpnode)  # re-registers in root.edges with updated tail/head

        # 4) Hide the subgraph's nodes from enclosed_node's perspective
        #    i.e., move them into enclosed_node's hidden_node_set, remove from parent_graph.nodes
        pgdata = parent_graph.cmp_graph_data
        for nname, nobj in list(subg.nodes.items()):
            pgdata.hidden_node_set[nname] = nobj
            # Optionally remove the node from enclosed_node's nodes if it appears there.
            if nname in parent_graph.nodes:
                del parent_graph.nodes[nname]

        # 5) Remove the subgraph itself from the enclosed_node's subgraphs
        if subg.name in parent_graph.subgraphs:
            del parent_graph.subgraphs[subg.name]
            self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_DELETED, subg)
            agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{subg.name}' has been hidden from enclosed_node '{parent_graph.name}'.")

        # 6) Mark the compound node as collapsed
        rec.collapsed = True
        cmpnode.collapsed = True  # if you also track it at the Node level
        agerr(Agerrlevel.AGINFO, f"[Graph] Compound node '{cmpnode.name}' has been marked as collapsed (hidden).")
        return True

    # -------- Hiding Compound Node Method --------
    # def aghide(self, cmpnode: 'Node') -> bool:
    #     """
    #     Hides a collapsed subgraph node, reintegrating its subgraph into the graph enclosed_node.
    #     This involves:
    #         1. Remapping edges connected to the compound node.
    #         2. Hiding nodes within the subgraph.
    #         3. Hiding the subgraph itself.
    #
    #     :param cmpnode: The node representing the collapsed subgraph to hide.
    #     :return: True if hiding was successful, False otherwise.
    #     :raises ValueError: If the provided node is invalid or not a collapsed subgraph.
    #     """
    #     if not isinstance(cmpnode, Node):
    #         agerr(Agerrlevel.AGWARN, f"Can only hide Node objects. {cmpnode} is not a Node object.")
    #         return False
    #     rec = cmpnode.compound_node_data
    #     if rec.subgraph is None:
    #         agerr(Agerrlevel.AGWARN, f"The Node '{cmpnode.name}' does not have a compound subgraph node.")
    #         return False  # Not a compound node at all
    #
    #     if rec.collapsed:
    #         agerr(Agerrlevel.AGWARN, f"The Node '{cmpnode.name}' is a already a collapsed subgraph node.")
    #         return False
    #
    #     subg = rec.subgraph
    #     parent_graph = cmpnode.enclosed_node # Assuming this method is called on the graph enclosed_node
    #     root = parent_graph.get_root(parent_graph)
    #
    #     # 1) If by chance 'cmpnode' is inside its own subgraph, remove it
    #     if cmpnode.name in subg.nodes:
    #         del subg.nodes[cmpnode.name]
    #
    #     # # 2) For each node n in subg, "splice" edges if they appear in root
    #     # for nname, nobj in list(subg.nodes.items()):
    #     #     rootn = root.nodes.get(nname)
    #     #     if not rootn:
    #     #         continue
    #     #     # For each edge e from or to rootn, we "splice" to cmpnode
    #     #     for (sname, dname, ename), eobj in list(root.edges.items()):
    #     #         if eobj.tail == rootn or eobj.head == rootn:
    #     #             # If it's "external" to subg, splice to cmpnode
    #     #             if sname not in subg.nodes or dname not in subg.nodes:
    #     #                 rec.stackpush(save_stack_of(eobj, rootn), rootn, cmpnode)
    #     #                 agsplice(eobj, cmpnode)
    #
    #
    #     # Remap Edges: Redirect edges connected to cmpnode back to original nodes
    #     for other_node, n_edge in cmpnode.saved_connections:
    #         if n_edge.tail == cmpnode:
    #             # Reconnect tail to the original node
    #             agerr(Agerrlevel.AGINFO, 
    #                 f"[Graph] Reconnecting edge '{n_edge.key}' from '{cmpnode.name}' to '{n_edge.head.name}' back to '{other_node.name}'.")
    #             # Remove the old edge from main enclosed_node
    #             old_key = (cmpnode.name, n_edge.head.name, n_edge.key)
    #             if old_key in self.edges:
    #                 del self.edges[old_key]
    #             # Update edge's tail to the original node
    #             n_edge.tail = other_node
    #             # Add the updated edge back to the main enclosed_node
    #             new_key = (other_node.name, n_edge.head.name, n_edge.key)
    #             self.edges[new_key] = n_edge
    #             self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, n_edge)
    #             agerr(Agerrlevel.AGINFO, 
    #                 f"[Graph] Edge '{n_edge.key}' has been reconnected from '{other_node.name}' to '{n_edge.head.name}'.")
    #
    #         elif n_edge.head == cmpnode:
    #             # Reconnect head to the original node
    #             agerr(Agerrlevel.AGINFO, 
    #                 f"[Graph] Reconnecting edge '{n_edge.key}' from '{n_edge.tail.name}' to '{cmpnode.name}' back to '{other_node.name}'.")
    #             # Remove the old edge from main enclosed_node
    #             old_key = (n_edge.tail.name, cmpnode.name, n_edge.key)
    #             if old_key in self.edges:
    #                 del self.edges[old_key]
    #             # Update edge's head to the original node
    #             n_edge.head = other_node
    #             # Add the updated edge back to the main enclosed_node
    #             new_key = (n_edge.tail.name, other_node.name, n_edge.key)
    #             self.edges[new_key] = n_edge
    #             self.clos.invoke_callbacks(GraphEvent.EDGE_ADDED, n_edge)
    #             agerr(Agerrlevel.AGINFO, 
    #                 f"[Graph] Edge '{n_edge.key}' has been reconnected from '{n_edge.tail.name}' to '{other_node.name}'.")
    #
    #     # Clear saved connections as they have been restored
    #     cmpnode.saved_connections.clear()
    #
    #     # Hide Nodes: Remove all nodes in the subgraph from the graph enclosed_node
    #     for n_node in list(subg.nodes.values()):
    #         self.delete_node(n_node)
    #
    #     # Hide Subgraph: Remove the subgraph from the graph enclosed_node's subgraphs
    #     if subg.name in self.subgraphs:
    #         del self.subgraphs[subg.name]
    #         self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_DELETED, subg)
    #         agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{subg.name}' has been hidden from enclosed_node '{self.name}'.")
    #
    #     # Update State: Mark the compound node as uncollapsed
    #     cmpnode.collapsed = False
    #     # Update 'has_cmpnd' flag using the helper method
    #     self.update_has_cmpnd_flag()
    #
    #     agerr(Agerrlevel.AGINFO, f"[Graph] Node '{cmpnode.name}' has been marked as uncollapsed.")
    #     agerr(Agerrlevel.AGINFO, f"[Graph] Graph '{self.name}' has compound subgraphs: {self.has_cmpnd}")
    #
    #     return True

    def delete_subgraph(self, sgr: 'Graph') -> bool:
        """
        Deletes a subgraph from the enclosed_node.

        :param sgr: The Graph object representing the subgraph to delete.

        Returns False if the subgraph was not deleted else True

        """
        if sgr.name not in self.subgraphs:
            agerr(Agerrlevel.AGWARN, f"Subgraph '{sgr.name}' does not exist in the enclosed_node.")
            return False

        # Recursively close the subgraph, and Remove the subgraph
        sgr.agclose()

        # Recursively delete all nodes and edges in the subgraph
        for n_node in list(sgr.nodes.values()):
            self.delete_node(n_node)

        deletion = False
        if sgr.id not in self.id_to_subgraph.keys():
            agerr(Agerrlevel.AGERR, f"Subgraph '{sgr.id}' does not exist in the self.id_to_subgraph.")
        else:
            self.id_to_subgraph.pop(sgr.id, None)
            deletion = True

        # Remove subgraph from enclosed_node
        if sgr.name not in self.subgraphs.keys():
            agerr(Agerrlevel.AGERR, f"Subgraph '{sgr.name}' does not exist in the self.subgraphs.")
        else:
            self.subgraphs.pop(sgr.name, None)
            deletion = True

        # Invoke subgraph deleted callbacks
        if deletion:
            self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_DELETED, sgr)

        agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{sgr.name}' has been  deleted successfully.")
        return True

    def expose_subgraph(self, sgr_name: str) -> Optional['Graph']:
        """
        Creates and exposes a subgraph within the current enclosed_node.
        Ensures that a corresponding Node exists for the subgraph.

        :param sgr_name: The name of the subgraph to create and expose.
        :return: The created subgraph Graph object if successful, else None.
        """
        if sgr_name in self.subgraphs:
            agerr(Agerrlevel.AGWARN, f"[Graph] Subgraph '{sgr_name}' already exists.")
            return self.subgraphs[sgr_name]

        # Create a corresponding node for the subgraph
        cmpnode = self.add_node(sgr_name)
        if not cmpnode:
            agerr(Agerrlevel.AGERR, f"[Graph] Failed to create node for subgraph '{sgr_name}'.")
            return None

        # Create a new subgraph
        sgraph = Graph(name=sgr_name, directed=self.directed, root=self.root, parent=self)
        sgraph.parent = self  # Set the enclosed_node reference

        # Associate the subgraph with the compound node
        cmpnode.subgraph = sgraph

        # Add the subgraph to the current enclosed_node's subgraphs
        if sgraph.name == sgr_name:
            pass
        self.subgraphs[sgr_name] = sgraph

        # Invoke subgraph added callbacks
        self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, sgraph)

        agerr(Agerrlevel.AGWARN, f"[Graph] Subgraph '{sgr_name}' has been exposed "
                                 f"and integrated into enclosed_node '{self.name}'.")
        return sgraph


    def create_subgraph(self, name: str, enclosed_node: Optional['Node'] = None) -> Optional['Graph']:
        """
        Create a new subgraph named 'name' within this graph.
        If 'parent' is provided, link the new subgraph to that node
        (forming a compound node). Also move or share relevant nodes/edges,
        so they appear within the subgraph if desired.

        :param name: The name of the new subgraph.
        :param enclosed_node: An optional Node object that will exist within this subgraph.
        :return: The newly created subgraph object, or None on failure.

        This is how a compound node (subgraph) is created

        """
        # 0) Check if subgraph name already used
        if name in self.subgraphs:
            agerr(Agerrlevel.AGWARN, f"Subgraph '{name}' already exists in '{self.name}'.")
            return self.subgraphs[name]

        # 1) Create the subgraph object
        subg = Graph(
            name=name,
            parent=self,  # Because the parent is self then this will be a compound node
            directed=self.directed,
            strict=self.strict,
            no_loop=self.no_loop,
            root=self.root  # share the same root as the enclosed_node
        )
        # Create a copy because this subgraph will potentially have its closures and descriptions.
        subg.clos = copy(self.clos)
        subg.desc = copy(self.desc)
        subg.desc.maingraph = False

        # 2) Register subg in self.subgraphs
        self.subgraphs[name] = subg

        # If you track subgraphs by ID, also do: self.id_to_subgraph[subg.id] = subg
        # (assuming subg.id is assigned in subg.__init__)

        # 3) If there is a enclosed node => set up compound node logic
        if enclosed_node:
            # (a) Check if it's already compound
            if enclosed_node.compound_node_data.is_compound:
                agerr(Agerrlevel.AGWARN, f"Node '{enclosed_node.name}' is already a compound node.")
                return enclosed_node.compound_node_data.subgraph

            # (b) Mark the node as compound, link to the new subgraph
            enclosed_node.compound_node_data.is_compound = True
            enclosed_node.compound_node_data.subgraph = subg
            enclosed_node.compound_node_data.collapsed = False
            # If you also track subgraph -> node link:
            # subg.cmp_graph_data.node = enclosed_node


            # # (c) Optionally ensure that 'enclosed_node' appears in the new subgraph's node dictionary.
            # In a typical cgraph approach, we do something like:

            # In the aghide method, the subgraph nodes dictionary deletes this node from its nodes dict
            if enclosed_node.name not in subg.nodes:
                subg.nodes[enclosed_node.name] = enclosed_node
                # Or if you prefer removing from the enclosed_node's .nodes:
                #   del self.nodes[enclosed_node.name]
                # (depends on whether you want the node to exist in both places or just subg)
            enclosed_node.set_compound_data("centrality", self.compute_centrality(enclosed_node))

            # (d) If the 'enclosed' node already has edges that you want to appear in subg,
            # you can move or duplicate them:
            for key, edge in list(self.edges.items()):
                # Suppose the edge is wholly internal (both endpoints) to the subgraph,
                # or you specifically want the edge in subg if it touches 'enclosed_node'.
                # Check if edge.tail == enclosed_node or edge.head == enclosed_node, etc.

                MOVE_EDGE_TO_SUBGRAPH = True
                if MOVE_EDGE_TO_SUBGRAPH:
                    if edge.tail == enclosed_node or edge.head == enclosed_node:
                        # Move or copy the edge into subg's .edges
                        subg.edges[key] = edge
                        # Optionally remove from self.edges if you want it only in subg:
                        # del self.edges[key]


        # No enclosed_node node => normal subgraph
        self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, subg)

        return subg

    # def create_subgraph(self, name: str, enclosed_node: Optional['Node'] = None) -> Optional['Graph']:
    #     """
    #     Create a new subgraph named 'name' within this graph.
    #     If 'enclosed_node' is provided, link the new subgraph to that node
    #     to form a 'compound node' relationship.
    #
    #     :param name: The name of the new subgraph.
    #     :param enclosed_node: An optional Node object that will 'own' this subgraph.
    #     :return: The newly created subgraph object.
    #     :raises ValueError: If a subgraph with the same name already exists.
    #     """
    #     # Creating a regular subgraph without associating it with a enclosed_node node
    #     if name in self.subgraphs:
    #         agerr(Agerrlevel.AGWARN, f"Subgraph '{name}' already exists.")
    #         # raise ValueError(f"Subgraph '{name}' already exists in graph '{self.name}'.")
    #         return self.subgraphs[name]
    #
    #     if enclosed_node:
    #         # 1. Check if the enclosed_node node is already a compound node
    #         if enclosed_node.compound_node_data.is_compound:
    #             agerr(Agerrlevel.AGWARN, f"Node '{enclosed_node.name}' is already a compound node.")
    #             return enclosed_node.compound_node_data.subgraph
    #
    #         # 2. Check if the enclosed_node node already has an associated subgraph
    #         if enclosed_node.name in self.subgraphs:
    #             agerr(Agerrlevel.AGWARN, f"Subgraph for node '{enclosed_node.name}' already exists.")
    #             return self.subgraphs[enclosed_node.name]
    #
    #         # 3. Create the internal subgraph
    #         # Note: Here we pass 'enclosed_node=self' because the new subgraph is being created within the current enclosed_node.
    #         # subg = Graph(name=name, enclosed_node=self)
    #         subg = Graph(
    #             name=name,
    #             enclosed_node=self,
    #             directed=self.directed,
    #             strict=self.strict,
    #             no_loop=self.no_loop,
    #             root=self.root  # we share the same root as our enclosed_node
    #         )
    #
    #         # 4. Register the new subgraph in the graph enclosed_node.
    #         # In this design, the enclosed_node's enclosed_node is accessed via enclosed_node.enclosed_node.
    #         # (Typically, enclosed_node.enclosed_node should be the same as self if the enclosed_node node belongs to self.)
    #         if enclosed_node.enclosed_node is not self:
    #             agerr(Agerrlevel.AGERR, f"Subgraph for node '{enclosed_node.enclosed_node.name}' is not the same as {self.name}.")
    #             return None
    #
    #         self.subgraphs[subg.name] = subg
    #         self.id_to_subgraph[subg.id] = subg
    #
    #         # 5. Associate the new subgraph with the enclosed_node node to make it a compound node
    #         enclosed_node.compound_node_data.subgraph = subg
    #         enclosed_node.compound_node_data.is_compound = True
    #         enclosed_node.compound_node_data.collapsed = False  # Default visibility
    #
    #         # 6. (Optional) Update comparison metrics for the enclosed_node node.
    #         # Update comparison metrics if necessary
    #         enclosed_node.set_compound_data("centrality", self.compute_centrality(enclosed_node))
    #         self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, subg)
    #         return subg
    #     else:
    #
    #         subg = Graph(
    #             name=name,
    #             enclosed_node=self,
    #             directed=self.directed,
    #             strict=self.strict,
    #             no_loop=self.no_loop,
    #             root=self.root  # we share the same root as our enclosed_node
    #         )
    #         self.subgraphs[name] = subg
    #         self.id_to_subgraph[subg.id] = subg
    #         self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, subg)
    #         return subg

    def create_subgraph_as_compound_node(self, name: str, compound_node: 'Node') -> Optional['Graph']:
        """
        Creates a subgraph and assigns it to a compound node.

        :param name: The name of the subgraph.
        :param compound_node: The Node to convert into a compound node.
        :return: The created subgraph if successful, else None.
        """
        if compound_node.compound_node_data.is_compound:
            agerr(Agerrlevel.AGWARN, f"Node '{compound_node.name}' is already a compound node.")
            return compound_node.compound_node_data.subgraph

        # Create the subgraph
        sgr = self.create_subgraph(name, enclosed_node=compound_node)
        # Move the existing node into this subgraph
        re_assign = False
        if re_assign:
            compound_node.parent = sgr
            compound_node.compound_node_data.subgraph = sgr
        if sgr:
            # Optionally, set additional comparison data or attributes
            compound_node.set_compound_data("centrality", self.compute_centrality(compound_node))
            self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, sgr)
        return sgr

    # Subgraph functions from /cgraph/subg.c
    def agsubg(self, name: Optional[str], cflag: bool) -> Optional['Graph']:
        """
        Retrieves a subgraph by its name, optionally creating it if it doesn't exist.

        :param name: The name of the subgraph.
        :param cflag: Flag indicating whether to create the subgraph if it doesn't exist.
        :return: The Graph instance if found or created, else None.
        """
        return self.add_subgraph(name, cflag)

    def agidsubg(self, id_: int, cflag: bool) -> Optional['Graph']:
        """
        Retrieves a subgraph by its ID, optionally creating it if it doesn't exist.

        :param id_: The unique identifier of the subgraph.
        :param cflag: Flag indicating whether to create the subgraph if it doesn't exist.
        :return: The Graph instance if found or created, else None.
        """
        subg = self.agfindsubg_by_id(id_)
        if subg is None and cflag:
            if self.agallocid(id_):
                subg = self.localsubg(id_)
        return subg

    def agfindsubg_by_id(self, id_: int) -> Optional['Graph']:
        """
        Finds a subgraph within the enclosed_node by its unique ID.

        :param id_: The unique identifier of the subgraph.
        :return: The Graph instance if found, else None.
        """
        subg = self.id_to_subgraph.get(id_)
        if subg:
            agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph with ID '{id_}' found: '{subg.name}'.")
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph with ID '{id_}' not found.")
        return subg

    def get_or_create_subgraph_by_id(self, subg_id: int, create_if_missing: bool = False) -> Optional['Graph']:
        """
        Retrieves a subgraph by its ID, optionally creating it if it doesn't exist.

        :param subg_id: The unique identifier of the subgraph.
        :param create_if_missing: Flag indicating whether to create the subgraph if it doesn't exist.
        :return: The Agraph instance if found or created, else None.
        """
        subg = self.id_to_subgraph.get(subg_id)
        if subg is None and create_if_missing:
            # Allocate ID if possible
            if self.disc.alloc(self.clos, ObjectType.AGGRAPH, subg_id):
                subg = self.create_subgraph(name=f"Subgraph_{subg_id}")
                subg_new = self.id_to_subgraph.pop(subg.id)
                self.id_to_subgraph[subg_id] = subg_new
                subg.id = subg_id
        return subg

    def get_or_create_subgraph_by_name(self, name: str, create_if_missing: bool = False) -> Optional['Graph']:
        subg = self.subgraphs.get(name)
        if subg is None and create_if_missing:
            subg = Graph(name=name, directed=self.directed, root=self.root)
            subg.parent = self
            self.subgraphs[name] = subg
            self.id_to_subgraph[subg.id] = subg
            # Trigger callbacks if any
        return subg

    def agfstsubg(self) -> Optional['Graph']:
        """
        Retrieves the first subgraph within the enclosed_node.

        :return: The first Graph instance if any, else None.
        """
        first_subgraph = None
        first_name = next(iter(self.subgraphs))
        if first_name:
            first_subgraph = self.subgraphs[first_name]
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] No subgraphs in '{self.name}'.")
        return first_subgraph

    def agnxtsubg(self, subg: 'Graph') -> Optional['Graph']:
        """
        Retrieves the next subgraph after the given subgraph.

        :param subg: The current subgraph.
        :return: The next Graph instance if any, else None.
        """
        next_subgraph = None
        parent = self.agparent(subg)
        if parent:
            get_next = False
            for name, sgr in parent.subgraphs.items():
                if get_next:
                    next_subgraph = sgr
                    break
                agerr(Agerrlevel.AGINFO, f"Subgraph Name: {name}, ID: {subg.id}")
                if subg.name == name:
                    get_next = True
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{subg.name}' has no enclosed_node.")

        if next_subgraph:
            agerr(Agerrlevel.AGINFO, f"[Graph] Next subgraph after '{subg.name}': '{next_subgraph.name}'.")
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] No next subgraph after '{subg.name}'.")
        return next_subgraph

    def agdelsubg(self, subg: 'Graph') -> bool:
        """
        Deletes a subgraph from the enclosed_node.

        :param subg: The subgraph to delete.
        :return: True if deletion was successful, else False.
        """
        return self.delete_subgraph(subg)
        # enclosed_node = self.agparent(subg)
        # if not enclosed_node:
        #     agerr(Agerrlevel.AGINFO, f"[Graph] Cannot delete subgraph '{subg.name}' without a enclosed_node.")
        #     return False
        #
        # if subg.id in enclosed_node.id_to_subgraph:
        #     del enclosed_node.id_to_subgraph[subg.id]
        #     del enclosed_node.subgraphs[subg.name]
        #     agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{subg.name}' with ID '{subg.id}' deleted from enclosed_node '{enclosed_node.name}'.")
        #     return True
        # else:
        #     agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{subg.name}' with ID '{subg.id}' not found in enclosed_node '{enclosed_node.name}'.")
        #     return False

    def localsubg(self, id_: int) -> 'Graph':
        """
        Creates a local subgraph with the specified ID.

        :param id_: The unique identifier for the subgraph.
        :return: The newly created Graph instance.
        """
        subg = self.get_or_create_subgraph_by_id(id_,  True)
        # subg = Graph(name=f"Subgraph_{id_}", directed=self.directed, root=self.root)
        # subg.enclosed_node = self
        # if subg.id != id_:
        #     agerr(Agerrlevel.AGWARN, f"Subgraph ID: {subg.id} does not match the requested ID: {id_}")
        # self.id_to_subgraph[id_] = subg
        # self.subgraphs[subg.name] = subg
        # self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, subg)
        #
        # agerr(Agerrlevel.AGINFO, f"[Graph] Local subgraph '{subg.name}' with ID '{id_}' created.")
        # return subg
        return subg

    def agallocid(self, id_: int, objt: Optional[ObjectType] = None) -> bool:
        """
        Allocates a unique ID for a subgraph.

        :param id_: The unique identifier to allocate.
        :param objt: the type of object which defaults to a enclosed_node
        :return: True if allocation was successful, else False.
        """
        if id_ in self.id_to_subgraph:
            agerr(Agerrlevel.AGERR, f"[Graph] ID '{id_}' is already allocated to subgraph '{self.id_to_subgraph[id_].name}'.")
            return False
        else:
            """
            Attempts to allocate a specific ID. Always fails in this implementation.
            Equivalent to agallocid in C.
            """
            otype = objt if objt else ObjectType.AGGRAPH
            agerr(Agerrlevel.AGINFO, f"[Graph] ID '{id_}' allocated for new subgraph.")
            return self.disc.alloc(self.clos, otype, id_)

    def agapply(self, obj: ['Graph', 'Node', 'Edge'], fn: Callable, arg, preorder) -> bool:  # from cgraph/apply.c
        """
        Pythonic version of:
            int agapply(Agraph_t * g, Agobj_t * obj, agobjfn_t fn, void *arg, int preorder)
        We'll do a minimal approach: If 'obj' is a enclosed_node, we call 'fn' on it and its subgraphs.
                                   If 'obj' is a node or edge, we apply 'fn' on it
                                   and potentially any parallel object in subgraphs.
        :param obj: the object (Graph, Node, or Edge) in that enclosed_node hierarchy
        :param fn: a callback function (enclosed_node, object, arg) -> None
        :param arg: arbitrary user data
        :param preorder: int/boolean, if True => call fn before recursion, else after
        :return: None
        """
        # For brevity, let's only handle the trivial case:
        if obj.obj_type == ObjectType.AGGRAPH:
            objsearch = subgraph_search
        elif obj.obj_type == ObjectType.AGNODE:
            objsearch = subnode_search
        elif obj.obj_type == ObjectType.AGEDGE:
            objsearch = subedge_search
        else:
            agerr(Agerrlevel.AGERR, f"agapply: unknown object type {obj.obj_type}")
            return False
        # Attempt to find the matching object in the main enclosed_node 'g'
        subobj = objsearch(self, obj)
        if subobj is not None:
            self.rec_apply(subobj, fn, arg, objsearch, bool(preorder))
            return True
        else:
            return False

    @staticmethod
    def agattrsym(obj: ['Graph', Node, Edge], name: 'str') -> Optional[AgSym]:  # from /cgraph/attr.c
        """
        Pythonic version of 'agattrsym(obj, name)':
        Return the AgSym corresponding to 'name', or None if not found.
        """
        if obj.obj_type == ObjectType.AGGRAPH:
            # enclosed_node
            root = get_root_graph(obj)
            return root.attr_dict_g.get(name)
        elif obj.obj_type == ObjectType.AGNODE:
            return obj.attr_dict_n.get(name)
        elif obj.obj_type == ObjectType.AGEDGE:
            root = get_root_graph(obj.parent)
            return root.attr_dict_e.get(name)
        return None

    def agregister(self, obj_type: Union[ObjectType, str], subg: 'Graph'):
        """
        Registers a subgraph within the enclosed_node's subgraph dictionary.

        :param obj_type: The type of object ('GRAPH').
        :param subg: The subgraph to register.
        """
        if isinstance(obj_type, str):

            if obj_type == 'AGRAPH':
                obj_type = ObjectType.AGGRAPH
        if obj_type == ObjectType.AGGRAPH:
            self.id_to_subgraph[subg.id] = subg
            self.subgraphs[subg.name] = subg
            # self.subgraph_name_to_id[subg.name] = subg.id
            agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{subg.name}' with ID '{subg.id}' registered.")
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] Registration failed: Unsupported object type '{obj_type}'.")

    def create_edge(self, tail, head, eid: int):
        """
        Creates a new pair of edges in a directed enclosed_node (AGOUTEDGE + AGINEDGE),
        or just one edge if you like. The snippet code uses an Agedgepair_t.
        We can store only the 'out' edge as the official reference (like cgraph).
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

    def get_ancestors(self, subg:'Graph') -> List['Graph']:
        """
        Return a list of subg's ancestors from 'subg' itself
        up to the root (the topmost parent).
        """
        chain = []
        current = subg
        while current is not None:
            chain.append(current)
            current = current.parent  # climb up
        return chain

    def lowest_common_subgraph(self, node1: Node, node2: Node) -> Optional['Graph']:
        anc1 = self.get_ancestors(node1.parent)
        anc2 = self.get_ancestors(node2.parent)
        # anc1[0] is node1's subgraph, anc1[-1] is root
        # anc2[0] is node2's subgraph, anc2[-1] is root

        # Convert anc1 to a set for quick lookup
        set1 = set(anc1)

        # Walk anc2 from the smallest scope to the largest
        for candidate in anc2:
            if candidate in set1:
                return candidate
        return None  # shouldn't happen if there's a shared root

    def add_edge(self, tail_name: str, head_name: str, edge_name: Optional[str] = None, cflag: bool = True) -> Optional["Edge"]:
        """
        Equivalent to agedge(g, tail, head, edge_name, cflag).
        edge_name is the same as the key

        In standard cgraph (the core Graphviz library) and most “compound node” designs, edges that cross between a
        parent graph and its subgraph follow this general policy:

        An edge belongs to a subgraph only if both of its endpoints are also in that subgraph.

        In other words, if tail and head nodes both live inside the subgraph, that edge can appear in the subgraph’s
        edge dictionary.

        If one endpoint is outside (i.e., belongs to the parent graph), the edge does not appear in the subgraph.
        Crossing edges remain at the parent (or root) level.

        Because only one endpoint is inside the subgraph, the edge is tracked by the parent graph’s (or the root
        graph’s) .edges. The subgraph’s .edges does not duplicate it.

        In a “compound node” scenario (like Graphviz’s cmpnd.c code), you can optionally “splice” or “hide” crossing
        edges when collapsing a subgraph. For example:

            Splicing: Re-route the crossing edge so it connects to the compound node instead of the internal subgraph
            node, effectively collapsing those subgraph nodes behind a single node placeholder.

            Hiding: Remove or move the crossing edge into a “hidden set” so it vanishes from the parent’s visible edges
            while the subgraph is collapsed.

        No replication of the edge in both parent and subgraph.**

        Graphviz/cgraph does not store the same physical edge at two levels (parent and subgraph). Each edge is in
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

        key = (tail_name, head_name, edge_name)
        if key in self.edges:
            return self.edges[key]

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

        # Determine the owner graph for the edge:
        # If both endpoints have a parent (i.e. they belong to some subgraph), find their lowest common subgraph.
        if tail.parent is not None and head.parent is not None:
            lcs = self.lowest_common_subgraph(tail, head)
            edge_graph = lcs if lcs is not None else self
        else:
            # At least one node belongs directly to the current graph.
            edge_graph = self

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


    def agpushdisc(self, cbd: 'Agcbdisc', state: Any):
        """
        Pushes a discipline onto the stack.
        :param cbd: The callback discipline.
        :param state: The state associated with the discipline.
        """
        # """
        # Pushes a discipline onto the stack.
        #
        # :param g: The enclosed_node.
        # :param cbd: The callback discipline.
        # :param state: The state associated with the discipline.
        # """
        # stack_ent = Agcbstack()
        # stack_ent.f = cbd
        # stack_ent.state = state
        # stack_ent.prev = g.clos['cb']
        # g.clos['cb'] = stack_ent

        self.push_discipline(cbd, state)

    def agparent(self, obj: Optional[Union['Graph', 'Node', 'Edge']] = None):
        if obj:
            return self.get_graph_of(obj).parent
        else:
            return self.parent

    def agdeledge(self, e):  # from cgraph/edge.c
        self.delete_edge(e)

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

    # def _next_edge_seq(self) -> int:
    #     """Increment a sequence counter. Real code also checks overflow, etc."""
    #     # For simplicity, we’ll just reuse the _next_edge_id
    #     val = self._next_edge_id
    #     self._next_edge_id += 1
    #     return val

    def find_edge_by_id_tail_head(self, tail, head, eid: int):
        """
        Like 'agfindedge_by_id', tries to find an edge by numeric ID in this enclosed_node
        or (if undirected) by flipping tail/head if not found.
        We'll just do a simple search in self.edges. In real cgraph, you do dtsearch.
        """
        # We’ll rummage through edges to see if any have the same ID.
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
        We'll just do a simple search in self.edges. In real cgraph, you do dtsearch.
        """
        # We’ll rummage through edges to see if any have the same ID.
        # Real Graphviz uses a node-based dictionary; here we do a linear search for demo.
        for e in self.edges.values():
            if e.id == eid:
                return e
        return None

    # -------- Node Management Methods Equivalent to C Code --------
    def find_by_id(self, id_: int):
        found_node = self.find_node_by_id(id_)
        if found_node:
            return found_node
        found_edge = self.find_edge_by_id(id_)
        if found_edge:
            return found_edge



    def find_node_by_id(self, id_: int) -> Optional['Node']:  # from /cgraph/node.c
        """
        Equivalent to agfindnode_by_id in C.

        :param id_: The ID of the node to find.
        :return: The Node object if found, else None.
        """
        for node_item in self.nodes.values():
            if node_item.id == id_:
                return node_item
        return None

    def find_graph_by_name(self, name: str) -> Optional['Graph']:  # from /cgraph/node.c
        """
        Equivalent to agfindnode_by_name in C.

        :param name: The name of the edge to find.
        :return: The Node object if found, else None.
        """
        if self.name == name:
            return self
        else:
            for sgname, sgr in self.subgraphs:
                if sgname == self.name:
                    return sgr
        if self.parent:
            if self.parent.name == name:
                return self.parent

        return None

    def find_edge_by_name(self, name: str) -> Optional['Edge']:  # from /cgraph/node.c
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

    def find_node_by_name(self, name: str) -> Optional['Node']:  # from /cgraph/node.c
        """
        Equivalent to agfindnode_by_name in C.

        :param name: The name of the node to find.
        :return: The Node object if found, else None.
        """
        id_ = self.disc.map(self.clos, ObjectType.AGNODE, name, createflag=False)
        # id_ = agmapnametoid(self, ObjectType.AGNODE, name, createflag=False)
        if id_ is not None:
            return self.find_node_by_id(id_)
        return None

    def first_node(self) -> Optional["Node"]:  # from /cgraph/node.c
        """
        Equivalent to agfstnode in C.

        :return: The first Node in the enclosed_node if exists, else None.
        """
        if not self.nodes:
            return None
        # Assuming insertion order; first inserted node
        first_name = next(iter(self.nodes))
        return self.nodes[first_name]

    def next_node(self, current: "Node") -> Optional["Node"]:    # from /cgraph/node.c
        """
        Equivalent to agnxtnode in C.

        :param current: The current Node.
        :return: The next Node in the enclosed_node if exists, else None.
        """
        names = list(self.nodes.keys())
        try:
            idx = names.index(current.name)
            if idx + 1 < len(names):
                return self.nodes[names[idx + 1]]
        except ValueError:
            pass
        return None

    def last_node(self) -> Optional["Node"]:    # from /cgraph/node.c
        """
        Equivalent to aglstnode in C.

        :return: The last Node in the enclosed_node if exists, else None.
        """
        if not self.nodes:
            return None
        last_name = next(reversed(self.nodes))
        return self.nodes[last_name]

    def previous_node(self, current: "Node") -> Optional["Node"]:  # from /cgraph/node.c
        """
        Equivalent to agprvnode in C.

        :param current: The current Node.
        :return: The previous Node in the enclosed_node if exists, else None.
        """
        names = list(self.nodes.keys())
        try:
            idx = names.index(current.name)
            if idx - 1 >= 0:
                return self.nodes[names[idx - 1]]
        except ValueError:
            pass
        return None

    def create_node_by_id(self, id_: int) -> Optional["Node"]:  # from /cgraph/node.c
        """
        Equivalent to agidnode in C.
        Creates a node with a specific ID if 'createflag' is True.

        :param id_: The ID for the new node.
        :return: The created Node object if successful, else None.
        """
        existing_node = self.find_node_by_id(id_)
        if existing_node:
            return existing_node  # Node already exists

        # Allocate ID (in this implementation, IDs are managed automatically)
        # Here, we assume that 'agallocid' is similar to 'map' with createflag=True
        # Since 'alloc' does not support specific ID allocation, this method is limited
        # For demonstration, we'll skip specific ID allocation
        agerr(Agerrlevel.AGWARN, "Specific ID allocation is not supported in this implementation.")
        return None

    def create_node_by_name(self, name: str, cflag: bool = True) -> Optional["Node"]:  # from /cgraph/node.c
        """
        Equivalent to agnode in C.
        Creates a node with a specific name.

        :param name: The name of the node.
        :param cflag: If True, create the node if it does not exist.
        :return: The created or existing Node object if successful, else None.
        """
        return self.add_node(name, create=cflag)

        # if name in self.nodes:
        #     return self.nodes[name]
        #
        # # id = agmapnametoid(self, ObjectType.AGNODE, name, createflag=createflag)
        # # if id is None:
        # #     return None
        #
        # id_ = self.disc.map(self.clos, ObjectType.AGNODE, name, createflag=cflag)
        # if id_ is None:
        #     agerr(Agerrlevel.AGWARN, f"Failed to allocate ID for node '{name}'.")
        #     return None
        #
        # seq = self.get_next_sequence(ObjectType.AGNODE)
        #
        # new_node = Node(name=name, graph=self, id_=id_, seq=seq, root=self.get_root())
        #
        # # node = Node(name=name, enclosed_node=self, id=id)
        # self.nodes[name] = new_node
        # self.disc.idregister(self.clos, ObjectType.AGNODE, new_node)
        # # agregister(self, ObjectType.AGNODE, node)
        #
        # # Initialize comparison data metrics as needed
        # new_node.set_compound_data("centrality", self.compute_centrality(new_node))
        # new_node.set_compound_data("rank", 0)  # Example initialization
        #
        # # Invoke node added callbacks
        # self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, new_node)
        # return new_node

    # def agrelabel_node(n: 'Node',  newname: 'str') -> 'int':
    #     pass
    def agrelabel_node(self, obj, newname):
        self.rename(obj, newname)

    def relabel_node(self, original_node: "Node", newname: str) -> bool: # from /cgraph/node.c
        """
        Equivalent to agrelabel_node in C.
        Relabels a node with a new name.

        :param original_node: The Node object to relabel.
        :param newname: The new name for the node.
        :return: True if relabeling was successful, else False.
        """
        if self.find_node_by_name(newname):
            agerr(Agerrlevel.AGWARN, f"Node with name '{newname}' already exists.")
            return False

        # TODO: Add callbacks for node deleted and node added
        # Remove old name mapping
        self.clos.invoke_callbacks(GraphEvent.NODE_DELETED, self.nodes[original_node.name])
        del self.nodes[original_node.name]
        # Update node's name
        original_node.name = newname

        # Add new name mapping
        self.nodes[newname] = original_node

        # Update mappings in ID discipline
        self.disc.idregister(self.clos, ObjectType.AGNODE, original_node)
        self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, original_node)

        return True

    def add_subgraph_node(self, sgr: 'Graph', work_node: "Node", createflag: bool = True) -> Optional["Node"]: # from /cgraph/node.c
        """
        Equivalent to agsubnode in C.
        Looks up or inserts a node into a subgraph.

        :param sgr: The subgraph to insert the node into.
        :param work_node: The Node object to insert.
        :param createflag: If True, create the node in the subgraph if it does not exist.
        :return: The Node object in the subgraph if successful, else None.
        """

        print("A node is being added and created to a subgraph")
        # (a) Check if it's already compound
        if work_node.compound_node_data.is_compound:
            agerr(Agerrlevel.AGWARN, f"Node '{work_node.name}' is already a compound node.")
            return None

        # (b) Mark the node as compound, link to the existing subgraph
        work_node.compound_node_data.is_compound = True
        work_node.compound_node_data.subgraph = sgr
        work_node.compound_node_data.collapsed = False

        root_graph = get_root_graph(self)
        root_graph.nodes[work_node.name] = work_node


        if sgr.find_node_by_id(work_node.id):
            return sgr.find_node_by_id(work_node.id)

        if createflag:
            sgr.nodes[work_node.name] = work_node
            self.disc.idregister(self.clos, ObjectType.AGNODE, work_node)
            # agregister(subgraph, ObjectType.AGNODE, node)
            return work_node
        return None

    # -------- Record Management Methods --------

    # def agbindrec(self, rec_name: str, rec_size: int, mtf: bool = False) -> Agrec:  # from cgraph/rec.c
    #     """
    #     Binds a new record to the enclosed_node object.
    #
    #     :param rec_name: The name of the record.
    #     :param rec_size: The size of the record (unused in Python).
    #     :param mtf: Flag indicating whether to move the record to the front upon binding.
    #     :return: The newly created record.
    #     """
    #     return super().agbindrec(rec_name, rec_size, mtf)

    # def aggetrec(self, rec_name: str, mtf: bool = False) -> Optional[Agrec]:  # from cgraph/rec.c
    #     """
    #     Retrieves a record by name from the enclosed_node object.
    #
    #     :param rec_name: The name of the record to retrieve.
    #     :param mtf: Flag indicating whether to move the record to the front upon retrieval.
    #     :return: The requested record if it exists, else None.
    #     """
    #     return super().aggetrec(rec_name, mtf)

    def agdelrec(self, rec_name: str):  # from cgraph/rec.c
        """
        Deletes a record by name from the enclosed_node object.

        :param rec_name: The name of the record to delete.
        :return: True if deletion was successful, False otherwise.
        """
        self.attr_record.pop(rec_name, None)

    def aginit(self, kind: ObjectType, rec_name: str, rec_size: int, mtf: bool = False):  # from cgraph/rec.c
        """
        Initializes records for enclosed_node objects based on the specified kind.

        :param kind: The kind of object to initialize (ObjectType.AGGRAPH, ObjectType.AGNODE, ObjectType.AGEDGE).
        :param rec_name: The name of the record to bind.
        :param rec_size: The size of the record (unused in Python).
        :param mtf: Flag indicating whether to enable MTF optimization.
        """
        if kind == ObjectType.AGGRAPH:
            self.agbindrec(rec_name, rec_size, mtf)
            # Recursively initialize subgraphs if any
            if rec_size < 0:
                for subg in self.subgraphs.values():
                    subg.aginit(kind, rec_name, rec_size, mtf)
        elif kind == ObjectType.AGNODE:
            for n_node in self.nodes.values():
                n_node.agbindrec(rec_name, rec_size, mtf)
        elif kind in (ObjectType.AGOUTEDGE, ObjectType.AGINEDGE, ObjectType.AGEDGE):
            for n_edge in self.edges.values():
                n_edge.agbindrec(rec_name, rec_size, mtf)
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] aginit failed: Unknown kind '{kind}'.")

    def agclean(self, kind: ObjectType, rec_name: str):  # from cgraph/rec.c
        """
        Cleans (deletes) all records of a specific kind from the enclosed_node object.

        :param kind: The kind of object whose records are to be cleaned ('AGRAPH', 'AGNODE', 'AGEDGE').
        :param rec_name: The name of the record to delete.
        """
        if kind == ObjectType.AGGRAPH:
            self.attr_dict_g.pop(rec_name, None)
            # Recursively clean subgraphs if any
            for subg in self.subgraphs.values():
                subg.agclean(kind, rec_name)
        elif kind == ObjectType.AGNODE:
            self.attr_dict_n.pop(rec_name, None)
            for n in self.nodes.values():
                n.attributes.pop(rec_name, None)
            for subg in self.subgraphs.values():
                subg.agclean(ObjectType.AGNODE, rec_name)

        elif kind in (ObjectType.AGOUTEDGE, ObjectType.AGINEDGE, ObjectType.AGEDGE):
            self.attr_dict_e.pop(rec_name, None)
            for e in self.edges.values():
                e.attributes.pop(rec_name, None)
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] agclean failed: Unknown kind '{kind}'.")

    # def agrecclose(self):  # from cgraph/rec.c
    #     """
    #     Closes all records associated with the enclosed_node object.
    #     """
    #     super().agrecclose()

    # -------- Existing Callback and Other Methods --------

    @staticmethod
    def agdtinsert(dict_: GraphDict, handle: Any):
        """
        Inserts an item into a dictionary.

        :param dict_: The dictionary to insert into.
        :param handle: The item to insert.
        """
        key = handle['key']
        dict_[key] = handle

    @staticmethod
    def agdtsearch(dict_: Dict, key: Any) -> Optional[Any]:
        """
        Searches for an item in a dictionary.

        :param dict_: The dictionary to search.
        :param key: The key to search for.
        :return: The found item or None.
        """
        return dict_.get(key)

    # -------- Memory Management Methods --------


    @staticmethod
    def agdictobjmem(p: Optional[Any], size: int) -> Optional[Any]:  # from the /cgraph/utils.c
        """
        Custom memory allocation/deallocation function.
        Behavior: If a global enclosed_node (Ag_dictop_G) is set, it uses agalloc or agfree for memory operations; otherwise, it defaults to malloc and free.
        Emulates agdictobjmem from C.
         # agdictobjmem: from the /cgraph/utils.c
        """
        if p:
            # Emulate agfree(g, p)
            agerr(Agerrlevel.AGINFO, f"[Agraph] Freeing object: {p}")
            # In Python, garbage collection handles memory, so explicit freeing isn't required
            return None
        else:
            # Emulate agalloc(g, size)
            obj = object.__new__(object)  # Allocate a new generic object
            agerr(Agerrlevel.AGINFO, f"[Agraph] Allocating new object of size {size}: {obj}")
            return obj

    @staticmethod
    def agdictobjfree(p: Any):
        """
        Custom object free function.Purpose: Frees memory for dictionary objects.
        Emulates agdictobjfree from C. from the /cgraph/utils.c
        Behavior: Similar to agdictobjmem, it uses agfree if a global enclosed_node is set, else free.
        """
        # Emulate agfree(g, p)
        agerr(Agerrlevel.AGINFO, f"[Agraph] Freeing object: {p}")
        # In Python, garbage collection handles memory, so explicit freeing isn't required

    # -------- Dictionary Management Methods --------

    def agdtopen(self, method: Optional[Callable] = None) -> GraphDict:
        """
        Opens a new dictionary with a specific discipline.
        Purpose: Opens a new dictionary with a specific discipline.
        Emulates agdtopen from C from the /cgraph/utils.c
        Behavior: Temporarily sets the global enclosed_node (Ag_dictop_G), assigns the custom memory function, and opens the dictionary.
        """
        agerr(Agerrlevel.AGINFO, f"[Agraph] Opening dictionary with discipline and method: {method}")
        self.dict = GraphDict(discipline=self.disc, method=method)
        return self.dict

    # def agdtopen(self, disc: Any, mode: str) -> Dict:
    #     """
    #     Opens a new dictionary for managing data associated with enclosed_node objects.
    #
    #     :param agraph: The enclosed_node object.
    #     :param disc: Discipline or key for the dictionary.
    #     :param mode: Mode of the dictionary (e.g., 'Dttree').
    #     :return: A dictionary representing the opened data structure.
    #     """
    #     return {}

    def agdtdelete(self, obj: Any) -> bool:
        """
        Deletes an object from the dictionary.
        Purpose: Deletes an object from the dictionary.
        Emulates agdtdelete from C.from the /cgraph/utils.c
        Behavior: Sets the global enclosed_node and deletes the object using dtdelete.
        """
        if not self.dict:
            agerr(Agerrlevel.AGINFO, "[Agraph] Dictionary not initialized.")
            return False
        success = self.dict.delete(obj)
        if success:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Deleted object from dictionary: {obj}")
        else:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Object not found in dictionary: {obj}")
        return success

    #
    # def agdtdelete(self, dict_: Dict, handle: Any):
    #     """
    #     Deletes an item from a dictionary.
    #
    #     :param dict_: The dictionary to delete from.
    #     :param handle: The item to delete.
    #     """
    #     key = handle['key']
    #     dict_.pop(key, None)

    def agdtclose(self) -> bool:
        """
        Closes the dictionary.Purpose: Closes the dictionary.
        Emulates agdtclose from C.from the /cgraph/utils.c
        Behavior: Sets the global enclosed_node, closes the dictionary using dtclose, and restores the original memory function.
        """
        if not self.dict:
            agerr(Agerrlevel.AGINFO, "[Agraph] Dictionary not initialized or already closed.")
            return False
        success = self.dict.close()
        if success:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Dictionary closed successfully.")
        else:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Failed to close dictionary.")
        self.dict = None
        return success

    def agdtdisc(self, disc: AgIdDisc):
        """
        Sets the discipline for the dictionary.
        Purpose: Sets the discipline for the dictionary.
        Behavior: Updates the dictionary's discipline if it's different from the current one.
        Emulates agdtdisc from C.from the /cgraph/utils.c
        """
        agerr(Agerrlevel.AGINFO, f"[Agraph] Setting discipline: {disc}")
        self.disc = disc
        if self.dict:
            self.dict.discipline = disc

    def agdtopen_subgraph_dict(self, method: Optional[Callable] = None) -> GraphDict:
        agerr(Agerrlevel.AGINFO, f"[Agraph] Opening subgraph dictionary with method: {method}")
        return self.agdtopen(method=method)

    def agdtdelete_subgraph_by_name(self, name: str) -> bool:
        subg = self.subgraphs.get(name)
        if subg:
            return self.agdelsubg(subg)
        else:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Cannot delete non-existent subgraph with name '{name}'.")
            return False

    # -------- String Management Methods --------

    def agstrbind(self, s: str) -> str:
        """
        Binds a string to the enclosed_node's string dictionary with reference counting.

        :param s: The string to bind.
        :return: The bound string.
        """
        if s in self._strdict:
            self._strdict[s]['refcnt'] += 1
            agerr(Agerrlevel.AGINFO, f"[Graph] String '{s}' already bound. Incremented refcnt to {self._strdict[s]['refcnt']}.")
        else:
            self._strdict[s] = {'refcnt': 1, 'is_html': False}
            agerr(Agerrlevel.AGINFO, f"[Graph] String '{s}' bound with refcnt=1.")
        return s

    def agstrdup(self, s: str) -> str:
        """
        Duplicates a string without marking it as HTML.

        :param s: The string to duplicate.
        :return: The duplicated string.
        """
        return self.agstrbind(s)

    def agstrdup_html(self, s: str) -> str:
        """
        Duplicates a string and marks it as HTML.

        :param s: The string to duplicate.
        :return: The duplicated string marked as HTML.
        """
        if s in self._strdict:
            self._strdict[s]['refcnt'] += 1
            agerr(Agerrlevel.AGINFO, f"[Graph] HTML string '{s}' already bound. Incremented refcnt to {self._strdict[s]['refcnt']}.")
        else:
            self._strdict[s] = {'refcnt': 1, 'is_html': True}
            agerr(Agerrlevel.AGINFO, f"[Graph] HTML string '{s}' bound with refcnt=1 and is_html=True.")
        return s

    def agstrfree(self, s: str) -> bool:
        """
        Frees a string from the enclosed_node, decrementing its reference count.

        :param s: The string to free.
        :return: True if successfully freed, False otherwise.
        """
        if s not in self._strdict:
            agerr(Agerrlevel.AGINFO, f"[Graph] Cannot free string '{s}'; it does not exist.")
            return False

        self._strdict[s]['refcnt'] -= 1
        agerr(Agerrlevel.AGINFO, f"[Graph] Decremented refcnt of string '{s}' to {self._strdict[s]['refcnt']}.")

        if self._strdict[s]['refcnt'] == 0:
            del self._strdict[s]
            agerr(Agerrlevel.AGINFO, f"[Graph] String '{s}' has been fully freed and removed from the dictionary.")

        return True

    def aghtmlstr(self, s: str) -> bool:
        """
        Checks if a string is marked as HTML.

        :param s: The string to check.
        :return: True if marked as HTML, False otherwise.
        """
        if s in self._strdict:
            is_html = self._strdict[s]['is_html']
            agerr(Agerrlevel.AGINFO, f"[Graph] String '{s}' is_html={is_html}.")
            return is_html
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] String '{s}' not found in dictionary.")
            return False

    def agmarkhtmlstr(self, s: str) -> bool:
        """
        Marks a string as HTML.

        :param s: The string to mark.
        :return: True if successfully marked, False otherwise.
        """
        if s in self._strdict:
            self._strdict[s]['is_html'] = True
            agerr(Agerrlevel.AGINFO, f"[Graph] String '{s}' marked as HTML.")
            return True
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] Cannot mark string '{s}' as HTML; it does not exist.")
            return False

    def agstrclose(self):
        """
        Closes the string dictionary, clearing all bound strings.
        """
        self._strdict.clear()
        agerr(Agerrlevel.AGINFO, f"[Graph] String dictionary for enclosed_node '{self.name}' has been closed and cleared.")

    def get_graph_attr(self, attr_name: str) -> str:
        if attr_name in self.attr_dict_g:
            return self.attr_dict_g[attr_name]
        else:
            # fallback to root if this isn't root
            root = get_root_graph(self)
            return root.attr_dict_g.get(attr_name)

    def agget(self, name:str):  # from /cgraph/attr.c
        """
        Pythonic version of 'agget(obj, name)':
        Return the string value of the attribute named 'name' for obj.
        Return None if attribute does not exist.
        """
        return self.get_graph_attr(name)

    def set_graph_attr(self, attr_name: str, value: str):
        """
        Change the actual default for THIS enclosed_node (and effectively subgraphs).
        Usually done only at the root, or if subgraphs share the enclosed_node's dictionaries.
        """
        self.attr_dict_g[attr_name] = value

    def agset(self, name, value):  # from /cgraph/attr.c
        """
        Pythonic version of 'agset(obj, name, value)':
        Set the attribute named 'name' for 'obj' to 'value'.
        Return SUCCESS/FAILURE.
        """
        self.set_graph_attr(name, value)

    def agsafeset(self, name, value, default):  # from /cgraph/attr.c
        """
        Pythonic version of 'agsafeset(obj, name, value, def)':
        If 'name' attribute doesn't exist, define it with 'default' at the root enclosed_node.
        Then set it to 'value'.
        """
            # Declare a new attribute with default
        if name in self.attr_record:
            self.attr_record[name] = value
        else:
            self.attr_record[name] = value
            self.set_graph_attr(name, default)


    def agnnodes(self) -> int:
        return len(self.nodes)

    def agnedges(self) -> int:
        return len(self.edges)

    def agnsubg(self) -> int:
        return len(self.subgraphs)

    # 3.8 agisdirected(self), agisundirected(self), etc.
    def agisdirected(self) -> bool:
        return self.desc.directed

    def agisundirected(self) -> bool:
        return not self.desc.directed

    def agisstrict(self) -> bool:
        return self.desc.strict

    def agissimple(self) -> bool:
        return self.desc.strict and self.desc.no_loop


    def agclose(self):
        """
        Closes the enclosed_node, performing cleanup via the Agclos instance.
        """
        # Recursively close all subgraphs
        for sgr in list(self.subgraphs.values()):
            sgr.agclose()

        # Reset callbacks
        self.clos.reset_callbacks()

        # Close string dictionary
        self.agstrclose()

        # Reset string dictionary
        self._strdict.clear()
        self.closed = True
        agerr(Agerrlevel.AGINFO, f"[Graph] Graph '{self.name}' has been closed successfully.")


    # def agclose(self, other: 'Graph') -> int:
    #     """
    #     3.5 g.agclose()  # agclose(g)
    #     Recursively close subgraphs, free nodes/edges, handle memory discipline close, etc.
    #
    #     1) if par==NULL => free entire heap?
    #     2) else recursively close subgraphs, nodes, free dictionaries
    #     3) if root => free closure
    #     return SUCCESS or FAILURE
    #     """
    #     if other.closed:
    #         return 0  # Already closed
    #     enclosed_node = other.enclosed_node  # agparent(g)
    #     # if enclosed_node is None:
    #     #     if g.state['enclosed_node'].clos.state:
    #     #         if g.clos.state.mem:
    #     #             # This is the main enclosed_node
    #     #             # 1) call agmethod_delete(g, g) => no-op or minimal
    #     #             # 2) free ID
    #     #             # 3) clos->disc.mem->close(clos->state.mem)
    #     #             g.clos.state.mem.close(g.clos.state.mem)
    #
    #     if enclosed_node is None:  # This has no enclosed_node so close this enclosed_node
    #         # Assuming 'clos' is a dictionary containing the state
    #         if other.clos:
    #             # Call the memory discipline's close method with 'clos' as the state
    #             other.disc.close(other.clos)
    #     # Additional cleanup can be performed here if necessary
    #     other.closed = True
    #
    #     # # 2) for each subgraph in g.subgraphs => subgraph.agclose()  # agclose(subgraph)
    #     # for sg in list(g.subgraphs.values()):
    #     #     sg.agclose()  # agclose(sg)
    #
    #     # 2) Close subgraphs
    #     for sname, sg_copy in list(other.subgraphs.items()):
    #         sg_copy.close()  # agclose(sg)
    #     other.subgraphs.clear()
    #
    #     # 3) delete all nodes
    #     for n_value in list(other.nodes.values()):
    #         other.delete_node(n_value)
    #     other.nodes.clear()
    #
    #     # 4) free internal dictionaries
    #     # 5) if g->description.has_attrs => agraphattr_delete(g)
    #     # 6) free ID
    #     # 7) if enclosed_node => remove from enclosed_node's subgraphs
    #     if enclosed_node:
    #         if other.name in enclosed_node.subgraphs:
    #             agerr(Agerrlevel.AGINFO, f"deleting {other.name}")
    #             del enclosed_node.subgraphs[other.name]
    #         # free the memory in enclosed_node's closure?
    #     else:
    #         # if root => free the closure
    #         # # 4) If main enclosed_node, free clos
    #         # if g == g.root:
    #         #     # This would mimic AGDISC(g, mem)->close(AGCLOS(g, mem)), etc.
    #         #     pass
    #
    #         pass
    #     other.closed = True
    #     return 0


    def agdelcb(self, obj: Union['Graph', 'Node', 'Edge'], cbstack: Optional[Agcbstack]):
        """
        Recursive deletion callbacks.

        :param obj: The object.
        :param cbstack: The callback stack.
        """
        if cbstack is None:
            return
        self.agdelcb(obj, cbstack.prev)
        fn = None
        if isinstance(obj, Graph):
            fn = cbstack.f.graph.delete if cbstack.f and hasattr(cbstack.f, 'enclosed_node') else None
        elif isinstance(obj, Node):
            fn = cbstack.f.node.delete if cbstack.f and hasattr(cbstack.f, 'node') else None
        elif isinstance(obj, Edge):
            fn = cbstack.f.edge.delete if cbstack.f and hasattr(cbstack.f, 'edge') else None
        if fn:  # TODO: the cbstack.state object needs to be examined/ fixed
            fn(obj, cbstack.state)

    def close(self):
        """
        This would mimic 'agclose', removing edges, nodes, subgraphs,
        and eventually freeing the enclosed_node. We'll do a minimal version.
        """
        if self.closed:
            agerr(Agerrlevel.AGWARN, f"Graph '{self.name}' is already closed.")
            return

        # Remove edges
        for edge_key in list(self.edges.keys()):
            edge = self.edges[edge_key]
            self.disc.free(self.clos, ObjectType.AGEDGE, edge.id)

            # agfreeid(self, ObjectType.AGEDGE, edge.id)
            del self.edges[edge_key]

        # Remove nodes
        for node_name in list(self.nodes.keys()):
            node = self.nodes[node_name]
            self.disc.free(self.clos, ObjectType.AGNODE, node.id)

            # agfreeid(self, ObjectType.AGNODE, node.id)
            del self.nodes[node_name]

        # Recursively close subgraphs
        for sg_name in list(self.subgraphs.keys()):
            sg = self.subgraphs[sg_name]
            sg.close()
            if sg_name in self.subgraphs.keys():
                del self.subgraphs[sg_name]
        if not self.is_main_graph and self.parent:
            del self.parent.subgraphs[self.name]
        # Invoke discipline's close method
        # Close the current enclosed_node
        if self.parent is None:
            # Check if 'clos' is initialized and has necessary state
            if self.clos:
                # Reset the 'clos' state
                self.clos.reset()
                # Invoke the memory discipline's close method with 'clos' as the state
                self.disc.close(self.clos)

        # Mark as closed
        self.closed = True

        # -------- Centrality Computation Methods --------

    def compute_degree_centrality(self):
        """
        Computes Degree Centrality for all nodes in the enclosed_node.
        Degree Centrality is the number of direct connections a node has.
        """
        for node in self.nodes.values():
            degree = len(node.outedges) + len(node.inedges)
            node.set_compound_data("degree_centrality", degree)
            # Optionally, normalize if desired
            node.set_compound_data("degree_centrality_normalized",
                                   degree / (len(self.nodes) - 1) if len(self.nodes) > 1 else 0)

    def compute_betweenness_centrality(self):
        """
        Computes Betweenness Centrality for all nodes in the enclosed_node.
        Betweenness Centrality measures the number of times a node acts as a bridge along the
        shortest path between two other nodes.
        """
        betweenness = {node.name: 0.0 for node in self.nodes.values()}

        for s in self.nodes.values():
            # Single-source shortest-paths
            stack = []
            predecessors = {node.name: [] for node in self.nodes.values()}
            sigma = {node.name: 0 for node in self.nodes.values()}  # Number of shortest paths
            distance = {node.name: -1 for node in self.nodes.values()}
            sigma[s.name] = 1
            distance[s.name] = 0
            queue = deque([s])

            while queue:
                v = queue.popleft()
                stack.append(v)
                for edge in v.outedges:
                    w = edge.head
                    if distance[w.name] < 0:
                        distance[w.name] = distance[v.name] + 1
                        queue.append(w)
                    if distance[w.name] == distance[v.name] + 1:
                        sigma[w.name] += sigma[v.name]
                        predecessors[w.name].append(v.name)

            # Accumulation
            delta = {node.name: 0.0 for node in self.nodes.values()}
            while stack:
                w = stack.pop()
                for v_name in predecessors[w.name]:
                    delta[v_name] += (sigma[v_name] / sigma[w.name]) * (1 + delta[w.name])
                if w != s.name:
                    betweenness[w.name] += delta[w.name]

        # Normalize the betweenness centrality values
        scale = 1 / ((len(self.nodes) - 1) * (len(self.nodes) - 2)) if len(self.nodes) > 2 else 1
        for node in self.nodes.values():
            node.set_compound_data("betweenness_centrality", betweenness[node.name] * scale)

    def compute_closeness_centrality(self):
        """
        Computes Closeness Centrality for all nodes in the enclosed_node.
        Closeness Centrality measures how close a node is to all other nodes based on the shortest paths.
        """
        for node in self.nodes.values():
            # BFS to compute shortest paths
            visited = {n.name: False for n in self.nodes.values()}
            distance = {n.name: 0 for n in self.nodes.values()}
            queue = deque([node])
            visited[node.name] = True
            while queue:
                current = queue.popleft()
                for edge in current.outedges:
                    neighbor = edge.head
                    if not visited[neighbor.name]:
                        visited[neighbor.name] = True
                        distance[neighbor.name] = distance[current.name] + 1
                        queue.append(neighbor)

            # Sum of distances
            total_distance = sum(distance.values())
            if total_distance > 0:
                closeness = (len(self.nodes) - 1) / total_distance
            else:
                closeness = 0.0
            node.set_compound_data("closeness_centrality", closeness)

    def compute_centrality(self, graph_or_node: Agobj = None):
        """
        Computes all centrality measures for all nodes.
        """
        if not graph_or_node:
            graph_or_node = self
        graph_or_node.compute_degree_centrality()
        graph_or_node.compute_betweenness_centrality()
        graph_or_node.compute_closeness_centrality()
        if isinstance(graph_or_node, Node):
            return float(graph_or_node.compound_node_data.degree_centrality)
        if isinstance(graph_or_node, Graph):
            return float(graph_or_node.cmp_graph_data.degree_centrality)

    # def __repr__(self):
    #     if hasattr(self, 'desc'):
    #         d = "directed" if self.desc.directed else "undirected"
    #         s = "strict" if self.desc.strict else "non-strict"
    #     else:
    #         d = None
    #         s = None
    #
    #     return (f"<Graph {self.name}, directed={d}, strict={s}, "
    #             f"nodes={len(self.nodes)}, edges={len(self.edges)}, "
    #             f"subgraphs={len(self.subgraphs)}, flatlock={self.desc.flatlock}>")

    def __repr__(self):
        def safe_repr(val):
            # For Graph, Node, and Edge instances, just show a short summary.
            # (Assuming Graph, Node, and Edge are available in this module’s scope.)
            if isinstance(val, Graph):
                return f"<Graph {val.name}>"
            elif isinstance(val, Node):
                return f"<Node {val.name}>"
            elif isinstance(val, Edge):
                return f"<Edge {val.name}>"
            else:
                return repr(val)

        # Collect base attributes except for nodes, edges, and subgraphs.
        base_attrs = {}
        for attr, value in self.__dict__.items():
            if attr in ['nodes', 'edges', 'subgraphs']:
                continue
            base_attrs[attr] = safe_repr(value)

        # Build a single-line string with each base attribute indented.
        base_attrs_str = "\n".join(f"    {k}: {v}" for k, v in base_attrs.items())

        # Summarize contained objects by their names/keys.
        node_names = list(self.nodes.keys())
        edge_keys = [str(k) for k in self.edges.keys()]
        subgraph_names = list(self.subgraphs.keys())

        return (
            f"<Graph {self.name}:\n{base_attrs_str},\n"
            f"  Nodes ({len(node_names)}): {node_names},\n"
            f"  Edges ({len(edge_keys)}): {edge_keys},\n"
            f"  Subgraphs ({len(subgraph_names)}): {subgraph_names}>"
        )

    def aginitcb(self, obj: Union['Graph', 'Node', 'Edge'], cbstack: Optional[Agcbstack] = None):
        """
        Initializes callbacks for a enclosed_node object by traversing the callback stack.
        Equivalent to the C 'aginitcb' function in /cgraph/obj.c

        :param obj: The enclosed_node object (Graph, Node, or Edge) to initialize.
        :param cbstack: The current callback stack node.
        """
        if cbstack is None:
            return  # Base case for recursion

        # Recursively initialize callbacks with the previous stack node
        self.aginitcb(obj, cbstack.prev)

        fn = None
        # Determine the type of the object and retrieve the corresponding 'ins' function
        if isinstance(obj, Graph):
            fn = cbstack.f.graph.ins
        elif isinstance(obj, Node):
            fn = cbstack.f.node.ins
        elif isinstance(obj, Edge):
            fn = cbstack.f.edge.ins

        # If an 'ins' function is found, invoke it
        if fn:
            fn(self, obj, cbstack.state)


    def agobjkind(self, arg: Any) -> Optional[ObjectType]:
        """
        Retrieves the kind of the object.

        :param arg: The object.
        :return: The type of the object as an integer.
        """
        return self.obj_kind(arg)

    @staticmethod
    def obj_kind(obj: Union["Node", "Graph"]) -> Optional[ObjectType]:
        """
        Retrieves the type of the object.

        :param obj: The object whose type is to be retrieved.
        :return: The type of the object as an integer.
        """
        if isinstance(obj, Graph):
            return ObjectType.AGGRAPH
        elif isinstance(obj, Node):
            return ObjectType.AGNODE
        elif isinstance(obj, Edge):
            # Assuming Edge has an attribute 'etype' indicating IN or OUT
            return ObjectType.AGINEDGE if obj.etype == 'in' else ObjectType.AGOUTEDGE
        else:
            return None  # Invalid object type

    def agrename(self, obj: Union["Node", "Graph"], newname: str) -> bool:
        agerr(Agerrlevel.AGWARN, "Use G.rename() instead of G.agrename()")
        return self.rename(obj, newname)

    def rename(self, obj: Union["Node", "Graph"], newname: str) -> bool:  # from agrename in /cgraph/obj.c
        """
        Renames a node or the enclosed_node.

        :param obj: The object to rename.
        :param newname: The new name for the object.
        :return: True if renaming was successful, False otherwise.
        """
        obj_type = obj.obj_type
        if obj_type == ObjectType.AGGRAPH:
            if newname in self.subgraphs:
                agerr(Agerrlevel.AGINFO, f"[Agraph] Rename failed: Subgraph '{newname}' already exists.")
                return False
            old_name = obj.name
            if old_name in self.subgraphs:
                obj.name = newname
                self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_DELETED, obj)
                self.subgraphs[newname] = self.subgraphs.pop(old_name)
                self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, obj)
                return True
            else:
                return self.rename_graph(newname)
        elif obj_type == ObjectType.AGNODE:
            if newname in self.nodes:
                agerr(Agerrlevel.AGINFO, f"[Agraph] Rename failed: 'Node' '{newname}' already exists.")
                return False
            old_name = obj.name
            obj.name = newname
            self.clos.invoke_callbacks(GraphEvent.NODE_DELETED, self.nodes[old_name])
            self.nodes[newname] = self.nodes.pop(old_name)
            self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, obj)

            agerr(Agerrlevel.AGINFO, f"[Agraph] Node '{old_name}' renamed to '{newname}'.")
            return True
        else:
            agerr(Agerrlevel.AGERR, "agrename not supported for this object type")
            return False

    def rename_graph(self, newname: str) -> bool:
        """
        Renames the enclosed_node.

        :param newname: The new name for the enclosed_node.
        :return: True if renaming was successful, False otherwise.
        """
        old_id = self.id
        root_graph = self.get_root()
        if not root_graph:
            agerr(Agerrlevel.AGERR, "Cannot find root enclosed_node for renaming")
            return False

        # Check if the new name can be reserved
        new_id = self.disc.map(self.clos, ObjectType.AGGRAPH, newname, createflag=False)
        # TODO: not sure how the use of root_graph is special here
        # new_id = agmapnametoid(root_graph, ObjectType.AGGRAPH, newname, createflag=False)
        if new_id is not None:
            if new_id == old_id:
                return True  # Name is unchanged
            else:
                return False  # Name already exists

        # Reserve the new ID
        new_id = self.disc.map(self.clos, ObjectType.AGGRAPH, newname, createflag=False)
        # new_id = agmapnametoid(root_graph, ObjectType.AGGRAPH, newname, createflag=True)
        if new_id is None:
            agerr(Agerrlevel.AGERR, "Failed to reserve new name for enclosed_node")
            return False

        # Free the old ID
        self.disc.free(self.clos, ObjectType.AGGRAPH, old_id)
        # agfreeid(self, ObjectType.AGGRAPH, old_id)
        self.id = new_id
        self.name = newname

        # Handle graph enclosed_node's subgraphs mapping if necessary
        if self.parent:
            self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_DELETED, self.parent.subgraphs[self.name])
            del self.parent.subgraphs[self.name]
            # self.subgraphs[newname] = self.subgraphs.pop(old_name)
            self.parent.subgraphs[newname] = self
            self.clos.invoke_callbacks(GraphEvent.SUBGRAPH_ADDED, self)

        return True

    def agroot(self, obj: Union["Graph", "Node", "Edge"]) -> Optional["Graph"]:
        return self.root_m(obj)

    def root_m(self, obj: Optional[Union["Graph", "Node", "Edge"]]) -> Optional["Graph"]:
        """
        Retrieves the root enclosed_node of the given object.

        :param obj: The object whose root enclosed_node is to be retrieved.
        :return: The root Graph object if exists, else None.
        """
        if obj:
            if isinstance(obj, Graph):
                return obj.parent.root_m(obj) if obj.parent else obj
            elif isinstance(obj, Node):
                return self.root_m(obj.parent)
            elif isinstance(obj, Edge):
                return self.root_m(obj.tail.parent)
            else:
                agerr(Agerrlevel.AGERR, "enclosed_node root of a bad object")
                return None
        else:
            return self.root

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

    @staticmethod
    def get_root(obj: Optional[Union['Graph', 'Node', 'Edge']] = None) -> Optional['Graph']:
        """
        Retrieves the root enclosed_node of a given object.

        :param obj: The enclosed_node object (Graph, Node, or Edge).
        :return: The root Graph object if found, else None.
        """
        if isinstance(obj, Graph) or obj is None:
            return obj.root if hasattr(obj, 'root') else None
        elif isinstance(obj, Node):
            return obj.parent.root if hasattr(obj.parent, 'root') else None
        elif isinstance(obj, Edge):
            return obj.tail.parent.root if hasattr(obj.tail.parent, 'root') else None
        else:
            agerr(Agerrlevel.AGINFO, "[Graph] get_root failed: Unsupported object type.")
            return None


    def get_next_sequence(self, objtype: ObjectType) -> int:
        """
        Retrieves the next sequence number for the given object type.

        :param objtype: The type of the object
            (ObjectType.AGGRAPH, ObjectType.AGNODE, ObjectType.AGEDGE) an ObjectType
            or
            (AGTYPE_GRAPH, AGTYPE_NODE, AGTYPE_EDGE) a string
        :return: The next sequence number.
        """
        # Placeholder for sequence number management
        # For simplicity, increment by 2 to maintain even/odd separation

        # if isinstance(objtype, str):
        #     name = objtype.lower()
        # elif isinstance(objtype, ObjectType):
        #     name = objtype.name.lower()
        # else:
        #     name = "bad_object_type_item"
        # seq_attr = f"_next_seq_{name}"
        # if not hasattr(self.clos['seq'], seq_attr):
        #     setattr(self.clos, seq_attr, 2)  # Initialize at 2
        # seq = getattr(self.clos, seq_attr)
        # setattr(self.clos, seq_attr, seq + 2)
        # return seq

        return self.clos.get_next_sequence(objtype)

    def agraphof(self, obj: Union["Graph", "Node", "Edge"]) -> Optional["Graph"]:
        return self.graph_of(obj)

    def get_graph_of(self, obj: Union["Graph", "Node", "Edge"]) -> Optional["Graph"]:
        return self.graph_of(obj)

    @staticmethod
    def graph_of(obj: Union["Graph", "Node", "Edge"]) -> Optional["Graph"]:
        """
        Retrieves the enclosed_node an object belongs to.

        :param obj: The object whose enclosed_node is to be retrieved.
        :return: The Graph object if exists, else None.
        """
        if isinstance(obj, Graph):
            return obj
        elif isinstance(obj, Node):
            return obj.parent
        elif isinstance(obj, Edge):
            return obj.graph
        else:
            agerr(Agerrlevel.AGERR, f"graph_of obj={obj} is not a recognized object")
            return None

    def agcontains(self, obj:  Union["Graph", "Node", "Edge"]) -> bool:
        """
        Checks if the enclosed_node contains the specified object.
        :param obj: The object to check.
        :return: 1 if contains, 0 otherwise.
        """
        return self.contains(obj)

    def contains(self, obj: Union["Graph", "Node", "Edge"]) -> bool:
        """
        Checks if the enclosed_node contains the specified object.

        :param obj: The object to check for containment.
        :return: True if the enclosed_node contains the object, False otherwise.
        """
        root_graph = self.get_root(obj)
        target_root = self.root
        if root_graph != target_root:
            return False

        obj_type = self.obj_kind(obj)
        if obj_type == ObjectType.AGGRAPH:
            # Traverse enclosed_node hierarchy to see if 'self' is an ancestor
            current = obj.parent
            while current:
                if current == self:
                    return True
                current = current.parent
            return self == obj  # If 'self' is the same as obj

        elif obj_type == ObjectType.AGNODE:
            return obj.name in self.nodes and self.nodes[obj.name] == obj
        elif obj_type in (ObjectType.AGINEDGE, ObjectType.AGOUTEDGE, ObjectType.AGEDGE):
            edge_key = (obj.tail.name, obj.head.name, obj.name)
            return edge_key in self.edges and self.edges[edge_key] == obj
        else:
            return False

    # -------- Discipline Management Methods --------

    def push_discipline(self, cbd: 'Agcbdisc', state: Any):
        """
        Pushes a discipline onto the callback stack.
        Equivalent to 'agpushdisc' in C.

        :param cbd: The callback discipline to push.
        :param state: The state associated with the discipline.
        """
        stack_ent = Agcbstack(f=cbd.callback_functions, state=state, prev=self.clos.cb)
        # stack_ent.f = cbd
        # stack_ent.state = state
        # stack_ent.prev = self.discipline_stack
        # self.discipline_stack = stack_ent
        # self.clos.cb = self.discipline_stack
        # self.agpushdisc(self, cbd, state)

        self.clos.set_callback_stack(stack_ent)
        agerr(Agerrlevel.AGINFO, f"[Graph] Discipline '{cbd.name}' pushed onto the callback stack with state '{state}'.")

    def rec_apply(self, obj: ['Graph', 'Node', 'Edge'], fn: Callable, arg: Any, objsearch: Callable,
                  preorder: bool):  # from cgraph/apply.c
        """
        Recursively apply the function 'fn' to 'obj' (and its images in subgraphs).
        - g: the current Graph
        - obj: the current object (Graph, Node, or Edge)
        - fn: a callback function fn(enclosed_node, obj, arg) Note that 'enclosed_node' must be passed explicitly
        - arg: an arbitrary argument passed to fn
        - objsearch: a function (sub, obj) -> subobj or None
        - preorder: bool, whether to apply 'fn' before or after recursion
        """
        # "preorder" => call the callback before descending to subgraphs
        if preorder:
            fn(self, obj, arg)

        # For every subgraph, see if there's a corresponding object
        for subname, subg in self.subgraphs.items():
            subobj = objsearch(subg, obj)
            if subobj is not None:
                subg.rec_apply(subobj, fn, arg, objsearch, preorder)

        # If not preorder => call the callback after visiting subgraphs
        if not preorder:
            fn(self, obj, arg)

    # todo: agcbdisc needs to be defined or refactored to remove
    def agpopdisc(self, cbd: 'Agcbdisc') -> bool:
        """
        Pops a discipline from the stack.
        :param cbd: The callback discipline.
        :return: SUCCESS (1) if successful, FAILURE (0) otherwise.
        """
        stack_ent = self.clos.cb
        if stack_ent:
            if stack_ent.f == cbd:
                self.clos.cb = stack_ent.prev
            else:
                # Traverse to find the discipline to pop
                current = stack_ent
                while current and current.prev and current.prev.f != cbd:
                    current = current.prev
                if current and current.prev:
                    current.prev = current.prev.prev
            if stack_ent:
                # Assuming agfree is a function to free memory, which is not needed in Python
                # So we just remove the reference
                # del stack_ent
                self.clos.cb = stack_ent.prev
                return True
        return False

    def pop_discipline(self, cbd: 'Agcbdisc') -> bool:
        """
        Pops a discipline from the callback stack.
        Equivalent to 'agpopdisc' in C.

        :param cbd: The callback discipline to pop.
        :return: True if popping was successful, False otherwise.
        """
        stack_ent = self.clos.cb
        prev = None

        while stack_ent:
            if stack_ent.f == cbd.callback_functions:
                if prev:
                    prev.prev = stack_ent.prev
                else:
                    self.clos.cb = stack_ent.prev
                # TODO: Need to understand whether the actual callback is called. Original code doesnt do this

                self.clos.invoke_callbacks(GraphEvent.DELETION, stack_ent)  # Optional: Trigger deletion callbacks
                agerr(Agerrlevel.AGINFO, f"[Graph] Discipline '{cbd.name}' popped from the callback stack.")
                return True
            prev = stack_ent
            stack_ent = stack_ent.prev

        agerr(Agerrlevel.AGINFO, f"[Graph] Discipline '{cbd.name}' not found on the callback stack.")
        return False


    def make_compound_node(self, compound_name: str, existing_node: Optional[Node] = None) -> Optional['Node']:
        """
        Creates a node with a given name into a compound node by creating an internal subgraph and linking it.

        The node remains is maintained in the enclosed_node's node dictionary, but its compound state is stored in its
        'compound_node_data' (an instance of CompoundNode). The internal subgraph is created (via
        create_subgraph) and assigned to compound_node.compound_node_data.subgraph, and is also added
        to the main enclosed_node's subgraphs dictionary.

        This is a slightly refactored version of agcmpnode and agassociate

        :param compound_name: The name to assign to the new internal subgraph.
        :param existing_node: The existing Node that is to be converted into a compound node.
        :return: The newly created subgraph (Graph) if successful; otherwise, None.
        """

        # This is like the agcmpnode
        if existing_node:
            compound_node = existing_node
        else:
            compound_node = self.add_node(f"{compound_name}Node")

        # Neither of these checks should fail with a newly created node
        # Ensure the node has a CompoundNode instance in its compound_node_data.
        if not hasattr(compound_node, "compound_node_data"):
            if compound_node.compound_node_data.is_compound:
                agerr(Agerrlevel.AGWARN, f"Node '{compound_node.name}' is already a compound node.")
                return compound_node.compound_node_data.subgraph
        # Reset the compound node data
        compound_node.compound_node_data = CompoundNode()
        # Create the internal subgraph.
        # Since the enclosed_node is passed then this will become a compound node
        new_subgraph = self.create_subgraph(name=compound_name, enclosed_node=compound_node)
        if new_subgraph is None:
            agerr(Agerrlevel.AGERR, f"Failed to create subgraph for compound node '{compound_node.name}'.")
            return None
        # 1) Avoid cycle: If compound_node already is registered in subgraphs, fail
        if compound_node.name in self.subgraphs:
            # That implies compound_node is a subnode of new_subgraph
            return None

        # Mark the node as compound by updating its CompoundNode instance.
        if not compound_node.compound_node_data.is_compound:
            agerr(Agerrlevel.AGERR, f"Subgraph is not marked as a compound node '{compound_node.name}'.")

        # 2) Link the subgraph and the node
        # compound_node.compound_node_data.subgraph = new_subgraph
        # new_subgraph.cmp_graph_data.node = compound_node
        # Optionally, you might want to set additional fields in the CompoundNode, e.g. reset hidden flag.
        # compound_node.compound_node_data.hidden = False
        # compound_node.set_compound_data("centrality", self.compute_centrality(compound_node))

        # Check that the new subgraph is registered in the graph enclosed_node's subgraphs dictionary.
        if self.subgraphs[compound_name] != new_subgraph:
            agerr(Agerrlevel.AGERR, f"{compound_name} is not in self.subgraphs[...]")

        # Set the enclosed_node pointer of the new subgraph to this enclosed_node.
        # Check that the enclosed_node of the subgraph is the same as this enclosed_node
        if new_subgraph.parent != self:
            agerr(Agerrlevel.AGERR, f"{compound_name} enclosed_node != {self.name}.")

        agerr(Agerrlevel.AGINFO, 
            f"Compound node '{compound_node.name}' created. Its subgraph '{compound_name}' is now linked into the enclosed_node structure.")
        return compound_node

    def map_name_to_id(self, objtype: ObjectType, name: Optional[str], createflag: bool) -> Optional[int]: # from /cgraph/id.c
        """
        Maps a name to an ID, creating it if 'createflag' is True.
        Equivalent to agmapnametoid in C.
        """
        agerr(Agerrlevel.AGWARN, "Use self.disc.map() instead")
        return self.disc.map(self.clos, objtype, name, createflag)


    # -------- Callback Management Methods --------


    def method_init(self):
        """
        Initializes or resets the enclosed_node's internal state.
        Equivalent to 'method_init' in the original C implementation.

        This method performs tasks such as:
        - Clearing existing nodes, edges, and subgraphs.
        - Resetting callbacks.
        - Setting up default attributes if necessary.
        """
        if self.initialized:
            agerr(Agerrlevel.AGWARN, f"[Graph] Graph '{self.name}' is already initialized.")
            return

        # Clear existing data structures
        self.nodes.clear()
        self.edges.clear()
        self.subgraphs.clear()

        # Reset callbacks
        self.clos.reset()
        self._strdict.clear()
        # Initialize subgraph dictionary and name-to-id mapping
        self.id_to_subgraph.clear()
        self.subgraphs.clear()
        # self.subgraph_name_to_id.clear()
        # self._id_counter = 1

        # Optionally, register default callbacks or set default attributes
        # For example, you might want to set default enclosed_node attributes here
        self.initialized = True
        agerr(Agerrlevel.AGINFO, f"[Graph] Graph '{self.name}' has been initialized.")


    def agmethod_upd(self, obj: Union['Graph', 'Node', 'Edge'], sym: AgSym):  # from /cgraph/obj.c
        # void agmethod_upd(Agraph_t * g, void *obj, Agsym_t * sym)
        # {
        # if (g->clos->callbacks_enabled)
        if self.clos.callbacks_enabled:
            if self.clos.cb:
                self.agupdcb(obj, sym, self.clos.cb)
            else:
                agerr(Agerrlevel.AGINFO, "[Graph] Callback stack 'cb' is not set.")
        else:

            cb_modify = GraphEvent.MODIFY
            self.agrecord_callback(obj, cb_modify, sym)
            # 	agrecord_callback(g, obj, CB_UPDATE, sym);
        # }

    # -------- Callback Update Method (agupdcb) --------

    def agupdcb(self, obj: Union['Graph', 'Node', 'Edge'],
                sym: Optional[Union[AgSym, str]] = None,
                cbstack: Optional[Agcbstack] = None):
        """
        Updates callbacks for a enclosed_node object based on the callback system state.
        Equivalent to the C 'agupdcb' function.

        :param obj: The enclosed_node object (Graph, Node, or Edge) to update.
        # TODO: This needs to handle strings that represent an attribute in AgSym
        :param sym: The symbol associated with the update.
        :param cbstack: The current callback stack node.
        """
        if isinstance(sym, str):
            new_id = self.disc.map(state=self.clos, ot=obj.obj_type, name=None, createflag=True)
            new_sym = AgSym(name=sym, defval="", attr_id=new_id, kind=obj.obj_type)
            sym = new_sym

        if self.clos.callbacks_enabled:
            if self.clos.cb:
                if cbstack is None:
                    return

                # Recursively initialize callbacks with the previous stack node
                self.agupdcb(obj, sym, cbstack.prev)

                fn = None
                # Determine the type of the object and retrieve the corresponding 'mod' function
                if isinstance(obj, Graph):
                    fn = cbstack.f.graph.mod
                elif isinstance(obj, Node):
                    fn = cbstack.f.node.mod
                elif isinstance(obj, Edge):
                    fn = cbstack.f.edge.mod
                # If a function is found, invoke it
                if fn:
                    fn(self, obj, cbstack.state, sym)
            else:
                agerr(Agerrlevel.AGINFO, "[Graph] Callback stack 'cb' is not set.")
        else:
            # Record the 'mod' callback for later initialization
            CB_MODIFY = GraphEvent.MODIFY
            self.agrecord_callback(obj, CB_MODIFY, sym)

    def method_update(self,  event: GraphEvent, callback: Callable, action: str = 'add'):
        """
        Updates callbacks when an attribute changes.

        :param event: The event name type to add or delete:
            GraphEvent.NODE_ADDED = 'node_added'
            GraphEvent.NODE_DELETED = 'node_deleted'
            GraphEvent.EDGE_ADDED = 'edge_added'
            GraphEvent.EDGE_DELETED = 'edge_deleted'
            GraphEvent.SUBGRAPH_ADDED = 'subgraph_added'
            GraphEvent.SUBGRAPH_DELETED = 'subgraph_deleted'
            GraphEvent.INITIALIZE = 'initialize'
            GraphEvent.MODIFY = 'modify'  # Added 'modify' event
            GraphEvent.DELETION = 'deletion'  # Added 'deletion' event
        :param callback: The callback function to update.
        :param action: The action to perform ('add' or 'remove' or 'remove-all').
        :raises ValueError: If the event is unknown or the action is invalid.
        """
        # agmethod_upd(self, obj, sym)
        if action not in ('add', 'remove', 'remove-all'):
            raise ValueError(f"[Graph] Unknown action '{action}' for method_update. Use 'add' or 'remove'.")

        if action == 'add':
            self.clos.register_callback(event, callback)
            agerr(Agerrlevel.AGINFO, f"[Graph] Callback added for event '{event}'.")
        elif action == 'remove':
            self.clos.unregister_callback(event, callback)
            agerr(Agerrlevel.AGINFO, f"[Graph] Callback removed for event '{event}'.")
        elif action == 'remove-all':
            self.clos.reset_callbacks(event)
            agerr(Agerrlevel.AGINFO, f"[Graph] All callbacks removed for event '{event}'.")

    def agmethod_delete(self, obj: Union['Agobj', List['Agobj'], str]):  # from cgraph/cghdr.h
        """
        Deletes callbacks for a enclosed_node object based on the callback system state.
        Equivalent to 'agmethod_delete' in C.
        C Functionality: Deletes callback methods for a enclosed_node object. It either deletes callbacks immediately or
        records the deletion for later based on whether callbacks are enabled.

        Implementation: Similar to agmethod_init and agmethod_upd, but handles deletion callbacks
        :param obj: The enclosed_node object (Graph, Node, or Edge) to delete callbacks for.

        """
        if isinstance(obj, list):
            for item in obj:
                self.agmethod_delete(item)  # Recursive call for each item
        # handle string
        if isinstance(obj, str):
            obj_node = self.find_node_by_name(obj)
            if obj_node:
                obj = obj_node
            else:
                obj_edge = self.find_edge_by_name(obj)
                if obj_edge:
                    obj = obj_edge
                else:
                    obj_graph = self.find_graph_by_name(obj)
                    if obj_graph:
                        obj = obj_graph
                    else:
                        agerr(Agerrlevel.AGERR, f"Object {obj} not found for calling a delete "
                                                f"callback deletion. Must be a valid Node, Edge, "
                                                f"or Graph name.")
                        return

        if self.clos.callbacks_enabled:
            if self.clos.cb:
                self.agdelcb(obj, self.clos.cb)
            else:
                agerr(Agerrlevel.AGINFO, "[Graph] Callback stack 'cb' is not set.")
        else:
            # Just post the deletion callback
            CB_DELETION = None
            if isinstance(obj, Node):
                CB_DELETION = GraphEvent.NODE_DELETED
            elif isinstance(obj, Edge):
                CB_DELETION = GraphEvent.EDGE_DELETED
            elif isinstance(obj, Graph):
                CB_DELETION = GraphEvent.SUBGRAPH_DELETED
            if CB_DELETION:
                self.agrecord_callback(obj, CB_DELETION, None)

    def agdelete(self, obj: Agobj):  # from /cgraph/obj.c
        self.method_delete(obj)

    def method_delete(self,  obj: Union['Agobj', List['Agobj'], str]):
        """
        Deletes one or more enclosed_node elements (node, edge, or subgraph) from the enclosed_node.

        :param obj: A single Agobj instance or a list of Agobj instances to delete.
        :raises TypeError: If the object type is unsupported.
        """
        if isinstance(obj, list):
            for item in obj:
                self.method_delete(item)  # Recursive call for each item
        else:
            if isinstance(obj, str):
                obj_node = self.find_node_by_name(obj)
                if obj_node:
                    obj = obj_node
                else:
                    obj_edge = self.find_edge_by_name(obj)
                    if obj_edge:
                        obj = obj_edge
                    else:
                        obj_graph = self.find_graph_by_name(obj)
                        if obj_graph:
                            obj = obj_graph
                        else:
                            agerr(Agerrlevel.AGERR, f"Object {obj} not found for deletion. "
                                                    f"Must be a valid Node, Edge, or Graph name.")
                            return
            if isinstance(obj, Node):
                self.delete_node(obj)
            elif isinstance(obj, Edge):
                self.delete_edge(obj)
            elif isinstance(obj, Graph):
                self.delete_subgraph(obj)
            else:
                raise TypeError("Unsupported object type for deletion. Must be Node, Edge, Graph or a name.")

    # -------- Augmented Mapping Methods --------
    def internal_map_lookup(self, objtype: ObjectType, name: str) -> Optional[int]:
        """
        Equivalent to aginternalmaplookup: looks up the ID for a given name and objtype.
        Returns the ID if found, else None.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        return self.clos.lookup_by_name[objtype].get(name)

    def internal_map_insert(self, objtype: ObjectType, name: str, id_: int):
        """
        Equivalent to aginternalmapinsert: inserts a new name-ID mapping.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        self.clos.lookup_by_name[objtype][name] = id_
        self.clos.lookup_by_id[objtype][id_] = name

    def internal_map_print(self, objtype: ObjectType, id_: int) -> Optional[str]:
        """
        Equivalent to aginternalmapprint: returns the name associated with an ID.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        return self.clos.lookup_by_id[objtype].get(id_)

    def internal_map_delete(self, objtype: ObjectType, id_: int) -> bool:
        """
        Equivalent to aginternalmapdelete: deletes the name-ID mapping for the given ID.
        Returns True if deleted, False otherwise.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        name = self.clos.lookup_by_id[objtype].get(id_)
        if name:
            del self.clos.lookup_by_id[objtype][id_]
            del self.clos.lookup_by_name[objtype][name]
            return True
        return False

    def internal_map_clear_local_names(self):
        """
        Equivalent to aginternalmapclearlocalnames: removes all mappings where name starts with LOCALNAMEPREFIX.
        """
        for objtype in ObjectType:
            lookup_name = self.clos.lookup_by_name[objtype]
            names_to_remove = [name for name in lookup_name if name.startswith(LOCALNAMEPREFIX)]
            for name in names_to_remove:
                id_ = lookup_name[name]
                del lookup_name[name]
                del self.clos.lookup_by_id[objtype][id_]

    def internal_map_close(self):
        """
        Equivalent to aginternalmapclose: closes all mapping dictionaries.
        """
        for objtype in ObjectType:
            self.clos.lookup_by_name[objtype].clear()
            self.clos.lookup_by_id[objtype].clear()

    # CGRAPH_API extern Agdesc_t Agdirected;
    # CGRAPH_API extern Agdesc_t Agstrictdirected;
    # CGRAPH_API extern Agdesc_t Agstrictundirected;
    # CGRAPH_API extern Agdesc_t Agundirected;
    # CGRAPH_API extern Agdisc_t AgDefaultDisc;
    # CGRAPH_API extern Agiddisc_t AgIdDisc;
    # CGRAPH_API extern Agiodisc_t AgIoDisc;
    # CGRAPH_API extern Agmemdisc_t AgMemDisc;
    def agalloc(self,  size: 'int') -> None:
        # This should never be used in Python
        raise NotImplementedError



    def agattr(self, kind: ObjectType, name: str, value: Optional[str] = None):
        """
        Create or update an attribute descriptor for the enclosed_node.

        If a value is provided, the attribute is created or updated (like an assignment).
        If no value is provided, it simply returns the current attribute descriptor (if any).

        :param kind: The type of the attribute (AGGRAPH, AGNODE, or AGEDGE).
        :param name: The name of the attribute.
        :param value: The new value for the attribute; if None, perform a lookup only.
        :return: An AgSym instance representing the attribute descriptor,
                 or None if not found (when value is None).
        """
        # In C, if g is NULL the function creates a ProtoGraph; here we assume self is valid.

        root = get_root_graph(self)
        if kind == ObjectType.AGGRAPH:
            adict = root.attr_dict_g
        elif kind == ObjectType.AGNODE:
            adict = root.attr_dict_n
        elif kind in (ObjectType.AGEDGE, ObjectType.AGINEDGE, ObjectType.AGOUTEDGE):
            adict = root.attr_dict_e
        else:
            return None
        adict[name] = value
        return adict[name]

    def declare_attribute_graph(self, attr_name: str, default_value: str):
        """
        Declare a new attribute for the GRAPH itself. Store the default in root enclosed_node's dict.
        """
        self.agattr(kind=ObjectType.AGGRAPH, name=attr_name, value=default_value)

    def declare_attribute_node(self, attr_name: str, default_value: str):
        """
        Declare a new attribute for NODES with a default value.
        """
        self.agattr(kind=ObjectType.AGNODE, name=attr_name, value=default_value)

    def declare_attribute_edge(self, attr_name: str, default_value: str):
        """
        Declare a new attribute for EDGES with a default value.
        """
        self.agattr(kind=ObjectType.AGEDGE, name=attr_name, value=default_value)


    def agcallbacks(self,  flag: 'int') -> 'int': #  return prev value #
        raise NotImplementedError

    def agcanon(self, c: 'str', i: int) -> 'str':
        raise NotImplementedError

    def agcanonStr(self, s: 'str') -> 'str': #  manages its own buf #
        raise NotImplementedError

    def agconcat(self,  chan: Any, disc: AgIdDisc) -> 'Graph':
        pass

    def agcopyattr(self, oldobj: Any, newobj: Any) -> 'int':
        raise NotImplementedError

    def agcountuniqedges(self,  n: 'Node',  in_: 'int', out: 'int') -> 'int':
        raise NotImplementedError

    def agdegree(self,  n: 'Node',  in_: 'int', out: 'int') -> 'int':
        raise NotImplementedError

    def agfree(self,  ptr: Any) -> None:
        # This should never be used in Python
        raise NotImplementedError

    def agedge(self,  tail_name: str,  head_name: str, name: Optional[str], cflag: bool) -> Optional[Edge]:
        """
        Pythonic version of 'agedge(Agraph_t *g, Agnode_t *t, Agnode_t *h, char *name, int cflag)'.
        - If name is given, we might do ID-based logic. We'll keep it simpler here:
          we see if there's an existing edge with the same key. If yes, return it.
          If not, possibly create a new edge.
        - cflag: create edge if it doesn't exist
        """
        tail = self.add_node(tail_name)
        head = self.add_node(head_name)

        # In real cgraph, 'name' might map to an ID. Let's skip that and just store 'name' in the edge as a label.
        key = (tail_name, head_name, name)
        e = self.edges.get(key)
        if e:
            return e

        # If strict/no_loop checks fail, return None
        if not ok_to_make_edge(self, tail, head):
            if cflag:
                return None
            else:
                return None  # same result in either case

        # Otherwise, create a new edge
        eid = self.get_next_sequence(ObjectType.AGEDGE)
        # g._next_edge_id += 1
        # tail: Node, head: Node, name: str, enclosed_node: Graph, id=None, seq=None, etype: str=None):
        out_e = Edge(tail=tail, head=head, name=name, graph=self, id_=eid,
                     seq=self.get_next_sequence(ObjectType.AGEDGE), etype=EdgeType.AGOUTEDGE)

        # Insert adjacency
        tail.outedges.append(out_e)
        head.inedges.append(out_e)  # We'll store the same Edge object for in-edge too

        # Insert into the dictionary, Edge should store itself in the Graph already
        if key not in self.edges:
            self.edges[key] = out_e
        return out_e


    def agfstedge(self,  n: 'Node') -> 'Edge':
        return agfstedge(self, n)

    def agfstin(self,  n: 'Node') -> 'Edge':
        return agfstin(self, n)

    def agfstout(self,  n: 'Node') -> 'Edge':
        return agfstout(self, n)

    def agidedge(self, t: 'Node', h: 'Node', eid, c_flag) -> 'Edge':
        return agidedge(self, t, h, eid, c_flag)

    def agnxtedge(self, e: 'Edge', n: 'Node') -> 'Edge':
        return agnxtedge(self, e, n)

    def agnxtin(self, e: 'Edge') -> 'Edge':
        return agnxtin(self, e)

    def agnxtout(self, e: 'Edge') -> 'Edge':
        return agnxtout(self, e)

    def agsubedge(self, e: 'Edge', createflag: 'int') -> 'Edge':
        raise NotImplementedError

    def agfstnode(self) -> 'Node':
        raise NotImplementedError

    def agidnode(self,  id, createflag: 'int') -> 'Node':
        raise NotImplementedError

    def aginternalmapclearlocalnames(self) -> None:
        self.internal_map_clear_local_names()

    def aglasterr(self) -> 'str':
        raise NotImplementedError

    def aglstnode(self) -> 'Node':
        return self.last_node()

    def agmemconcat(self,  cp: 'str') -> 'Graph':
        raise NotImplementedError

    def agmemread(self, cp: 'str') -> 'Graph':
        raise NotImplementedError

    def agnode(self,  name: 'str', createflag: bool) -> 'Node':
        return self.add_node(name, createflag)

    def agnodebefore(self, u: 'Node', v: 'Node') -> 'int':  #  we have no shame #
        raise NotImplementedError

    def agnxtattr(self,  kind: 'int', attr: AgSym) -> AgSym:
        raise NotImplementedError

    def agnxtnode(self,  n: 'Node') -> 'Node':
        raise NotImplementedError

    def agopen(name: 'str',  desc: Agdesc, disc: AgIdDisc) -> 'Graph':
        return Graph(name=name, description=desc, disc=disc)

    def agprvnode(self,  n: 'Node') -> 'Node':
        return self.previous_node(current=n)

    def agread(self, chan: Any,  disc: AgIdDisc) -> 'Graph':
        raise NotImplementedError

    def agreadline(self, int_) -> None:
        raise NotImplementedError

    def agrealloc(self,  ptr: Any, oldsize: int) -> None:
        # This should never be used in Python
        raise NotImplementedError

    def agreseterrors(self) -> 'int':
        raise NotImplementedError

    def agseterr(self, elevel: "Agerrlevel") -> "Agerrlevel":
        raise NotImplementedError

    def agseterrf(self, f: 'str'):  # -> "Agusererrf":
        raise NotImplementedError

    def agsetfile(self, c: 'str') -> None:
        raise NotImplementedError

    def agstrcanon(self, a: 'str', b: 'str') -> 'str':
        raise NotImplementedError

    def agsubnode(self,  g: 'Graph', n: 'Node',  createflag: bool) -> 'Node':
        return self.add_subgraph_node(g, n, createflag)

    def agsubrep(self,  n: 'Node') -> "Node":
        return agsubrep(self, n)

    def agwarningf(self, fmt: 'str') -> None:
        raise NotImplementedError

    def agwrite(self,  c: Any) -> 'int':
        raise NotImplementedError

    def agxget(self, obj: Any, sym: AgSym) -> 'str':
        raise NotImplementedError

    def agxset(self, obj: Any, sym: AgSym, value: 'str') -> 'int':
        raise NotImplementedError


    def agflatten_edges(self, n: Node, flag: int):
        """
        If flag is nonzero => switch to list
        If flag is zero => switch to set
        We basically call 'agflatten_elist' on outedges and inedges.
        """
        # 2.2 agflatten_edges(g, n, flag)
        # void agflatten_edges(Agraph_t * g, Agnode_t * n, int flag) {
        #     Agsubnode_t *sn = agsubrep(g,n);
        #     ...
        #     agflatten_elist(g->e_seq, &sn->out_seq, flag);
        #     agflatten_elist(g->e_seq, &sn->in_seq, flag);
        # }
        # Simpler version
        # In cgraph, 'agsubrep(g,n)' checks if n is in g. We'll just assume it is.
        to_list = bool(flag)  # if flag=1 => to_list
        n.agflatten_elist(outedge=True, to_list=to_list)
        n.agflatten_elist(outedge=False, to_list=to_list)

    def agflatten(self, flag: int):
        """
        If flag != 0 and g.desc.flatlock is False => switch to list mode (flatten).
        If flag == 0 and g.desc.flatlock is True  => switch to set mode.
        For each node in g, call agflatten_edges(g, node, flag).
        Then set g.desc.flatlock accordingly.
        """
        #  Note: The flatten.c code also calls dtmethod(g->n_seq,Dtlist) or dtmethod(g->n_seq,Dtoset), meaning the dictionary of
        #  nodes itself changes from a set-based iteration to a list-based iteration.
        #  In Python, we might interpret that differently, but the main effect is toggling how edges
        #  (and possibly nodes) are stored/traversed.

        # Summary
        # We extended Graph, Node, and Edge with a flatlock flag on Graph and adjacency stored as either list or set in Node.
        # The functions agflatten_elist, agflatten_edges, and agflatten replicate the logic from the snippet,
        # toggling the data structure used for adjacency.
        #       flag=1 => flatten to “list mode.”
        #       flag=0 => revert to “set mode.”
        # In this way, we conceptually mirror how the original C code changes the dictionaries’ methods (Dtlist, Dtoset)
        # to flatten or unflatten a enclosed_node’s nodes and edges.

        if flag:  # want list mode
            if not self.desc.flatlock:
                # Switch all nodes to list mode
                for node in self.nodes.values():
                    self.agflatten_edges(node, flag)
                self.desc.flatlock = True
        else:  # want set mode
            if self.desc.flatlock:
                # Switch all nodes to set mode
                for node in self.nodes.values():
                    self.agflatten_edges(node, flag)
                self.desc.flatlock = False


def gather_all_subgraphs(g) -> List[Graph]:
    """Return a list of g plus all nested subgraphs (recursively)."""
    result = [g]
    for sg in g.subgraphs.values():
        result.extend(gather_all_subgraphs(sg))
    return result

def get_root_graph(g) -> 'Graph':
    """
    If g is a Graph, climb up the .enclosed_node chain to find the root.
    If it's not a enclosed_node, assume .enclosed_node is. This is a convenience
    for attribute dictionary lookups.
    """
    if isinstance(g, Graph):
        while g.parent:
            g = g.parent
        return g
    else:
        return get_root_graph(g.parent)


###################
# NODE REFERENCES #
###################

def FIRSTNREF(g: "Graph"):
    """
    #define FIRSTNREF(g) (agflatten(g,1), AGHEADPOINTER(g))
    :param g:
    :return:
    """
    g.agflatten(1)
    # If g.nodes is a dict, pick the “first” in insertion order
    # (Python 3.7+ iteration is insertion-ordered)
    if not g.nodes:
        return None
    first_name = next(iter(g.nodes.keys()))
    return g.nodes[first_name]


def NEXTNREF(g: "Graph", rep: "Node"):
    """
    #define NEXTNREF(g, rep) (AGRIGHTPOINTER(rep) == AGHEADPOINTER(g)? 0 : AGRIGHTPOINTER(rep))
    :param g:
    :param rep:
    :return:
    """
    node_list = list(g.nodes.values())  # flattened iteration
    try:
        idx = node_list.index(rep)
    except ValueError:
        return None
    if idx + 1 < len(node_list):
        return node_list[idx + 1]
    else:
        return None

def PREVNREF(g: "Graph", rep: "Node"):
    """
    #define PREVNREF(g, rep) (((rep)==AGHEADPOINTER(g))?0:(AGLEFTPOINTER(rep)))
    :param g:
    :param rep:
    :return:
    """
    node_list = list(g.nodes.values())
    try:
        idx = node_list.index(rep)
    except ValueError:
        return None
    if idx > 0:
        return node_list[idx - 1]
    else:
        return None


def LASTNREF(g: "Graph"):
    """
    #define LASTNREF(g) (agflatten(g,1), AGHEADPOINTER(g)?AGLEFTPOINTER(AGHEADPOINTER(g)):0)
    :param g:
    :return:
    """
    g.agflatten(1)
    node_list = list(g.nodes.values())
    if node_list:
        return node_list[-1]
    return None


def NODEOF(rep: "Node"):
    """
    #define NODEOF(rep) ((rep)->node)
    :param rep:
    :return:
    """
    # If 'rep' is already the node object, just return rep
    return rep


###################
# EDGE REFERENCES #
###################
def FIRSTOUTREF(g: "Graph", sn: "Node"):
    """
    #define FIRSTOUTREF(g, sn) (agflatten(g,1), (sn)->out_seq)
    :param g:
    :param sn:
    :return:
    """
    g.agflatten(1)
    return sn.outedges[0] if sn.outedges else None


def LASTOUTREF(g: "Graph", sn: "Node"):
    """
    #define LASTOUTREF(g, sn) (agflatten(g,1), (Agedgeref_t*)dtlast(sn->out_seq))
    :param g:
    :param sn:
    :return:
    """
    g.agflatten(1)
    return sn.outedges[-1] if sn.outedges else None


def FIRSTINREF(g: "Graph", sn: "Node"):
    """
    #define FIRSTINREF(g, sn) (agflatten(g,1), (sn)->in_seq)
    :param g:
    :param sn:
    :return:
    """
    g.agflatten(1)
    return sn.inedges[0] if sn.inedges else None


def NEXTEREF(g: "Graph", rep: "Edge", edgelist: List["Edge"]):
    """
    #define NEXTEREF(g, rep) ((rep)->right)

    'rep' is the current Edge. Return the next Edge in 'edgelist', or None if none.
    You must pass the relevant edgelist (like sn.outedges) or do a search.
    """
    try:
        idx = edgelist.index(rep)
    except ValueError:
        return None
    if idx + 1 < len(edgelist):
        return edgelist[idx + 1]
    return None


def PREVEREF(g: "Graph", rep: "Edge", edgelist: List["Edge"]):
    """
    #define PREVEREF(g, rep) ((rep)->hl._left)
    :param g:
    :param rep:
    :param edgelist:
    :return:
    """
    try:
        idx = edgelist.index(rep)
    except ValueError:
        return None
    if idx > 0:
        return edgelist[idx - 1]
    return None

def AGSNMAIN(sn: Node) -> bool:
    """
    In cgraph, checks if 'sn' is the main subnode of 'sn->node->mainsub'.
    Python: If we unify subnode with node, you might skip this check.
    """
    is_subgraph = False
    if sn.compound_node_data.is_compound:
        is_subgraph = sn.compound_node_data.subgraph is None
    return is_subgraph  # or some trivial check

