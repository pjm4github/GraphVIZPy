"""
Twopi layout engine — radial layout (not yet implemented).

Twopi arranges nodes in concentric circles radiating outward from
a root node.  Each ring corresponds to a BFS level from the root.

Reference: Graphviz lib/twopigen/
"""


class TwopiLayout:
    """Radial layout engine (not yet implemented)."""

    def __init__(self, graph):
        self.graph = graph

    def layout(self) -> dict:
        raise NotImplementedError("Twopi layout engine not yet implemented")
