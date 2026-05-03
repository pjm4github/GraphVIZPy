# DONE — GraphvizPy work log

Archive of shipped work pulled out of `TODO.md` to keep the live roadmap
short.  Ordered newest → oldest.

---

## §4.T — Twopi engine C-alignment (full port) — 2026-05-02

End-to-end port of `lib/twopigen/` to a Py package mirroring the
C file structure.  Algorithm faithfully aligned with C's
`circle.c` (Emden Gansner's port of Graham Wills' GD'97 paper);
overlap removal and spline routing reuse the engine-agnostic
helpers shipped with the neato port.

**Package structure:**

| Py module | C source | Role |
|---|---|---|
| `twopi_layout.py` | `twopiinit.c` | Orchestrator + `LayoutNode` |
| `circle.py` | `circle.c` | Algorithm |

**Algorithmic alignment** (mirrors `circle.c` line-by-line):

- `init_layout` ↔ `initLayout` (74) — `s_leaf=0` for leaves, `INF`
  for interior; `s_center=INF`; `theta=UNSET`.
- `is_leaf` ↔ `isLeaf` (55) — at most one distinct neighbour
  (excluding self-loops).
- `set_n_steps_to_leaf` ↔ `setNStepsToLeaf` (34) — DFS from each
  leaf, propagate `s_leaf = min steps to any leaf`.
- `find_center_node` ↔ `findCenterNode` (96) — pick max `s_leaf`
  (most-interior node).  This is C-aligned and replaces the prior
  Py double-BFS eccentricity centre.  For balanced trees both
  give the same answer; for asymmetric graphs the SLEAF-based
  approach produces a more visually-balanced radial layout.
- `set_n_steps_to_center` ↔ `setNStepsToCenter` (117) — BFS from
  centre to assign `s_center` (radial level) and parent pointers.
- `set_parent_nodes` ↔ `setParentNodes` (147) — driver that returns
  the max `s_center` (radial depth) or `-1` on failure.
- `set_subtree_size` ↔ `setSubtreeSize` (172) — bottom-up: each
  leaf in the BFS tree increments its own `stsize` and walks up
  the parent chain incrementing each ancestor.
- `set_subtree_spans` / `set_child_subtree_spans` ↔ (210/184) —
  top-down: each child's span is `parent_span * child_stsize /
  parent_stsize`.
- `set_positions` / `set_child_positions` ↔ (246/220) — top-down:
  centre `theta=0`; each child's `theta` walks left-to-right from
  the parent's lower fan boundary.
- `get_ranksep_array` ↔ `getRankseps` (258) — cumulative ranksep
  array of length `max_rank + 1` from the colon-separated
  `ranksep` attribute.  Last delta repeats for additional rings.
- `set_absolute_pos` ↔ `setAbsolutePos` (289) — convert
  `(s_center, theta)` to `(x, y)`.
- `circle_layout` ↔ `circleLayout` (312) — top-level entry point
  for one connected component.

**Bug fix found in the prior Py implementation:**

The previous Py used `root_ln.theta = math.pi` as the centre's
seed angle; combined with `start_angle = theta - span/2 = 0` the
first child landed at theta = π/2.  C uses `theta = 0` for the
centre and gets the same first-child angle (π/2) via the same
arithmetic.  Algorithmically equivalent, but the C convention is
clearer (centre at 0 means children fan out around 0).

**Reuse of neato infrastructure:**

- `neato.adjust.remove_overlap` is engine-agnostic — only reads
  `layout.lnodes`, `layout.sep`, `layout.overlap`.  Twopi exposes
  the same fields and gets the full mode dispatcher (true/false/
  scale/scalexy/compress/voronoi/prism/ortho/portho/etc.) for free.
- `neato.splines.route_edges` is similarly engine-agnostic — sets
  `layout.edge_routes` from the `splines` graph attribute.
  Twopi inherits Bezier / polyline / line / none routing.
- Twopi's `_to_json` mirrors `NeatoLayout._to_json`: emits
  multi-point routes when `edge_routes` is populated, falls
  through to base 2-point straight lines otherwise.

**Tests:** 24/24 pass (10 new alignment tests covering centre
finding, leaf detection, subtree size, ranksep array
construction with default + explicit, splines bezier dispatch,
and overlap dispatcher routing).  Full suite 1132 pass, 4 skip.

Trace channel: `GVPY_TRACE_TWOPI=1` emits `[TRACE twopi]` lines.

---

## §4.N — Neato engine C-alignment (full port) — 2026-05-02

End-to-end port of `lib/neatogen/` to a Python package mirroring the
C file structure.  Started from a single 826-line `neato_layout.py`
that inlined all three modes; finished with a multi-module package
that's algorithmically C-aligned across all major modes, all
overlap-removal algorithms, smart-init, and edge spline routing.
9 commits, ~12-15 estimated days of work compressed into one
session via aggressive use of existing infrastructure (numpy,
scipy.spatial, the already-ported pathplan library).

**Phase N1 — package restructure.**  Convert
`gvpy/engines/layout/neato/` from one file (826 LOC) to a package
mirroring `lib/neatogen/`:

| Py module | C source |
|---|---|
| `neato_layout.py` | `neatoinit.c::neato_layout` (orchestrator only, 427 LOC) |
| `stress.py` | `stress.c`, `circuit.c` |
| `kkutils.py` | `stuff.c::solve_model` + `kkutils.c` |
| `sgd.py` | `sgd.c` |
| `bfs.py` / `dijkstra.py` | `bfs.c` / `dijkstra.c` (unit-conversion wrappers) |
| `adjust.py` | `adjust.c` + `constraint.c` (overlap modes) |
| `voronoi.py` | `adjust.c::vAdjust` (substitutes for ~1500 LOC of hand-rolled Voronoi) |
| `smart_ini.py` | `stress.c::sparse_stress_subspace_majorization_kD` (substitutes via PivotMDS) |
| `splines.py` | `neatosplines.c::spline_edges_` |

Engine-agnostic primitives moved to `common/`:

- `common/matrix.py` — Gauss-Jordan inverse + `gauss_solve`
  (`matinv.c`, `lu.c`, `solve.c`).
- `common/graph_dist.py` — BFS / Dijkstra APSP on adjacency dicts.
- `common/laplacian.py` — packed upper-tri Laplacian indexing +
  matrix-vector multiply (`matrix_ops.c::right_mult_with_vector_ff`).
- `common/conjgrad.py` — conjugate-gradient solver
  (`conjgrad.c::conjugate_gradient_mkernel`).
- `common/pivot_mds.py` — Brandes & Pich PivotMDS (substitute for
  C's HDE+PCA pipeline).

**Phase N2 — algorithmic alignment of the three modes.**

- **N2.1 MAJOR (stress majorization).**  Replaced the naive O(N²)
  per-iteration SMACOF direct update with a faithful port of
  `stress_majorization_kD_mkernel` (stress.c:795).  Per iteration:
  build the Laplacian L_Z(X) of weights `1/(d_ij × ||x_i-x_j||)`
  in packed upper-tri form; compute `b = L_Z @ X`; solve the
  constant Laplacian L_w (1/d_ij²) system `L_w X^new = b` per
  spatial dimension via conjugate gradient.  Stress is now
  monotonically non-increasing per the SMACOF guarantee.
  Sign-convention note: C uses negated Laplacians (off-diag +,
  diag -); this port uses proper Laplacians (off-diag -, diag +).
  Equivalent under sign flips of the stress formula; documented in
  `_iter_stress`.

- **N2.2 KK (Kamada-Kawai Newton).**  Ported `stuff.c::solve_model`
  + `diffeq_model` + `move_node` + `D2E` + `update_arrays` +
  `choose_node` + `total_e`.  Per-iteration force tensors,
  max-residual node selection, 2×2 Hessian Newton step via Gauss
  elimination, with C's `[Damping, Damping + 2(1-Damping)]` random
  scale, then incremental `update_arrays` to refresh the force
  tensor for the moved node and its neighbours.  Known KK
  pathology: from random init on symmetric graphs (triangle,
  Y-shape, K5) Newton lands on saddle points where ∇=0 but
  Hessian has negative eigenvalues — escape requires N2.4
  smart-init.

- **N2.3 SGD.**  Aligned three differences from the prior Py SGD:
  step cap `mu = min(eta * w, 1.0)` (sgd.c:221) — bounds per-term
  step at full distance to prevent flinging in early iterations;
  sign convention `dx = pos_i - pos_j`; formula
  `r = mu * (mag - d) / (2 * mag)` matching C exactly.  SGD now
  produces high-quality layouts where KK previously got stuck:
  Y-shape root-leaf 76.5 (analytical optimum 76.8 — within 0.4%);
  path-5 adjacent spans 72.8/73.2/73.2/73.0 (ratio 1.005).

- **N2.4 Smart-init.**  Shipped via PivotMDS (Brandes & Pich
  2007) — substitutes for C's full
  `sparse_stress_subspace_majorization_kD` pipeline.  Reaches the
  same goal at ~150 LOC instead of ~600+ LOC of faithful HDE +
  PCA + sparse-majorization port.  Uses `np.linalg.eigh` for the
  small-K eigendecomposition.  Y-shape + KK now hits the analytical
  optimum; K5 + SGD lands at the EXACT regular pentagon
  (long/short pair-distance ratio = 1.618 = golden ratio φ, the
  global optimum).

**Phase N3 — overlap removal (all 7 algorithms).**

- **N3.1 dispatcher.**  Mirrors `adjust.c::getAdjustMode`.  Maps
  `overlap=` attribute strings (true/false/scale/scalexy/voronoi/
  prism/compress/ortho/portho/etc.) to canonical mode constants.
  Bug fix: the previous Py had an inverted boolean check —
  `overlap=false` triggered the function but the function then
  returned immediately because of an inner short-circuit on the
  same string.  Net effect: overlap removal was NEVER run.  Now
  fixed.

- **N3.2 scale + scalexy.**  Initial port shipped iterative
  `sAdjust`/`rePos` (1.05× per iteration loop).  N3.4 upgraded
  these to the Marriott closed-form `scAdjust` (constraint.c:767)
  — single optimal scale via `computeScale` (max over overlap
  pairs of `min((wi/2+wj/2)/Δx, (hi/2+hj/2)/Δy)`) for uniform;
  and the `computeScaleXY` sort + DP with `(1, ∞)` sentinel for
  the minimum-area separate-axis solution.

- **N3.3 Voronoi.**  Faithful port of
  `adjust.c::vAdjust` (line 415) using `scipy.spatial.Voronoi` for
  the diagram itself instead of porting C's hand-rolled
  `delaunay.c` + `voronoi.c` + `site.c` + `hedges.c` + `heap.c` +
  `legal.c` (~1500 LOC).  Iteration loop matches C exactly:
  `rmEquality` to jitter coincident sites, fence sites at corners
  to bound all real cells, move overlapping nodes to area-weighted
  centroid via shoelace triangulation, `doAll` heuristic + bbox
  expansion when stuck.  Used for both AM_VOR and AM_PRISM (C uses
  real PRISM only when GTS is available).

- **N3.4 compress + ortho/portho family + vpsc/ipsep stubs.**
  - `compress_adjust` mirrors `compress` (constraint.c:629):
    when no overlap, find the largest s ≤ 1 that wouldn't cause
    touching, apply uniformly.  Refuses to compress through
    pre-existing overlap (returns 0, matches C).
  - `ortho_adjust` covers AM_ORTHO / AM_PORTHO with `*_yx`,
    `orthoxy`, `orthoyx`, `porthoxy`, `porthoyx` variants.
    Approximates `cAdjust` (constraint.c:538) via iterative
    pair-slide projection — less optimal than C's NS / QP
    constraint solve but produces non-overlapping output and
    preserves relative ordering on the chosen axis.
  - VPSC / IPSEP fall back to scale + warning.  Real handling
    needs the constrained-majorization QP solver; deferred
    indefinitely.

  Reference: Marriott, Stuckey, Tam, He, "Removing Node
  Overlapping in Graph Layout Using Constrained Optimization"
  (Constraints 8(2):143-172, 2003) — closed-form basis for
  scAdjust.

**Phase N4 — edge spline routing.**  Ship a working spline router
on top of the existing `gvpy.engines.layout.pathplan` infrastructure
(`Pobsopen` / `Pobspath` / `Pobsclose`).  Mirrors
`neatosplines.c::spline_edges_` (line 586): build axis-aligned
polygon obstacle per node, open visibility config, route each edge
via `Pobspath` from tail centre to head centre with POLYID hints,
clip first/last segments to node borders, then either keep polyline
or fit cubic Bezier via Schneider's recursive curve fit.  Self-loops
generate four-point arc above the node (simplified port of
`makeSelfArcs`).

`splines=` mapping:

| Value | Output |
|---|---|
| `true` / `spline` (default) | cubic Bezier |
| `polyline` | polyline avoiding bboxes |
| `line` | straight line |
| `false` / `none` | base 2-point edges |

Edge JSON output gains a `spline_type` field and `points` becomes
the multi-point control-point or vertex list.

Defensive fix in `pathplan/cvt.py::Pobspath`: bound the
back-pointer walk over the `dad` array to N+2 steps.  KK
saddle-collinear configurations produced inputs where `ptVis`
returned empty visibility for an endpoint inside an obstacle,
`makePath` set up a degenerate `dad` with a cycle, and the original
walk looped forever.  Now bails out to a straight-line fallback.

**Tests.**  Started at 27 functional tests (no-crash + basic
separation only).  Finished at 54 tests including 17 new
alignment tests covering: packed Laplacian indexing, `right_mult_packed`
matches dense, CG converges on a path Laplacian, SMACOF stress
monotonicity, Gauss-solve 2×2 + singular, KK diffeq invariants,
KK path-5 uniform spacing, SGD step cap, SGD Y-shape near-optimal,
smart-init Y-shape escape, smart-init K5 pentagon, PivotMDS smoke,
adjust dispatcher modes, Marriott scale exact factor, scalexy
horizontal-only, compress shrink + skip-on-overlap, ortho clear,
Voronoi grid clearance, polygon centroid, splines bezier /
polyline / line / none modes.

**Remaining open items** (deferred indefinitely): IPSEP / VPSC
need a constrained-majorization QP solver, narrowly used; not
worth pulling in `quad_prog_solve.c` infrastructure for the
small share of corpus inputs that use them.

Trace channel: `GVPY_TRACE_NEATO=1` emits `[TRACE neato_*]` lines
across `init`, `major`, `kk`, `sgd`, `adjust`, `voronoi`, and
`splines` phases.

---

## §2.5.7 / §2.5.10 / §2.5.11 — Skel-mode default + Phase B keepout-filter drop — 2026-05-02

Three shipped pieces from the §2.5 D5 alignment chain plus a recorded
failed attempt:

**§2.5.7 — Skel mode promoted to default (mincross.py:1272).**  The
``build_ranks_on_skeleton`` BFS-based rank rebuild after cluster
collapse is now the default — gate inverted from
``GVPY_SKELETON_BUILD_RANKS=1`` (opt-in) to
``GVPY_LEGACY_PHASE1_RANKS=1`` (opt-out).  Verified C-aligned:
1001/1001 BFS install events match between Py and C on 1879.dot;
mincross_exit ``final_crossings = 23`` matches C; 8/9 ranks land
bit-identical post-expand.  Corpus net -6 crossings vs prior default,
1141 tests pass.  ``test_d5_regression.BASELINE_VISIBLE_CROSSINGS``
bumped 1 → 3 (C reports 2; the new 3 is closer to C than the old 0
was).

**§2.5.10 — Phase B: drop ``any_cluster_members`` filter
(position.py:563-615).**  In §3f keepout (``ns_x_position``), removed
the historical ``ext not in any_cluster_members`` filter that was
masking an aa1332 ``cluster_6409`` 240pt-compaction bug.  Now mirrors
C's ``keepout_othernodes`` (lib/dotgen/position.c:443-475) which fires
keepout for any NORMAL or unrelated-virtual node — even ones inside
another cluster.  Gated behind ``GVPY_LEGACY_KEEPOUT_FILTER=1`` for
revert.

**Corpus impact (skel-default → Phase B v2, 196-graph corpus):**

| Metric | Skel-default (Apr 30) | Phase B v2 (May 2) | Δ |
|---|---:|---:|---|
| Total Py crossings | 138 | 131 | -7 |
| 1879.dot top offender | +69 | +60 | -9 |
| Clean graphs | 148 | 149 | +1 |
| Files OK | 174 | 175 | +1 |

Removed: 1474.dot (+2 → 0).  Added small +1 cases: 1436, 2476,
2521_1.  aa1332's 240pt-compaction bug did **not** re-emerge.

**§2.5.11 — Phase C diagnostic: ``post_rankdir_keepout`` is not
dead code.**  Gated the post-pass behind
``GVPY_DISABLE_POST_RANKDIR_KEEPOUT=1`` and re-ran the corpus.
Result: corpus +80 worse (Py 131 → 211); 1879 +60 → +108; 1436 +1 →
+9.  Only 2620 mildly improved (-10).  Phase B's NS keepout is not
sufficient on its own — the post-rankdir safety net is catching real
misses.  Gate removed.

**§2.5.11.1 — Slot-accumulator min-clearance attempt failed.**  Tried
converting ``_exit_slot`` (position.py:1955) from a cumulative
accumulator to a minimum-clearance push, hoping to eliminate the
2025pt sprawl on 1879's ``node_5507_5507``.  Spot check: 1879 +9,
1436 +6, only 2620 -2.  The cumulative push is actively preventing
in-rank cluster-bbox crossings that ``_enforce_rank_separation``
doesn't catch in time.  The visible sprawl on extreme outliers is a
*separate failure mode* from the bbox-crossings the audit metric
counts.  Reverted; comment block in ``post_rankdir_keepout`` records
the failed attempt so the next attempt knows what didn't work.

**Helper added:** ``aux_canreach()`` (position.py:41-65) ports C
``lib/dotgen/position.c:217-232``; gates cycle-creating aux-edge
additions in the flat-label and (planned) keepout phases.

**Phase A.1 (flat-edge label constraints) ported but gated off**
behind ``GVPY_FLAT_LABEL_CONSTRAINTS=1`` — wider Py label widths (D7
font-metrics drift) push layouts past C's local optimum on
2470/2796.  Will re-enable after the font-metrics fix.

**Audit timeout** bumped 60 → 90s
(porting_scripts/visual_audit.py:52) — multiprocessing.Process
overhead pushes 2470/2620 (~40s standalone) past 60s.

**Remaining gap:** 1879 +60 vs C's +2.  Closing it requires Phase D
(see TODO §2.5.11.1 scoping) — debug why Py's NS generates fewer
effective keepout edges than C's for long pile-up cases on cluster
sides.  2-3 days, medium risk.

1141 layout tests pass.  ``test_dot_parser`` has one pre-existing
unrelated failure.

---

## §1.5.60 — Audit C-side parser bug fix; TODO §2.3 retraction — 2026-04-27

`porting_scripts/visual_audit.py`'s `_html_unescape` only handled
the three named entities `&gt;`, `&lt;`, `&amp;`.  C dot.exe
encodes the directed-edge arrow as `&#45;&gt;` (numeric hyphen +
named gt) inside `<title>` tags.  After unescape the title was
`couple_X&#45;>node_Y` — neither `->` nor `--` matched, so every
edge was silently dropped from the C-side parse and the audit
reported `c=0` for every file.

