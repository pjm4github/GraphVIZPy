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

## Session 7: C-aligned inter-cluster chain creation (2026-04-22)

Ported C's ``class2.c: interclrep`` + ``leader_of`` + ``make_chain``
semantics into Python's ``skeleton_mincross`` inter-cluster chain
builder.  Legacy sibling-pair logic had four divergences:

1. Missed chains when only ONE endpoint was in a cluster
   (C's ``leader_of`` returns the node itself for non-cluster
   nodes, enabling chain creation against any cluster's leader).
2. Missed chains for top-level disjoint clusters — the common case
   (``t_cl == h_cl == None`` guard in the sibling-pair walk
   exited early when no common ancestor existed).
3. Missed chains for nested child→parent edges (break fired when
   one side's child equalled the common ancestor).
4. Used SIBLING-level skeletons when C uses INNERMOST-level
   skeletons (``GD_rankleader(ND_clust(v))[ND_rank(v)]``).

### Implementation

New ``_leader_of(node_name, rank)`` helper + rewritten chain
creation loop in ``skeleton_mincross``.  Legacy sibling-pair
logic kept behind ``GVPY_LEGACY_ICV=1`` for A/B diagnostics.
New ``GV_TRACE=d5_icv`` channel emits one line per chain built
with endpoint rank-leaders + the original edge, so Python's
chain set can be diffed against C's interclrep emissions in
future sessions.

### Corpus impact

| fixture        | legacy | C-aligned | delta |
|----------------|-------:|----------:|------:|
| d5_regression  |      1 |         1 |     0 |
| **aa1332**     |      2 |       **1** |    **−1** |
| **1332**       |      4 |       **1** |    **−3** |
| 1472           |      8 |         8 |     0 |
| 2796           |     15 |        15 |     0 |
| 1213-1         |      3 |         3 |     0 |
| 1213-2         |      2 |         3 |    +1 |
| 2239           |      1 |         1 |     0 |
| 1879           |    145 |       157 |   +12 |

Chain-count diagnostics (`d5_icv` trace):

| fixture   | legacy chains | C-aligned chains |
|-----------|--------------:|-----------------:|
| aa1332    |            57 |               64 |
| 1332      |            57 |               64 |
| 1213-2    |             0 |                6 |
| 1879      |             0 |              353 |

Legacy creates 0 chains on 1213-2 and 1879 because neither has
the "sibling-pair across common-ancestor" configuration its logic
requires.  C-aligned creates the chains C actually builds.

### The 1879 regression

1879 has ~100 nested clusters (one per person in a family tree),
many pairs of which have direct edges between them.  C-aligned
creates 353 inter-cluster chains; each chain contributes extra
edges to the skeleton graph's median computation.  On this graph
the extra edges happen to push mincross toward a worse local
minimum (+12 visible crossings vs legacy's 0-chain baseline).

1879 is also the corpus-wide top HTML-sizing regression (see
earlier section) — its Python output differs from C primarily
because C's HTML parser silently drops labels when embedded IMG
resolution fails, sizing clusters much smaller than Python.  The
+12 D5 regression is secondary to that structural difference.

### Net

D5-relevant fixtures: −4 crossings (aa1332, 1332 improvements
outweigh 1213-2 loss).  Plus correctness: legacy was provably
incomplete.  1879 regression documented as a known interaction
with its HTML sizing issue.

## Session 8: C-side chain parity verification (2026-04-22)

Added ``[TRACE d5_icv]`` emissions to C's ``class2.c: interclrep``
so Python's and C's inter-cluster chain sets can be compared
line-for-line.  C emits one line per chain built:

```
[TRACE d5_icv] chain t=<cluster>@<rank> h=<cluster>@<rank>
               tail=<raw_tail> head=<raw_head>
[TRACE d5_icv] merge t=<cluster>@<rank> h=<cluster>@<rank>
               tail=<raw_tail> head=<raw_head>
```

### Chain counts

| fixture | Py (C-aligned) | C chains | C merges | C total |
|---------|---------------:|---------:|---------:|--------:|
| aa1332  |             64 |       69 |        9 |      78 |
| 1332    |             64 |       69 |        9 |      78 |
| 1213-2  |              6 |        6 |        0 |       6 |
| **1879**|        **353** |  **353** |        0 |     353 |

### The key finding — 1879 chains match byte-for-byte

Diffed the chain (tail, tail_rank, head, head_rank) tuples between
Python and C on 1879 after normalizing Python's ``_skel_<cluster>_<rank>``
prefix to just the cluster name (C's format).  Result:

```
Py chains=353   C chains=353
Common:  353
Py-only:   0
C-only:    0
```

**Every chain C creates, Python creates.**  Same endpoints, same
ranks.  The chain-creation alignment is complete.

### Where the 1879 regression lives

Both paths (legacy and C-aligned) produce **0 D5 mincross-level
crossings** on 1879 — the metric reports identical mincross output.
But all 9 rank orderings differ between the two paths, and visible
cluster crossings differ: legacy Python = 145, C-aligned Py = 157,
C = 0.

The inference: the divergence is **downstream of mincross**
(phase 3 position or phase 4 spline routing), not in chain
creation.  Same ICV chains, same D5 metric, but different final
layouts.  Legacy's 0-chain state on 1879 happens to produce
mincross ordering that spline-routes with fewer visible crossings,
entirely by accident.

C-aligned ICV is correct — chain sets match byte-for-byte.  The
+12 regression on 1879 is a loss of an accidental benefit, not a
bug in the alignment.  Closing the remaining 157-vs-0 gap on 1879
requires investigating phase 3 or phase 4 divergence, which is
separate D5-adjacent work.

### aa1332 merge_chain gap

C reports 9 ``merge_chain`` operations on aa1332/1332.  Each one
combines weights (``ED_weight``, ``ED_count``, ``ED_xpenalty``)
from duplicate-endpoint edges into an already-existing chain.
Python's deduplication (``_seen_skel_edges``) silently skips
duplicate (leader_pair) edges — no weight accumulation.

On aa1332/1332 Python improved (2→1, 4→1) so the missing weight
accumulation isn't hurting there.  The correct port would be a
``merge_chain`` equivalent that accumulates ``le.weight`` into
the existing chain's edges.  Deferred — low priority because the
current approximation is already winning.

## Session 9: phase 3 instrumentation + divergence audit (2026-04-22)

Both sides already had ``[TRACE position]`` emissions at the key
phase-3 stages:

- ``phase3 begin`` — entry
- ``set_ycoords`` — y-coord per real node
- ``pre_ns`` — pre-NS state per real node (rank_val = mincross
  order * MC_SCALE / N, lw, rw)
- ``ns_solved`` — post-NS x position per real node
- ``final_pos`` — final x, y, w, h

Captured Python and C on ``d5_regression.dot`` and compared.

### Result: phase 3 is aligned; divergences echo mincross output

Comparing ``pre_ns`` rank_val on rank 2:

| node  | C rank_val | Py rank_val |
|-------|-----------:|------------:|
| A_l1  |          0 |         144 |
| A_l2  |         72 |         216 |
| A_r1  |        144 |           0 |
| A_r2  |        216 |          72 |
| B_in  |        288 |         288 |
| C_m1  |        436 |         400 |

C places cluster_A_left LEFT of cluster_A_right; Python reverses
them.  This is **already the case at mincross-exit** — phase 3
faithfully encodes whatever ordering mincross produced into
pre_ns.rank_val.

Comparing ``ns_solved`` (NS-solved x positions):

| node  | C x_pos | Py x_pos |
|-------|--------:|---------:|
| A_l1  |    −170 |      205 |
| A_l2  |     −98 |      277 |
| A_r1  |      −4 |       45 |
| A_r2  |      68 |      117 |
| B_in  |     173 |      357 |
| C_m1  |     355 |      477 |

Different absolute origins, but each engine's NS solver correctly
places its OWN rank-2 ordering with proper node separation
(72/94/72/105/182 on C; 72/88/72/80/120 on Py).  Phase 3's job
(translate mincross order into x-coords honoring nodesep, cluster
bbox containment, etc.) is performed equivalently on both sides.

### Implication for D5 work

Phase 3 isn't the leverage point.  Any remaining D5 divergence
traces back to mincross output:

- ``d5_regression``'s 1 residual comes from Python placing B_in
  LEFT of cluster_A_right while C places B_in RIGHT of both A
  clusters.  Mincross decision, not phase 3.
- ``1879``'s +12 regression comes from C-aligned ICV chains
  changing mincross convergence to a different (worse-for-1879)
  rank ordering.  Phase 3 faithfully encodes both.
- ``2796``'s 15 residuals are mincross-level RL-flips (documented
  in session 1).

**Phase 3 matches C.**  No fix needed.  D5 investigation closes
at the mincross layer — the four alignments shipped this session
(run_mincross backend, cluster-contiguity normalization, opt-in
BFS build_ranks, C-aligned interclrep) plus the earlier
remincross + remincross_phase fixes are the net-positive
deliverable.

## Session 10: C-seed injection test (2026-04-22)

User asked: "Can we inject the same seed in Python as C uses to
confirm initial seeding is the issue?"

Added a diagnostic override hook to ``phase2_ordering``:

- ``GVPY_RANK_OVERRIDE=<path>`` — apply a JSON spec
  ``{"rank_num_str": [node_name, ...]}`` to ``layout.ranks`` before
  mincross runs.
- ``GVPY_RANK_OVERRIDE_SKIP_MINCROSS=1`` — additionally skip the
  mincross sweeps entirely, so phase-3 / phase-4 operate on the
  injected ordering verbatim.

Extracted C's final rank ordering (after C's full mincross) from
``[TRACE order]`` on d5_regression, aa1332, 2796 — converted to
JSON seeds.  Injected each into Python and re-measured visible
cluster crossings.

### Results

| fixture        | baseline | C-seed + mincross | C-seed + skip_mincross |
|----------------|---------:|------------------:|-----------------------:|
| d5_regression  |        1 |             **0** |                      2 |
| aa1332         |        1 |                 4 |                      3 |
| 2796           |       15 |                15 |                     18 |

### Interpretation

- **d5_regression (1→0)**: Python's mincross accepts C's
  ordering as a fixed point — stays there, gets 0 crossings.
  **The divergence here is entirely in ``build_ranks``** (the
  initial ordering Python's DFS-based builder produces).

- **aa1332 (1→4)**: Python's mincross **perturbs** C's ordering
  ON PURPOSE, thinking it found a better configuration.  Diffing
  the per-rank result shows 12/27 ranks differ from C after
  Python's mincross runs on the C-seed.  Sample:

  ```
  rank 5  C:  c4118 c4145 c4147 c4051 c4236 c4243
  rank 5  Py: c4118 c4145 c4147 c4236 c4051 c4243
  ```

  Python moves c4051 past c4236.  Python's crossing count /
  median / left2right evaluates this swap as a WIN; C's rejects
  it.  **Divergence here is in the mincross iteration itself.**

- **2796 (15 = 15)**: Python's mincross converges from C's seed
  to the same 15-crossing local minimum as from its own build_ranks
  seed.  Python's mincross has a DIFFERENT OPTIMUM than C's —
  they disagree about what's minimal.

### Conclusion

The D5 divergence is not a single root cause.  Three distinct
levels contribute:

1. **``build_ranks``** produces different initial orderings.
   The C-seed test proves this dominates on small fixtures
   (d5_regression).
2. **Mincross iteration** (median + reorder + transpose) agrees
   with C on structurally simple graphs but diverges on
   complex cluster arrangements.  The C-seed + aa1332 test
   isolates this: even starting from C's answer, Python
   perturbs to something worse.
3. **Mincross convergence criterion** stops at a different local
   minimum on large graphs.  The 2796 result shows Python's
   optimum is structurally 15 visible crossings regardless of
   starting point.

### What's actionable

The ``GVPY_RANK_OVERRIDE`` override is now a **permanent
diagnostic tool**.  It lets any future investigator inject a
known-good ordering and isolate "seeding vs iteration" on any
specific fixture.

Two narrowed next-step candidates:

- **Aligning build_ranks BFS more carefully** (session 5's
  attempt regressed 2796 by +13 without install_cluster; maybe
  a targeted hybrid works).
- **Instrumenting the specific mincross perturbation on aa1332
  rank 5** that moves c4051 past c4236.  Identify which swap
  decision (median / reorder / transpose) fires and whether
  its cost function disagrees with C's.

Both are multi-session projects.  The override tool makes each
tractable without blind iteration.

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

## Session 11: transpose scoped-crossing fix (2026-04-23)

Continuation of the aa1332 rank-5 isolation pinned down in session 10
— where `c4051` swaps past `_skel_cluster_4246_5` in Python but C
keeps them in opposite order.

### Instrumentation delta

Added `[TRACE d5_step] transpose_enter / transpose_cmp / transpose_block`
to C's `lib/dotgen/mincross.c: transpose_step()` (matches the format
already emitted by Python's `cluster_transpose`).

### What the C trace showed

C's transpose at rank 5 operates **per-cluster-subgraph** scope.
For the cluster_4250 expansion, C sees only three nodes at rank 5:

```
[TRACE d5_step] transpose_enter rank=5 reverse=0 rmx=0
                nodes=[clusterc4236:3 cluster_4246:4 c4051:5]
[TRACE d5_step] transpose_cmp rank=5 v=clusterc4236@3 w=cluster_4246@4
                c_before=100 c_after=0 swapped=1
[TRACE d5_step] transpose_cmp rank=5 v=clusterc4236@4 w=c4051@5
                c_before=0 c_after=0 swapped=0
```

C swaps `clusterc4236 ↔ cluster_4246` first — then `(cluster_4246,
c4051)` is *never compared* because they're not adjacent in C's
scoped rank after that swap (final order `cluster_4246@3,
clusterc4236@4, c4051@5`).

Python saw six nodes at the same rank (all root-level rank-5 siblings)
and a different first-pair outcome — kept `clusterc4236 @3,
cluster_4246 @4` and then swapped `cluster_4246 ↔ c4051`.

### Root cause

`count_crossings_for_pair` in `mincross.py` iterated every edge in
`layout.ledges`, which during the cluster-expand phase mixes
sibling-cluster edges into the crossing count.  C's `in_cross` /
`out_cross` instead iterate `ND_out` / `ND_in` — the cluster
subgraph's scoped edge list, built by `class2` with
intra-child-cluster edges excluded (class2.c:199).

### Fix

Added `count_scoped_pair_crossings(layout, fg_out, fg_in, u, v)` —
same topology as the C pair counter, restricted to a caller-supplied
fast graph.  Threaded `mc_fg_out` / `mc_fg_in` through to
`cluster_transpose` during the expand phase so its cost function
uses the same scoping as `cluster_medians`.  `remincross_full` and
the early `run_mincross` loop still use the global counter because
their scope legitimately *is* the whole graph.

### Measurement

`tests/test_d5_regression.py`: unchanged, still passes with
`BASELINE_VISIBLE_CROSSINGS=1`.  Full suite: 1137/1137 passing
(one pre-existing parser failure is unrelated to mincross).

On aa1332 specifically the `c4051 ↔ _skel_cluster_4246_5` swap
still fires.  The scope fix brings Python's cost function into
alignment with C's, but the cascade diverges earlier at rank 4 —
C's rank-4 ordering already placed `cluster_4246_4 left-of
clusterc4236_4`, while Python has them in the opposite order.
So rank-5's cost inputs differ not because of the counter anymore
but because of the rank-4 orders Python feeds into it.

### Next step

Walk the same d5_step traces down to rank 4 to find the first rank
where Python and C diverge on orders.  The scope fix shipped here
is a prerequisite correctness win; the residual divergence is a
separate cascade earlier in the sweep.

## Session 12: rank-6 divergence isolated on aa1332 (2026-04-23)

Session 11 concluded that the rank-5 cost function was itself sound
once scoped; the cascade had to start earlier.  This session walks
cluster_4250's expand phase down to the first rank where Python and
C disagree on a swap decision.

### Setup

Both engines dump `reorder_enter` / `transpose_enter` / `transpose_cmp`
on the `d5_step` channel now (C: `lib/dotgen/mincross.c`, Python:
`gvpy/engines/layout/dot/mincross.py`).  Captured:

- C trace: `GV_TRACE=d5_step dot.exe -Tsvg aa1332.dot`
- Python trace: `PYTHONHASHSEED=0 GV_TRACE=d5_step python dot.py aa1332.dot`

### First divergence: rank 6 mval

At the START of cluster_4250's expand phase, both engines agree on
rank-5 and rank-6 ORDERS:

```text
C: reorder_enter rank=5 reverse=1 rmx=0
   nodes=[clusterc4236:3:-1 cluster_4246:4:-1 c4051:5:-1]
C: reorder_enter rank=6 reverse=1 rmx=0
   nodes=[clusterc4237:1:1088 cluster_4246:2:1024 c4149:3:384]

Py: reorder_enter rank=5 reverse=1 rmx=0
    nodes=[...:0:-1 ...:1:-1 ...:2:-1 clusterc4236:3:-1 cluster_4246:4:-1 c4051:5:-1]
Py: reorder_enter rank=6 reverse=1 rmx=0
    nodes=[clusterc4163:0:-1 clusterc4237:1:1024 cluster_4246:2:1024 c4149:3:384]
```

(Python's extra prefix nodes are sibling-cluster skeletons at the
same rank, gated out of the median sort with mval=-1.)

The orders for the three in-scope nodes match exactly:
`clusterc4237:1, cluster_4246:2, c4149:3`.

**The mval for `clusterc4237` diverges**: C computes 1088, Python
computes 1024 (VAL = 256 × order + port.order).  `c4149=384` and
`cluster_4246=1024` match.

### Consequence

- C: 384 < 1024 < 1088 — unambiguous sort, rank-6 reorder lands on
  `[c4149:1, cluster_4246:2, clusterc4237:3]`.
- Python: 384 < 1024 = 1024 — the `clusterc4237`/`cluster_4246`
  pair is tied.  Under `reverse=1`, the reorder bubble-sort treats
  the tied pair as swappable (`p1 >= p2 && reverse`), producing
  oscillating swap storms for the pair (visible in the trace as
  multiple `swapped=1` lines on the same pair back-and-forth).

That rank-6 instability cascades back to rank 5's transpose cost
function: because Python's rank-6 order ends up with
`clusterc4237` at a different position than C's, the crossing
count for `(clusterc4236, cluster_4246)` at rank 5 comes out
0 (no crossing) in Python versus 100 (one crossing × CL_CROSS) in C.

### Why the mval differs

Both engines compute `mval = median(VAL(neighbor, port))` on the
adjacent rank below.  `clusterc4237_6`'s only in-scope rank-7
neighbor is `clusterc4242_7`.  C reports the median as 1088,
Python as 1024.

Likely sources (to investigate next session, in order of likelihood):

1. **Extra neighbors in C's scope**: C's `build_skeleton` +
   `install_cluster` may place additional virtual chain edges on
   the skeleton that Python's `_build_skeleton` doesn't replicate.
   If the median spans 2+ positions, even one missing neighbor
   shifts the result.
2. **Port offsets**: `VAL = 256 × order + port.order`.  An 88-point
   delta is too large for a port offset (typical port orders are
   small integers), so probably (1) not (2).
3. **Edge merging / weight differences**: `interclrep` /
   `merge_chain` might route an edge through a different skeleton
   node in C vs Python.

### Recommended next step

Add per-node median-positions dump on the `d5_step` channel
(print the `positions[]` list that feeds the median for
`clusterc4237_6`) in both engines and diff.  That will show which
specific neighbor positions Python is missing or double-counting.

## Session 13: port-propagation fix lands (2026-04-23)

Continuation of session 12.  Added `[TRACE d5_step] medians_node`
to both engines dumping the per-node `positions[]` list fed into
the median computation.  Diffed the first call for `clusterc4237_6`
at `r0=6 r1=5` (cluster_4250's expand phase):

```text
C:       vals=[768, 1408]  → median = 1088
Python:  vals=[768, 1280]  → median = 1024
```

Both engines see two incoming edges.  The first neighbour (768)
matches byte-for-byte — that's the `c4236 → c4237` skeleton chain
edge at rank-5 order 3, port offset 0.

The second diverges by 128 = `MC_SCALE / 2`.  C has `1408 =
256 × 5 + 128`; Python has `1280 = 256 × 5 + 0`.  The edge is
`c4051:Out0 → c4237:In1` (directly from aa1332.dot).  C picks up
the `Out0` port offset (128); Python loses it.

### Root cause

Python's `mc_fg_out` / `mc_fg_in` build pass substitutes
hidden-real-node endpoints with their parent cluster's skeleton
(`_skel_sub`).  The edge `c4051 → c4237` becomes
`c4051 → _skel_clusterc4237_6` in the scoped fast graph.  The
port lookup in `cluster_medians` keys on that substituted pair —
but `layout._edge_port_lookup` was only populated with
*original* `(tail, head)` pairs, so the lookup missed and the
tail port fell back to empty.  `mval_edge("", ...)` returns
`MC_SCALE × order + 0`, losing the 128-point offset.

### Fix

In `cluster_mincross_expand` (mincross.py ~line 1165), when we
substitute `(t, h)` → `(t_sub, h_sub)`, propagate the original
edge's port identifiers onto the substituted key — but only on
the *non-substituted* side.  A substituted endpoint stands in for
a whole cluster, matching C's `make_chain` / `interclrep` which
rewrites the edge into a chain where the skeleton side has no
port.  So:

```python
hp, tp = _edge_port_lookup[(t, h)]
if t_sub != t: tp = ''   # skeleton tail — no port
if h_sub != h: hp = ''   # skeleton head — no port
if hp or tp:
    _edge_port_lookup[(t_sub, h_sub)] = (hp, tp)
```

Also eagerly populate `_edge_port_lookup` before the mc_fg build
so the copy can find the original entry (previously cluster_medians
populated it lazily — *after* mc_fg construction).

### Measurement

- Python's `clusterc4237_6` mval now reports **1088** (was 1024),
  byte-for-byte matching C's `[768, 1408]` input list.
- The tied-pair instability at rank 6 is gone — reorder sorts
  unambiguously to `[c4149:1, cluster_4246:2, clusterc4237:3]`
  matching C.
- The cascade swap `c4051 ↔ _skel_cluster_4246_5` at rank 5
  no longer fires (transpose_cmp now reports `c_before=0
  c_after=0 swapped=0` instead of `c_before=1 c_after=0
  swapped=1`).
- Test suite: 1137/1137 pass, D5 regression unchanged.
- aa1332 residual cluster-pair crossings still at 4 (down from
  a previous visual count of 7 in session 10, pre-scoped-counter
  fix) — the mincross-level alignment closes the rank-5/6
  divergence but other ranks still diverge.  Another session
  can extend the medians_node diff to the remaining ranks.

### Files touched

- `lib/dotgen/mincross.c` — `medians_node` trace emission inside
  `medians()` (gated on `d5_step`, emits only for cluster skeletons
  and real nodes).
- `gvpy/engines/layout/dot/mincross.py` —
  - `cluster_medians`: matching `medians_node` trace emission.
  - `cluster_mincross_expand`: eager `_edge_port_lookup`
    population + substituted-pair port propagation with
    skeleton-side suppression.

## Session 14: early-exit investigation (2026-04-23)

Investigation into the next divergence after session 13's port-
propagation fix.  Diffed `medians_node` traces across both engines
on aa1332 and found 307 differences, many of them cluster skeletons
present in C's trace but missing entirely from Python's (ONLY-C
entries for `cluster_6407`, `clusterc4143`, `clusterc6722`, etc.).

### Investigation

Traced the flow: cluster_6407 IS built by Python's `_build_skeleton`
and gets spliced into `layout.ranks` during cluster_6409's expand.
But when cluster_6409's inner mincross loop calls `cluster_medians`,
the skeleton's mval is never computed.

Found the cause: Python's expand-phase mincross has
```python
for _pass in range(max_iter):
    if cur_cross == 0:
        break
```
and `_scoped_cross()` returns 0 for many cluster subgraphs, so the
loop exits on `_pass=0` — no medians, no reorder, no transpose.

### Two hypothesis tested

**Option 2** (remove the early-exit entirely, let MIN_QUIT stop it
naturally, assuming that's what C does) — *turned out to be wrong
about C*: `lib/dotgen/mincross.c:1088` has the exact same
`if (cur_cross == 0) break;` check.  Python's behavior matches C.

Corpus measurement anyway, for the record:

| Variant | Total Py cross | Comparable delta | Extra timeouts |
|---|---:|---:|---:|
| Baseline | 224 | — | — |
| Option 2 (no cur_cross=0 break) | 70 | −9 | +1 (1879.dot) |
| Option 1 (force one pass then break) | 90 | +12 | +2 (1879, 2239) |

Net regressions in both: 2620.dot (7 → 18 in Option 2, 7 → 39 in
Option 1), 2796, 1436, 1213-2, aa1332.  The "improvement" from
big drops on 1472 (27 → 8) and 1332_ref (13 → 4) is offset by
2620's explosion + new timeouts.

### Root cause of the ONLY-C medians_node entries

The 307 diffs are NOT from an iteration-count mismatch.  They're
from **different initial scoped crossing counts** between the two
engines — C's `ncross()` returns >0 for some clusters where
Python's `count_scoped_crossings` returns 0, so C enters the
iteration loop and computes medians while Python bails.

Topologically the crossings should be the same.  The divergence is
likely in edge set or weight:
- C's `ncross` uses `ED_xpenalty × ED_xpenalty` (weighted).  For
  skeleton chain edges, `ED_xpenalty = CL_CROSS`.  A single weighted
  crossing = 100 × 100 = 10000 (or similar), which is >0 even though
  unweighted count may be 1 and rounds to "some crossings present".
- Python's `count_scoped_crossings` counts topologically (1 per
  crossing).  If it returns 0, there really are zero crossings —
  C should also see 0.  Either C sees phantom crossings from extra
  edges in `ND_in`/`ND_out`, or Python is missing some.

The real divergence to chase is the edge content of `mc_fg_in` /
`mc_fg_out` vs C's `ND_in` / `ND_out` for the same scope.

### Decision

Reverted both options.  The `cur_cross == 0` check is correct and
matches C.  Next session should diff the cluster-scoped edge sets
between engines on a specific cluster where Python reports 0 but
C sees >0 (e.g. cluster_6409 during aa1332).

## Session 15: exit-edge filter fix (2026-04-23)

Continuation of session 14's investigation of the
`Python sees 0 where C sees >0` scoped-crossing divergence.

### Method

Added matching `[TRACE d5_edges]` emissions in both engines that
dump the cluster-scoped fast graph (`mc_fg_out` in Python,
`ND_out` in C) at the start of each cluster subgraph's expand
mincross, keyed on cluster name, so they can be line-diffed.

### Finding

For cluster_6409 on aa1332:

```text
Both engines (5 shared):
  cluster_6407@r14 → cluster_6407@r15   (chain)
  cluster_6407@r15 → cluster_6407@r16   (chain)
  cluster_6407@r16 → cluster_6407@r17   (chain)
  cluster_6407@r17 → clusterc6408@r18   (inter-child chain)
  clusterc6384@r14 → cluster_6407@r15   (inter-child chain)

Only in C (1):
  clusterc6408@r18 → clusterc6410@r19   (exit edge — leaves cluster_6409)
```

The extra C edge is an **exit edge** — `clusterc6408` is a child
of cluster_6409 at rank 18; `clusterc6410` is a sibling of
cluster_6409 at rank 19 (both under cluster_6754).  C's `ND_out`
naturally retains this edge because class2 / interclrep / make_chain
ran it through the cluster's skeleton even though the head lands
outside the subgraph's rank range.

### Why Python was missing it

`mincross.py` around line 1167, the mc_fg_out build had:

```python
if not t_in or not h_in:
    t_r = layout.lnodes[t].rank
    h_r = layout.lnodes[h].rank
    if t_r < min_r or t_r > max_r:  continue
    if h_r < min_r or h_r > max_r:  continue
```

`h_r=19 > max_r=18` for cluster_6409, so the filter rejected the
edge entirely.  That in turn made `count_scoped_crossings` return
0 for cluster_6409, and the iteration loop exited on `cur_cross=0`
without running medians — cascading through session 14's observed
307 `medians_node` divergences.

### Fix

Relax the filter by 1 rank in each direction so boundary-crossing
exit edges survive:

```python
if t_r < min_r - 1 or t_r > max_r + 1:  continue
if h_r < min_r - 1 or h_r > max_r + 1:  continue
```

and extend `count_scoped_crossings`'s rank iteration by 1 on each
side so the boundary (max_r, max_r+1) is actually counted:

```python
for r in range(min_r - 1, max_r + 1):
    ...
```

### Measurement

cluster_6409's edge set now matches C byte-for-byte (6=6 edges,
empty diff).

Corpus audit (196 → 197 graphs, PYTHONHASHSEED=0, 60s timeout):

| Metric | Baseline | After fix |
|---|---:|---:|
| Total Py crossings | 224 | 51 |
| Python regressions | 11 | 9 |
| Clean-on-both-sides | 161 | 162 |

Per-file (on 170 shared):

- Improved (4): **1472.dot −19**, 1332_ref.dot −9, 1332.dot −1, 2239.dot −1 (went fully clean)
- Regressed (4): 1436.dot +4, 2796.dot +2, 1213-2.dot +1, aa1332.dot +1
- Unchanged: 162

Net on comparable files (excluding 1879/2620 timeouts):
**72 → 51 = −21 crossings (−29%)** — first non-trivial corpus
improvement since session 11.

Cost: 2620.dot newly times out (was 7 crossings).  The extra
iteration work from including exit edges in the fast graph pushes
it past the 60s per-side budget.  Candidates for future work:
optimise `count_scoped_crossings` inner loop, or raise timeout.

## Session 16: post-refactor + self-skeleton exclusion (2026-04-23)

### Refactor: cached output views

Ten call sites across six helpers rebuilt the same virtual-node /
virtual-edge filters (`_apply_size`, `_translate_bb_to_origin`,
`_apply_center`, `_concentrate_edges`, `_compute_xlabel_positions`,
`_finalize_graph_label`, `_write_back`, `_to_json`).  Added
``_rebuild_output_views()`` called once after phase 3 and replaced
all sites with reads from three cached attributes:
``_output_nodes_list``, ``_output_nodes_dict``, ``_output_edges``.

Corpus audit: **no drift** on any existing graph.  1879.dot and
2620.dot newly complete (were PY_TIMEOUT) thanks to this + the
fg_out forwarding fix from earlier in the session.

### fg_out forwarding to cluster_transpose

Session 13 wired scoped pair-crossing counting (O(degree)) into
``cluster_transpose`` for the expand phase.  But ``run_mincross``
(initial pass on the collapsed graph) and ``remincross_full``
(final pass) still called ``_cluster_transpose`` without the
``fg_out=`` / ``fg_in=`` kwargs, so the inner loop fell back to
``count_crossings_for_pair`` — O(E) per pair.

Both call sites already built a root-scope fast graph (lines
482-496 and 589-599).  One-line fix: forward it.

2620.dot: **58.7s → 23.2s** wall time, a 2.5× speedup.  Now
completes under the 60s audit budget; was PY_TIMEOUT after
session 15.

### Class-level mutable dicts → __init__

Audit flagged ``_node_mval`` and ``_port_order_cache`` defined at
class scope, shared across all DotGraphInfo instances.
``_edge_port_lookup`` right next to them was already per-instance
in ``__init__`` — so this was an inconsistent pre-existing latent
bug.  Moved both to ``__init__``.  No behavioral change (layouts
always overwrote mvals per-node), but it closes the memory-leak
and port-collision risks in long-lived processes (GUI, pytest).

### Self-skeleton exclusion

Diffed ``mc_fg_out`` content for cluster_4250 on 1332.dot vs C's
``ND_out`` and found **5 extra edges** in Python.  Two were
``_skel_cluster_4250_5 → _skel_clusterc4237_6`` style edges —
cluster_4250's OWN skeleton appearing as a tail in its OWN expand
scope.  Leftover chain edges from when cluster_4250 was collapsed,
never cleaned up when it was re-expanded.

Fix: skip any edge where either endpoint is in ``skeleton_nodes
[cl_name].values()`` — the cluster's own rank-leader skeleton set.

Corpus measurement: **0 improved, 0 regressed on 174 shared files.**
Pure cleanup — the offending edges were being written into scope
but happened not to affect reorder decisions.  Bonus: 2470.dot
newly completes (was PY_TIMEOUT) with 17 crossings.  Unit tests:
1137/1137 still pass.

Three other extra edges remain in cluster_4250's scope (intra-
cluster c4147→c4149, sibling-cluster clusterc4145→c4149,
skeleton-vs-real head naming clusterc4249→clusterc4251 vs
clusterc4249→c4251).  Each is a separate investigation thread.

## Session 17: dedup_cluster_nodes tie-break (reverted, 2026-04-23)

Task #147 investigated why 1332.dot cluster_4250 has 5 extra edges
in its scoped fast graph vs C.  Session 16's self-skeleton
exclusion cleared 2 of them; this session chased a third.

### Root cause (confirmed)

`dedup_cluster_nodes` picked cluster_4250 as the "home" of c4051,
not clusterc4051 (the singleton wrapper that actually declares it).
Both are at tree-depth 1 under cluster_4252, so the depth
tie-breaker stayed with the first-iterated cluster.  Result:
clusterc4051 ended up with `nodes=[]` while cluster_4250 falsely
claimed c4051 (added by edge reference, not by declaration).

### Attempted fix

Replaced the depth-only tie-break with size-first, depth-fallback:
smaller cluster wins on ties, matching the DOT convention that
`cluster<node>` singleton wrappers own their named node.

### Corpus result

- 173 unchanged, 0 improved, **1 regressed** (aa1332 3 → 6)
- 2239.dot newly PY_TIMEOUT (was clean at 0 crossings)

The fix is theoretically correct — clusterc4051 does declare c4051
and cluster_4250 only references it in an edge — but the
downstream cascade penalizes aa1332 and pushes 2239 past its 60s
budget.  Singleton-wrapper nodes get walled off into their own
skeleton, which constrains mincross more than the legacy
fallthrough behavior where the outer cluster had them as direct
members.

### Reverted

Back to depth-only tie-break.  A real fix needs to distinguish
declared-vs-referenced at parse time (track which nodes were
actually declared inside each subgraph vs picked up via edge
references).  That's invasive — defer.

## Session 18: scoped _skel_sub (landed), foreign-skel filter (reverted) — 2026-04-24

### Scoped _skel_sub (landed)

`_skel_sub` in the mc_fg_out build was substituting *any* hidden
real node to its cluster skeleton, regardless of whether the
hiding cluster was a direct child of the currently-expanding
``cl_name``.  On 1332.dot cluster_4250's expand, this pulled
`c4251` (hidden by clusterc4251, a *sibling* of cluster_4250)
to ``_skel_clusterc4251_11`` — producing an edge
``clusterc4249 → _skel_clusterc4251_11`` where C has
``clusterc4249 → c4251``.

Fix: only substitute when the hider is in
``children_of[cl_name]``.  A sibling cluster's skeleton isn't in
this scope; the real node is what belongs.

Corpus: **0 drift** on all 175 shared files.  Clean cleanup.

### Foreign-skeleton filter (reverted)

Extended the fix to also exclude edges where either endpoint is
a `_skel_*` for a cluster not in cl_name's {self, direct-children}
set.  This matched more aggressive interpretation of "foreign"
skeleton chain edges built by Python's inter-cluster chain
builder that C doesn't have.

Corpus result: **+8 total, 2 improved (1332 −1, aa1332 −1) but
1332_ref regressed +10.**  The "duplicate" skeleton-chain edges
being filtered were actually load-bearing on 1332_ref's mincross.
Reverted.

### cluster_4250 remaining divergence

Down to 2 extra edges now, both with mis-attributed nodes
(c4145→c4149, c4147→c4149) that trace back to the declared-vs-
referenced parser issue (task #148).  Can't cleanly fix without
parser-level changes.

## Session 19-20: declared-vs-referenced + tuning attempts (2026-04-24)

### Implementation (session 19)

Per ``Docs/declared_vs_referenced_proposal.md`` (task #148):

- ``Graph.add_node`` accepts a new ``declared: bool = True`` flag.
  When ``False``, the node is created in the root graph (if missing)
  but NOT added to ``self.nodes`` of the current subgraph.  Matches
  C cgraph's agedge + agnode where edge references don't establish
  cluster membership — only ``node_stmt`` declarations do.
- Visitor ``_resolve_node_id`` calls ``add_node(name, declared=False)``
  for edge-endpoint resolution.
- ``Graph.add_edge`` calls ``add_node(..., declared=False)`` for both
  tail and head.
- 4 regression tests in ``tests/test_declared_vs_referenced.py``.

Direct probe on 1332.dot post-parse:
- ``clusterc4051.nodes = ['c4051']`` ✓ (was ``[]`` pre-fix)
- ``clusterc4149.nodes = ['c4149']`` ✓ (was ``[]`` pre-fix)
- ``cluster_4250.nodes`` no longer contains c4051 / c4149 ✓

### Corpus impact

- 173/175 files unchanged
- 3 regressed: aa1332 3→5 (+2), 1332 1→3 (+2), 2183 0→1 (+1)
- Net: 172 → 177 (+5 crossings)

The fix is semantically correct (matches C) but practically pushes
mincross into worse local minima.  Sibling-declared nodes like
c4051 are now walled off in their singleton clusters
(``clusterc4051``) which skip their own mincross loop
(``len(cl_ranks) < 2``).  Their position is fixed at build_ranks
output and never refined — reorder-time mval is set to -1 because
they aren't in any cluster's ``cl_node_set``.

### Tuning attempt 1 (session 19): wide neighbour augmentation

Added all edge-neighbour nodes within the cluster's rank range to
``cl_node_set`` during expand mincross.  Goal: re-grant reorder
flexibility to formerly-polluted-now-orphaned nodes.

Result: **net +14 crossings, 5 regressions**:
- 2796: 15 → 37 (+22)
- 1332_ref: 4 → 11 (+7)
- 1332: 1 → 3 (+2)
- 2183: 0 → 1 (+1)
- 2239: 0 → 1 (+1)
- 2470, 2620 newly timed out.

The wider scope confused the median heuristic — too many sibling-
cluster nodes in the reorder pool.  Reverted.

### Tuning attempt 2 (session 20): narrow singleton augmentation

Restricted the augmentation to outsiders whose home cluster is a
SINGLETON (1 node, 1 rank — skips its own mincross loop).  This
should be safer: only add nodes that genuinely have nowhere else
to be reordered.

Result: still net regression (1332 3→4, 2796 15→25, aa1332 5→4).
Targeted is better than wide but neither beats the no-augmentation
baseline.

Reverted.  Decision: keep declared-vs-referenced active (option 2,
+5 corpus regression), accept that Python's mincross heuristic
doesn't benefit from the wider reorder scope C uses.  Future work
could explore a different angle — e.g., a final "loose-node"
reorder pass over orphaned singleton-cluster members within their
rank — but the open-ended nature of the tuning makes it a
non-priority.

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
