

"""
Below is an example of how you might translate (and slightly adapt) the original C code into Python, using the classes (Agobj, Graph, Node, Edge) shown previously.

We'll need to introduce a few key ideas to mirror the C code:

    1) A way to determine which enclosed_node an object (node or edge) “belongs to” (akin to agraphof(obj)).
    2) A method to look up the “same” node or edge in a subgraph (akin to agsubnode, agsubedge).
    3) A recursive mechanism to apply a callback to an object in the main enclosed_node and all corresponding objects in subgraphs (akin to rec_apply and agapply).

Below is a complete, minimal Python version. The main changes from our previous Python classes:

    - We store a reference to the graph enclosed_node in each Node and Edge (so we can quickly check “which enclosed_node” the object belongs to).
    - We implement helper functions (subnode_search, subedge_search, subgraph_search) that attempt to find the corresponding object in a subgraph.
    - We implement rec_apply and agapply using a Python-style callback.


Below is a Python version that expands our original Graph, Node, and Edge classes to include attribute dictionaries (similar to Agdatadict_t, Agsym_t, Agattr_t, etc. in the C code). It also provides helper functions corresponding to key Graphviz operations (e.g., agattr, agget, agset, etc.). This is not a line-by-line port but rather a conceptual translation capturing the same ideas:

Objects (Graph, Node, Edge) maintain references to:

    A dictionary of declared attributes (name -> AgSym).
    A storage of actual string values for each declared attribute.
    Symbols (AgSym) loosely represent the C Agsym_t, storing:

    The attribute name (e.g., "color", "label").
    A default value.
    A numeric ID that indexes into the owner’s attribute storage (like sym->id).
    Attribute Records (AgAttrRecord) store the string values for a given object, keyed by the attribute’s ID.

Initialization:

    Declaring a new attribute in the root enclosed_node automatically gives it a new AgSym.id
    and sets default values on existing subgraphs/nodes/edges.
    If an attribute is locally overridden in a subgraph, that subgraph has its own entry.
    Helper Functions:

    agattr(...), agget(...), agset(...), agattrsym(...) mimic the usage in the C code.
    We keep them as Python stand-alone functions or as methods on Graph.
    Below is one possible Python design that balances simplicity with fidelity to the C approach. You can tailor it as needed.

"""
import threading
from contextlib import contextmanager
from enum import Enum
from typing import Callable, Optional, List, Dict, Tuple, Union, Any

from collections import deque

from typing import TYPE_CHECKING


# Forward declarations: these imports are only for type checking.
if TYPE_CHECKING:
    from .Headers import *
    from .CGError import *
    from .CGNode import Node, CompoundNode
    from .CGEdge import Edge

from .Headers import *
from .CGNode import Node
from .CGEdge import Edge
from .CGGraph import Graph


# def streq(a, b):
#     """Mimic the C inline function streq(a,b) == (strcmp(a,b)==0)."""
#     return a == b


def agerrorf(fmt: 'str') -> None:
    raise NotImplementedError

def agerrors() -> 'int':
    raise NotImplementedError


def iofread(chan, bufsize):
    """
    Pythonic equivalent of iofread().
    chan: a file-like object (e.g. sys.stdin, open() result, io.StringIO, etc.)
    bufsize: maximum number of characters to read from a single line
    Returns a tuple (nread, text), where:
      - nread is the number of characters actually read
      - text is the read string
    """
    line = chan.readline()
    if not line:
        # No data read (EOF or error)
        return 0, ""
    # If the line is longer than bufsize, truncate
    text = line[:bufsize]
    return len(text), text


def ioputstr(chan, text):
    """
    Pythonic equivalent of ioputstr().
    chan: a file-like object
    text: the string to write
    Returns the number of characters written, or -1 on error.
    """
    try:
        written = chan.write(text)
        # Some Python file-like objects return None if successful (especially older ones).
        # We can standardize on returning the length of text written.
        if written is None:
            written = len(text)
        return written
    except Exception as e:
        return e # error


def ioflush(chan):
    """
    Pythonic equivalent of ioflush().
    chan: a file-like object
    Returns 0 if success, -1 if error.
    """
    try:
        chan.flush()
        return 0
    except Exception as e:
        return e



class AgIoDisc:  # from /cgraph/enclosed_node.c (implemented in io.c)
    def __init__(self):
        self.read = iofread
        self.putstr = ioputstr
        self.flush = ioflush

