from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any, Union, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph

from .node import Node
from .edge import Edge
from .error import agerr, Agerrlevel
from .defines import ObjectType
from .headers import GraphEvent, Agcbstack, Agcbdisc, AgSym

_logger = logging.getLogger(__name__)


class CallbackMixin:
    """Mixin providing callback and discipline management methods for Graph."""

    def agrecord_callback(self, obj: Union['Graph', 'Node', 'Edge'], callback_type: GraphEvent, state):
        """
        Records a callback of a specific type for an object.

        :param obj: The enclosed_node object to associate with the callback.
        :param callback_type: The type of the callback (e.g., 'initialize').
        :param state: The state associated with the callback.
        """
        from .graph import Graph
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

    def agmethod_init(self, obj: Union['Graph', 'Node', 'Edge']):  # from /core/obj.c
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

    def agpushdisc(self, cbd: 'Agcbdisc', state: Any):
        """
        Pushes a discipline onto the stack.
        :param cbd: The callback discipline.
        :param state: The state associated with the discipline.
        """
        self.push_discipline(cbd, state)

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

    def push_discipline(self, cbd: 'Agcbdisc', state: Any):
        """
        Pushes a discipline onto the callback stack.
        Equivalent to 'agpushdisc' in C.

        :param cbd: The callback discipline to push.
        :param state: The state associated with the discipline.
        """
        stack_ent = Agcbstack(f=cbd.callback_functions, state=state, prev=self.clos.cb)
        self.clos.set_callback_stack(stack_ent)
        agerr(Agerrlevel.AGINFO, f"[Graph] Discipline '{cbd.name}' pushed onto the callback stack with state '{state}'.")

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

    def aginitcb(self, obj: Union['Graph', 'Node', 'Edge'], cbstack: Optional[Agcbstack] = None):
        """
        Initializes callbacks for a enclosed_node object by traversing the callback stack.
        Equivalent to the C 'aginitcb' function in /core/obj.c

        :param obj: The enclosed_node object (Graph, Node, or Edge) to initialize.
        :param cbstack: The current callback stack node.
        """
        from .graph import Graph
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

    def aginternalmapclearlocalnames(self) -> None:
        self.internal_map_clear_local_names()

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

        # Optionally, register default callbacks or set default attributes
        # For example, you might want to set default enclosed_node attributes here
        self.initialized = True
        agerr(Agerrlevel.AGINFO, f"[Graph] Graph '{self.name}' has been initialized.")

    def agmethod_upd(self, obj: Union['Graph', 'Node', 'Edge'], sym: AgSym):  # from /core/obj.c
        from .graph import Graph
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
        from .graph import Graph
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

    def agmethod_delete(self, obj: Union['Agobj', List['Agobj'], str]):  # from core/cghdr.h
        """
        Deletes callbacks for a enclosed_node object based on the callback system state.
        Equivalent to 'agmethod_delete' in C.
        C Functionality: Deletes callback methods for a enclosed_node object. It either deletes callbacks immediately or
        records the deletion for later based on whether callbacks are enabled.

        Implementation: Similar to agmethod_init and agmethod_upd, but handles deletion callbacks
        :param obj: The enclosed_node object (Graph, Node, or Edge) to delete callbacks for.

        """
        from .graph import Graph
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

    def method_delete(self,  obj: Union['Agobj', List['Agobj'], str]):
        """
        Deletes one or more enclosed_node elements (node, edge, or subgraph) from the enclosed_node.

        :param obj: A single Agobj instance or a list of Agobj instances to delete.
        :raises TypeError: If the object type is unsupported.
        """
        from .graph import Graph
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

    def agdelcb(self, obj: Union['Graph', 'Node', 'Edge'], cbstack: Optional[Agcbstack]):
        """
        Recursive deletion callbacks.

        :param obj: The object.
        :param cbstack: The callback stack.
        """
        from .graph import Graph
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
