# Core Module Refactoring

Outstanding work on `gvpy/core/` structure.  See
`CLAUDE.md` for the long-term architecture direction and
`memory/project_view_architecture.md` for the GraphView pattern.

## Split `gvpy/core/graph.py` (1680 → ~800 lines)

**Problem**: `graph.py` mixes the `Graph` class data model with ~400
lines of module-level C-API helper functions and auxiliary classes.
The `Graph` class doesn't start until line 407 — hard to navigate,
hard to diff against C source files.

**Goal**: Split helpers into per-concern files matching C's `lib/cgraph/`
factoring.  `graph.py` keeps only the `Graph` class itself.

### Moves (C-style functions → per-concern files)

| Functions | Target file | C source |
|---|---|---|
| `agedge`, `agidedge`, `agdeledge`, `agfstout`, `agnxtout`, `agfstin`, `agnxtin`, `agfstedge`, `agnxtedge`, `ok_to_make_edge`, `agsubrep` | **`_graph_edges.py`** (join existing EdgeMixin) | `lib/cgraph/edge.c` |
| `subnode_search`, `subedge_search`, `subgraph_search` | **`_graph_apply.py`** (new) | `lib/cgraph/apply.c` |
| `Agcmpgraph`, `agfindhidden` | **`_graph_cmpnd.py`** (new) | `lib/cgraph/cmpnd.c` |
| `agnextseq` | **`_graph_id.py`** (already exists) | `lib/cgraph/graph.c` |
| `gather_all_nodes`, `gather_all_edges`, `gather_all_subgraphs`, `get_root_graph` | **`_graph_traversal.py`** (new) | Python-specific helpers (no C origin) |
| `GraphDict` | Inline in `graph.py` or new `_graph_dict.py` | Python utility |

### Redundancy resolution rule

Some module functions duplicate mixin methods (e.g. `agedge` vs
`Graph.add_edge`).  The duplication is deliberate: the module function
is the C-porting reference, the mixin method is the Pythonic facade.
Keep both, but:

- Module function = authoritative implementation (matches C line-for-line)
- Mixin method = thin Pythonic wrapper that calls the module function
- Document the pairing in the mixin docstring:
  `"""See also: agedge() in _graph_edges.py for the C-style function."""`

### Migration steps

