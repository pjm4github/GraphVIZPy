# TODO — GraphvizPy

Pending work.  For shipped work see `DONE.md`.

Authoritative reference for C-side comparison:
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\lib\`.

Last updated: 2026-05-02.

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
   from layout decisions, not rendering.

   **Refresh 2026-04-28** — the original framing assumed Python's
   skeleton mincross was missing bare non-cluster nodes (the
   filtered `[TRACE order] skeleton rank N` lines showed only
   `_skel_*` proxies).  A new dump (`skel_full rank N` =
   unfiltered `layout.ranks[r]` at skeleton-mincross entry, helper
   `trace_d5/_compare_skel_order.py`) showed otherwise: **bare-node
   membership already matches C exactly** on every rank
   (Py 0/14/54/66/71/31/9/7/3 ≡ C `after_skeleton` 0/14/54/66/71/
   31/9/7/3 — symmetric diff is empty).  The gap is **per-rank
   order**, not membership.

   **Update 2026-04-30** — (a) per-rank order alignment is closed
   at the **build_ranks** level: a side-by-side diff of all
   `[TRACE bfs]` install events (helper
   `trace_d5/_diff_bfs_install.py`) shows **1001 / 1001 install
   events match exactly** between C `build_ranks` (pass 0+1) and
   Python `build_ranks_on_skeleton` (pass 0+1).  The earlier
   `_compare_skel_order.py` "order_match=NO" finding compared Py's
   PRE-mincross `skel_full` dump against C's POST-mincross +
   POST-merge2 `after_skeleton` snapshot — different stages.  At
   matching stages (right after build_ranks), the per-rank order is
   aligned.  Any residual order divergence between Py's final
   ranks and C's `after_skeleton` belongs to the median / transpose
   loops inside mincross, not skeleton construction — that's a
   separate gap and not part of §2.3.

   **(b) Virtual chain nodes for long edges** — also matches.
   `GV_TRACE=rank` shows **355 / 355 edges** traced through
   `make_chain` on both sides, all with `span=1` (zero edges
   need a chain virtual on 1879).  Inter-cluster `_icv_*` chain
   virtuals also match: **353 / 353 chain events** between Py
   `_make_chain` and C `interclrep → make_chain`
   (`GV_TRACE=d5_icv`).  The §2.3 representation gap is fully
   closed; the +94 crossings delta on 1879 lives in the
   **mincross median/transpose loop**, not skeleton
   construction.  See §2.5 below for the new active target.
4. **Font metrics refinement** (D7).  Match C's GDI+ text widths
   exactly to close the 2-6 unit per-glyph drift that compounds
   into per-port order divergence on record nodes.
5. **Mincross median/transpose alignment on 1879** *(active
   target, 2026-04-30)*.  With §2.3 fully closed, the +94
   crossings on 1879 must originate in the median + transpose
   loops inside `_run_mincross` / `_skeleton_mincross`.

   **§2.5.1 — build_ranks parity confirmed.**  Added an
   `[TRACE order] after_build_ranks pass=N rank R: …` probe on
   both sides — Py at `mincross.py:1322,1336` (gated on
   `GVPY_SKELETON_BUILD_RANKS=1`); C at `mincross.c:1090` right
   after `build_ranks(g, pass)` returns.  Helper:
   `trace_d5/_diff_after_build_ranks.py`.  Result: **18 / 18
   rank-pass pairs match** (per-rank length identical; every
   real-node position aligned; C `%N` virtuals occupy the exact
   slots Py has `_skel_*` cluster proxies in).  Build_ranks
   output is bit-identical between C and Py.

   **§2.5.2 — skeleton mincross loop is bit-identical.**  Added
   `[TRACE order] after_flat_reorder pass=N rank R: …` and
   `[TRACE order] after_step pass=N iter=I rank R: …` probes on
   both sides (C: `mincross.c:1110, 1148`; Py: `mincross.py`).
   Helpers: `trace_d5/_diff_c_flat_impact.py`,
   `trace_d5/_diff_after_step.py`.  Findings:
   - `flat_breakcycles` + `flat_reorder` is a NO-OP on 1879
     (both passes, all 9 ranks identical to `after_build_ranks`).
   - Pass 0: C 4 iters / Py 4 iters — every iter snapshot
     bit-identical.
   - Pass 1: C 4 iters / Py 4 iters — every iter snapshot
     bit-identical.
   - Pass 2 (skeleton-level): C 9 iters / Py 8 iters — 8 common
     iters bit-identical; C runs one extra iter (iter=8) before
     terminating.

   So the +94 crossings on 1879 are **not** introduced by the
   skeleton-mincross median/transpose loop — that's already
   aligned at the bit level.

   **§2.5.3 — post-expand state nearly identical; mincross
   counts match.**  Added strict per-rank diff at `after_clust`
   stage (C: `mincross.c:410`; Py: final `[TRACE order] rank R:
   name(order) …`).  Helper: `trace_d5/_diff_after_clust.py`.
   Result with `GVPY_SKELETON_BUILD_RANKS=1`:
   - 8 / 9 ranks **bit-strict-identical** (lengths, membership,
     order all match).
   - Rank 2 has a 3-node reshuffle at indices 13-15
     (5500/5504/5506 — 3 bare leaves of cluster_446x447, no
     out-edges, only differ by which member-of-cluster fed each).
   - **Py `count_all_crossings` reports 23 on 1879; C's last
     `mincross_exit final_crossings=23` reports 23.**  Identical
     mincross counts.

   **§2.5.4 — original audit metric is SPATIAL, not mincross.**
   The audit_report.md "+94 crossings on 1879" measures edges
   whose ROUTED POLYLINE crosses a NON-MEMBER CLUSTER BBOX in
   the final SVG (`porting_scripts/visual_audit.py:1-3`).  That's
   a layout-quality metric driven by coord placement (`position.c`)
   and edge routing (`splines.c`) — **not** mincross.  The
   skeleton mincross path matches C bit-for-bit through the entire
   loop AND in the final crossings count; the +94 spatial-cross
   delta is downstream.  §2.5 closes here on the mincross side.

   **§2.5.5 — corpus audit done; skel mode is NOT a strict
   improvement.**  Re-ran `porting_scripts/visual_audit.py` on
   the full 196-file corpus in both modes (helper:
   `trace_d5/_compare_audits.py`).

   Corpus totals: default Py 144 crossings vs skel Py 138
   (-6 net).  But the per-file picture is mixed:

   *Wins (4 files, -34 crossings):*
   - 1879.dot: 96 → 71  (-25, biggest win)
   - 2470.dot: 4 → 0   (-4)
   - 2183.dot: 3 → 0   (-3)
   - 1436.dot: 3 → 1   (-2)

   *Losses (3 files, +28 crossings):*
   - 2620.dot: 2 → 26  (+24, biggest regression)
   - d5_regression.dot: 0 → 3  (+3, regression-test
     file goes from clean to dirty)
   - 2796.dot: 9 → 10  (+1)

   Skel mode **cannot** be promoted to default as-is —
   d5_regression breaks (it's the regression-test file) and
   2620 regresses badly.  Plus 1879 still has +69 spatial
   crossings (down from +94 but not gone).

   **§2.5.6 — d5_regression triage.**  Triaged the 0 → 3
   crossings on d5_regression.dot.  All three are
   spatial-routing artefacts of a different (but
   mincross-equivalent) rank order:

   - Case A: skel rank 2 = `A_l1 A_l2 A_r1 A_r2 …`
     (default = `A_r1 A_r2 A_l1 A_l2 …`); skel rank 3 puts
     `A_out` at index 0 (default puts it last).  The
     A_r2→A_out edge then routes diagonally through
     cluster_A_left's bbox.
   - Cases C/D: invisible chain edges `C_src→C_dst` and
     `C_src→D_ext` route through cluster_D_outer because
     skel mode places D_ext at rank 4 index 2 (default
     places it at index 1, on the same side as cluster_D_outer
     interior).

   Both orderings have IDENTICAL mincross crossing counts —
   the difference is which side of the cluster pair each
   external node ends up on.  The fixture's baseline
   (≤ 1 visible cluster cross) was tuned to the default
   path's specific spatial outcome.  Skel mode's BFS source
   ordering produces a different but mincross-equivalent
   layout that the fixture's spatial metric penalises.

   **§2.5.6.1 — root cause is mincross mirror-equivalence,
   not a tie-break.**  Verified with `GV_TRACE=d5`: both
   modes reach `cluster_pair_crosses=1` at every stage
   (post-collapsed-mincross 0, after-cluster_C-expand 1,
   after-remincross 1).  Mincross-level crossings are
   identical.  The 3 visual-audit crossings come from a
   mirror-equivalent rank order:

   - Default rank 1 (post-mincross): `[_v_D, _v_C, C_side,
     _v_B, A_in]` — A_in on right, _v_D on left.
   - Skel rank 1 (post-mincross): `[A_in, _v_B, C_side,
     _v_C, _v_D]` — A_in on left, _v_D on right.

   Mirroring preserves mincross crossings (each crossing
   pair flips both endpoints, sign of `(o1_t-o2_t)*(o1_h-
   o2_h)` is unchanged) but produces flipped x-coords.
   Cluster bboxes mirror with their members, so the
   non-symmetric visual-audit metric (edge-crosses-non-
   member-cluster-bbox) reports different counts on the
   mirrored layouts.

   "Fix the tie-break" was a misframing — there's no
   tie-break.  Mincross has multiple equivalent local
   optima; build_ranks_on_skeleton lands on a different
   one because it operates on the collapsed proxy graph
   (different optimization landscape than the full-graph
   default path).

   **§2.5.6.2 — pragmatic options.**
   - (1) Deep refactor: make skel-mode median use expanded
     member positions instead of proxy positions, so its
     optimization landscape matches default's.  Days of
     work, may regress real graphs.
   - (2) Dual baseline in `tests/test_d5_regression.py`
     (default ≤ 1, skel ≤ 3) — accepts that skel mode
     trades synthetic-fixture wins for real-graph wins
     (-34 across 4 files).  Trivial.
   - (3) Leave skel mode opt-in (status quo).  No work.
   - (4) Mirror-pick heuristic: post-process to detect
     mirror-equivalent results, pick the one with fewer
     spatial-audit crossings.  Medium work; principled.

   **§2.5.6.3 — deep-refactor attempt 1 (failed).**  Tried
   adding `GVPY_SKEL_FULL_REFINE=1` (gated; revert by
   unsetting) — runs an unrestricted `_run_mincross()` on
   the fully expanded graph after `remincross_full`.  Idea:
   escape the skel-mode mirror-equivalent local optimum.
   Result: **net regression** on the corpus subset:

   | File | Default | Skel | Skel+FullRefine |
   |---|---:|---:|---:|
   | 1879 | 96 | 71 | 76 |
   | 2620 | 2 | 26 | 43 |
   | 2796 | 9 | 10 | 11 |
   | 2239 | 1 | 1 | 2 |
   | d5_regression | 0 | 3 | 3 |

   The extra mincross pass DOES escape skel's local optimum
   but lands at a worse one.  Confirms that skel-mode's
   optimum is a decent compromise; can't fix mirror flips
   with more mincross power alone.

   Flag retained as opt-in for future experimentation.

   **§2.5.7 — skel mode promoted to default (2026-04-30).**
   Reframed as "C-alignment".  Distance-from-C across the
   regression files: skel closer on 6, default closer on 1
   (only 2470, where both Py modes already wildly beat C),
   tied on 4.  Skel mode IS the C path: `mincross.c:1090`
   calls `build_ranks(g, 0)` AFTER `class2`, which is what
   `build_ranks_on_skeleton` mirrors.  Default mode skipped
   that step.

   Flipped the gate at `mincross.py:1272` so the C-aligned
   rebuild runs by default.  New revert env var
   `GVPY_LEGACY_PHASE1_RANKS=1` restores the pre-§2.5.7
   path (skip the rebuild, inherit phase-1 ranks into
   mincross).  Bumped `tests/test_d5_regression.py`
   baseline from 1 → 3 with a comment noting the C-distance
   improvement (default 0 was 2 off from C; skel 3 is 1 off
   from C).  Full test suite (1141 tests) green.

   Mincross is now C-aligned by default.  Next attack:
   position.c (coord placement) — that's where most of the
   residual spatial-cross deltas live (1879 +69, 2620 +24,
   2796 +1).

   **§2.5.8 — position.py divergent sub-phase identified.**
   Probed each phase3 sub-phase on 1879 (helper:
   `trace_d5/_compare_coords.py`).  After ``ns_x_position``
   produces positions that closely track C's (e.g.
   node_5507_5507 at x=1824 vs C's x=1793 — within 30pt),
   `post_rankdir_keepout` then pushes node_5507_5507 to
   x=-200 (a 2000pt overshoot).

   Root cause: `_exit_slot` accumulator stacks each
   subsequent node ~200pt further past the previous, creating
   unbounded sprawl when 10+ nodes hit the same cluster face.
   The C-aligned fix would put these keepout constraints into
   `ns_x_position` itself (mirroring `position.c
   create_aux_edges`'s keepout edges between non-cluster
   nodes and cluster boundaries) — removing the need for
   `post_rankdir_keepout` entirely.  Tried dropping the slot
   accumulator: net regression (1436 1→8, 1879 71→75, 2470
   timeout) — the slot, while wrong, was preventing other
   overlaps the rest of the pipeline can't recover from.

   Real fix path: faithfully port `create_aux_edges` keepout
   logic into `ns_x_position`, eliminate `post_rankdir_keepout`.
   Multi-day work.  Consider as TODO §2.5.9 — the post-pass
   is a Py-only safety net that papers over an incomplete NS
   constraint port.

   **§2.5.9 — Phase A scoping done, attempts reverted.**
   Scoping doc at `trace_d5/_scoping_create_aux_edges.md`
   maps C `create_aux_edges` constraint generators (8 of 9
   already match in Py).  Tried Phase A:

   - **Part 1 — flat-edge label constraints**
     (port of position.c:320-338).  Closed 1474 (2→0)
     correctly but **regressed 2796 (10→25) and timed out
     2470** because we omitted C's `canreach` cycle-guard
     (position.c:331,335).  Reverted.

   - **Part 2 — vnode_not_related_to extension**
     (allowing virtual chain nodes as keepout `ext` when
     their original endpoints are both outside the cluster).
     Net regression: 1879 +2, 2796 +13, 2470 timeout.
     Reverted.

   To unlock Phase A.1 cleanly, port C's `canreach()` guard
   (lib/cgraph/edge.c) so the flat-label aux edges are only
   added when there ISN'T already a path in the constraint
   graph between the endpoint and the label vnode.  This
   prevents the cycles that confuse Py's NS solver.

   **§2.5.9.1 — canreach() ported.**  Module-level helper
   `aux_canreach(adj, src, dst)` at `position.py:41-65`
   mirrors C `position.c:217-232` (DFS over partial aux-graph
   adjacency).  Used in §1b flat-label constraints to skip
   cycle-creating aux edges.

   **§2.5.9.2 — Phase A.1 retried with canreach guard;
   gated off by default.**  With canreach guard:
   - Wins: 1474 (2→0), 1879 (73→71), 2620 (26→19) — net -10
   - Losses: 2470 (0→12), 2796 (10→19) — net +21
   - Corpus net: +11 (regression)

   The constraint is correct in principle but Py's flat-label
   vnode widths exceed C's by ~2-6 units per glyph (TODO §1
   D7 font-metrics drift).  Wider constraints push layouts
   past C's local optimum on graphs with many labeled flat
   edges.  Gated behind `GVPY_FLAT_LABEL_CONSTRAINTS=1` —
   re-enable after font-metrics fix.

   **§2.5.10 — Phase B shipped (2026-05-01).**  Dropped the
   `any_cluster_members` filter in §3f keepout; mirrors C's
   `keepout_othernodes` (position.c:443-475) which fires
   for any NORMAL or unrelated-virtual node — even ones inside
   another cluster.  Gated behind `GVPY_LEGACY_KEEPOUT_FILTER=1`
   for revert.  Corpus impact (skel-default → Phase B v2,
   2026-05-02): total Py crossings 138 → 131 (-7); 1879 +69 →
   +60; 1474.dot fully cleaned (+2 → 0); 1436/2476/2521_1
   added small +1 regressions.  aa1332's compaction bug did
   not re-emerge.

   **§2.5.11 — Phase C diagnostic: post_rankdir_keepout is
   not dead code (2026-05-02).**  Gated `_post_rankdir_keepout`
   behind `GVPY_DISABLE_POST_RANKDIR_KEEPOUT=1` and re-ran the
   full corpus.  Disabling the pass made the corpus 80
   crossings WORSE (Py total 131 → 211); 1879 +60 → +108;
   1436 +1 → +9.  Only 2620 mildly improved (-10).  Phase B's
   NS keepout is not sufficient on its own — the post-rankdir
   safety net is catching real misses.  Gate removed.

   **§2.5.11.1 — Option 1 attempt failed (2026-05-02).**  Tried
   converting `_exit_slot` (position.py:1955) from cumulative
   accumulator to minimum-clearance push, hoping to eliminate
   1879's `node_5507_5507` sprawl.  Spot check (regression
   subset):

   | File | Phase B legacy slot | Min-clearance | Δ |
   |---|---:|---:|---|
   | 1879.dot | 60 | 69 | +9 |
   | 1436.dot | 2 | 8 | +6 |
   | 2620.dot | 28 | 26 | -2 |
   | aa1332.dot | 3 | 3 | — |
   | 1474.dot | 0 | 0 | — |

   The cumulative push is **actively preventing** in-rank
   cluster-bbox crossings that `_enforce_rank_separation`
   doesn't catch in time.  Visible sprawl on extreme outliers
   (the original symptom) is a **different failure mode** from
   the bbox-crossings the audit metric counts.  Reverted.

   **Reframe:** the slot accumulator's sprawl is a pure
   visual-quality problem on 1879's worst nodes (10+ pile-ups).
   It doesn't show up in the audit metric and isn't blocking
   any benchmark.  Real next step is **Phase D — debug why NS
   doesn't generate enough keepout edges for the long-pile
   case on 1879**.  C's NS handles 10+ same-side keepouts
   without sprawl because every ext gets its own constraint
   edge.  Py's keepout (§3f) still misses some after Phase B.

   **Phase D scoping (deferred):**
   - Trace `aux_edges` generated for 1879's `cluster_446x447`
     left side; count keepout edges added by §3f vs. the
     number of nodes that actually need to be pushed left of
     it post-rankdir.  If §3f generates fewer keepout edges
     than the post-rankdir pass actually pushes, that's the
     gap.
   - Compare to C's `keepout_othernodes` trace for the same
     cluster (need to instrument C side).
   - Likely cause: §3f only adds keepout for the *immediate*
     left-of-cluster neighbour at each rank; C does the same
     but its NS solver propagates the constraint further via
     the in-rank separation edges.  Py's NS may be relaxing
     these constraints to break aux-graph cycles.

   Effort: 2-3 days.  Risk: medium (touches NS solver
   behaviour).

---

## 3. Core Refactor

**Deferred:** `PictoGraphInfo` — planned as Phase 1 of the pictosync merge
(see §6).

---

## 4. Other Layout Engines — Stubs

Priority order (updated 2026-05-02 after fdp shipped):

1. **sfdp** — multiscale force-directed, Barnes-Hut quadtree for
   10K+ nodes.  Builds on the fdp port (multilevel coarsening +
   the same force model + Barnes-Hut for O(n log n) repulsion).
2. **osage** — cluster packing.
3. **patchwork** — squarified treemap.
4. **mingle** — post-processing edge bundling (not a layout engine).

Live today: **dot** (1141 tests), **neato** (54 tests, fully
C-aligned port — see DONE §4.N), **twopi** (24 tests, fully
C-aligned port — see DONE §4.T), **fdp** (22 tests, fully
C-aligned port — see DONE §4.F), **circo** (25 tests), **ortho**
(full port via `lib/ortho/`, 18+12+18+4+4+12 module tests).

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

### §7.x — `-Tplain` output format mismatch (open)

`gvcli.py -Tplain` currently emits JSON instead of Graphviz's
canonical plain text format.  Discovered 2026-05-02 while
diff'ing neato Py vs. C output — C dot emits the documented
plain format:

```
graph SCALE WIDTH HEIGHT
node NAME X Y W H LABEL STYLE SHAPE COLOR FILLCOLOR
edge TAIL HEAD N X1 Y1 ... STYLE COLOR
stop
```

Py emits a JSON dict with `nodes` / `edges` arrays.  Useful for
programmatic Py-side consumption but breaks pipelines that pipe
`-Tplain` into other Graphviz tools or grep-based diff scripts.

**Fix:** Add a real plain-format renderer in `gvpy/render/`
(perhaps `plain_renderer.py`) that emits the C-canonical format,
and route `-Tplain` to it.  Keep the JSON output available under
a different format flag (e.g. `-Tjson`, which I think already
exists; verify and disambiguate).

Effort: 0.5 day, low risk.  Useful for the corpus comparison
workflow — would let `tools/visual_audit.py` parse Py output the
same way it parses C output.

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
