import logging
from copy import copy
from typing import Callable, Optional, List, Dict, Tuple, Union, Any, TYPE_CHECKING
from collections import deque
if TYPE_CHECKING:
    from .headers import *
    from .defines import *
    from .error import *
    from .node import Node, CompoundNode, agsplice, save_stack_of, stackpush, NodeDict
    from .edge import Edge
    from .graph_view import GraphView

from .agobj import Agobj
from .headers import AgIdDisc, AgSym, Agdesc, GraphEvent, Agcbstack, Agcbdisc
from .defines import ObjectType, EdgeType, LOCALNAMEPREFIX
from .node import Node, CompoundNode, agsplice, save_stack_of, stackpush, NodeDict
from .edge import Edge
from .error import agerr, Agerrlevel

_logger = logging.getLogger(__name__)


# ── Re-exports from per-concern submodules ──────────────────────────
# These names used to live as inline definitions in this file.  As
# part of the core refactor (TODO_core_refactor.md step 6) they were
# moved into per-concern modules matching ``lib/cgraph/`` factoring.
# The re-exports below preserve the public ``from gvpy.core.graph
# import X`` API used by tests, render code, and other gvpy modules.
from ._graph_apply import subnode_search, subedge_search, subgraph_search
from ._graph_cmpnd import Agcmpgraph, agfindhidden
from ._graph_traversal import (
    gather_all_subgraphs,
    gather_all_nodes,
    gather_all_edges,
    get_root_graph,
)
from ._graph_id import agnextseq
from ._graph_edges import (
    agsubrep, agfstout, agnxtout, agfstin, agnxtin,
    agfstedge, agnxtedge, ok_to_make_edge,
    agedge, agidedge, agdeledge,
)


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


from ._graph_nodes import NodeMixin
from ._graph_edges import EdgeMixin
from ._graph_subgraphs import SubgraphMixin
from ._graph_attrs import AttrMixin
from ._graph_callbacks import CallbackMixin
from ._graph_id import IdMixin


