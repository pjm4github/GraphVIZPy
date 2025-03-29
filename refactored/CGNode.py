from collections import deque
from typing import List, Dict, Optional, TYPE_CHECKING, Tuple, Any
if TYPE_CHECKING:
    from .Headers import *
    from .CGError import *
    from .CGGraph import Graph
    from .CGEdge import Edge

from .Agobj import Agobj
from .Defines import ObjectType
from .CGError import agerr, Agerrlevel

# Forward declarations: these imports are only for type checking.


class CompoundNode:   # from /cgraph/cmpnd.c  (compound node functions)
    """
    Pythonic version of 'Agcmpnode_t':
    Encapsulates comparison-related data for a node.
      - subg: A reference to the subgraph
      - collapsed: whether we've 'hidden' it

    provides "compound nodes" on top of base Libgraph.
    a compound node behaves as both an ordinary node and a subgraph.
    there are additional primitives to "hide" and "expose" its contents.

    Think of these as hypergraphs, but there is an asymmetry
    in the operations we have chosen.  i.e. nodes "own" their edges,
    but nodes and interior edges are "owned by" the hyperedges.
    also the subgraphs are nested, etc. the bottom line is that graphs
    and hypergraphs are just sets, everything else here is convenience
    and maintaining consistency.

    this package adds a primitive "agsplice" to move endpoints of edges.
    this could be useful in other situations.
    """
    def __init__(self):
        # Compound Node Attributes
        self.is_compound: bool = False
        self.subgraph: Optional['Graph'] = None  # Reference to the internal subgraph
        self.collapsed = False

        self.degree: int = 0  # Total number of connections (incoming + outgoing).
        self.centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.degree_centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.betweenness_centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.closeness_centrality: float = 0.0  # Measure of node importance within the enclosed_node.
        self.degree_centrality_normalized = 0.0
        self.rank: int = 0  # Position in hierarchical layouts.
        self.cluster_id: Optional[int] = None  # Identifier for node clustering.
        # Add additional comparison metrics as needed

        # Example of positional data
        # x and y: Coordinates for node placement (useful for layout algorithms).
        self.x: float = 0.0
        self.y: float = 0.0

    def update_degree(self, outedges: [int, List], inedges: [int, List]):
        """
        Updates the degree based on outgoing and incoming edges.

        :param outedges: Number of outgoing edges.
        :param inedges: Number of incoming edges.
        """
        num_outedges = len(outedges) if isinstance(outedges, list) else outedges
        num_inedges = len(inedges) if isinstance(inedges, list) else inedges
        self.degree = num_outedges + num_inedges

    # def __repr__(self):
    #     return (f"CompoundNode(degree={self.degree}, centrality={self.centrality}, "
    #             f"rank={self.rank}, cluster_id={self.cluster_id}, "
    #             f"is_compound={self.is_compound}, collapsed={self.collapsed})")


    def __repr__(self):
        def safe_repr(val):
            from .CGGraph import Graph
            # For Graph or Node objects, return a short summary.
            if isinstance(val, Graph):
                return f"<Graph {val.name}>"
            elif isinstance(val, Node):
                return f"<Node {val.name}>"
            else:
                return repr(val)

        # Gather all attributes from the instance.
        base_attrs = {}
        for attr, value in self.__dict__.items():
            base_attrs[attr] = safe_repr(value)

        # Build a multi-line string with each attribute on its own indented line.
        base_attrs_str = "\n".join(f"    {k}: {v}" for k, v in base_attrs.items())

        return f"<CompoundNode:\n{base_attrs_str}\n>"


# 4. Key Compound-Graph Functions
# Below we define minimal Python versions of the major compound-node methods from your code:
#

def agcmpnode(g: 'Graph', name: str) -> Optional['Node']:  # from /cgraph/cmpnd.c
    """
    Creates a compound node with the same name as a subgraph. That means:
    Pythonic version of 'agcmpnode(Agraph_t* g, char* name)'.
    - Create/find a node 'name' in g
    - Create/find a subgraph named 'name' in g
    - Associate them if possible
    """
    node = g.add_node(name)
    subg = g.add_subgraph(name)
    # Associate them:
    if node and subg:
        ok = agassociate(node, subg)
        if ok:
            return node
    return None


