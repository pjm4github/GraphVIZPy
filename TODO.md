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
| D1 | `splines=ortho` uses a naïve Z-router, not `lib/ortho/*` | `dotsplines.ortho_route` — Z with compass-aware mid_y clamp | 2620.dot: 66 crossings |
| D2 | `make_flat_adj_edges` lacks subgraph clone + re-layout | `flat_edge.make_flat_adj_edges` partial (E+.2-B); record-field ports warn | narrow (record-port same-rank only) |
| D3 | No `smode` straight-segment dispatch inside `make_regular_edge` | helpers ported, not yet wired | cosmetic on long chains |
| D4 | Cluster-clipping gives sub-pixel corner-grazing on bezier interior | `make_regular_edge` + `maximal_bbox` margin | aa1332=9, 1332=9, 1472=25, 2796=32, 1213-1=4, 1213-2=3, 2239=2, 2521_1=1 (86 total) |
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

1. **Cluster corner-grazing** (D4).  86 remaining bezier crossings across 8
   graphs — anchors sit just outside cluster walls but the bezier curve
   bulges a few points inside.  Needs either (a) bigger safety margin in
   `maximal_bbox`'s cluster clip, or (b) sample-validate-and-reshape on
   each bezier.  Per-case analysis, not a single fix.
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

1. **neato** — stress majorization / Kamada-Kawai.  Highest priority —
   widely used, well-documented.
2. **fdp** — Fruchterman-Reingold with cluster support.
3. **twopi** — radial BFS; straightforward; good for trees / DAGs.
4. **sfdp** — multiscale force-directed, Barnes-Hut for 10K+ nodes.
5. **osage** — cluster packing.
6. **patchwork** — squarified treemap.
7. **mingle** — post-processing edge bundling (not a layout engine).
8. **ortho** — full port of `lib/ortho/*` (~3000 lines) to replace the
   naïve Z-router (D1).

Live today: **dot** (836 tests) and **circo** (25 tests).

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
