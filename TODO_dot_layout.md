# Dot Layout Engine — Complete

All planned layout features have been implemented.

## Implemented Features

- [x] Network simplex for ranking and X-positioning
- [x] Virtual nodes for multi-rank edges
- [x] Cycle breaking (DFS)
- [x] Crossing minimization (weighted median + transpose)
- [x] Rank constraints (same/min/max/source/sink)
- [x] Label-based node sizing (text width/height estimation)
- [x] Record shape parsing (field separators, ports)
- [x] `newrank` (global vs cluster-aware ranking)
- [x] `group` attribute (weight boost ×100)
- [x] `samehead`/`sametail` (shared edge endpoints)
- [x] `clusterrank` (local/global/none)
- [x] `pos`/`pin` (fixed node positioning)
- [x] `rankdir` (TB/BT/LR/RL)
- [x] `ranksep`/`nodesep` (spacing control)
- [x] `splines` (ortho/polyline/bezier/line)
- [x] `compound`/`lhead`/`ltail` (cluster edge clipping)
- [x] `concentrate` (parallel edge merging)
- [x] `ordering` (preserve input order)
- [x] `size`/`ratio` (graph scaling)
- [x] `constraint` (exclude edges from ranking)
- [x] `minlen`/`weight` (edge ranking attributes)
- [x] `tailport`/`headport` (compass direction + record port routing)
- [x] `headclip`/`tailclip` (disable edge boundary clipping)
- [x] `nslimit`/`nslimit1` (NS iteration limits)
- [x] `mclimit`/`remincross` (crossing minimization parameters)
- [x] `searchsize` (NS search limit)
- [x] `normalize` (shift coordinates to origin)
- [x] `labelangle`/`labeldistance` (edge label offset)
- [x] `quantum` (grid snapping)
- [x] SVG output (`svg_renderer.py`)
- [x] Multi-graph file support (`read_dot_all`)
- [x] Encoding fallback (UTF-8 → latin-1)
- [x] Subgraph edge collection (edges from subgraphs included in layout)

---

## Rendering — Delegate to Pictosync

The rendering pipeline will be handled by the **pictosync** project, not by GraphvizPy directly. The `svg_renderer.py` in this project is a minimal standalone renderer for testing/debugging.

### Integration Plan
- The layout engine (`DotLayout.layout()`) produces a JSON dict with node positions, edge routes, cluster boxes, and all DOT attributes.
- Pictosync consumes this JSON and renders via its `attribute_schema.json` pipeline.

### Pictosync Integration Files
- **Pictosync project:** `C:\Users\pmora\OneDrive\Documents\Git\GitHub\pictosync`
- **Schema file:** `pictosync/attribute_schema.json`
- **SVG registry:** `pictosync/SVGNodeRegistry`

---

## TODO: Layout-side cluster avoidance (deferred)

Two related improvements that fix edge-cluster crossings at the
**layout** level rather than the routing level.  Deferred because
they touch mincross / position code which is fragile and has been
carefully tuned; the channel routing work in ``splines.py`` is
being done first and should eliminate the user-visible crossings
by post-processing.

### (c) Layout divergence — same-side placement

For some multi-rank edges, Python places the endpoints on
**opposite sides** of a cluster while C places them on the **same
side**, so C's edge naturally avoids the cluster and Python's
can't.  The clearest example on ``aa1332.dot`` is ``c0 → c5359``:

- C: both c0 and c5359 end up on the same side of cluster_5378 in
  the cross-rank direction; C's polyline stays on that side and
  never enters the cluster.
- Python: c0 is visually *above* cluster_5378 (y=23) and c5359 is
  visually *below* (y=396); the edge must cross the cluster's
  cross-rank y range at some point.

Root cause suspected in mincross + phase 3 cross-rank Y assignment.
Specifically, Python's cross-rank ordering for the rank containing
c0 places c0 at order 0 (top of rank) while C's places it at the
bottom of its rank.  Needs investigation into:

1. What median value c0 gets during mincross (what are its
   neighbors pulling it toward?)
2. Whether the Y assignment in ``phase3_position``'s NS X solver
   treats rank 0's first node as "top" or "bottom" consistently
   with C's convention.
3. Whether the rank-axis y convention is consistent with apply_rankdir.

Investigation will be a separate dedicated session; probably a
multi-phase instrumentation workflow per ``CLAUDE.md``.

### (d) Position-time virtual-node y constraints

An intermediate fix that's more forward-compatible with the full
channel routing: when ``ns_x_position`` computes virtual-node
cross-rank positions in phase 3, add **hard constraints** that
each virtual's y must be outside any non-member cluster's bbox at
its rank.

- Implementation: walk each virtual's rank, compute the "forbidden
  y intervals" from non-member clusters that intersect the
  virtual's cluster chain, and add aux_edges that push the virtual
  out of those intervals.
- Scope: ~80-120 lines in ``position.py`` (new aux_edge type:
  "cluster keep-out for virtuals").
- Forward-compat: ~60% of the code transfers to channel routing
  work (specifically the "which clusters does this edge's rank
  pass through" computation).

Deferred until the channel routing in ``splines.py`` is complete
and we understand what residual layout issues remain.

## TODO: Font Metrics Refinement

The mincross port.order computation uses Times-Roman AFM character
width tables (gvpy/engines/font_metrics.py) for record field sizing.
These are the standard PostScript metrics but may differ from the
actual font engine (GDI+, Cairo) used by the C reference.

Port.order values (C vs Python, c4118 label):
- In0: C=42, Python=99 (should match for mincross convergence)
- Out0: C=213, Python=239

To improve:
1. Try Times New Roman metrics (Windows GDI+ uses TNR, not Times-Roman)
2. Consider integrating with the rendering font engine for exact metrics
3. The SVG renderer's _parse_record_label should be replaced by
   Node.record_fields (ANTLR4 RecordParser) — ~130 lines to remove
4. _record_size in dot_layout.py still imports svg_renderer._parse_record_label

## Current Test Coverage Summary

| Test File | Tests | Status |
|---|---|---|
| `tests/test_dot_layout.py` | 133 | All pass |
| `tests/test_dot_parser.py` | 44 | All pass |
| `tests/test_svg_renderer.py` | 18 | All pass |
| Other refactored tests | 95+ | 23 fail (pre-existing hide/expose bugs) |
| 127 test files validation | 122 pass, 6 parse errors | 0 layout failures |