def agassociate(node: 'Node', subg: 'Graph'):  # from /cgraph/cmpnd.c
    """
    Check if the node already belongs to subg; if so, fail. Otherwise, link them:
    Pythonic version of 'agassociate(Agnode_t* n, Agraph_t* sub)'.
    - Avoid cycles by ensuring 'n' isn't already in 'subg'
    - Then set node->compound_node_data.subg = subg
    - and subg->cmp_graph_data.node = n
    Returns SUCCESS/FAILURE (True/False).
    """
    # 1) Avoid cycle: If subg already has 'n', fail
    if node.name in subg.nodes:
        # That implies n is a subnode of subg
        return False

    # 2) Link them
    node.compound_node_data.subgraph = subg
    subg.cmp_graph_data.node = node
    return True

def agcmpgraph_of(n: 'Node') -> Optional['Graph']:  # from /cgraph/cmpnd.c
    """
    Return the subgraph associated with node n, if it's not collapsed,
    else None.
    """
    rec = n.compound_node_data
    if rec and not rec.collapsed:
        return rec.subgraph
    return None

def agcmpnode_of(g: 'Graph') -> 'Node':  # from /cgraph/cmpnd.c
    """
    Return the node associated with enclosed_node g.
    i.e., g->cmp_graph_data->node in C code.
    """
    return g.cmp_graph_data.node


# 6. Splicing Edges: agsplice(e, target)
# The original code reattaches an edge from e->node to a new “target” node. We do a minimal version here, updating the in/out references:

# Note: The real C code has more logic to figure out if we’re splicing the tail side or head side
# (spl->head_side). A fully faithful version would check if e->node == h or t and reorder
# references accordingly.

# def agsplice(e, target):  # from /cgraph/cmpnd.c
#     """
#     Pythonic version of 'agsplice(Agedge_t * e, Agnode_t * target)'.
#     1) If e is already pointing at target, do nothing.
#     2) Otherwise, remove e from old adjacency sets, update e.tail/e.head, reinsert.
#     """
#     if e.tail == target or e.head == target:
#         return False
#
#     old_src, old_dst = e.tail, e.head
#     # Suppose we interpret e.head as the "mutable" side if e.head==e.node in the C code, etc.
#     # We'll do a simpler approach: always update the 'head' for demonstration.
#     # Or choose logic if 'e.node' was the tail vs head. For brevity:
#     e.head = target
#
#     # In reality, you'd remove e from old_src.outedges, old_dst.inedges,
#     # and add to new adjacency sets. We'll skip adjacency sets for brevity.
#     return True


def agsplice(edge: 'Edge', target_node: 'Node') -> bool:
    """
    Reassigns one endpoint of 'edge' to 'target_node', effectively splicing the edge.
    - If 'edge' was from old_node -> other_node (directed) or old_node -- other_node,
      and old_node is the "active" side, we re-route it to target_node -> other_node.
    - The same logic applies if the edge's head is the "active" side.

    Returns True if successful, False otherwise.
    """
    # Basic validation
    if edge is None or target_node is None:
        return False
    if target_node == edge.tail or target_node == edge.head:
        # Already spliced to target
        return False

    graph = edge.graph
    if graph is None:
        return False

    old_tail = edge.tail
    old_head = edge.head

    # 1) Determine which side is "variant"
    #    In the cgraph 'cmpnd.c', code uses a 'head_side' boolean to see if e->node == HEAD(e).
    #    But in Python, we can just pick which endpoint we want to splice based on a separate marker,
    #    or see which node is being replaced.
    splice_tail_side = False
    splice_head_side = False

    # For example, if 'edge.tail' is the node we want to replace with 'target_node':
    if edge.tail == target_node:
        # Already spliced
        return False
    elif edge.head == target_node:
        # Already spliced
        return False
    else:
        # Usually you'd have logic deciding "are we re-routing the tail or the head?"
        # For example, if 'edge.node == old_head' in c code => splicing head side.
        # We'll assume we figure out from context; let's assume we re-splice the side that matches old_tail or old_head.
        # In a direct usage of 'cmpnd.c', there's a reason we know which side is variant.
        # We'll do a short example: if old_tail is the "side" we're changing
        splice_tail_side = True
        # or if we wanted the head side, set splice_head_side = True
        # (Pick the correct one depending on your call context.)

    # 2) Remove the edge from the graph's dictionary under the old key
    old_key = (old_tail.name, old_head.name, edge.name)
    if old_key in graph.edges:
        del graph.edges[old_key]

    # Also remove from adjacency in old_tail/old_head
    old_tail.remove_outedge(edge)
    old_head.remove_inedge(edge)

    # 3) Update the actual endpoint in the Edge
    if splice_tail_side:
        edge.tail = target_node
    else:
        edge.head = target_node

    new_tail = edge.tail
    new_head = edge.head

    # 4) Insert the edge under the new key in the graph dictionary
    new_key = (new_tail.name, new_head.name, edge.name)
    graph.edges[new_key] = edge

    # 5) Add to adjacency in new_tail/new_head
    new_tail.add_outedge(edge)
    new_head.add_inedge(edge)

    return True


