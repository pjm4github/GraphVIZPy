# Top-Down Port Plan: C `lib/ortho/` → `gvpy/engines/layout/ortho/`

Implementation plan for "option 1" from `TODO.md` §5a — a faithful port of
C Graphviz's orthogonal channel router into GraphvizPy.

Last updated: 2026-04-19.

---

## 0. Context snapshot

Verified facts driving this plan:

- **C source sizes** (verified via `wc -l`): `rawgraph.c` 100, `sgraph.c`
  191, `trapezoid.c` 898, `partition.c` 774, `maze.c` 517, `ortho.c` 1465,
  `fPQ.c` 119. Total ~4064 lines. Public headers confirm the stack is
  exactly `ortho → maze → partition → trapezoid`, `ortho → sgraph →
  rawgraph`, plus `fPQ` (priority queue used by `sgraph.shortPath`) as a
  tiny leaf dependency that ports with `sgraph`.
- **C entry point** at `ortho.c:1162` `void orthoEdges(Agraph_t *g, bool
  useLbls)`. Internal orchestration (lines 1204–1289): `mkMaze(g)` →
  per-edge `addNodeEdges`/`addLoop` + `shortPath` + `convertSPtoRoute` →
  `extractHChans` + `extractVChans` → `assignSegs` → `assignTracks` →
  `attachOrthoEdges`. The Python `ortho_edges` must reproduce this
  sequence.
- **Python dispatch** currently at `gvpy/engines/layout/dot/dotsplines.py:
  465-466` and `:482-483`, both per-edge. Must be folded into a single
  batch call sited just before the first dispatch loop.
- **Available building blocks (do not reuse).** `gvpy/engines/layout/
  pathplan/` and `common/` are ported but implement different algorithms
  than `lib/ortho/`. The whole point of option 1 is byte-for-byte parity
  with the C algorithm — do not "simplify" by routing through
  `pathplan.shortest`.

## 1. Dependency map

| C file | LOC | Public surface (from `.h`) |
|---|---:|---|
| `rawgraph.h/.c` | 100 | `rawgraph`, `vertex`, `adj_list_t`; `make_graph`, `free_graph`, `insert_edge`, `remove_redge`, `edge_exists`, `top_sort` |
| `sgraph.h/.c` | 191 | `snode`, `sedge`, `sgraph`, `pq_t`; `createSGraph`, `freeSGraph`, `initSEdges`, `createSNode`, `createSEdge`, `shortPath`, `gsave`, `reset` |
| `fPQ.h/.c` | 119 | `pq_t`, `PQgen`, `PQfree`, `PQinit`, `PQupheap`, `PQdownheap`, `PQinsert`, `PQremove` — internal to `sgraph`, port alongside it |
| `trap.h` + `trapezoid.c` | 898 | `segment_t`, `trap_t`, `traps_t`; `construct_trapezoids(int, segment_t*, int*)` — Seidel's algorithm |
| `partition.h/.c` | 774 | `boxf *partition(cell *cells, size_t ncells, size_t *nrects, boxf bb)` |
| `maze.h/.c` | 517 | `cell`, `maze`; `mkMaze(graph_t*)`, `freeMaze`, `updateWts`; `M_RIGHT/TOP/LEFT/BOTTOM`, `MZ_*`, `IsNode/IsVScan/IsHScan/IsSmallV/IsSmallH` |
| `structures.h` | — | shared types `segment`, `paird`, `pair`, `channel`, `route`, `bend` — port as `ortho/structures.py` first, imported by everyone |
| `ortho.h/.c` | 1465 | `orthoEdges(g, useLbls)` public; `convertSPtoRoute`, `extractHChans/VChans`, `assignSegs`, `assignTracks`, `attachOrthoEdges`, `addNodeEdges`, `addLoop` internal |

## 2. Ordered work breakdown

Leaves first. Rollout gated behind `GVPY_ORTHO_V2=1` env var; default path
remains the existing Z-router until Phase 7.

### Phase 0 — Scaffolding (~80 lines, small)

- Create `gvpy/engines/layout/ortho/` with `__init__.py` and
  `structures.py` (port `structures.h` dataclasses: `paird`, `pair`,
  `pair2`, `bend` enum, `segment`, `route`, `channel`).
- Add `ortho_edges(layout, *, use_lbls: bool) -> dict[id, list[pointf]]`
  stub in `ortho/ortho.py` that returns `{}` and logs
  `[TRACE ortho-route] entry nodes=<n> edges=<n>`.
