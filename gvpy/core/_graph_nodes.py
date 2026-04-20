from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph

from .node import Node, CompoundNode
from .edge import Edge
from .error import agerr, Agerrlevel
from .defines import ObjectType
from .headers import GraphEvent

_logger = logging.getLogger(__name__)


class NodeMixin:
    """Mixin providing node management methods for Graph."""

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
            # Check the root graph first — if the node already exists there,
            # reuse the same object so attributes aren't lost when a node
            # created in a child subgraph is later referenced at a parent level.
            from ._graph_traversal import get_root_graph
            root = get_root_graph(self)
            existing = root.nodes.get(n_name) if root is not self else None
            if existing is not None:
                self.nodes[n_name] = existing
                return existing

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
            # Centrality recompute dropped — the value was never read
            # anywhere (only the default 0.0 in _graph_cmpnd.py) and
            # running it on every ``add_node`` is O(V × E) betweenness.
            # Callers needing centrality should call
            # :meth:`compute_centrality` after the graph is fully built.
            new_n.set_compound_data("rank", 0)  # Example initialization
            # Invoke node added callbacks
            self.clos.invoke_callbacks(GraphEvent.NODE_ADDED, new_n)

            return_node = self.nodes[n_name]
        else:
            return_node = None
        return return_node

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

    def find_node_by_id(self, id_: int) -> Optional['Node']:  # from /core/node.c
        """
        Equivalent to agfindnode_by_id in C.

        :param id_: The ID of the node to find.
        :return: The Node object if found, else None.
        """
        for node_item in self.nodes.values():
            if node_item.id == id_:
                return node_item
        return None

    def find_node_by_name(self, name: str) -> Optional['Node']:  # from /core/node.c
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

    def first_node(self) -> Optional["Node"]:  # from /core/node.c
        """
        Equivalent to agfstnode in C.

        :return: The first Node in the enclosed_node if exists, else None.
        """
        if not self.nodes:
            return None
        # Assuming insertion order; first inserted node
        first_name = next(iter(self.nodes))
        return self.nodes[first_name]

    def next_node(self, current: "Node") -> Optional["Node"]:    # from /core/node.c
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

    def last_node(self) -> Optional["Node"]:    # from /core/node.c
        """
        Equivalent to aglstnode in C.

        :return: The last Node in the enclosed_node if exists, else None.
        """
        if not self.nodes:
            return None
        last_name = next(reversed(self.nodes))
        return self.nodes[last_name]

    def previous_node(self, current: "Node") -> Optional["Node"]:  # from /core/node.c
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

    def create_node_by_id(self, id_: int) -> Optional["Node"]:  # from /core/node.c
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

    def create_node_by_name(self, name: str, cflag: bool = True) -> Optional["Node"]:  # from /core/node.c
        """
        Equivalent to agnode in C.
        Creates a node with a specific name.

        :param name: The name of the node.
        :param cflag: If True, create the node if it does not exist.
        :return: The created or existing Node object if successful, else None.
        """
        return self.add_node(name, create=cflag)

    def relabel_node(self, original_node: "Node", newname: str) -> bool: # from /core/node.c
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

    def add_subgraph_node(self, sgr: 'Graph', work_node: "Node", createflag: bool = True) -> Optional["Node"]: # from /core/node.c
        """
        Equivalent to agsubnode in C.
        Looks up or inserts a node into a subgraph.

        :param sgr: The subgraph to insert the node into.
        :param work_node: The Node object to insert.
        :param createflag: If True, create the node in the subgraph if it does not exist.
        :return: The Node object in the subgraph if successful, else None.
        """

        _logger.debug("A node is being added and created to a subgraph")
        # (a) Check if it's already compound
        if work_node.compound_node_data.is_compound:
            agerr(Agerrlevel.AGWARN, f"Node '{work_node.name}' is already a compound node.")
            return None

        # (b) Mark the node as compound, link to the existing subgraph
        work_node.compound_node_data.is_compound = True
        work_node.compound_node_data.subgraph = sgr
        work_node.compound_node_data.collapsed = False

        from ._graph_traversal import get_root_graph
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

    def make_compound_node(self, compound_name: str, existing_node: Optional[Node] = None) -> Optional['Node']:
        """
        Creates a node with a given name into a compound node by creating an internal subgraph and linking it.

        The node remains is maintained in the enclosed_node's node dictionary, but its compound state is stored in its
        'compound_node_data' (an instance of CompoundNode). The internal subgraph is created (via
        create_subgraph) and assigned to compound_node.compound_node_data.subgraph, and is also added
        to the main enclosed_node's subgraphs dictionary.

        This is a slightly gvpycode version of agcmpnode and agassociate

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
