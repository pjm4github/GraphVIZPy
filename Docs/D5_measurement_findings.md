# D5 Mincross Divergence — Measurement Findings

**Date:** 2026-04-22
**Scope:** Python-side mincross inspection on the D4 residual corpus.
No C-side instrumentation yet — this is a pure Python measurement
pass to characterise what the mincross output looks like *before*
we decide how to fix it.

## What we measured

`GV_TRACE=d5` now emits, at the end of `phase2_ordering`, a classifier
line per `(edge, non-member cluster)` pair:

```
[TRACE d5] edge=<tail>-><head> ranks=r0-rN span=<N>
           cluster=<name> sides=<string> crosses=<bool>
           members_preview=<csv>
```

Each character of `sides` corresponds to one rank the edge touches
(tail rank, intermediate virtuals if any, head rank).  The character
is:

- `L` — node's order < leftmost cluster-member order at this rank
- `R` — node's order > rightmost cluster-member order at this rank
- `T` — node's order lies *within* the cluster's order range
  (threading through the cluster)
- `-` — cluster has no members at this rank

`crosses=True` when the sides set for a single edge contains both
`L` and `R`, or contains any `T` — a strong mincross-level signal
that the spline will need to bend around (or through) this cluster
in phase 4.

The tracer is gated on `GV_TRACE=d5` and has zero cost when the
channel is off.  Implementation: `mincross._trace_d5_sides`.

## Corpus summary

Run on the seven D4-residual fixtures (TODO §1 D4 row).  Each row
shows the total number of real edges, how many of those edges touch
at least one non-member cluster, and the count of edge-cluster
pairs whose side pattern implies a geometric crossing:

| fixture     | real edges | vs non-member cluster | crossing pairs |
|-------------|-----------:|----------------------:|---------------:|
| aa1332      |        117 |                   111 |              5 |
| 1332        |        117 |                   111 |              5 |
| 1472        |          — |                     — | (Pshortestpath failure, no trace) |
| 2796        |        204 |                   203 |            343 |
| 1213-1      |         17 |                    16 |             10 |
| 1213-2      |         17 |                    17 |              7 |
| 2239        |         86 |                    73 |            141 |

Key observation: the D4 post-hoc detour reshape (shipped
2026-04-20) already *handles* the vast majority of these — e.g.
2796 has 343 mincross-level crossings but only 18 visible residuals
post-Phase-4.  The residuals are the ones the reshape can't clear.

## Side-pattern distribution

The dominant crossing patterns reveal different failure modes per
fixture.  Counts below are the top pattern frequencies for
`crosses=True` lines:

### aa1332 / 1332 — small adjacent-rank flips

```
2  sides=RL
1  sides=RL-
1  sides=LR
```

Every crossing is a two-position flip (tail `R`, head `L`, or
vice-versa) on adjacent ranks.  Mincross isn't grouping the tail
and head on a consistent side of the non-member cluster.

### 2796 — dominated by adjacent-rank RL

```
157 sides=RL
 76 sides=RRL
 23 sides=LRR
 22 sides=--RRL
 19 sides=LR
```

Same pattern at scale.  The `RRL`/`LRR` patterns are three-rank
spans where the edge hugs one side at the start but its endpoint
flips at the last rank.

### 1213-1 / 1213-2 — purely `LR`/`RL`

```
1213-1:  9 LR + 1 RL
1213-2:  7 LR
```

Simplest case: flat (same-rank) or short spans with tail and head
on opposite sides of a non-member cluster.

### 2239 — dominated by THREAD (`T`) patterns

```
27 sides=LR
13 sides=LT
11 sides=TR
11 sides=T--
10 sides=-T-
10 sides=--T
```

Qualitatively different: 2239's non-member endpoints land
*within* the cluster's order range.  That shouldn't happen after
cluster-aware mincross — cluster members should form a contiguous
run of orders at each rank, leaving non-members strictly outside.
`T` patterns suggest either (a) the cluster-aware ordering isn't
enforcing contiguity for this graph, or (b) the cluster membership
set used at trace time is broader than what was enforced in the
mincross sweep.

## Hotspot edges

Top individual offenders (edge appears in the most crossings):

