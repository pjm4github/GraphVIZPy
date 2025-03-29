
from .CGError import agerr, Agerrlevel
from .Defines import *

# Forward declarations: these imports are only for type checking.
if TYPE_CHECKING:
    from .CGNode import Node
    from .CGGraph import Graph
    from .CGEdge import Edge


# In the original C code, each edge could store Agcmpedge_t,
# containing two stacks (in-stack, out-stack).
# Each stack holds (from, to) pairs for when edges get “spliced.”

class SaveET:  # from /cgraph/cmpnd.c  (compound node functions)
    """
    A Pythonic version of 'save_e_t', which stores (from_node, to_node)
    for splicing.
    """

    def __init__(self, from_node=None, to_node=None):
        self.from_node = from_node
        self.to_node = to_node


class SaveStackT:  # from /cgraph/cmpnd.c  (compound node functions)
    """
    A Pythonic version of 'save_stack_t':
      - A simple list storing SaveET objects
      - stacksize is len(self.mem)
    """

    def __init__(self):
        self.mem = []  # list of SaveET
        # (In C, 'stacksize' is a separate int. In Python, we can just use len(self.mem).)

    def push(self, from_node, to_node):
        self.mem.append(SaveET(from_node, to_node))

    def top(self):
        if self.mem:
            return self.mem[-1]
        return SaveET()  # empty

    def pop(self):
        if self.mem:
            return self.mem.pop()
        return SaveET()


class Agcmpedge:  # from /cgraph/cmpnd.c  (compound node functions)
    """
    Pythonic version of 'Agcmpedge_t'. Holds two SaveStackT:
       stack[IN_STACK], stack[OUT_STACK]
    We'll treat indexes 0=IN_STACK, 1=OUT_STACK.
    """

    def __init__(self):
        self.stack = [SaveStackT(), SaveStackT()]  # in-stack, out-stack


def get_root_graph_of_obj(obj) -> Optional['Graph']:
    """Convenience: get the root enclosed_node from a Graph, Node, or Edge."""
    if obj.obj_type == AGTYPE_GRAPH:
        root: 'Graph' = obj
        return root.get_root()
    elif obj.obj_type == AGTYPE_NODE:
        root: 'Graph' = obj.parent
        return root.get_root()
    elif obj.obj_type == AGTYPE_EDGE:
        root: 'Graph' = obj.parent
        return root.get_root()
    return None


class CallbackFunctions:
    """
    Holds initialization functions for different enclosed_node object types.
    """
    def __init__(self, graph_ins: Optional[Callable] = None,
                 node_ins: Optional[Callable] = None,
                 edge_ins: Optional[Callable] = None,
                 graph_mod: Optional[Callable] = None,
                 node_mod: Optional[Callable] = None,
                 edge_mod: Optional[Callable] = None
                 ):
        self.graph = self.GraphCallbacks(ins=graph_ins, mod=graph_mod)
        self.node = self.NodeCallbacks(ins=node_ins, mod=node_mod)
        self.edge = self.EdgeCallbacks(ins=edge_ins, mod=edge_mod)

    class GraphCallbacks:
        def __init__(self, ins: Optional[Callable] = None, mod: Optional[Callable] = None):
            self.ins = ins
            self.mod = mod
            self.delete = None

    class NodeCallbacks:
        def __init__(self, ins: Optional[Callable] = None, mod: Optional[Callable] = None):
            self.ins = ins
            self.mod = mod
            self.delete = None

    class EdgeCallbacks:
        def __init__(self, ins: Optional[Callable] = None, mod: Optional[Callable] = None):
            self.ins = ins
            self.mod = mod
            self.delete = None


