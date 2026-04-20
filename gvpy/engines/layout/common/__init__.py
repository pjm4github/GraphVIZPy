"""Engine-agnostic utilities shared across layout engines.

Mirrors Graphviz's ``lib/common/`` library — primitives every layout
binary links against (geometry, text layout, shapes, splines, post-
processing).  Imports may come from any engine subpackage (``dot``,
``neato``, ``circo``, etc.); this package never imports back from them
to avoid cycles.
"""