- **2796**:
  - `edge=28->48 ranks=9-9` → 13 non-member clusters crossed
  - `edge=33->48 ranks=9-9` → 12
  - `edge=23->52 ranks=7-7` → 12
  - `edge=22->48 ranks=9-9` → 11
  - all adjacent-rank (span=2, one virtual each), all converging
    on nodes 48 / 52 / 14 — strong positional magnet pulling edges
    across many sibling cluster bands.

- **aa1332**:
  - `edge=c0->c5359 ranks=9-14 span=6` — a genuine long edge
    (6 ranks) crossing `cluster_5378` with pattern `-LLLLR`.
    Edge hugs left for four ranks then flips right at the head.

- **1213-1**:
  - Every crossing involves the same two-cluster partitioning
    (cluster_0 / cluster_1 / cluster_2) — likely a stress-test
    fixture built specifically to probe cluster-group mincross.

## Failure modes identified

1. **Adjacent-rank side mismatch** (dominant in 2796, aa1332, 1332,
   1213-x) — tail at rank R and head at rank R+1 land on opposite
   sides of a non-member cluster.  The spline renderer's detour
   reshape handles most of these, but the algorithmic debt lives
   in mincross: the node-ordering pass doesn't penalise separating
   an edge's endpoints by a non-member cluster.

2. **Thread-through-cluster** (exclusive to 2239) — non-member
   endpoints take positions in the middle of a cluster's order
   range, suggesting cluster contiguity isn't being enforced
   strongly enough in 2239's particular graph.

3. **Long-edge side flip** (one instance in aa1332: `c0->c5359`)
   — the classic multi-rank edge pattern.  The 6-rank edge keeps
   to the left for 4 ranks then the head lands on the right of
   the cluster.  A virtual-chain cross-rank constraint could catch
   this, but it's rare enough that it's not the leverage target.

## C-side parity (2026-04-22)

`lib/dotgen/mincross.c` got the same classifier, hooked in at
`dot_mincross` end (right before `cleanup2`).  Cluster enumeration
recurses via `GD_clust` to match Python's flat `layout._clusters`
list.  Build + capture run through `cmake-build-debug-mingw`; C
traces saved alongside Python in `trace_d5/{fx}_c.txt`.  Diff
script: `trace_d5/diff_d5.py`.

Summary across the corpus — `(Py crosses, C crosses, gap)`:

| fixture | Py total_edges | Py crosses | C total_edges | C crosses | Py-only | C-only | both |
|---------|---------------:|-----------:|--------------:|----------:|--------:|-------:|-----:|
| aa1332  | 117 |   5 | 117 |   4 |   4 | 3 |   1 |
| 1332    | 117 |   5 | 117 |   4 |   4 | 3 |   1 |
| 1472    |  —  |  —  | 154 |   2 |   — | — |   — |
| 2796    | 204 | 343 | 213 |   8 | 341 | 6 |   2 |
| 1213-1  |  17 |  10 |  17 |   6 |   8 | 4 |   2 |
| 1213-2  |  17 |   7 |  17 |   6 |   7 | 6 |   0 |
| 2239    |  86 | 141 |  86 |   0 | 141 | 0 |   0 |

The `both` column is the set of `(edge, cluster)` crossings that
both engines produce — geometrically inherent, not fixable in
mincross.  `Py-only` is the actionable gap: cases where C avoids
the cluster cross-over but Python doesn't.

Additionally, on `2796` **1544 of 1689 shared pairs have different
sides strings between Python and C** — not just the crossings,
the ordering is broadly different across the whole table.  That's
pervasive divergence, not a few localised bugs.

### Two distinct bug classes

The hotspots split cleanly into two categories:

**Bug class 1 — adjacent-rank RL flips (2796-dominated).**
The top offenders in 2796 are all adjacent-rank edges terminating
on a small handful of attractor nodes (48, 52, 14):

```
28->48 crosses 13 non-member clusters — all pattern RL
23->52 crosses 12 — all RL
33->48 crosses 12 — all RL
22->48 crosses 11 — all RL
54->48 crosses 10 — all RL
```

