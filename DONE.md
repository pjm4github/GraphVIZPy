# DONE — GraphvizPy work log

Archive of shipped work pulled out of `TODO.md` to keep the live roadmap
short.  Ordered newest → oldest.

---

## §1.5.54–56 — Splines-level cluster-detour follow-ups — 2026-04-27

Three splines/channel-routing-level passes after §1.5.53 closed
1879.dot.  Constraint: only spline-routing code, no mincross /
position changes.

**§1.5.54 — Corpus rerun, picked next-largest divergence.**  After
§1.5.53 the `Δ_py − c` totals across the regression corpus were
1879=96, 2796=20, 1332_ref=17, 1472=13, aa1332=5, 1213-1=3,
1436=3, 2183=3, 1213-2=2, d5_regression=0.  Selected 2796.dot
(rankdir=LR, 59 nodes, 91 edges, 43 clusters) as the next target
since 1879's residual is dominated by HTML-IMG fallback noise.

**§1.5.55 — flat-edge cluster-detour reshape** (commit `7964b12`).
`reshape_around_clusters` was wired into `regular_edge.py` only;
flat-edge variants in `flat_edge.py` skipped it, leaving any flat
edge whose corridor straddled a non-member cluster un-detoured.
Added the reshape call at three sites in `flat_edge.py` (between
`routesplines/routepolylines` and `clip_and_install`).  Result:
2796 20→14, 1472 13→3, 1213-1 3→1, 1213-2 2→0.

**§1.5.56 — Self-edge direction picker + anchor projection.**
Two complementary follow-ups in `cluster_detour.py` and
`self_edge.py`:

*(a) Self-loop direction picker* (`_pick_self_loop_direction`).
`make_self_edge` defaults to a right-side loop when no port is
specified.  On 2796.dot three self-loops (`2->2`, `30->30`,
`43->43`) had a non-member cluster sitting inside the right-loop
bbox.  Reshape can't fix it because all 7 polyline points are
inside the cluster.  Fix: when port-free, score each direction's
candidate loop bbox against non-member cluster bboxes, pick the
direction with fewest overlaps.  Result on 2796: 14→11.

*(b) Interior anchor projection* (`_project_interior_anchors_outside`).
`routesplines` builds cubic bezier anchors that can fall straight
into a non-member cluster's bbox; the via-insertion loop can't
detour because both endpoints of the offending segment are inside.
Pre-pass: for each interior anchor (endpoints stay pinned to node
ports), if it lies inside any non-member cluster, project it onto
the nearest outside wall plus `_DETOUR_MARGIN`.  Bounded by 8
iterations per anchor for pinball cases.  Result on 2796: 11→9;
also 1213-1 1→0, 1332_ref 17→16, aa1332 5→3.

Also added a polyline-aware reshape variant
(`reshape_polyline_around_clusters`) for self-loop pts which is a
7-point CORNER POLYLINE rather than a Graphviz cubic bezier — the
bezier-aware variant misses anchor-on-vertex crossings.  Used as
defense-in-depth even though direction picking covers the bulk.

**Cumulative result across the regression corpus**:

| File | post §1.5.53 | post §1.5.55 | post §1.5.56 |
|---|---:|---:|---:|
| 1213-1.dot | 3 | 1 | **0** |
| 1213-2.dot | 2 | 0 | **0** |
| 1332_ref.dot | 17 | 17 | **16** |
| 1436.dot | 3 | 3 | 3 |
| 1472.dot | 13 | 3 | 3 |
| 1879.dot | 96 | 96 | 96 |
| 2183.dot | 3 | 3 | 3 |
| 2796.dot | 20 | 14 | **9** |
| aa1332.dot | 5 | 5 | **3** |
| **Total** | **162** | **142** | **133** |

1141 main tests pass (1 pre-existing parser test failure
unrelated).  Residual on 2796 (9 crossings) and 1879 (96 crossings,
HTML-IMG fallback compat) needs D5/D6 layout-level work, not
splines-level patches.

---

## §1.5.51–53 — Position-phase overlap audit + fixes — 2026-04-27

Built `trace_d5/_position_compare.py` overlap audit harness and
closed three position-phase bugs on 1879.dot.

**§1.5.51 — Overlap audit harness** (commit `9624dab`).  Compares
1879.dot's C and Py SVG outputs at the position-phase level
(post-mincross, post-coordinate-assignment).  Three measures:

