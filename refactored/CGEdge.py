
from typing import Optional, TYPE_CHECKING, Dict

# Forward declarations: these imports are only for type checking.
if TYPE_CHECKING:
    from .Headers import *
    from .CGGraph import Graph, get_root_graph
    from .CGNode import Node


from .Agobj import Agobj
from .Defines import ObjectType, EdgeType
from .Headers import Agcmpedge


class EdgeSeqLink:  # This is a derived class to handle the MACRO EDGEOF in /cgraph/cgraph.h
    """
    A small 'link' or dictionary node that
    references the containing Edge directly.
    """
    def __init__(self, edge: "Edge"):
        self.edge = edge  # direct pointer to the Edge object


class Edge(Agobj):   # from cgraph/cgraph.c

    """
    Pythonic equivalent of 'Agedge_t'.
    Includes a reference to the 'enclosed_node' that owns this edge.
    Attributes:
        tail: Reference to the "tail" node (used if etype == "AGOUTEDGE").
        head: Reference to the "head" node (used if etype == "AGINEDGE").
        etype: String indicating whether this is an out-edge ("AGOUTEDGE") or in-edge ("AGINEDGE").
        opp: Reference to the 'opposite' half of the same logical edge.
        node:  Typically, cgraph stores 'edge.node' for whichever node is relevant
               (tail if out-edge, head if in-edge).
               In a simpler design, you might store 'tail'/'head' separately
               and let 'node' be an alias.
        graph: The enclosed_node Graph object this edge belongs to.
        name:  Optional textual label or key for this edge.
        ...

    """

    def __init__(self, tail: 'Node', head: 'Node', name: str, graph: 'Graph', id_=None,
                 seq=None, etype: str = None, key=None, attributes: Optional[Dict[str, str]] = None, directed=False):
        super().__init__(obj_type=ObjectType.AGEDGE)
        self.tail = tail  # source
        self.head = head  # destination
        self.name = name
        # Instead of storing a memory offset, store an object with a direct reference
        self.seq_link = EdgeSeqLink(self)
        # That way, from seq_link, we can jump back to 'Edge' via seq_link.edge

        self.graph = graph  # The enclosed_node that owns this edge
        self.id = id_         # numeric ID
        self.seq = seq        # sequence number
        self._etype = None    # 'AGOUTEDGE' or 'AGINEDGE'
        # We'll store _opp privately and expose a property for opp
        self._opp: Optional["Edge"] = None # Opposite half-edge
        # Set the etype via our property to ensure consistency:
        self.etype = etype if etype else EdgeType.AGOUTEDGE
        # You might also store a single "node" pointer that cgraph uses
        # for 'edge->node' in the out/in halves:
        # If self.etype == "AGOUTEDGE": self.node = tail
        # else:                         self.node = head
        if self.etype == EdgeType.AGOUTEDGE:  # "AGOUTEDGE":
            self.node = tail
        else:
            self.node = head

        self.init_local_attr_values() # mimic 'agedgeattr_init(g,e)'
        self.key = key  # e.g. the "pseudo-attribute" if set
        self.graph.agmethod_init(self)
        # self.enclosed_node.method_init()  # agmethod_init(self.enclosed_node, self)

        # "Compound edge" data
        self.cmp_edge_data = Agcmpedge()


        self.attributes: Dict[str, str] = attributes or {}
        # Attributes to store original connections when collapsing
        self.saved_from: Optional['Node'] = None  # Original tail before collapse
        self.saved_to: Optional['Node'] = None    # Original head before collapse
        self.directed = directed
        # key = (tail_name, head_name, name)
        # key = ()
        # if self.enclosed_node:
        #     if key in self.enclosed_node.edges:
        #         raise agerr(Agerrlevel.AGERR, 'Edge key already exists')
        #     else:
        #         self.enclosed_node.edges[key] = self

    @property
    def etype(self) -> str:
        """
        Return the current edge type: "AGOUTEDGE" or "AGINEDGE".
        """
        return self._etype

    @etype.setter
    def etype(self, new_etype: str):
        """
        Change this half-edge's etype to 'AGOUTEDGE' or 'AGINEDGE'.
        Also update self.node accordingly, and if we have an opposite half-edge,
        adjust it so both remain consistent (no infinite recursion).
        """
        if new_etype not in (EdgeType.AGOUTEDGE, EdgeType.AGINEDGE):
            raise ValueError("etype must be 'AGOUTEDGE' (EdgeType.AGOUTEDGE) or 'AGINEDGE' (EdgeType.AGINEDGE)")

        # 1) Update our own etype
        self._etype = new_etype

        # 2) Update self.node based on new_etype
        #    cgraph logic: out-edge => node=tail; in-edge => node=head
        if self._etype == EdgeType.AGOUTEDGE:  # "AGOUTEDGE":
            self.node = self.tail
        else:  # AGINEDGE
            self.node = self.head

        # 3) If we have an opposite half-edge, update it to the complementary type
        #    BUT do so without calling its property setter to avoid infinite recursion
        if self._opp is not None:
            if self._etype == EdgeType.AGOUTEDGE:  # "AGOUTEDGE":
                # Then opp must be 'AGINEDGE'
                self._opp._etype = EdgeType.AGINEDGE  # "AGINEDGE"
                self._opp.node = self._opp.head
            else:
                # self is in-edge => opp must be out-edge
                self._opp._etype = EdgeType.AGOUTEDGE  # "AGOUTEDGE"
                self._opp.node = self._opp.tail

    @property
    def opp(self) -> Optional["Edge"]:
        """
        'opp' is the opposite half-edge of this logical edge.
        If self is an out-edge, self.opp is the corresponding in-edge, and vice versa.
        """
        return self._opp

    @opp.setter
    def opp(self, other: Optional["Edge"]):
        """
        Ensures a two-way link: if we set self.opp = other,
        also set other.opp = self (unless it's already correct).
        """
        self._opp = other
        if other is not None and other.opp is not self:
            other._opp = self

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
            for attr_name, default_value in root.attr_dict_e.items():
                # 3) If the local edge doesn’t already have an override, set it
                if attr_name not in self.attributes:
                    self.attributes[attr_name] = default_value

    def get_root_graph(self):
        current = self.graph
        while current.parent is not None:
            current = current.parent  # climb the parent
        return current

    def agedgeattr_init(self):
        """
        Allocate space & defaults for each declared Edge attribute.
        Similar to 'agedgeattr_init'.
        """
        self.init_local_attr_values()

    def root_attr_dict(self):
        """Return the dictionary of edge attributes from the *root* enclosed_node."""
        root = self.graph
        if root:
            while getattr(root, 'enclosed_node', None):  # climb to root
                root = root.parent
            return root.attr_dict_e
        else:
            return {}

    def get_edge_attr(self, attr_name: str) -> str:

        if attr_name in self.attributes:
            return self.attributes[attr_name]
        else:
            # fallback to the root's default
            attr_dict = self.root_attr_dict()
            default_value = attr_dict.get(attr_name)
            return default_value  # might be None if never declared

    def agget(self, name: str):  # from /cgraph/attr.c
        """
        Pythonic version of 'agget(obj, name)':
        Return the string value of the attribute named 'name' for obj.
        Return None if attribute does not exist.
        """
        return self.get_edge_attr(name)

    def set_edge_attr(self, attr_name: str, value: str):
        self.attributes[attr_name] = value

    def agset(self, name, value):  # from /cgraph/attr.c
        """
        Pythonic version of 'agset(obj, name, value)':
        Set the attribute named 'name' for 'obj' to 'value'.
        Return SUCCESS/FAILURE.
        """
        self.set_edge_attr(name, value)

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
            root = get_root_graph(self.graph)
            root.set_graph_attr(name, default)

    # def __repr__(self):
    #     repr_str = f"{self.__class__.__name__}"
    #     repr_str += '('
    #
    #     for key, val in self.__dict__.items():
    #         val = f"'{val}'" if isinstance(val, str) else val
    #         repr_str += f"{key}={val}, "
    #     rs = repr_str.strip(", ") + ')'
    #     label = f"<{rs}>"
    #     return label
    def __repr__(self):
        def safe_repr(val):
            from .CGGraph import Graph
            from .CGNode import Node
            if isinstance(val, Graph):
                return f"<Graph {val.name}>"
            elif isinstance(val, Node):
                return f"<Node {val.name}>"
            elif isinstance(val, Edge):
                return f"<Edge {val.name}>"
            else:
                return repr(val)

        # Gather all attributes from __dict__
        base_attrs = {}
        for attr, value in self.__dict__.items():
            base_attrs[attr] = safe_repr(value)

        # Build a string with each attribute on its own indented line.
        base_attrs_str = "\n".join(f"    {k}: {v}" for k, v in base_attrs.items())

        return (
            f"<Edge {self.name}:\n"
            f"{base_attrs_str}\n>"
        )

        #
        # direction = "Not Set"
        # directed = getattr(self, 'directed', None)
        # if directed:
        #     direction = "->" if self.directed else "--"
        # has_etype = getattr(self, 'etype', None)
        # ty = "Not Set"
        # if has_etype:
        #     ty = self.etype.replace("AG", "")
        # id =  getattr(self, 'id', "Not Set")
        # head = getattr(self, 'head', None)
        # head_name = "Not Set"
        # if head:
        #     head_name = getattr(self, 'head', head_name)
        # tail = getattr(self, 'tail', None)
        # tail_name = "Not Set"
        # if tail:
        #     tail_name = getattr(self, 'head', tail_name)
        #
        # label = (f"<Edge (tail) {tail_name} {direction} (head) {head_name}, id={id}, "
        #          f"seq={self.seq}, type={ty}, key={self.key or ''}, attributes={self.attributes}")
        # if self.name:
        #     label += f" [name={self.name}]"
        # return label + ">"


def agedgeattr_init(g, e):
    """
    Mimic 'agedgeattr_init(Agraph_t * g, Agedge_t * e)'.
    If e->attr_record is not set, allocate, fill defaults, etc.
    """
    raise NotImplemented("Use the edge.agedgeattr_init method")


def EDGEOF(rep: "EdgeSeqLink") -> "Edge":
    """
    cgraph uses pointer arithmetic to get Agedge_t from rep->seq_link.
    In Python, you typically store a direct reference to the Edge object.
    So we can return 'rep' if 'rep' is already an Edge, or a field from rep.
    """
    return rep.edge  # If 'rep' is already the Edge