Every cluster touched has tail `R` (right of cluster) and head
`L` (left of cluster).  C's mincross avoids all of these.
Mechanism: C's median/transpose appears to penalise separating
an edge's endpoints by a non-member cluster; Python's doesn't
have that term.  Confirming which function is missing the term
is the prerequisite for the Bug-1 fix.

**Bug class 2 — thread-through cluster (2239-exclusive).**
Python's 141 crossings on 2239 are entirely `T` (node lands
inside cluster order range) patterns.  C shows zero — cluster
contiguity is strongly enforced.  Example Python entry:

```
edge=_proxypad59_*->rtpbin_*_src_0 crosses 9 non-member clusters
  cluster_dtlsenc1   sides=LR
  cluster_dtlsenc1_src sides=LR
  cluster_dtlssrtpdec2 sides=TR    ← T!
  cluster_dtlssrtpdec2_src sides=TR ← T!
  cluster_dtlssrtpenc1 sides=LR
```

The `T` side means the tail's order is between the first and
last cluster member — i.e. the non-member node is sitting inside
a cluster's rank positions.  Cluster-aware mincross should never
let this happen; Python's cluster skeleton / expansion pass is
letting non-members leak into cluster ranges on 2239.

### aa1332 / 1332 — small mutual gap

```
Py-only: c0->c5359 vs cluster_5378 (sides -LLLLR, the long edge)
         c4113->c4145 vs cluster_4148 (LR)
         c5382->c5384 vs cluster_6737 (RL)
         c6378->c6410 vs cluster_6409 (RL-)
C-only:  c4254->c5359 vs cluster_5378 (RL)
         c5380->c5384 vs cluster_6737 (LR)
         c6412->c6414 vs cluster_6748 (RL)
```

Symmetric-ish: Python crosses 4 cases C doesn't, C crosses 3
cases Python doesn't.  Net +1 crossings for Python.  These are
close to parity; any fix here is cosmetic.  1332 matches aa1332
byte-for-byte because the `aa*` prefix is a layout re-rendering
of the same graph.

### 1213-x — small proportional gap

1213-1: Py 10 vs C 6 (+4 Py).  1213-2: Py 7 vs C 6 (+1 Py).
These fixtures were hand-built as cluster-mincross stress tests
(the `V*` / `S*H*` node naming).  Both engines struggle; Python
just a little more.

## Bug 1 fix attempt (2026-04-22)

Ported the `ReMincross` branch of C's `left2right` (mincross.c line
842-845) into Python: a new `remincross_phase` flag on
`cluster_reorder` / `cluster_transpose` tightens the block to
"any cluster mismatch including None" and removes the virtual
escape hatch when set.  `remincross_full` passes `True`.  Also
found that `dotinit.py` was defaulting `remincross=False` when the
DOT source didn't specify it — C defaults to `True` for clustered
graphs; fixed to match.

**Measured impact** (visible cluster-crossings from
`count_cluster_crossings.py`):

| fixture | baseline (no fix) | with fix | delta |
|---------|------------------:|---------:|------:|
| aa1332  |  2 |  2 |   0 |
| 1332    |  4 |  4 |   0 |
| 1472    | 27 | 27 |   0 |
| 2796    | 17 | 15 |  −2 |
| 1213-1  |  3 |  3 |   0 |
| 1213-2  |  2 |  2 |   0 |
| 2239    |  1 |  1 |   0 |

Net: 2 fewer visible crossings on 2796, nothing else moves.  D5
mincross-level crossings unchanged (343 on 2796, 141 on 2239) —
the single-flag fix is correct per C but can't close the deep gap
on its own.  Full test suite still at 1135 pass.

The root cause of the residual Bug 1 gap lives **before**
`remincross_full` runs — in `skeleton_mincross`'s expand /
per-cluster mincross phase.  C's `mincross_clust` recursively
descends into `GD_clust(g)[c]` with an orthogonal iteration
structure (expand → ordered_edges → flat_breakcycles →
flat_reorder → mincross(g, 2) → recurse).  Python's
`skeleton_mincross` has its own expand walker that doesn't
precisely mirror this recursion shape.  Closing the remaining
335-crossing gap on 2796 would require either (a) a careful
alignment of the recursion with C's shape, or (b) an additive
penalty term in the median / transpose functions for
"edge straddles non-member cluster".

