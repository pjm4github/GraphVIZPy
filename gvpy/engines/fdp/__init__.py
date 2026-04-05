"""
Fdp layout engine — force-directed placement (not yet implemented).

Fdp uses a spring-electrical model (Fruchterman-Reingold variant)
for undirected graphs.  Supports clusters as rectangular constraints.

Reference: Graphviz lib/fdpgen/
"""


class FdpLayout:
    """Force-directed placement layout engine (not yet implemented)."""

    def __init__(self, graph):
        self.graph = graph

    def layout(self) -> dict:
        raise NotImplementedError("Fdp layout engine not yet implemented")
