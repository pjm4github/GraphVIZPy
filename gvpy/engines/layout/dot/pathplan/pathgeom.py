"""Pathplan geometry primitives (back-compat re-export).

The canonical definitions now live in
:mod:`gvpy.engines.layout.common.geom`.  This module re-exports them
so existing ``from gvpy.engines.layout.dot.pathplan.pathgeom import …``
imports keep working.
"""
from gvpy.engines.layout.common.geom import Ppoint, Pvector, Ppoly, Ppolyline, Pedge

__all__ = ["Ppoint", "Pvector", "Ppoly", "Ppolyline", "Pedge"]
