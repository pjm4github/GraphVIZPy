"""Visibility-graph path routing — public API surface.

C analogue: ``lib/pathplan/vispath.h`` + ``lib/pathplan/vis.h``.

Phase B step B2 lands the :class:`Vconfig` dataclass plus the
``POLYID_*`` sentinel constants.  The ``Pobsopen`` / ``Pobsclose`` /
``Pobspath`` entry points land in step B4 (they glue visibility +
shortest-path together).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


# ── POLYID sentinel values ─────────────────────────────────────────
# C analogue: ``vispath.h:50-51``.
#
# Passed to ``Pobspath`` / ``ptVis`` / ``directVis`` as the "which
# polygon does this endpoint belong to" hint:
#   POLYID_NONE    — caller verified the endpoint is outside every obstacle
#   POLYID_UNKNOWN — caller does not know; visibility helper should check
#   >= 0           — the endpoint is inside polygon of this index

POLYID_NONE: Final[int] = -1111
POLYID_UNKNOWN: Final[int] = -2222


@dataclass
class Vconfig:
    """Opaque visibility-graph state handle.

    C analogue: ``struct vconfig_s`` in ``lib/pathplan/vis.h:29-39``::

        struct vconfig_s {
            int Npoly;
            int N;           /* number of points in walk of barriers */
            Ppoint_t *P;     /* barrier points */
            int *start;
            int *next;
            int *prev;
            array2 vis;      /* computed visibility matrix */
        };

    All fields preserve C's spelling and semantics:

    - ``Npoly`` — number of polygonal obstacles.
    - ``N`` — total number of vertices across *all* obstacles (flat).
    - ``P`` — flat list of :class:`~...pathgeom.Ppoint` vertices, one
      polygon's points after another.
    - ``start`` — list of length ``Npoly + 1``.  ``start[i]`` is the
      index of the first vertex of polygon ``i`` in ``P``, and
      ``start[Npoly]`` == ``N`` sentinels the end.
    - ``next`` — list of length ``N`` giving the next-vertex index for
      each point (within the same polygon, wrapping at the polygon's
      last vertex back to its first).
    - ``prev`` — list of length ``N``, the reverse of ``next``.
    - ``vis`` — visibility matrix, lazily populated by :func:`visibility`.
      Shape: ``N + 2`` rows (the extra 2 are placeholders for the two
      query points added dynamically by ``Pobspath``).  The first ``N``
      rows each have length ``N``; the extra rows are ``None`` until
      ``Pobspath`` fills them.

    ``next`` shadows Python's builtin ``next()`` — that's fine because
    it's an attribute, not a module-level name.  Kept verbatim from C
    for fidelity.
    """

    Npoly: int = 0
    N: int = 0
    P: list = field(default_factory=list)      # list[Ppoint]
    start: list = field(default_factory=list)  # list[int]
    next: list = field(default_factory=list)   # list[int] — shadows builtin
    prev: list = field(default_factory=list)   # list[int]
    vis: list | None = None                    # list[list[float] | None] | None
