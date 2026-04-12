"""SimulationView — abstract intermediate base for simulation engines.

Sits between :class:`gvpy.core.graph_view.GraphView` and the two
concrete simulation paradigms (event-driven and synchronous block
diagram).  Mirrors the :class:`gvpy.engines.layout.base.LayoutView`
pattern: the abstract intermediate fixes the *contract* (lifecycle,
time queries, per-node/per-edge state queries, JSON round-trip) so
consumers can drive a simulation without caring whether it's
SimPy-style discrete events or PyCBD-style synchronous dataflow.

Lifecycle contract
------------------
Subclasses must implement these:

- :meth:`init`     — build runtime simulation state from the graph
- :meth:`step`     — advance one event/iteration; return False when done
- :meth:`reset`    — restore initial state at ``t = 0``

The base provides :meth:`run` as a convenience loop over ``step``.

Time
----
``self.now`` is the current simulation time.  For event-driven
engines this is a float that jumps to the next scheduled event;
for synchronous block diagrams it advances by ``delta_t`` per
iteration.  ``self.is_done()`` lets the base ``run`` loop know when
to stop without having to peek into engine internals.

Round-trip
----------
The :meth:`to_json` / :meth:`from_json` pair captures *simulation
state* — current time, per-block state vector, event-queue contents
— so a paused simulation can be saved and resumed.  This matches
the pictosync pattern where the JSON editor and the graphical
canvas are two views of the same underlying state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional

from gvpy.core.graph_view import GraphView

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.core.node import Node
    from gvpy.core.edge import Edge


class SimulationView(GraphView, ABC):
    """Abstract base class for simulation views attached to a Graph.

    Concrete subclasses are:

    - :class:`gvpy.engines.sim.events.EventSimulationView` —
      SimPy-style discrete-event simulation.
    - :class:`gvpy.engines.sim.cbd.CBDSimulationView` —
      PyCBD-style synchronous block diagrams (three-phase Mealy).

    The base class only stores the parent graph reference, the
    current simulation time, and the bookkeeping flag set by
    :meth:`init`.  Everything paradigm-specific lives in the
    subclass.
    """

    view_name: str = "simulation"

    def __init__(self, graph: "Graph"):
        super().__init__(graph)
        self._now: float = 0.0
        self._initialized: bool = False

    # ── Lifecycle (subclass overrides) ────────────────────────────

    @abstractmethod
    def init(self) -> None:
        """Build the runtime simulation state from the graph topology.

        Subclasses walk ``self.graph.nodes`` / ``self.graph.edges``
        and instantiate per-node and per-edge runtime objects
        (processes, blocks, ports, channels) based on attributes.
        Should set ``self._initialized = True`` on success.
        """

    @abstractmethod
    def step(self) -> bool:
        """Advance the simulation by one unit.

        Returns ``True`` if the simulation made progress, ``False``
        if there is nothing left to do (event queue empty, end-time
        reached, etc.).
        """

    @abstractmethod
    def reset(self) -> None:
        """Restore the simulation to its initial state at ``t = 0``."""

    # ── Time / progress queries ───────────────────────────────────

    @property
    def now(self) -> float:
        """Current simulation time."""
        return self._now

    def is_done(self) -> bool:
        """Return True if there is no more work to do.

        The default implementation always returns False; subclasses
        with a finite event queue or end-time should override.
        """
        return False

    # ── Convenience driver loop ───────────────────────────────────

    def run(self, until: Optional[float] = None,
            max_steps: Optional[int] = None) -> None:
        """Step the simulation until a stop condition is met.

        Stops when *any* of these become true:

        - ``until`` is set and ``self.now >= until``
        - ``max_steps`` is set and that many steps have been taken
        - :meth:`step` returns False (engine reports it's done)
        - :meth:`is_done` returns True

        :meth:`init` is called automatically if it hasn't been yet.
        """
        if not self._initialized:
            self.init()

        steps = 0
        while True:
            if until is not None and self._now >= until:
                return
            if max_steps is not None and steps >= max_steps:
                return
            if self.is_done():
                return
            if not self.step():
                return
            steps += 1

    # ── Per-element state queries ─────────────────────────────────
    # Subclasses override these to expose their runtime state in a
    # uniform way (so a UI / trace recorder doesn't need to know
    # whether it's looking at a Process or a Block).

    def get_node_state(self, name: str) -> dict[str, Any]:
        """Return current state of the runtime object for node ``name``.

        Default returns ``{}``.  Subclasses populate with engine-
        specific keys (process status, block outputs, etc.).
        """
        return {}

    def get_edge_state(self, edge: "Edge") -> dict[str, Any]:
        """Return current state of the runtime object for an edge.

        Default returns ``{}``.  Subclasses populate with channel
        contents, connection values, etc.
        """
        return {}

    # ── Round-trip serialization ──────────────────────────────────

    def to_json(self) -> dict[str, Any]:
        """Serialize simulation state to a JSON-compatible dict.

        The base implementation captures only the view name and the
        current time.  Subclasses should extend with their per-node
        / per-edge runtime state and any pending event queue
        contents.
        """
        return {
            "view_name": self.view_name,
            "now": self._now,
            "initialized": self._initialized,
        }

    def from_json(self, data: dict[str, Any]) -> None:
        """Restore simulation state from a JSON-compatible dict.

        The base implementation restores only the time and
        initialized flag.  Subclasses should extend.
        """
        self._now = float(data.get("now", 0.0))
        self._initialized = bool(data.get("initialized", False))
