# TODO — GraphvizPy

Pending work.  For shipped work see `DONE.md`.

Authoritative reference for C-side comparison:
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\lib\`.

Last updated: 2026-04-24.

---

## 1. Python ↔ C Divergences

Known functional gaps in the live `gvpy/engines/layout/dot/` pipeline versus
C dotgen.  Reference table — not a priority list (see §2 for priority).

| # | Divergence | Python status | Impact |
|---|---|---|---|
| D2 | `make_flat_adj_edges` lacks subgraph clone + re-layout | `flat_edge.make_flat_adj_edges` partial (E+.2-B); record-field ports warn | narrow (record-port same-rank only) |
| D4 | Cluster-clipping gives sub-pixel corner-grazing on bezier interior; also control-point-deep-inside cases where tail/head straddle a non-member cluster on adjacent ranks | `make_regular_edge` + `cluster_detour.reshape_around_clusters` (post-hoc detour reshape with 8-pt rounded corners — arc radius > typical 4.5-pt node rounded-rect radius).  Partial cover — residuals are D5/D6 positioning symptoms | was 86, now ~12 visible regressions: aa1332=5, 1332=3, 1472=8, 2796=15, 1213-1=3, 1213-2=3, 2239=0, 1332_ref=4, 2620=2, 2470=17, 1879=105 (HTML-label compat) |
| D5 | Mincross places multi-rank edges on opposite sides of a cluster where C keeps them same-side.  Investigated heavily across [Docs/D5_measurement_findings.md](Docs/D5_measurement_findings.md) §1.5.1–§1.5.20 (2026-04-22 → 2026-04-24).  Most scope-correctness fixes have landed (port-propagation, exit-edge filter, scoped pair-crossing counter, self/foreign skeleton exclusion, scoped `_skel_sub`, weighted `xpenalty` matching C, declared-vs-referenced parser semantics).  **§1.5.21–§1.5.39 (2026-04-25 → 2026-04-26)**: investigated and **closed** 1879.dot's parent-vs-children placement gap at the build_ranks level.  Initial root cause was traced to `build_ranks()` divergence (rank-0 cluster ordering).  Fixes shipped in two layers: **build_ranks side** — install_cluster recursion (§1.5.22), rank-then-DOT source ordering (§1.5.23), rank-internal source repositioning by children-median with iteration-to-convergence (§1.5.24/25); **mincross side** — C-faithful 3-pass loop with MinQuit/Convergence early-stop (§1.5.27), cross-rank transpose with candidate flags (§1.5.29), reverse tie-break (§1.5.29) + CL_CROSS guard for weighted ties (§1.5.30), `flat_mval`/`hasfixed` semantics (§1.5.29), per-pass restart from build_ranks snapshot (§1.5.31), removed redundant remincross loop (§1.5.33).  Then **§1.5.34–§1.5.39 architectural deep-dive** (gated behind `GVPY_SKELETON_BUILD_RANKS=1`): added `build_ranks_on_skeleton` operating on post-class2 skeleton + DFS pre-order through out+in edges + ND_in tail-DOT-sort, mirroring C's `decompose()` exactly.  Closed via 5-channel C instrumentation (`[TRACE skeleton_nlist]`, `[TRACE nd_out_emit]`, `[TRACE gd_clust]`, `[TRACE nd_in_emit]`, `[TRACE bfs]`) — **all 42 BFS source picks on 1879 now match C exactly by name AND iter_order index** (28, 29, 30, 32, ..., 352).  **§1.5.40–§1.5.50 (2026-04-26 → 2026-04-27) — MINCROSS FULLY ALIGNED**: post-build_ranks chain — §1.5.42 added a transpose call at the end of build_ranks_on_skeleton (mirrors C `mincross.c:1700-1701`); §1.5.43 iterated edges by tail node in `layout.graph.nodes` order (mirrors C `class2.c` `agfstnode→agfstout`); §1.5.44 substituted hidden cluster-member ends with their proxies AT THE ORIGINAL EDGE'S POSITION in `layout.ledges`; §1.5.45 mapped `_skel_<cluster>_<rank>` keys back to their cluster name in `node_cl` so reorder's sawclust check fires for skeleton cluster proxies (matches C's `ND_clust(*rp)` behaviour at `mincross.c:1493-1503`); §1.5.46 added a `pass_idx` parameter to `build_ranks_on_skeleton` so it can run in C's pass=1 bottom-up BFS mode and called it at outer pass_n=1 boundary in `_multi_pass_loop`; §1.5.47 propagated transpose candidate flags on ANY swap (incl. tie-break) — mirrors C's `mincross.c:991-1000`; §1.5.48 fixed remincross sawclust gating: (a) sawclust fires only on virtual cluster proxies during cluster expand-mincross; (b) populate `node_cl` with EVERY node during `remincross_full` (mirrors C's `mark_lowclusters` at `cluster.c:433`) and gate sawclust on `(rn_virt OR remincross_phase)` so reorder is a near-no-op in ReMincross; §1.5.49 at the cluster expand-splice step, sort cluster interior by external in-edge median position to mirror C's `mincross_clust(g)` + `mincross(g, 2)` per-cluster mincross — substitutes hidden in-edge tails with their cluster's active proxy at the tail's rank; §1.5.50 fixed a leaky-variable bug where `cl_node_set` from a PREVIOUS expand iteration was used as the intra-cluster filter in §1.5.49's sort, causing legitimate external edges to be falsely skipped (e.g. on 1879 cluster_7499x7500 the sort silently saw 0 in-neighbors instead of 1).  Cumulative result on 1879.dot: **first-reorder match: 100% (353/353)** across all 9 ranks; **pass-by-pass match (top-level events): 100% (10326/10326) across all 25 passes** — entire mincross + remincross pipeline matches C exactly.  1879.dot skeleton-path cluster crossings 133→115 (-18 cumulative); default-path 106→100 (-6).  d5_regression yellow warning (2 vs baseline 1) tracked under §1.5.41+ chain.  1879.dot couple_630x633 + children spread drops 17× (6950pt → 400pt range).  Four analysis helpers under `trace_d5/`: `_event_categories.py`, `_pass_compare.py`, `_compare_table.py`, `_per_rank_diverge.py`. | `mincross.py` + `rank.py` aligned with `lib/dotgen/mincross.c`; `[TRACE d5_step]` / `[TRACE d5_edges]` / `[TRACE bfs]` channels both engines.  **§1.5.51-§1.5.52 (2026-04-27)**: built `trace_d5/_position_compare.py` overlap audit harness; identified post_rankdir_keepout collapsing sibling leaf nodes to same cluster boundary on 1879.dot.  Fix: track per-(cluster, side) exit slots and stack nodes (each next push offset by node_width + nodesep) so siblings pushed past the same face stack properly.  Eliminated all 3 exact-bbox dup groups; node-node overlaps 123→101; cluster-non-member overlaps 37→13; 1879 default crossings 100→87. | residual ~100 partial overlaps (likely from inflated HTML-table node widths exceeding NS-allocated channel widths) — §1.5.53 |
| D6 | Phase 3 position lacks hard keep-out constraints for virtuals vs. non-member cluster y-bands | `position.py` — confirmed aligned with C in §1.5.9 audit (pre/post-NS x-coords match per-engine).  Divergence traces entirely to mincross output.  The "corridor-carve" fix remains the right D6-specific intervention (replace ``rank_box(rank)`` with ``rank_box_gapped`` covering the rank strip MINUS non-member cluster bboxes), ~200-300 lines in phase-4 splines code (``completeregularpath`` / ``routespl`` / ``maximal_bbox``), gated behind ``GVPY_CLUSTER_CARVE=1``.  Can be tackled once the spline test corpus regressions require it. | compounds D4 |
| D7 | Font metrics are Times-Roman AFM, not the rendering font | Layout-side already uses TNR via ``text_width_system`` (tkinter) for record port sizing.  Render-side: emits the ANTLR-parsed ``record_fields`` tree on the layout-output node dict (``record_tree``) and svg_renderer consumes it in place of its hand-written ``_parse_record_label`` — single-parser consistency between layout and render.  ``_parse_record_label`` kept as fallback for older node dicts.  **Investigated 2026-04-20: the "C=42 vs Python=99" claim doesn't reproduce — running C with ``GV_TRACE=port`` on 1332's c0.Out1 gives ``order=99``, same as Python.  Python's compass math in ``RecordField.port_fraction`` matches C's ``compassPort`` (shapes.c:2870) byte-for-byte.  The real residual divergence is in record-field SIZING — C's GDI+ text widths differ from Python's tkinter/TNR widths by a few points per glyph, which compounds into different subfield bboxes, different port positions, and per-port order drift of ~2-6 units (not 50+).  Closing this means matching C's text widths exactly, which is a much deeper project than anything the "compass rotation" framing suggested.** | record-node mincross divergence only |
| D8 | Recursive layout pipeline can't be invoked on a subgraph clone | `DotGraphInfo.__init__` assumes root-graph state | blocks E+.2-A |

**Tool-side caveats the audit currently absorbs:**
- `count_cluster_crossings.py` uses `le.route.spline_type` to pick
  bezier vs. polyline sampling; verify after any `EdgeRoute` schema
  change.
- `visual_audit.py` infers C-side bezier-vs-polyline from `"C"` command
  letters; a Graphviz output-format change could silently re-introduce
  phantom crossings.
- Timeout budget is 60 s per graph per side; remaining timeouts in the
  corpus fall into very-large-graph territory (≥ 20k lines, bounded by
  algorithmic complexity not overhead) and medium graphs where phase-4
  splines triangulation dominates (see §8).

---

## 2. Priority 1 — Dot Engine Quality

Ordered by payoff.  Each item is independently shippable.

1. **Cluster corner-grazing** (D4).  Reduced from 86 to ~10 visible
   regressions after the post-hoc detour reshape (`cluster_detour.py`)
   shipped 2026-04-20.  Detour polylines render with 8-pt rounded
   corners (arc radius > typical 4.5-pt rounded-rect node radius),
   detour margin 20 pt to guarantee ≥ 4-pt clearance.  Residuals split
   between (a) anchor-inside-non-member-cluster cases (pure D5/D6
   positioning issue; not fixable at the splines layer) and (b)
   nested-overlap cases where no detour side clears all other
   non-member clusters near the edge.  Closing the rest means tackling
   D5/D6 directly.
2. **Layout-level fixes** (D5, D6).  Item D5 has had 20 sessions of
   measurement and scope-correctness work — most function-level
   alignment with C is done.  Remaining work targets the median
   heuristic itself (Python's reorder doesn't reach C's local minimum
   on ~12 graphs) or specific regression patterns.  D6 is ~80–120
   lines in `position.py` for the corridor-carve fix.
3. **Font metrics refinement** (D7).  Try Times New Roman metrics,
   replace `svg_renderer._parse_record_label` with `Node.record_fields`
   (ANTLR4).  Closing the 2-6 unit per-glyph drift means matching C's
   GDI+ text widths exactly.
4. **HTML-label IMG fallback compat (D4 / 1879)**.  C silently falls
   back to the node name when an embedded ``<IMG SRC>`` fails to
   resolve, collapsing the node bbox.  Python honors the full table
   (correct per its own HTML interpretation), producing larger nodes
   that tangle with the cluster layout.  1879.dot = 105 crossings on
   that pattern.  Either match C's silent-fallback behaviour (bug
   compatibility) or push through D5 deep enough that correctly-sized
   HTML nodes don't force crossings.

---

## 3. Priority 2 — Splines Port Deferred Items

| Bucket | Status | Notes |
|---|---|---|
| E+.2-A full recursive clone + re-layout | deferred | Requires `DotGraphInfo` to support sub-graph instantiation (blocks on D8) |

---

## 4. Core Refactor

**Deferred:** `PictoGraphInfo` — planned as Phase 1 of the pictosync merge
(see §7).

---

## 5. Other Layout Engines — Stubs

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
  Reruns in ~25-30 min.  `audit_report.md` is the baseline snapshot.
- `tools/count_cluster_crossings.py` — per-graph Python counter.
  `use_channel` kwarg is a no-op (kept for back-compat).
- `[TRACE d5_step]` / `[TRACE d5_edges]` / `[TRACE d5_icv]` — D5
  diagnostic channels in both engines (Python: `mincross.py` +
  `trace.py`; C: `lib/dotgen/mincross.c`, `lib/dotgen/class2.c`).

**Remaining timeout work:**
- Very large graphs (≥ 20 k lines, bounded by algorithmic complexity
  not overhead).
- Medium graphs (~500 nodes like 2343.dot) where phase-4 splines
  shortest-path triangulation now dominates: 94 % of the post-fix
  2343.dot runtime is ``routespl.routesplines_`` →
  ``shortest.Pshortestpath`` → ``_triangulate_pnls`` →
  ``isdiagonal`` (236 M ``ccw`` calls on obstacle polygons per run).
  Algorithmic (C's ear-clip triangulation is the same shape, just
  faster per-call); not a cache miss.  Next triage target would
  attack the triangulation itself — memoise per-obstacle, cache-once-
  per-edge the clip-box, or swap in a different visibility algorithm.
  Also note a large volume of ``routesplines, Pshortestpath failed``
  fallback messages on 2343.dot (~40 per run) — each failed call still
  costs the full triangulation and then routes to a straight fallback;
  fixing whatever makes ``Pshortestpath`` fail could cut those
  triangulations entirely.

---

## 9. HTML-like Labels — open follow-ups

Phase 1-3 (text styling) and Phase 4 (`<TABLE>` / `<TR>` / `<TD>` core)
shipped earlier; Phase 4+ spec-completeness pass shipped 2026-04-21
(see DONE.md).  Phase 4+ PORT + mixed-content pass shipped 2026-04-22.

Open items:

1. **Entity coverage beyond the big five** — currently
   ``html.parser.HTMLParser`` with ``convert_charrefs=True``
   handles every named HTML5 entity, so ``&rarr;`` etc. work for
   free.  No action needed; noted for completeness only.
2. **`<IMG>` follow-ups** — remote-URL ``SRC`` (currently file-path
   only), SVG file size probe (currently PNG/JPEG/GIF only).
3. **Spline-side port-exit geometry through cell edges** — PORT
   captures cell geometry on ``Node.html_table`` so mincross's
   port-order hook can resolve ``node:port`` consistently with
   records, but the spline endpoint still funnels through the node's
   outer bbox rather than the cell's edge.  Cosmetic.