**Fix**: replace the hand-rolled unescape with stdlib
`html.unescape`, which handles all named + numeric entities at
zero perf cost.

**Impact** — running the 10-file regression subset with the fixed
parser, comparing against the local CLion-built dot:

| File | Py | C (was) | C (fixed) | Δ |
|---|---:|---:|---:|---:|
| 1213-1.dot | 0 | 0 | 3 | -3 |
| 1213-2.dot | 0 | 0 | 3 | -3 |
| 1332_ref.dot | 16 | 0 | 6 | +10 |
| 1436.dot | 3 | 0 | 1 | +2 |
| 1472.dot | 3 | 0 | 9 | -6 |
| 1879.dot | 96 | 0 | 2 | +94 |
| 2183.dot | 3 | 0 | 0 | +3 |
| 2796.dot | 9 | 0 | 54 | -45 |
| aa1332.dot | 3 | 0 | 15 | -12 |
| d5_regression.dot | 0 | 0 | 2 | -2 |

Total Py = 133, C = 57.  **Only 4 of 10 files have Py > C; the
rest, Python's layout already routes around clusters better than
C's.**  1879 is the lone real outlier (+94).

Also added a `GVPY_DOT_EXE` env-var override so the audit can be
re-run against the libexpat-enabled system dot
(`c:/tools/graphviz/bin/dot.exe`) — useful for HTML-label-heavy
graphs where the local CLion build wouldn't render `<TABLE>`.
With the system dot the 1879 picture is identical (Py=96, C=2):
verified C and Python both produce ~108×79 pt for `node_325x326_325`
on 1879, so the +94 delta is layout-level, not rendering.