class Agcbdisc:
    """
    Represents a callback discipline, encapsulating callback functions and state.
    """
    def __init__(self, name: str, callback_functions: 'CallbackFunctions'):
        self.name = name
        self.callback_functions = callback_functions


# class Agdisc:  # from /cgraph/enclosed_node.c
#     """Equivalent to 'Agdisc_t' in C."""
#     def __init__(self, mem=None, id=None, io=None):
#         self.mem = mem if mem else Agmemdisc()
#         self.id = id if id else AgIdDisc()
#         self.io = io if io else AgIoDisc()
#
# # The default discipline:
# AgDefaultDisc = Agdisc()



# Closure (Agclos_t)
# Holds references to the discipline pointers, some “state” closures, sequence counters, etc.:
#
# class Agmemdisc:  # forward definition
#     pass
#




# # Discipline (Equivalent to Agdisc_t)
# # In C, Agdisc_t points to memory, ID, and I/O “disciplines.” We’ll store placeholders in Python:
# class Agmemdisc:  # from /cgraph/mem.c, used in /cgraph/enclosed_node.c
#     """
#     Memory management discipline class replicating Agmemdisc_t from C.
#     Manages memory allocations, reallocations, and deallocations.
#     """
#
#     def open(self) -> Optional[dict]:
#         """
#         Initializes the memory discipline.
#         Equivalent to 'memopen' in C.
#
#         :param disc: The discipline object (unused in this implementation).
#         :return: None (since 'memopen' returns NULL in C).
#         """
#         # In C, 'memopen' returns NULL and is unused.
#
#         return {}  # e.g. a dict as "memory arena"
#
#     def alloc(self, memclosure, memclosure_size: int) -> Optional[bytearray]:
#         """
#         Allocates a memory block of the specified size, initialized to zero.
#         Equivalent to 'memalloc' in C using calloc.
#
#         :param memclosure: The memory heap/state (unused in this implementation).
#         :param memclosure_size: The size of the memory block to allocate.
#         :return: A bytearray of the requested size or None if allocation fails.
#
#         # We can't literally allocate. We'll just create the object
#         """
#         try:
#             return bytearray(memclosure_size)  # Initialized to zero
#         except MemoryError:
#             return None
#
#     def resize(self, memclosure, ptr: bytearray, oldsize: int, request: int) -> Optional[bytearray]:
#         """
#         Resizes an existing memory block from 'oldsize' to 'request'.
#         Equivalent to 'memresize' in C using realloc and memset.
#
#         :param memclosure: The memory heap/state (unused in this implementation).
#         :param ptr: The existing memory block (bytearray) to resize.
#         :param oldsize: The current size of the memory block.
#         :param request: The new desired size of the memory block.
#         :return: The resized bytearray or None if reallocation fails.
#         """
#         try:
#             if request > oldsize:
#                 # Extend the bytearray with zeros
#                 ptr.extend([0] * (request - oldsize))
#             elif request < oldsize:
#                 # Truncate the bytearray to the new size
#                 del ptr[request:]
#             return ptr
#         except MemoryError:
#             return None
#
#     def free(self, memclosure, ptr: bytearray):
#         """
#         Frees the allocated memory block.
#         Equivalent to 'memfree' in C using free.
#         In Python, memory is managed automatically, so this is a no-op.
#
#         :param memclosure: The memory heap/state (unused in this implementation).
#         :param ptr: The memory block (bytearray) to free.
#         """
#         # No action needed; Python's garbage collector handles memory.
#         pass
#
#     def close(self, memclosure):
#         pass


# Singleton instance of the default memory discipline
# AgMemDisc = Agmemdisc()

#
# def agalloc(g: Graph, size: int) -> bytearray:# from /cgraph/mem.c,
#     """
#     Allocates a memory block of the specified size using the enclosed_node's memory discipline.
#     Equivalent to 'agalloc' in C.
#
#     :param g: The enclosed_node object, expected to have 'disc.mem' and 'clos.mem' attributes.
#     :param size: The size of the memory block to allocate.
#     :return: A bytearray representing the allocated memory.
#     :raises MemoryError: If memory allocation fails.
#     """
#     mem = g.disc.mem.alloc(g.clos.mem, size)
#     if mem is None:
#         agerr(Agerrlevel.AGERR, "memory allocation failure")
#     return mem


