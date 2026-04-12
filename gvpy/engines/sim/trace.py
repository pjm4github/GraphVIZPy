"""Optional simulation-trace recorder.

Captures per-step snapshots of named signals so plots / debug
output / regression tests can compare runs.

Usage::

    trace = SimulationTrace()
    cbd_view.run(...)        # caller writes to trace via record()
    trace.record(t, "x", value)
    series = trace.get_series("x")   # -> list[(time, value)]

This is intentionally minimal — it's a passive bag of timestamped
samples, not a live observer that hooks into solver phases.  A
caller decides what to record and when.  More elaborate
hookup (decorator, automatic per-block) can be layered on top
later.
"""
from __future__ import annotations

from typing import Any


class SimulationTrace:
    """Per-signal time-series recorder.

    Stores samples as ``{name: [(time, value), ...]}``.  No
    interpolation, no decimation — what you record is what you
    get back.
    """

    def __init__(self):
        self._series: dict[str, list[tuple[float, Any]]] = {}

    def record(self, time: float, name: str, value: Any) -> None:
        """Append a ``(time, value)`` sample to series ``name``."""
        self._series.setdefault(name, []).append((time, value))

    def get_series(self, name: str) -> list[tuple[float, Any]]:
        """Return the recorded samples for series ``name`` (empty
        list if nothing was ever recorded under that name)."""
        return list(self._series.get(name, []))

    def names(self) -> list[str]:
        """Return the list of recorded series names."""
        return sorted(self._series.keys())

    def clear(self) -> None:
        """Drop every recorded sample."""
        self._series.clear()

    def to_json(self) -> dict[str, list[list]]:
        """Serialize as ``{name: [[t, v], [t, v], ...]}``."""
        return {
            name: [[t, v] for t, v in samples]
            for name, samples in self._series.items()
        }

    def from_json(self, data: dict[str, list[list]]) -> None:
        """Restore from a dict produced by :meth:`to_json`."""
        self._series = {
            name: [(s[0], s[1]) for s in samples]
            for name, samples in data.items()
        }
