# TODO — GraphvizPy

Pending work.  For shipped work see `DONE.md`.

Authoritative reference for C-side comparison:
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\lib\`.

Last updated: 2026-04-19.

---

## 1. Python ↔ C Divergences

Known functional gaps in the live `gvpy/engines/layout/dot/` pipeline versus
C dotgen.  Reference table — not a priority list (see §2 for priority).

| # | Divergence | Python status | Impact |
|---|---|---|---|
| D1 | ~~`splines=ortho` uses a naïve Z-router, not `lib/ortho/*`~~ | ✅ resolved 2026-04-20 — full `lib/ortho/` port lives at `gvpy/engines/layout/ortho/` with cluster-avoidance layer.  Legacy Z-router reachable via `GVPY_ORTHO_LEGACY=1` for two release cycles | 2620.dot: **3** crossings (was 66) |
| D2 | `make_flat_adj_edges` lacks subgraph clone + re-layout | `flat_edge.make_flat_adj_edges` partial (E+.2-B); record-field ports warn | narrow (record-port same-rank only) |
| D3 | No `smode` straight-segment dispatch inside `make_regular_edge` | helpers ported, not yet wired | cosmetic on long chains |
| D4 | Cluster-clipping gives sub-pixel corner-grazing on bezier interior; also control-point-deep-inside cases where tail/head straddle a non-member cluster on adjacent ranks | `make_regular_edge` + `cluster_detour.reshape_around_clusters` (ships 2026-04-20: post-hoc detour reshape with 8-pt rounded corners — arc radius > typical 4.5-pt node rounded-rect radius).  Partial cover — residuals are D5/D6 positioning symptoms | was 86, now 40: aa1332=1, 1332=3, 1472=12, 2796=18, 1213-1=3, 1213-2=2, 2239=1, 2521_1=0 |
| D5 | Mincross places multi-rank edges on opposite sides of a cluster where C keeps them same-side | `mincross.py` — needs instrumentation pass | contributes to D4 on aa1332 / 1332 |
| D6 | Phase 3 position lacks hard keep-out constraints for virtuals vs. non-member cluster y-bands | `position.py` — ~80-120 lines | compounds D4 |
| D7 | Font metrics are Times-Roman AFM, not the rendering font | `font_metrics.py` — gives wrong `port.order` widths on records (C=42 vs Python=99 on 1332) | record-node mincross divergence only |
| D8 | Recursive layout pipeline can't be invoked on a subgraph clone | `DotGraphInfo.__init__` assumes root-graph state | blocks E+.2-A |

**Tool-side caveats the audit currently absorbs:**
- `count_cluster_crossings.py` uses `le.route.spline_type` to pick
  bezier vs. polyline sampling; verify after any `EdgeRoute` schema
  change.
- `visual_audit.py` infers C-side bezier-vs-polyline from `"C"` command
  letters; a Graphviz output-format change could silently re-introduce
  phantom crossings.
- Timeout budget is 60 s per graph per side; 14 graphs in the corpus
  fail this — separate problem class from divergences.

---

## 2. Priority 1 — Dot Engine Quality

Ordered by payoff.  Each item is independently shippable.

1. **Cluster corner-grazing** (D4).  Was 86, now 40 after post-hoc
   detour reshape shipped 2026-04-20 (`cluster_detour.py`).  Detour
   polylines render with 8-pt rounded corners (arc radius >
   typical 4.5-pt rounded-rect node radius), detour margin 20 pt to
   guarantee ≥ 4-pt clearance between the arc and the cluster wall.
   Residuals split between (a) anchor-inside-non-member-cluster
   cases — the endpoint node is visually inside a cluster it doesn't
   belong to (pure D5/D6 positioning issue; not fixable at the
   splines layer) and (b) nested-overlap cases where no detour side
   clears all other non-member clusters near the edge.  The reshape
   handles the straight-cubic-through-interior case (2521_1 style)
   cleanly; closing the rest means tackling D5/D6 directly.
2. **`smode` dispatch** (D+.2b).  Wire the ported `straight_len` /
   `straight_path` / `recover_slack` helpers into `make_regular_edge`'s
   virtual-chain loop.  Requires restructuring to emit multiple path
   segments per edge.  Cosmetic win on long vertical chains.
3. **Layout-level fixes** (D5, D6).  Item D5 is a multi-phase
   instrumentation job on mincross; D6 is ~80–120 lines in
   `position.py`.  Defer until after D4.
4. **Font metrics refinement** (D7).  Try Times New Roman metrics,
   replace `svg_renderer._parse_record_label` with `Node.record_fields`
   (ANTLR4).  Fixes record-port mincross order divergence.

---

## 3. Priority 2 — Splines Port Deferred Items

| Bucket | Status | Notes |
|---|---|---|
| D+.2b `smode` dispatch | deferred | See §2.2 |
| E+.2-A full recursive clone + re-layout | deferred | Requires `DotGraphInfo` to support sub-graph instantiation (blocks on D8) |

---

## 4. Core Refactor

**Deferred:** `PictoGraphInfo` — planned as Phase 1 of the pictosync merge
(see §7).

---

## 5. Other Layout Engines — Stubs

Priority order:

1. **ortho** — full port of `lib/ortho/*` to replace the naïve Z-router
   (D1).  **Next scheduled work** — see §5a below for the kickoff brief.
2. **neato** — stress majorization / Kamada-Kawai.  Widely used,
   well-documented.
3. **fdp** — Fruchterman-Reingold with cluster support.
4. **twopi** — radial BFS; straightforward; good for trees / DAGs.
5. **sfdp** — multiscale force-directed, Barnes-Hut for 10K+ nodes.
6. **osage** — cluster packing.
7. **patchwork** — squarified treemap.
8. **mingle** — post-processing edge bundling (not a layout engine).

Live today: **dot** (836 tests) and **circo** (25 tests).

---

## 5a. Ortho port kickoff brief

**Goal:** replace the naïve Z-router with a proper orthogonal channel
router that respects non-member cluster bboxes.  Target graph: **2620.dot
(66 crossings)** — the remaining outlier in the audit corpus.

**C source:** `C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\lib\ortho\`
(~3000 lines).  Entry point is `orthoEdges()` in `ortho.c`.  Supporting
modules: `maze.c` (obstacle grid), `partition.c` (rectangle decomposition),
`sgraph.c` (sparse-graph shortest path), `trapezoid.c`, `rawgraph.c`.

**Current Python ortho code (all placeholder):**
- `gvpy/engines/layout/dot/dotsplines.py::ortho_route(layout, le, tail, head)` —
  naïve Z with `_ortho_safe_midy` cluster-avoidance clamp (commit `0b7c251`,
  B2).  Compass-aware, but doesn't do channel routing.  Returns 4-point
  polyline.
- `_ortho_safe_midy`, `_ortho_member_clusters`, `_ortho_any_obstacle_at` —
  supporting helpers in `dotsplines.py`, called only from `ortho_route`.
- Dispatch sites: `dotsplines.phase4_routing_body` at the two
  `elif layout.splines == "ortho": le.points = layout._ortho_route(…)`
  branches — once in the real-edge loop, once in the chain-edge loop.

**Architecture options (pick one at kickoff):**

1. **Top-down port of `lib/ortho/`.**  Mirror the C tree — new
   `gvpy/engines/layout/ortho/` with `maze.py`, `ortho.py`, `partition.py`,
   `sgraph.py`, `trapezoid.py`, `rawgraph.py`.  High fidelity, ~3000
   lines, ~1-2 weeks.  Best if we want to match dot.exe byte-for-byte on
   ortho output.
2. **Incremental extension of the Z-router.**  Grow `dotsplines.ortho_route`
   into a proper channel router without cloning C's structure.  Shorter,
   Python-idiomatic, may diverge from dot.exe output.  Iterate against
   `tools/count_cluster_crossings.py test_data/2620.dot`.
3. **Separate engine shell.**  New `gvpy/engines/layout/ortho/` subpackage
   with its own entry point, but implement incrementally rather than
   top-down.  Splits the difference — clean separation without
   committing to a faithful port.

**Available building blocks in `common/` (shipped 2026-04-19):**
- `common/geom.py` — `Ppoint`, `Pvector`, `Ppoly`, `Ppolyline`, `Pedge`,
  `approx_eq`, `interval_overlap`, `MILLIPOINT`.
- `common/shapes.py` — `Box`, `InsideFn`, `ellipse_inside`, `box_inside`,
  `make_inside_fn`, `self_loop_points`.
- `common/clip.py` — `bezier_clip`, `shape_clip`, `clip_and_install`,
  `conc_slope`.
- `common/splines.py` — `to_bezier`, `make_polyline`, `bezier_point`,
  `polyline_midpoint_raw`.
- `common/text.py` — label sizing and collision-aware placement.
- `common/postproc.py` — normalize / rotate / center / component packing.
- `pathplan/` (moved to layout root 2026-04-19) — shortest-path,
  triangulation, visibility graph, Schneider spline fit.  Usable
  directly by ortho for channel routing.

**Known dispatch integration:**
- Phase 4 runs inside a TB-frame wrapper (`_phase4_to_tb` /
  `_phase4_from_tb`) — if the ortho router produces output in TB frame,
  the wrapper will rotate it to the output rankdir automatically.  This
  is why the current B2 compass-port fix works for LR graphs.

**Success criterion:**
- `tools/count_cluster_crossings.py test_data/2620.dot` goes from 66 to
  a small single-digit count (or zero).
- Full suite 836 tests still pass.
- Consider rerunning `tools/visual_audit.py` for a corpus-wide check
  afterwards; other 17 ortho graphs in the corpus currently show 0
  crossings but may have shifted.

**Starting command for the next session:** read `DONE.md`'s 2026-04-19
entry for the B2 fix + audit tool context, then `grep -n "ortho_route\|
_ortho_safe_midy" gvpy/engines/layout/dot/dotsplines.py` to see the
existing code, then pick one of the three architecture options.

**Decision (2026-04-19):** option 1 (top-down port) chosen.  Full
implementation plan lives in [`ORTHO_PORT_PLAN.md`](ORTHO_PORT_PLAN.md)
— see §5b below for status.

---

## 5b. Ortho port — execution tracker

Plan: [`ORTHO_PORT_PLAN.md`](ORTHO_PORT_PLAN.md) (option 1, top-down
port of `lib/ortho/`, ~3930 Python lines, 10–13 days).

| Phase | Module | Status |
|---|---|---|
| 0 | Scaffolding + `structures.py` + stub `ortho_edges` | ✅ done |
| 1 | `rawgraph.py` | ✅ done (18 tests, hand-traced 6-node DAG) |
| 2 | `fpq.py` + `sgraph.py` | ✅ done (18 tests, NetworkX cross-check) |
| 3 | `trapezoid.py` (Seidel) | ✅ done (4 fixtures, byte-match vs C harness) |
| 4 | `partition.py` | ✅ done (4 fixtures, match-vs-C harness) |
| 5 | `maze.py` | ✅ done (12 structural tests; C harness deferred — see notes) |
| 6 | `ortho.py` orchestration | ✅ done (full port; end-to-end runs on all 17 fixtures) |
| 7a | Resilience fixes (None-guards for sparse sgraph, channel-gap tolerance, zero-length angle) | ✅ done |
| 7b | Cluster avoidance (overlap-based cell flagging + per-edge weight bump) | ✅ done (2620: 66 → 3) |
| 7 | Dispatch restructure + `GVPY_ORTHO_V2` flag | ✅ done (Phase 0 already wired it) |
| 8 | Flag flip (V2 default) | ✅ done — opt back out with `GVPY_ORTHO_LEGACY=1` |

Rollout: V2 is now the default (2026-04-20).  Opt back out with
`GVPY_ORTHO_LEGACY=1` to restore the old Z-router — the legacy code
in `dotsplines.ortho_route` will stay in place for two release cycles
while the new router settles, then be removed.

Success criterion **met**: 2620.dot drops from 66 → 3 crossings (well
under the ≤9 bar); the other 16 ortho fixtures stay at 0; all 892
tests pass.

Off-ramp (if Seidel trapezoidation in Phase 3 stalls >3 days): bail to
option 3, keep `rawgraph.py` + `sgraph.py`, wire to `pathplan/shortest.py`
visibility triangulation.

### Phase 7+ — cluster avoidance (shipped 2026-04-20)

Closed the gap noted below.  `ortho.py` computes a ``_ClusterInfo``
once per routing call (cluster bboxes + per-cluster cell-index sets
via overlap test), then for each edge bumps sedge weights by
1,000,000 on cells inside clusters that contain **neither** endpoint,
resetting to ``base_weight`` between edges.  Dijkstra then prefers
paths that skirt non-member clusters.

Corpus result: 2620.dot 66 → 3; other 16 fixtures stay at 0.  The 3
remaining crossings on 2620 are geometrically forced (`digidialog`,
`kalenderservice`, `loginportal` — all originating outside the
clusters they cross, no non-crossing path exists in the current
maze).

The enhancement required one new field (``Sedge.base_weight``) and
~100 lines in ``ortho.py``.  None of this is in C's ortho.c — it's
a GraphvizPy-specific layer on top of the faithful port.

### (historical) Phase 7+ finding — cluster avoidance is a design gap, not a porting bug

The full port runs end-to-end on all 17 ortho fixtures (V2 flag on).
Crossings result across the corpus:

| fixture | legacy | V2 | delta |
|---|---:|---:|---:|
| 14 fixtures | 0 | 0 | — |
| 2183.dot | 0 | 1 | +1 |
| 2620.dot | 66 | 85 | +19 |

The regressions are not porting bugs — they are **faithful to C's
ortho.c**.  The legacy Python Z-router
(`dotsplines.ortho_route` + `_ortho_safe_midy`) has a GraphvizPy-
specific cluster-bbox clamp that bends the route's mid-y to avoid
non-member clusters.  C's `ortho.c` has no equivalent clamp — its
channel router just treats cells as obstacles by width weight, with
no notion of "avoid this non-member cluster".  So a faithful port
naturally loses legacy's dodge behaviour.

To meet the §5b success criterion (`2620 ≤ 9`), Phase 8 needs an
**additive enhancement** beyond the C port:

1. **Cluster-weighted maze** — in `maze._create_sedges`, bump edge
   weights to `BIG` on cells whose bbox sits inside a cluster the
   current edge does not belong to.  Requires the adapter in
   `ortho_edges` to pass `layout.clusters` into `mk_maze` and a
   per-edge membership tag.
2. **Port legacy's clamp into V2** — replicate `_ortho_safe_midy`
   logic after `attachOrthoEdges` to post-process the waypoints.
3. **Hybrid dispatch** — keep V2 for simple graphs, fall back to
   legacy when the route crosses any non-member cluster.

Neither option is a one-line fix, and none of them are in the C
source.  This is the decision point the plan flagged as
"option 3 (incremental Z-router extension)" being complementary to
option 1's strict port.

**Resilience fixes shipped during Phase 7 debug pass:**
- `_find_channel` — relaxed assertion, added intersect + nearest
  fallbacks for channel-gap segments caused by Python↔C partition
  cell-ordering divergence (RNG identity vs `srand48(173)`).
- `_cell_of` / `_convert_sp_to_route` — tolerate `None` cells
  links (C's `assert` compiles out in release; Python was crashing).
- `_is_parallel` — demoted comm_coord assert to return `False`
  (matches C release-build behaviour).
- `_get_angle` — return `-4.0` sentinel on zero-length edges
  (C silently divides by zero).
- `_make_new_monotone_poly` — grow `vnext`/`vpos` beyond C's
  hardcoded `[4]` to avoid buffer-overflow crashes.

With these in place, every fixture runs without error and
892/892 tests still pass.

---

## 6. MainGraphvisPy GUI

Five-phase plan, none started:

1. **Backing model integration** — wire `cgraph.Graph` under the GUI
   scene, drive node/edge creation through it, sync attributes.
2. **DOT save/load** — replace custom JSON with DOT round-trip through
   cgraph.
3. **Layout integration** — "Auto Layout" button running
   `DotLayout(graph).layout()`, update `NodeItem`/`EdgeItem` positions
   and routes.
4. **Attribute sync** — node/edge/graph attributes through cgraph;
   subgraph/cluster UI support.
5. **Pictosync alignment** — `SVGNodeRegistry`, `attribute_schema.json`,
   snake_case.

---

## 7. Pictosync Merge

| Phase | Description | Status |
|---|---|---|
| 1 | graphvizpy as pip dep in pictosync venv | pending |
| 2 | GraphAdapter (canvas ↔ cgraph bidirectional sync) | pending |
| 3 | QTreeView hierarchy browser + folder-per-subgraph persistence | pending |
| 4 | Layout menu entries (dot / neato / circo / twopi) | blocked on neato+twopi ports |
| 5 | DOT import/export, round-trip validation | blocked on Phase 2 |
| 6 | `SimNode(Node)` subclass with 4-phase execution | new work |
| 7 | `DiscreteTimeSimulator` engine on a Graph of SimNodes | depends on Phase 6 |
| 8 | MNAM matrix builder from cgraph topology | depends on Phase 7 |
| 9 | MainGraphvisPy cgraph integration | depends on §6 |

Order 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.  Phases 1–5 unblock pictosync's
diagram UI; 6–9 add simulation.

---

## 8. Diagnostics & Tooling

- `tools/visual_audit.py` — corpus-wide Python vs. C crossings audit.
  Reruns in ~5–8 min.  `audit_report.md` is the baseline snapshot.
- `tools/count_cluster_crossings.py` — per-graph Python counter.
  `use_channel` kwarg is a no-op (kept for back-compat).
- **14 Python timeouts + 1 RecursionError** known in the audit corpus —
  see the failure table in `audit_report.md`.  Separate problem class
  from crossings; worth a dedicated triage session.
