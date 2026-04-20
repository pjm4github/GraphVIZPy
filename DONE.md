# DONE — GraphvizPy work log

Archive of shipped work pulled out of `TODO.md` to keep the live roadmap
short.  Ordered newest → oldest.

---

## 2026-04-19 — Directory restructure to mirror Graphviz

- **`dot/pathplan/` → `pathplan/`**.  Moved to the layout root because
  pathplan is a shared library in Graphviz (`lib/pathplan/`), not a
  subpackage of dotgen.  All 12 modules git-tracked as renames; callers in
  `dot/` and `tests/test_phase4_coverage.py` updated.  836 tests pass.
- **`dot/splines.py` → `dot/dotsplines.py`**.  Filename now matches
  `lib/dotgen/dotsplines.c`; `common.splines` keeps the shared-code
  namespace.  ~60 call sites in `dot_layout.py` + stragglers in
  `flat_edge`, `label_place`, `rank`, `regular_edge`,
  `tests/test_rank_box_cache.py`, `tools/{audit_c_refs,extract_splines}.py`
  rewritten.

## 2026-04-19 — Second `common/` pass (§4.2)

Five commits (`84d0ff5` → `83d2bd1`), 836 tests pass at each step, zero
behavioral change.

| # | Commit  | Target module               | Moved |
|---|---|---|---|
| 1 | `84d0ff5` | `common/shapes.py` (new) | `Box`, `InsideFn`, `ellipse_inside`, `box_inside`, `make_inside_fn`, `self_loop_points` |
| 2 | `e3d0d5b` | `common/clip.py` (new), `common/splines.py` | `bezier_clip`, `shape_clip0`, `shape_clip`, `clip_and_install`, `conc_slope`, `bezier_point` |
| 3 | `4570af4` | `common/splines.py` | `polyline_midpoint_raw` (pure core split out of `label_place.polyline_midpoint`) |
| 4 | `fc12807` | `common/labels.py` (new) | `late_double` |
| 5 | `83d2bd1` | `common/geom.py` | `approx_eq`, `interval_overlap`, `MILLIPOINT` |

Every moved symbol left a one-line re-export or legacy alias at its
original location.  Coupled code (`end_points`, `place_portlabel`,
`port_point`, `_node_out_edges`, `beginpath`/`endpath`, `routesplines_`,
`self_edge.py`, `straight_edge.py` etc.) stayed in `dot/`.

## 2026-04-19 — First `common/` pass (§4.1)

Five commits (`40d51b6` → `73c569c`), 836 tests pass, no behavioral
change.  Modules shipped:

| Module | Contents | C counterpart |
|---|---|---|
| `common/geom.py` | `Ppoint`, `Pvector`, `Ppoly`, `Ppolyline`, `Pedge` | `lib/pathplan/pathgeom.h` |
| `common/postproc.py` | `apply_normalize`, `apply_rotation`, `apply_center`, `find_components`, `pack_components_lr` | `lib/common/postproc.c` |
| `common/text.py` | Times-Roman AFM + tkinter metrics, `estimate_label_size`, `overlap_area`, `compute_label_positions` | `lib/common/labels.c` |
| `common/splines.py` | `to_bezier` (Schneider fit), `make_polyline` | `lib/common/splines.c`, `lib/pathplan/util.c @ 44` |
| `common/ns_solver.py` | Re-export `NetworkSimplex` | `lib/common/ns.c @ 623` |

Back-compat preserved via re-exports in `dot/pathplan/pathgeom.py`,
`dot/pathplan/util.py`, `dot/splines.py` (`to_bezier`), and the
standalone `font_metrics.py`.

## 2026-04-19 — Repo hygiene

- Normalized 264 `C analogue:` docstrings → canonical `See:
  /lib/path/file.c @ NNN` form (commit `2e7cfd1`).  4 unresolved
  references (`cmpnd.c` and `compact_rankset`) rewritten as "No direct C
  analogue" with context.
- Removed six legacy per-topic TODO files (`TODO_dot_layout.md`,
  `TODO_dot_splines_port.md`, etc.); single `TODO.md` is now the source
  of truth.
- `.gitignore` updated to drop scratch artifacts
  (`trace_*.txt`, `Snippet.py`, `test_run*.md`, coverage, `test_data/*.svg`).
- Added `Docs/dotgen_components.{png,puml,svg}` architecture diagram.
- Seven test-data `.dot` inputs added (record-port + label-placement
  fixtures + `1332_ref.dot` regression target).

## 2026-04-18 → 2026-04-19 — Dot engine quality session