The correctness fix above is kept because it matches C on the one
branch Python was diverging on, and shows measurable improvement
on the one fixture where it bites.  The deeper skeleton/expand
work is deferred (TODO §1 D5 row updated).

## Skeleton/expand alignment push (2026-04-22, session 2)

Added a staged D5 counter (`d5_stage_crossings`) that emits
`[TRACE d5] stage=<name> cluster_pair_crosses=<n>` at key pipeline
points.  On 2796.dot:

```
stage=post_collapsed_mincross   crosses=0
stage=post_expand_cluster_1     crosses=19
stage=post_expand_cluster_3     crosses=20
stage=post_expand_cluster_5     crosses=21
stage=post_expand_cluster_9     crosses=32
stage=post_expand_cluster_13    crosses=39
stage=post_expand_cluster_15    crosses=43
stage=post_expand_cluster_18    crosses=53
stage=post_expand_cluster_22    crosses=92     (+39)
stage=post_expand_cluster_31    crosses=198    (+106)
stage=post_expand_cluster_34    crosses=253    (+55)
stage=post_expand_cluster_41    crosses=346    (+93)
stage=after_skeleton_mincross   crosses=346
stage=after_remincross_full     crosses=346
```

The "post_collapsed_mincross=0" is **not meaningful** — the D5
metric requires real cluster members in the rank to classify
non-member edges.  While clusters are collapsed to single skeleton
nodes, `member_set` is empty and no classification happens.
Cumulative growth per expand reflects the metric gaining visibility,
not new positioning decisions.

Two follow-up experiments both showed zero impact:

1. **Skip the local per-cluster mincross entirely** (GVPY_SKIP_LOCAL_MC=1).
   Crossings identical.  Local mincross isn't the culprit.
2. **Post-expansion global transpose** with ``remincross_phase=True``
   over every touched rank.  Crossings identical.  `cluster_transpose`
   optimises edge crossings, not cluster-straddles — the two metrics
   are only loosely correlated.

### Real conclusion

The divergence lives in the **skeleton mincross itself** — the
positions Python chooses for each cluster skeleton relative to
non-cluster real nodes.  C and Python see the same input, run
cross-reducing mincross on the collapsed graph, but converge to
different cluster orderings.  Once the skeletons are placed and
clusters expand, the cluster-straddle metric is determined.

Closing the remaining 335-crossing gap on 2796 would require one of:

- **Median/reorder alignment.**  Instrument C and Python's
  `medians()` side by side on specific ranks and find where the
  computed mvals / chosen orderings diverge.  Probably involves
  matching ``VAL`` / ``port.order`` / weighted-median calculation
  exactly.  Multi-day.
- **D5-aware cost function.**  Add cluster-straddle cost (weighted)
  to `cluster_transpose`'s swap decision so it has visibility
  into the D5 metric during the final remincross pass.  Novel (not
  in C) but could close the gap without matching C byte-for-byte.

Neither is a one-session job.  Deferring; the correctness fixes
landed this pass (remincross default, remincross_phase,
shape=none cap) and the staged instrumentation are the deliverable.

## Byte-for-byte alignment push (2026-04-22, session 3)

Added `d5_step` channel to both Python's `cluster_reorder` and C's
`reorder` with identical line format:

```
[TRACE d5_step] reorder_enter rank=R reverse=0|1 rmx=0|1
                nodes=[name:ord:mval ...]
[TRACE d5_step] reorder_cmp rank=R l=name@ord r=name@ord
                p1=V p2=V swapped=0|1
[TRACE d5_step] reorder_block rank=R l=name@ord r=name@ord
```

C-side skeleton virtuals report as `<cluster_name>` (extracted via
`ND_clust()`) rather than the anonymous `%0`, so Python's
`_skel_<cluster>_<rank>` and C's virtuals can be matched.

### First localized divergence: aa1332 rank 4

Diffing final rank orderings between Python and C on aa1332
reveals the **first structural divergence at rank 4**:

