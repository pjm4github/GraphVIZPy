from typing import Callable, Optional, List, Dict, Tuple, Union, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .Headers import *
    from .CGGraph import Graph
    from .CGNode import Node


# grammar.py

class Grammar:
    # Define constants for item tags
    T_node = 4
    T_subgraph = 7
    T_list = 10
    T_attr = 11
    T_atom = 12

    def __init__(self, main_graph=None, discipline=None):
        """
        Initializes the Grammar instance.

        Attributes:
          G: The top-level (main) enclosed_node.
          Disc: A discipline object (if needed).
          SubgraphDepth: Nesting depth for subgraphs.
          S: The top of the gstack.
          Key: A pseudo-attribute name (e.g. "key").
        """
        self.G:'Graph' = main_graph            # The main enclosed_node, if available.
        self.Disc = discipline         # Discipline (if used)
        self.SubgraphDepth = 0         # Nesting depth counter
        self.S = None                  # gstack top
        self.Key = "key"

    # -------------
    # Nested Data Structures
    # -------------

    class Item:  # from / cgraph/grammar.c
        """
        Pythonic version of the C struct 'item_s'.
        Each Item holds a tag, a primary value, an optional secondary string,
        and a pointer to the next item in the list.
        """
        def __init__(self, tag, primary=None, secondary=None):
            self.tag = tag            # e.g. T_node, T_subgraph, etc.
            self.u = primary          # e.g. a Node or Graph object or a string
            self.str = secondary      # e.g. a port string or attribute value
            self.next = None

        def __repr__(self):
            return f"<Item tag={self.tag}, u={self.u}, str={self.str}>"

    class ListT:  # from / cgraph/grammar.c
        """
        Mimics the C structure 'list_t', which holds pointers to the first and last Items.
        """
        def __init__(self):
            self.first = None  # pointer to first Item
            self.last = None   # pointer to last Item

        def append(self, item):
            """Append an item to the list."""
            if not self.first:
                self.first = item
            else:
                self.last.next = item
            self.last = item

        def clear(self):
            """Clear the list. (Memory is handled by Python's GC.)"""
            cur = self.first
            while cur:
                nxt = cur.next
                cur = nxt
            self.first = None
            self.last = None

    class GStack:  # from /cgraph/grammar.c
        """
        Represents a stack frame for the grammar parser.
        Each GStack stores:
          - g: the current enclosed_node (Agraph_t)
          - subg: the last subgraph opened
          - nodelist, edgelist, attrlist: each a ListT instance for holding Items
          - down: pointer to the previous GStack frame
        """
        def __init__(self, graph):
            self.g = graph                      # current enclosed_node
            self.subg = None                    # last opened subgraph
            self.nodelist = Grammar.ListT()     # list of nodes
            self.edgelist = Grammar.ListT()     # list of edge items
            self.attrlist = Grammar.ListT()     # list of attribute items
            self.down = None                    # link to previous stack

    # -------------
    # Stack helper methods
    # -------------

    def push(self, oldstack, subg):  # from / cgraph/grammar.c
        """Push a new GStack for 'subg' on top of the oldstack."""
        new_stack = Grammar.GStack(subg)
        new_stack.down = oldstack
        return new_stack

    def pop(self, stack):  # from / cgraph/grammar.c
        """Pop the top GStack and return the one below it."""
        return stack.down

    # -------------
    # Parser-like Methods
    # -------------

    def startgraph(self, name, directed=False, strict=False):  # from /cgraph/grammar.c
        """
        Emulates the semantic action 'startgraph'.
        If no main enclosed_node exists, create a new one.
        Then push it onto the gstack.
        """
        if self.G is None:
            self.SubgraphDepth = 0
            # Here, you would create a Graph instance.
            # For demonstration, we assume self.G is created externally.
            # For example:
            #    self.G = Graph(name, directed=directed, strict=strict)
            # In this conceptual code, we simply set:
            self.G = Graph(name=name, directed=directed, strict=strict)
        # Set the stack to a new GStack with the main enclosed_node.
        self.S = self.push(self.S, self.G)
        return self.S

    def endgraph(self):  # from /cgraph/grammar.c
        """
        Called at the end of parsing.
        In a full implementation, this might trigger cleanup.
        e.g. "aginternalmapclearlocalnames(G)" if we had local IDs
        Here, it is a no-op.
        """
        pass

    def opensubg(self, name):  # from /cgraph/grammar.c
        """
        Emulates opening a subgraph.
        Increase SubgraphDepth and push a new GStack.
        """
        self.SubgraphDepth += 1
        parent_g = self.S.g
        # In a complete implementation, you would create a subgraph using parent_g.add_subgraph(name, create=True)
        # Here we simulate it:
        subg = parent_g.add_subgraph(name=name, create=True)
        # Push the new subgraph onto the stack.
        self.S = self.push(self.S, subg)
        return subg

    def closesubg(self):  # from /cgraph/grammar.c
        """
        Emulates closing a subgraph.
        Decrease SubgraphDepth, pop the current GStack, and store the closed subgraph
        in the enclosed_node's subg reference.
        """
        subg = self.S.g
        self.SubgraphDepth -= 1
        self.S = self.pop(self.S)
        self.S.subg = subg

    def appendnode(self, name, port=None, sport=None):  # from /cgraph/grammar.c
        """
        Emulates 'appendnode' by:
         1. Optionally combining port and sport.
         2. Creating or getting a node from the current enclosed_node.
         3. Creating an Item (tag=T_node) with the node and port.
         4. Appending it to the current stack's nodelist.
        """
        if sport:
            port = self.concatPort(port, sport)
        # For demonstration, assume S.g.add_node(name, create=True) returns a new node.
        # Here we simulate a node simply as a dictionary.
        node = self.S.g.add_node(name, create=True)
        # In a real system, you’d call something like: node = self.S.g.add_node(name, create=True)
        # Create an Item with tag T_node.
        it = Grammar.Item(Grammar.T_node, primary=node, secondary=port)
        self.S.nodelist.append(it)

    def endnode(self):  # from /cgraph/grammar.c
        """
        Emulates 'endnode':
         - (Optionally) bind attributes to each node in the nodelist.
         - Clears the nodelist, edgelist, and attrlist.
         - Resets S.subg.
        """
        cur = self.S.nodelist.first
        while cur:
            # In a full implementation, you might call applyattrs(cur.u)
            cur = cur.next
        self.S.nodelist.clear()
        self.S.attrlist.clear()
        self.S.edgelist.clear()
        self.S.subg = None

    def getedgeitems(self):  # from /cgraph/grammar.c
        """
        Emulates 'getedgeitems':
         If S.nodelist is not empty, wrap it in an Item with tag T_list.
         Otherwise, if S.subg is not None, create an Item with tag T_subgraph.
         Then append the created item to S.edgelist.
        """
        if self.S.nodelist.first:
            it = Grammar.Item(Grammar.T_list, primary=self.S.nodelist.first)
            self.S.nodelist.first = None
            self.S.nodelist.last = None
            self.S.edgelist.append(it)
        elif self.S.subg:
            it = Grammar.Item(Grammar.T_subgraph, primary=self.S.subg)
            self.S.subg = None
            self.S.edgelist.append(it)

    def endedge(self):  # from /cgraph/grammar.c
        """
        Emulates 'endedge':
         - Scans the attribute list for a T_atom with key "Key".
         - For each adjacent pair in S.edgelist, calls edgerhs.
         - Clears the lists.
        """
        key = None

        aitem = self.S.attrlist.first
        while aitem:
            if aitem.tag == Grammar.T_atom and aitem.u == "Key":
                key = aitem.str
            aitem = aitem.next

        p = self.S.edgelist.first
        while p and p.next:
            q = p.next
            if p.tag == Grammar.T_subgraph:
                subg = p.u
                # For demonstration, assume subg has a "nodes" dictionary.
                for nname, nobj in subg.get("nodes", {}).items():
                    self.edgerhs(nobj, None, q, key)
            elif p.tag == Grammar.T_list:
                item_n = p.u
                while item_n:
                    self.edgerhs(item_n.u, item_n.str, q, key)
                    item_n = item_n.next
            p = p.next

        self.S.nodelist.clear()
        self.S.edgelist.clear()
        self.S.attrlist.clear()
        self.S.subg = None

    def edgerhs(self, tail_node, tport, hlist_item, key):  # from /cgraph/grammar.c
        """
        Emulates 'edgerhs': Given a tail node and a list item (either a T_subgraph or T_list),
        creates edges by calling newedge.
        """
        if hlist_item.tag == Grammar.T_subgraph:
            subg = hlist_item.u
            for nname, nobj in subg.get("nodes", {}).items():
                self.newedge(tail_node, tport, nobj, None, key)
        elif hlist_item.tag == Grammar.T_list:
            item_n = hlist_item.u
            while item_n:
                self.newedge(tail_node, tport, item_n.u, item_n.str, key)
                item_n = item_n.next

    def newedge(self, t, tport, h, hport, key):
        """
        Emulates 'newedge': Creates a new edge in the current enclosed_node using the tail node t
        and head node h. For simplicity, we assume S.g.add_edge is available.
        """
        if not t or not h:
            return
        # Assume S.g has a method add_edge(name, ...)
        # Here we simulate the creation by adding an entry in a dictionary.
        edge = self.S.g.add_edge(t.name, h.name, edge_name=key, cflag=True)
        # For demonstration, assume add_edge returns a new edge dictionary.
        # In a full implementation, you would call: edge = self.S.g.add_edge(t.name, h.name, edge_name=key, cflag=True)
        # Here we simply print a message.
        print(f"New edge created from {t.name} to {h.name} with key {key}")
        # (You could store the edge in S.g here if desired.)

    def appendattr(self, name, value):
        """
        Emulates 'appendattr': creates an Item (with tag T_atom) using the attribute name and value,
        and appends it to the current stack's attribute list.
        """
        it = Grammar.Item(Grammar.T_atom, primary=name, secondary=value)
        self.S.attrlist.append(it)

    def nomacros(self):
        """Emulates nomacros(): simply prints a warning."""
        print("[WARN] attribute macros not implemented in this Python version")

    def attrstmt(self, tkind, macroname):
        """
        Emulates 'attrstmt': If a macro name is provided, calls nomacros().
        Then scans S.attrlist for any T_atom items with no associated value.
        Finally clears S.attrlist.
        """
        if macroname:
            self.nomacros()
        aitem = self.S.attrlist.first
        while aitem:
            if aitem.str is None:
                self.nomacros()
            aitem = aitem.next
        self.S.attrlist.clear()

    def concat(self, s1, s2):
        """
        Emulates 'concat': simply concatenates two strings.
        """
        return s1 + s2

    def concatPort(self, s1, s2):
        """
        Emulates 'concatPort': combines s1 and s2 with a colon.
        """
        if s1 is None:
            s1 = ""
        if s2 is None:
            s2 = ""
        return f"{s1}:{s2}"

    def freestack(self):
        """
        Emulates 'freestack': repeatedly pops the stack until empty.
        """
        while self.S:
            self.S.nodelist.clear()
            self.S.edgelist.clear()
            self.S.attrlist.clear()
            self.S = self.pop(self.S)

