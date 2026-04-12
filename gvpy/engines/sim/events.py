"""Event-driven simulation primitives (SimPy-inspired).

Implements a minimal subset of the `SimPy <https://simpy.readthedocs.io>`_
discrete-event simulation API:

- :class:`Environment` — owns the priority queue and the current time
- :class:`Event`       — generic event with a callback list
- :class:`Timeout`     — convenience event scheduled at ``now + delay``
- :class:`Process`     — wraps a generator that yields events to wait on

Usage::

    def producer(env):
        while True:
            yield env.timeout(2)
            print(f"produced at {env.now}")

    env = Environment()
    env.process(producer(env))
    env.run(until=10)

Process / Event lifecycle
-------------------------
A :class:`Process` is itself an :class:`Event` — it succeeds when its
generator returns.  When a process yields an event ``e``, the runtime
adds the process's ``_resume`` method as a callback on ``e``.  When
``e`` fires (its time arrives or it's manually triggered), all
callbacks run, and ``_resume`` calls ``send`` on the generator with
``e.value``.  This is exactly how SimPy threads processes through
events.

Three differences from real SimPy
---------------------------------
1. **No resources / stores** — only the bare event/process loop.
2. **No interruptions** — a process can't be cancelled mid-flight.
3. **Single-process step**: :meth:`Environment.step` pops one event
   and fires its callbacks.  No batched-time semantics.

These omissions keep the skeleton small; they can be added later
without breaking the public API.
"""
from __future__ import annotations

import heapq
import itertools
from typing import TYPE_CHECKING, Any, Callable, Generator, Optional

from .base import SimulationView
from .clock import ContinuousClock

if TYPE_CHECKING:
    from gvpy.core.graph import Graph


# ── Core event/process classes ──────────────────────────────────────


class Event:
    """A future occurrence in the simulation.

    Holds a list of callbacks that fire when the event is triggered.
    Subclasses (:class:`Timeout`, :class:`Process`) layer scheduling
    and generator-resumption semantics on top.
    """

    def __init__(self, env: "Environment"):
        self.env = env
        self.callbacks: list[Callable[["Event"], None]] = []
        self.value: Any = None
        # ``triggered``  — the event has been *scheduled* (placed on the
        #                  heap or registered for immediate fire).  Set
        #                  by Timeout's constructor and Event.succeed().
        # ``_processed`` — the callbacks have actually been invoked.
        #                  Set by Environment.step() right before
        #                  ``cb(event)``.  Late ``add_callback`` calls
        #                  see this and fire the callback immediately
        #                  (matching SimPy semantics).
        self.triggered: bool = False
        self._processed: bool = False
        self.ok: bool = True  # False if .fail() was used
        self.exc: Optional[BaseException] = None

    # Triggering --------------------------------------------------

    def succeed(self, value: Any = None) -> "Event":
        """Mark the event as successful with an optional return value.

        Subsequent processes that yielded this event will resume
        with ``value``.  The event is added to the env's run-queue
        so its callbacks fire on the next :meth:`Environment.step`.
        """
        if self.triggered:
            raise RuntimeError(f"{self!r} already triggered")
        self.ok = True
        self.value = value
        self.triggered = True
        self.env._enqueue_now(self)
        return self

    def fail(self, exc: BaseException) -> "Event":
        """Mark the event as failed with the given exception."""
        if self.triggered:
            raise RuntimeError(f"{self!r} already triggered")
        self.ok = False
        self.exc = exc
        self.triggered = True
        self.env._enqueue_now(self)
        return self

    # Callback wiring ---------------------------------------------

    def add_callback(self, cb: Callable[["Event"], None]) -> None:
        """Register ``cb`` to be invoked when this event fires.

        If the event has already been *processed* (callbacks have
        already run), the new callback fires immediately with the
        event's stored value — matching SimPy's late-subscription
        semantics.  Merely being *scheduled* (``triggered=True``)
        is not enough: the queue still needs to pop this event so
        time can advance to its scheduled instant before fan-out
        runs.
        """
        if self._processed:
            cb(self)
        else:
            self.callbacks.append(cb)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} triggered={self.triggered}>"


class Timeout(Event):
    """An event scheduled to fire after a fixed delay.

    Constructed via :meth:`Environment.timeout`; you typically don't
    create one directly.
    """

    def __init__(self, env: "Environment", delay: float, value: Any = None):
        super().__init__(env)
        if delay < 0:
            raise ValueError(f"Timeout delay must be non-negative: {delay}")
        self.delay = float(delay)
        self.value = value
        # Schedule immediately
        env._schedule(self, env.now + self.delay)
        self.triggered = True  # already on the queue


class Process(Event):
    """A simulation process backed by a Python generator.

    The generator yields :class:`Event` instances to wait on.  When
    each yielded event fires, the runtime sends its ``value`` back
    into the generator (or throws the exception if the event
    failed).  When the generator returns or raises StopIteration,
    the process itself fires (so other processes can wait on it).
    """

    def __init__(self, env: "Environment", generator: Generator):
        super().__init__(env)
        self._gen = generator
        # Kick off the generator on the next step
        self.env._enqueue_now(_StartEvent(env, self))

    def _resume(self, _trigger: Event) -> None:
        """Resume the generator after a yielded event has fired."""
        try:
            if _trigger is self or isinstance(_trigger, _StartEvent):
                next_event = self._gen.send(None)
            elif _trigger.ok:
                next_event = self._gen.send(_trigger.value)
            else:
                next_event = self._gen.throw(_trigger.exc)
        except StopIteration as si:
            # Process complete — trigger ourselves with the return value
            self.value = si.value
            self.triggered = True
            self.env._enqueue_now(self)
            return
        except BaseException as exc:
            self.exc = exc
            self.ok = False
            self.triggered = True
            self.env._enqueue_now(self)
            return

        # Generator yielded another event — wait for it
        next_event.add_callback(self._resume)