```
rank 4  C: c4116(0) c4113(1) c4143(2) c4146(3)
rank 4 Py: c4116(0) c4113(1) c4146(2) c4143(3)
```

c4143 and c4146 are swapped.  c4143 belongs to `clusterc4143`
(nested inside `cluster_4144`); c4146 belongs to `cluster_4148`.
Both are single-rank clusters on rank 4, so the swap is determined
by the skeleton mincross at root level.

### Specific mval divergence

Filtering `d5_step` to rank=4 at root level on both sides uncovers
matching orderings for the first several passes — both C and Python
compute identical mvals 0/256/512/-1 initially, converge on the
same 384/0/768/512 mvals after one iteration.  At **iteration 3
(reverse=0)** they diverge:

```
C:  mvals = [cluster_4117=0, clusterc4113=256, cluster_4148=-1,  cluster_4144=512]
Py: mvals = [cluster_4117=0, clusterc4113=256, cluster_4148=256, cluster_4144=512]
                                                           ^^^ diverges
```

Both start the iteration with identical ordering and compute
medians from the same adjacent-rank positions.  But Python's
`cluster_4148` ends up with mval **256** where C gets **−1**
(cluster_4148 has no member edges reaching rank 3, so -1 is
correct).  The 256 means Python is seeing a neighbor at order 1
on rank 3 that shouldn't exist at the skeleton level.

### Root cause candidate: Python's ICV chain creation

The extra neighbor comes from Python's inter-cluster skeleton
chain creation in `skeleton_mincross` (the `_icv_*` virtual
chain nodes created at line 698 via the `_seen_skel_edges`
dedup).  C has the same algorithm (`class2.c: make_chain()`)
but Python's output includes edges C doesn't — evidence:

```
    fixture   baseline   GVPY_SKIP_ICV=1
    aa1332          5      10       (worse — Python's ICV helps)
    2796          343     343       (no change)
    2239          141     134       (better — Python's ICV hurts)
```

Wholesale disable is NOT the fix — ICV edges help some fixtures
and hurt others.  The correct fix is to align Python's `_icv_*`
chain creation logic to C's `interclrep` + `make_chain` exactly,
including:

1. C's `leader_of(agtail(e))` vs Python's `_node_skel_cluster`
   lookup — do they return the same cluster for every original
   edge's endpoint?
2. C's `find_fast_edge(t, h)` deduplication + `merge_chain`
   fallback when the chain already exists — does Python's
   `_seen_skel_edges` do the same thing?
3. C's sibling-level walk (``leader_of`` returns the cluster at
   rank r, which may not be the innermost cluster for a given
   node) — does Python's `t_child` / `h_child` computation
   match?

Each of these needs side-by-side code reading and probably
instrumentation of `class2.c: interclrep` itself — another
multi-session scope.  Deferred.

### What this session shipped

- `trace.py` — new `d5_step` channel
- `gvpy/engines/layout/dot/mincross.py` — `d5_step` emissions in
  `cluster_reorder` (entry + per-cmp + per-block)
- `lib/dotgen/mincross.c` — matching `d5_step` emissions with
  skeleton-virtual → cluster-name mapping for diffable output
- `Docs/D5_measurement_findings.md` — this section

Diffing traces is now routine.  Future session can pick up where
this one left off — the first divergence is at **rank 4 iteration 3
(reverse=0), cluster_4148 mval**, traceable into Python's ICV
chain creation.

## run_mincross backend swap (2026-04-22, session 4)

Diffing d5_step traces on the small ``d5_regression`` fixture
(4 test cases, ~20 nodes) surfaced a structural divergence the
aa1332 investigation only hinted at:

### The bug

Python's ``run_mincross`` (invoked by skeleton mincross on the
collapsed graph) used ``order_by_weighted_median`` +
``transpose_rank``.  C's ``mincross`` uses ``medians()`` +
``reorder()`` + ``transpose()``.  The two are not equivalent:

