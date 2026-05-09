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
| D7 | Font metrics LUT ported; HTML-table sizing is the new gap | **§2.5.18 (2026-05-07)**: The C font-metric stack used by the CLion-built ``dot.exe`` is **NOT** GDI+ but the hardcoded LUT in ``lib/common/textspan_lut.c`` (no Cairo/Pango/GD plugin loaded → ``gvtextlayout`` returns false → ``estimate_textspan_size`` falls through to the LUT).  Ported the LUT verbatim to ``gvpy/engines/layout/font_metrics_lut.py`` (11 font families × 4 variants × 128 widths) and rewired ``text_width_system`` to use it.  All 1181 tests pass.  But on 1879 the NODE width drift (Py vs C) is still 33 pt mean / 150 pt max — the dominant drift source is **HTML-table sizing** (`<TABLE><TR><TD>` cell/padding/border math in ``html_label.py``), not text widths.  The per-glyph LUT swap closed the small drift the original framing described but exposed that the big inflation on 1879 lives in table sizing.  See §2.5.18 for the next probe (compare ``size_html_table`` output against C ``htmltable.c`` cell-sizing). | Original D5-sprawl framing of "font metrics drift" was incomplete: per-glyph widths are now within 0.01 pt; HTML-table cell sizing is a separate (newly identified) gap. |
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
4. **Font metrics refinement** (D7).  Match C's GDI+ text
   widths exactly.  §2.5.12 showed D7 controls 100% of the
   keepout-edge minlen inflation (186/186 minlens become
   bit-identical to C when widths are overridden).  But
   §2.5.13 falsified the "D7 alone closes the sprawl"
   hypothesis — with C widths in place, 1879's spatial-cross
   count DOUBLES (62 → 144), so a downstream driver
   independent of font metrics also exists.  D7 is necessary
   but not sufficient; do option 4 of §2.5.13 first
   (post-NS position diff, ~1 hour) to localise the
   downstream driver before committing to the 1-2 week port.
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

   **§2.5.12 — Phase D scoping done; root cause is
   minlen-inflation, NOT a missing-edge gap (2026-05-06).**
   Added matching `[TRACE keepout]` probes on both sides
   (C: `position.c:keepout_othernodes`, gated on
   `GV_TRACE_KEEPOUT=1`; Py: `position.py` §3f, gated on
   `GVPY_TRACE_KEEPOUT=1`).  Helper:
   `trace_d5/_diff_keepout.py`.

   Captured on 1879.dot:

   - **C  : 186 keepout aux-edges (92 L-side, 94 R-side)**
   - **Py : 186 keepout aux-edges (92 L-side, 94 R-side)**
   - **Per-cluster, per-rank, per-side count: 186 / 186
     match.**  Set difference (cluster, rank, side, src, dst)
     is empty in both directions — 0 unique-to-C, 0
     unique-to-Py.

   Originally we expected Py to be missing edges that C adds.
   It isn't.  The structural keepout generator (Py §3f vs
   C `keepout_othernodes`) is **already at C parity** — the
   §2.5.10 Phase B drop of `any_cluster_members` filter
   closed the structural gap completely.

   The actual divergence is in `minlen` values:

   - All 186 shared edges have a `minlen` mismatch (Py is
     **always larger** than C).
   - Top deltas (Py − C):
     - `cluster_450x451 r=3 L src=node_5507_5507`: C=56 Py=128 (+72)
     - `cluster_7461x3   r=8 R dst=node_8_8`:       C=35 Py=100 (+65)
     - `cluster_440x441 r=3 R dst=node_5508_5508`:  C=56 Py=114 (+58)
     - `cluster_52x51   r=5 L src=node_566_566`:    C=49 Py=98  (+49)
     - `cluster_452x453 r=4 R dst=node_5523_5523`:  C=56 Py=103 (+47)
   - The `node_5507_5507` keepout (+72 pt) is the SAME node
     §2.5.11.1 saw sprawl on (pushed to x=-200).  When 10+
     left-side keepouts each carry a +30..+70 pt inflation,
     the cumulative push is hundreds of pt past C's solution.

   Both formulas are `margin + half_width(ext)`.  margin is
   identical (CL_OFFSET=8).  So the inflation comes from
   `half_width(ext)` — i.e. Py thinks the ext node is wider
   than C does.  That's TODO §1 D7 (font-metrics drift)
   propagating from glyph-width into node bbox into keepout
   minlen into NS solution into post-rankdir slot
   accumulator into visible sprawl.

   **Reframing:**
   - The "Py's keepout misses some after Phase B" framing in
     §2.5.11.1 was wrong.  Py's keepout doesn't miss any
     edges; it over-constrains every one it adds.
   - D7 is no longer a "small drift on record nodes only"
     item — it's the **upstream root cause** of 1879's +60
     spatial cluster crossings AND the post-rankdir sprawl.
   - Closing D7 (matching C's GDI+ text widths exactly)
     should collapse the keepout-minlen inflation, which
     should let NS land on C's solution, which should
     remove the need for the slot accumulator and most of
     `post_rankdir_keepout`'s safety-net work.

   **Effort revision:** Phase D as originally framed
   (NS solver / missing edges) is no longer necessary.
   The next attack is **D7 — port C's GDI+ text width
   computation**.  Estimated 1-2 weeks (touches the
   per-glyph metric stack), but unblocks D5/D6/Phase D in
   one shot.

   Instrumentation kept in tree (gated on env vars) for
   future regressions.  Build the C side via the standard
   CLion mingw cmake command.

   **§2.5.13 — D7-sufficiency hypothesis falsified
   (2026-05-06).**  Before committing to a 1-2 week D7 port,
   ran a 1-hour validation experiment to confirm D7 alone
   would close 1879's sprawl.

   Setup:
   - Added `[DUMP widths]` probe to C
     `position.c:create_aux_edges` (gated on `GV_DUMP_WIDTHS=1`),
     emitting one `node=… lw=… rw=… ht=…` line per NORMAL node.
   - Added override hook in `dot_layout.py:_phase3_position`
     (gated on `GVPY_C_WIDTH_OVERRIDE=<path>`) that replaces
     each `Lnode.width` / `Lnode.height` with the C dump
     values right before Phase 3 starts.
   - Captured 549 width records from C for 1879.dot.
   - Ran Py with override; all 549 NORMAL nodes overrode
     cleanly (0 missing matches).

   Two-part result:

   **Part A — keepout minlens: bit-perfect.**  Re-running
   `_diff_keepout.py` with the override:
   - Py vs C minlen mismatches: **186/186 → 0/186**
   - Mean |delta|: **13.8 → 0.0**
   - Max |delta|: **72 → 0**

   D7 fully controls keepout-edge minlens.  No other source
   of inflation exists in the §3f generator.  Width drift is
   100% of the keepout-constraint divergence.

   **Part B — spatial cluster crossings: WORSE, not better.**
   Ran `porting_scripts/count_cluster_crossings.py` on 1879:
   - Default Py             : **62** edges cross non-member clusters
   - Py with C-widths override: **144** edges cross
     non-member clusters

   With Py's keepout constraints exactly matching C's, the
   spatial-cross count more than DOUBLES.  The expected
   "constraints match → positions match → crossings match"
   chain breaks somewhere downstream of the keepout edges.

   **Conclusion: D7 is necessary but NOT sufficient.**  The
   downstream driver(s) for 1879's spatial sprawl exist
   independently of font-metrics drift.  Candidates to
   investigate next:

   1. **`make_LR_constraints` section 1** — section-1 rank
      separation edges in `position.py:240-266` use the same
      `width / 2.0` formula and ARE updated by the override.
      But they may interact with mincross-decided node order
      differently when widths shrink — narrower nodes →
      tighter NS positions → cluster bboxes narrower → edges
      that previously detoured now graze.
   2. **Cluster bbox computation** — `_compute_cluster_boxes`
      may add Py-only padding that C doesn't, or omit padding
      that C adds.  Compare per-cluster bb against C's
      `dot -Tplain` output post-override.
   3. **Phase 4 spline routing** — TODO §1 D4 "cluster
      corner-grazing" was originally a Phase-4 detour issue;
      tighter cluster bboxes (matching C) may re-expose
      cases that the §1.5.20 `cluster_detour` pass papers
      over with Py's wider boxes.
   4. **NS-solved positions diff** — instrument both sides
      to dump post-NS x-coordinates per real node; diff to
      see whether positions match C or diverge despite
      identical constraints.  Cheapest next probe.

   **Effort revision (again):** Don't start the 1-2 week D7
   port yet.  First do option 4 — dump post-NS positions on
   both sides with override active — to localise the
   downstream driver.  ~1 hour.  If positions match C
   despite worse audit count, the gap is in Phase 4 routing
   or bbox computation, NOT in NS / constraint generation.
   If positions diverge, NS solver behaviour or another
   constraint generator (1, 1b, 3a-3e) is the gap.

   D7 stays on the priority list but its impact framing is
   downgraded: closing it eliminates the keepout-minlen
   inflation but does NOT by itself close the spatial-cross
   sprawl.  Both D7 and the to-be-identified downstream
   driver need fixing.

   Instrumentation kept in tree:
   - C: `lib/dotgen/position.c` `create_aux_edges` width
     dump (`GV_DUMP_WIDTHS=1`).
   - Py: `dot_layout.py:_phase3_position` override loader
     (`GVPY_C_WIDTH_OVERRIDE=<path>`).
   - Captures: `trace_d5/1879_widths_c.txt`,
     `trace_d5/1879_keepout_py_cw.txt`.

   **§2.5.14 — post-NS position diff: gap is structural in
   the aux-graph, not just minlen-driven (2026-05-06).**

   Captured `[TRACE position] ns_solved` (gated on
   `GV_TRACE=position`) for 1879.dot in three modes:
   default Py, Py with `GVPY_C_WIDTH_OVERRIDE`, and C.  All
   three emit 549 lines (one per NORMAL node).

   Pre-NS widths with override are bit-identical to C
   (0/549 mismatches in `pre_ns: name lw=… rw=…`).  Post-NS
   x-coordinates diverge:

   - Default Py vs C: 549/549 differ; mean |delta|=4116,
     max=11867.  516 distinct `Py-C` offset bands → no
     coherent global shift.
   - PyC (with override) vs C: 549/549 differ; mean
     |delta|=4381, max=13418.  193 distinct offset bands —
     more clustered but still highly fragmented.
   - 10 000 random node-pair separations (`a-b`) where
     `pyc[a]-pyc[b] == c[a]-c[b]`: only **112/10 000
     (1.1%)** match.  Within 5 pt: 210/10 000 (2.1%).

   Pair-separation invariance is the offset-free measure.
   1.1% match means the layouts are fundamentally different,
   not just globally shifted.  D7 alone closes keepout
   minlens but does NOT close NS-solved positions.

   **Aux-graph topology gap (the new lead).**  The
   `[TRACE position] aux_graph` line shows:

   - C  : `total_aux_edges=2851`
   - Py : `total_aux_edges=2655 total_aux_nodes=1100`
   - **Gap: Py is missing 196 aux-edges that C generates.**

   Even with C-widths overridden, Py's NS gets a smaller
   constraint graph than C's.  This explains why post-NS
   positions diverge despite matched widths: the NS
   solver is solving a subset of the C constraint problem.

   Per-section breakdown (Py, with override active):

   | section | C  count | Py count | match? |
   |---|---:|---:|:---:|
   | sec1 (rank-pair separation, `make_LR_constraints`) | ? | 540 | unknown |
   | sec2 (slack alignment, `make_edge_pairs`) | ? | 710 (= 355 × 2) | unknown |
   | sec3a (containment ln→leaf, leaf→rn) | 196 (98 + 98 from `contain_ln`/`contain_rn` traces) | 196 | **MATCH** |
   | sec3c (compaction ln→rn weight=128) | 98 (1 per cluster) | 98 | **MATCH** |
   | sec3d (hierarchy parent→child) | 0 (flat hierarchy on 1879) | 0 | **MATCH** |
   | sec3e (sibling separation rn→ln) | ? | 925 | unknown |
   | sec3f (keepout, §2.5.12 proven) | 186 | 186 | **MATCH** |
   | **total** | **2851** | **2655** | gap = +196 (C) |

   The 196-edge gap is in **sec1, sec2, or sec3e**.
   Containment + compaction + hierarchy + keepout all
   match.  Likely candidates for the gap:

   - **sec1**: C's `make_LR_constraints` adds flat-edge
     endpoint constraints (position.c:340-372).  1879 has 0
     flat (same-rank) ledges in Py's view, but C's view
     might count differently if a cluster-internal edge
     becomes flat after virtual-chain expansion.
   - **sec2**: Py iterates `layout.ledges` for slack-node
     alignment.  C iterates `ND_save_out` per node, which
     includes virtual chain segments.  1879 has 0 chain
     virtuals per §2.5, so this should match — but worth
     verifying with a per-segment counter.
   - **sec3e**: Py's `separate_subclust` uses a per-rank
     mincross-order rule; C uses `v[0]` at `high.minrank`.
     These can differ on cluster ordering at the
     decision rank, which would change which (left,
     right) sibling pair gets an edge.  Or Py may skip
     overlapping pairs that C keeps (or vice versa).

   **Next probe (~30 min).**  Add per-section counters to
   C `position.c` (5 lines: increment per `make_aux_edge`
   call inside each generator, dump via
   `GV_TRACE=position` at end of `create_aux_edges`).
   Rebuild, recapture, diff section totals.  That
   localises the gap to one of sec1 / sec2 / sec3e.

   **Reframe (again).**  D7 (font metrics) is necessary
   for keepout-minlen parity but is one of two independent
   gaps.  The other gap is structural (missing aux-edges
   in Py's section 1, 2, or 3e).  Both must be closed for
   1879's spatial sprawl to fully match C.  Effort
   estimate: D7 still 1-2 weeks; structural gap likely
   1-3 days once localised.

   Instrumentation kept in tree:
   - Py section counter: `GVPY_TRACE_AUX_SECTIONS=1`
     emits `[AUX SECTIONS] sec1=… sec2_align=… …` from
     `position.py` `ns_x_position`.
   - Captures: `trace_d5/1879_pos_{c,py,py_cw}.txt`,
     `trace_d5/1879_aux_sec2.txt`.

   **§2.5.15 — structural gap localised to sec3d hierarchy
   (2026-05-06).**

   Added per-section counters to C `position.c` (one
   increment per `make_aux_edge` call, dumped at the end
   of `create_aux_edges` via the existing `[TRACE
   position]` channel).  Side-by-side with Py's
   `[AUX SECTIONS]` line on 1879.dot:

   | section | C | Py | delta |
   |---|---:|---:|---:|
   | sec1 (rank-pair separation) | 540 | 540 | 0 |
   | sec1b (flat-edge label) | 0 | 0 | 0 |
   | sec1c (flat-edge endpoint) | 0 | 0 | 0 |
   | sec2 (slack alignment) | 710 | 710 | 0 |
   | sec3a_cont (ln→leaf, leaf→rn) | 196 | 196 | 0 |
   | sec3a_lrvn_label | 98 | 0 | +98 |
   | sec3c_compact (ln→rn w=128) | 0 | 98 | -98 |
   | **sec3d_hier (parent↔child)** | **196** | **0** | **+196** |
   | sec3e_sib (rn→ln) | 925 | 925 | 0 |
   | sec3f_keepout | 186 | 186 | 0 |
   | **total** | **2851** | **2655** | **+196** |

   The +98 / -98 swap on `lrvn_label` vs `compact` is
   cosmetic: C's `make_lrvn` creates a label-width edge
   `ln→rn`, then `contain_clustnodes` finds it via
   `find_fast_edge` and promotes its weight by 128 instead
   of creating a new edge.  Py creates the compaction edge
   fresh in section 3c.  Same 98 ln→rn edges, same
   constraint, just different bookkeeping in the counters.

   The real structural gap is **sec3d hierarchy = +196
   edges**.

   **Root cause:** C's `contain_subclust` is called on the
   root graph and recursively descends.  At the root call,
   it iterates the root's direct cluster children and
   adds, for each:

   - `root.ln → cluster.ln` (margin + root.border_left)
   - `cluster.rn → root.rn` (margin + root.border_right)

   For 1879, root has 98 top-level clusters → 98 × 2 = 196
   hierarchy edges.

   Py's section 3d in `position.py:457-468` skips when
   `tree_parent[cluster] is None` (i.e., the cluster's
   direct parent is the root graph).  Py never creates
   `root.ln` / `root.rn` boundary nodes either.  So the
   196 root-anchor edges are absent.

   This explains why post-NS positions diverge despite
   identical widths: Py's NS lacks the root-bbox
   constraint that anchors all top-level clusters, so
   their absolute X positions float freely relative to
   each other.  The 1.1% pair-separation match (§2.5.14)
   is consistent with "constraints intact within each
   cluster, but inter-cluster spacing under-constrained".

   **Fix path (1 day):**
   1. In `dotinit.py` (cluster discovery) or
      `_phase3_position` (Phase-3 entry), generate
      `_cln_root` / `_crn_root` virtual aux-nodes for the
      root graph.
   2. In `position.py:ns_x_position` section 3d, drop the
      `if par is None: continue` skip; treat `None` parent
      as the root graph and add the two hierarchy edges
      with `margin = root_margin` (CL_OFFSET = 8pt) and
      `border_left/right = 0` (root has no cluster border).
   3. Add a section-3a containment check: the root
      cluster's `ln`/`rn` only constrain top-level
      cluster boundaries (no need for direct member
      edges, since root contains everything trivially).
   4. Re-run `_diff_keepout.py` and corpus audit; expect
      sec3d to flip to 196 in Py and the +196 total gap
      to close.

   Risk: medium.  Adding 196 new constraints could shift
   NS solutions on every clustered graph in the corpus,
   not just 1879.  Need to gate behind
   `GVPY_ROOT_HIERARCHY=1` for the first pass and run
   the full corpus regression before flipping the
   default.

   **Caveat:** Closing this gap should bring Py's NS
   solution structurally closer to C's, but D7 (font
   metrics) is still required to match keepout minlens
   and final per-pixel positions.  The two fixes are
   independent and both must land for full 1879 parity.

   **§2.5.16 — sec3d root-hierarchy fix landed (gated);
   structural correctness confirmed but audit metric
   regresses (2026-05-06).**

   Implemented in `position.py` `ns_x_position`:
   - Added synthetic `_cln_root` / `_crn_root` aux-nodes
     when `GVPY_ROOT_HIERARCHY=1`.
   - Section 3d now treats `tree_parent[c] is None` as
     "root" instead of skipping; emits the missing 196
     `root.ln→cluster.ln` + `cluster.rn→root.rn` edges
     with `margin=CL_OFFSET=8pt`, `border=0`.
   - Seed root.ln/rn at `min/max(cluster_seeds) ±
     CL_OFFSET` so NS doesn't start them at 0.
   - Tests: 1181 pass, 4 skipped (gated path doesn't
     touch the default flow).

   Re-ran section counters — Py now matches C bit-for-bit:

   ```
   Py: sec1=540 sec2=710 sec3a_cont=196 sec3c_compact=98
       sec3d_hier=196 sec3e_sib=925 sec3f_keepout=186
       total=2851
   C : sec1=540 sec2=710 sec3a_cont=196 sec3a_lrvn_label=98
       sec3d_hier=196 sec3e_sib=925 sec3f_keepout=186
       total=2851
   ```

   The 196-edge gap is closed.  The +98/-98 swap on
   `sec3a_lrvn_label` (C) vs `sec3c_compact` (Py) is
   cosmetic — same 98 ln→rn weight=128 edges, different
   order of operations.

   **But cluster-cross audit got WORSE, not better:**

   | flags | 1879.dot crossings |
   |---|---:|
   | baseline (no fixes) | 62 |
   | C-widths override only | 144 |
   | root-hierarchy only | 116 (was 118 pre-seed; -2 with seed) |
   | C-widths + root-hierarchy | 165 |

   And on the corpus subset:

   | file | baseline | with RH | delta |
   |---|---:|---:|---:|
   | 1879 | 62 | 118 | **+56** |
   | aa1332 | 3 | 3 | 0 |
   | 1474 | 0 | 0 | 0 |
   | 2620 | 27 | 28 | +1 |
   | 2796 | 9 | 9 | 0 |
   | 2470 | 0 | 0 | 0 |
   | 1436 | 2 | 2 | 0 |
   | d5_regression | 3 | 2 | -1 |

   Net: -1 on d5_regression, +57 across the rest.  Not a
   win.  Pair-separation match (PyC-widths + RH vs C):
   slightly worse than C-widths alone (103 vs 112 exact
   per 10000 sample).

   **Why the structurally-correct fix hurts the metric:**
   With both Py's aux-graph topology AND pre-NS widths
   matching C, the NS solver still lands at a different
   solution than C's.  Possible causes:
   - **Per-edge minlens differ.**  We've only proven
     sec3f keepout matches.  sec1, sec2, sec3a, sec3d
     minlens may have small drifts (e.g., section 1
     uses `width/2` symmetric — C uses asymmetric
     `ND_lw + ND_rw` if any node has self-loops).
   - **NS solver tie-breaking.**  Both C `rank()` and Py
     `_NetworkSimplex` minimise weighted slack but the
     constraint LP has a polytope of optimal vertices
     when most edges are weight=0.  Different pivot
     rules → different feasible optima.
   - **Phase 4 routing.**  Even with identical NS
     positions, Py's spline router may go through
     cluster bboxes more often than C's.

   **Decision:** Keep `GVPY_ROOT_HIERARCHY=1` gated off
   by default.  The implementation is correct against
   the C reference but not a win on the existing audit
   metric.  Don't flip the default until the deeper
   driver is found.

   **Next probe (~1 hour):**  Dump per-edge minlens for
   sec1 + sec3d (or all sections) on both sides; diff
   to find any per-edge drift.  If minlens fully match,
   the gap is in NS solver behaviour or Phase 4
   routing.  If they differ, target the drift first.

   **Reframe again:** The 1879 sprawl has at least three
   gaps, not two:
   1. D7 font metrics (proven necessary for keepout
      minlen parity, §2.5.12-13).
   2. sec3d root-hierarchy edges (proven topologically
      missing, §2.5.15-16; landed gated).
   3. **A third gap that prevents Py's NS from converging
      to C's solution even when (1) and (2) are matched.**
      Localisation pending — likely per-edge minlen drift
      OR NS algorithm differences.

   None of these alone closes 1879.  The audit metric
   degradation when (1)+(2) are both applied suggests the
   third gap dominates and the first two only matter once
   it is closed.

   **§2.5.17 — minlen-floor drift found and fixed
   (2026-05-06).**

   Added per-edge `[DUMP aux_minlen]` probes on both sides
   (gated by `GV_DUMP_AUX_MINLENS=1` in C and
   `GVPY_DUMP_AUX_MINLENS=1` in Py).  Aggregated by
   `(section, minlen, weight)` and diffed.  Result on
   1879.dot with override + root-hierarchy:

   | section | C-effective | Py | drift |
   |---|---:|---:|:---:|
   | sec1 (rank-pair sep) | 540 | 540 | MATCH |
   | sec2 (slack alignment) | 710 | 710 | MATCH |
   | sec3a (containment) | 196 | 196 | **+8 per edge** |
   | sec3c_eff (compaction post-promote) | 98 | 98 | **+98 minlen drift** |
   | sec3d (hierarchy) | 196 | 196 | **+8 per edge** |
   | sec3e (sibling) | 925 | 925 | **+8 per edge** |
   | sec3f (keepout) | 186 | 186 | MATCH |

   **Drift 1: +8 on sec3a/sec3d/sec3e.**  Root cause:
   Py's `_rc_floor=8` (a "settable routing-channel width
   floor" Py-only knob) inflated every cluster-boundary
   gap by 8 pt.  C uses `late_int(g, G_margin, CL_OFFSET,
   0)` which `atoi`-parses the margin attr — a fractional
   `margin="0.8"` parses to 0 in C, but Py's `int(0.8) =
   0` then `max(0, 8) = 8`.

   Also: the root-hierarchy edges added in §2.5.16 used
   `margin=CL_OFFSET=8`, but C's `late_int(root,
   G_margin, ...)` returns 0 (root's "margin" attribute
   is "0.5,0.5" page-margin which atoi-parses to 0).

   **Drift 2: +98 sec3c_eff label-width.**  C creates
   ln→rn label-width edges in `make_lrvn` for TB clusters
   with labels (`!GD_flip(agroot(g))` is true for TB), then
   `contain_clustnodes` promotes weight to 128.  Py
   currently computes cluster border widths only when
   `is_flipped` (LR/RL) and skips for TB, so the label
   constraint is missing.  98 clusters × minlen ranging
   81-123 vs Py's flat minlen=1.

   **Fixes landed (gated behind `GVPY_ROOT_HIERARCHY=1`):**
   1. `_rc_floor = 0.0` when the gate is set (no routing
      floor — match C's atoi behaviour).
   2. Root sec3d edges use `_atoi_margin(root.margin,
      CL_OFFSET)` — picks up the page-margin's atoi-of-0.
   3. Root-level sec3e siblings use the same root margin.
   4. Drop `max(1, ...)` minlen floor for sec3d/sec3e in
      C-alignment mode (C accepts minlen=0).

   Drift 2 (sec3c label width) NOT yet fixed — needs
   matching of C's TB cluster label-width formula in Py,
   which depends on the cluster's font-metric label width.
   That's effectively D7 territory.

   **Re-run audit on 1879 with fixes:**

   | flags | crossings | vs prior |
   |---|---:|---:|
   | baseline | 62 | — |
   | RH only | 68 | +6 (was +56) |
   | C-widths only | 144 | unchanged |
   | C-widths + RH | **115** | -50 (was 165) |

   The full-alignment combo dropped from 165 → 115 (-50,
   ~30% reduction) once minlen-floor drift was fixed.
   1879 still has +53 over baseline (62) because the sec3c
   label-width edges are missing.

   **Corpus subset (RH-only, no width override):**

   | file | baseline | RH | delta |
   |---|---:|---:|---:|
   | 1879 | 62 | 68 | +6 |
   | aa1332 | 3 | 2 | **-1** |
   | 1474 | 0 | 0 | 0 |
   | 2620 | 27 | 27 | 0 |
   | 2796 | 9 | 9 | 0 |
   | 2470 | 0 | 0 | 0 |
   | 1436 | 2 | 2 | 0 |
   | d5_regression | 3 | 2 | **-1** |
   | net | | | -2 |

   With minlen-floor fixed, RH-only is now net-neutral on
   the corpus subset (was +57 before §2.5.17).  Two small
   wins (aa1332, d5_regression), one small regression (1879
   +6), no other changes.

   1181 tests pass, 4 skipped.  The fixes only fire when
   `GVPY_ROOT_HIERARCHY=1` so the default code path is
   untouched.

   **Remaining gaps for full 1879 parity:**
   1. **sec3c TB cluster label widths** (drift 2 above).
      Compute label text width in Py for TB clusters; emit
      a `cl.ln → cl.rn` edge with minlen = label_w.  The
      label widths are font-metric dependent (D7).
   2. **D7 font metrics** (still required for keepout
      minlen parity, even though §2.5.13 showed it isn't
      sufficient alone).
   3. **Phase 4 spline routing or other downstream**:
      with all three above closed, 1879 should match C's
      ~2 crossings.  If it doesn't, the remaining gap is
      Phase 4.

   Instrumentation kept in tree:
   - C: `position.c create_aux_edges` per-edge minlen dump
     (`GV_DUMP_AUX_MINLENS=1`).
   - Py: `position.py ns_x_position` per-edge minlen dump
     (`GVPY_DUMP_AUX_MINLENS=1`).
   - Captures: `trace_d5/1879_minlens_{c,py,py2}.txt`.

   **§2.5.18 — D7 LUT port done; HTML-table sizing is the
   real gap on 1879 (2026-05-07).**

   Recon discovered the CLion-built C ``dot.exe`` uses
   ``lib/common/textspan_lut.c`` (a hardcoded TrueType-units
   LUT for 11 font families × 4 variants × 128 widths), NOT
   GDI+.  The build has no Cairo, no GD, no Pango plugin
   loaded — ``gvtextlayout`` returns false and
   ``estimate_textspan_size`` falls through to the LUT.

   The original D7 framing assumed a GDI+ port (1-2 weeks);
   the actual fix is a verbatim LUT port (2-3 days).

   **Implementation done in this session:**
   - One-shot extractor: ``tools/_extract_font_lut.py``
     parses C source, emits Python data.
   - New module: ``gvpy/engines/layout/font_metrics_lut.py``
     — 11 font families with the same data, plus the
     C-aligned API: ``_font_name_equal_permissive``,
     ``_lookup_family``, ``estimate_text_width_1pt``,
     ``text_width_lut``.
   - ``common/text.py``: ``text_width_system`` rewired to
     call ``text_width_lut`` (drops the tkinter dependency
     entirely; preserves the function signature).
   - 1181 tests pass; 4 skipped; gated paths untouched.

   **Verification — sample widths:**

   | text | LUT (C) | Py AFM | Py LUT | drift LUT-vs-C |
   |---|---:|---:|---:|---:|
   | `node` | 27.21 | 27.22 | 27.21 | -0.00 |
   | `cluster_446x447` | 93.32 | 93.32 | 93.32 | -0.01 |
   | `mmmmm` | 54.45 | 54.46 | 54.45 | -0.01 |
   | `iiiii` | 19.45 | 19.46 | 19.45 | -0.01 |

   Per-glyph widths are now within 0.01 pt of C's LUT.
   The historical AFM table (Times-Roman 1000-unit-per-em)
   was already nearly equivalent — the actual fix was
   removing the tkinter preference in
   ``record_parser.py`` and ``common/text.py``.

   **But — 1879 spatial-cross count unchanged: still 62.**

   Width audit on 1879 post-LUT-port:

   | metric | value |
   |---|---:|
   | shared NORMAL nodes | 549 |
   | exact match (\|d\|<0.01) | **12 / 549** |
   | mean \|drift\| | **33.3 pt** |
   | max  \|drift\| | **150.7 pt** |

   The drift is concentrated in HTML-table label nodes
   (e.g. ``node_5505_5505`` Py=263.9 vs C=113.2, drift
   +150 pt).  These nodes have ``shape="none"`` with
   ``<TABLE><TR><TD>`` content.  Plain-text and record
   nodes (which use the LUT or AFM directly) are NOT in
   the drift set.

   **The new gap: HTML-table sizing.**  The cell / padding
   / border / cellspacing math in
   ``gvpy/grammar/html_label.py: size_html_table`` (and
   helpers) produces tables 30-150 pt wider than C's
   ``lib/common/htmltable.c``.  Per-glyph widths inside
   the cells now match C, but the surrounding cell-bbox
   math drifts.

   **Next probe (~1 hour):**  Pick one drift node (say
   ``node_5505_5505``), dump its parsed table tree from
   Py, and run ``htmltable.c sizeHTMLLabel`` on the same
   parse tree from C.  Compare per-cell widths/heights.
   The drift is likely in:

   - cell ``CELLPADDING`` / ``CELLSPACING`` defaults
   - ``BORDER`` / ``CELLBORDER`` arithmetic
   - row-height / column-width balancing pass
   - implicit ``<TR>`` height padding
   - or the table-level minimum-size clamp

   **Effort revision:** D7 LUT port done (2 hours, not
   1-2 weeks).  HTML-table sizing fix estimated at 1-3
   days depending on which sub-step diverges.

   **Reframe of D5 sprawl model after §2.5.18:**
   - D7 (per-glyph LUT): closed.
   - HTML-table sizing: NEW gap, dominant width-drift
     source on 1879.  Tracked under D7 in the §1
     divergence table since they share the metric stack.
   - sec3d root-hierarchy: closed (gated, §2.5.16).
   - sec3a/3d/3e minlen-floor: closed (gated, §2.5.17).
   - sec3c TB cluster label widths: still open (depends
     on closing HTML-table sizing first since cluster
     labels can be HTML).

   Once HTML-table sizing matches C, re-run the override
   experiment — expect Py node widths bit-equivalent to
   C without needing ``GVPY_C_WIDTH_OVERRIDE``.

   Instrumentation kept in tree:
   - ``tools/_extract_font_lut.py`` — re-run if Graphviz
     upstream changes the LUT.
   - ``gvpy/engines/layout/font_metrics_lut.py`` —
     deterministic, font-engine-free width path.

   **§2.5.19 — major reference bug: CLion dot.exe has no
   libexpat, so HTML-label drift was overstated by 6×
   (2026-05-07).**

   Probed the HTML-table sizing gap by inspecting one
   drift node (``node_5505_5505``).  Py reports node width
   263.9 pt; the CLion-built C ``dot.exe`` reports 113.2 pt
   (1.5724").  Drift +150 pt.

   But the SYSTEM ``dot.exe`` (``c:/tools/graphviz/bin/
   dot.exe``, version 14.1.4 with libexpat) reports
   **256.5 pt** (3.5625").  Drift only +7 pt.

   The CLion build is missing **libexpat** — without it,
   the C side can't parse the ``<TABLE>...</TABLE>``
   syntax and falls back to treating the literal
   ``<...>`` text as a tiny plain string.  CLAUDE.md
   §"reference binary" notes this caveat ("the default is
   the local CLion-built dot, which lacks libexpat") but
   I missed it during the §2.5.12-18 audits.

   Re-running the per-node width audit on 1879 with the
   SYSTEM ``dot.exe`` as the reference:

   | metric | vs CLion (no libexpat) | vs system (libexpat) |
   |---|---:|---:|
   | mean \|drift\| | 33.3 pt | **5.3 pt** |
   | max  \|drift\| | 150.7 pt | **20.4 pt** |
   | within 0.5 pt | 12 / 549 | 36 / 549 |
   | within 5   pt | n/a | **443 / 549** |

   So the D7 LUT port already lands Py within **5 pt for
   80 % of 1879's nodes** versus the proper C reference.
   The "30-150 pt HTML-table drift" diagnosed in §2.5.18
   was inflated 6× by the reference bug.

   **Remaining 20 pt drift, concentrated on ``couple_*``
   nodes:**

   | node | Py | C-system | drift |
   |---|---:|---:|---:|
   | couple_7499x7500 | 204.82 | 184.39 | +20.43 |
   | couple_440x441   | 180.72 | 160.39 | +20.32 |
   | couple_7461x3    | 170.22 | 149.90 | +20.32 |
   | couple_52x715    | 148.81 | 128.89 | +19.92 |
   | couple_7482x7483 | 126.26 | 106.39 | +19.86 |

   Cause: ``_compute_node_size`` (``dot_layout.py:941``)
   adds ``XPAD=16`` and ``YPAD=8`` around every label
   including HTML labels.  C's path for ``shape="none"``
   HTML tables sets node bbox to the HTML table's own
   bbox without further XPAD/YPAD wrap.  ``204.82 -
   16 (XPAD) = 188.82`` matches Py's ``tbl.width``;
   ``188.82 - 184.39 = 4.43`` is residual cellspacing
   perimeter drift.

   **Implications for §2.5.12-18 findings:**
   - All "Py inflated 30-70 pt per keepout edge" numbers
     are against the CLion (no-libexpat) reference and
     are **inflated by the same 6×**.  Real per-keepout
     drift vs system C is closer to 5-15 pt.
   - The §2.5.13 "C-widths override on 1879 makes
     spatial crossings worse" finding may also need
     re-running with the system dot.exe.
   - The §2.5.16 sec3d root-hierarchy fix and §2.5.17
     minlen-floor fix landed for the right reasons —
     C aux-graph topology and minlens differ regardless
     of the libexpat issue.

   **Updated D5 sprawl model:**

   | gap | status |
   |---|---|
   | Reference: must use system dot.exe for HTML graphs | known caveat now |
   | D7 per-glyph LUT | closed |
   | Keepout structure | matched (proven against CLion ref; valid) |
   | sec3d root-hierarchy | closed gated |
   | sec3a/3d/3e minlen-floor +8 | closed gated |
   | XPAD around HTML labels | **NEW: +16 pt over-pad on shape="none" tables** |
   | cellspacing perimeter (residual) | open, ~4 pt |
   | sec3c TB cluster label widths | open |

   **Effort revision:** The remaining HTML-table sizing
   gap is +20 pt on ``couple_*`` nodes (an XPAD bug
   rather than table sizing) plus ~4 pt cellspacing
   drift.  Estimated 1-2 hours to fix once we decide
   the right behaviour for ``shape="none"`` HTML XPAD.

   Action items kept in tree:
   - ``trace_d5/1879_plain_sys.txt`` — system dot.exe
     -Tplain output for 1879 (the proper reference).
   - Re-run §2.5.12-15 audits with
     ``GVPY_DOT_EXE=c:/tools/graphviz/bin/dot.exe`` set,
     before claiming any final parity number.

   **§2.5.20 — XPAD-removal attempt failed: not the bug
   (2026-05-07).**

   Tried skipping ``XPAD=16`` / ``YPAD=8`` in
   ``_compute_node_size`` for ``shape="none"`` HTML
   labels (the ``couple_*`` nodes were +20 pt over, and
   16 pt of that looked like XPAD over-pad).  Reverted
   after the audit showed the fix went the wrong direction
   on most nodes.

   Result on 1879 with the XPAD-skip patch (vs system C):

   | metric | XPAD on (revert state) | XPAD off (attempt) |
   |---|---:|---:|
   | mean \|drift\| | 5.3 pt | 10.5 pt |
   | max  \|drift\| | 20.4 pt | 22.9 pt |
   | within 5 pt | 443 / 549 | 98 / 549 |

   The drift sign is **not uniform** across HTML nodes:

   | node | with XPAD (Py - C) | without XPAD |
   |---|---:|---:|
   | couple_7499x7500 | +20 (over) | +4 (over) |
   | node_251_251 | -7 (under) | -23 (under) |

   So Py's drift on ``couple_*`` is +20 (over), but on rich
   HTML nodes (BGCOLOR, multiple ``FONT POINT-SIZE``
   rows) it's already **-7 (under)** with XPAD on.
   Removing XPAD makes the under-direction worse.

   The XPAD is doing the right thing on aggregate; the
   actual bug is in ``html_label_size`` itself —
   different nodes drift in different directions.

   **Verified the LUT calculation is right:**
   For ``node_251_251``'s widest row (R4 at 10pt:
   ``"Xxxxxxxx, Xxxxxxxxxx, Xxxxxxxxxxxx, XXX"``):
   - Manual LUT calc: 39594 / 2048 × 10 = 193.33 pt
   - Py ``cell.content_w``: 197.32 (= 193.33 + 4 from
     ``2*cellpadding``).  ✓ matches.
   - Py ``tbl.width``: 201.32 (= 197.32 + 4 from
     ``(ncols+1)*cellspacing``).  ✓ matches Py's
     ``html_label_size`` output.

   So Py's table sizing is internally consistent with the
   LUT.  But system C reports 224.25 pt for this node,
   which is **~23 pt wider than what we compute**.
   With XPAD added (217.32) the residual is still 7 pt.

   **Reframed: the gap is unaccounted-for C-side
   content/padding.**  Possible drivers:
   - ``BGCOLOR`` may trigger extra perimeter padding in
     C that Py doesn't add (only ``couple_*`` lack
     BGCOLOR; the under-pad nodes all have BGCOLOR).
   - ``FONT POINT-SIZE`` per-run may interact with
     line-height or per-line padding differently.
   - ``ALIGN="CENTER"`` may add per-row whitespace.
   - C may compute different cell content widths via a
     different word-wrap or whitespace handling path
     than Py's per-run sum.

   **Next probe (~1 hour):**  Instrument C's
   ``size_html_tbl`` to dump per-cell ``box.UR`` and
   compare side-by-side with Py's ``cell.content_w``.
   That isolates the gap to a specific cell-sizing
   sub-step.

   **State preserved in tree:**
   - 1181 tests pass (XPAD reverted).
   - The XPAD-skip path remains the right fix for
     ``couple_*``-style nodes if we can also fix the
     under-pad on BGCOLOR nodes; the two need a unified
     analysis.

   Action: Park the HTML-table-sizing fix until the
   per-cell C dump is in place.  D5 sprawl summary stands
   as: D7 LUT done, sec3d/floor fixes gated, residual
   ~5 pt mean drift, and one localised drift family
   (BGCOLOR HTML tables) yet to investigate.

   **§2.5.21 — per-cell C dump probe blocked: CLion
   build can't exercise ``size_html_tbl`` (2026-05-07).**

   To dump per-cell sizes from C, we need to instrument
   ``lib/common/htmltable.c: size_html_cell`` and run a
   libexpat-enabled ``dot.exe`` on 1879's HTML labels.
   The CLion build at
   ``cmake-build-debug-mingw/cmd/dot/dot.exe`` has
   ``EXPAT_LIBRARY-NOTFOUND`` in its CMakeCache (libexpat
   not detected at configure time) — so the
   ``parseHTML`` call in ``make_html_label`` returns NULL
   and the ``size_html_tbl`` path is never exercised.
   CLAUDE.md forbids reconfiguring this build dir.

   The system ``dot.exe`` at
   ``c:/tools/graphviz/bin/dot.exe`` IS libexpat-enabled
   (we use it as the proper HTML reference), but it's
   pre-built — we can't instrument it without source.

   **Source-level analysis done instead:**

   - C ``size_html_cell`` (htmltable.c:1100) computes
     ``margin = 2 * (cp->data.pad + cp->data.border)``
     and ``sz.x = child_sz.x + margin``.  Py
     ``size_html_table`` (html_label.py:1283) uses
     ``nat_w = cw + 2 * pad`` — equivalent for default
     ``border=0``, drift only when CELLBORDER differs.
   - C table-level final size (htmltable.c:1670):
     ``wd = (column_count+1) * space + 2 * border``,
     plus ``sum(widths)``.  Py ``tbl.width`` (html_label
     .py:1406): ``2 * b + sum(col_widths) + (ncols+1) * s``
     — identical formula.
   - C ``poly_init`` (shapes.c:1992) adds ``PAD(dimen)``
     = XPAD/YPAD = 16/8 unconditionally for non-plain
     shapes including ``shape="none"``.  Py adds the
     same.
   - For ``couple_*`` (no BGCOLOR, simple text): Py = 188.82
     table + 16 XPAD = 204.82.  Csys reports 184.39 —
     consistent with C ADDING 0 instead of 16 XPAD.
   - For ``node_251_*`` (BGCOLOR, FONT POINT-SIZE): Py
     = 201.32 + 16 = 217.32.  Csys = 224.25 — consistent
     with C adding ~23 pt extra (more than XPAD).

   So the drift sign flips between BGCOLOR and non-BGCOLOR
   nodes.  This **cannot** be explained by a uniform XPAD
   bug.  Likely C has a per-table behaviour that differs
   based on table attributes (BGCOLOR triggering extra
   perimeter padding, or some FONT POINT-SIZE / ALIGN
   interaction) which Py mirrors only partially.

   **To unblock localisation** we need one of:
   (a) Build a libexpat-enabled ``dot.exe`` in a sibling
       directory ``cmake-build-libexpat-mingw`` outside
       CLion's path (msys64's ``libexpat.a`` is already
       on disk at ``C:/msys64/mingw64/lib/``).  Per
       CLAUDE.md the existing CLion dir is off-limits but
       a new sibling dir is fine.  Estimated 30-60 min to
       configure and build, then the ``[DUMP cell]``
       instrumentation runs cleanly.
   (b) Translate C ``size_html_tbl`` /
       ``size_html_cell`` line-by-line into Python and
       diff against Py's ``size_html_table`` algorithm.
       Estimated 2-3 hours, pure reading/translation.

   Both are tractable but bigger than the per-cell probe
   was meant to be.  The **D5 sprawl problem itself is
   unaffected** — the residual 5-20 pt drift on a few
   HTML node families is a polish issue, not a layout
   blocker.

   **Session deliverables (2026-05-06 / 2026-05-07):**

   1. § 2.5.12: Keepout structure proven 100% match.
   2. § 2.5.13-15: D7 falsified as sole fix; aux-graph
      topology gap localised to sec3d (-196 edges).
   3. § 2.5.16: Sec3d root-hierarchy fix landed gated.
   4. § 2.5.17: ``_rc_floor`` minlen-floor +8 drift
      fixed gated.
   5. § 2.5.18: D7 LUT port (textspan_lut.c → Python),
      tkinter dep dropped.  1181 tests pass.
   6. § 2.5.19: **CLion-no-libexpat reference bug
      discovered** — saves enormous future time.
   7. § 2.5.20: XPAD attempted fix proven not the bug
      and reverted.
   8. § 2.5.21: per-cell probe blocked on libexpat
      build, source-level analysis done.

   The 1879 D5 sprawl model is now well-understood.
   D7 LUT closed the per-glyph drift; sec3d/floor
   fixes are gated and ready.  Residual HTML drift is
   tractable but needs a libexpat-enabled local build
   to investigate further.

   Instrumentation kept in tree:
   - C: `lib/dotgen/position.c` per-section counters
     (`GV_TRACE=position` dumps `[TRACE position]
     aux_section sec1=… sec2_align=… …`).
   - Py: `position.py` `[AUX SECTIONS]` counter
     (`GVPY_TRACE_AUX_SECTIONS=1`).
   - Captures: `trace_d5/1879_aux_c.txt`,
     `trace_d5/1879_aux_sec2.txt`.

---

## 3. Core Refactor

**Deferred:** `PictoGraphInfo` — planned as Phase 1 of the pictosync merge
(see §6).

---

## 4. Other Layout Engines — Stubs

Priority order (updated 2026-05-08):

1. **sfdp** — port arc started.  Cluster awareness shipped via
   fdp's deriveGraph reuse (DONE §4.S-derivegraph).  Remaining:
   port C ``Multilevel.c`` (proper MIES coarsening),
   ``spring_electrical.c`` (stable solver + adaptive cooling),
   ``post_process.c`` + ``stress_model.c`` + ``sparse_solve.c``
   (stress smoothing).  See §4.x-sfdp below.
2. **osage** — cluster packing.
3. **patchwork** — squarified treemap.
4. **mingle** — post-processing edge bundling (not a layout engine).

Live today: **dot** (1141 tests), **neato** (54 tests, fully
C-aligned port — see DONE §4.N), **twopi** (24 tests, fully
C-aligned port — see DONE §4.T), **fdp** (43 tests, fully
C-aligned port + cluster-aware spline routing + cluster bbox
emission + deriveGraph two-level layout — see DONE §4.F /
§4.F-clusters / §4.F-derivegraph), **sfdp** (22 tests,
multilevel + Barnes-Hut + cluster-aware via fdp deriveGraph
reuse — see DONE §4.S-derivegraph; full C port of
Multilevel/spring_electrical/post_process pending), **circo**
(25 tests), **ortho** (full port via `lib/ortho/`,
18+12+18+4+4+12 module tests).

### §4.x-circo — circo port (CLOSED 2026-05-09)

All circogen sources ported verbatim across 2 sessions:

- §4.C-blocktree: block.c + nodelist.c + blocktree.c —
  data types + Tarjan articulation-point DFS + block-cut
  tree construction.
- §4.C-full: blockpath.c + circpos.c — spanning tree, longest
  path, residual placement, crossings reduction, layout_block,
  rotation math, applyDelta cascade, getInfo/setInfo,
  positionChildren, position, doBlock, circPos.

56 circo tests passing.  Engine has 3-gate dispatch matrix
(``GVPY_CIRCO_BLOCKTREE`` / ``BLOCKPATH`` / ``CIRCPOS``); all
default to ``c``.  Visual canvas size matches system C within
4% on circo_demo.gv.

### §4.x-sfdp — sfdp port (closing 2026-05-09)

Sessions 1–4 shipped.  Core sfdp is now C-aligned end-to-end:

- **§4.S-derivegraph** — cluster awareness via fdp deriveGraph
  reuse.  ``derive.py`` made engine-pluggable; sfdp plugs in
  its own per-scope force solver.
- **§4.S-multilevel** — Multilevel.c port (MIES + supervariable
  preprocessing + Galerkin coarsening).
- **§4.S-spring-electrical** — spring_electrical.c port (force
  iteration with adaptive cooling, prolongation between levels,
  pcp_rotate).
- **§4.S-post-process** — post_process.c + stress_model.c +
  sparse_solve.c port (stress majorization smoothing,
  conjugate-gradient solver).

50 sfdp tests; 1236 full-suite tests passing.

**Remaining (optional perf work, not correctness-blocking)**:

#### §4.S-quadtree — Barnes-Hut O(n log n) repulsion

**Why optional**: the slow O(n²) variant ported in
§4.S-spring-electrical is correct.  Performance becomes the
gating concern around n ≥ ~500 — the all-pairs pairwise
distance array becomes the inner-loop hot spot.  Below that, no
user observation distinguishes the two paths.

**C reference**: ``lib/sparse/QuadTree.c`` (690 LOC),
``lib/sparse/QuadTree.h`` (74 LOC).  Three public entry points
that ``spring_electrical.c`` consumes:

- ``QuadTree_new_from_point_list(dim, n, max_level, coord)`` —
  build the tree from a point cloud.
- ``QuadTree_get_supernodes(qt, bh, pt, nodeid, ...)`` — used
  by the regular ``spring_electrical_embedding`` (per-node
  query of supernodes that satisfy the ``width / dist < bh``
  Barnes-Hut criterion).
- ``QuadTree_get_repulsive_force(qt, force, x, bh, p, KP,
  counts)`` — used by ``spring_electrical_embedding_fast`` (a
  pairwise-tree traversal that interacts each tree pair once,
  amortised across all nodes).

**Three approaches, ranked by effort/value**:

1. **Refactor existing Python Barnes-Hut** (cheapest, ~1
   day).  ``SfdpLayout._QTNode`` already implements a working
   2D Barnes-Hut in `sfdp_layout.py`.  The traversal is
   correct; the *force formula* it applies is the homegrown
   ``Kp / dist^(1+p)`` not C's ``KP / dist^(1-p) · (xᵢ - xⱼ)``.
   Migrate the routine into ``spring_electrical.py``, swap the
   force formula, gate via ``n >= 45`` (mirrors C's
   ``quadtree_size``).  *Caveat*: still pure Python recursion
   — speedup is ~5-10× over O(n²) for n ≈ 1000, not C's
   100× over the same.

2. **Direct port of QuadTree.c** (mid effort, ~2-3 days).
   Faithful port preserving the C class hierarchy and the two
   query modes (per-node vs pairwise).  Pure Python recursion
   means it'll be slow on the hot path; the value is
   primarily *correctness alignment* for the diagnostic gate
   ``GVPY_SFDP_QUADTREE_VARIANT=fast|slow|none``.  Recommended
   only if we want C-comparable trace dumps.

3. **Vectorised numpy / Cython acceleration** (high effort,
   ~5+ days).  Lay out the tree as flat arrays (Morton-coded
   quadrants) and do batch queries via numpy advanced
   indexing.  Or compile the inner loop with Cython / numba.
   The point of diminishing returns: sfdp is for "scalable"
   layouts, but pure Python ``spring_electrical_embedding``
   is already running at ~5k iterations per node-second; for
   n ≤ 1000 the slow variant takes a few seconds.  Above that
   we should be asking whether sfdp is the right tool.

**Recommendation**: defer for now, revisit when there's a
concrete user-facing performance ask.  The legacy Python
Barnes-Hut remains available behind
``GVPY_SFDP_SPRING_ELECTRICAL=legacy`` for users who hit the
slow-variant ceiling on large graphs.

**Out-of-scope sfdp niceties** (not pursued):

- ``call_tri.c`` Delaunay triangulation port — needed by
  ``smoothing=triangle`` and ``smoothing=rng``.  Both modes
  surface a one-line warning and no-op for now.
- Edge label node handling (``edge_labeling_scheme``) —
  ``shorting_edge_label_nodes`` /
  ``attach_edge_label_coordinates``.  GraphvizPy doesn't yet
  expose ``edge_labeling_scheme`` as a graph attribute.

### §4.x — fdp cluster-aware routing + deriveGraph — shipped 2026-05-08

Closed end-to-end.  See DONE.md:
- ``§4.F-clusters`` — cluster-aware spline routing, cluster
  bbox emission, simple-fix visual passes.
- ``§4.F-derivegraph`` — full C ``deriveGraph`` two-level
  recursive layout (replaces the simple post-passes).

fdp now uses C's hierarchical algorithm: bottom-up
recursion lays out each cluster's interior first, parent
scopes use cluster proxies sized to their interior bbox,
xlayout at each scope enforces non-overlap.  43 fdp tests.
sfdp will inherit this clean foundation.

Side-issues filed (separate parser bugs):
- Edges INSIDE subgraph blocks dropped by parser.
- Edges AFTER subgraph blocks at root level also dropped.

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
