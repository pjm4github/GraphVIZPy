"""Trace gating for the dot layout engine.

Every diagnostic trace line emitted by the dot phases has the form
``[TRACE <channel>] <message>`` where ``<channel>`` is one of the
channel names listed in :data:`KNOWN_CHANNELS`.  By default none of
these lines are printed.  Set the ``GV_TRACE`` environment variable
to a comma-separated list of channels to enable them; the special
value ``all`` turns on every channel.

The ``spline_*`` family is progressively enabled as functions land
in ``TODO_dot_splines_port.md`` Phases A–G.  Each sub-channel maps
to a concrete subsystem in ``lib/dotgen/dotsplines.c`` and
``lib/common/splines.c`` so that ``filters/diff_phases.py`` can
compare one function's output at a time.

Examples::

    GV_TRACE=spline  python dot.py foo.dot -Tsvg -o foo.svg
    GV_TRACE=rank,order,position  python dot.py foo.dot
    GV_TRACE=spline_path,spline_route  python dot.py foo.dot
    GV_TRACE=all  python dot.py foo.dot

The matching C side uses the same channel vocabulary and is gated via
``lib/common/tracegate.h`` in the graphviz source tree.  Keeping the
vocabulary identical lets ``filters/compare_traces.py`` diff output
line-for-line when both engines are re-enabled.

Design notes
------------
- :func:`trace` prepends ``[TRACE <channel>] `` automatically, so
  callers pass the bare message (no prefix).
- The ``GV_TRACE`` variable is read once at import time and cached.
  Changing it after the engine has been imported has no effect;
  restart the process to switch channels.
- The membership check is a frozenset lookup.  When ``GV_TRACE`` is
  unset the set is empty and every :func:`trace` call is one hash
  miss — effectively free.
- f-strings passed to :func:`trace` are still *evaluated* even when
  the channel is disabled.  For hot-path callers that format
  expensive values, guard with :func:`trace_on` first::

      if trace_on("spline_detail"):
          trace("spline_detail", f"{expensive!r}")
"""
from __future__ import annotations

import os
import sys
from typing import Final


KNOWN_CHANNELS: Final[frozenset[str]] = frozenset({
    "bfs",
    "class2",
    "d5",            # TODO §1 D5 diagnostic: multi-rank edge side-of-
                     # cluster classification, emitted at mincross-exit.
    "d5_step",       # TODO §1 D5 byte-for-byte medians/reorder
                     # alignment — emits rank state + per-swap
                     # decisions so a diff tool can find the first
                     # Python-vs-C divergence in ordering.
    "label",
    "median",
    "order",
    "phase",
    "port",
    "position",
    "rank",
    "record",
    # Spline routing channels — progressively enabled as each phase of
    # the dotsplines.c port lands.  ``spline`` is the top-level phase
    # marker (``phase4 begin`` / ``phase4 end``); the other six are
    # per-subsystem and will get trace emissions as functions land in
    # Phases A–G of TODO_dot_splines_port.md.
    "spline",           # phase begin/end + per-edge summary
    "spline_detail",    # per-edge intermediate control-point dumps
    "spline_regular",   # make_regular_edge internals
    "spline_flat",      # make_flat_edge / make_flat_labeled_edge / ...
    "spline_self",      # makeSelfEdge + self{Top,Bottom,Left,Right}
    "spline_clip",      # clip_and_install + shape_clip + arrow_clip
    "spline_path",      # beginpath / endpath / add_box / maximal_bbox
    "spline_route",     # routesplines_ box-corridor optimiser
})


def _parse_env(raw: str) -> frozenset[str]:
    if not raw:
        return frozenset()
    if raw.strip() == "all":
        return KNOWN_CHANNELS
    return frozenset(c.strip() for c in raw.split(",") if c.strip())


_enabled: frozenset[str] = _parse_env(os.environ.get("GV_TRACE", ""))


def trace_on(channel: str) -> bool:
    """Return True if the given trace channel is enabled."""
    return channel in _enabled


def trace(channel: str, msg: str) -> None:
    """Emit a trace line on the given channel, if enabled.

    The ``[TRACE <channel>] `` prefix is added automatically; pass
    only the message body.
    """
    if channel in _enabled:
        print(f"[TRACE {channel}] {msg}", file=sys.stderr)