1. **Mval scale.**  ``order_by_weighted_median`` stores raw
   positional indices (0, 1, 2.5, 3, ...) as median values.  C's
   ``medians()`` computes ``VAL(node, port) = MC_SCALE * order +
   port.order`` → (0, 256, 512, ...).  Same sort order in simple
   cases, but different weighted-median arithmetic:

   ```
   if lspan == rspan:
       mval = (positions[lm] + positions[m]) / 2.0
   elif lspan + rspan > 0:
       mval = (positions[lm] * rspan + positions[m] * lspan)
              / (lspan + rspan)
   ```

   With tiny integer positions, ``lspan == rspan`` fires far more
   often (hitting the simple-average branch); with MC_SCALE-256
   positions it rarely does.  The weighted-median results diverge.

2. **Reorder algorithm.**  ``order_by_weighted_median`` uses a
   group-then-sort approach: bucket consecutive same-cluster
   runs, sort within each bucket by mval.  C's ``reorder()``
   uses a bubble-sort that walks pairs, allows "jumping over"
   a single cluster via ``sawclust``, and respects ``left2right``
   per-pair.  Different sequences of swaps → different final
   orderings.

### The fix

``run_mincross`` now uses ``cluster_medians`` / ``cluster_reorder``
/ ``cluster_transpose`` — the same C-aligned implementations that
``remincross_full`` and the per-cluster expand already use.  Legacy
behaviour kept behind ``GVPY_LEGACY_MINCROSS=1`` for diagnostics.

### Impact

On ``test_data/d5_regression.dot``:

| metric                              | legacy | C-aligned | C   |
|-------------------------------------|-------:|----------:|----:|
| visible cluster crossings           |      4 |     **1** |   0 |
| D5 mincross-level crossings         |      2 |         2 |   0 |

75 % reduction in visible cluster crossings on the new fixture;
D5 metric unchanged.  Corpus D5-residual fixtures (aa1332, 2796,
2239, 1472, 1332, 1213-x, 1879) all held steady — their mincross
path already went through the cluster_* backend so the swap was
a no-op for them.

### What this tells us

The remaining 2796/2239 D5 gap isn't in ``reorder()``'s sort
logic — both sides now use the same C-aligned implementation
for it.  The divergence must live in either:
(a) the initial rank ordering (``build_ranks`` — Python uses DFS
    from a stack; C uses BFS from source nodes with a queue), or
(b) the median VAL computation itself (port.order contributions),
    or
