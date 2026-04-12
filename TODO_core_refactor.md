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
- [ ] **Step 6**: `graph.py` split (this file's first section)
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
- [ ] **Step 7c**: Extract remaining dot phases — Phase 1 rank
      assignment (rank.c), cluster geometry (cluster.c), class2,
      fastgr, flat, sameport, acyclic — into per-phase modules
      matching `lib/dotgen/`
- [ ] **Step 8**: Add `SimulationView` base + minimal skeleton
- [ ] **Step 9**: Add `PictoGraphInfo(LayoutView)` pictosync engine
