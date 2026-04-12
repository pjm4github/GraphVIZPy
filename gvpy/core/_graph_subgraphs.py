from __future__ import annotations
import logging
from copy import copy
from typing import Optional, List, Dict, Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph

from .node import Node, CompoundNode, agsplice, save_stack_of, stackpush
from .edge import Edge
from .error import agerr, Agerrlevel
from .defines import ObjectType
from .headers import GraphEvent

_logger = logging.getLogger(__name__)


class SubgraphMixin:
    """Mixin providing subgraph management methods for Graph."""

    def add_subgraph(self, name: str, create: bool = True) -> Optional['Graph']:
        from .graph import Graph
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
        from .graph import Graph
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
        from .graph import Graph
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
            # In a typical core approach, we do something like:

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

    # Subgraph functions from /core/subg.c
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
        from .graph import Graph
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

    def localsubg(self, id_: int) -> 'Graph':
        """
        Creates a local subgraph with the specified ID.

        :param id_: The unique identifier for the subgraph.
        :return: The newly created Graph instance.
        """
        subg = self.get_or_create_subgraph_by_id(id_,  True)
        return subg

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

    def aghide(self, cmpnode: 'Node') -> bool:
        """
        Hides a collapsed subgraph node, reintegrating its subgraph into the graph enclosed_node.
        This involves:
          1. Splicing edges from external nodes so that edges incident to nodes of the subgraph
             now connect to the compound node.
          2. Moving the subgraph's nodes into the graph enclosed_node's hidden set.
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
        from ._graph_traversal import get_root_graph
        root = get_root_graph(parent_graph)

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
            for (tail_name, head_name, ekey), edge in list(root.edges.items()):
                # Check if this edge is incident on 'rootn'
                if edge.tail == rootn or edge.head == rootn:
                    # Is it an "external" edge? (One endpoint in subg, the other endpoint outside subg)
                    tail_in_subg = (edge.tail.name in subg.nodes)
                    head_in_subg = (edge.head.name in subg.nodes)
                    both_in_subg = (tail_in_subg and head_in_subg)
                    neither_in_subg = (not tail_in_subg and not head_in_subg)
                    if neither_in_subg:
                        _logger.debug("Skipping splice of  %s, %s, %s", edge.name, edge.tail.name, edge.name)
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

    def find_graph_by_name(self, name: str) -> Optional['Graph']:  # from /core/node.c
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

    def agdtopen_subgraph_dict(self, method: Optional[Callable] = None) -> 'GraphDict':
        agerr(Agerrlevel.AGINFO, f"[Agraph] Opening subgraph dictionary with method: {method}")
        return self.agdtopen(method=method)

    def agdtdelete_subgraph_by_name(self, name: str) -> bool:
        subg = self.subgraphs.get(name)
        if subg:
            return self.agdelsubg(subg)
        else:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Cannot delete non-existent subgraph with name '{name}'.")
            return False