**TODO.md retraction**: §2.3's "HTML-IMG fallback bug-compat"
theory was wrong — based on the broken audit, not on actual
behavioural inspection.  Replaced with "1879 D5 alignment" (apply
the §1.5.21–53 workflow on 1879's genealogy topology).  D5 row
in §1 now reflects the corrected baseline; the long-tail per-file
residual list was almost entirely a parser artefact.

1141 tests pass.  `audit_report.md` regenerated for the 10-file
subset; full-corpus rerun pending.

---

## §1.5.59 — D4 closed; TODO.md cleanup — 2026-04-27

D4 (cluster-clipping sub-pixel corner-grazing + control-point-deep-
inside cases) is closed-out as splines-level-resolved.  The
cluster-detour pass (`gvpy/engines/layout/dot/cluster_detour.py`)
plus its follow-ups cover the D4 cases:

| Step | Coverage |
|---|---|
| §1.5.20 (2026-04-20) | Initial post-hoc detour reshape with 8-pt rounded corners, 20-pt detour margin, member-cluster identity-keying. |
| §1.5.55 (2026-04-27) | Wired into flat-edge variants (was regular-edge only). |
| §1.5.56 (2026-04-27) | Self-loop direction picker; interior-anchor projection for control-point-deep-inside cases. |
| §1.5.57 (2026-04-27) | D6 corridor-carve MVP (opt-in `GVPY_CLUSTER_CARVE=1`) for same-side rank-box constraints. |

**What's left in the audit isn't D4.**  Verified by sampling
`audit_report.md`'s top regression files:

- 1879 (96 crossings) — the `<IMG SRC>` fallback compat bug, see
  TODO §2.3.  Not D4.
- 1332_ref (16 crossings), 2796 (9), 2620 (2), 2470 (4) — every
  remaining crossing is an edge whose tail and head straddle a
  non-member cluster on adjacent ranks.  That's a D5 mincross /
  position decision: C tightens same-cluster nodes so the straddle
  doesn't arise.  Splines-level reshape can't undo that.

**Cleanup to TODO.md** done in this session:

- Drop D4 from §1 divergence table; record in a "closed
  divergences" sub-section.
- Re-attribute the per-file residual stats from D4 to D5.
- Rewrite §2 priorities to drop the D4 entry, promote D5 alignment
  on next-largest file (1332_ref), keep D6 hardening + HTML-IMG
  compat + D7 font metrics.
- Drop the empty §3 "Splines Port Deferred Items" section
  (E+.2-A closed in §1.5.58).
- Renumber §4–§9 to §3–§8; fix internal cross-refs (§7 phase 9,
  §1 tool-side caveats).

No code changes; documentation-only.  1141 tests still pass.

---

## §1.5.58 — D2 / E+.2-A closed-out as won't-fix — 2026-04-27

D2 (record-field-port faithful flat-edge routing) had been parked
on the TODO since the splines port — its faithful fix is option
**E+.2-A**: clone the two-node subgraph, run the full
``rank`` → ``mincross`` → ``position`` → ``dot_splines_`` pipeline
with ``rank=source`` on the clone, then transform the resulting
splines back.  E+.2-A is itself blocked on D8 (``DotGraphInfo``
can't be invoked recursively on a subgraph clone).

**Decision**: close out as won't-fix.  The current E+.2-B fallback
(compass-port attach points + corridor) covers the common case and
the residual narrow case (record-field port on adjacent flat edge)
fires :class:`UnsupportedPortRoutingWarning` so users see the
limitation.  Closing D2 lets us drop:

- the D2 row from the TODO §1 divergence table
- the E+.2-A entry from §3 deferred items
- the stale ``TODO_dot_splines_port.md`` pointer in
  ``flat_edge.py``'s :class:`UnsupportedPortRoutingWarning`
  docstring + emit text

D8 stays in the divergence table as **dormant** — it has no live
consumer once E+.2-A is closed, but the underlying gap (recursive
`DotGraphInfo` instantiation) might re-surface later (e.g., for
nested-graph features).  No code changes besides the warning text.
1141 tests pass, no regression suite movement.

---

## §1.5.57 — D6 corridor-carve MVP (opt-in) — 2026-04-27

First cut of the D6 corridor-carve fix promised in TODO §2.2.
Replaces ``rank_box(rank)`` with ``rank_box_gapped(...)`` for
regular-edge corridors when ``GVPY_CLUSTER_CARVE=1`` is set.  The
gapped variant shrinks the rank-box x-extent so the spline corridor
doesn't include non-member clusters that sit on the same side of
both endpoints.

**Wiring**: `regular_edge.make_regular_edge` reads
``GVPY_CLUSTER_CARVE`` once per call.  When set, it pre-computes
member cluster ids/names for the edge's tail/head and routes every
``rank_box(...)`` call inside the virtual-chain walk through a local
``_rank_box_for(rank, prev_node, next_node)`` helper that delegates
to ``rank_box_gapped``.  Flat and self edges are unchanged — they
already have their own cluster-avoidance via ``cluster_detour``.

**Carve rules** (per non-member cluster ``cl`` whose y-range
overlaps the rank strip):

- ``prev_x ≤ cx1 - splinesep`` AND ``next_x ≤ cx1 - splinesep`` →
  ``ur_x = min(ur_x, cx1 - splinesep)`` (path stays left).
- ``prev_x ≥ cx2 + splinesep`` AND ``next_x ≥ cx2 + splinesep`` →
  ``ll_x = max(ll_x, cx2 + splinesep)`` (path stays right).
- Otherwise (straddle): unchanged — D5 mincross divergence, no
  splines-level fix.

**Effect across regression corpus** (``GVPY_CLUSTER_CARVE=1``):

| File | post §1.5.56 | with carve |
|---|---:|---:|
| 1879.dot | 96 | 95 |
| 2796.dot | 9 | 7 |
| Total (10-file) | 133 | 130 |

**Trade-off**: ~9 new ``Pshortestpath: triangulation failed``
warnings on 2796 — the carve over-constrains some corridors,
forcing polyline fallback.  Polyline fallback is a worse visual but
doesn't introduce additional cluster crossings (the audit metric is
unchanged or improved).  An attempted "natural-path-only" guardrail
(skip clusters outside ``[min(prev_x, next_x), max(prev_x, next_x)]``)
zeroed out the wins entirely — the helpful carves were exactly the
"distant cluster" cases.

Kept opt-in for now.  1141 tests pass with both flag states.
Promoting to default would need a more careful rank_box / adjacent-
maximal_bbox compatibility check to eliminate the new triangulation
failures.

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
