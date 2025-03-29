from typing import Dict, Optional
from .Defines import *


class Agrec:
    """
    Represents a record associated with a enclosed_node object.
    """
    def __init__(self, name: str):
        self.name = name
        self.attributes: Dict[str, Any] = {}
        # Add other fields as necessary


class Agobj:  # from cgraph/cgraph.c
    """
    The base object type, loosely corresponding to 'Agobj_t' in Graphviz.
    """

    def __init__(self, obj_type: ObjectType):
        self.obj_type = obj_type
        self.attributes = {}
        self._records: Dict[str, Agrec] = {}
        self._mtflock: bool = False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def get_attribute(self, key, default=None):
        return self.attributes.get(key, default)

    def agbindrec(self, rec_name: str, rec_size: int, move_to_front: bool = False) -> Agrec:
        """
        Binds a new record to the object.

        :param rec_name: The name of the record.
        :param rec_size: The size of the record (unused in Python).
        :param move_to_front: Flag indicating whether to move the record to the front.
        :return: The newly created record.
        """
        if rec_name in self._records:
            raise ValueError(f"Record '{rec_name}' already exists in {self.obj_type}.")

        record = Agrec(name=rec_name)
        self._records[rec_name] = record

        if move_to_front:
            # Move to front logic can be handled if needed
            pass

        print(f"[Agobj] Record '{rec_name}' bound to {self.obj_type} with mtf={move_to_front}.")
        return record

    def aggetrec(self, rec_name: str, move_to_front: bool = False) -> Optional[Agrec]:
        """
        Retrieves a record by name from the object.

        :param rec_name: The name of the record to retrieve.
        :param move_to_front: Flag indicating whether to move the record to the front upon retrieval.
        :return: The requested record if it exists, else None.
        """
        record = self._records.get(rec_name)

        if record:
            if move_to_front and not self._mtflock:
                # Implement move-to-front logic if records are ordered
                pass
            return record
        else:
            print(f"[Agobj] Record '{rec_name}' not found in {self.obj_type}.")
            return None

    def agdelrec(self, rec_name: str) -> bool:
        """
        Deletes a record by name from the object.

        :param rec_name: The name of the record to delete.
        :return: True if deletion was successful, False otherwise.
        """
        if rec_name not in self._records:
            print(f"[Agobj] Record '{rec_name}' does not exist in {self.obj_type}.")
            return False

        del self._records[rec_name]
        print(f"[Agobj] Record '{rec_name}' deleted from {self.obj_type}.")
        return True

    def agrecclose(self):
        """
        Closes all records associated with the object.
        """
        self._records.clear()
        self._mtflock = False
        print(f"[Agobj] All records closed for {self.obj_type}.")

    @staticmethod
    def agnameof(obj) -> Optional[str]:  # from /cgraph/id.c
        """
        Returns the name associated with an object.
        For Nodes and Graphs with even IDs, returns the name.
        For Edges or anonymous IDs, returns the edge's key if available or None.
        Equivalent to agnameof in C.
        """
        from .CGNode import Node
        from .CGGraph import Graph
        from .CGEdge import Edge
        if isinstance(obj, Node):
            objtype = ObjectType.AGGRAPH if isinstance(obj, Graph) else ObjectType.AGNODE
            return obj.parent.disc.print_id(obj.parent.clos, objtype, obj.id)
        elif isinstance(obj, Graph):
            objtype = ObjectType.AGGRAPH if isinstance(obj, Graph) else ObjectType.AGNODE
            return obj.disc.print_id(obj.clos, objtype, obj.id)
        elif isinstance(obj, Edge):
            return obj.key  # Assuming edges do not have names unless keys are used
        else:
            return None

    def __repr__(self):
        return f"<Agobj type={self.obj_type}>"

