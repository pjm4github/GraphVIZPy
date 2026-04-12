"""Simulation engine sub-package.

Two paradigms live side by side here:

- **Event-driven** (SimPy-inspired) — :mod:`gvpy.engines.sim.events`
  provides ``Environment``, ``Event``, ``Timeout``, and ``Process``
  for discrete-event simulation where time advances by jumping to
  the next scheduled event.

- **Synchronous block diagrams** (PyCBD-inspired) —
  :mod:`gvpy.engines.sim.cbd` provides ``Block``, ``StatefulBlock``,
  ``DelayBlock``, ``CompoundBlock``, and a small primitive library
  (``ConstantBlock``, ``GainBlock``, ``AdderBlock``, ...).
  :mod:`gvpy.engines.sim.solver` runs the three-phase Mealy step
  (Output → Update → Advance) described in Van Tendeloo &
  Vangheluwe (2018).

Both paradigms share the :class:`SimulationView` base from
:mod:`gvpy.engines.sim.base`, which extends
:class:`gvpy.core.graph_view.GraphView` so a simulation attaches to
a :class:`gvpy.core.graph.Graph` via ``graph.views[name]``
alongside any layout view.

Public API
----------
Re-exports the most commonly used classes for terse imports::

    from gvpy.engines.sim import Environment, Process, Timeout
    from gvpy.engines.sim import CompoundBlock, GainBlock, DelayBlock
    from gvpy.engines.sim import CBDSolver, SimulationView
"""
from __future__ import annotations

from .base import SimulationView
from .clock import Clock, DiscreteClock, ContinuousClock
from .events import (
    Environment,
    Event,
    Timeout,
    Process,
    EventSimulationView,
)
from .cbd import (
    Port,
    Connection,
    Block,
    StatefulBlock,
    DelayBlock,
    CompoundBlock,
    ConstantBlock,
    GainBlock,
    AdderBlock,
    NegatorBlock,
    ProductBlock,
    CBDSimulationView,
)
from .solver import CBDSolver, topological_sort
from .trace import SimulationTrace

__all__ = [
    # base
    "SimulationView",
    # clocks
    "Clock", "DiscreteClock", "ContinuousClock",
    # event-driven
    "Environment", "Event", "Timeout", "Process",
    "EventSimulationView",
    # cbd
    "Port", "Connection", "Block", "StatefulBlock", "DelayBlock",
    "CompoundBlock", "ConstantBlock", "GainBlock", "AdderBlock",
    "NegatorBlock", "ProductBlock", "CBDSimulationView",
    # solver / utility
    "CBDSolver", "topological_sort", "SimulationTrace",
]
