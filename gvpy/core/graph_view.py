"""Base class for graph-attached views.

A GraphView is a domain-specific projection of a Graph — layout
coordinates, simulation state, analysis results, render overrides, etc.
One instance per (graph, view-name) pair, attached via
``graph.views[name] = view``.

C Graphviz analogue
-------------------
In C Graphviz, each engine attaches an ``Agraphinfo_t`` struct to the
graph via ``aginit(g, AGRAPH, "Agraphinfo_t", sizeof(Agraphinfo_t), true)``
and accesses it through the ``AGDATA(g)`` macro.  Macros like
``GD_rank(g)``, ``GD_nlist(g)`` etc. deref through ``AGDATA`` to reach the
per-engine extension data.

In Python we use a dict keyed by view-name — ``graph.views[name]`` — which
allows multiple engines (dot, neato, fdp, ...) to coexist on the same
graph without colliding, and also supports non-layout views (simulation,
analysis, render-state).

View categories
---------------
Concrete subclasses fall into categories, each with its own intermediate
base class:

- ``LayoutView``     — positions, dimensions, edge routes, bboxes
                        (DotGraphInfo, NeatoGraphInfo, PictoGraphInfo, ...)
- ``SimulationView`` — time-domain simulation with per-node state machines
                        and per-edge message channels
- ``AnalysisView``   — graph analysis (SCCs, cycles, centrality, reach)
- ``RenderingView``  — visual state overrides (colors, line styles)

Cross-view communication
------------------------
Views reference each other explicitly via ``graph.views[name]`` lookups.
A rendering view reads the simulation view's per-node overrides; no
``Graph`` pollution.  Views subscribe to graph-mutation events via the
optional ``on_*`` hooks defined below.

Round-trip (graphic ↔ code)
---------------------------
Every view must support both a graphic presentation and a code (JSON)
presentation, and the two must round-trip losslessly.  Subclasses
implement ``to_json()`` and ``from_json()`` for this.  This matches the
pictosync model where the JSON editor and the graphical canvas are two
views of the same underlying state.
"""
from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.core.node import Node
    from gvpy.core.edge import Edge


class GraphView(ABC):
    """Abstract base class for all graph-attached views.

    Subclasses own their per-node / per-edge / per-graph derived state
    and expose query methods.  The base class only tracks the parent
    graph reference and provides optional lifecycle / mutation hooks.
    """

    #: Short identifier for this view category (override in subclasses).
    #: Used as the default key when attaching via ``graph.attach_view``.
    view_name: str = "base"

    def __init__(self, graph: "Graph"):
        self.graph = graph

    # ── Lifecycle hooks ────────────────────────────────────────────
    # Called by graph.attach_view / detach_view.  Override as needed.

    def on_attach(self) -> None:
        """Called after this view is added to ``graph.views``."""

    def on_detach(self) -> None:
        """Called before this view is removed from ``graph.views``."""

    # ── Graph-mutation hooks ───────────────────────────────────────
    # Views that care about structural changes override these.  By
    # default they're no-ops.

    def on_node_added(self, node: "Node") -> None:
        """Called when a node is added to the graph."""

    def on_node_removed(self, node: "Node") -> None:
        """Called when a node is removed from the graph."""

    def on_edge_added(self, edge: "Edge") -> None:
        """Called when an edge is added to the graph."""

    def on_edge_removed(self, edge: "Edge") -> None:
        """Called when an edge is removed from the graph."""

    def on_attr_changed(self, obj: Any, key: str,
                        old: Any, new: Any) -> None:
        """Called when an attribute on a graph, node, or edge changes."""

    # ── Invalidation ───────────────────────────────────────────────

    def invalidate(self) -> None:
        """Mark this view as stale (needs recomputation).

        Views that cache results should clear those caches here.  The
        base implementation is a no-op.
        """

    # ── Round-trip (graphic ↔ code) ───────────────────────────────
    # Subclasses must implement these if they have persistent state.

    def to_json(self) -> dict[str, Any]:
        """Serialize this view's state to a JSON-compatible dict.

        Every view that has user-editable or persistent state must
        override this.  The serialized form must be sufficient to
        reconstruct an equivalent view via ``from_json``.
        """
        return {"view_name": self.view_name}

    def from_json(self, data: dict[str, Any]) -> None:
        """Restore this view's state from a JSON-compatible dict.

        Must be the inverse of ``to_json`` — i.e. after
        ``v.from_json(v.to_json())`` the view should be unchanged.
        """