class Agdesc:  # from /cgraph/enclosed_node.c
    """
    A “enclosed_node descriptor” (Agdesc_t) that specifies directed vs. undirected, strict vs. non-strict, etc.
    Python version of Agdesc_t:
      - directed (bool)
      - strict (bool)
      - no_loop (bool)
      - maingraph (bool)
      - ... other flags ...
        Agdesc (Equivalent to Agdesc_t)
    """
    def __init__(self, directed=False, strict=False, no_loop=False,
                 maingraph=False, has_attrs=False, flatlock=True):
        """
        :param directed:
        :param strict:
        :param no_loop:
        :param maingraph:
        :param has_attrs:
        """
        self.directed = directed
        self.strict = strict
        self.no_loop = no_loop
        self.maingraph = maingraph
        self.has_attrs = has_attrs
        self.flatlock = flatlock
        # For simplicity, we omit fields like has_attrs, flatlock, etc.


class Agcbdisc:
    """
    Represents a callback discipline, encapsulating callback functions and state.
    """
    def __init__(self, name: str, callback_functions: 'CallbackFunctions'):
        self.name = name
        self.callback_functions = callback_functions


class Agcbstack:
    """
    Represents a callback stack node.
    """
    def __init__(self, f: CallbackFunctions, state, prev: Optional['Agcbstack'] = None):
        self.f = f  # Methods
        self.state = state  # Closure
        self.prev = prev  # Kept in stack, unlike ither disciplines


