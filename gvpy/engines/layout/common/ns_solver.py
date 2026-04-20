"""Network-simplex solver — engine-agnostic re-export.

See: /lib/common/ns.c @ 623

The canonical implementation lives in
:mod:`gvpy.engines.layout.dot.ns_solver` (imported by dot's Phase 1
ranking and Phase 3 X-position passes).  The solver itself is pure
numeric — it takes (nodes, edges, minlen, weight) and returns integer
ranks — so other engines (a future neato refinement pass, a
lightweight DAG arranger, etc.) can reuse it without touching dot.

This module re-exports the public class so callers don't have to
reach into the dot subpackage.
"""
from gvpy.engines.layout.dot.ns_solver import _NetworkSimplex  # noqa: F401

# A more readable public alias.  ``_NetworkSimplex`` keeps its
# leading underscore in the dot module because it was historically
# a private implementation detail; exposing it from ``common`` we
# drop the underscore so cross-engine code reads naturally.
NetworkSimplex = _NetworkSimplex

__all__ = ["NetworkSimplex", "_NetworkSimplex"]