Thirteen commits ported deferred splines work and caught two real bugs.

**Shipped (alphabetical):**
- **B1** `splines._phase4_to_tb` / `_phase4_from_tb` — the single biggest
  layout-quality improvement.  Phase 4 now runs in a pure-TB frame
  regardless of output rankdir, matching C's `GD_flip` idiom.  Rescued
  edge routing on every LR graph in the corpus (e.g. `aa1332` 109 → 117
  routed, `2239` 41 → 84 routed, `2796` 69 → 193 routed).
- **B2** ortho cluster-avoidance.  `ortho_route` picks a mid_y that
  clears non-member cluster bboxes on the horizontal leg.  Plus fixed
  `count_cluster_crossings` / `visual_audit` to distinguish polyline
  from bezier output (was phantom-counting 19 crossings on 2620).
- **B4** deleted orphaned channel-routing code.  1600 lines of
  `channel_route_edge`, `_find_gap_obstacles`, `_bridge_points_for_obstacle`
  etc. — the `_use_channel_routing=True` flag was a no-op, all the
  cluster-aware work had migrated into `make_regular_edge` via
  `maximal_bbox`.  Cleanup only; crossings unchanged.
- **D+.1** `top_bound` / `bot_bound` neighbor check wired into
  `completeregularpath`.
- **D+.2** straight-segment helpers (`straight_len`, `straight_path`,
  `resize_vn`) + `recover_slack` wired into `make_regular_edge`.
- **E+.1** `make_simple_flat_labels` — alternating up/down stacking for
  labeled adjacent flat edges.  Port includes `edgelblcmpfn` sort
  comparator.
- **E+.2-B** compass-port aware adjacent-flat routing.  Non-compass /
  record-field ports emit `UnsupportedPortRoutingWarning` pointing at
  the still-deferred E+.2-A clone-and-rerun.
- **F+.1** spline geometry primitives in `label_place.py`:
  `end_points`, `getsplinepoints`, `polyline_midpoint`, `edge_midpoint`.
- **F+.2** label positioning: `place_portlabel`, `make_port_labels`,
  `add_edge_labels`, `place_vnlabel`.  Replaces the earlier
  `compute_label_pos` heuristic.

**Bugs fixed:**
- `1902.dot` `RecursionError` — duplicate-named nested clusters created a
  self-parent edge in `tree_parent`.  Guarded `_walk_tree` +
  `_desc_nodes` with cycle detection.
- `rank_box` cache poisoning — `routesplines_` mutated cached `Box`
  instances to `±∞`, poisoning every later fetch.  `rank_box` now
  returns a fresh copy.  Impact: `1472.dot` routed edges 118 → 145,
  several graphs fully routed.

**Tool:**
- `tools/visual_audit.py` — corpus-wide Python vs. C crossings audit.
  Runs 190 graphs in ~5–8 min, produces `audit_report.md`.  Session
  total-crossings went 171 → 151 with the fixes above.

## 2026-04-16 — Splines port (Phases A-G) complete

Every function in `lib/dotgen/dotsplines.c` + the portions of
`lib/common/splines.c` it depends on has a Python port.  Deferred
optimizations (D+/E+/F+ buckets) tracked separately — the session above
closed most of those.

## 2026-04-12 — Core refactor

- **`graph.py` split**: 19 module-helpers from `gvpy/core/graph.py` moved
  to per-concern modules (`_graph_apply.py`, `_graph_cmpnd.py`,
  `_graph_edges.py`, `_graph_id.py`, `_graph_traversal.py`) matching
  Graphviz's `lib/cgraph/` factoring.  `graph.py` went 1680 → 1329 lines.
- **`GraphView` base + `DotGraphInfo` rename**: abstract projection-of-a-
  graph type; `DotLayout` became `DotGraphInfo(LayoutView)` with a
  backward-compat alias.
- **Phase extraction**: `dot_layout.py` went 6739 → 1777 lines over the
  session (-74%).  Methods moved to `position.py` (11), `mincross.py`
  (18), `splines.py` (23), `rank.py` (11), `ns_solver.py` (448-line
  `_NetworkSimplex` class), `cluster.py` (7), `dotinit.py` (5).
- **NS constraint bug fix** (aa1332 overlaps) — removed per-rank stable
  sort by innermost cluster name + disabled sibling-separation edges.
  0 overlaps, 3 residual small NS violations, 0 cycles.
- **`SimulationView` skeleton**: 7 modules (~1200 lines) with
  event-driven + CBD primitives.  9 smoke tests.