(c) the inter-cluster skeleton chain edges (the ``_icv_*`` chains
    that create median-influencing edges C doesn't).

The d5_step instrumentation is the same; future sessions can
drill into any of the three without re-adding plumbing.

## build_ranks BFS-vs-DFS investigation (2026-04-22, session 5)

Python's legacy ``build_ranks`` (rank.py) uses DFS over an
*undirected* adjacency list, starting from every real node in
DOT-file order then filling remaining virtuals.  C's ``build_ranks``
(mincross.c:1518) uses BFS over *directed* out-edges, starting
only from "source" nodes (no in-edges for pass=0), and calls
``install_cluster`` to batch-insert cluster members.

On ``d5_regression.dot``, Python's DFS plunges from ``root`` through
the invis ``root→D_ext`` chain before visiting cluster members.
Rank 2 initial order ends up as
``[_v_root_D_ext_2, _v_root_C_src_2, B_in, A_r1, A_l1, ..., A_l2, A_r2]``
— cluster members interleaved with virtuals.  C's BFS produces
``[A_l1, A_l2, A_r1, A_r2, B_in, ...]`` — cluster blocks tight.

### BFS-from-sources variant

Implemented as the non-default path in ``build_ranks``, enabled
via ``GVPY_BFS_BUILD_RANKS=1``.  Matches C's BFS traversal +
directed-out-adjacency + source-first iteration.  Does NOT yet
implement ``install_cluster`` batching (that needs cluster
skeletons at rank level, which are post-build_ranks).

### Corpus impact (env var on)

| fixture        | DFS (default) | BFS (env var) | delta |
|----------------|--------------:|--------------:|------:|
| d5_regression  |             1 |             1 |     0 |
| aa1332         |             2 |             3 |    +1 |
| 1332           |             4 |             5 |    +1 |
| 1472           |            27 |            21 |    −6 |
| 2796           |            15 |            28 |   +13 |
| 1213-1         |             3 |             4 |    +1 |
| 1213-2         |             2 |             3 |    +1 |
| 2239           |             1 |             0 |    −1 |
| 1879           |           145 |           151 |    +6 |

Mixed.  Big wins on **1472 (−6)** and **2239 (−1 to zero)**.
Big regression on **2796 (+13)**.  Net +4 across the D5 corpus.

### Why 2796 regresses

Hypothesis: 2796 has several attractor nodes (48, 52, 14) with
many converging edges.  Without C's ``install_cluster`` batch
inserting all cluster members at once, BFS interleaves attractors
with cluster members — breaking the attractor-group clustering
that Python's DFS happened to produce.

Brief attempt at cluster-peer batching (when BFS installs a
cluster member, also install its peers from the same cluster)
didn't improve 2796 (actually slightly worse) because peers
often live at different ranks that BFS hasn't reached yet —
the install-order matters.

### Current state

BFS path kept behind ``GVPY_BFS_BUILD_RANKS=1`` for future work.
Default remains DFS so the corpus baselines don't shift.  To
close the BFS-vs-DFS gap on 2796 we'd need to port C's
``install_cluster`` properly — which requires cluster rank-leader
data structures that currently only live in ``skeleton_mincross``.

Defer to a later session.  The next divergence candidate left is
the ``_icv_*`` inter-cluster skeleton chain edges — that
investigation can proceed with d5_step instrumentation already
in place.

## Session 6: cluster-contiguity normalization (2026-04-22)

Tried porting C's ``install_cluster`` to Python's BFS build_ranks.
Direct port (batch-install all cluster members on first wavefront
touch) disrupted BFS ordering and hurt 7 of 9 corpus fixtures.

Pivoted to a **post-build_ranks normalization** approach: after
build_ranks completes (either BFS or DFS backend), walk each rank
and reorder so cluster members are contiguous at the position
where the cluster was first encountered.  Preserves the base
algorithm's visit order for non-cluster nodes and the cluster's
own first-touched position; only relocates peers that landed in
separate spots.

### Implementation

``_normalize_cluster_contiguity(layout)`` — runs after both the
BFS and DFS paths in ``build_ranks``.  Builds an innermost-cluster
map, then for each rank walks left-to-right finding each cluster's
first-occurrence index and collecting all its members.  Rebuilds
the rank by emitting non-cluster nodes in place and emitting each
cluster's full member list at its first-occurrence position.
Placed clusters are skipped on subsequent encounters.

### Corpus impact (default DFS path + normalization)

| fixture        | before | after | delta |
|----------------|-------:|------:|------:|
| d5_regression  |      1 |     1 |     0 |
| aa1332         |      2 |     2 |     0 |
| 1332           |      4 |     4 |     0 |
| **1472**       |     27 |   **8** | **−19** |
| 2796           |     15 |    15 |     0 |
| 1213-1         |      3 |     3 |     0 |
| 1213-2         |      2 |     2 |     0 |
| 2239           |      1 |     1 |     0 |
| 1879           |    145 |   145 |     0 |

**Net −19 across corpus with zero regressions.**  Full test
suite at 1137 pass.

### Why it works

1472's 19-crossing improvement comes from cluster members that
Python's DFS visited via disconnected sub-trees, landing them
far apart on the same rank.  The normalization pulls them back
together, giving mincross a cluster-contiguous starting state
it can improve from.

The fixtures that showed no change already had cluster members
contiguous from DFS's natural traversal — normalization is a
no-op on them.

The BFS backend is still behind ``GVPY_BFS_BUILD_RANKS=1``; the
normalization helps it too (2239 → 0) but the BFS base still
regresses 2796 (+12) and a handful of small-gap fixtures.
Separately-gated; to be revisited when Python's pre-skeleton
graph representation is closer to C's pre-skeletonized form.

## Adjacent investigation: 1879.dot (corpus-wide top regression)

`porting_scripts/visual_audit.py` reports 1879.dot as the single
biggest Python-vs-C gap in the corpus (145 crossings vs 0).  This
sits outside the D5 measurement corpus but the user flagged it as
the worst HTML-label regression.

Spent a measurement pass comparing Python vs C node sizes on
1879's `node_567x568_567` (a `shape=none` node with an 8-row HTML
`<TABLE>` label containing an `<IMG>` tag):