class Agclos:  # from /cgraph/enclosed_node.c, /cgraph/cgraph.h
    """
    Python equivalent of the C struct Agclos_t.
    Encapsulates state and metadata for a enclosed_node.
    """

    # def __init__(self, disc: Optional[AgIdDisc]):
    #     self.disc = disc            # memory, id, io discipline
    #     self.mem = None
    #     self.id = None
    #     # Counters for all ObjectTypes
    #     self.seq = {member.name.lower(): 0 for member in ObjectType}
    #     # self.seq = {AGTYPE_GRAPH: 0, AGTYPE_NODE: 0, AGTYPE_EDGE: 0}  # counters for different object types (GRAPH, NODE, EDGE)
    #     self.callbacks_enabled = True

    def __init__(self):
        """
        Initializes the Agclos instance with memory discipline and empty mappings.

        """
        self.lookup_by_name: Dict[ObjectType, Dict[str, int]] = {
            ot: {} for ot in ObjectType
        }
        self.lookup_by_id: Dict[ObjectType, Dict[int, str]] = {
            ot: {} for ot in ObjectType
        }
        self.sequence_counters: Dict[ObjectType, int] = {
            ot: 2 for ot in ObjectType  # Starting at 2 for even IDs (named objects)
        }

        # Flag to control callback execution
        self.callbacks_enabled: bool = True

        # Lists to hold registered callback functions
        self.node_added_callbacks: List[Callable[['Node'], None]] = []
        self.node_deleted_callbacks: List[Callable[['Node'], None]] = []
        self.edge_added_callbacks: List[Callable[['Edge'], None]] = []
        self.edge_deleted_callbacks: List[Callable[['Edge'], None]] = []
        # Dictionaries to hold lists of callback functions for each event
        # self.callbacks: Dict[str, List[Callable]] = {
        #     'node_added': [],
        #     'node_deleted': [],
        #     'edge_added': [],
        #     'edge_deleted': [],
        #     'subgraph_added': [],  # New event
        #     'subgraph_deleted': []  # New event
        #     # Additional events can be added here
        # }

        self.callbacks: Dict[GraphEvent, List[Callable]] = {
            GraphEvent.NODE_ADDED: [],
            GraphEvent.NODE_DELETED: [],
            GraphEvent.EDGE_ADDED: [],
            GraphEvent.EDGE_DELETED: [],
            GraphEvent.SUBGRAPH_ADDED: [],
            GraphEvent.SUBGRAPH_DELETED: [],
            GraphEvent.INITIALIZE: [],
            GraphEvent.MODIFY: [],
            GraphEvent.DELETION: []  # Added 'deletion' event

            # Additional events can be added here
        }
        self.disc: Optional[AgIdDisc] = None  # resource discipline functions
        self.state: Optional[Agcbstack] = None  # resource closures
        # Lock for thread-safe operations
        self.lock = threading.Lock()
        self.cb: Optional[Agcbstack] = None  # Callback stack

    @contextmanager
    def temporary_callback_state(self, enable=True):
        """
        A context manager to temporarily enable or disable callbacks.

        :param enable: Boolean flag to enable or disable callbacks.
        """
        original_state = self.callbacks_enabled
        self.callbacks_enabled = enable
        try:
            yield
        finally:
            self.callbacks_enabled = original_state
            state = "enabled" if self.callbacks_enabled else "disabled"
            agerr(Agerrlevel.AGINFO, f"[Agclos] Callbacks have been {state}.")

    # -------- Cleanup Method --------

    def reset(self):
        """
        Resets the Agclos state, clearing all registered callbacks.
        """
        self.callbacks_enabled = True
        self.node_added_callbacks.clear()
        self.node_deleted_callbacks.clear()
        self.edge_added_callbacks.clear()
        self.edge_deleted_callbacks.clear()
        for ot in ObjectType:
            self.lookup_by_name[ot].clear()
            self.lookup_by_id[ot].clear()
            self.sequence_counters[ot] = 2  # Reset to initial value
        self.reset_callbacks()

    def reset_callbacks(self, event: Optional[GraphEvent] = None):
        """
        Resets all callbacks, clearing all registered functions.
        """
        with self.lock:
            if event:
                self.callbacks[event].clear()
                agerr(Agerrlevel.AGINFO, f"[Agclos] All callbacks for event {event} have been reset.")
            else:
                for event in self.callbacks:
                    self.callbacks[event].clear()
                agerr(Agerrlevel.AGINFO, "[Agclos] All callbacks have been reset.")

            self.callbacks_enabled = True

    def register_node_added_callback(self, callback: Callable[['Node'], None]):
        """
        Registers a callback function to be called when a node is added.
        """
        self.node_added_callbacks.append(callback)

    def register_node_deleted_callback(self, callback: Callable[['Node'], None]):
        """
        Registers a callback function to be called when a node is deleted.
        """
        self.node_deleted_callbacks.append(callback)

    def register_edge_added_callback(self, callback: Callable[['Edge'], None]):
        """
        Registers a callback function to be called when an edge is added.
        """
        self.edge_added_callbacks.append(callback)

    def register_edge_deleted_callback(self, callback: Callable[['Edge'], None]):
        """
        Registers a callback function to be called when an edge is deleted.
        """
        self.edge_deleted_callbacks.append(callback)

    # -------- Callback Invocation Methods --------

    def invoke_node_added(self, n_node: 'Node'):
        """
        Invokes all registered node added callbacks if callbacks are enabled.
        """
        if self.callbacks_enabled:
            for callback in self.node_added_callbacks:
                try:
                    callback(n_node)
                except Exception as e:
                    agerr(Agerrlevel.AGINFO, f"Error in node_added_callback: {e}")

    def invoke_node_deleted(self, n_node: 'Node'):
        """
        Invokes all registered node deleted callbacks if callbacks are enabled.
        """
        if self.callbacks_enabled:
            for callback in self.node_deleted_callbacks:
                try:
                    callback(n_node)
                except Exception as e:
                    agerr(Agerrlevel.AGINFO, f"Error in node_deleted_callback: {e}")

    def invoke_edge_added(self, n_edge: 'Edge'):
        """
        Invokes all registered edge added callbacks if callbacks are enabled.
        """
        if self.callbacks_enabled:
            for callback in self.edge_added_callbacks:
                callback(n_edge)

    def invoke_edge_deleted(self, n_edge: 'Edge'):
        """
        Invokes all registered edge deleted callbacks if callbacks are enabled.
        """
        if self.callbacks_enabled:
            for callback in self.edge_deleted_callbacks:
                callback(n_edge)

    def register_callback(self, event: GraphEvent, callback: Callable):
        """
        Registers a callback function for a specific event.

        :param event: The event name (e.g., 'node_added').
        :param callback: The callback function to register.
        """

        with self.lock:
            if event in self.callbacks:
                if callback not in self.callbacks[event]:
                    self.callbacks[event].append(callback)
                    agerr(Agerrlevel.AGINFO, f"[Agclos] Callback registered {callback} for event type '{event}'.")
                else:
                    agerr(Agerrlevel.AGINFO, f"[Agclos] Callback {callback} already registered for event '{event}'.")
            else:
                raise ValueError(f"[Agclos] Unknown event '{event}' for callback registration.")

    def unregister_callback(self, event: GraphEvent, callback: Callable):
        """
        Unregisters a callback function for a specific event.

        :param event: The event name.
        :param callback: The callback function to unregister.
        """
        with self.lock:
            if event in self.callbacks:
                if callback in self.callbacks[event]:
                    self.callbacks[event].remove(callback)
                    agerr(Agerrlevel.AGINFO, f"[Agclos] Callback unregistered {callback} for event type '{event}'.")
                else:
                    agerr(Agerrlevel.AGINFO, f"[Agclos] Callback {callback} not found for event type '{event}'.")
            else:
                raise ValueError(f"[Agclos] Unknown event '{event}' for callback unregistration.")

    # -------- Callback Invocation Methods --------

    def invoke_callbacks(self, event: GraphEvent, obj):
        """
        Invokes all registered callbacks for a specific event.

        :param event: The event name.
        :param obj: The enclosed_node object associated with the event.
        """
        with self.lock:
            if self.callbacks_enabled and event in self.callbacks:
                for callback in self.callbacks[event]:
                    try:
                        callback(obj)
                    except Exception as e:
                        agerr(Agerrlevel.AGINFO, f"[Agclos] Error in callback for event '{event}': {e}")

    # -------- Control Methods --------

    def enable_callbacks(self):
        """
        Enables the execution of callbacks and invokes 'initialize' callbacks.
        """
        with self.lock:
            self.callbacks_enabled = True
            agerr(Agerrlevel.AGINFO, "[Agclos] Callbacks have been enabled.")

        with self.lock:
            self.callbacks_enabled = True
            agerr(Agerrlevel.AGINFO, "[Agclos] Callbacks have been enabled.")
            # Invoke 'initialize' callbacks upon enabling
            if GraphEvent.INITIALIZE in self.callbacks:
                for callback in self.callbacks[GraphEvent.INITIALIZE]:
                    try:
                        callback()
                    except Exception as e:
                        agerr(Agerrlevel.AGINFO, f"[Agclos] Error in 'initialize' callback: {e}")
                # Clear 'initialize' callbacks after invoking
                self.callbacks[GraphEvent.INITIALIZE].clear()


    def disable_callbacks(self):
        """
        Disables the execution of callbacks.
        """
        with self.lock:
            self.callbacks_enabled = False
            agerr(Agerrlevel.AGINFO, "[Agclos] Callbacks have been disabled.")



    def get_next_sequence(self, ot: ObjectType) -> int:
        """
        Retrieves the next sequence number for the given object type.

        :param ot: The type of the object (AGGRAPH, AGNODE, AGEDGE).
        :return: The next sequence number.
        """
        seq = self.sequence_counters[ot]
        self.sequence_counters[ot] += 2  # Increment by 2 to maintain even/odd separation
        return seq

    def set_sequence_counter(self, ot: ObjectType, new_seq: int):
        """
        Sets the sequence counter for a specific object type.

        :param ot: The type of the object.
        :param new_seq: The new sequence number to set.
        """
        self.sequence_counters[ot] = new_seq

    # -------- Callback Stack Management --------

    def set_callback_stack(self, cbstack: 'Agcbstack'):
        """
        Sets the current callback stack.

        :param cbstack: The callback stack to set.
        """
        with self.lock:
            self.cb = cbstack
            agerr(Agerrlevel.AGINFO, f"[Agclos] Callback stack has been set to {cbstack}.")


