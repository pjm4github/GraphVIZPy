# TODO — GraphvizPy

Consolidated roadmap. Supersedes per-topic TODO files (`TODO_core_refactor.md`,
`TODO_dot_layout.md`, `TODO_dot_splines_port.md`, `TODO_layout_engines.md`,
`TODO_main_gui.md`, `TODO_pictosync_merge.md`) — kept on disk for history only.

Authoritative reference for C-side comparison:
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\lib\dotgen\` +
`lib\common\splines.c`.

Last updated: 2026-04-19 (post-B4 audit).

---

## 1. Python ↔ C Divergences

Known functional gaps in the live `gvpy/engines/layout/dot/` pipeline versus C
dotgen. Each row is a point where Python produces different routing / layout
than C would. Ordered by impact on the audit corpus.

| # | Divergence | C analogue | Python status | Impact |
|---|---|---|---|---|
| D1 | `splines=ortho` is a naïve Z-router | `lib/ortho/*` (~3000 lines) | `splines.ortho_route` — Z with compass-aware mid_y clamp (B2) | 2620.dot: 66 crossings |
| D2 | `make_flat_adj_edges` ports-case compromises: no subgraph clone + re-layout | `dotsplines.c:make_flat_adj_edges` → full recursive `dot_splines_` | `flat_edge.make_flat_adj_edges` partial (E+.2-B); record-field ports emit `UnsupportedPortRoutingWarning` | narrow (record-port same-rank only) |
| D3 | No `smode` straight-segment dispatch inside `make_regular_edge` — chains fit a single spline | `dotsplines.c:make_regular_edge` lines 1809-1869 | `regular_edge.straight_len` + `straight_path` + `recover_slack` ported as utilities, not yet wired | cosmetic on long chains |
| D4 | Cluster-clipping gives sub-pixel corner-grazing on bezier interior | `maximal_bbox` margin OK; C uses same geometry but bezier fit differs | `clip.bezier_point` + `regular_edge.make_regular_edge` | aa1332=9, 1332=9, 1472=25, 2796=32, 1213-1=4, 1213-2=3, 2239=2, 2521_1=1 (86 total) |
| D5 | Mincross puts multi-rank edges on *opposite* sides of a cluster where C would put them same-side | `lib/dotgen/mincross.c` — median / cross-rank ordering | `mincross.py` — TODO_dot_layout.md item (c) | contributes to D4 on aa1332/1332 specifically |
| D6 | Phase 3 position doesn't add hard keep-out constraints for virtuals vs. non-member cluster y-bands | `position.c` NS solver | `position.py` — TODO_dot_layout.md item (d); ~60% overlaps with deferred channel routing | compounds D4 |
| D7 | Font metrics are Times-Roman AFM, not the rendering font | Depends on `gvrender_*` plugin | `font_metrics.py` — gives wrong `port.order` widths on records (C=42, Python=99 on the 1332 sample) | record-node mincross divergence only |
| D8 | Recursive layout pipeline can't be invoked on a subgraph clone | Needed for `make_flat_adj_edges`, and for any future nested-layout port | `DotGraphInfo.__init__` assumes root-graph state — `_spline_info` etc. | blocks E+.2-A |
| D9 | `apply_rankdir` semantics — LR coords now un/re-swapped around phase 4 only | C rotates at `postproc`, after splines | `splines._phase4_to_tb` / `_phase4_from_tb` (B1) | **resolved** — kept as a reference; was the single biggest regression |

Three tool-side caveats the audit tool should report but currently absorbs:
- `tools/count_cluster_crossings.py` uses `le.route.spline_type` to pick bezier
  vs. polyline sampling (fixed 2026-04-19). Verify after any EdgeRoute schema
  change.
- `tools/visual_audit.py` infers C-side bezier-vs-polyline from `"C"` command
  letters. A Graphviz version change that emits different path syntax would
  silently re-introduce phantom crossings.
- Timeout budget is 60s per graph per side; 14 graphs in the corpus fail this.
  Separate problem class from divergences.

---

## 2. Priority 1 — Dot Engine Quality

### Active (ordered by payoff)

1. **Cluster corner-grazing** (D4). The 86 remaining bezier crossings across 8
   graphs are all "anchor just outside cluster wall, bezier curve bulges a few
   points in." Needs either (a) bigger safety margin in `maximal_bbox`'s
   cluster clip, or (b) sample-validate-and-reshape on each bezier. Each case
   seems to need individual analysis — not a single fix.
2. **`smode` dispatch (D+.2b)**. Wire the already-ported `straight_len` /
   `straight_path` / `recover_slack` helpers into `make_regular_edge`'s
   virtual-chain loop. Requires restructuring the loop to emit multiple path
   segments per edge. ~cosmetic win on long vertical chains.
3. **Layout-level fixes (c) + (d)** from `TODO_dot_layout.md`. Defer until
   after the channel-routing residuals above. Item (c) is a multi-phase
   instrumentation job on mincross; item (d) is ~80-120 lines in
   `position.py`.
4. **Font metrics refinement**. Try Times New Roman metrics, replace
   `svg_renderer._parse_record_label` with `Node.record_fields` (ANTLR4).
   Fixes record-port mincross order divergence (D7).

### Completed this session (for the record)

- F+.1 spline geometry primitives (`label_place.py`): `end_points`,
  `getsplinepoints`, `polyline_midpoint`, `edge_midpoint`.
- F+.2 label placement: `place_portlabel`, `make_port_labels`,
  `add_edge_labels`, `place_vnlabel`.
- D+.1 `top_bound` / `bot_bound` neighbor check wired into
  `completeregularpath`.
- E+.1 labeled-adjacent flat stacking (`make_simple_flat_labels`).
- D+.2 straight-segment helpers + `recover_slack` wired into
  `make_regular_edge`.
- E+.2-B compass-port aware adjacent-flat routing + `UnsupportedPortRoutingWarning`.
- B1 phase-4 TB-frame wrapper — the single biggest layout-quality improvement.
- B2 ortho cluster-avoidance (compass-port mid_y clamp) + audit polyline
  mis-sampling fix.
- B4 delete orphaned 1600-line channel routing code.
- Fix 1902.dot RecursionError (duplicate-named nested clusters).
- Fix rank_box cache poisoning (shared mutable Box).

---

## 3. Priority 2 — Splines Port Completion

All **Phase A-G** ports complete as of 2026-04-16. The deferred work is the
`D+` / `E+` / `F+` buckets — optimizations that were spun out to let the base
port ship. Current status:

| Bucket | Status | Notes |
|---|---|---|
| D+.1 top/bot_bound | **done** 2026-04-18 | |
| D+.2 straight helpers + recover_slack | **done** 2026-04-18 | `smode` dispatch still deferred (D+.2b above) |
| E+.1 flat label stacking | **done** 2026-04-18 | |
| E+.2-B compass port flat routing | **done** 2026-04-18 | Record-field ports still emit warning (E+.2-A defers full clone) |
| F+.1 geometry primitives | **done** 2026-04-18 | |
| F+.2 label positioning | **done** 2026-04-18 | |

Deferred:

- **D+.2b** — wire `smode` dispatch inside `make_regular_edge` loop.
- **E+.2-A** — full recursive clone + re-layout + transform-back for
  `make_flat_adj_edges`. Requires `DotGraphInfo` to support sub-graph
  instantiation (see D8).

Full port-map table is in `TODO_dot_splines_port.md` — kept as archival
history; all rows flagged `done` or mapped to the deferred buckets above.

---

## 4. Core Refactor (mostly done)

All architectural work from the original `TODO_core_refactor.md` landed
2026-04-12:

- **Done**: `graph.py` split (19 module-helpers → per-concern files),
  `GraphView` base + `DotGraphInfo` rename, phase extraction into
  `position.py` / `mincross.py` / `splines.py` / `rank.py` / `ns_solver.py` /
  `cluster.py` / `dotinit.py`, `SimulationView` skeleton (7 modules, 9 tests).
- **Deferred**: `PictoGraphInfo` — planned as Phase 1 of the pictosync merge.

### 4.1 `gvpy.engines.layout.common` package (done 2026-04-19)

Mirrors Graphviz's `lib/common/` library — engine-agnostic utilities every
layout binary links against (shapes, splines, text layout, geometry).  Five
commits (`2e7cfd1` → `73c569c`), each 836 tests pass, no behavioral change:

**Audit findings:**
- No cross-engine imports exist today (`circo`, `fdp`, `neato`, `osage`,
  `patchwork`, `sfdp`, `twopi` each import only from `base.py` + core).
  Nothing broken; refactor is organizational, not corrective.
- Already-shared code lives in three files at `gvpy/engines/layout/`:
  `base.py` (734 lines — `LayoutEngine` with post-processing, component
  packing, label-collision placement, shape boundary clipping),
  `layout_features.py` (307 lines — per-engine attribute support matrix),
  `font_metrics.py` (113 lines — Times-Roman AFM + tkinter fallback).
- Dot-specific but engine-agnostic: `dot/pathplan/pathgeom.py` (Ppoint /
  Ppoly / Ppolyline), `dot/ns_solver.py` (NumPy network simplex),
  `dot/splines.py` pure-geometry helpers (`to_bezier`, `make_polyline`).

**Target tree:**

```
gvpy/engines/layout/common/
├── __init__.py
├── geom.py         # Ppoint, Ppoly, Ppolyline, clip_to_boundary,
│                   #   bbox helpers  (mirrors lib/common/geomprocs.h)
├── text.py         # font_metrics + label sizing + collision-aware
│                   #   positioning  (mirrors lib/common/labels.c)
├── shapes.py       # shape boundary intersection, shape area
│                   #   (mirrors lib/common/shapes.c)
├── splines.py      # polyline_to_bezier, make_polyline — stateless
│                   #   geometry only  (mirrors lib/common/splines.c)
├── ns_solver.py    # re-export dot/ns_solver.py — usable by any engine
├── layout_node.py  # optional LayoutNodeBase dataclass with the common
│                   #   fields (name, node, x, y, width, height, pinned)
└── postproc.py     # normalize / rotate / center / find_components /
                    #   pack_components_lr  (mirrors lib/common/postproc.c)
```

**Shipped modules:**

| Module | Contents | C counterpart |
|---|---|---|
| `common/geom.py` | `Ppoint`, `Pvector`, `Ppoly`, `Ppolyline`, `Pedge` | `lib/pathplan/pathgeom.h` |
| `common/postproc.py` | `apply_normalize`, `apply_rotation`, `apply_center`, `find_components`, `pack_components_lr` | `lib/common/postproc.c` |
| `common/text.py` | Times-Roman AFM + tkinter metrics, `estimate_label_size`, `overlap_area`, `compute_label_positions` | `lib/common/labels.c` |
| `common/splines.py` | `to_bezier` (Schneider recursive fit), `make_polyline` | `lib/common/splines.c` + `lib/pathplan/util.c @ 44` |
| `common/ns_solver.py` | Re-exports `NetworkSimplex` from `dot/ns_solver.py` | `lib/common/ns.c @ 623` |

**Back-compat preserved everywhere.**  `dot/pathplan/pathgeom.py`,
`dot/pathplan/util.py`, `dot/splines.py`'s `to_bezier`, and the standalone
`gvpy/engines/layout/font_metrics.py` all became re-exports so every
existing call site continues to resolve.

**Deferred (optional):**
- `LayoutNodeBase` dataclass with the six universal fields.  Each engine's
  `LayoutNode` already defines these plus engine-specific extensions;
  extracting would force a base-class-bloat tradeoff.  Defer until a
  second engine needs the same extension point.

### 4.2 Second common/ pass: `lib/common/` citations (planned)

The first pass pulled obviously-shared code (post-processing, font metrics,
Schneider fit).  A broader audit of `See: /lib/common/` citations in
`gvpy/engines/layout/dot/` identified **15 more engine-agnostic candidates**
(77 total `/lib/common/` references across dot; 38 stay because they read
`LayoutEdge` / `LayoutNode` / `layout._*` state).

Proposed five commits, same cadence as §4.1:

| # | Target module | Candidates | Source file(s) | Risk |
|---|---|---|---|---|
| 1 | `common/shapes.py` (NEW) | `ellipse_inside`, `box_inside`, `make_inside_fn`, `self_loop_points`, `Box` dataclass | `dot/clip.py`, `dot/splines.py`, `dot/path.py` | low |
| 2 | `common/clip.py` (NEW) | `bezier_clip`, `shape_clip0`, `shape_clip`, `clip_and_install`, `conc_slope` | `dot/clip.py` | **medium** (critical path) |
| 3 | `common/splines.py` (extend) | `bezier_point` (de Casteljau), pure-geometry core of `polyline_midpoint` | `dot/clip.py`, `dot/label_place.py` | low |
| 4 | `common/labels.py` (NEW) | `_late_double` attribute-parse helper | `dot/label_place.py` | low |
| 5 | `common/geom.py` (extend) | `_approx_eq`, `overlap` (interval overlap) | `dot/clip.py`, `dot/routespl.py` | low |

**Must stay in `dot/`** (sample — reason in parens):
- `end_points`, `getsplinepoints`, `place_portlabel`, `place_vnlabel`, `make_port_labels`, `add_edge_labels` (read `le.route` / `le.points` / `le.edge.attributes`)
- `edge_start_point`, `edge_end_point`, `record_port_point`, `port_point` (read `le.tailport` / `le.headport` / node shape)
- `_node_out_edges`, `_node_in_edges`, `_clust` (walk `layout.ledges` / `layout._chain_edges` / `layout._clusters`)
- `beginpath`, `endpath` (mutate `PathEnd` + node-geometry workspace)
- `routesplines_`, `routesplines`, `routepolylines`, `limit_boxes`, `checkpath` (routing pipeline state)
- All `self_edge.py` / `straight_edge.py` functions (operate on `LayoutEdge` + `layout` structure)

**SPLIT note**: `edge_midpoint` stays in `dot/label_place.py` because it calls `end_points`; its pure-geometry core `polyline_midpoint` moves to `common/splines.py` and is re-exported from `label_place.py` for back-compat.

**Back-compat**: every moved symbol will leave a one-line re-export in its
current module so no existing import breaks.

---

## 5. Other Layout Engines

### Live
- **dot** (hierarchical) — 836 tests passing.
- **circo** (circular) — 25 tests passing.

### Stubs only (priority order)
1. **neato** — stress majorization / Kamada-Kawai. Highest priority — widely
   used, well-documented.
2. **fdp** — Fruchterman-Reingold force-directed with cluster support.
3. **twopi** — radial BFS; straightforward; good for trees / DAGs.
4. **sfdp** — multiscale force-directed, Barnes-Hut for 10K+ nodes.
5. **osage** — cluster packing.
6. **patchwork** — squarified treemap.
7. **mingle** — post-processing edge bundling (not a layout engine).

---

## 6. MainGraphvisPy GUI

Five-phase plan, none started:

1. **Backing model integration** — wire `cgraph.Graph` under the GUI scene,
   drive node/edge creation through it, sync attributes.
2. **DOT save/load** — replace custom JSON with DOT round-trip through
   cgraph.
3. **Layout integration** — "Auto Layout" button running
   `DotLayout(graph).layout()`, update `NodeItem`/`EdgeItem` positions and
   routes.
4. **Attribute sync** — node/edge/graph attributes through cgraph;
   subgraph/cluster UI support.
5. **Pictosync alignment** — SVGNodeRegistry, `attribute_schema.json`, snake_case.

---

## 7. Pictosync Merge

Nine-phase plan:

| Phase | Description | Status |
|---|---|---|
| 1 | graphvizpy as pip dep in pictosync venv | pending |
| 2 | GraphAdapter (canvas ↔ cgraph bidirectional sync) | pending |
| 3 | QTreeView hierarchy browser + folder-per-subgraph persistence | pending |
| 4 | Layout menu entries (dot / neato / circo / twopi) | blocked on neato+twopi ports |
| 5 | DOT import/export, round-trip validation | blocked on Phase 2 |
| 6 | `SimNode(Node)` subclass with 4-phase execution | new work |
| 7 | `DiscreteTimeSimulator` engine on Graph of SimNodes | depends on Phase 6 |
| 8 | MNAM matrix builder from cgraph topology | depends on Phase 7 |
| 9 | MainGraphvisPy cgraph integration | depends on Section 6 above |

Order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Phases 1–5 unblock pictosync's
diagram UI; 6–9 add simulation.

---

## 8. Diagnostics & Tooling

- `tools/visual_audit.py` — corpus-wide Python vs. C crossings audit. Reruns
  in ~5–8 min. `audit_report.md` is the baseline snapshot.
- `tools/count_cluster_crossings.py` — per-graph Python counter.
  `use_channel` kwarg is a no-op (kept for back-compat).
- 14 Python timeouts + 1 RecursionError known — see the audit report's
  failure table. Separate from crossings; worth a dedicated triage session.

---

## 9. Index of the old per-topic TODOs

These files are kept for archival reference. **Prefer this consolidated
document** for new work:

- `TODO_core_refactor.md` — history of the 2026-04-12 refactor (now all done).
- `TODO_dot_layout.md` — deferred layout-level fixes (c), (d) + font-metrics
  notes. Summarized in §1 and §2 above.
- `TODO_dot_splines_port.md` — large historical log of the A-G splines port
  (1145 lines). Everything marked `done` or deferred; see §3 above.
- `TODO_layout_engines.md` — listing of layout-engine stubs. See §5.
- `TODO_main_gui.md` — five-phase GUI plan. See §6.
- `TODO_pictosync_merge.md` — nine-phase merge plan. See §7.