- Wire call from `phase4_routing_body` under the env-var flag; when flag
  is off, fall through to the legacy Z-router unchanged.

**Validate:** pytest green (stub is no-op); `GVPY_ORTHO_V2=1 python -m gvpy
14.dot` produces the trace line. No crossings change yet.

### Phase 1 — `rawgraph.py` (~120 lines, small)

- Port `vertex`, `rawgraph`, `make_graph`, `insert_edge`, `remove_redge`,
  `edge_exists`, `top_sort` (DFS topological sort with WHITE/GRAY/BLACK
  coloring).
- **Trace tag `[TRACE ortho-rawgraph]`** (only at `top_sort` entry/exit
  — creation/insertion are too noisy):
  - `[TRACE ortho-rawgraph] topsort n=<nvs> order=<comma-separated
    topsort_order indices>`

**Validate:** unit test mirroring a hand-built 6-node DAG against C. No
integration test yet.

### Phase 2 — `fpq.py` + `sgraph.py` (~320 lines, medium)

- Port `fPQ.c` (binary-heap PQ keyed on `snode.n_val`).
- Port `sgraph.c` (`createSGraph`, `createSNode`, `createSEdge`,
  `initSEdges`, `gsave/reset`, `shortPath` Dijkstra).
- **Trace tag `[TRACE ortho-sgraph]`**:
  - At `shortPath` entry: `[TRACE ortho-sgraph] shortpath from=<idx>
    to=<idx> nnodes=<n> nedges=<n>`.
  - At exit (after `n_dad` backtrack): `[TRACE ortho-sgraph] shortpath
    result cost=<n_val> path=<v0,v1,...,vn>`.
  - Do NOT trace PQ pushes/pops — noisy, bugs hide in edge weights, which
    the final path captures.

**Validate:** unit test on a 10-node hand-built sgraph; compare Dijkstra
output against a NetworkX reference.

### Phase 3 — `trapezoid.py` (~900 lines, large)

- Port `trap.h` (constants, `C_EPS`, `fp_equal`, `dfp_cmp`,
  `greater_than`) and `trapezoid.c` (Seidel's randomized trapezoidation:
  `construct_trapezoids`, `locate_endpoint`, `thread_segment`,
  `merge_trapezoids`). Keep variable names and branch order identical.
- **Trace tag `[TRACE ortho-trapezoid]`** — boundaries only:
  - On entry: `[TRACE ortho-trapezoid] construct nsegs=<n>`.
  - On exit: `[TRACE ortho-trapezoid] construct ntraps=<n>` and per trap
    `[TRACE ortho-trapezoid] trap i=<idx> lseg=<n> rseg=<n> hi=<x,y>
    lo=<x,y> u0=<n> u1=<n> d0=<n> d1=<n>` — precision divergences will
    surface here.

**Validate:** hand-built 4-rect obstacle set through both C (add
`fprintf` in `lib/ortho/trapezoid.c`, rebuild via CLion cmake) and Python.
`tools/compare_traces.py` zero diffs before proceeding.

### Phase 4 — `partition.py` (~780 lines, large)

- Port `partition(cell *cells, size_t ncells, size_t *nrects, boxf bb)`.
- **Trace tag `[TRACE ortho-partition]`**:
  - On entry: `[TRACE ortho-partition] ncells=<n> bb=<LLx,LLy,URx,URy>`.
  - On exit: `[TRACE ortho-partition] nrects=<n>` + per-rect
    `[TRACE ortho-partition] rect i=<idx> bb=<LLx,LLy,URx,URy>` —
    ordering matters, maze divergence starts here.

**Validate:** `14.dot`, then `144_ortho.dot`. Rebuild C `dot` with
partition fprintf shims, compare. Rect counts must agree exactly.

### Phase 5 — `maze.py` (~550 lines, medium)

- Port `cell`, `maze`, `mkMaze`, `freeMaze`, `updateWts`, `M_*` side
  constants, `MZ_*` flags, `IsNode/IsVScan/IsHScan/IsSmallV/IsSmallH`
  predicates.
- `mkMaze` takes a GraphvizPy layout object rather than `graph_t*`. The
  adapter reads `lnode.x`, `lnode.y`, `lnode.w`, `lnode.h`, cluster
  bboxes (via `GD_bb` equivalent), and `GD_nodesep`. This is the only
  place where the C boundary crosses into GraphvizPy-specific objects.
