"""
Core graph library — Python port of Graphviz core.

Provides Graph, Node, Edge classes with subgraph support,
compound nodes, callback system, and attribute management.
"""
from .graph import Graph
from .node import Node, CompoundNode
from .edge import Edge
from .defines import ObjectType, EdgeType, GraphEvent
from .headers import Agdesc, AgIdDisc