class AgIdDisc:  # from /cgraph/enclosed_node.c (from cgraph.h)
    """
    A simple implementation of AgIdDisc that assigns incremental IDs.
    These are the discipline methods for the ID of the enclosed_node.
    This base class defines the interface for ID disciplines

    Python equivalent of the C struct Agiddisc_s.
    The New Structure, Remove the abstract base class (AgIdDisc as ABC) and Renames DefaultAgIdDisc to
    AgIdDisc and remove inheritance from ABC.
    """
    # object ID allocator discipline cgraph.h line 179
    #
    # struct Agiddisc_s {
    #     void *(*open) (Agraph_t * g, Agdisc_t*);	/* associated with a enclosed_node */
    #     long (*map) (void *state, int objtype, char *str, IDTYPE *id,
    # 		 int createflag);
    #     long (*alloc) (void *state, int objtype, IDTYPE id);
    #     void (*free) (void *state, int objtype, IDTYPE id);
    #     char *(*print) (void *state, int objtype, IDTYPE id);
    #     void (*close) (void *state);
    #     void (*idregister) (void *state, int objtype, void *obj);

    def __init__(self):
        # Initialize a counter starting at 1, incremented by 2 for anonymous IDs
        self.ctr = 2  # Start at 2 for even IDs (named objects)

    @staticmethod
    def open() -> Agclos:
        """
        Initialize the ID discipline with empty mappings and a counter.
        ID discipline no longer depends on a memory discipline
        :return: A closure object.
        """
        # Initialize the Agclos instance
        return Agclos()

    @staticmethod
    def map(state: 'Agclos', ot: ObjectType, name: Optional[str], createflag: bool) -> Optional[int]:

        """
        Map a name to an ID. If 'name' is None, generates an anonymous ID.

        :param state: The state as a closure (Agclos type)
        :param ot: The type of object.
        :param name: The name to map.
        :param createflag: Whether to create the ID if it does not exist.
        :return: The ID as an integer, or None if not found and not created.
        """
        if ot == ObjectType.AGINEDGE:
            ot = ObjectType.AGEDGE  # Treat AGINEDGE as AGEDGE for mapping

        if name and not name.startswith(LOCALNAMEPREFIX):
            # Named items are always even sequence numbers
            if name in state.lookup_by_name[ot]:
                return state.lookup_by_name[ot][name]
            elif createflag:
                # Assign the next even ID
                id_ = state.get_next_sequence(ot)
                state.lookup_by_name[ot][name] = id_
                state.lookup_by_id[ot][id_] = name
                return id_
            else:
                return None
        else:
            # Generate an anonymous ID (odd number)
            id_ = state.get_next_sequence(ot) - 1  # Assign an odd number by subtracting 1
            return id_

    @staticmethod
    def alloc(state: 'Agclos', ot: 'ObjectType', id_: int) -> bool:
        """
        Allocate a specific ID for an object type.

        :param state: The state as Agclos.
        :param ot: The type of object.
        :param id_: The ID to allocate.
        :return: True if successful, False if the ID is already allocated.
        """
        if id_ in state.lookup_by_id.keys():
            return False  # ID already allocated
        state.lookup_by_id[ot][id_] = ""  # No name associated yet
        if id_ >= state.sequence_counters[ot]:
            # Since the object is unnamed, it will be assigned and the ID for that type will be incremented
            # to ensure all unnamed objects are ODD seq numbers.
            state.sequence_counters[ot] = id_ + 1
        return True

    @staticmethod
    def free(state: 'Agclos', ot: ObjectType, id_: int):
        """
        Free an allocated ID.
        If the ID is even, it is associated with a name and can be removed from mappings.

        :param state: The state object Agclos type.
        :param ot: The type of object.
        :param id_: The ID to free.
        """
        # if id in state['id_to_name']:
        #     key = state['id_to_name'][id]
        #     if key and key[0] == objtype:
        #         del state['name_to_id'][key]
        #     del state['id_to_name'][id]

        if ot == ObjectType.AGINEDGE:
            ot = ObjectType.AGEDGE  # Treat AGINEDGE as AGEDGE for mapping

        if id_ % 2 == 0:
            name = state.lookup_by_id[ot].get(id_)
            if name:
                del state.lookup_by_id[ot][id_]
                del state.lookup_by_name[ot][name]
        # Odd IDs are anonymous and do not require handling in Python

    def idregister(self, state: 'Agclos', ot: ObjectType, obj):
        """
        Registers an object with its ID.
        Equivalent to aginternalmapinsert in C.
        Inserts the name-ID mapping into lookup dictionaries.
        """
        if ot == ObjectType.AGINEDGE:
            ot = ObjectType.AGEDGE  # Treat AGINEDGE as AGEDGE for mapping

        name = obj.agnameof(obj)
        if name and not name.startswith(LOCALNAMEPREFIX):
            self.internal_map_insert(state=state, ot=ot, name=name, id_=obj.id)
        # If the object has no name, it's anonymous; no mapping required

    @staticmethod
    def internal_map_insert(state: 'Agclos', ot: ObjectType, name: str, id_: int):
        """
        Inserts a new name-ID mapping into the lookup dictionaries.
        Equivalent to aginternalmapinsert in C.
        """
        if ot == ObjectType.AGEDGE and name is None:
            # Internal edges without names are treated differently if needed
            return
        state.lookup_by_name[ot][name] = id_
        state.lookup_by_id[ot][id_] = name

    @staticmethod
    def print_id(state: 'Agclos', ot: ObjectType, id_: int) -> Optional[str]:
        """
        Returns the string representation of an ID.
        For even IDs, returns the associated name.
        For odd IDs, returns None.
        """
        if ot == ObjectType.AGINEDGE:
            ot = ObjectType.AGEDGE  # Treat AGINEDGE as AGEDGE for mapping

        if id_ % 2 == 0:
            return state.lookup_by_id[ot].get(id_)
        else:
            return None

    @staticmethod
    def close(state: 'Agclos'):
        """
        Closes the ID discipline, performing any necessary cleanup.
        Equivalent to 'aginternalmapclose' in C.
        """
        # Clear all mappings
        for ot in ObjectType:
            state.lookup_by_name[ot].clear()
            state.lookup_by_id[ot].clear()
        state.sequence_counters = {ot_: 2 for ot_ in ObjectType}  # Reset sequence counters


