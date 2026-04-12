"""Clock abstractions for simulation engines.

Two flavours of time-keeping live here:

- :class:`DiscreteClock` — fixed step ``delta_t``, integer
  iteration counter.  Used by :class:`gvpy.engines.sim.cbd
  .CBDSimulationView` for synchronous block diagrams.

- :class:`ContinuousClock` — floating-point ``now`` that jumps to
  the next scheduled event time.  Used by :class:`gvpy.engines.sim
  .events.EventSimulationView` for SimPy-style discrete events.

Both implement the :class:`Clock` protocol so any sim driver code
can ask ``clock.now``, ``clock.advance(dt)``, ``clock.reset()``
without caring which flavour it has.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Clock(ABC):
    """Abstract clock protocol used by both sim paradigms."""

    @property
    @abstractmethod
    def now(self) -> float:
        """Current simulation time."""

    @abstractmethod
    def advance(self, dt: float) -> None:
        """Advance the clock by ``dt`` time units."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the clock to its initial state (``now == 0``)."""


class DiscreteClock(Clock):
    """Fixed-step clock with integer iteration counter.

    Used by synchronous block-diagram simulators where every block
    is computed once per ``delta_t`` tick.  ``iteration`` increments
    on every :meth:`advance` and ``now`` is always
    ``iteration * delta_t``.
    """

    def __init__(self, delta_t: float = 1.0):
        self.delta_t = float(delta_t)
        self.iteration: int = 0

    @property
    def now(self) -> float:
        return self.iteration * self.delta_t

    def advance(self, dt: float | None = None) -> None:
        """Advance one tick.

        ``dt`` is accepted for protocol compatibility but ignored —
        the discrete clock always advances by exactly one
        ``delta_t``.
        """
        self.iteration += 1

    def reset(self) -> None:
        self.iteration = 0


class ContinuousClock(Clock):
    """Floating-point clock that jumps to arbitrary times.

    Used by event-driven simulators where ``advance(dt)`` is called
    with the delay between successive events on the priority queue.
    """

    def __init__(self):
        self._now: float = 0.0

    @property
    def now(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        if dt < 0:
            raise ValueError(f"Cannot advance clock backwards: dt={dt}")
        self._now += float(dt)

    def jump_to(self, t: float) -> None:
        """Jump the clock forward to absolute time ``t``.

        Convenience used by the event-queue stepper which sets
        ``now`` to the next event's scheduled time directly.
        """
        if t < self._now:
            raise ValueError(
                f"Cannot jump backwards: t={t} < now={self._now}"
            )
        self._now = float(t)

    def reset(self) -> None:
        self._now = 0.0
