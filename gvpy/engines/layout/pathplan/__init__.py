"""Pathplan — polygonal shortest-path and spline routing primitives.

Python port of Graphviz's ``lib/pathplan/`` source tree.  Used by
Phase D / Phase E of the spline-routing port to route edges around
polygonal barriers and fit cubic Beziers through corridor polylines.

Port status (Phase B):

- **Step B1** — pathgeom, solvers, minimal visibility helpers
  (area2, wind), inpoly, util (Ppolybarriers, make_polyline).
- **Step B2** — full visibility graph: Vconfig, POLYID_*, allocArray,
  inBetween, intersect, in_cone, dist2, dist, inCone, clear, compVis,
  visibility, polyhit, ptVis, directVis.
- **Step B3** — triangulation + shortest path:
  Ptriangulate (ear-clipping), Pshortestpath (funnel algorithm in a
  triangulated polygon), shortestPath (Dijkstra on visibility graph),
  makePath (glue).
- **Step B4** (this commit) — obstacle-avoidance glue: Pobsopen,
  Pobsclose, Pobspath.  End-to-end obstacle-avoidance pipeline is
  now testable.
- Step B5 lands the Proutespline recursive spline-fit engine.

See ``TODO_dot_splines_port.md`` for the full roadmap.
"""
from __future__ import annotations

from gvpy.engines.layout.pathplan.pathgeom import (
    Pedge,
    Ppoint,
    Ppoly,
    Ppolyline,
    Pvector,
)
from gvpy.engines.layout.pathplan.solvers import solve1, solve2, solve3
from gvpy.engines.layout.pathplan.visibility import (
    allocArray,
    area2,
    clear,
    compVis,
    dist,
    dist2,
    directVis,
    in_cone,
    inBetween,
    inCone,
    intersect,
    polyhit,
    ptVis,
    visibility,
    wind,
)
from gvpy.engines.layout.pathplan.inpoly import in_poly
from gvpy.engines.layout.pathplan.util import (
    Ppolybarriers,
    freePath,
    make_polyline,
)
from gvpy.engines.layout.pathplan.vispath import (
    POLYID_NONE,
    POLYID_UNKNOWN,
    Vconfig,
)
from gvpy.engines.layout.pathplan.triang import (
    ISCCW,
    ISCW,
    ISON,
    Ptriangulate,
    ccw,
    isdiagonal,
)
from gvpy.engines.layout.pathplan.shortest import Pshortestpath
from gvpy.engines.layout.pathplan.shortestpth import makePath, shortestPath
from gvpy.engines.layout.pathplan.cvt import Pobsopen, Pobsclose, Pobspath

__all__ = [
    # pathgeom
    "Ppoint",
    "Pvector",
    "Ppoly",
    "Ppolyline",
    "Pedge",
    # solvers
    "solve1",
    "solve2",
    "solve3",
    # visibility
    "allocArray",
    "area2",
    "clear",
    "compVis",
    "dist",
    "dist2",
    "directVis",
    "in_cone",
    "inBetween",
    "inCone",
    "intersect",
    "polyhit",
    "ptVis",
    "visibility",
    "wind",
    # vispath
    "POLYID_NONE",
    "POLYID_UNKNOWN",
    "Vconfig",
    # inpoly
    "in_poly",
    # util
    "Ppolybarriers",
    "freePath",
    "make_polyline",
    # triang
    "ISCCW",
    "ISCW",
    "ISON",
    "Ptriangulate",
    "ccw",
    "isdiagonal",
    # shortest
    "Pshortestpath",
    # shortestpth
    "makePath",
    "shortestPath",
    # cvt (obstacle avoidance glue)
    "Pobsopen",
    "Pobsclose",
    "Pobspath",
]
