"""Orthogonal channel router — Python port of C Graphviz ``lib/ortho/``.

Mirrors the C source tree one file per module to preserve step-for-step
trace parity with ``dot.exe``.  Entry point :func:`ortho_edges` is
called once per graph from :mod:`gvpy.engines.layout.dot.dotsplines`
phase 4, gated behind the ``GVPY_ORTHO_V2`` env var during rollout.

Port plan and phase tracker: ``ORTHO_PORT_PLAN.md`` at the repo root.
"""

from gvpy.engines.layout.ortho.ortho import ortho_edges

__all__ = ["ortho_edges"]