- **Trace tag `[TRACE ortho-maze]`**:
  - `[TRACE ortho-maze] mkmaze entry gnodes=<n> bb=<...>`.
  - `[TRACE ortho-maze] mkmaze exit ncells=<n> ngcells=<n>
    sg_nnodes=<n> sg_nedges=<n>`.
  - Per gcell: `[TRACE ortho-maze] gcell i=<idx> bb=<...>
    sides=<r_snode,t_snode,l_snode,b_snode>`.
  - Per cell: `[TRACE ortho-maze] cell i=<idx> bb=<...> flags=<hex>`.

**Validate:** `14.dot`, `144_ortho.dot`, `1408.dot`. Cell/gcell counts,
sgraph node/edge counts must match C exactly.

### Phase 6 — `ortho.py` core (~1000 lines, large)

- Port `ortho.c` minus `emitEdge/emitSearchGraph/emitGraph` debug
  helpers. Sub-order: helpers (`cellOf`, `midPt`, `sidePt`, `setSeg`,
  `edgeLen`, `edgecmp`, `coordOf`); `convertSPtoRoute`; `addNodeEdges`,
  `addLoop`; `extractHChans`, `extractVChans`; `assignSegs`;
  `assignTracks` (channel-coloring + `rawgraph` topsort);
  `attachOrthoEdges`; public `ortho_edges`.
- **Trace tag `[TRACE ortho-route]`**:
  - `[TRACE ortho-route] entry n_edges=<n>`.
  - After qsort by `edgeLen`: `[TRACE ortho-route] edges sorted=<list of
    (tail_name,head_name,d)>`.
  - Per edge, after `convertSPtoRoute`: `[TRACE ortho-route] edge
    i=<idx> tail=<n> head=<n> nsegs=<n> segs=[(isVert,comm_coord,p1,p2),
    ...]`.
  - After `extractHChans/VChans`: `[TRACE ortho-route] channels h=<nh>
    v=<nv>`.
  - After `assignTracks`: `[TRACE ortho-route] tracks assigned ok=<bool>`.
  - After `attachOrthoEdges`, per edge: `[TRACE ortho-route] waypoints
    tail=<n> head=<n> pts=[(x,y),...]`.

**Validate:** full ladder — `14.dot`, `144_ortho.dot`, `1408.dot`,
`1447_1.dot`, `2620.dot`. Rebuild C with corresponding fprintf shims,
run both sides, diff.

### Phase 7 — Dispatch integration + legacy fallback (~60 lines, small)

- Restructure `phase4_routing_body`:
  - Just before the `for le in sorted_real_edges:` loop
    (`dotsplines.py:454`), insert:
    ```python
    ortho_routes = {}
    if layout.splines == "ortho":
        from gvpy.engines.layout.ortho import ortho_edges
        ortho_routes = ortho_edges(
            layout, use_lbls=layout.has_edge_labels
        )
    ```
  - Replace both `elif layout.splines == "ortho":` branches with: look up
    `ortho_routes.get(id(le))`; if present, assign `le.points`; else
    fall through to legacy `layout._ortho_route(le, tail, head)`.
  - Gate the whole `ortho_edges` call behind
    `os.environ.get("GVPY_ORTHO_V2") == "1"`; unset → `ortho_routes = {}`
    and dispatch behaves exactly as today.
- Keep `ortho_route`, `_ortho_safe_midy`, `_ortho_member_clusters`,
  `_ortho_any_obstacle_at` in `dotsplines.py` untouched as fallback.

**Validate:** full 836-test suite passes with flag off **and** on.
`tools/count_cluster_crossings.py` on all 17 ortho `.dot` files. Gate:
`2620.dot` ≤ 9, others remain at 0.

### Phase 8 — Flag flip (minimal)

Flip the default. Check becomes
`os.environ.get("GVPY_ORTHO_LEGACY") != "1"` so V2 is default, legacy is
opt-in. Retain legacy code for two release cycles, then delete.

## 3. Instrumentation summary — C-side shim locations

Add `fprintf(stderr, ...)` at these call sites, rebuild with the CLion
cmake command. Never change algorithm code — only observation points.

- `lib/ortho/rawgraph.c::top_sort` — entry/exit.
- `lib/ortho/sgraph.c::shortPath` — entry/exit (one emit each).
- `lib/ortho/trapezoid.c::construct_trapezoids` — entry/exit, one emit
  per trap.