class Graph(NodeMixin, EdgeMixin, SubgraphMixin, AttrMixin,
            CallbackMixin, IdMixin, Agobj):  # from core/core.c
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
        # Attached GraphView instances (C analogue: Agraphinfo_t via AGDATA).
        # One entry per (graph, view-name) pair.  Layout engines,
        # simulation state, analysis results, render overrides, etc. all
        # live here rather than polluting the core data model.
        # See gvpy/core/graph_view.py for the base class and docstring.
        from typing import Any as _Any
        self.views: Dict[str, _Any] = {}  # name -> GraphView (import-avoided)
        # This can be acheived by self.subgraphs[name].id
        # self.subgraph_name_to_id: Dict[str, int] = {}  # Mapping from subgraph names to IDs
        # self._id_counter: int = 1  # Starting ID counter


        # Whether we've "closed" or not
        self.closed = False

        # Initialize 'clos' — subgraphs share the root graph's closure
        # so that IDs are unique across the hierarchy (matching Graphviz C).
        if parent is not None:
            self.clos = parent.clos
        else:
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
            # Each subgraph gets its own copy of attribute dicts so that
            # child attribute assignments don't overwrite parent values.
            # Node/edge defaults are inherited (copied) from the parent so
            # that e.g. ``node [shape=record]`` at the parent level applies
            # to children, but children can override without affecting the
            # parent.
            if not hasattr(self.parent, "attr_dict_g"):
                self.parent.attr_dict_g = {}
            if not hasattr(self.parent, "attr_dict_n"):
                self.parent.attr_dict_n = {}
            if not hasattr(self.parent, "attr_dict_e"):
                self.parent.attr_dict_e = {}
            self.attr_dict_g = {}  # graph attrs are per-subgraph
            self.attr_dict_n = dict(self.parent.attr_dict_n)
            self.attr_dict_e = dict(self.parent.attr_dict_e)

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

    # ── Graph views (attached engine / simulation / analysis state) ──
    # See gvpy/core/graph_view.py for the GraphView base class.
    # C analogue: aginit()/AGDATA() for Agraphinfo_t extension data.

    def attach_view(self, view: "GraphView", name: Optional[str] = None) -> "GraphView":
        """Attach a GraphView to this graph under the given name.

        If ``name`` is omitted, uses ``view.view_name``.  Calls the
        view's ``on_attach`` hook after registration.  Returns the view.
        """
        key = name if name is not None else view.view_name
        self.views[key] = view
        view.on_attach()
        return view

    def detach_view(self, name: str) -> Optional["GraphView"]:
        """Detach the view registered under ``name`` and return it.

        Calls the view's ``on_detach`` hook before removal.  Returns
        ``None`` if no view with that name is attached.
        """
        view = self.views.get(name)
        if view is None:
            return None
        view.on_detach()
        del self.views[name]
        return view

    def get_view(self, name: str) -> Optional["GraphView"]:
        """Return the view registered under ``name``, or None."""
        return self.views.get(name)

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

    def agapply(self, obj: ['Graph', 'Node', 'Edge'], fn: Callable, arg, preorder) -> bool:  # from core/apply.c
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
    def agparent(self, obj: Optional[Union['Graph', 'Node', 'Edge']] = None):
        if obj:
            return self.get_graph_of(obj).parent
        else:
            return self.parent

    def agdeledge(self, e):  # from core/edge.c
        self.delete_edge(e)

    def find_by_id(self, id_: int):
        found_node = self.find_node_by_id(id_)
        if found_node:
            return found_node
        found_edge = self.find_edge_by_id(id_)
        if found_edge:
            return found_edge



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

    def rename(self, obj: Union["Node", "Graph"], newname: str) -> bool:  # from agrename in /core/obj.c
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

    def rec_apply(self, obj: ['Graph', 'Node', 'Edge'], fn: Callable, arg: Any, objsearch: Callable,
                  preorder: bool):  # from core/apply.c
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

    # todo: agcbdisc needs to be defined or gvpycode to remove
    def agdelete(self, obj: Agobj):  # from /core/obj.c
        self.method_delete(obj)

    def agedge(self, tail_name: str, head_name: str, name: Optional[str] = None,
               cflag: bool = True) -> Optional[Edge]:
        """Find or create an edge (C API: agedge)."""
        tail = self.add_node(tail_name)
        head = self.add_node(head_name)
        key = (tail_name, head_name, name)
        e = self.edges.get(key)
        if e:
            return e
        if not ok_to_make_edge(self, tail, head):
            return None
        eid = self.get_next_sequence(ObjectType.AGEDGE)
        out_e = Edge(tail=tail, head=head, name=name, graph=self, id_=eid,
                     seq=self.get_next_sequence(ObjectType.AGEDGE), etype=EdgeType.AGOUTEDGE)
        tail.outedges.append(out_e)
        head.inedges.append(out_e)
        if key not in self.edges:
            self.edges[key] = out_e
        return out_e

    def agnode(self, name: str, createflag: bool = True) -> Optional['Node']:
        return self.add_node(name, createflag)

    def agfstnode(self) -> Optional['Node']:
        return self.first_node()

    def agnxtnode(self, n: 'Node') -> Optional['Node']:
        return self.next_node(n)

    def aglstnode(self) -> Optional['Node']:
        return self.last_node()

    def agprvnode(self, n: 'Node') -> Optional['Node']:
        return self.previous_node(current=n)

    def agidnode(self, id_, createflag: bool = True) -> Optional['Node']:
        return self.create_node_by_id(id_)

    # ── Edge traversal (C API) ────────────────────

    def agfstedge(self, n: 'Node') -> Optional[Edge]:
        return agfstedge(self, n)

    def agnxtedge(self, e: Edge, n: 'Node') -> Optional[Edge]:
        return agnxtedge(self, e, n)

    def agfstin(self, n: 'Node') -> Optional[Edge]:
        return agfstin(self, n)

    def agnxtin(self, e: Edge) -> Optional[Edge]:
        return agnxtin(self, e)

    def agfstout(self, n: 'Node') -> Optional[Edge]:
        return agfstout(self, n)

    def agnxtout(self, e: Edge) -> Optional[Edge]:
        return agnxtout(self, e)

    # ── Edge traversal (Pythonic aliases) ────────

    def first_out_edge(self, n: 'Node') -> Optional[Edge]:
        """Get first outgoing edge from node n."""
        return agfstout(self, n)

    def next_out_edge(self, e: Edge) -> Optional[Edge]:
        """Get next outgoing edge after e."""
        return agnxtout(self, e)

    def first_in_edge(self, n: 'Node') -> Optional[Edge]:
        """Get first incoming edge to node n."""
        return agfstin(self, n)

    def next_in_edge(self, e: Edge) -> Optional[Edge]:
        """Get next incoming edge after e."""
        return agnxtin(self, e)

    def first_edge(self, n: 'Node') -> Optional[Edge]:
        """Get first edge (in or out) of node n."""
        return agfstedge(self, n)

    def next_edge(self, e: Edge, n: 'Node') -> Optional[Edge]:
        """Get next edge (in or out) of node n after e."""
        return agnxtedge(self, e, n)

    # ── Other C API ──────────────────────────────

    def agidedge(self, t: 'Node', h: 'Node', eid, c_flag) -> Optional[Edge]:
        return agidedge(self, t, h, eid, c_flag)

    def agsubnode(self, g: 'Graph', n: 'Node', createflag: bool = True) -> Optional['Node']:
        return self.add_subgraph_node(g, n, createflag)

    def agsubrep(self, n: 'Node') -> Optional['Node']:
        return agsubrep(self, n)

    def degree(self, n: 'Node', in_: bool = True, out: bool = True) -> int:
        """Count edges at node n."""
        count = 0
        if in_:
            count += len(n.inedges)
        if out:
            count += len(n.outedges)
        return count

    # C API alias
    agdegree = degree

    def count_unique_edges(self, n: 'Node', in_: bool = True, out: bool = True) -> int:
        """Count unique edges at node n (self-loops counted once)."""
        edges = set()
        if out:
            for e in n.outedges:
                edges.add(id(e))
        if in_:
            for e in n.inedges:
                edges.add(id(e))
        return len(edges)

    # C API alias
    agcountuniqedges = count_unique_edges

    def agnodebefore(self, u: 'Node', v: 'Node') -> bool:
        """Check if u comes before v in node ordering."""
        names = list(self.nodes.keys())
        if u.name in names and v.name in names:
            return names.index(u.name) < names.index(v.name)
        return False

    @staticmethod
    def agopen(name: str, desc: Agdesc = None, disc: AgIdDisc = None) -> 'Graph':
        return Graph(name=name, description=desc, disc=disc)

    def agconcat(self, chan: Any, disc: AgIdDisc = None) -> Optional['Graph']:
        pass  # TODO: implement graph concatenation from channel

    # TODO: I/O operations (deferred — use gvpy.render.read_gv() instead)
    def agread(self, chan: Any, disc: AgIdDisc = None) -> Optional['Graph']:
        raise NotImplementedError("Use gvpy.render.read_gv() or read_gv_file() instead")

    def agwrite(self, chan: Any) -> int:
        raise NotImplementedError("Use gvpy.render.write_gv() instead")

    def agmemread(self, cp: str) -> Optional['Graph']:
        raise NotImplementedError("Use gvpy.render.read_gv() instead")

    def agmemconcat(self, cp: str) -> Optional['Graph']:
        raise NotImplementedError("Use gvpy.render.read_gv() instead")

    # TODO: attribute iteration
    def agsubedge(self, e: Edge, createflag: bool = True) -> Optional[Edge]:
        raise NotImplementedError("Subgraph edge access not yet implemented")

    # TODO: error state management
    def agseterr(self, elevel: "Agerrlevel") -> "Agerrlevel":
        raise NotImplementedError

    def aglasterr(self) -> str:
        raise NotImplementedError

    def agreseterrors(self) -> int:
        raise NotImplementedError

    # TODO: string canonicalization
    def agstrcanon(self, a: str, b: str) -> str:
        raise NotImplementedError

    def acyclic(self) -> list:
        """Break cycles by reversing back edges (DFS-based).

        Returns list of reversed edges. Modifies the graph in-place.
        Equivalent to graphviz_acyclic().
        """
        UNVISITED, IN_PROGRESS, DONE = 0, 1, 2
        state = {n: UNVISITED for n in self.nodes}
        reversed_edges = []

        def dfs(u):
            state[u] = IN_PROGRESS
            for e in list(self.nodes[u].outedges):
                v = e.head.name
                if v not in state:
                    continue
                if state[v] == IN_PROGRESS:
                    # Back edge — reverse it
                    e.tail, e.head = e.head, e.tail
                    reversed_edges.append(e)
                elif state[v] == UNVISITED:
                    dfs(v)
            state[u] = DONE

        for n in self.nodes:
            if state[n] == UNVISITED:
                dfs(n)
        return reversed_edges

    def tred(self) -> list:
        """Transitive reduction — remove edges implied by transitivity.

        For each edge u→v, if there's another path u→...→v of length ≥2,
        the direct edge is redundant and removed.
        Returns list of removed edges. Equivalent to graphviz_tred().
        """
        removed = []
        edges_to_check = list(self.edges.values())
        for e in edges_to_check:
            tail_name = e.tail.name
            head_name = e.head.name
            # BFS/DFS from tail to head, excluding the direct edge
            visited = set()
            queue = deque()
            for other_e in e.tail.outedges:
                if other_e is not e:
                    queue.append(other_e.head.name)
            found = False
            while queue and not found:
                cur = queue.popleft()
                if cur == head_name:
                    found = True
                    break
                if cur in visited:
                    continue
                visited.add(cur)
                if cur in self.nodes:
                    for out_e in self.nodes[cur].outedges:
                        queue.append(out_e.head.name)
            if found:
                self.delete_edge(e)
                removed.append((tail_name, head_name))
        return removed

    def unflatten(self, max_min_len: int = 0, chain_limit: int = 0,
                  do_fans: bool = False) -> None:
        """Adjust minlen to improve aspect ratio for hierarchical layouts.

        Increases minlen on edges from nodes with many outgoing edges
        (fan-out) or on chain paths. Equivalent to graphviz_unflatten().

        Args:
            max_min_len: Maximum minlen to set (0 = no limit).
            chain_limit: Max consecutive chain nodes to adjust (0 = no limit).
            do_fans: If True, also adjust fan-out nodes.
        """
        for name, node in self.nodes.items():
            n_out = len(node.outedges)
            if n_out <= 1 and not do_fans:
                continue
            # Leaf check: skip if node is a leaf
            if n_out == 0 or len(node.inedges) == 0:
                continue
            for e in node.outedges:
                cur_minlen = int(e.attributes.get("minlen", "1"))
                new_minlen = cur_minlen + 1
                if max_min_len > 0:
                    new_minlen = min(new_minlen, max_min_len)
                e.attributes["minlen"] = str(new_minlen)

    def node_induce(self) -> int:
        """Add edges from parent graph whose endpoints are both in this subgraph.

        For each edge in the root graph, if both tail and head are nodes
        in this subgraph, add the edge here too. Returns count of edges added.
        Equivalent to graphviz_node_induce().
        """
        root = get_root_graph(self)
        if root is self:
            return 0
        count = 0
        for key, edge in root.edges.items():
            tail_name, head_name, edge_name = key
            if tail_name in self.nodes and head_name in self.nodes:
                if key not in self.edges:
                    self.edges[key] = edge
                    count += 1
        return count

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
        # In core, 'agsubrep(g,n)' checks if n is in g. We'll just assume it is.
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