# 7. Stack Helpers:
# The code calls:
#  stackpush(save_stack_of(e, rootn), rootn, cmpnode);
def save_stack_of(e, node_being_saved):  # from /cgraph/cmpnd.c
    """
    Finds e.cmp_edge_data, determines if node_being_saved is e.head or e.tail,
    returns the appropriate stack (IN_STACK or OUT_STACK).
    In the original code:
        if node_being_saved == AGHEAD(e) => i=IN_STACK
        else => i=OUT_STACK
    We'll do a simpler check:
    """
    cmpdata = e.cmp_edge_data
    if not cmpdata:
        # If not present, create it
        cmpdata = Agcmpedge()
        e.cmp_edge_data = cmpdata

    # Decide which index is IN_STACK or OUT_STACK
    # Let's say if node_being_saved == e.head => IN_STACK=0
    # else => OUT_STACK=1
    # This is just a heuristic:
    if node_being_saved == e.head:
        i = 0
    else:
        i = 1
    return cmpdata.stack[i]

def stackpush(stk, from_node, to_node):  # from /cgraph/cmpnd.c
    """Push a pair (from_node, to_node) onto the stack."""
    stk.push(from_node, to_node)


class NodeDict(dict):
    def __init__(self, parent=None, *args, **kwargs):
        """
        :param parent: The enclosed_node object (e.g., a Graph) that owns this NodeDict.
        :param *args, **kwargs: Additional arguments passed to dict's constructor
                                (for copying items, etc.).
        """
        super().__init__(*args, **kwargs)
        self.parent = parent  # store the reference

    def __setitem__(self, key, value):
        # Insert your validation or callbacks here
        if self.parent:
            print("assigning a node to a graph with a enclosed_node")
            if not self.parent.is_main_graph:
                print("assigning a graph which is a subgraph")

        if not isinstance(key, str):
            raise ValueError("Node keys must be strings.")
        # Possibly check if value is a Node
        super().__setitem__(key, value)


