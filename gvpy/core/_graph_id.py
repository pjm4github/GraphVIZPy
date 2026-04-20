from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any, Callable, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import Graph

from .error import agerr, Agerrlevel
from .defines import ObjectType, LOCALNAMEPREFIX
from .headers import AgIdDisc

_logger = logging.getLogger(__name__)


class IdMixin:
    """Mixin providing ID management and dictionary methods for Graph."""

    def agfreeid(self, obj_type: ObjectType, old_id: int):  # from /core/id.c
        """
        Frees an internal ID associated with a enclosed_node object.

        Not really needed in Python but added here for completeness.

        :param obj_type: The type of object ('AGRAPH', 'AGNODE', 'AGEDGE').
        :param old_id: The ID to free.
        """
        from ._graph_traversal import get_root_graph, gather_all_subgraphs
        if obj_type == ObjectType.AGGRAPH:
            g = get_root_graph(self)
            sg_list = gather_all_subgraphs(g)
            for sgr in sg_list:
                if sgr.id == old_id:
                    self.delete_subgraph(sgr)
                    break
        elif obj_type == ObjectType.AGNODE:
            found_node = self.find_node_by_id(old_id)
            if found_node is None:
                agerr(Agerrlevel.AGWARN, f"The Node with id = {old_id} does not exist in enclosed_node '{self.name}'.")
            else:
                self.delete_node(found_node)
        elif obj_type == ObjectType.AGEDGE:
            found_edge = self.find_edge_by_id(old_id)
            if found_edge is None:
                agerr(Agerrlevel.AGWARN, f"The Edge with id = {old_id} does not exist in enclosed_node '{self.name}'.")
            else:
                self.delete_edge(found_edge)

    def agallocid(self, id_: int, objt: Optional[ObjectType] = None) -> bool:
        """
        Allocates a unique ID for a subgraph.

        :param id_: The unique identifier to allocate.
        :param objt: the type of object which defaults to a enclosed_node
        :return: True if allocation was successful, else False.
        """
        if id_ in self.id_to_subgraph:
            agerr(Agerrlevel.AGERR, f"[Graph] ID '{id_}' is already allocated to subgraph '{self.id_to_subgraph[id_].name}'.")
            return False
        else:
            """
            Attempts to allocate a specific ID. Always fails in this implementation.
            Equivalent to agallocid in C.
            """
            otype = objt if objt else ObjectType.AGGRAPH
            agerr(Agerrlevel.AGINFO, f"[Graph] ID '{id_}' allocated for new subgraph.")
            return self.disc.alloc(self.clos, otype, id_)

    def agregister(self, obj_type: Union[ObjectType, str], subg: 'Graph'):
        """
        Registers a subgraph within the enclosed_node's subgraph dictionary.

        :param obj_type: The type of object ('GRAPH').
        :param subg: The subgraph to register.
        """
        if isinstance(obj_type, str):

            if obj_type == 'AGRAPH':
                obj_type = ObjectType.AGGRAPH
        if obj_type == ObjectType.AGGRAPH:
            self.id_to_subgraph[subg.id] = subg
            self.subgraphs[subg.name] = subg
            # self.subgraph_name_to_id[subg.name] = subg.id
            agerr(Agerrlevel.AGINFO, f"[Graph] Subgraph '{subg.name}' with ID '{subg.id}' registered.")
        else:
            agerr(Agerrlevel.AGINFO, f"[Graph] Registration failed: Unsupported object type '{obj_type}'.")

    @staticmethod
    def agdtinsert(dict_: 'GraphDict', handle: Any):
        """
        Inserts an item into a dictionary.

        :param dict_: The dictionary to insert into.
        :param handle: The item to insert.
        """
        key = handle['key']
        dict_[key] = handle

    @staticmethod
    def agdtsearch(dict_: Dict, key: Any) -> Optional[Any]:
        """
        Searches for an item in a dictionary.

        :param dict_: The dictionary to search.
        :param key: The key to search for.
        :return: The found item or None.
        """
        return dict_.get(key)

    @staticmethod
    def agdictobjmem(p: Optional[Any], size: int) -> Optional[Any]:  # from the /core/utils.c
        """
        Custom memory allocation/deallocation function.
        Behavior: If a global enclosed_node (Ag_dictop_G) is set, it uses agalloc or agfree for memory operations; otherwise, it defaults to malloc and free.
        Emulates agdictobjmem from C.
         # agdictobjmem: from the /core/utils.c
        """
        if p:
            # Emulate agfree(g, p)
            agerr(Agerrlevel.AGINFO, f"[Agraph] Freeing object: {p}")
            # In Python, garbage collection handles memory, so explicit freeing isn't required
            return None
        else:
            # Emulate agalloc(g, size)
            obj = object.__new__(object)  # Allocate a new generic object
            agerr(Agerrlevel.AGINFO, f"[Agraph] Allocating new object of size {size}: {obj}")
            return obj

    @staticmethod
    def agdictobjfree(p: Any):
        """
        Custom object free function.Purpose: Frees memory for dictionary objects.
        Emulates agdictobjfree from C. from the /core/utils.c
        Behavior: Similar to agdictobjmem, it uses agfree if a global enclosed_node is set, else free.
        """
        # Emulate agfree(g, p)
        agerr(Agerrlevel.AGINFO, f"[Agraph] Freeing object: {p}")
        # In Python, garbage collection handles memory, so explicit freeing isn't required

    def agdtopen(self, method: Optional[Callable] = None) -> 'GraphDict':
        """
        Opens a new dictionary with a specific discipline.
        Purpose: Opens a new dictionary with a specific discipline.
        Emulates agdtopen from C from the /core/utils.c
        Behavior: Temporarily sets the global enclosed_node (Ag_dictop_G), assigns the custom memory function, and opens the dictionary.
        """
        from .graph import GraphDict
        agerr(Agerrlevel.AGINFO, f"[Agraph] Opening dictionary with discipline and method: {method}")
        self.dict = GraphDict(discipline=self.disc, method=method)
        return self.dict

    def agdtdelete(self, obj: Any) -> bool:
        """
        Deletes an object from the dictionary.
        Purpose: Deletes an object from the dictionary.
        Emulates agdtdelete from C.from the /core/utils.c
        Behavior: Sets the global enclosed_node and deletes the object using dtdelete.
        """
        if not self.dict:
            agerr(Agerrlevel.AGINFO, "[Agraph] Dictionary not initialized.")
            return False
        success = self.dict.delete(obj)
        if success:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Deleted object from dictionary: {obj}")
        else:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Object not found in dictionary: {obj}")
        return success

    def agdtclose(self) -> bool:
        """
        Closes the dictionary.Purpose: Closes the dictionary.
        Emulates agdtclose from C.from the /core/utils.c
        Behavior: Sets the global enclosed_node, closes the dictionary using dtclose, and restores the original memory function.
        """
        if not self.dict:
            agerr(Agerrlevel.AGINFO, "[Agraph] Dictionary not initialized or already closed.")
            return False
        success = self.dict.close()
        if success:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Dictionary closed successfully.")
        else:
            agerr(Agerrlevel.AGINFO, f"[Agraph] Failed to close dictionary.")
        self.dict = None
        return success

    def agdtdisc(self, disc: AgIdDisc):
        """
        Sets the discipline for the dictionary.
        Purpose: Sets the discipline for the dictionary.
        Behavior: Updates the dictionary's discipline if it's different from the current one.
        Emulates agdtdisc from C.from the /core/utils.c
        """
        agerr(Agerrlevel.AGINFO, f"[Agraph] Setting discipline: {disc}")
        self.disc = disc
        if self.dict:
            self.dict.discipline = disc

    def get_next_sequence(self, objtype: ObjectType) -> int:
        """
        Retrieves the next sequence number for the given object type.

        :param objtype: The type of the object
            (ObjectType.AGGRAPH, ObjectType.AGNODE, ObjectType.AGEDGE) an ObjectType
            or
            (AGTYPE_GRAPH, AGTYPE_NODE, AGTYPE_EDGE) a string
        :return: The next sequence number.
        """
        return self.clos.get_next_sequence(objtype)

    def map_name_to_id(self, objtype: ObjectType, name: Optional[str], createflag: bool) -> Optional[int]: # from /core/id.c
        """
        Maps a name to an ID, creating it if 'createflag' is True.
        Equivalent to agmapnametoid in C.
        """
        agerr(Agerrlevel.AGWARN, "Use self.disc.map() instead")
        return self.disc.map(self.clos, objtype, name, createflag)

    def internal_map_lookup(self, objtype: ObjectType, name: str) -> Optional[int]:
        """
        Equivalent to aginternalmaplookup: looks up the ID for a given name and objtype.
        Returns the ID if found, else None.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        return self.clos.lookup_by_name[objtype].get(name)

    def internal_map_insert(self, objtype: ObjectType, name: str, id_: int):
        """
        Equivalent to aginternalmapinsert: inserts a new name-ID mapping.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        self.clos.lookup_by_name[objtype][name] = id_
        self.clos.lookup_by_id[objtype][id_] = name

    def internal_map_print(self, objtype: ObjectType, id_: int) -> Optional[str]:
        """
        Equivalent to aginternalmapprint: returns the name associated with an ID.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        return self.clos.lookup_by_id[objtype].get(id_)

    def internal_map_delete(self, objtype: ObjectType, id_: int) -> bool:
        """
        Equivalent to aginternalmapdelete: deletes the name-ID mapping for the given ID.
        Returns True if deleted, False otherwise.
        """
        if objtype == ObjectType.AGEDGE:
            objtype = ObjectType.AGEDGE  # Handle AGINEDGE if necessary
        name = self.clos.lookup_by_id[objtype].get(id_)
        if name:
            del self.clos.lookup_by_id[objtype][id_]
            del self.clos.lookup_by_name[objtype][name]
            return True
        return False

    def internal_map_clear_local_names(self):
        """
        Equivalent to aginternalmapclearlocalnames: removes all mappings where name starts with LOCALNAMEPREFIX.
        """
        for objtype in ObjectType:
            lookup_name = self.clos.lookup_by_name[objtype]
            names_to_remove = [name for name in lookup_name if name.startswith(LOCALNAMEPREFIX)]
            for name in names_to_remove:
                id_ = lookup_name[name]
                del lookup_name[name]
                del self.clos.lookup_by_id[objtype][id_]

    def internal_map_close(self):
        """
        Equivalent to aginternalmapclose: closes all mapping dictionaries.
        """
        for objtype in ObjectType:
            self.clos.lookup_by_name[objtype].clear()
            self.clos.lookup_by_id[objtype].clear()


# ── Module-level helpers ────────────────────────────────────────────

def agnextseq(g: "Graph", objtype: ObjectType) -> int:
    """Increment and return the next sequence number for ``objtype``.

    See: /lib/cgraph/graph.c @ 152

    In gvpy the closure's per-object-type sequence counter lives in
    ``g.clos`` and is bumped via ``g.get_next_sequence(objtype)``.
    Extracted from ``graph.py`` as part of the core refactor (TODO
    ``TODO_core_refactor.md`` step 6).
    """
    return g.get_next_sequence(objtype)
