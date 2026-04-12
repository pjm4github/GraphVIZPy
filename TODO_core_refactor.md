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
      are now 3-line delegating wrappers.  `position.py` is 517 lines;
      `dot_layout.py` reduced by ~350 lines.  All 715 tests pass,
      0 overlaps.  Remaining Phase 3 helpers (`_set_ycoords`,
      `_expand_leaves`, `_insert_flat_label_nodes`,
      `_bottomup_ns_x_position`, `_compute_cluster_boxes`,
      `_simple_x_position`, `_median_x_improvement`, `_center_ranks`,
      `_apply_rankdir`, `_resolve_cluster_overlaps`,
      `_post_rankdir_keepout`) still live in `dot_layout.py` and are
      called back via `layout._xxx()`.  Full extraction is a future
      mechanical pass — the hard part (understanding the bug fix
      context) is already in the new module.
- [ ] **Step 3**: Rename `DotLayout` → `DotGraphInfo`, inherit from
      `LayoutView`, keep `DotLayout = DotGraphInfo` alias
- [ ] **Step 4b**: Complete extraction of remaining Phase 3 helpers
      into `position.py`
- [ ] **Step 6**: `graph.py` split (this file's first section)
- [ ] **Step 7**: Extract remaining dot phases (rank, mincross,
      splines, cluster, class2, fastgr, flat, sameport, acyclic)
      into per-phase modules matching `lib/dotgen/`
- [ ] **Step 8**: Add `SimulationView` base + minimal skeleton
- [ ] **Step 9**: Add `PictoGraphInfo(LayoutView)` pictosync engine