- `lib/ortho/partition.c::partition` — entry/exit, one emit per rect.
- `lib/ortho/maze.c::mkMaze` — entry/exit, one pass over `cells`/
  `gcells`.
- `lib/ortho/ortho.c::orthoEdges` — entry, post-sort, per-edge
  post-`convertSPtoRoute`, post-`extract{H,V}Chans`, post-`assignTracks`,
  per-edge inside `attachOrthoEdges`.

Tags match Python counterparts so `tools/compare_traces.py trace_c.txt
trace_py.txt` produces narrow diffs.

## 4. Known risks and decision points

1. **Seidel trapezoidation precision.** `trap.h` uses `C_EPS=1e-7` and a
   randomized order. C has a hidden dependency on segment-insertion order
   via `rand()`. Mitigations: (a) make the Python port deterministic by
   inserting in input order (C does this when `DEBUG`; check
   `init_query_structure`), (b) if traces diverge, compare per-trap
   `root0/root1` Q-tree indices — divergence there is usually
   float-epsilon. **Off-ramp:** if trapezoid port stalls >3 days, fall
   back to option 3 (keep `rawgraph.py`, `sgraph.py`, wire them to
   `pathplan/shortest.py` visibility triangulation instead of porting
   Seidel).
2. **`mkMaze`'s `graph_t` coupling.** `maze.c:mkMaze` calls `GD_bb`,
   `ND_coord`, `ND_lw`, `ND_rw`, `ND_ht`, `GD_clust`, `GD_nodesep`, and
   stashes a `cell*` in `ND_alg(n)`. Python equivalents: `layout.bb`,
   `lnode.coord`, `lnode.lw/rw/ht`, `layout.clusters`, `layout.nodesep`,
   and a `{id(lnode): cell}` dict instead of `ND_alg`. Confirm these
   accessors before Phase 5.
3. **`assignTracks` channel coloring.** Uses `rawgraph.top_sort` on an
   interference graph per channel. If Phase 1's topsort order differs
   from C's (DFS visits children in insertion order — Python dict
   iteration is insertion-order since 3.7, matches C adj list), track
   assignment differs. Likeliest source of "Python routes correctly but
   with different corner placements" bugs.
4. **Cluster bbox semantics.** Success criterion hinges on `mkMaze`
   treating clusters as obstacles for non-member edges. `lib/ortho/
   maze.c` iterates `GD_clust` and adds cluster bboxes as `cells`.
   Confirm `layout.clusters` has corresponding bboxes computed before
   Phase 4 runs.
5. **Test-data leakage between flag states.** If the 17 ortho fixtures'
   expected-output files were captured from the legacy Z-router,
   flipping V2 regresses them by definition. Before Phase 7, re-baseline
   against `dot.exe` in a separate commit so the diff is auditable.

## 5. Build command reference (load-bearing)

Per `CLAUDE.md`, the only way to rebuild C `dot` after adding trace
shims:

```powershell
$env:PATH = "C:\Program Files\JetBrains\CLion 2023.2.2\bin\mingw\bin;" + $env:PATH
& "C:\Program Files\JetBrains\CLion 2023.2.2\bin\cmake\win\x64\bin\cmake.exe" `
    --build "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\cmake-build-debug-mingw" `
    --target dot
```

Do not invent alternatives.

## 6. Effort estimate

Python-side line counts: rawgraph ~120, fPQ+sgraph ~320, trapezoid ~900,
partition ~780, maze ~550, ortho ~1000, structures+scaffolding ~200,
dispatch patch ~60. **Total ~3930 lines.**

Per-phase walltime at steady state: P0–P2 one day, P3 two–three days,
P4 two days, P5 one–two days, P6 three–four days, P7–P8 one day.
**~10–13 focused days** matching the 1-2 weeks estimate.

## 7. Test file ladder

| File | Lines | Clusters | Role |
|---|---:|---:|---|
| `test_data/14.dot` | 5 | 0 | smoke |
| `test_data/144_ortho.dot` | 10 | 0 | small smoke |
| `test_data/1408.dot` | 31 | 0 | richer, still flat |
| `test_data/1447_1.dot` | 454 | 0 | edge volume |
| `test_data/2620.dot` | 747 | 22 (nested) | success target — 66 → 0 |

Regression sweep before declaring done: all 17 ortho files
(`14, 56, 144_ortho, 1408, 1447, 1447_1, 1658, 1856, 1880, 1990, 2082,
2168_5, 2183, 2361, 2538, 2620, 2643`).