class _StartEvent(Event):
    """Internal: kicks a freshly created Process into its first step."""

    def __init__(self, env: "Environment", process: "Process"):
        super().__init__(env)
        self.value = None
        self.ok = True
        self.triggered = True
        self.add_callback(process._resume)


# ── The Environment (priority queue + step loop) ────────────────────


class Environment:
    """SimPy-style environment: priority queue of scheduled events.

    The queue is a heap of ``(time, seq, event)`` tuples; ``seq`` is
    a monotonic counter so equal-time events fire in scheduling
    order (FIFO tie-breaking).  ``step()`` pops one event, advances
    ``now`` to its time, and fires all of its callbacks (which may
    enqueue more events).

    The clock is a :class:`gvpy.engines.sim.clock.ContinuousClock`;
    you can read it via ``env.now`` (a property).
    """

    def __init__(self):
        self.clock = ContinuousClock()
        self._heap: list[tuple[float, int, Event]] = []
        self._counter = itertools.count()

    @property
    def now(self) -> float:
        return self.clock.now

    # Scheduling --------------------------------------------------

    def _schedule(self, event: Event, time: float) -> None:
        """Push ``event`` onto the heap to fire at ``time``."""
        seq = next(self._counter)
        heapq.heappush(self._heap, (time, seq, event))

    def _enqueue_now(self, event: Event) -> None:
        """Schedule ``event`` to fire at the current time (callbacks
        run on the very next ``step``)."""
        self._schedule(event, self.now)

    def timeout(self, delay: float, value: Any = None) -> Timeout:
        """Create and schedule a :class:`Timeout` event."""
        return Timeout(self, delay, value)

    def event(self) -> Event:
        """Create an unscheduled :class:`Event`.  Trigger it manually
        via :meth:`Event.succeed` or :meth:`Event.fail`."""
        return Event(self)

    def process(self, generator: Generator) -> Process:
        """Wrap a generator in a :class:`Process` and schedule it."""
        return Process(self, generator)

    # Stepping ----------------------------------------------------

    def step(self) -> bool:
        """Pop the next event off the heap and fire its callbacks.

        Returns ``True`` if an event was processed, ``False`` if the
        queue is empty.
        """
        if not self._heap:
            return False
        time, _seq, event = heapq.heappop(self._heap)
        if time > self.now:
            self.clock.jump_to(time)
        event._processed = True
        # Fire callbacks (they may enqueue more events)
        for cb in event.callbacks:
            cb(event)
        event.callbacks.clear()
        return True

    def run(self, until: Optional[float] = None) -> None:
        """Step the queue until empty or ``now >= until``."""
        while True:
            if until is not None and self.now >= until:
                return
            if not self.step():
                return


# ── GraphView wrapper ───────────────────────────────────────────────


class EventSimulationView(SimulationView):
    """SimulationView wrapper around a SimPy-style :class:`Environment`.

    Holds a single :class:`Environment` instance and a registry of
    per-graph-node Process objects.  ``init`` walks the graph and
    instantiates a Process for each node whose ``process_factory``
    attribute resolves to a generator function.

    For now this is mostly skeleton: the user is expected to populate
    ``self.processes`` directly or override :meth:`init` for custom
    binding semantics.  The lifecycle methods just delegate to
    ``self.env``.
    """

    view_name: str = "sim_event"

    def __init__(self, graph: "Graph"):
        super().__init__(graph)
        self.env = Environment()
        # name -> Process (one per graph node, optional)
        self.processes: dict[str, Process] = {}

    def init(self) -> None:
        """Default init: no-op.

        Subclasses or callers should populate ``self.processes`` by
        looking at ``self.graph.nodes`` attributes and calling
        ``self.env.process(factory(self.env, node))``.  This base
        method just marks the view as initialized so :meth:`run`
        won't re-call it.
        """
        self._initialized = True

    def reset(self) -> None:
        """Recreate the Environment and clear processes."""
        self.env = Environment()
        self.processes.clear()
        self._now = 0.0
        self._initialized = False

    def step(self) -> bool:
        """Pop one event off the env's queue."""
        result = self.env.step()
        self._now = self.env.now
        return result

    def is_done(self) -> bool:
        return not self.env._heap

    def get_node_state(self, name: str) -> dict[str, Any]:
        proc = self.processes.get(name)
        if proc is None:
            return {}
        return {
            "triggered": proc.triggered,
            "value": proc.value,
            "ok": proc.ok,
        }

    def to_json(self) -> dict[str, Any]:
        d = super().to_json()
        d["paradigm"] = "event"
        d["heap_size"] = len(self.env._heap)
        d["processes"] = {
            name: self.get_node_state(name) for name in self.processes
        }
        return d