- Python layout: `w=166.3 h=205.6` — accounts for the full HTML
  table height (name + 5 dated sub-rows + image cell).
- C layout (`dot -Tdot`): `w=127.2 h=36.0` — node bbox collapses
  to just the default height.
- C's xdot `_ldraw_` draws *only the node name* as the label
  (`T 6676 910.6 0 111.21 16 -node_567x568_567`), not the HTML
  table.  Suggests C's HTML parser is falling back to the node
  name — possibly because the embedded `<IMG SRC="1879.png"/>`
  can't resolve the image from CWD without an `imagepath` hint,
  and C's failure mode drops the entire label.

Consequence: C's node bboxes are small, cluster bboxes are small,
and the layout fits without crossings.  Python honours the table
and produces accurate bboxes — but that then tangles with the
skeleton/expand cluster ordering divergence already documented
above, blowing up to 145 crossings.

Landing a fix here would require *either*:

1. Matching C's HTML-label fallback behaviour when an embedded
   IMG fails to resolve (arguably a "bug compatibility" fix — the
   C behaviour feels more like a silent failure than an
   intentional fallback), or
2. Pushing through the deep skeleton/expand alignment so
   correctly-sized HTML nodes don't force crossings.

Deferred.  Adjacent cleanup landed during this pass: `shape=none`
/ `plaintext` / `plain` now treat explicit `width` / `height` as
**hard values** rather than minimums — matches C's
label-free-shape semantics and shows no corpus-wide impact
(1879 is unaffected because it sets no explicit dims).

## Bug prioritisation

1. **Bug 1 (2796)** — highest leverage.  Fixing the adjacent-rank
   RL-flip penalty in mincross would take 2796 from 343 → close
   to 8, which is a 40× reduction.  D4's residuals on 2796 (18)
   would likely drop to single digits since the reshape currently
   fights through an overwhelming base of mincross-level crosses.

2. **Bug 2 (2239)** — high leverage but different fix.  141 →
   0 is attainable if we can identify where cluster contiguity
   is leaking.  Likely culprit: the cluster skeleton expansion
   pass in `mincross._skeleton_mincross` / `expand_cluster` isn't
   re-asserting contiguity after the outer remincross pass.

3. **aa1332 / 1332 / 1213-x** — defer.  Small mutual gaps; not
   worth isolated fixes before the 2796-class and 2239-class
   bugs are addressed.

## Next step

Isolate Bug 1 first — instrument one offending edge (e.g. `28->48`
in 2796) through Python's median / transpose to find where C
would reject a move that Python accepts.  The `median` channel is
already present in KNOWN_CHANNELS; a targeted `[TRACE median]`
diff between Py and C on 2796 should surface the missing term.

Then Bug 2: add contiguity asserts at `_skeleton_mincross` exit
and at `_remincross_full` exit to measure whether cluster ranges
stay contiguous through the pipeline on 2239.  Fix at the first
place contiguity breaks.

## Files touched in this measurement

- `gvpy/engines/layout/dot/trace.py` — added `"d5"` to
  `KNOWN_CHANNELS`.
- `gvpy/engines/layout/dot/mincross.py` — new `_trace_d5_sides`
  helper invoked from `phase2_ordering` when gated.
- `Docs/D5_measurement_findings.md` — this document.

## Reproduction

```powershell
cd C:\Users\pmora\OneDrive\Documents\Git\GitHub\GraphvizPy
$env:GV_TRACE = "d5"
.venv\Scripts\python.exe dot.py test_data\2796.dot -Tsvg -o nul 2> trace_2796.txt
# Filter to crossings:
Select-String -Path trace_2796.txt -Pattern "crosses=True"
# Or a summary:
Select-String -Path trace_2796.txt -Pattern "summary"
```

bash / Git Bash:

```bash
GV_TRACE=d5 .venv/Scripts/python.exe dot.py test_data/2796.dot \
    -Tsvg -o /tmp/out.svg 2> trace_2796.txt
grep -c "crosses=True" trace_2796.txt
grep "summary" trace_2796.txt
```