# def agrealloc(g: Graph, ptr: Optional[bytearray], oldsize: int, size: int) -> Optional[bytearray]:  # from /cgraph/mem.c,
#     """
#     Reallocates (resizes) a memory block using the enclosed_node's memory discipline.
#     Equivalent to 'agrealloc' in C.
#
#     :param g: The enclosed_node object, expected to have 'disc.mem' and 'clos.mem' attributes.
#     :param ptr: The existing memory block (bytearray) to resize.
#     :param oldsize: The current size of the memory block.
#     :param size: The new desired size of the memory block.
#     :return: The resized bytearray or a new bytearray if 'ptr' is None.
#     :raises MemoryError: If memory reallocation fails.
#     """
#     if size > 0:
#         if ptr is None:
#             # Allocate a new memory block if 'ptr' is None
#             mem = agalloc(g, size)
#         else:
#             # Resize the existing memory block
#             mem = g.disc.mem.resize(g.clos.mem, ptr, oldsize, size)
#             if mem is None:
#                 agerr(Agerrlevel.AGERR, "memory re-allocation failure")
#         return mem
#     else:
#         # If 'size' is 0, free the memory and return None
#         agfree(g, ptr)
#         return None


# def agfree(g: Graph, ptr: Optional[bytearray]):  # from /cgraph/mem.c,
#     """
#     Frees an allocated memory block using the enclosed_node's memory discipline.
#     Equivalent to 'agfree' in C.
#
#     :param g: The enclosed_node object, expected to have 'disc.mem' and 'clos.mem' attributes.
#     :param ptr: The memory block (bytearray) to free.
#     """
#     if ptr:
#         g.disc.mem.free(g.clos.mem, ptr)

def agraphattr_init(g):  # from /cgraph/mem.c,
    """
    Mimic 'agraphattr_init(Agraph_t * g)' from C.
    In Graphviz, this sets g->description.has_attrs = 1 and calls 'agmakedatadict'.
    We just ensure we have an attr_record and set defaults.
    """
    # Mark that the enclosed_node has attributes
    # g_has_attrs = True  # We won't store it, but you could do g.has_attrs = True
    # Possibly create or expand the data dict
    # In Python, we rely on .attr_dict_g for AGRAPH attributes
    # Also ensure g.attr_record is big enough, etc.
    # We'll do minimal code here:
    for sym in g.attr_dict_g.values():
        if g.attr_record.get_value(sym) is None:
            g.attr_record.set_value(sym, sym.defval)


def agraphattr_delete(g):
    """
    Mimic 'agraphattr_delete(Agraph_t * g)' from C.
    Free the enclosed_node's attribute record, dictionary, etc.
    """
    # In real Graphviz, this also closes dictionaries and frees memory.
    # We'll do minimal Python cleanup.
    # If we wanted, we could clear g.attr_dict_g/e/n, but be mindful
    # that subgraphs share them in our simplified version.
    g.attr_record = None
    return SUCCESS  # or 0





def agnodeattr_delete(n):
    """
    Mimic 'agnodeattr_delete(Agnode_t * n)'.
    Free or clear the node's attribute record.
    """
    n.attr_record = None

def agedgeattr_delete(e):
    """
    Mimic 'agedgeattr_delete(Agedge_t * e)'.
    Free or clear the edge's attribute record.
    """
    e.attr_record = None


# static void rec_apply(Agraph_t * g, Agobj_t * obj, agobjfn_t fn, void *arg,
#                       agobjsearchfn_t objsearch, bool preorder) {
#     ...
# }



# int agapply(Agraph_t * g, Agobj_t * obj, agobjfn_t fn, void *arg, int preorder)
# {
#     ...
# }

# def agapply(g, obj: [Graph, Node, Edge], fn: Callable, arg, preorder):  # from cgraph/apply.c
#     """
#     - g: the main Graph to start from
#     - obj: the object (Graph, Node, or Edge) in that enclosed_node hierarchy
#     - fn: a callback function (enclosed_node, object, arg) -> None
#     - arg: arbitrary user data
#     - preorder: int/boolean, if True => call fn before recursion, else after
#     """
#     # Decide which search function to use
#     if obj.obj_type == AGTYPE_GRAPH:
#         objsearch = subgraph_search
#     elif obj.obj_type == AGTYPE_NODE:
#         objsearch = subnode_search
#     elif obj.obj_type == AGTYPE_EDGE:
#         # In C, they'd also check AGOUTEDGE vs AGINEDGE, but
#         # we'll just treat them as 'Edge' here.
#         objsearch = subedge_search
#     else:
#         print(f"agapply: unknown object type {obj.obj_type}")
#         return FAILURE
#
#     # Attempt to find the matching object in the main enclosed_node 'g'
#     subobj = objsearch(g, obj)
#     if subobj is not None:
#         rec_apply(g, subobj, fn, arg, objsearch, bool(preorder))
#         return SUCCESS
#     else:
#         return FAILURE