1. Create target files with imports
2. Move functions one concern at a time (edges first, it's the biggest)
3. Update internal call sites (most are `from .graph import X` → `from ._graph_edges import X`)
4. Run full test suite after each concern
5. `graph.py` shrinks to ~800 lines — just the `Graph` class

### Why it matters

- Makes per-phase C-to-Python diffs much easier (match file to file)
- Reduces noise in `graph.py` pull requests
- Aligns with the long-term GraphView architecture where per-concern
  modules are the norm
- Preserves the C-porting layer intact (no deletions, just reorganization)

### Timing

Defer until after:
- Phase 3 NS bug fix (user-visible correctness)
- `DotLayout` → `DotGraphInfo` rename (step 3 of view architecture)
- Phase 3 extraction to `position.py` (step 4)

Do this refactor before continuing to extract more dot phases (rank,
mincross, splines) so that the core is clean when more modules pile on.

## GraphView architecture migration

See `memory/project_view_architecture.md` for the full plan.  Step
completion status:

- [x] **Step 1**: Add `GraphView` base + `graph.views` dict (done 2026-04-12)
- [x] **Step 2**: Add `LayoutView(GraphView)` intermediate base with
      query API + `to_json`/`from_json` round-trip (done 2026-04-12)
- [x] **Step 5**: Fix the NS constraint bug (eliminate 4 overlapping
      nodes in aa1332.dot) — done 2026-04-12.  Two root causes fixed:
      (a) removed per-rank "stable sort by innermost cluster name"
      inside `_ns_x_position` which destroyed mincross ordering;
      (b) disabled "sibling separation" edges (section 3e) whose
      average-order sorting created cycles in the constraint graph
      when sibling clusters interleaved across ranks.  Result: 0
      node overlaps (was 4), 3 residual small NS violations (was 238),
      0 cycles in constraint graph (was 99 cyclic nodes).  All 715
      tests pass.  Verified 14/15 test files (sample) show 0
      overlaps — 1411.dot fails for an unrelated ANTLR parse error
      on `&`/`!` in labels.
- [x] **Step 4 (partial)**: Extract Phase 3 entry point and NS X
      solver into `gvpy/engines/dot/position.py` — done 2026-04-12.
      Created `position.phase3_position(layout)` and
      `position.ns_x_position(layout)` as free functions taking the
      layout instance.  `DotLayout._phase3_position` / `_ns_x_position`
      are now 3-line delegating wrappers.
- [x] **Step 3**: Rename `DotLayout` → `DotGraphInfo`, inherit from
      `LayoutView`, keep `DotLayout = DotGraphInfo` alias — done
      2026-04-12.  Added `view_name="dot"` class attribute so the
      instance attaches under `graph.views["dot"]` by default.  The
      backward-compat alias `DotLayout = DotGraphInfo` lives at the
      bottom of `dot_layout.py`; `gvpy/engines/dot/__init__.py` exports
      both names.  All consumers (tests, renderers, engine registry)
      continue to work unchanged.
- [x] **Step 4b**: Complete extraction of remaining Phase 3 helpers
      into `position.py` — done 2026-04-12.  Moved 11 methods
      (`_compute_cluster_boxes`, `_expand_leaves`,
      `_insert_flat_label_nodes`, `_set_ycoords`, `_simple_x_position`,
      `_median_x_improvement`, `_bottomup_ns_x_position`,
      `_resolve_cluster_overlaps`, `_post_rankdir_keepout`,
      `_center_ranks`, `_apply_rankdir`) as free functions via
      `tools/extract_phase3.py`.  Each class method is now a 3-line
      delegating wrapper.  Final sizes: `dot_layout.py` 5593 lines
      (was 6389 before step 4b, 6389+ before step 4), `position.py`
      1402 lines (was 517 before step 4b).  All 715 tests pass,
      14/14 sampled test files produce clean layouts with 0 overlaps.
      `bottomup_ns_x_position` fallback path verified to run without
      NameError via targeted call.  Dead-code cleanup done 2026-04-12:
      removed `_hierarchical_x_position` (228 lines),
      `_compact_clusters` (56 lines) and `_keepout_noncluster_nodes`
      (71 lines) — all three were unreferenced anywhere in gvpy/ or
      tests/.  Total 355 lines deleted; dot_layout.py now 5238 lines.
      All 715 tests still pass, 0 overlaps on aa1332.dot.
- [x] **Step 6**: `graph.py` split — done 2026-04-12.  Moved 19
      module-level helpers out of `gvpy/core/graph.py` into per-concern
      files matching `lib/cgraph/` factoring:
      - `_graph_apply.py` (61 lines, NEW): `subnode_search`,
        `subedge_search`, `subgraph_search` (C: `lib/cgraph/apply.c`)
      - `_graph_cmpnd.py` (84 lines, NEW): `Agcmpgraph`,
        `agfindhidden` (C: `lib/cgraph/cmpnd.c`)
      - `_graph_traversal.py` (77 lines, NEW): `gather_all_nodes`,
        `gather_all_edges`, `gather_all_subgraphs`, `get_root_graph`
        (no C analogue — Python convenience helpers)
      - `_graph_edges.py` (281 -> 480 lines): added 11 module-level
        edge functions `agsubrep`, `agfstout`, `agnxtout`, `agfstin`,
        `agnxtin`, `agfstedge`, `agnxtedge`, `ok_to_make_edge`,
        `agedge`, `agidedge`, `agdeledge` (C: `lib/cgraph/edge.c`)
      - `_graph_id.py` (275 -> 295 lines): added module-level
        `agnextseq` (C: `lib/cgraph/graph.c`)
      `graph.py` keeps re-exports of every moved name so existing
      `from gvpy.core.graph import X` imports continue to work
      (tests, render code, and other gvpy modules).  Internal
      `_graph_*.py` modules updated to import directly from the new
      home (`from ._graph_traversal import get_root_graph` instead of
      `from .graph import get_root_graph`).  `GraphDict` stays in
      `graph.py` for now (only used by `_graph_id.py:148`).
      `graph.py`: 1680 -> 1329 lines (-351, -21%).  All 715 tests
      pass, aa1332.dot still has 0 node overlaps.
- [x] **Step 7 (partial)**: Extract Phase 2 (mincross) into
      `gvpy/engines/dot/mincross.py` — done 2026-04-12.  Moved 18
      methods (~1500 lines) as free functions via
      `tools/extract_mincross.py` (improved from extract_phase3.py
      to handle multi-line signatures + wrappers use `*args,
      **kwargs` for pass-through).  `mincross.py` is 1661 lines;
      docstring captures the session history (cluster DFS expand
      order, scoped crossing count, down_first/up_first fixes) and
      C↔Python file mapping (`lib/dotgen/mincross.c` +
      `class2.c`/`fastgr.c`/`cluster.c` pieces).  Dead-code cleanup
      alongside: deleted `_mval` (9 lines), `_count_cluster_crossings`
      (30 lines), `_cluster_group_ordering` (76 lines) — all
      unreferenced anywhere.  `dot_layout.py` now 3687 lines (was
      5238 pre-mincross, 6739 pre-session — net -3052 over the full
      session).  All 715 tests pass, 14/14 sampled files produce
      0 node overlaps.
- [x] **Step 7b (partial)**: Extract Phase 4 (splines/edge routing)
      into `gvpy/engines/dot/splines.py` — done 2026-04-12.  Moved 23
      methods (~766 lines) via `tools/extract_splines.py` (same
      pattern as `extract_mincross.py`).  `splines.py` is 893 lines;
      C analogue: `lib/dotgen/dotsplines.c` + `lib/common/splines.c`.
      Covers regular/chain/flat/self-loop routing, endpoint calc,
      samehead/sametail merging, compound-edge clipping, Bezier
      conversion, ortho routing.  Post-extraction fix: lazy import
      for the `_COMPASS` module-level constant inside `port_point`.
      `dot_layout.py`: 3687 -> 3036 lines this pass; 6739 -> 3036
      over the full session (-3703, -55%).  All 715 tests pass,
      14/14 sampled files produce 0 overlaps.
- [x] **Step 7c (Phase 1)**: Extract Phase 1 (rank assignment) into
      `gvpy/engines/dot/rank.py` — done 2026-04-12.  Moved 11 methods
      (~498 lines) via `tools/extract_rank.py` (improved
      `_replace_self_outside_strings` so the regex-based
      `self`->`layout` rename no longer touches string literals — a
      regression where edge_type literal `"self"` got rewritten to
      `"layout"` was the catch).  `rank.py` is 602 lines; C analogue
      `lib/dotgen/rank.c`.  Covers break_cycles, classify_edges (pre+
      post), inject_same_rank_edges, network_simplex_rank,
      cluster_aware_rank, apply_rank_constraints, compact_ranks,
      add_virtual_nodes, build_ranks.  Required lazy imports for
      `_NetworkSimplex`, `LayoutEdge`, `LayoutNode` inside the
      functions that instantiate them.  `dot_layout.py`: 3036 -> 2593
      lines this pass; **6739 -> 2593 over the full session (-4146,
      -62%)**.  All 715 tests pass, 0 overlaps on aa1332.dot.
- [x] **Step 7d (NS solver)**: Extract `_NetworkSimplex` class into
      `gvpy/engines/dot/ns_solver.py` — done 2026-04-12.  448-line
      class moved to its own module (483 lines including docstring +
      imports).  C analogue: `lib/dotgen/ns.c`.  A re-export
      `from gvpy.engines.layout.dot.ns_solver import _NetworkSimplex` is
      kept in `dot_layout.py` so existing imports
      (`from gvpy.engines.layout.dot.dot_layout import _NetworkSimplex`)
      continue to work — used by `tests/test_dot_layout.py`.  The
      lazy imports inside `rank.py` and `position.py` now import
      directly from `ns_solver.py` to avoid the re-export hop.
      `dot_layout.py`: 2593 -> 2167 lines this pass; **6739 -> 2167
      over the full session (-4572, -68%)**.  All 715 tests pass,
      0 overlaps on aa1332.dot.
- [x] **Step 7e**: Extract cluster geometry + init helpers — done
      2026-04-12.  Moved 7 cluster methods (`_collect_clusters`,
      `_collect_nodes_into`, `_scan_clusters`, `_dedup_cluster_nodes`,
      `_separate_sibling_clusters`, `_shift_cluster_nodes_y`,
      `_shift_cluster_nodes_x`) into `gvpy/engines/dot/cluster.py`
      (357 lines; C analogue `lib/dotgen/cluster.c`) and 5 init
      methods (`_init_from_graph`, `_collect_rank_constraints`,
      `_scan_subgraphs`, `_collect_edges`, `_collect_edges_recursive`)
      into `gvpy/engines/dot/dotinit.py` (298 lines; C analogue
      `lib/dotgen/dotinit.c`) via `tools/extract_cluster_init.py`
      (two-batch driver reusing the string-aware `self`->`layout`
      substitution from `extract_rank.py`).  C-ref traceability
      re-established across all 6 extracted modules — `tools/audit_c_refs.py`
      reports 100% (rank 11/11, mincross 18/18, position 13/13,
      splines 23/23, cluster 7/7, dotinit 5/5) after re-annotating
      35 functions whose docstrings had lost their C analogue line.
      `dot_layout.py`: 2167 -> 1777 lines this pass; **6739 -> 1777
      over the full session (-4962, -74%)**.  All 715 tests pass,
      0 overlaps on aa1332.dot (verified via `LayoutNode` bbox
      intersection over 107 nodes).
- [ ] **Step 8**: Add `SimulationView` base + minimal skeleton
- [ ] **Step 9**: Add `PictoGraphInfo(LayoutView)` pictosync engine
