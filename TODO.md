# TODO — GraphvizPy

Pending work.  For shipped work see `DONE.md`.

Authoritative reference for C-side comparison:
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\lib\`.

Last updated: 2026-04-27.

---

## 1. Python ↔ C Divergences

Known functional gaps in the live `gvpy/engines/layout/dot/` pipeline versus
C dotgen.  Reference table — not a priority list (see §2 for priority).

| # | Divergence | Python status | Impact |
|---|---|---|---|
| D5 | Mincross / position layout-level placement: Python places nodes such that an edge geometrically crosses a non-member cluster.  Mincross + remincross 100% aligned with C across 25 passes on 1879.dot, position-phase overlap audit within 2 of C (see DONE.md §1.5.21–53).  Splines-level covers (D4 detour reshape, D6 corridor-carve) absorb most of the per-file residual.  **Corrected baseline (§1.5.60)**: on the 10-file regression subset Python = 133 crossings, C = 57; only 4 files have Py > C.  1879 dominates the delta (+94); on most of the corpus Py < C, i.e., Python's layout already routes around clusters better than C's. | `mincross.py` + `rank.py` + `position.py` aligned with `lib/dotgen/{mincross.c, position.c}`.  Channels: `[TRACE d5_step]`, `[TRACE d5_edges]`, `[TRACE bfs]`.  Helpers: `trace_d5/_pass_compare.py`, `_position_compare.py`, etc. | True regressions (post-§1.5.60 audit fix): 1879=+94, 1332_ref=+10, 2183=+3, 1436=+2 on the 10-file regression subset.  Full corpus rerun pending. |
| D6 | Phase 3 position lacks hard keep-out constraints for virtuals vs. non-member cluster y-bands | MVP corridor-carve shipped 2026-04-27 (§1.5.57): `rank_box_gapped` shrinks the x-extent of regular-edge rank boxes for same-side non-member clusters when `GVPY_CLUSTER_CARVE=1` is set.  Effect: 2796 9→7, 1879 96→95 (net -3 corpus crossings).  Trade-off: ~9 new triangulation failures fall back to polylines.  Kept opt-in until rank_box / maximal_bbox compatibility is hardened.  Straddle cases (prev/next on opposite sides) remain D5 territory. | compounds D5 |
| D7 | Font metrics are Times-Roman AFM, not the rendering font | Layout-side uses TNR via `text_width_system` (tkinter).  Render-side emits the ANTLR-parsed `record_fields` tree on the layout-output node dict and svg_renderer consumes it in place of its hand-written `_parse_record_label`.  Residual: C's GDI+ text widths differ from Python's tkinter/TNR by 2-6 units per glyph, compounding into per-port order drift.  Investigated 2026-04-20 — closing this means matching C's GDI+ text widths exactly. | record-node mincross only |
| D8 | Recursive layout pipeline can't be invoked on a subgraph clone | `DotGraphInfo.__init__` assumes root-graph state | dormant — no live consumer after D2 / E+.2-A closure |

**Closed divergences** (rolled out of this table):

- **D2** (record-field-port flat-edge routing) — closed-out 2026-04-27
  as won't-fix; see DONE.md §1.5.58.
- **D4** (cluster corner-grazing) — splines-level cover shipped via
  the `cluster_detour` pass (§1.5.20) plus follow-ups through
  §1.5.57.  86 → ~150 raw bbox-cross signals, but every remaining
  case is a D5 mincross/position symptom rather than a D4 clipping
  issue.  See DONE.md §1.5.59.

**Tool-side caveats the audit currently absorbs:**
- `count_cluster_crossings.py` uses `le.route.spline_type` to pick
  bezier vs. polyline sampling; verify after any `EdgeRoute` schema
  change.
- `visual_audit.py` infers C-side bezier-vs-polyline from `"C"` command
  letters; a Graphviz output-format change could silently re-introduce
  phantom crossings.
- Timeout budget is 60 s per graph per side; remaining timeouts fall
  into very-large-graph territory (see §7).

---

## 2. Priority 1 — Dot Engine Quality

Ordered by payoff.  Each item is independently shippable.

1. **D5 alignment on the next-largest divergence file**.  The
   §1.5.21–53 workflow (pass-by-pass mincross + remincross trace
   compare → position-phase overlap audit) is the proven recipe.
   1879.dot is closed; current corpus residuals are 1332_ref=16,
   2796=9, 1472=3, then the long tail.  Pick 1332_ref next.
2. **D6 corridor-carve hardening**.  §1.5.57 shipped the MVP
   opt-in (`GVPY_CLUSTER_CARVE=1`).  Promoting to default-on
   needs (a) a guard so the carve doesn't disconnect the rank_box
   from adjacent maximal_bbox / tend / hend boxes (~9 spurious
   triangulation failures on 2796 today), and (b) extension to flat
   and self-edge corridors.  Estimated 80-120 lines.
3. **1879.dot D5 alignment** (96 crossings vs C's 2; +94 delta —
   the only true outlier).  Earlier framing as an HTML-IMG fallback
   bug was wrong: with libexpat-enabled dot.exe (system 14.x, see
   §7), C *does* render the same `<TABLE>` as Python and produces
   nearly identical node sizes (e.g. `node_325x326_325` is 108×79
   pt in C, 110×80 pt in Python).  The 94-crossing delta comes
   from layout decisions, not rendering.  Apply the §1.5.21–53
   pass-by-pass mincross+remincross alignment workflow to find
   where Python diverges from C on 1879's many-cluster genealogy
   topology.
4. **Font metrics refinement** (D7).  Match C's GDI+ text widths
   exactly to close the 2-6 unit per-glyph drift that compounds
   into per-port order divergence on record nodes.

---

## 3. Core Refactor

**Deferred:** `PictoGraphInfo` — planned as Phase 1 of the pictosync merge
(see §6).

---

## 4. Other Layout Engines — Stubs

Priority order:

1. **neato** — stress majorization / Kamada-Kawai.  Widely used,
   well-documented.
2. **fdp** — Fruchterman-Reingold with cluster support.
3. **twopi** — radial BFS; straightforward; good for trees / DAGs.
4. **sfdp** — multiscale force-directed, Barnes-Hut for 10K+ nodes.
5. **osage** — cluster packing.
6. **patchwork** — squarified treemap.
7. **mingle** — post-processing edge bundling (not a layout engine).

Live today: **dot** (1141 tests), **circo** (25 tests), **ortho** (full
port via `lib/ortho/`, 18+12+18+4+4+12 module tests).

---

## 5. MainGraphvisPy GUI

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

## 6. Pictosync Merge

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
| 9 | MainGraphvisPy cgraph integration | depends on §5 |

Order 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.  Phases 1–5 unblock pictosync's
diagram UI; 6–9 add simulation.

---

## 7. Diagnostics & Tooling

- `tools/visual_audit.py` — corpus-wide Python vs. C crossings audit.
  Reruns in ~25-30 min.  `audit_report.md` is the baseline snapshot.
  Override the C-side dot.exe with `GVPY_DOT_EXE=/path/to/dot.exe`;
  the default is the local CLion-built dot, which lacks libexpat
  (so HTML `<TABLE>` content isn't rendered, but the node footprints
  still match because non-table sizing isn't very different).  The
  upstream Windows distribution at `c:/tools/graphviz/bin/dot.exe`
  has libexpat.
- `tools/count_cluster_crossings.py` — per-graph Python counter.
  `use_channel` kwarg is a no-op (kept for back-compat).
- `[TRACE d5_step]` / `[TRACE d5_edges]` / `[TRACE d5_icv]` — D5
  diagnostic channels in both engines (Python: `mincross.py` +
  `trace.py`; C: `lib/dotgen/mincross.c`, `lib/dotgen/class2.c`).

**Remaining timeout work:**
- Very large graphs (≥ 20 k lines) — algorithmic complexity, not
  overhead.
- Medium graphs (~500 nodes like 2343.dot) where phase-4 splines
  shortest-path triangulation dominates (94% of the runtime is
  `routespl.routesplines_` → `shortest.Pshortestpath` →
  `_triangulate_pnls` → `isdiagonal`, ~236 M `ccw` calls per run).
  Triage targets: memoise per-obstacle, cache clip-box once per
  edge, or swap in a different visibility algorithm.  Also: ~40
  `Pshortestpath failed` fallbacks per 2343.dot run each pay full
  triangulation cost — fixing whatever causes the failures would
  cut the work entirely.

---

## 8. HTML-like Labels — open follow-ups

Phase 1-3 (text styling) and Phase 4 (`<TABLE>` / `<TR>` / `<TD>` core)
shipped earlier; Phase 4+ spec-completeness pass shipped 2026-04-21
(see DONE.md).  Phase 4+ PORT + mixed-content pass shipped 2026-04-22.

Open items:

1. **`<IMG>` follow-ups** — remote-URL ``SRC`` (currently file-path
   only), SVG file size probe (currently PNG/JPEG/GIF only).  Note:
   the ``<IMG SRC>`` *resolution-failure* fallback is tracked
   separately as TODO §2.3 (1879.dot bug-compat with C).
2. **Spline-side port-exit geometry through cell edges** — PORT
   captures cell geometry on ``Node.html_table`` so mincross's
   port-order hook can resolve ``node:port`` consistently with
   records, but the spline endpoint still funnels through the node's
   outer bbox rather than the cell's edge.  Cosmetic.
