
from typing import Optional, TYPE_CHECKING, Dict

# Forward declarations: these imports are only for type checking.
if TYPE_CHECKING:
    from .headers import *
    from .graph import Graph, get_root_graph
    from .node import Node


from .agobj import Agobj
from .defines import ObjectType, EdgeType
from .headers import Agcmpedge


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

    # ── DOT attribute properties ──────────────────

    @property
    def label(self) -> str:
        return self.attributes.get("label", "")

    @label.setter
    def label(self, value: str):
        self.attributes["label"] = value

    @property
    def color(self) -> str:
        return self.attributes.get("color", "black")

    @color.setter
    def color(self, value: str):
        self.attributes["color"] = value

    @property
    def style(self) -> str:
        return self.attributes.get("style", "")

    @style.setter
    def style(self, value: str):
        self.attributes["style"] = value

    @property
    def penwidth(self) -> str:
        return self.attributes.get("penwidth", "1")

    @penwidth.setter
    def penwidth(self, value: str):
        self.attributes["penwidth"] = value

    @property
    def arrowhead(self) -> str:
        return self.attributes.get("arrowhead", "normal")

    @arrowhead.setter
    def arrowhead(self, value: str):
        self.attributes["arrowhead"] = value

    @property
    def arrowtail(self) -> str:
        return self.attributes.get("arrowtail", "normal")

    @arrowtail.setter
    def arrowtail(self, value: str):
        self.attributes["arrowtail"] = value

    @property
    def dir(self) -> str:
        return self.attributes.get("dir", "forward")

    @dir.setter
    def dir(self, value: str):
        self.attributes["dir"] = value

    @property
    def weight_attr(self) -> int:
        """Edge weight (uses weight_attr to avoid conflict with any base class)."""
        try:
            return int(self.attributes.get("weight", "1"))
        except ValueError:
            return 1

    @weight_attr.setter
    def weight_attr(self, value: int):
        self.attributes["weight"] = str(value)

    @property
    def minlen(self) -> int:
        try:
            return int(self.attributes.get("minlen", "1"))
        except ValueError:
            return 1

    @minlen.setter
    def minlen(self, value: int):
        self.attributes["minlen"] = str(value)

    @property
    def constraint(self) -> bool:
        return self.attributes.get("constraint", "true").lower() not in ("false", "0", "no", "none")

    @constraint.setter
    def constraint(self, value: bool):
        self.attributes["constraint"] = "true" if value else "false"

    @property
    def headport(self) -> str:
        return self.attributes.get("headport", "")

    @headport.setter
    def headport(self, value: str):
        self.attributes["headport"] = value

    @property
    def tailport(self) -> str:
        return self.attributes.get("tailport", "")

    @tailport.setter
    def tailport(self, value: str):
        self.attributes["tailport"] = value

    @property
    def lhead(self) -> str:
        return self.attributes.get("lhead", "")

    @lhead.setter
    def lhead(self, value: str):
        self.attributes["lhead"] = value

    @property
    def ltail(self) -> str:
        return self.attributes.get("ltail", "")

    @ltail.setter
    def ltail(self, value: str):
        self.attributes["ltail"] = value

    @property
    def root_graph(self):
        """Return the root graph of this edge."""
        current = self.graph
        while current.parent is not None:
            current = current.parent
        return current

    # ── Initialization ───────────────────────────

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
        """Backward-compatible alias for root_graph property."""
        return self.root_graph

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

    def get_attr(self, name: str) -> Optional[str]:
        """Get an attribute value by name, falling back to root defaults."""
        return self.get_edge_attr(name)

    def set_attr(self, name: str, value: str):
        """Set an attribute value."""
        self.set_edge_attr(name, value)

    # C API aliases
    agget = get_attr
    agset = set_attr

    def set_edge_attr(self, attr_name: str, value: str):
        """Sets edge's local override for attr_name."""
        self.attributes[attr_name] = value

    def agsafeset(self, name, value, default):
        """Set attribute, declaring with default if it doesn't exist."""
        self.attributes[name] = value
        if name not in self.attributes:
            root = get_root_graph(self.graph)
            if root:
                root.set_graph_attr(name, default)

    def __repr__(self):
        tail = self.tail.name if self.tail else "?"
        head = self.head.name if self.head else "?"
        return f"<Edge {tail}->{head}, etype={self._etype}, name={self.name}>"