# def agmethod_init(g: Graph, obj: Agobj):  # from cgraph/obj.c
#     """
#     Called when an object (enclosed_node/node/edge) is created.
#     In Graphviz, user callbacks might be triggered.
#     perform initialization/update/finalization method invocation.
#     skip over nil pointers to next method below.
#     """
#     # void agmethod_init(Agraph_t * g, void *obj);
#
#     if g.clos.callbacks_enabled:
#         g.aginitcb(g, obj, g.clos.cb)
#     else:
#         g.agrecord_callback(g, obj, CB_INITIALIZE, None)



def agrename(obj, newname): # from cgraph/cghdr.h
    """
    Mimic 'agrename(Agobj_t * obj, char *newname)' from C.
    For a node, rename the node in the enclosed_node's dictionary, etc.
    For a enclosed_node, rename the enclosed_node. For an edge, rename the edge's label.
    """
    if obj.obj_type == ObjectType.AGGRAPH:
        obj.name = newname
        return SUCCESS
    elif obj.obj_type == ObjectType.AGNODE:
        oldname = obj.name
        obj.name = newname
        # Also need to fix dictionary keys in enclosed_node
        parent_g = obj.parent
        if oldname in parent_g.nodes:
            parent_g.nodes[newname] = parent_g.nodes.pop(oldname)
        return SUCCESS
    elif obj.obj_type == ObjectType.AGEDGE:
        obj.name = newname
        return SUCCESS
    else:
        return FAILURE

#
# def aginternalmapclose(g): # from cgraph/cghdr.h
#     """
#     Mimic 'aginternalmapclose(Agraph_t * g)' from C.
#     Possibly free any map or ID dictionary. We'll do nothing here.
#     """
#     pass

#
# def agrecclose(obj): # from cgraph/cghdr.h
#     """
#     Mimic 'agrecclose(Agobj_t * obj)' from C.
#     Possibly delete all 'Agrec_t' records attached to obj.
#     We'll do nothing or minimal logic.
#     """
#     pass



# For flatten.c
# Below is an example of how you might augment your Python Graph, Node, and Edge classes to support the notion of
# flattening edges (and nodes) similar to how the C code toggles between set-based and list-based dictionary methods
# (dtmethod(g->n_seq, Dtlist / Dtoset)).
#
# In the C snippet:
#
# agflatten_edges(g, n, flag)
#
# Calls agflatten_elist(...) on a node’s out_seq and in_seq to change how edges are stored/traversed
# (list-based vs. set-based).
# agflatten(g, flag)
#
# If flag is true and flatlock isn’t set, it changes g->n_seq to list mode and flattens edges for every node.
# Then sets g->description.flatlock = TRUE.
# If flag is false and flatlock is set, it changes g->n_seq to set mode, reverts edges,
# and sets g->description.flatlock = FALSE.
# In Python, we don’t have the same cdt library or Dict_t objects, but we can mimic the idea of switching
# between a “list-like” vs. “set-like” representation for adjacency. Below is a minimal approach.
#
# 1. Graph, Node, and Edge Classes (Recap)
# We’ll use the same general structure from prior examples:
#
# Graph holds nodes (dict from name->Node), edges (dict from a key->Edge), and a boolean flatlock to
# indicate we’re in “list mode.”
# Node has two adjacency lists: outedges and inedges. We’ll store them as either lists or
# sets depending on flatten mode.