AgSym = dict


# class AgSym:  # from cgraph/cgraph.c
#     """
#     A Pythonic equivalent of 'Agsym_t' from cgraph:
#       - name: the attribute name (string)
#       - defval: the default string value
#       - id: a unique integer ID used as an index
#       - kind: e.g., AGTYPE_GRAPH, AGTYPE_NODE, AGTYPE_EDGE
#       - other fields (print, fixed) omitted or simplified here
#     """
#     def __init__(self, name: str, defval: str, kind: ObjectType, fixed: bool = False, print_flag: bool = False):
#         self.name = name
#         self.defval = defval
#         self.kind = kind
#         self.id = 0
#         # C code might have 'print', 'fixed' bits, etc. We omit or set defaults:
#         self.print_flag = print_flag
#         self.fixed = fixed
#
#     def __repr__(self):
#         return f"<AgSym name={self.name}, kind={self.kind}, defval={self.defval}>"

AgAttrRecord = dict

# class AgAttrRecord(dict):  # from cgraph/cgraph.c
#     """
#     A Pythonic equivalent of 'Agattr_t' from cgraph:
#       - A reference to a dictionary of 'AgSym' (the declared attributes).
#       - An array or dict of actual string values indexed by sym.id.
#     """
#     # def __init__(self):
#     #     # 'symdict' can be a dictionary: {attr_name: AgSym}
#     #     # We'll store the actual attribute values in a list,
#     #     # indexed by AgSym.id. We initialize with 'size' (min. capacity).
#     #     super().__init__()
#     #     self.symdict = {}
#     #     self.strings: Optional[List[str]] = None   # store attribute values by ID
#     #     self.attributes = {}
#
#     def __init__(self, *args, **kwargs):
#         super().__init__()
#         self.update(*args, **kwargs)
#
#     def __getitem__(self, key):
#         val = dict.__getitem__(self, key)
#         return val
#
#     def __setitem__(self, key, val):
#         dict.__setitem__(self, key, val)
#
#     def __repr__(self):
#         dictrepr = dict.__repr__(self)
#         return '%s(%s)' % (type(self).__name__, dictrepr)
#
#     def update(self, *args, **kwargs):
#         for k, v in dict(*args, **kwargs).items():
#             self[k] = v
#
#     def ensure_size(self, needed):
#         """
#         Ensures 'strings' list is large enough to hold 'needed' indices.
#         """
#         pass  # Not needed in python
#         # if needed >= len(self.strings):
#         #     # Grow the list (like the C code resizing the char** array).
#         #     self.strings.extend([None]*(needed - len(self.strings) + 1))
#
#     def set_value(self, dict_or_int: [AgSym, int], value):
#         """Set the attribute value for a particular AgSym."""
#
#         if isinstance(dict_or_int, int):
#             # Get the key indecated by the position passed as an int
#             key = list(self.keys())[dict_or_int - 1]
#             dict.__setitem__(self, key, value)
#         else:
#             dict.__setitem__(self, dict_or_int, value)
#
#     def get_value(self, dict_or_int: [AgSym, int]):
#         """Get the attribute value for a particular AgSym."""
#         if isinstance(dict_or_int, int):
#             # Get the key indecated by the position passed as an int
#             val = dict.__getitem__(self, dict_or_int)
#         else:
#             val = dict.__getitem__(self, dict_or_int)
#         return val

