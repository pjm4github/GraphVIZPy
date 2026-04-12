"""Layout engine sub-package.

All graph **layout** engines (dot, neato, fdp, circo, twopi, sfdp,
osage, patchwork) live under ``gvpy.engines.layout.<name>``.  This
keeps them grouped under one parent package and leaves the sibling
``gvpy.engines.sim`` namespace free for simulation engines (event-
driven SimPy-style and synchronous CBD-style).

The intermediate base classes :class:`LayoutView` and
:class:`LayoutEngine` live in :mod:`gvpy.engines.layout.base` and
the shared layout helpers (font metrics, post-processing utilities,
the interactive PyQt6 wizard) live alongside them.

Engine discovery still happens through the registry in
:mod:`gvpy.engines.__init__`; this sub-package only provides the
namespace.
"""
from __future__ import annotations