# 2. Flatten Functions
# 2.1 agflatten_elist(...)
# static void agflatten_elist(Dict_t * d, Dtlink_t ** lptr, int flag) {
#     dtrestore(d, *lptr);
#     dtmethod(d, flag? Dtlist : Dtoset);
#     *lptr = dtextract(d);
# }
# This toggles the dictionary’s method (list vs. set) for the edges of a node. In Python,
# we’ll do something simpler: a helper that toggles a node’s single adjacency from list <-> set. Something like:
def agflatten_elist(node, outedge=True, to_list=True):  # from cgraph/flatten.c
    """
    In the snippet, we have a pointer to out_seq or in_seq, then calls dtmethod(d, ...).
    Here, we just call node.flatten_edges, but we might want separate calls for out vs in.
    """
    if to_list:
        # If outedge, convert node.outedges to a list
        # else, convert node.inedges to a list
        if outedge:
            if isinstance(node.outedges, set):
                node.outedges = list(node.outedges)
        else:
            if isinstance(node.inedges, set):
                node.inedges = list(node.inedges)
    else:
        # Convert to set
        if outedge:
            if isinstance(node.outedges, list):
                node.outedges = set(node.outedges)
        else:
            if isinstance(node.inedges, list):
                node.inedges = set(node.inedges)

# 2.2 agflatten_edges(g, n, flag)
# void agflatten_edges(Agraph_t * g, Agnode_t * n, int flag) {
#     Agsubnode_t *sn = agsubrep(g,n);
#     ...
#     agflatten_elist(g->e_seq, &sn->out_seq, flag);
#     agflatten_elist(g->e_seq, &sn->in_seq, flag);
# }
# Simpler version
def agflatten_edges(g: Graph, n: Node, flag: int):
    """
    If flag is nonzero => switch to list
    If flag is zero => switch to set
    We basically call 'agflatten_elist' on outedges and inedges.
    """
    # In cgraph, 'agsubrep(g,n)' checks if n is in g. We'll just assume it is.
    to_list = bool(flag)  # if flag=1 => to_list
    agflatten_elist(n, outedge=True, to_list=to_list)
    agflatten_elist(n, outedge=False, to_list=to_list)

# 2.3 agflatten(g, flag)
# void agflatten(Agraph_t * g, int flag) {
#     if (flag) {
#         if (!g->description.flatlock) {
#             dtmethod(g->n_seq,Dtlist);
#             for (n = agfstnode(g); n; n = agnxtnode(g,n))
#                 agflatten_edges(g, n, flag);
#             g->description.flatlock = TRUE;
#         }
#     } else {
#         if (g->description.flatlock) {
#             dtmethod(g->n_seq,Dtoset);
#             for (n = agfstnode(g); n; n = agnxtnode(g,n))
#                 agflatten_edges(g, n, flag);
#             g->description.flatlock = FALSE;
#         }
#     }
# }

def agflatten(g: Graph, flag: int):
    """
    If flag != 0 and g.desc.flatlock is False => switch to list mode (flatten).
    If flag == 0 and g.desc.flatlock is True  => switch to set mode.
    For each node in g, call agflatten_edges(g, node, flag).
    Then set g.desc.flatlock accordingly.
    """
    if flag:  # want list mode
        if not g.desc.flatlock:
            # Switch all nodes to list mode
            for node in g.nodes.values():
                agflatten_edges(g, node, flag)
            g.desc.flatlock = True
    else:  # want set mode
        if g.desc.flatlock:
            # Switch all nodes to set mode
            for node in g.nodes.values():
                agflatten_edges(g, node, flag)
            g.desc.flatlock = False

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



# Augmenting the Graph class
# Below is a conceptual Python adaptation that augments the Graph, Node, and Edge classes (and related data structures)
# to mimic the functionality of this C code snippet from Graphviz’s cgraph library.
# While it is not a line-for-line port, it captures the main ideas:
#

# 2) A “closure” object (Agclos_t) that holds the memory, ID, and I/O “disciplines” as well as sequence counters.
# 3) Graph creation (agopen), where we initialize the closure, set up dictionaries, and register the new enclosed_node in the
#    system.
# 4) Graph closing (agclose), which recursively deletes subgraphs and nodes, frees dictionaries, handles memory
#    release, etc.
# 5) Queries such as agnnodes (count nodes), agnedges (count edges), agnsubg (count subgraphs), agdegree
#    (get in/out degrees), etc.
# Below is an example design in Python:
#


