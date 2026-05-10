# TODO — GraphvizPy

Pending work.  For shipped work see `DONE.md` (newest → oldest).

Last reorganized: 2026-05-09.

**Engine port arc is complete** — all 9 layout engines have full
C-aligned ports (see DONE.md §4.* and the engine matrix below).
1307 tests passing.  The active workfront is now the pictosync
merge (§3) and the MainGraphvisPy GUI (§4).

---

## 1. Python ↔ C Divergences

Known functional gaps in the live `gvpy/engines/layout/dot/`
pipeline versus C dotgen.  **Re-prioritized 2026-05-09**: each
divergence is now annotated with a "next-step trigger" — the
condition under which it's worth fixing.  Most are deferred
until a real-world graph in pictosync surfaces a visible
problem.

| # | Divergence | Status | Next-step trigger |
|---|---|---|---|
| **D5** | 1879.dot has +94 spatial cluster-cross delta vs C; 1332_ref +10, 2183 +3, 1436 +2.  Most of the corpus has Py ≤ C (Py routes around clusters *better* than C in many files). | **Defer**.  Mincross + build_ranks bit-aligned with C; sec3d / floor / D7 fixes gated and ready (`GVPY_ROOT_HIERARCHY=1`).  Audit-metric improvement requires closing HTML-table sizing first (D7 follow-on). | A pictosync user reports a real diagram with edges crossing into wrong clusters. |
| **D6** | Phase-3 position lacks hard keep-out for virtuals vs. non-member cluster y-bands. | **Opt-in MVP shipped** behind `GVPY_CLUSTER_CARVE=1` (see DONE.md §1.5.57).  Net -3 corpus crossings; ~9 spurious triangulation failures on 2796.  Promotion to default-on needs (a) `rank_box`/`maximal_bbox` compatibility guard, (b) extension to flat + self-edge corridors. | Same as D5 — a pictosync diagram visibly mis-routed by the disabled-by-default behaviour. |
| **D7** | Per-glyph font widths now match C within 0.01pt (LUT shipped, see DONE §4.S-* arc and `font_metrics_lut.py`).  Residual ~33pt mean / 150pt max NODE-width drift on 1879 lives in **HTML-table cell sizing** (`html_label.py` vs C `htmltable.c`). | **Defer**.  Per-cell C dump probe needs a libexpat-enabled local build (CLAUDE.md forbids reconfiguring CLion's build dir).  Could build a sibling cmake dir or translate `htmltable.c` line-by-line in Python (~2-3 hrs).  See DONE.md §2.5.12-21 archive. | Pictosync renders an HTML-`<TABLE>` node whose width visibly disagrees with the C reference. |
| **D8** | Recursive layout pipeline can't be invoked on a subgraph clone (DotGraphInfo assumes root state). | **Dormant** — no live consumer after D2 / E+.2-A closure. | Pictosync needs to lay out a sub-tree of a larger graph independently. |

**Closed divergences** (rolled out of this table):

- **D2** (record-field-port flat-edge routing) — won't-fix, see DONE.md §1.5.58.
- **D4** (cluster corner-grazing) — splines-level cover shipped via the `cluster_detour` pass (§1.5.20-57).  Every remaining case is a D5 mincross/position symptom rather than a D4 clipping issue.

**Tooling caveats** (still active):

- `count_cluster_crossings.py` uses `le.route.spline_type` to pick bezier vs. polyline sampling — verify after any `EdgeRoute` schema change.
- `visual_audit.py` infers C-side bezier-vs-polyline from `"C"` command letters — a Graphviz output-format change could silently re-introduce phantom crossings.
- Audit timeout budget is 60 s per graph per side; remaining timeouts fall into very-large-graph territory (see §6).

---

## 2. Core Refactor

**Deferred:** `PictoGraphInfo` — planned as Phase 1 of the
pictosync merge (see §4).

---

## 3. MainGraphvisPy GUI

Five-phase plan, none started.  This is the natural next
project — the layout engines are done; the GUI is the user-
facing payoff.

1. **Backing model integration** — wire `cgraph.Graph` under
   the GUI scene; drive node/edge creation through it; sync
   attributes.
2. **DOT save/load** — replace custom JSON with DOT round-trip
   through cgraph.
3. **Layout integration** — "Auto Layout" button running
   `DotLayout(graph).layout()`; update `NodeItem`/`EdgeItem`
   positions and routes.
4. **Attribute sync** — node/edge/graph attributes through
   cgraph; subgraph/cluster UI support.
5. **Pictosync alignment** — `SVGNodeRegistry`,
   `attribute_schema.json`, snake_case identifiers throughout.

---

## 4. Pictosync Merge

| Phase | Description | Status |
|---|---|---|
| 1 | graphvizpy as pip dep in pictosync venv | pending |
| 2 | GraphAdapter (canvas ↔ cgraph bidirectional sync) | pending |
| 3 | QTreeView hierarchy browser + folder-per-subgraph persistence | pending |
| 4 | Layout menu entries (dot / neato / circo / twopi / fdp / sfdp / osage / patchwork) | unblocked — all engines C-aligned |
| 5 | DOT import/export, round-trip validation | blocked on Phase 2 |
| 6 | `SimNode(Node)` subclass with 4-phase execution | new work |
| 7 | `DiscreteTimeSimulator` engine on a Graph of SimNodes | depends on Phase 6 |
| 8 | MNAM matrix builder from cgraph topology | depends on Phase 7 |
| 9 | MainGraphvisPy cgraph integration | depends on §3 |

Order 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.  Phases 1–5 unblock
pictosync's diagram UI; 6–9 add simulation.

---

## 5. Diagnostics & Tooling

- `tools/visual_audit.py` — corpus-wide Python vs. C crossings
  audit.  Reruns in ~25-30 min.  `audit_report.md` is the
  baseline snapshot.  Override the C-side dot.exe with
  `GVPY_DOT_EXE=/path/to/dot.exe`.  Default is the local
  CLion-built dot, which lacks libexpat (so HTML `<TABLE>`
  content isn't rendered, but non-table sizing still matches).
  The upstream Windows distribution at
  `c:/tools/graphviz/bin/dot.exe` has libexpat.
- `tools/count_cluster_crossings.py` — per-graph Python counter.
  `use_channel` kwarg is a no-op (kept for back-compat).
- `[TRACE d5_step]` / `[TRACE d5_edges]` / `[TRACE d5_icv]` —
  D5 diagnostic channels in both engines.

### Performance — large-graph timeout work

- **Very large graphs** (≥ 20 k lines): algorithmic complexity,
  not overhead.
- **Medium graphs** (~500 nodes like 2343.dot) where phase-4
  splines shortest-path triangulation dominates (94% of the
  runtime is `routespl.routesplines_` →
  `shortest.Pshortestpath` → `_triangulate_pnls` →
  `isdiagonal`, ~236 M `ccw` calls per run).  Triage targets:
  memoise per-obstacle, cache clip-box once per edge, or swap
  in a different visibility algorithm.  Also: ~40
  `Pshortestpath failed` fallbacks per 2343.dot run each pay
  full triangulation cost — fixing whatever causes the
  failures would cut the work entirely.

### sfdp QuadTree — Barnes-Hut O(n log n) repulsion

**Defer** — slow O(n²) variant ported in §4.S-spring-electrical
is correct.  Performance only matters above n ≈ 500.  Three
porting approaches (refactor existing Python BH, full
QuadTree.c port, or vectorised numpy / Cython) sketched in
DONE.md §4.S notes.  Revisit when there's a concrete user-
facing perf ask.  Legacy Python Barnes-Hut remains available
behind `GVPY_SFDP_SPRING_ELECTRICAL=legacy`.

---

## 6. HTML-like Labels — open follow-ups

Phases 1-4 + 4+ (text styling, `<TABLE>`/`<TR>`/`<TD>`,
mixed-content) shipped 2026-04-21/22 (see DONE.md).

1. **`<IMG>` follow-ups** — remote-URL `SRC` (currently
   file-path only); SVG file size probe (currently PNG/JPEG/GIF
   only).  The `<IMG SRC>` resolution-failure fallback is
   tracked separately as §1 D7 (1879.dot bug-compat with C).
2. **Spline-side port-exit geometry through cell edges** —
   PORT captures cell geometry on `Node.html_table` so
   mincross's port-order hook can resolve `node:port`
   consistently with records, but the spline endpoint still
   funnels through the node's outer bbox rather than the
   cell's edge.  Cosmetic.

---

## 7. Engine matrix (snapshot)

| engine | tests | status |
|---|---:|---|
| dot | 1141 | full port |
| neato | 54 | full C-aligned port |
| twopi | 24 | full C-aligned port |
| fdp | 43 | full C-aligned port + cluster routing + deriveGraph |
| sfdp | 50 | full C-aligned port: clusters + multilevel + spring-electrical + stress smoothing |
| osage | 29 | full C-aligned port |
| patchwork | 28 | full C-aligned port |
| circo | 56 | full C-aligned port |
| ortho | 18+12+18+4+4+12 | full port via lib/ortho/ |

**Total**: 1307 tests passing, 4 skipped, 1 deselected.
