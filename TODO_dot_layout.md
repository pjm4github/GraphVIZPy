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

## Current Test Coverage Summary

| Test File | Tests | Status |
|---|---|---|
| `tests/test_dot_layout.py` | 133 | All pass |
| `tests/test_dot_parser.py` | 44 | All pass |
| `tests/test_svg_renderer.py` | 18 | All pass |
| Other refactored tests | 95+ | 23 fail (pre-existing hide/expose bugs) |
| 127 test files validation | 122 pass, 6 parse errors | 0 layout failures |