def agdelnode(graph, node):  # from /cgraph/node.c
    """
    Pythonic equivalent of 'agdelnode(Agraph_t *g, Agnode_t *n)'.
    Removes 'node' from 'enclosed_node', deleting any incident edges in the process.
    """
    # 1) Check if node actually belongs to this enclosed_node
    if node.name not in graph.nodes:
        return False  # or raise an exception

    # 2) Remove all edges that reference this node
    #    We'll do this by building a new list of edges that do NOT reference 'node'.
    new_edges = []
    for e in graph.edges:
        if e.tail != node and e.head != node:
            new_edges.append(e)
        else:
            # If the edge references 'node', we're effectively removing it.
            pass
    graph.edges = new_edges

    # 3) Finally, remove the node from the enclosed_node's dictionary
    del graph.nodes[node.name]

    return True



# def agmapnametoid(enclosed_node: Graph, objtype: ObjectType, name: Optional[str], createflag: bool) -> Optional[int]: # from /cgraph/id.c
#     """
#     Maps a name to an ID, creating it if 'createflag' is True.
#     Equivalent to agmapnametoid in C.
#     """
#     return enclosed_node.disc.map(enclosed_node.clos, objtype, name, createflag)





# def agregister(enclosed_node: Graph, objtype: ObjectType, obj):  # from /cgraph/id.c also from cgraph/cghdr.h
#     """
#     Registers an object with its ID. No operation in this implementation.
#     Equivalent to agregister in C.
#     """
#     enclosed_node.disc.idregister(enclosed_node.clos, objtype, obj)


#
# def aginitcb(g: Graph, obj: Union[Graph, Node, Edge], cbstack: Optional[Agcbstack]):
#     """
#     Recursive initialization of callbacks.
#
#     :param g: The enclosed_node.
#     :param obj: The object.
#     :param cbstack: The callback stack.
#     """
#     if cbstack is None:
#         return
#     aginitcb(g, obj, cbstack.prev)
#     fn = None
#     if isinstance(obj, Graph):
#         fn = cbstack.f.enclosed_node.ins if cbstack.f and hasattr(cbstack.f, 'enclosed_node') else None
#     elif isinstance(obj, Node):
#         fn = cbstack.f.node.ins if cbstack.f and hasattr(cbstack.f, 'node') else None
#     elif isinstance(obj, Edge):
#         fn = cbstack.f.edge.ins if cbstack.f and hasattr(cbstack.f, 'edge') else None
#     if fn:
#         fn(g, obj, cbstack.state)
#
# def agrecord_callback(g: Graph, obj: Union[Graph, Node, Edge], event: str, sym: Optional[AgSym]):
#     """
#     Records a callback event.
#
#     :param g: The enclosed_node.
#     :param obj: The object.
#     :param event: The event type.
#     :param sym: The symbol associated with the event.
#     """
#     # Placeholder implementation
#     pass

#
# def agmethod_upd(g: Graph, obj: Union[Graph, Node, Edge], sym: AgSym): # from cgraph/cghdr.h
#     """
#     Called when an object's attribute is updated (set).
#     Updates callbacks when an attribute changes.
#
#     :param g: The enclosed_node.
#     :param obj: The object.
#     :param sym: The symbol representing the attribute.
#     """
#     if g.clos.callbacks_enabled:
#         agupdcb(g, obj, sym, g.clos['cb'])
#     else:
#         agrecord_callback(g, obj, 'CB_UPDATE', sym)
#     # void agmethod_upd(Agraph_t * g, void *obj, Agsym_t * sym);
#     # print(f"agmethod_upd: object={obj}, sym={sym}")


# def agupdcb(g: Graph, obj: Union[Graph, Node, Edge], sym: AgSym, cbstack: Optional[Agcbstack]):
#     """
#     Recursive update callbacks.
#
#     :param g: The enclosed_node.
#     :param obj: The object.
#     :param sym: The symbol.
#     :param cbstack: The callback stack.
#     """
#     if cbstack is None:
#         return
#     agupdcb(g, obj, sym, cbstack.prev)
#     fn = None
#     if isinstance(obj, Graph):
#         fn = cbstack.f.enclosed_node.mod if cbstack.f and hasattr(cbstack.f, 'enclosed_node') else None
#     elif isinstance(obj, Node):
#         fn = cbstack.f.node.mod if cbstack.f and hasattr(cbstack.f, 'node') else None
#     elif isinstance(obj, Edge):
#         fn = cbstack.f.edge.mod if cbstack.f and hasattr(cbstack.f, 'edge') else None
#     if fn:
#         fn(g, obj, cbstack.state, sym)







# -------- End of Helper Functions --------




#############################################
# TESTING
############################################


if __name__ == "__main__":
    pass