def AGOPP(e: "Edge") -> "Edge":
    """
    Return the opposite half-edge of 'e'.
    Equivalent to `AGOPP(e)` in cgraph macros:
      - If 'e' is the in-edge, returns e-1 (the out-edge).
      - If 'e' is the out-edge, returns e+1 (the in-edge).
    """
    return e.opp

def AGMKOUT(e: "Edge") -> "Edge":
    """
    Return the out-edge variant of the edge pair.
    Equivalent to `AGMKOUT(e)` in cgraph:
      - If e is already an out-edge, return e.
      - If e is an in-edge, return e.opp (the out-edge partner).
    """
    if e.etype == "AGOUTEDGE":
        return e
    else:
        return e.opp

def AGMKIN(e: "Edge") -> "Edge":
    """
    Return the in-edge variant of the edge pair.
    Equivalent to `AGMKIN(e)` in cgraph:
      - If e is already an in-edge, return e.
      - If e is an out-edge, return e.opp.
    """
    if e.etype == "AGINEDGE":
        return e
    else:
        return e.opp

def AGTAIL(e: "Edge") -> "Node":
    """
    Return the tail node of a directed edge.
    Equivalent to `AGTAIL(e)` in cgraph macros:
      - The tail node is stored in the 'in-edge' variant's e->node in cgraph,
        hence we do AGMKIN(e).node.
    """
    return AGMKIN(e).node

def AGHEAD(e: "Edge") -> "Node":
    """
    Return the head node of a directed edge.
    Equivalent to `AGHEAD(e)` in cgraph macros:
      - The head node is stored in the 'out-edge' variant's e->node in cgraph,
        hence we do AGMKOUT(e).node.
    """
    return AGMKOUT(e).node

def AGEQEDGE(e: "Edge", f: "Edge") -> bool:
    """
    Return True if both 'e' and 'f' refer to the same logical edge
    (i.e., they share the same out-edge half).
    Equivalent to `AGEQEDGE(e, f)` in cgraph:
      - Checks if AGMKOUT(e) == AGMKOUT(f)
    """
    return AGMKOUT(e) is AGMKOUT(f)

# For convenience, you can also define aliases matching the cgraph names:
agopp   = AGOPP
agmkout = AGMKOUT
agmkin  = AGMKIN
agtail  = AGTAIL
aghead  = AGHEAD
ageqedge= AGEQEDGE