1. Structural — rank-bucket count, per-rank node populations,
   per-rank Y-gap ratio (Py/C).  On 1879: both engines emit 9
   rank buckets; average gap ratio 1.67× (Py inflates due to
   HTML-table rendering; C doesn't render `<TABLE>`).
2. Per-engine overlap audit — counts node-node, cluster-NON-
   member-node, and cluster-cluster sibling overlaps separately.
   C is the reference; Py overlaps that exceed C's count flag
   real positioning bugs vs HTML-inflation noise.
3. Side-by-side summary table.

Bbox extraction handles `<rect>`/`<ellipse>`/`<polygon>`/`<image>`/
`<text>` (C's HTML-label nodes render as `<image>` + `<text>`,
not `<rect>`).  Depth-balanced `<g>...</g>` matching for C's nested
`a_nodeN` wrappers.

**§1.5.52 — Stack nodes pushed past same cluster boundary**
(commit `25bf6e8`).  `post_rankdir_keepout` pushed each node
independently to the boundary of overlapping non-member clusters.
Multiple sibling nodes whose NS-positioned X all fell inside the
same cluster bbox got pushed to the SAME boundary X — collapsing
onto each other.  On 1879.dot rank 5: NS placed sibling leaves
of `couple_330x331` distinctly (`node_420_420` x=4303,
`node_390_390` x=4450), but both fell inside `cluster_52x715`'s
bbox (4244-4741) and got pushed past `cluster_74x75`'s right edge
to `x = 4222 + gap + hw = 4294.66` — exact-bbox duplicates in
the SVG.  Fix: track `_exit_slot[(cluster_name, side)]` =
next-available boundary X.  When pushing a node past a cluster
face, place it at the slot's current target and bump the slot
by `node_width + nodesep` so subsequent nodes stack rather than
collide.

**§1.5.53 — Final per-rank separation pass after keepout**
(commit `d9b5cef`).  `post_rankdir_keepout` pushes nodes out of
non-member cluster bboxes but doesn't enforce inter-node spacing
among the pushed nodes.  Pairs of orphan rank-N siblings whose
NS positions fell inside the same sibling cluster got pushed by
DIFFERENT clusters and landed in the same region.  Fix: after
`post_rankdir_keepout` + `post_resolve_align`, walk each rank
in cross-rank order; for any pair of consecutive nodes overlapping
or closer than `nodesep`, bump the right node so its left edge
sits `nodesep` past the prior's right edge.

**Cumulative result on 1879.dot**:

| measure | baseline | post §1.5.53 |
|---|---|---|
| Exact-bbox dup groups | 3 (6 nodes) | **0** ✓ |
| Node-node overlaps | 123 | **24** (within 2 of C's 22) |
| Cluster-non-member | 37 | **10** (vs C's 0) |
| Cluster-cluster sibling | 0 | 0 ✓ |
| 1879 default crossings | 100 | 96 (-4) |

Broader corpus default-path crossings: 1213-1 4→3, 1213-2 unchanged,
1472 14→13, 2796 22→20, aa1332 unchanged, 2239 0→1.  1141 main
tests pass; d5_regression yellow warning unchanged.

---

## §1.5.40–50 — Mincross + remincross fully aligned with C on 1879.dot — 2026-04-26 → 2026-04-27

Cumulative chain that achieved **100% pass-by-pass match
(10326/10326 entries across all 25 mincross + remincross passes)**
on 1879.dot.  Built on §1.5.21–39's build_ranks-source-pick
closure.

**§1.5.40 — Investigated downstream divergence post-build_ranks.**
First-reorder match was 100% but pass-1+ diverged.  Identified the
chain below.

**§1.5.42 — Post-build_ranks transpose** (mirrors C
`mincross.c:1700-1701`).  C's `build_ranks` calls
`transpose(g, false)` if `ncross() > 0` — so the input C feeds
into mincross is already locally optimised, not pure BFS output.
Without this, Py's pure-BFS rank arrays carried into mincross
with different crossing patterns, and downstream median/reorder
decisions diverged.

**§1.5.43 — Iterate edges by tail node in `layout.graph.nodes`
order** (mirrors C `class2.c` `agfstnode → agfstout`).  Was
walking raw DOT-edge-line order; for clusters with multiple
member nodes, edges interleave by DOT line.  C's by-node walk
aggregates each member's edges as a block.

**§1.5.44 — Substitute hidden cluster-member ends with their
proxies AT THE ORIGINAL EDGE'S POSITION in `layout.ledges`**.
Real edges with hidden heads (cluster members) were filtered
out; the chain edge `t → cluster_proxy` got appended LAST in
out_adj.  C's `class2` inserts the chain head in `agfstout`'s
iteration position.  With seen_pairs dedup, substituted
(early-position) entry now wins over late-position chain edge.

**§1.5.45 — Skeleton cluster proxies trigger sawclust.**
Mapped `_skel_<cluster>_<rank>` keys back to their cluster name
in `node_cl` so `cluster_reorder`'s sawclust check fires for
skeleton cluster proxies — matches C's `ND_clust(*rp)` at
`mincross.c:1493-1503`.

**§1.5.46 — Bottom-up build_ranks(pass=1).**  C's
`mincross.c:1617 build_ranks(g, pass)` has TWO modes selected
by `pass`: pass=0 sources are no-in-edges (DAG roots), BFS walks
out-edges (top-down); pass=1 sources are no-out-edges (DAG sinks),
BFS walks in-edges (bottom-up).  C calls both at outer pass=0
and outer pass=1; Py implemented only pass=0.  Added `pass_idx`
parameter and called pass=1 at outer pass_n=1 boundary in
`_multi_pass_loop`.  Kept `_skeleton_post_build_transpose` alive
across `_run_mincross` so the pass=1 BFS output also gets the
post-build transpose.

**§1.5.47 — Transpose candidate flags fire on tie-break swaps.**
C's `transpose_step` returns `int64_t` delta; tie-break swaps
where `c_before == c_after` contribute 0 to delta but still set
the rank's candidate flag (`mincross.c:991`).  Py's
`transpose_all_ranks` was keying candidate-propagation on `d > 0`,
so tie-break swaps got lost — cluster proxies got stuck early in
their bounce sequence past runs of fixed (-1) nodes.  Fixed by
tracking `swap_count` (incl. tie-break) and stashing on
`layout._last_transpose_swap_count`; outer loop still terminates
on `delta < 1` so tie-break-only sweeps don't oscillate.

**§1.5.48 — Remincross sawclust + mark_lowclusters.**  Two-part
fix: (a) sawclust fires only on virtual cluster proxies during
cluster expand-mincross (real members can swap within the
cluster); (b) populate `node_cl` with EVERY node during
`remincross_full` (mirrors C's `mark_lowclusters` at
`cluster.c:433` called before ReMincross), and gate sawclust on
`(rn_virt OR remincross_phase)` so reorder is a near-no-op in
ReMincross matching C's "transpose-only" semantics.  C's
ReMincross emits 0 reorder_cmp events at rank=4 pass 16; Py was
emitting 6860.

**§1.5.49 — Sort cluster interior by external in-edge median at
expand-splice.**  C's `mincross_clust(g)` calls `expand_cluster`
+ `mincross(g, 2)` per cluster.  The per-cluster mincross runs
medians using `ND_in/ND_out` which include EXTERNAL edges,
sorting interior by external position.  Py's expand-mincross loop
gated to `len(cl_ranks) >= 2` skipped single-rank clusters
(1879's 3-member family-tree clusters — `cluster_20x21`,
`cluster_7499x7500`, `cluster_622x627`, `cluster_630x633`,
`cluster_6x7`).  Fix: at the splice step, compute external
in-edge median for each member from `layout.ranks[r-1]`, sort
unfixed positions by mval ascending while leaving -1 fixed
positions in place.  Hidden in-edge tails substituted with their
cluster's currently-active proxy at the tail's rank.

**§1.5.50 — Fix cl_node_set leak in expand-splice sort.**
§1.5.49's sort used the wrong variable for the intra-cluster
filter — `cl_node_set` is assigned at line ~1582 (post-expansion
mincross block) and PERSISTS across iterations of the `for cl_name
in cluster_dfs_order` loop.  At the splice step (lines 1420-1450),
`cl_node_set` therefore referred to the PREVIOUS cluster's
members.  On `cluster_7499x7500`'s expand: `cl_node_set` contained
`cluster_7504x7505`'s members from the prior iteration; the
intra-cluster check `if t in cl_node_set: continue` falsely
skipped the legitimate external edge `couple_7504x7505 →
node_7499x7500_7499`.  Fix: use `cl_member_set` (= `node_sets[cl_name]`)
which IS the current cluster's members.

**Cumulative result on 1879.dot**:

| measure | result |
|---|---|
| First-reorder match (top-level events) | **100% (353/353 across 9 ranks)** ✓ |
| Pass-by-pass match (top-level events, 25 passes) | **100% (10326/10326)** ✓ |
| Default-path cluster crossings | 106 → 100 (-6) |
| Skeleton-path cluster crossings | 133 → 115 (-18) |

`couple_630x633` + children spread drops 17× (6950pt → 400pt
range).  d5_regression yellow warning (2 vs baseline 1) tracked
under §1.5.41+ chain.

Commits: `dd3037c` (§1.5.45), `99516eb` (§1.5.46), `f854f80`
(§1.5.47), `c2d8b97`/`67ed916` (§1.5.48), `ccc7431` (§1.5.49),
`3afbfbe` (§1.5.50), plus several earlier commits for §1.5.40-44.

Four analysis helpers under `trace_d5/`: `_event_categories.py`,
`_pass_compare.py`, `_compare_table.py`, `_per_rank_diverge.py`,
`_position_compare.py`.

Channels: `[TRACE d5_step]`, `[TRACE d5_edges]`, `[TRACE bfs]`,
`[TRACE skeleton_nlist]`, `[TRACE nd_out_emit]`, `[TRACE gd_clust]`,
`[TRACE nd_in_emit]` — both engines.

---

## §1.5.21–39 — D5 build_ranks closure on 1879.dot — 2026-04-25 → 2026-04-26

Investigated and **closed** 1879.dot's parent-vs-children placement
gap at the build_ranks level.  Root cause traced to `build_ranks()`
divergence (rank-0 cluster ordering).  Fixes shipped in two layers.

**§1.5.21 — D5 baseline measurement.**  Identified 1879.dot's
mincross-output distance as the largest single divergence in the
corpus.  Established the comparison harness against C's traces.

**Build_ranks side**:

- **§1.5.22 — install_cluster recursion.**  Mirrors C's
  `install_cluster` which recursively installs all rank-leaders
  of a cluster (not just its top leader) when a cluster is the
  BFS source.

- **§1.5.23 — Rank-then-DOT source ordering.**  Walk
  `layout.graph.nodes` in DOT order, sorted by `lnodes[n].rank`,
  then by DOT index within rank — matching C's `agfstnode → agnxtnode`
  + cluster-leader prepending order.

- **§1.5.24/25 — Rank-internal source repositioning.**  Sources
  inside a rank get repositioned to the children-median X
  (iterated to convergence) so source nodes track their downstream
  neighbours rather than landing at left-end of rank.

**Mincross side**:

- **§1.5.27 — C-faithful 3-pass loop.**  Replaced legacy
  multi-pass loop with C's outer-3 + MinQuit/Convergence early-stop.

- **§1.5.29 — Cross-rank transpose with candidate flags.**
  Mirrors `mincross.c:1006-1021` candidate-flag propagation.
  Adds reverse tie-break (`c0 > 0 && reverse && c1 == c0`).
  Adds `flat_mval`/`hasfixed` semantics.

- **§1.5.30 — CL_CROSS guard for weighted ties.**  Restrict
  reverse-tie-break swap to unweighted ties (`c_before <
  CL_CROSS=1000`); avoids over-firing on virtual edges where Py
  weight bookkeeping diverges from C's.

- **§1.5.31 — Per-pass restart from build_ranks snapshot.**
  Mirrors C's pass=0/1 `build_ranks` re-call at
  `mincross.c:1086-1095`.

- **§1.5.33 — Removed redundant remincross loop.**  Was
  triple-counting iterations (skeleton mincross hit 48 iters vs
  C's 16 on 1879.dot).

**Architectural deep-dive — build_ranks_on_skeleton (gated behind
`GVPY_SKELETON_BUILD_RANKS=1`)**:

- **§1.5.34–39** — added `build_ranks_on_skeleton` operating on
  post-class2 skeleton + DFS pre-order through out + in edges +
  ND_in tail-DOT-sort, mirroring C's `decompose()` exactly.
  Closed via 5-channel C instrumentation: `[TRACE skeleton_nlist]`,
  `[TRACE nd_out_emit]`, `[TRACE gd_clust]`, `[TRACE nd_in_emit]`,
  `[TRACE bfs]`.

**Result**: all **42 BFS source picks on 1879 now match C exactly
by name AND iter_order index** (28, 29, 30, 32, ..., 352).
d5_regression baseline matched C exactly (1 cluster crossing).
1879.dot `couple_630x633` + children spread dropped 17× (6950pt
→ 400pt range).

---

## §1.5.11–20 — D5 mincross scope correctness + parser semantics — 2026-04-22 → 2026-04-24

Twenty session deep-dive on the D5 cluster-straddle divergence,
documented in detail at [Docs/D5_measurement_findings.md](Docs/D5_measurement_findings.md).
Architecture is now byte-true with C's mincross at the function
level; output drift on ~12 corpus graphs remains.

**Mincross scope alignment** (commits `5be9f98`, `4b6b147`):
- **Port-propagation for substituted edges** — when ``mc_fg_out``
  collapses an edge (t, h) → (t_sub, h_sub) via ``_skel_sub``, the
  original edge's port identifier survives onto the substituted-pair
  key.  Without this, ``c4051:Out0 → c4237`` lost its 128-pt port
  offset and the rank-6 median for ``clusterc4237_6`` dropped from
  1088 → 1024, stranding reorder in a tied-pair cycle.
- **Exit-edge filter relaxed** — boundary edges one rank outside the
  cluster's range now survive ``mc_fg_out`` filtering, matching C's
  ``ND_out`` which keeps exit edges (was missing
  ``clusterc6408@r18 → clusterc6410@r19`` style edges on aa1332's
  cluster_6409).
- **Scoped pair-crossing counter** — ``count_scoped_pair_crossings``
  ports C's ``in_cross``/``out_cross`` exactly, including the
  ``ED_xpenalty(e1) * ED_xpenalty(e2)`` weighting.
- **Self-skeleton + foreign-skeleton exclusion** — a cluster's own
  ``_skel_<cl>_<r>`` chain edges from the prior collapse are filtered
  out of its expand scope; sibling clusters' skeletons don't pollute
  the scope either.
- **Scoped ``_skel_sub``** — substitutes real → skeleton only when
  the hider is a direct child of the currently-expanding cluster
  (was substituting through any ancestor).
- **Cached output views** — ``_output_nodes_list`` /
  ``_output_nodes_dict`` / ``_output_edges`` computed once after
  phase 3; nine post-layout helpers stop re-filtering ``lnodes`` /
  ``ledges`` on each call.
- **fg_out forwarding to ``cluster_transpose``** — ``run_mincross``
  and ``remincross_full`` previously called the inner pair cost
  with ``count_crossings_for_pair`` (O(E) per pair).  Forwarded the
  already-built fast graph so the inner cost uses
  ``count_scoped_pair_crossings`` (O(degree)).  2620.dot:
  58.7s → 23.2s (2.5× speedup), no longer hits 60s timeout.
- **Class-level mutable dicts → ``__init__``** — ``_node_mval``
  and ``_port_order_cache`` were shared across all ``DotGraphInfo``
  instances.  Latent memory-leak / port-collision risk in
  long-lived processes.

**Weighted crossing count** (commit `4b6b147`):
- ``LayoutEdge.xpenalty`` field (default 1, ``CL_CROSS=100`` for
  skeleton chain edges).  ``in_cross``/``out_cross`` now count
  ``xpenalty(e1) * xpenalty(e2)`` per crossing — a real edge
  crossing a cluster skeleton costs 100 vs 1 for a real-vs-real
  crossing.  Mechanism that makes mincross push real edges around
  non-member clusters.  1332.dot 3 → 1.

**Declared-vs-referenced parser semantics** (commit `9fbda7b`):
- ``Graph.add_node(declared: bool = True)`` — when False, ensure the
  node exists (creating in root if missing) but skip
  ``self.nodes[name] = node``.  Matches C cgraph's agedge ⇒
  agsubnode-without-membership semantics.
- Visitor ``_resolve_node_id`` and ``Graph.add_edge`` use
  ``declared=False`` for edge endpoints.  ``clusterc4051.nodes``
  now correctly contains ``c4051``; cluster_4250 no longer
  spuriously claims it via the edge reference.
- 4 regression tests in ``tests/test_declared_vs_referenced.py``.
- Two tuning attempts (wide / narrow neighbour augmentation) both
  produced corpus regressions and were reverted.  +5 net corpus
  delta accepted as the cost of correctness.

**Diagnostic infrastructure**:
- ``[TRACE d5_step]`` / ``[TRACE d5_edges]`` / ``[TRACE d5_icv]``
  channels on both engines, line-format-matched for diff tooling.
- ``test_data/d5_regression.dot`` regression fixture (4 cases:
  RL-flip, thread-through, multi-rank thread, nested interclrep).
- ``tests/test_d5_regression.py`` baseline gate.

**Tests**: 1141 passing.  Visual audit corpus: 162 / 197 graphs clean
on both sides (was 161); ~12 graphs with Python > C residuals totaling
~177 crossings (vs 224 baseline).

## 2026-04-22 — HTML labels Phase 4+ PORT + mixed-content pass

Shipped ``test_data/html_port_mixed.dot`` +
``tests/test_html_port_mixed.py`` (21 cases).

- **Mixed text + nested table in one cell** — ``TableCell.blocks``
  is now an ordered list of ``HtmlLine`` / ``HtmlTable`` /
  ``HtmlImage`` fragments.  When a cell mixes content kinds the
  sizer and renderer iterate the list, stacking blocks top-aligned.
  Contiguous text lines fold into a single paragraph fragment so
  BR / BALIGN still work.  Simple cells (text-only / table-only /
  image-only) keep their existing code paths via ``_cell_is_mixed``.
- **PORT="…" on TD / TABLE** — parser captures PORT on both
  elements; sizer fills in cell geometry as before.  Layout stashes
  the sized ``HtmlTable`` on ``Node.html_table`` so mincross's
  port-order hook calls ``html_port_fraction`` with the same
  compass-angle convention as records.  Edges written as
  ``node:port`` resolve to the ported cell's centre during ordering.

## 2026-04-21 — HTML labels Phase 4+ spec-completeness

Three back-to-back passes that closed most of the Phase 4+
follow-up list.

**Quick-wins pass** — ``test_data/html_style.dot`` +
``tests/test_html_style.py`` (34 cases):
- ``STYLE="rounded"`` and ``STYLE="radial"`` on tables/cells.
  Rounded emits ``rx="4" ry="4"`` on the rect; radial + BGCOLOR
  emits a ``<radialGradient>`` in a module-level ``<defs>`` block.
  Single-colour radial fades to white; colour-pair BGCOLOR
  (``c1:c2``) produces either radial or linear depending on STYLE.
- ``GRADIENTANGLE=…`` — linear gradients honour the angle (CCW
  from +x), falling back to a default horizontal gradient when unset.
- ``SIDES="LTRB"`` on TD — when ``SIDES`` is a non-``LTRB`` subset
  the renderer emits a stroke-less fill rect plus individual
  ``<line>`` segments for each present side.  Empty ``SIDES=""``
  falls back to the default (full rect).
- ``ALIGN="TEXT"`` and BALIGN — parser propagates ``BALIGN`` into
  the default alignment assigned to new lines created inside the
  cell; explicit ``<BR ALIGN=…/>`` overrides.  Rendering resolves
  per-line alignment, falling back to ``cell.align`` only when the
  line's own alignment is ``center``.  ``ALIGN="TEXT"`` parses as
  a recognised cell-alignment token and renders like ``CENTER`` at
  the block level while preserving per-line alignment.
- ``<HR/>`` inside cells — parser emits ``HtmlLine(is_hr=True)``;
  sizer adds its stored height to the cell content; the renderer
  emits a horizontal ``<line>`` spanning the cell's inner width.

**Spec-completeness pass** — ``test_data/html_spec.dot`` +
``tests/test_html_spec.py`` (36 cases):
- ``<O>`` renders as overline (was incorrectly underline).
- ``<VR/>`` between cells plus ``<HR/>`` between rows.
- ``ROWS="*"`` / ``COLUMNS="*"`` on TABLE.
- ``WIDTH`` / ``HEIGHT`` / ``FIXEDSIZE`` on TABLE+TD.
- ``SIDES`` on TABLE (outer partial borders).
- ``ALIGN="TEXT"`` on TD preserves per-line alignment.
- COLSPAN / ROWSPAN extra-width distribution proportional to
  existing column widths (narrow columns stay narrow); falls back
  to even split when every spanned column / row has width 0.

**IMG + hyperlink-attribute pass** —
``test_data/html_img_link.dot`` (with
``test_data/test_img.png`` auto-generated by the test session
fixture) + ``tests/test_html_img_link.py`` (32 cases):
- ``<IMG SRC SCALE/>`` inside TDs — ``HtmlImage`` AST node + parser
  handler.  Image dimensions probed via stdlib ``struct`` from PNG
  IHDR / JPEG SOF / GIF LSD headers (no Pillow dependency).  SCALE
  modes map onto SVG ``<image>`` + ``preserveAspectRatio``: FALSE
  (natural, centred), TRUE (fit with aspect), BOTH (stretch,
  ``preserveAspectRatio="none"``), WIDTH (fill width, proportional
  height), HEIGHT (dual).  Deferred: remote URL src, SVG file size
  probe.
- HREF / TARGET / TITLE / TOOLTIP / ID on TABLE and TD wrap the
  rendered output in ``<a xlink:href>`` + ``<title>`` + ``<g id="…">``.

## 2026-04-20 — Ortho port + dot-engine performance triage

**Ortho engine — full port of `lib/ortho/` shipped** (option 1, top-down
port, ~3930 Python lines).  Module structure mirrors C: `rawgraph.py`,
`fpq.py`, `sgraph.py`, `trapezoid.py` (Seidel), `partition.py`,
`maze.py`, `ortho.py` orchestration.  Plus a GraphvizPy-specific
cluster-avoidance layer (~100 lines in `ortho.py` + new
`Sedge.base_weight` field) that bumps sedge weights by 1,000,000 on
cells inside non-member clusters; Dijkstra prefers paths skirting them.

| Phase | Module | Tests |
|---|---|---:|
| 0 | Scaffolding + `structures.py` + stub `ortho_edges` | — |
| 1 | `rawgraph.py` | 18 |
| 2 | `fpq.py` + `sgraph.py` | 18 |
| 3 | `trapezoid.py` (Seidel) | 4 byte-match-vs-C |
| 4 | `partition.py` | 4 byte-match-vs-C |
| 5 | `maze.py` | 12 structural |
| 6 | `ortho.py` orchestration | end-to-end on 17 fixtures |
| 7a | Resilience fixes (None-guards, channel-gap tolerance, zero-length angle) | — |
| 7b | Cluster avoidance (overlap-based cell flagging + per-edge weight bump) | — |
| 7 | Dispatch restructure + `GVPY_ORTHO_V2` flag | — |
| 8 | Flag flip — V2 default | opt-out: `GVPY_ORTHO_LEGACY=1` for two release cycles |

Result: 2620.dot 66 → 3 crossings (well under the ≤9 success bar);
other 16 ortho fixtures stay at 0; 892 tests pass.  Resolves D1.

The 3 remaining 2620.dot crossings are geometrically forced
(`digidialog`, `kalenderservice`, `loginportal` — originating outside
the clusters they cross, no non-crossing path in the current maze).

**`smode` straight-segment dispatch shipped** (D3 / §2.2) — post-hoc
flattening pass `flatten_straight_runs` in `regular_edge.py`.  Detects
x-aligned runs in the output bezier and replaces cubic control points
with linear interpolation.  Cosmetic effect matches C's smode on long
vertical chains (no more subtle wobble on straight runs).  Cluster-
safety guard skips runs where the straight chord would cut through a
non-member cluster bbox.

**Dot-engine timeout triage** — three O(V·E²)-class hot spots fixed
(commits `324455c`, `7dd6c1b`):

1. ``ortho/fpq._pq_check`` running on every heap op → gated behind
   ``GVPY_PQCHECK=1``.  80 % speedup on 2620.dot (76 s → 15 s);
   recovered 2 of 17 audit timeouts.
2. ``core/_graph_edges.add_edge`` + ``_graph_nodes.add_node``
   recomputing betweenness centrality per addition (dead write —
   no reader).  Parse of 2343.dot 180 s+ → 0.34 s.
3. ``dot/mincross.transpose_rank`` scanning ``layout.ledges``
   inside its pair-count inner loop → pre-compute rank-local
   adjacency cache once per call.  Phase 2 on 172-node 2343
   subset 55 s → 4 s (14×).
4. (follow-up) ``dot/mincross.order_by_weighted_median`` — same
   precompute pattern was missing.  On 2343.dot phase-2
   108 s → 13.5 s (8×); total runtime 369 s → 156 s.  Equivalence
   verified via ``GVPY_MINCROSS_CHECK`` trace — medians
   byte-identical to legacy.  Post-audit: 3 previously-timing-out
   graphs now measure (2470 → 19 cross, 2620 → 3 cross, 1879 → 251
   cross newly exposed).

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
