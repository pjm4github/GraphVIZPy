from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph

from .node import Node
from .edge import Edge
from .error import agerr, Agerrlevel
from .defines import ObjectType
from .headers import AgSym

_logger = logging.getLogger(__name__)


class AttrMixin:
    """Mixin providing attribute management methods for Graph."""

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
            from .graph import Graph
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
            from .graph import Graph
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

    def init_local_attr_values(self):
        """
        Like 'agmakeattrs' in the C code, ensure we have attribute
        storage for each declared symbol relevant to AGRAPH.
        """
        # For each sym in self.attr_dict_g, set to default if we have no value
        for name, value in self.attr_dict_g.items():
            if self.attr_record.get(name) is None:
                self.attr_record[name] = value

    def get_graph_attr(self, attr_name: str) -> str:
        from .graph import get_root_graph
        if attr_name in self.attr_dict_g:
            return self.attr_dict_g[attr_name]
        else:
            # fallback to root if this isn't root
            root = get_root_graph(self)
            return root.attr_dict_g.get(attr_name)

    def agget(self, name:str):  # from /core/attr.c
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

    def agset(self, name, value):  # from /core/attr.c
        """
        Pythonic version of 'agset(obj, name, value)':
        Set the attribute named 'name' for 'obj' to 'value'.
        Return SUCCESS/FAILURE.
        """
        self.set_graph_attr(name, value)

    def agsafeset(self, name, value, default):  # from /core/attr.c
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

    def agdelrec(self, rec_name: str) -> bool:  # from core/rec.c
        """Delete a record by name from both attr_record and base _records."""
        self.attr_record.pop(rec_name, None)
        return super().agdelrec(rec_name)

    def aginit(self, kind: ObjectType, rec_name: str, rec_size: int, mtf: bool = False):  # from core/rec.c
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

    def agclean(self, kind: ObjectType, rec_name: str):  # from core/rec.c
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

    def agattr(self, kind: ObjectType, name: str, value: Optional[str] = None):
        """Create or look up an attribute descriptor."""
        from .graph import get_root_graph
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
        self.agattr(kind=ObjectType.AGGRAPH, name=attr_name, value=default_value)

    def declare_attribute_node(self, attr_name: str, default_value: str):
        self.agattr(kind=ObjectType.AGNODE, name=attr_name, value=default_value)

    def declare_attribute_edge(self, attr_name: str, default_value: str):
        self.agattr(kind=ObjectType.AGEDGE, name=attr_name, value=default_value)

    def agnxtattr(self, kind: int, attr: AgSym = None) -> Optional[AgSym]:
        raise NotImplementedError("Attribute iteration not yet implemented")

    def agxget(self, obj: Any, sym: AgSym) -> Optional[str]:
        raise NotImplementedError("Use node.agget() or edge.agget() instead")

    def agxset(self, obj: Any, sym: AgSym, value: str) -> int:
        raise NotImplementedError("Use node.agset() or edge.agset() instead")

    @staticmethod
    def agattrsym(obj: ['Graph', Node, Edge], name: 'str') -> Optional[AgSym]:  # from /core/attr.c
        """
        Pythonic version of 'agattrsym(obj, name)':
        Return the AgSym corresponding to 'name', or None if not found.
        """
        from .graph import get_root_graph
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

    def agcopyattr(self, src, dst) -> bool:
        """Copy all attributes from src object to dst object.

        Both must be the same type (Node->Node, Edge->Edge, or Graph->Graph).
        Returns True on success.
        """
        if hasattr(src, 'attributes') and hasattr(dst, 'attributes'):
            for k, v in src.attributes.items():
                dst.attributes[k] = v
            return True
        return False
