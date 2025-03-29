import threading
from contextlib import contextmanager
from enum import Enum
from typing import Callable, Optional, List, Dict, Any, TYPE_CHECKING


SUCCESS = 0
FAILURE = 1

LOCALNAMEPREFIX = '_'  # Prefix for internal/system-generated names

AGTYPE_GRAPH = 'AGraph'
AGTYPE_NODE = 'AGNode'
AGTYPE_EDGE = 'AGEdge'

class GraphEvent(Enum):
    NODE_ADDED = 'node_added'
    NODE_DELETED = 'node_deleted'
    EDGE_ADDED = 'edge_added'
    EDGE_DELETED = 'edge_deleted'
    SUBGRAPH_ADDED = 'subgraph_added'
    SUBGRAPH_DELETED = 'subgraph_deleted'
    UNKNOWN_EVENT = 'unknown_event'
    INVALID_EVENT = 'invalid_event'
    INITIALIZE = 'initialize'
    MODIFY = 'modify'  # Added 'modify' event
    DELETION = 'deletion'  # Added 'deletion' event
    # Additional events can be added here

class ObjectType(Enum):
    AGGRAPH = 0
    AGNODE = 1
    AGEDGE = 2
    AGINEDGE = 3  # Internal/System-generated edges
    AGOUTEDGE = 4

class EdgeType:
    AGOUTEDGE = "AGOUTEDGE"
    AGINEDGE = "AGINEDGE"