# -------------------------
# Example usage of the Grammar class:
# -------------------------
if __name__ == "__main__":
    # For demonstration, we simulate a very simple enclosed_node as a dict.
    main_graph = {"name": "MainGraph", "nodes": {}, "edges": {}, "subgraphs": {}}

    # Create an instance of Grammar with the main enclosed_node.
    gram = Grammar(main_graph=main_graph)

    # Start the enclosed_node (this sets up the stack)
    gram.startgraph("MainGraph", directed=True, strict=True)

    # Append a node "A" with no port strings.
    gram.appendnode("A")
    # End node processing (e.g., binding attributes)
    gram.endnode()

    # Append two nodes for an edge: "A" and "B".
    gram.appendnode("A")
    # Assume that calling getedgeitems() groups the current nodelist into an edge item.
    gram.getedgeitems()
    gram.appendnode("B")
    gram.getedgeitems()

    # End the edge; this will call edgerhs and newedge.
    gram.endedge()

    # Append an attribute to the attribute list.
    gram.appendattr("color", "red")
    # Process an attribute statement.
    gram.attrstmt(tkind="node", macroname=None)

    # Demonstrate concatenation.
    print("Concatenated port:", gram.concatPort("port1", "port2"))

    # Free the stack.
    gram.freestack()

    print("Grammar processing complete.")