class Node(Agobj):   # from cgraph/cgraph.c
    """
    Pythonic equivalent of 'Agnode_t'.
    Includes a reference to the 'enclosed_node' that owns this node.
    """
    def __init__(self,
                 name: str,
                 graph: Optional['Graph'] = None,
                 id_: int = 0,
                 seq: int = 0,
                 root: Optional['Graph'] = None,
                 attributes: Optional[Dict[str, str]] = None
                 ):
        super().__init__(obj_type=ObjectType.AGNODE)
        self.name = name
        self.parent = graph  # A reference to the enclosed_node Graph
        self.id = id_
        self.seq = seq
        self.root = root
        # Potential adjacency structures
        self.outedges: List[Edge] = []  # edges for which this node is 'tail'
        self.inedges:  List[Edge] = []  # edges for which this node is 'head'
        self.attributes: Dict[str, str] = attributes or {}
        # Our attribute record. We'll share the node attribute dictionary
        # from the root enclosed_node.
        self.init_local_attr_values()

        # "Compound node" data
        self.compound_node_data: CompoundNode = CompoundNode()  # was cmp_mode_data
        self.collapsed: bool = False  # Indicates if this node is a collapsed subgraph
        self.subgraph: Optional['Graph'] = None  # Reference to the subgraph if collapsed
        self.saved_connections: List[Tuple['Node', 'Edge']] = []  # Stores (other_node, edge) tuples

    def agedgeattr_init(self):
        """
        Make sure we allocate space & defaults for each declared Node attribute.
        Similar to 'agnodeattr_init'.
        """
        self.init_local_attr_values()

    def init_local_attr_values(self):
        """
        Mimics cgraph's 'agedgeattr_init(g, e)' by ensuring that
        every declared edge attribute in the root enclosed_node is set on 'edge'.
        If the edge has no local override, we apply the default.
        """
        # 1) Find the root enclosed_node
        root = self.get_root_graph()
        # 2) For each declared edge attribute and default value in the root
        if root:
            for attr_name, default_value in root.attr_dict_n.items():
                # 3) If the local edge doesn’t already have an override, set it
                if attr_name not in self.attributes:
                    self.attributes[attr_name] = default_value

    def get_root_graph(self):
        root = self.parent
        if root:
            while getattr(root, 'enclosed_node', None):  # climb to root
                root = root.parent
            return root
        else:
            return None

    def root_attr_dict(self):
        """Return the dictionary of node attributes from the *root* enclosed_node."""
        root = self.parent
        if root:
            while getattr(root, 'enclosed_node', None):  # climb to root
                root = root.parent
            return root.attr_dict_n
        else:
            return {}

    def get_node_attr(self, attr_name: str) -> str:

        if attr_name in self.attributes:
            return self.attributes[attr_name]
        else:
            # fallback to the root's default
            attr_dict = self.root_attr_dict()
            default_value = attr_dict.get(attr_name)
            self.attributes[attr_name] = default_value
            return default_value  # might be None if never declared

    def agget(self, name:str):  # from /cgraph/attr.c
        """
        Pythonic version of 'agget(obj, name)':
        Return the string value of the attribute named 'name' for obj.
        Return None if attribute does not exist.
        """
        return self.get_node_attr(name)

    def set_node_attr(self, attr_name: str, value: str):
        """
        Sets node's local override for attr_name. Does NOT change the root default.
        """
        self.attributes[attr_name] = value

    def agset(self, name, value):  # from /cgraph/attr.c
        """
        Pythonic version of 'agset(obj, name, value)':
        Set the attribute named 'name' for 'obj' to 'value'.
        Return SUCCESS/FAILURE.
        """
        self.set_node_attr(name, value)

    def agsafeset(self, name, value, default):  # from /cgraph/attr.c
        """
        Pythonic version of 'agsafeset(obj, name, value, def)':
        If 'name' attribute doesn't exist, define it with 'default' at the root enclosed_node.
        Then set it to 'value'.
        """
        if name in self.attributes:
            self.attributes[name] = value
        else:
            self.attributes[name] = value
            # Declare a new attribute with default
            root = self.get_root_graph()
            root.set_graph_attr(name, default)

    def flatten_edges(self, to_list: bool):
        """
        Convert outedges and inedges to either list or set
        """
        if to_list:
            if isinstance(self.outedges, set):
                self.outedges = list(self.outedges)
            if isinstance(self.inedges, set):
                self.inedges = list(self.inedges)
        else:
            # Convert to sets
            if isinstance(self.outedges, list):
                self.outedges = set(self.outedges)
            if isinstance(self.inedges, list):
                self.inedges = set(self.inedges)

    def add_outedge(self, edge: 'Edge'):
        if edge not in self.outedges:
            self.outedges.append(edge)
            self.compound_node_data.update_degree(len(self.outedges), len(self.inedges))

    def add_inedge(self, edge: 'Edge'):
        if edge not in self.inedges:
            self.inedges.append(edge)
            self.compound_node_data.update_degree(len(self.outedges), len(self.inedges))

    def remove_outedge(self, edge: 'Edge'):
        if edge in self.outedges:
            self.outedges.remove(edge)
            self.compound_node_data.update_degree(len(self.outedges), len(self.inedges))

    def remove_inedge(self, edge: 'Edge'):
        if edge in self.inedges:
            self.inedges.remove(edge)
            self.compound_node_data.update_degree(len(self.outedges), len(self.inedges))

    def set_compound_data(self, key: str, value: Any):  # was set_cmp_data
        """
        Sets a specific compound data point in CompoundNode.

        :param key: The name of the comparison metric.
        :param value: The value to set for the metric.
        """

        # One of cmp data components is the centrality computation
        # 1. Centrality Measures Overview
        # 1.1. Degree Centrality
        #       Definition: Measures the number of direct connections a node has.
        #       Interpretation: Nodes with higher degree centrality are more connected and potentially more influential.
        # 1.2. Betweenness Centrality
        #       Definition: Quantifies the number of times a node acts as a bridge along the shortest path
        #       between two other nodes.
        #       Interpretation: Nodes with high betweenness centrality can control information flow and play
        #       critical roles in communication within the network.
        # 1.3. Closeness Centrality
        #       Definition: Measures how close a node is to all other nodes in the enclosed_node based on the shortest paths.
        #       Interpretation: Nodes with high closeness centrality can quickly interact with all other nodes.
        if hasattr(self.compound_node_data, key):
            setattr(self.compound_node_data, key, value)
        else:
            raise AttributeError(f"The compound node: {self.compound_node_data.cluster_id} object has no attribute '{key}'")

    def get_compound_data(self, key: str) -> Optional[Any]:  # was get_cmp_data
        """
        Retrieves a specific comparison data point from CompoundNode.

        :param key: The name of the comparison metric.
        :return: The value of the metric if it exists, else None.
        """
        return getattr(self.compound_node_data, key, None)

    def compare_degree(self, other: 'Node') -> int:
        """
        Compares two nodes based on their degree.

        :param other: The other Node to compare with.
        :return: -1 if self < other, 0 if equal, 1 if self > other
        """
        if not isinstance(other, Node):
            raise TypeError("Comparison must be between Node instances")

        self_degree = self.compound_node_data.degree
        other_degree = other.compound_node_data.degree

        if self_degree < other_degree:
            return -1
        elif self_degree > other_degree:
            return 1
        else:
            return 0

    def make_compound(self, subgraph_name: str) -> Optional['Graph']:
        """
        Converts the node into a compound node by creating an internal subgraph.

        :param subgraph_name: The name of the internal subgraph.
        :return: The created subgraph.
        """
        if self.compound_node_data.is_compound:
            agerr(Agerrlevel.AGWARN, f"Node '{self.name}' is already a compound node.")
            return self.compound_node_data.subgraph

        # Create the internal subgraph
        subgraph = self.parent.create_subgraph(subgraph_name, enclosed_node=self)
        # This values should already be set in the create_subgraph method of Graph

        if self.compound_node_data.subgraph != subgraph:
            agerr(Agerrlevel.AGERR, f"Subgraph '{subgraph_name}' compound_node_data not set correctly.")
            return None
        if not self.compound_node_data.is_compound:
            agerr(Agerrlevel.AGERR, f"Subgraph '{subgraph_name}' is not marked as compound.")
            return None

        if self.compound_node_data.collapsed:  # Default to visible
            agerr(Agerrlevel.AGERR, f"Subgraph '{subgraph_name}' is marked as collapsed (hidden) and should not be.")
            return None

        return subgraph

    def hide_contents(self):  # TODO This needs to be cleaned up, requires more than a just setting the collapsed flag.
        """
        Hides the contents of the compound node, effectively hiding its subgraph.

        :raises ValueError: If the node is not a compound node.
        """
        if not self.compound_node_data.is_compound:
            raise ValueError(f"Node '{self.name}' is not a compound node.")

        self.compound_node_data.collapsed = True

    def splice_edge(self, edge: 'Edge', new_tail: Optional['Node'] = None, new_head: Optional['Node'] = None):
        """
        Reassigns the tail and/or head of an edge, effectively moving its endpoints.

        :param edge: The Edge to splice.
        :param new_tail: The new tail node. If None, the tail remains unchanged.
        :param new_head: The new head node. If None, the head remains unchanged.
        """
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
        edge.tail.set_compound_data("centrality", self.compute_centrality(edge.tail))
        edge.head.set_compound_data("centrality", self.compute_centrality(edge.head))

    def compute_betweenness_centrality(self, n: Optional['Node'] = None):
        """
        Computes Betweenness Centrality for all nodes in the enclosed_node.
        Betweenness Centrality measures the number of times a node acts as a bridge along the shortest path between two other nodes.
        """
        if not n:
            betweenness = {node.name: 0.0 for node in self.parent.nodes.values()}

            for s in self.parent.nodes.values():
                # Single-source shortest-paths
                stack = []
                predecessors = {node.name: [] for node in self.parent.nodes.values()}
                sigma = {node.name: 0 for node in self.parent.nodes.values()}  # Number of shortest paths
                distance = {node.name: -1 for node in self.parent.nodes.values()}
                sigma[s.name] = 1
                distance[s.name] = 0
                queue = deque([s])

                while queue:
                    v = queue.popleft()
                    stack.append(v)
                    for edge in v.outedges:
                        w = edge.head
                        dw = distance.get(w.name)
                        if not dw:
                            agerr(Agerrlevel.AGINFO, f"this outedge {w.name} is outside the subgraph")
                        else:
                            if dw < 0:
                                distance[w.name] = distance.get(v.name) + 1
                                queue.append(w)
                            if distance.get(w.name) == distance.get(v.name) + 1:
                                sigma[w.name] += sigma.get(v.name)
                                predecessors[w.name].append(v.name)

                # Accumulation
                delta = {node.name: 0.0 for node in self.parent.nodes.values()}
                while stack:
                    w = stack.pop()
                    for v_name in predecessors[w.name]:
                        delta[v_name] += (sigma[v_name] / sigma[w.name]) * (1 + delta[w.name])
                    if w != s.name:
                        betweenness[w.name] += delta[w.name]

            # Normalize the betweenness centrality values
            scale = 1 / ((len(self.parent.nodes) - 1) * (len(self.parent.nodes) - 2)) if len(self.parent.nodes) > 2 else 1
            for node in self.parent.nodes.values():
                node.set_compound_data("betweenness_centrality", betweenness[node.name] * scale)

    def compute_centrality(self, n: 'Node'):
        return float(n.compound_node_data.degree_centrality)

    def compute_degree_centrality(self):
        """
        Computes Degree Centrality for all nodes in the enclosed_node.
        Degree Centrality is the number of direct connections a node has.
        """
        n = self
        degree = len(n.outedges) + len(n.inedges)
        n.set_compound_data("degree_centrality", degree)
        # Optionally, normalize if desired
        n.set_compound_data("degree_centrality_normalized",
                            degree / (len(self.parent.nodes) - 1)
                            if len(self.parent.nodes) > 1 else 0)

    def compute_closeness_centrality(self):
        """
        Computes Closeness Centrality for all nodes in the enclosed_node.
        Closeness Centrality measures how close a node is to all other nodes based on the shortest paths.
        """
        for node in self.parent.nodes.values():
            # BFS to compute the shortest paths
            visited = {n.name: False for n in self.parent.nodes.values()}
            distance = {n.name: 0 for n in self.parent.nodes.values()}
            queue = deque([node])
            visited[node.name] = True
            while queue:
                current = queue.popleft()
                for edge in current.outedges:
                    neighbor = edge.head
                    n_name = visited.get(neighbor.name)
                    if not n_name:
                        agerr(Agerrlevel.AGINFO, f"this outedge node {neighbor.name} is outside the subgraph")
                    else:
                        if not visited[neighbor.name]:
                            visited[neighbor.name] = True
                            distance[neighbor.name] = distance[current.name] + 1
                            queue.append(neighbor)

            # Sum of distances
            total_distance = sum(distance.values())
            if total_distance > 0:
                closeness = (len(self.parent.nodes) - 1) / total_distance
            else:
                closeness = 0.0
            node.set_compound_data("closeness_centrality", closeness)

    def get_degree_centrality(self) -> float:
        """
        Retrieves the degree centrality of the node.

        :return: Degree centrality value.
        """
        return self.compound_node_data.degree_centrality

    def get_betweenness_centrality(self) -> float:
        """
        Retrieves the betweenness centrality of the node.

        :return: Betweenness centrality value.
        """
        return self.compound_node_data.betweenness_centrality

    def get_closeness_centrality(self) -> float:
        """
        Retrieves the closeness centrality of the node.

        :return: Closeness centrality value.
        """
        return self.compound_node_data.closeness_centrality

    def expose_contents(self): # TODO needs more than just setting teh collapsed flag.
        """
        Exposes the contents of the compound node, making its subgraph visible.

        :raises ValueError: If the node is not a compound node.
        """
        if not self.compound_node_data.is_compound:
            raise ValueError(f"Node '{self.name}' is not a compound node.")

        self.compound_node_data.collapsed = False
    #
    # def __repr__(self):
    #     degree = "Not Set"
    #     centrality = "Not Set"
    #
    #     cnd = getattr(self, 'compound_node_data', None)
    #     if cnd:
    #         degree = getattr(cnd, 'degree', degree)
    #         centrality = getattr(cnd, 'centrality', centrality)
    #
    #     return (f"Node(name={self.name}, id={self.id}, seq={self.seq}, "
    #             f"degree={degree}, centrality={centrality}, "
    #             f"attributes={self.attributes})")

    def __repr__(self):
        def safe_repr(val):
            from .CGGraph import Graph
            from .CGEdge import Edge
            if isinstance(val, Graph):
                return f"<Graph {val.name}>"
            elif isinstance(val, Node):
                return f"<Node {val.name}>"
            elif isinstance(val, Edge):
                return f"<Edge {val.name}>"
            else:
                return repr(val)

        # Collect base attributes except the ones we want to summarize separately.
        # For example, we'll handle 'attributes', 'outedges', 'inedges', and 'saved_connections' later.
        base_attrs = {}
        for attr, value in self.__dict__.items():
            if attr in ["attributes", "outedges", "inedges", "saved_connections"]:
                continue
            if attr == "compound_node_data":
                # Get its safe representation and indent each line by four spaces.
                compound_repr = safe_repr(value)
                compound_repr_indented = "\n".join("    " + line for line in compound_repr.splitlines())
                base_attrs[attr] = compound_repr_indented
            else:
                base_attrs[attr] = safe_repr(value)
        # Build a string for the base attributes, one per line.
        base_attrs_str = "\n".join(f"    {k}: {v}" for k, v in base_attrs.items())

        # Summarize the attribute's dictionary.
        if self.attributes:
            attr_summary = "\n        ".join(f"{k}: {v}" for k, v in self.attributes.items())
        else:
            attr_summary = "None"

        # Summarize outedges and inedges by listing the names of the connected edges.
        outedges_summary = [edge.name for edge in self.outedges] if self.outedges else []
        inedges_summary = [edge.name for edge in self.inedges] if self.inedges else []

        # Summarize saved connections as tuples of (other_node_name, edge_name)
        saved_conn_summary = [(node.name, edge.name) for node, edge in
                              self.saved_connections] if self.saved_connections else []

        return (
            f"<Node {self.name}:\n"
            f"  Base Attributes:\n{base_attrs_str}\n"
            f"  Attributes dict:\n        {attr_summary}\n"
            f"  Outedges ({len(outedges_summary)}): {outedges_summary}\n"
            f"  Inedges ({len(inedges_summary)}): {inedges_summary}\n"
            f"  Saved Connections ({len(saved_conn_summary)}): {saved_conn_summary}\n>"
        )

    def agflatten_elist(self, outedge=True, to_list=True):  # from cgraph/flatten.c
        """
        In the snippet, we have a pointer to out_seq or in_seq, then calls dtmethod(d, ...).
        Here, we just call node.flatten_edges, but we might want separate calls for out vs in.
        """
        # 2. Flatten Functions
        # 2.1 agflatten_elist(...)
        # static void agflatten_elist(Dict_t * d, Dtlink_t ** lptr, int flag) {
        #     dtrestore(d, *lptr);
        #     dtmethod(d, flag? Dtlist : Dtoset);
        #     *lptr = dtextract(d);
        # }
        # This toggles the dictionary’s method (list vs. set) for the edges of a node. In Python,
        # we’ll do something simpler: a helper that toggles a node’s single adjacency from list <-> set. Something like:

        if to_list:
            # If outedge, convert node.outedges to a list
            # else, convert node.inedges to a list
            if outedge:
                if isinstance(self.outedges, set):
                    self.outedges = list(self.outedges)
            else:
                if isinstance(self.inedges, set):
                    self.inedges = list(self.inedges)
        else:
            # Convert to set
            if outedge:
                if isinstance(self.outedges, list):
                    self.outedges = set(self.outedges)
            else:
                if isinstance(self.inedges, list):
                    self.inedges = set(self.inedges)

