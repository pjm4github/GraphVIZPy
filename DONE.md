# DONE — GraphvizPy work log

Archive of shipped work pulled out of `TODO.md` to keep the live roadmap
short.  Ordered newest → oldest.

---

## TODO reorganization — archive §2 research log + close engine arc — 2026-05-09

Compacted ``TODO.md`` from ~1650 lines to ~250.  All 9 layout
engines are C-aligned (DONE §4.D / §4.N / §4.T / §4.F /
§4.S-* / §4.O / §4.P / §4.C) and the ``-Tplain`` renderer is
shipped (commit ``02a2d0a``).  Re-prioritised the §1 divergence
list with explicit "defer until a pictosync use-case surfaces"
annotations.

### §2.5.12–21 archive — D5/D7 alignment research log (2026-05-06 → 2026-05-07)

Multi-day deep-dive into the +94 spatial-cluster-cross
delta on 1879.dot.  Final understanding (the one that
matters going forward):

1. **Mincross & build_ranks are bit-aligned with C.**
   §2.5.1–7 closed every layer of the rank-construction
   path; skel mode promoted to default 2026-04-30.  1879's
   crossings come from coord placement / spline routing,
   not mincross.

2. **Keepout structure matches C 100%.**  §2.5.12 added
   matching ``[TRACE keepout]`` probes — Py and C generate
   the same 186 aux-edges (92 L / 94 R) with identical
   (cluster, rank, side, src, dst) tuples.

3. **D7 (font metrics) controls keepout *minlens* but not
   final positions.**  §2.5.13 showed: Py with C-widths
   override → keepout minlens become bit-perfect (186/186
   match), but the spatial-cross count *doubles* (62→144).
   D7 is necessary, not sufficient.

4. **Aux-graph topology gap localised to sec3d (root
   hierarchy edges).**  §2.5.14–15: Py's NS gets 196 fewer
   constraint edges than C's because Python skipped the
   ``parent is None → root graph`` case in section 3d.
   §2.5.16 landed a gated fix
   (``GVPY_ROOT_HIERARCHY=1``) that closes the topology
   gap, but the audit metric still regresses (1879 62→118)
   because:

5. **Per-edge minlen drift across sec3a/sec3d/sec3e.**
   §2.5.17 found a Py-only ``_rc_floor=8`` knob that
   inflated every cluster-boundary edge by 8pt.  Plus Py
   missed C's TB-cluster label-width edges in
   ``sec3c_eff``.  Both fixed gated.

6. **D7 LUT port shipped.**  §2.5.18 ported
   ``lib/common/textspan_lut.c`` verbatim to
   ``gvpy/engines/layout/font_metrics_lut.py`` (11 font
   families × 4 variants × 128 widths).  Per-glyph widths
   now match C within 0.01pt.  But on 1879 the dominant
   drift source is *HTML-table sizing*
   (``<TABLE>``/``<TR>``/``<TD>`` cell math in
   ``html_label.py``), not glyph widths.  ~33pt mean / 150pt
   max NODE width drift remains.

7. **HTML-table residual analysis blocked on libexpat
   build.**  §2.5.21: instrumenting C's ``size_html_cell``
   requires a libexpat-enabled local build.  CLion's
   build dir lacks libexpat; CLAUDE.md forbids reconfiguring
   it.  Could build a sibling cmake dir with msys64's
   ``libexpat.a``, or translate ``htmltable.c`` line-by-line
   into Python and diff.  Both ~30-60 min.  Deferred — D5
   sprawl on 1879 is a single-file polish issue, not
   blocking.

**Final state**: 1879's spatial-cross count remains +94 vs
C, but the *structural* constraint generation is at parity
when the gates fire.  All instrumentation
(``GV_TRACE=position``, ``GV_DUMP_AUX_MINLENS``,
``GV_DUMP_WIDTHS``, ``GVPY_ROOT_HIERARCHY``,
``GVPY_C_WIDTH_OVERRIDE``, etc.) stays in tree for future
regressions.  The detailed §2.5.12–21 instrumentation
findings are preserved in git history at commit
``edee1e3^`` (the TODO.md before this reorganization).

### Engine arc complete (2026-05-09)

All 9 layout engines C-aligned end-to-end:

| engine | tests | DONE entry |
|---|---:|---|
| dot | 1141 | §1.5 series + various |
| neato | 54 | §4.N |
| twopi | 24 | §4.T |
| fdp | 43 | §4.F + §4.F-clusters + §4.F-derivegraph |
| sfdp | 50 | §4.S-derivegraph + §4.S-multilevel + §4.S-spring-electrical + §4.S-post-process |
| osage | 29 | §4.O |
| patchwork | 28 | §4.P |
| circo | 56 | §4.C-blocktree + §4.C-full |
| ortho | 18+12+18+4+4+12 | (early port via lib/ortho/) |

Total: 1307 passing, 4 skipped, 1 deselected.

### §7.x — `-Tplain` renderer — 2026-05-09

``gvcli.py -Tplain`` now emits the canonical Graphviz plain
text format (``graph SCALE WIDTH HEIGHT`` /
``node NAME X Y W H LABEL STYLE SHAPE COLOR FILLCOLOR`` /
``edge TAIL HEAD N x1 y1 ... STYLE COLOR`` / ``stop``,
inches, math-y).  Module: ``gvpy/render/plain_renderer.py``
(~190 LOC).  16 new tests.  Commit ``02a2d0a``.  JSON
output stays available under ``-Tjson`` / ``-Tjson0``.

---

## §4.C-full — Circo blockpath.c + circpos.c port (closes circo) — 2026-05-09

Completes the circo port started in §4.C-blocktree.  Both
``lib/circogen/blockpath.c`` (640 LOC) and
``lib/circogen/circpos.c`` (426 LOC) are now ported verbatim.
Combined with §4.C-blocktree, **circo is now fully C-aligned
end-to-end** — every algorithm in ``lib/circogen/`` has a
matching Python module.

**New modules**:

- ``gvpy/engines/layout/circo/blockpath.py`` (~480 lines):
  - ``_remove_pair_edges`` + ``_find_pair_edges`` — skeleton
    construction.  Iteratively peels lowest-degree nodes,
    adding synthetic connectivity edges between unpaired
    neighbours so the spanning tree topology is preserved.
  - ``_spanning_tree`` — DFS via explicit work stack
    (sidesteps Python recursion limits on dense blocks).
    Mirrors C ``spanning_tree`` (blockpath.c:340).
  - ``_measure_distance`` + ``_find_longest_path`` — diameter
    via measure-from-every-leaf algorithm.  Iterative version
    of C's recursion.
  - ``_place_node`` + ``_place_residual_nodes`` — insert
    off-path nodes adjacent to neighbours already on the path.
    Prefer position between two consecutive path neighbours;
    fall back to "after any one neighbour"; fall back to
    "append at end".
  - ``_count_all_crossings`` — open-edge-list sweep.  Two
    chords (a,b) and (c,d) cross iff one chord opens between
    the other's endpoints in the cyclic walk.
  - ``_reduce`` + ``_reduce_edge_crossings`` — try moving each
    node next to each of its neighbors (both before and
    after); keep moves that reduce crossings.  Iterates up to
    ``CROSS_ITER=10`` rounds.
  - ``layout_block`` — public entry mirroring C
    ``layout_block`` (blockpath.c:566) verbatim: skeleton →
    spanning tree → longest path → residual placement →
    crossings reduction → realign at ISPARENT → place on
    circle.  Caches per-node PSI on the block.

- ``gvpy/engines/layout/circo/circpos.py`` (~360 lines):
  - ``get_rotation`` — closed-form rotation math (C
    circpos.c:50).  Three branches:
    - 1-node blocks: ``θ + π - parent_pos``.
    - 2-node blocks: ``θ - π/2`` (perpendicular line of
      nodes).
    - N-node blocks: rotate so ``CHILD(sn)`` ends up adjacent
      to its parent.  Coalesced blocks use a different
      closed-form involving ``ρ``, ``r``, ``φ``, ``β``.
  - ``apply_delta`` — recursive rotation + translation cascade
    through a block subtree.
  - ``_get_info`` / ``_set_info`` — compute per-articulation-
    point fan geometry (max child radius, sum of diameters);
    scale fans so they don't overlap each other on the parent
    circle.
  - ``_position_children`` — distribute children at one
    articulation point around an arc, respecting individual
    radii.  Calls ``get_rotation`` + ``apply_delta`` per
    child.
  - ``position`` — outer loop handling 1/2/N-articulation-point
    cases.  Includes the **coalescing branch** (C
    circpos.c:380-385): when the parent has exactly one total
    child block, shift everything over to merge them and mark
    the block COALESCED.
  - ``do_block`` + ``circ_pos`` — top-level recursive
    orchestrator.  Mirrors C ``doBlock`` / ``circPos``
    verbatim: depth-first, layout each block, attach children
    via ``position``.

**Engine wiring** (``CircoLayout``):

- New dispatch matrix.  Three independent gates:
  - ``GVPY_CIRCO_BLOCKTREE=c|legacy``
  - ``GVPY_CIRCO_BLOCKPATH=c|legacy``
  - ``GVPY_CIRCO_CIRCPOS=c|legacy``

  All default to ``c``.  When all three are ``c``, the engine
  delegates the entire bottom-up + top-down recursion to
  ``circ_pos`` (which calls ``do_block``, which calls
  ``layout_block``).  Mixed modes fall back to the older split
  flow with ``_extract_positions_c_aligned`` /
  ``_position_block_tree_c_aligned_legacy_layout`` shims.

- ``_extract_positions_c_aligned`` walks the block tree after
  ``circ_pos`` returns and copies absolute coords into
  ``self.lnodes``.

**Bug found and fixed during port**:

- Coalescing branch in ``position`` initially used per-
  articulation-point child count; should be the *total*
  ``parent_block.children`` count (mirrors C's ``childCount``
  arg passed from ``doBlock``).  Without this fix, circo_demo
  rendered as 968×1108 (~2× too tall); after fix, 1027×582 vs
  system C's 1039×562 — within 4% on both dimensions.

**Verification**:

- 4-cycle: nodes at 90° intervals, radius matches C's
  ``N · (mindist + largest_node) / (2π)`` formula exactly.
- ``count_all_crossings`` correct on K4 (1 crossing) and 4-cycle
  in adjacent order (0 crossings).
- ``apply_delta`` with rotate=π/2 swaps x↔y axes correctly.
- ``get_rotation`` 2-node branch returns ``θ - π/2``.
- ``get_rotation`` 1-node parent_pos branch returns
  ``θ + π - parent_pos``.
- 3-block graph (a-b-c-a triangle + b-d edge + d-e-f-d
  triangle, articulation points b and d): all 6 nodes
  positioned, no errors.
- circo_demo.gv (13 nodes, multiple biconnected components):
  Python canvas 1027×582 vs system C 1039×562 — within 4%.

**Test counts**:

- circo tests: **56 passed** (was 42; +14 new
  ``TestCircoBlockpathCAligned`` and
  ``TestCircoCircposCAligned``).
- Full suite: **1291 passed**, 4 skipped, 1 deselected (was
  1277).

**Engine status after this session**:

| engine | tests | status |
|---|---:|---|
| circo | 56 | **full C-aligned port**: blocktree.c + blockpath.c + circpos.c + block.c + nodelist.c all ported verbatim.  No remaining legacy approximations. |

**All 9 layout engines now have full C-aligned ports.**

| engine | tests | status |
|---|---:|---|
| dot | 1141 | full port |
| neato | 54 | full C-aligned port |
| twopi | 24 | full C-aligned port |
| fdp | 43 | full C-aligned port + cluster-aware routing + deriveGraph |
| sfdp | 50 | full C-aligned port: clusters + multilevel + spring-electrical + stress smoothing |
| osage | 29 | full C-aligned port |
| patchwork | 28 | full C-aligned port |
| **circo** | **56** | **full C-aligned port (DONE §4.C-blocktree + §4.C-full)** |
| ortho | 18+12+18+4+4+12 | full port |

Files: ``gvpy/engines/layout/circo/blockpath.py`` (new, ~480
lines), ``gvpy/engines/layout/circo/circpos.py`` (new, ~360
lines), ``gvpy/engines/layout/circo/circo_layout.py``
(refactored — 3-gate dispatch + extract helpers, ~80 lines
changed), ``tests/test_circo_layout.py`` (+14 tests in two
new test classes).

---

## §4.C-blocktree — Circo blocktree.c + block.c + nodelist.c port — 2026-05-09

**Partial circo port** — replaces the most correctness-critical
piece (biconnected-component decomposition) with a verbatim
port of C, while leaving the per-block layout
(``blockpath.c``) and child-block positioning (``circpos.c``)
algorithms as the existing homegrown approximations behind a
gate.  The full C-aligned port of those two files is tracked
as TODO §4.x-circo follow-up work.

**New modules**:

- ``gvpy/engines/layout/circo/block.py`` (~140 lines):
  - ``Block`` dataclass mirroring C ``block_t`` (block.h:26):
    ``sub_graph``, ``child``, ``parent_anchor``, ``radius``,
    ``rad0``, ``circle_list``, ``children``, ``parent_pos``,
    ``flags``, ``node_pos``, ``center_x/y``, ``node_psi``.
  - ``Blocklist`` helper with C-style ``append`` / ``insert``
    (front-insert) semantics — mirrors ``block.c:47-69``.
  - Engine-compat property aliases (``nodes`` ↔ ``sub_graph``,
    ``cut_node`` ↔ ``parent_anchor``, ``circle_order`` ↔
    ``circle_list``) so the legacy positioning code keeps
    working without a rename.
- ``gvpy/engines/layout/circo/nodelist.py`` (~60 lines):
  - ``append_at`` (mirrors C ``appendNodelist``).
  - ``realign`` (mirrors ``realignNodelist`` — rotate so np
    becomes new front).
  - ``insert_relative`` (mirrors ``insertNodelist`` — re-insert
    cn before/after neighbor).
  - ``reverse_append`` (mirrors ``reverseAppend``).
- ``gvpy/engines/layout/circo/blocktree.py`` (~250 lines):
  - ``BlockState`` dataclass mirroring C ``circ_state``
    (circular.h:16).
  - Tarjan articulation-point DFS via explicit work stack
    (matches C's edge-stack semantics; sidesteps Python
    recursion-depth limits on dense graphs).  Mirrors
    ``blocktree.c::dfs`` verbatim.
  - ``find_blocks`` and ``create_blocktree`` — the public
    entry points mirroring ``blocktree.c:113`` and
    ``blocktree.c:143``.
  - For each non-root block, finds the smallest-VAL node ("the
    node IN bp linking to parent") and sets both
    ``bp.child`` (C-aligned) and ``bp.parent_anchor`` (the
    DFS parent of that node — the articulation point IN the
    parent block, which the engine's positioning code reads).

**Engine wiring** (``CircoLayout``):

- ``_layout_component`` dispatches between the C-aligned
  ``create_blocktree`` and the legacy homegrown Tarjan via
  ``GVPY_CIRCO_BLOCKTREE=c|legacy`` (default ``c``).
- New ``_populate_block_edges`` walks the blocktree to fill
  in ``block.edges`` from the global adjacency dict — the
  engine's per-block layout / crossings algorithms expect an
  edge list, which the C-aligned port doesn't track (C uses
  Graphviz's native graph mutation model).
- ``oneblock`` mode and tiny graphs (≤ 2 nodes) bypass the
  blocktree pass and use the legacy single-block fallback.

**What's NOT yet ported** (deferred to TODO §4.x-circo):

- ``blockpath.c`` (640 LOC): spanning-tree construction,
  longest-path discovery via two-BFS, place_node /
  place_residual_nodes, count_all_crossings + reduce
  algorithms.  The existing Python implementation produces
  valid layouts but uses an approximate crossings-reduction
  loop (10-iter neighbor-targeted insertion) rather than C's
  full reduce + reduce_edge_crossings cycles.
- ``circpos.c`` (426 LOC): getRotation closed-form rotation
  math, applyDelta cascade, getInfo/setInfo scaling,
  positionChildren angular distribution, position outer loop
  handling 1/2/N-parent cases.  The existing Python uses a
  simpler approximation (uniform angle distribution + scale-
  based push) that produces valid output but doesn't match
  C's bit-for-bit angles.

**Test counts**:

- circo tests: **42 passed** (was 25; +17 new
  ``TestCircoBlocktreeCAligned`` and
  ``TestCircoBlockNodelistCAligned``).
- Full suite: **1277 passed**, 4 skipped, 1 deselected (was
  1260).

**Engine status after this session**:

| engine | tests | status |
|---|---:|---|
| circo | 42 | partial C-aligned port: ``block.h`` data types + ``nodelist`` ops + ``blocktree.c`` Tarjan DFS + block-cut tree.  ``blockpath.c`` and ``circpos.c`` still homegrown approximations. |

Files: ``gvpy/engines/layout/circo/block.py`` (new, ~140
lines), ``gvpy/engines/layout/circo/nodelist.py`` (new, ~60
lines), ``gvpy/engines/layout/circo/blocktree.py`` (new, ~250
lines), ``gvpy/engines/layout/circo/circo_layout.py``
(refactored — module imports + dispatch + edge-population
helper, ~30 lines changed), ``tests/test_circo_layout.py``
(+17 tests in two new test classes).

---

## §4.P — Patchwork squarified-treemap layout port — 2026-05-09

Port of ``lib/patchwork/patchwork.c`` (282 C lines) +
``lib/patchwork/tree_map.c`` (116 lines).  Replaces the
homegrown squarified treemap with a faithful C-aligned port
matching Bruls / Huizing / van Wijk 2000.

**New module**: ``gvpy/engines/layout/patchwork/tree_map.py``
(~210 lines):

- ``Rectangle`` dataclass mirroring C ``rectangle`` (center +
  size, NOT lower-left + size).
- ``_squarify`` recursion mirroring C ``squarify``
  (tree_map.c:19) verbatim:
  - Fix the shorter side ``w`` of ``fillrec`` as the strip
    thickness.
  - Greedy add: extend strip with successive items, accept if
    worst aspect ratio improves; commit + recurse on remainder
    when it would worsen.
  - Strip placement: tall fillrec → strip at top, items
    left-to-right; wide fillrec → strip at left, items
    top-to-bottom.
- ``tree_map(areas, fillrec)`` — top-level entry mirroring C
  ``tree_map`` (tree_map.c:104).  Returns one rectangle per
  input area in the same order; returns ``None`` on overflow
  (matches C's NULL).

**Refactored**: ``gvpy/engines/layout/patchwork/patchwork_layout.py``
(rewritten, ~370 lines).  Mirrors C structure verbatim:

- ``_make_tree`` — recursive tree builder mirroring C ``mkTree``
  (patchwork.c:91).  Cluster area = ``(2·inset + sqrt(child_area))²``
  per C ``fullArea`` (patchwork.c:57).  Leaf area =
  ``area_attribute × SCALE`` per ``getArea`` (patchwork.c:64),
  defaulting to ``DFLT_SZ=1.0`` for missing / zero values.
  Non-cluster subgraphs are flattened into their parent cluster
  (matches C ``SPARENT`` skipping logic).
- Inset margin solved closed-form (patchwork.c:169-171):

      delta = h - w
      disc  = sqrt(delta² + 4·child_area)
      m     = (h + w - disc) / 2

  This gives a uniform inset on all sides such that the inner
  rectangle's area exactly equals the children's total area.
- ``_layout_tree`` — recursive squarify mirroring C
  ``layoutTree`` (patchwork.c:149): sort children by area
  descending, compute inset margin, call ``tree_map`` on the
  inner rectangle, recurse into cluster children.
- ``_walk_tree`` — pre-order extraction of node coords + cluster
  bboxes.  **Y-flip** at this seam: the squarify recursion
  uses math-y (y up) so C's "top of fillrec" semantics work;
  downstream consumers expect SVG-y (y down) — we negate every
  y-coord at output time, the smallest possible coord-system
  seam.

**Differences from the legacy Python implementation** (replaced
2026-05-09):

- Legacy ``_layout_row`` was an approximation that didn't
  recursively track aspect-ratio improvement; it committed
  rows greedily based on a single "side" length and could
  produce strips with much worse aspect than C.
- Legacy used a *fixed* inset (``_DFLT_INSET = 8 pt``)
  regardless of cluster size; C's closed-form margin solve
  scales appropriately so big clusters get bigger borders.
- Legacy used ``Rectangle = (LL_x, LL_y, w, h)`` while C uses
  center+size — port now matches C exactly.
- Legacy didn't handle non-cluster subgraphs (``subgraph S {
  ... }`` not starting with ``cluster``); they're now
  flattened correctly.

**Verification** (smoke + property tests):

- 4 equal areas → 2×2 grid with corners at (25,25), (25,75),
  (75,25), (75,75) — 50×50 each.
- Total output area exactly matches sum of input areas.
- Overflow (input area > fillrec area) returns None (matches C
  NULL).
- Squarified 16×1 layout: worst aspect ratio < 2.0 (would be
  16:1 if naive horizontal strip).
- Single-rect input fills the whole fillrec.
- Empty input returns ``[]``.
- Engine: ``area=4`` node has ~4× the area of ``area=1`` node
  (allowing ±50% slop for squarification rounding).
- Engine: nested clusters — child bbox enclosed by parent's;
  child nodes inside child bbox.
- Engine: 6 nodes with mixed areas → no leaf-rect overlaps.
- Engine: 1-node and empty-graph cases handled.

**Test counts**:

- patchwork tests: **28 passed** (was 17; +11 new
  ``TestPatchworkTreeMapCAligned`` and ``TestPatchworkCAligned``).
- Full suite: **1260 passed**, 4 skipped, 1 deselected (was
  1249).  Pre-existing parser test failure unchanged.

**Engine status after this session**:

| engine | tests | status |
|---|---:|---|
| patchwork | 28 | full C-aligned port: ``mkTree`` + recursive ``layoutTree`` (squarify + inset margin solve) + ``walkTree`` extraction with y-flip |

Files: ``gvpy/engines/layout/patchwork/tree_map.py`` (new,
~210 lines), ``gvpy/engines/layout/patchwork/patchwork_layout.py``
(rewritten, ~370 lines), ``tests/test_patchwork_layout.py``
(+11 tests).

---

## §4.O — Osage cluster-packing layout port — 2026-05-09

Port of ``lib/osage/osageinit.c`` (368 C lines) plus the
array-packing portion of ``lib/pack/pack.c`` (~250 LOC of the
1100-line file — only ``putRects`` / ``arrayRects`` /
``parsePackModeInfo`` / ``getPackInfo``).  Replaces the
homegrown osage layout with a faithful C-aligned port.

**New module**: ``gvpy/engines/layout/osage/pack.py`` (~340
lines):

- ``PackInfo`` dataclass mirroring C ``pack_info``.
- ``PackMode`` IntEnum mirroring C ``pack_mode`` (``L_ARRAY``,
  ``L_GRAPH``, etc.).
- ``PK_*`` flag bits matching C's bit layout.
- ``parse_pack_mode(spec, default)`` — full ``packmode``
  attribute parser supporting:
  - ``array[_<flags>][<size>]`` — array packing with optional
    flags and explicit column/row count.
  - Flags: ``c`` (col-major), ``i`` (input order), ``u`` (user
    values), ``t b l r`` (top/bot/left/right alignment).
  - ``aspect[<float>]``, ``cluster``, ``graph``, ``node`` modes
    (osage uses ``array``; others recognized for completeness).
- ``get_pack_info(pack, packmode, default_mode, default_margin)``
  — combines ``pack`` (margin) and ``packmode`` reads.
- ``array_rects(bbs, info)`` — the workhorse:
  - Grid sizing: ``ceil(sqrt(n))`` cols by default, or explicit
    ``info.sz`` (rows for col-major).
  - Sort: ascending by ``info.vals[i]`` if ``PK_USER_VALS`` set;
    descending by ``width + height`` otherwise (C's ``acmpf``);
    or input order with ``PK_INPUT_ORDER``.
  - Per-column/per-row max-size computation.
  - **Row reversal** — heights are built in reverse so row 0
    ends up at the *top* of the layout.  Subtle invariant that
    matches C verbatim and gives osage's "low-sortv at top-left,
    high-sortv at bottom-right" reading order.
  - Per-cell placement with full alignment-flag support.
- ``put_rects(bbs, info)`` — top-level dispatcher.

**Refactored**: ``gvpy/engines/layout/osage/osage_layout.py``
(~440 lines, was ~363).  Now mirrors C's structure verbatim:

- ``_make_clusters`` — recursive cluster discovery.  Mirrors C
  ``mkClusters`` (osageinit.c:280).  Non-cluster subgraphs are
  flattened into their nearest cluster ancestor.
- ``_layout_pass(box, depth)`` — bottom-up packing.  Mirrors C
  ``layout(g, depth)`` (osageinit.c:67):
  - Recurse into subclusters first.
  - Build bbox list (subclusters + direct nodes).
  - Call ``put_rects``.
  - Translate bboxes by displacements.
  - Compute ``rootbb`` union.
  - Add label space at top (cluster has label).
  - Add per-side margin (depth-dependent: 0 at root,
    ``pinfo.margin / 2`` otherwise).
  - Translate so ``rootbb.LL == origin``.
- ``_reposition_pass(box, depth, offset)`` — top-down absolute
  positioning.  Mirrors C ``reposition(g, depth)``
  (osageinit.c:236).
- ``ClusterBox`` dataclass holds per-cluster state (``children``,
  ``sub_clusters``, ``bb``, ``label``, ``sortv``, ``attrs``).
- ``LayoutNode`` gains a ``parent_cluster`` field (mirrors C
  ``ND_alg(n)``, osageinit.c:35).

**Verification**:

- 4 equal rects → 2×2 grid with distinct cells per rect ✓.
- ``PK_USER_VALS`` sort: rect with lowest sortv lands in
  top-row.
- Default size sort: descending by ``w + h`` (biggest first).
- ``PK_INPUT_ORDER`` flag: top-row rects above the row
  boundary, bottom-row below.
- ``packmode="array_u3"`` parsed as ``L_ARRAY`` + ``sz=3`` +
  ``PK_USER_VALS``.
- ``packmode="array_clt"`` parsed with col-major + left-align +
  top-align flags.
- Engine: ``packmode=array_u`` triggers ``sortv`` ordering;
  lowest-sortv cluster ends up at top of layout.
- Engine: ``pack=20`` widens canvas vs default ``pack=8``.
- Engine: nested clusters — child bbox is fully inside parent
  bbox.
- Engine: multi-cluster layout produces 0 overlapping nodes.
- Engine: labeled cluster reserves top space — node sits below
  the label header.

**What was deliberately skipped**:

- ``polyRects`` for ``packmode=graph`` (polyomino packing) —
  ~300 LOC, used by neato component packing not osage.  fdp/sfdp
  have their own polyomino packer in
  ``gvpy/engines/layout/neato/_neato_pack.py``.
- ``aspectRects`` for ``packmode=aspect`` — ~150 LOC,
  rarely-used aspect-ratio-driven variant.
- ``computeStep``, ``genBox``, ``placeGraph`` — polyomino
  packing helpers (only used by ``polyRects``).
- C label rendering — we estimate label dims via
  ``len(label) × fontsize × 0.55`` for width and ``fontsize ×
  1.5`` for height.  Good enough that labels fit and don't
  overlap interiors, but not pixel-perfect with C's
  ``do_graph_label``.

**Test counts**:

- osage tests: **29 passed** (was 16; +13 new
  ``TestOsagePackCAligned``).
- Full suite: **1249 passed**, 4 skipped, 1 deselected (was
  1236).  Pre-existing parser-error test failure unchanged.

**Engine status after this session**:

| engine | tests | status |
|---|---:|---|
| osage | 29 | full C-aligned port: ``mkClusters`` + bottom-up ``layout`` + top-down ``reposition`` + array packing with ``packmode``/``pack`` attributes |

Files: ``gvpy/engines/layout/osage/pack.py`` (new, ~340 lines),
``gvpy/engines/layout/osage/osage_layout.py`` (rewritten,
~440 lines), ``tests/test_osage_layout.py`` (+13 tests in
``TestOsagePackCAligned``).

---

## §4.S-post-process — Sfdp post_process.c + stress_model.c + sparse_solve.c port — 2026-05-09

Port of ``lib/sfdpgen/post_process.c`` (1034 C lines),
``lib/sfdpgen/stress_model.c`` (47 lines), and
``lib/sfdpgen/sparse_solve.c`` (146 lines) — stress
majorization smoothing for ``smoothing=avg_dist|graph_dist|
power_dist|spring`` plus the Gansner-Koren-North conjugate-
gradient solver that drives the inner loop.  Closes out the
sfdp port arc — sfdp's force pass is now C-aligned end to end.

**New modules**:

- ``gvpy/engines/layout/sfdp/sparse_solve.py`` (~165 lines):
  - ``_diag_precon_new(A)`` — diagonal Jacobi preconditioner
    (sparse_solve.c:33).
  - ``_conjugate_gradient(A, precon, x, rhs, tol, maxit)`` —
    in-place CG with diagonal preconditioning
    (sparse_solve.c:56).  Operates on a single dim.
  - ``sparse_matrix_solve(A, x0, rhs, tol, maxit)`` —
    multi-dim wrapper; loops CG per coordinate dimension and
    writes solutions back into ``rhs``
    (sparse_solve.c:137).  Default maxit = ``floor(sqrt(n))``
    matches C.

- ``gvpy/engines/layout/sfdp/post_process.py`` (~580 lines):
  - ``_ideal_distance_matrix(A, x)`` — symmetric-difference
    ideal distance matrix (post_process.c:36).  Rescales so
    mean ideal == mean Euclidean.
  - ``_avg_neighbor_distances(A, x)`` — per-node mean
    neighbour distance (post_process.c:138).
  - ``StressMajorizationSmoother`` dataclass mirroring
    ``StressMajorizationSmoother_struct`` (post_process.h:18).
  - ``stress_majorization_smoother2_new(A, x, lambda0,
    ideal_dist_scheme)`` — full builder with distance-2
    coverage (post_process.c:108).  Supports all three
    schemes: ``IDEAL_GRAPH_DIST``, ``IDEAL_AVG_DIST``,
    ``IDEAL_POWER_DIST``.
  - ``sparse_stress_majorization_smoother_new(A, x)`` —
    sparse builder used by ``stress_model``
    (post_process.c:309).  Treats ``A.data`` as distances,
    not weights.  Auto-randomizes ``x`` if all-zero (matches
    C's ``72 · drand()``).
  - ``stress_majorization_smoother_smooth(sm, x, maxit_sm)`` —
    outer fixed-point iteration (post_process.c:579).  Each
    iter rebuilds the per-iter ``Lwdd`` off-diags via
    ``Lwd[i,j] / dist(x_i, x_j)``, computes the RHS
    ``y = Lwdd · x + λ · x_0``, solves
    ``Lw · x' = y`` via CG, and converges on
    ``‖x' - x‖ / ‖x‖ < tol = 0.001``.  Includes the
    perturbation branch for coincident nodes.
  - ``stress_model(A, x, maxit_sm)`` — neato-style stress
    layout entry point (stress_model.c:10).  Builds the
    sparse smoother, smooths, rescales by ``1/scaling``.
  - ``post_process_smoothing(A, smoothing, x, *, rng,
    spring_re_run)`` — top-level dispatcher
    (post_process.c:974).  Maps GraphvizPy attribute strings
    (``avg_dist``, ``graph_dist``, ``power_dist``, ``spring``,
    ``triangle``, ``rng``, ``none``) to C's enum and routes
    to the appropriate smoother.

**What was deliberately skipped**:

- **TriangleSmoother / RNG smoother** — depend on
  ``neatogen/call_tri.c`` Delaunay triangulation (~600 LOC,
  separate port).  Modes ``smoothing=triangle`` /
  ``smoothing=rng`` print a one-line warning and no-op.
- **Edge label penalty matrix** (``get_edge_label_matrix``,
  ``SM_SCHEME_NORMAL_ELABEL``) — needs
  ``relative_position_constraints`` data structure.
  GraphvizPy doesn't expose ``edge_labeling_scheme`` yet.
- **SpringSmoother variant** (uses
  ``spring_electrical_spring_embedding`` with both adjacency
  and distance matrices).  Approximated via the
  ``spring_re_run`` callback which re-descends the existing
  multilevel hierarchy with ``maxiter=20``, ``step/=2``,
  ``random_start=False`` (matches C's ``SpringSmoother_new``
  control mutations, post_process.c:944-947).  Functionally
  equivalent for the ``smoothing=spring`` user-facing
  attribute.
- **Statistics counters** (``_statistics`` debug arrays)
  and ``DEBUG_PRINT`` blocks.

**Engine wiring** (``SfdpLayout``):

- New ``_post_process_smoothing_c_aligned(A, ctrl, grid, x,
  node_list)`` method called between the multilevel descent
  and the pt-space rescale.  Operates on unit-K coords so the
  smoother's ``Lwd`` matrix matches the per-edge spacing it
  saw.
- ``spring_re_run`` callback rebuilds a tightened
  ``SpringElectricalControl`` and invokes
  ``multilevel_spring_electrical_embedding`` against the same
  hierarchy.
- Dispatch behind ``GVPY_SFDP_POST_PROCESS=c|legacy`` (default
  ``c``).  Legacy mode skips smoothing entirely (matches the
  pre-port behaviour where only ``smoothing=spring`` did
  anything).

**Verification**:

- CG: 4-cycle Laplacian + diagonal shift converges to machine
  precision (residual < 1e-8).
- Diagonal preconditioner: returns 1/A[i,i] correctly,
  including the zero-diagonal fallback.
- Ideal distance matrix on equilateral triangle: rescaling
  produces uniform 1.0 entries (matches mean Euclidean).
- 5-node path with ``smoothing=avg_dist``: smoothed layout
  has graph-distance proportionality:

      edge dists ~25 pt, distance-2 ~50 pt, distance-4 ~105 pt

  i.e., ~4× ratio for far/edge — exactly what stress
  majorization should produce.
- ``stress_model`` on a 3-cycle with unit target distances:
  embeds as an equilateral triangle (max_side / min_side <
  1.5).
- ``smoothing=none``: x is unchanged.
- ``smoothing=triangle`` / ``rng``: one-line warning to
  stderr, x unchanged.
- Empty / 1-node graphs: smoother builder returns ``None``
  (no crash on ``sbot == 0`` degenerate case).
- Engine-level: ``smoothing=avg_dist`` on a 5-node path
  produces ``far / edge_mean > 3``.
- Engine-level: ``smoothing=graph_dist`` on a small clique
  runs without crash.
- ``GVPY_SFDP_POST_PROCESS=legacy`` skips smoothing path.

**Test counts**:

- sfdp tests: **50 passed** (was 39; +11 new
  ``TestSfdpPostProcessCAligned``).
- Full suite: **1236 passed**, 4 skipped, 1 deselected (was
  1225).  Pre-existing ``test_malformed_input_raises`` parser
  failure unchanged.

**Engine status after this session**:

| engine | tests | status |
|---|---:|---|
| sfdp | 50 | C-aligned end to end: clusters (deriveGraph) + multilevel coarsening + spring-electrical force iteration + stress majorization smoothing |

What's left for sfdp is now optional perf work only — see
TODO §4.S-quadtree for the Barnes-Hut O(n log n) port plan.

Files: ``gvpy/engines/layout/sfdp/sparse_solve.py`` (new,
~165 lines), ``gvpy/engines/layout/sfdp/post_process.py``
(new, ~580 lines), ``gvpy/engines/layout/sfdp/sfdp_layout.py``
(``_post_process_smoothing_c_aligned`` method,
``GVPY_SFDP_POST_PROCESS`` gate, smoothing-call wired into
``_layout_component_c_aligned``), ``tests/test_sfdp_layout.py``
(+11 tests in ``TestSfdpPostProcessCAligned``).

---

## §4.S-spring-electrical — Sfdp spring_electrical.c port — 2026-05-09

Port of ``lib/sfdpgen/spring_electrical.c`` (1206 C lines) —
the actual force iteration that drives sfdp.  Replaces sfdp's
homegrown FR + Barnes-Hut path with a faithful C-aligned
slow-variant embedding plus the multilevel descent that sits on
top of the Galerkin hierarchy shipped in §4.S-multilevel.

**New module**: ``gvpy/engines/layout/sfdp/spring_electrical.py``
(~430 lines).  Uses numpy for the all-pairs-repulsion array
operations and scipy.sparse CSR for per-edge attractive forces.

**What ported** (verbatim mirrors of C):

- ``SpringElectricalControl`` dataclass — defaults match
  ``spring_electrical_control_new`` (spring_electrical.c:51).
- ``average_edge_length`` (spring_electrical.c:153) — mean
  Euclidean distance over CSR entries.
- ``_update_step`` (spring_electrical.c:171) — three-branch
  adaptive cooling: ``Fnorm grew → cool=0.90·step``;
  ``Fnorm in (0.95·prev, prev) → step unchanged``;
  ``Fnorm dropped sharply → 0.99·step/cool`` (warm up).
  Non-adaptive fallback always cools.
- ``_power_law_graph`` (spring_electrical.c:872) — heuristic
  driving auto-p selection (-1.8 for power-law, -1 otherwise).
- ``spring_electrical_embedding`` (mirrors
  ``spring_electrical_embedding_slow``, spring_electrical.c:393):
  - Per iteration: vectorised O(n²) repulsive force
    (``f += KP·(xᵢ-xⱼ)/dist^(1-p)``, KP=K^(1-p)) via numpy
    broadcast over the pairwise difference array; per-edge
    attractive force (``f -= CRK·(xᵢ-xⱼ)·dist``,
    CRK=C^((2-p)/3)/K) via CSR indptr/indices loop.
  - Normalise each node's force to unit length, step by ``step``.
  - Cool ``step`` adaptively; terminate when ``step < tol·K``
    or maxiter reached.
- ``interpolate_coord`` (spring_electrical.c:832) — α=0.5 blend
  of each node toward its neighbour mean.
- ``prolongate`` (spring_electrical.c:855) —
  ``xf = P·xc → interpolate_coord → per-cluster jitter`` for
  members 2..end (cluster representative untouched).  C uses
  R's CSR rows to enumerate cluster members; we do the same.
- ``multilevel_spring_electrical_embedding`` (mirrors
  ``multilevel_spring_electrical_embedding``,
  spring_electrical.c:1073, minus QuadTree / edge-label-node /
  post-process / overlap-removal blocks): walks to coarsest
  level, runs ``spring_electrical_embedding`` per level,
  prolongates between levels, applies ``random_start=False``,
  ``adaptive_cooling=False``, ``step=0.1``, ``K *= 0.75`` for
  each finer level — verbatim with C.
- ``pcp_rotate`` (spring_electrical.c:896) — principal-axis
  rotation for stable orientation; closed-form 2×2
  eigendecomposition matches C's specific axis selection.

**What was deliberately skipped**:

- **QuadTree / Barnes-Hut** (``spring_electrical_embedding_fast``,
  ``spring_electrical_embedding`` regular variant): would
  require porting ``lib/sparse/QuadTree.c`` (~600 lines).  Out
  of scope; the slow O(n²) variant is correct, vectorised, and
  fast enough for n ≤ ~500.  The existing Python Barnes-Hut
  implementation stays available behind
  ``GVPY_SFDP_SPRING_ELECTRICAL=legacy``.
- **Edge label node handling** (``shorting_edge_label_nodes``,
  ``attach_edge_label_coordinates``): GraphvizPy's
  ``edge_labeling_scheme`` attribute isn't wired through yet.
- **post_process_smoothing**: separate port (post_process.c
  1034 LOC), tracked for the next session.
- **remove_overlap**: handled by the engine's
  ``_remove_overlap`` / ``xlayout`` after the descent returns
  — no behavioural change.

**Engine wiring** (``SfdpLayout``):

- Renamed old multi-level body to
  ``_layout_component_legacy(node_list, adj)``.
- New ``_layout_component_c_aligned`` builds a CSR adjacency,
  runs ``multilevel_new`` to build the hierarchy (the
  §4.S-multilevel port), then calls
  ``multilevel_spring_electrical_embedding`` with a numpy
  coords array.  Pinned nodes are mapped into unit-K space and
  marked in a ``pinned_mask`` so the descent leaves them put.
  Final coords rescale by ``self.K`` for pt-space consumers.
- Dispatch in ``_layout_component`` behind
  ``GVPY_SFDP_SPRING_ELECTRICAL=c|legacy`` (default ``c``).

**Verification** (smoke + property tests):

- 4-cycle: edge:diagonal ratio ≈ √2 (square layout) ✓.
- 16-path multilevel: 16 → 9 → 5 hierarchy descent; non-edge
  mean / edge mean ratio ≈ 4.7× — well-separated.
- ``average_edge_length`` exact on equilateral triangle.
- ``_update_step`` all three adaptive branches verified.
- ``interpolate_coord`` correct on triangle (manually checked).
- ``pcp_rotate`` aligns y=2x noisy cloud principal axis with
  x-axis (variance ratio inverts after rotation).
- Pinned-mask honored (3-triangle test: pinned nodes' coords
  unchanged, unpinned moves toward them).
- Engine dispatch default = c; legacy still selectable.

**Test counts**:

- sfdp tests: **39 passed** (was 28; +11 ``TestSfdpSpringElectricalCAligned``).
- Full suite: **1225 passed**, 4 skipped, 1 deselected (was
  1214).  Pre-existing parser test failure
  (``test_malformed_input_raises``) is unrelated.

**What this leaves on the table** for the last sfdp session:

- ``post_process.c`` (1034 lines) + ``stress_model.c`` (47 lines)
  + ``sparse_solve.c`` (146 lines): full stress majorization
  smoothing for ``smoothing=spring|avg_dist|graph_dist``.
  Currently ``_smoothing_pass`` is a stub — non-default
  smoothing modes silently fall through.  Independent of this
  port; can ship anytime.

Files: ``gvpy/engines/layout/sfdp/spring_electrical.py`` (new,
~430 lines), ``gvpy/engines/layout/sfdp/sfdp_layout.py``
(``_layout_component`` dispatcher + ``_layout_component_c_aligned``
+ ``_layout_component_legacy``),
``tests/test_sfdp_layout.py`` (+11 tests in
``TestSfdpSpringElectricalCAligned``).

---

## §4.S-multilevel — Sfdp Multilevel.c port (C-aligned coarsening) — 2026-05-08

Port of ``lib/sfdpgen/Multilevel.c`` (304 C lines) — the
multilevel coarsening hierarchy that sfdp's spring-electrical
solver runs on.  Replaces the homegrown greedy heaviest-edge
matching with C's MIES + supervariable preprocessing +
Galerkin coarsening.

**New module**: ``gvpy/engines/layout/sfdp/multilevel.py``
(~470 lines).  Uses ``scipy.sparse`` (already a project dep)
for the SparseMatrix machinery.

**Algorithm** (mirrors C verbatim):

1. **Supervariable decomposition** — ``_decompose_to_supervariables``
   ports ``SparseMatrix_decompose_to_supervariables`` from
   ``lib/sparse/SparseMatrix.c:1352``.  Groups nodes that share
   *identical* neighbour sets ("modules" in graph theory).
   For most graphs this returns one supervariable per node.
2. **Supernode pre-clustering** — for every supervariable with
   ≥ 2 members, cluster up to ``MAX_CLUSTER_SIZE=4`` per
   cluster.
3. **MIES heavy-edge matching** —
   ``_maximal_independent_edge_set`` ports
   ``maximal_independent_edge_set_heavest_edge_pernode_supernodes_first``
   from Multilevel.c:56.  Random-permutation order; for each
   unmatched node, find its heaviest unmatched neighbour and
   pair them.
4. **Singleton fallback** — any node still unmatched becomes
   its own 1-element cluster.

**Galerkin coarsening at each level** (mirrors
Multilevel.c:146 ``Multilevel_coarsen_internal``):

- Build ``P``: n×nc prolongation matrix; ``P[i, c] = 1`` iff
  node ``i`` is in cluster ``c``.
- ``R = P^T`` then row-normalise by degree (so prolongation
  back averages cluster member positions).
- ``cA = R · A · P`` — Galerkin product; edge weights aggregate
  correctly through this matrix multiplication.
- Strip diagonal of cA.

**Outer coarsening loop** (Multilevel.c:204
``Multilevel_coarsen``): iterate single steps until reduction
ratio falls below ``min_coarsen_factor=0.75``.  Multiplies
P/R together so the cumulative transformation maps the
original A to the final coarsened cA.

**Hierarchy build** (Multilevel.c:248-294
``Multilevel_establish`` + ``Multilevel_new``): recursive
descent; bottoms out when ``n < minsize=4`` or no further
reduction is possible.

**Adapter**: ``multilevel_to_legacy_levels(grid, node_names)``
converts the C-aligned hierarchy to the legacy
``[{nodes, adj, mapping}]`` shape the existing
``SfdpLayout._spring_electrical`` consumes.  Each cluster at
every coarsening level is identified by the **first member's
name** (deterministic via sorted indices) — this keeps every
hierarchy-level node name resolvable in ``layout.lnodes``,
so the existing flat solver runs without needing
synthetic-supernode entries installed.

``mapping[child_rep_name] = parent_rep_name`` lets the
existing prolongation step interpolate from a coarse level
to its finer level by copying the parent's position into
each child.

**Wiring**: ``SfdpLayout._build_hierarchy`` dispatches on
``GVPY_SFDP_MULTILEVEL`` env var:

- ``c`` (default since 2026-05-08): port of Multilevel.c.
- ``legacy``: pre-port homegrown matching.  Kept for
  diagnostic comparison.

**Verification on a 30-node 5-regular graph**:

```
[TRACE sfdp_multi] level=0 n=30 nz=120 density=0.1333
[TRACE sfdp_multi] level=1 n=16 nz=84 reduction=0.533
[TRACE sfdp_multi] level=2 n=8 nz=42 reduction=0.500
[TRACE sfdp_multi] level=3 n=5 nz=18 reduction=0.625
```

Each level achieves ≤ 0.75 reduction ratio (faster than the
``min_coarsen_factor`` threshold); 4 hierarchy levels for a
30-node graph.

**Tests**: 6 new in ``TestSfdpMultilevelCAligned``:
- ``test_cycle_8_coarsens``
- ``test_path_16_multilevel``
- ``test_singleton_doesnt_coarsen``
- ``test_galerkin_preserves_edge_weight_sum``
- ``test_legacy_adapter_resolvable_names``
- ``test_dispatch_gate``

**Test suite**: **1214 passed**, 4 skipped, 1 deselected
(was 1208).  28 sfdp tests (was 22).  No regressions.

**What this leaves on the table** for next sessions:

- ``spring_electrical.c`` (1206 lines): the actual force
  iteration.  Has its own multilevel-aware logic
  (``stable_outer_loop``, ``prolongate``,
  ``interpolate_coord``, adaptive cooling) that we'd port to
  replace ``SfdpLayout._spring_electrical``.
- ``post_process.c`` (1034 lines) + ``stress_model.c`` (47
  lines) + ``sparse_solve.c`` (146 lines): stress smoothing
  for ``smoothing=spring|avg_dist|graph_dist``.

The Galerkin coarsening built here is a foundation those
ports will compose on top of — the SparseMatrix machinery
in ``multilevel.py`` is already shaped for the matrix-vector
operations ``spring_electrical.c`` needs.

**Trace channel**: ``GVPY_TRACE_SFDP=1`` emits
``[TRACE sfdp_multi] ...`` lines for level/coarsening
counts.

---

## §4.S-derivegraph — Sfdp inherits fdp's deriveGraph cluster pipeline — 2026-05-08

Sfdp's session-1 deliverable: cluster awareness end-to-end by
reusing fdp's deriveGraph infrastructure.  Sfdp dispatches to
the same recursive two-level layout but plugs in its own
spring-electrical solver via engine-pluggable callbacks.

**Why open this thread:** sfdp needs the same cluster handling
fdp has — without it, sfdp produces overlapping cluster boxes
on clustered graphs.  Rather than duplicate the simple-fix
band-aids fdp shipped 2026-05-08, sfdp inherits the full
deriveGraph pipeline directly.  The next sessions can layer
sfdp-specific multilevel coarsening and Barnes-Hut on top
without compounding band-aids.

**derive.py refactor (engine-agnostic):**

- ``recursive_layout(layout, scope, *, force_solver=None,
  overlap_solver=None)`` — accepts pluggable callbacks for
  the per-scope force pass and the bbox-aware overlap pass.
  Defaults: fdp's ``tlayout`` + ``xlayout``.  Engines that
  pass alternates (sfdp does) keep all the cluster
  orchestration: bottom-up recursion, derived graph build,
  proxy installation, translate-to-proxy, bbox recompute.
- ``derive_graph_layout(layout, *, force_solver=None,
  overlap_solver=None)`` — same callback shape at the top
  level.
- ``_install_proxy_lnodes`` — duck-types the engine's
  ``LayoutNode`` class from existing entries instead of
  importing fdp's directly, so sfdp's LayoutNode (which adds
  a ``mass`` field) instantiates correctly.

**SfdpLayout wiring:**

- ``__init__`` adds ``_clusters`` / ``_cluster_parent`` /
  ``_cluster_level`` / ``_node_to_cluster`` /
  ``_node_to_cluster_obj`` (engine-agnostic fdp helpers).
- ``_init_from_graph`` calls ``discover_clusters`` +
  ``build_node_to_cluster`` after node materialisation;
  edges are enumerated via a new ``_iter_all_edges`` that
  walks ``gather_all_subgraphs`` (subgraph-edge fix from
  §4.F-clusters).
- ``layout()`` dispatches to ``derive_graph_layout`` when
  clusters present (gated on ``GVPY_SFDP_DERIVE_GRAPH=1``,
  default on); flat graphs continue through the existing
  multilevel + quadtree path.
- New ``_sfdp_force_solver`` adapts sfdp's
  ``_spring_electrical`` to the
  ``(layout, node_list, edges, K, maxiter)`` callback shape
  (builds adjacency from the lifted edge list).
- New ``_sfdp_overlap_solver`` bridges to fdp's
  ``xlayout(node_subset=...)`` for proper bbox-aware
  overlap removal at each scope.  (Sfdp's homegrown
  ``_remove_overlap`` uses an incorrect distance metric
  that can't separate cluster proxies whose bboxes are
  100-200 pt wide.)
- ``_to_json`` and ``_write_back`` overrides emit cluster
  bboxes for SVG / -Tdot output (mirror FdpLayout).
- After ``derive_graph_layout`` returns,
  ``compute_cluster_bboxes(self)`` runs once to refresh
  the root-level bboxes (``recursive_layout`` only
  refreshes non-root scopes).

**Verified on ``test_data/fdp_cluster_demo.gv``** (3 sibling
clusters + 2 root-level free nodes):

```
[TRACE fdp_derive] derive_graph_layout: starting recursive layout
[TRACE fdp_derive] recursive_layout: ROOT (depth=0)
[TRACE fdp_derive]   recursive_layout: cluster_left (depth=1)
[TRACE fdp_derive] derive_graph(scope=cluster_left): 3 derived nodes, 2 edges
[TRACE fdp_xlayout] cleared in attempt=0 iter=3
[TRACE fdp_derive]   recursive_layout: cluster_right (depth=1)
[TRACE fdp_derive] derive_graph(scope=cluster_right): 3 derived nodes, 2 edges
[TRACE fdp_xlayout] cleared in attempt=0 iter=3
[TRACE fdp_derive]   recursive_layout: cluster_middle (depth=1)
[TRACE fdp_derive] derive_graph(scope=cluster_middle): 2 derived nodes, 1 edges
[TRACE fdp_xlayout] cleared in attempt=0 iter=2
[TRACE fdp_derive] derive_graph(scope=ROOT): 5 derived nodes, 4 edges
[TRACE fdp_xlayout] cleared in attempt=0 iter=9
```

Final cluster bboxes are non-overlapping at distinct positions.

**Tests**: 6 new in ``TestSfdpClusters``:
- ``test_clusters_discovered``
- ``test_cluster_bboxes_computed_and_emitted``
- ``test_cluster_bboxes_dont_overlap``
- ``test_cluster_members_inside_bbox``
- ``test_flat_graph_skips_derive_graph``
- ``test_subgraph_edges_drive_cohesion``

Test suite: **1208 passed**, 4 skipped, 1 deselected (was
1202).  22 sfdp tests (was 16).  43 fdp tests unchanged
(derive.py refactor preserves fdp behaviour with default
callbacks).

**What's intentionally NOT ported yet** — these are the
sfdp-specific pieces that should follow in subsequent
sessions:

| C source | lines | Py status | next-session port |
|---|---:|---|---|
| ``Multilevel.c`` | 304 | homegrown coarsening | C-aligned MIES + heavy-edge matching with proper supernode handling |
| ``spring_electrical.c`` | 1206 | homegrown F-R + quadtree | C-aligned solver: stable_outer_loop, oned_optimizer step adaptation, prolongate / interpolate_coord |
| ``post_process.c`` | 1034 | not ported | stress smoothing (smoothing=spring/avg_dist/graph_dist) |
| ``sparse_solve.c`` | 146 | not ported | sparse linear solver — needed by stress_model |
| ``stress_model.c`` | 47 | not ported | stress majorization for smoothing |
| ``sfdpinit.c`` | 319 | minimal | input parsing; partially aligned, mostly attribute reading |

**Open follow-up sessions** (each independently shippable):

1. **Multilevel.c port (1-2 days)** — port C's MIES /
   heavy-edge matching for proper coarsening hierarchy.
   Replaces the homegrown matching in
   ``SfdpLayout._build_hierarchy``.
2. **spring_electrical.c port (2-3 days)** — port C's
   stable_outer_loop, prolongate, interpolate_coord, and
   adaptive cooling.  Replaces ``_spring_electrical``.
3. **Stress smoothing (post_process.c + stress_model.c +
   sparse_solve.c, 2-4 days)** — full stress majorization
   for ``smoothing=spring|avg_dist|graph_dist``.

**Trace channels reused**: ``GVPY_TRACE_FDP=1`` shows
``[TRACE fdp_cluster] / [TRACE fdp_derive] /
[TRACE fdp_xlayout]`` lines from the shared infrastructure.
``GVPY_SFDP_DERIVE_GRAPH=0`` reverts to the homegrown
multilevel path for diagnostic comparison.

---

## §4.F-derivegraph — Fdp deriveGraph two-level layout (full C port) — 2026-05-08

Full port of C `lib/fdpgen/layout.c: layout()` — the
deriveGraph two-level recursive pipeline.  Replaces the
quick-fix post-passes (``remove_cluster_overlap``,
``push_nonmembers_out_of_clusters``) with a structurally
correct hierarchical force-directed layout.

**Why:** The simple post-passes shipped 2026-05-08 gave most
of the visual benefit but the layouts didn't match C's
hierarchical placement.  When the next engine (sfdp) builds
on fdp, it should inherit the proper algorithm rather than
band-aids.

**Algorithm** (mirrors C ``layout()`` at lines 800-923):

1. **Bottom-up recursion**: lay out each cluster's interior
   first.  When a cluster's recursion returns, its ``bb`` is
   set to the bbox of its (now-positioned) members.
2. **deriveGraph(scope)**: at the parent scope, build a
   *derived graph* — one proxy node per direct child cluster
   (sized to the cluster's ``bb``), one pass-through node per
   direct member.  Edges are "lifted" to the derived graph:
   each endpoint maps to the immediate child of the scope
   that contains it; self-loops (both endpoints map to the
   same child) are dropped.
3. **tlayout** on the derived graph (proxies + free nodes
   treated as flat F-R nodes; proxy size in the force model =
   cluster bbox size).
4. **xlayout** on the derived graph with ``node_subset``
   restricting overlap removal to this scope's nodes
   (proxies and direct members).  Crucial: ``tlayout``'s F-R
   uses K=21.6 by default and can't separate proxies whose
   bboxes are 100-200 pt wide; xlayout's bbox-aware overlap
   pass enforces non-overlap.
5. **Translate**: for each cluster proxy, move every
   transitive member of the cluster so its centroid lands at
   the proxy's final position.
6. **Recompute bboxes**.

**New module**:
``gvpy/engines/layout/fdp/derive.py`` — ``DerivedNode`` /
``DerivedGraph`` dataclasses, ``derive_graph(layout, scope)``,
``recursive_layout(layout, scope, depth=0)``,
``derive_graph_layout(layout)`` (top-level entry).

**Modifications**:

- ``FdpLayout.layout()``: gated dispatch on
  ``GVPY_FDP_DERIVE_GRAPH=1`` (default on as of this commit).
  When clustered, calls ``derive_graph_layout``; flat graphs
  fall through to the existing per-component
  ``_layout_component`` path.
- ``FdpLayout.layout()``: skip the simple-fix post-passes
  (``remove_cluster_overlap``,
  ``push_nonmembers_out_of_clusters``) when deriveGraph is
  active — the deriveGraph pipeline already produces
  non-overlapping clusters with non-members placed correctly.
- ``xlayout``: added optional ``node_subset`` parameter so
  recursive layout can run xlayout at one scope without
  disturbing already-laid-out nodes from other scopes.

**What's deliberately left out vs C** (kept simple; can be
added later if needed):

- **Port nodes** (``IS_PORT``, ``getEdgeList``, ``genPorts``).
  C uses these to provide cluster-edge attachment angles
  during the recursive layout.  Py routing handles cluster
  edges via ``compoundEdges`` post-layout — port info not
  needed for an initial layout.
- **Pinned-cluster placement** (``chkPos``).  Minor; fdp
  pins are barely used.
- **finalCC normalize/translate-to-origin**.  The existing
  ``apply_normalize`` / ``apply_center`` post-pass handles
  this.
- **Connected-component split inside the derived graph**.  C
  packs disconnected components separately via ``putGraphs``;
  Py relies on F-R repulsion in tlayout + xlayout's
  bbox-overlap pass to spread proxies that lack inter-edges.
  Sufficient for the current test corpus.

**Verification** on ``test_data/fdp_cluster_demo.gv`` (3
sibling clusters, root-level free nodes a, b):

```
[TRACE fdp_derive] derive_graph_layout: starting recursive layout
[TRACE fdp_derive] recursive_layout: ROOT (depth=0)
[TRACE fdp_derive]   recursive_layout: cluster_left (depth=1)
[TRACE fdp_derive] derive_graph(scope=cluster_left): 3 derived nodes, 2 edges
[TRACE fdp_derive]   recursive_layout: cluster_right (depth=1)
[TRACE fdp_derive] derive_graph(scope=cluster_right): 3 derived nodes, 2 edges
[TRACE fdp_derive]   recursive_layout: cluster_middle (depth=1)
[TRACE fdp_derive] derive_graph(scope=cluster_middle): 2 derived nodes, 1 edge
[TRACE fdp_derive] derive_graph(scope=ROOT): 5 derived nodes, 4 edges
[TRACE fdp_derive] derive_graph_layout: done
```

Final cluster bboxes:
- cluster_left:   x=-170..-29, y=82..264 (left)
- cluster_right:  x=  1..156,  y=113..253 (right)
- cluster_middle: x=-112..-18, y=-123..-17 (upper-left)

Three disjoint cluster rects.  Free nodes a, b in the
central area, both outside every cluster.  No node-node
overlap.

**Test fixture for nested clusters**:
``test_data/fdp_nested_demo.gv`` — ``cluster_inner`` inside
``cluster_outer``.  ``test_derive_graph_nested_clusters``
asserts inner ⊂ outer post-layout.

**Tests**: 1 new test
(``test_derive_graph_nested_clusters``).  Also revised
``test_connected_intruders_escape_same_side`` →
``test_connected_intruders_not_split_across_cluster`` to
check the actual property (segment a→b doesn't cross the
cluster bbox) instead of a tight diagonal threshold tuned
to the simple-fix path.

Test suite: **1202 passed**, 4 skipped, 1 deselected (was
1201).  43 fdp tests (was 42).  No regressions.

**Trace channel**: ``GVPY_TRACE_FDP=1`` extends with
``[TRACE fdp_derive] ...`` for derive-graph build,
recursive-layout entry/exit, and bbox tracking.

**Default flag**: ``GVPY_FDP_DERIVE_GRAPH=1`` is the default;
set ``GVPY_FDP_DERIVE_GRAPH=0`` to revert to the simple-fix
post-passes (kept for diagnostic comparison).

**Why this matters for sfdp**: sfdp builds on fdp
(multilevel coarsening + Barnes-Hut quadtree + same force
model).  By making fdp's hierarchical layout structurally
correct, sfdp inherits a clean foundation rather than
band-aids that would compound at multiple levels of
multilevel hierarchy.

---

## §4.F-clusters — Fdp cluster-aware routing + visual cluster passes — 2026-05-08

End-to-end port of fdp's cluster-aware spline routing
(C `lib/fdpgen/clusteredges.c`) plus the visual passes
(cluster cohesion, cluster-cluster separation, free-node
escape, group coordination, perpendicular spread).

After this session the fdp engine produces visually
clean clustered layouts: cluster members cohesive,
cluster boxes non-overlapping, free nodes outside
non-member cluster bboxes, connected free-node pairs
on the same side of a cluster (short edges), no
intra-group node overlap.

**Two stacked routing bugs fixed:**

1. ``base._write_back`` ignored ``edge_routes`` — now
   emits the multi-point spline ``pos`` instead of a
   2-point straight-line fallback.  Affects fdp / neato
   / twopi / sfdp / osage / patchwork uniformly.
2. ``route_edges`` ignored clusters — fdp now dispatches
   to a new cluster-aware path on clustered graphs.

**Phase A — cluster tracking on FdpLayout.**  New
module ``gvpy/engines/layout/fdp/cluster.py``:

- ``FdpCluster`` dataclass (name, direct_nodes,
  transitive nodes, margin, label, attrs, bb).
- ``discover_clusters(layout)`` — recursive subgraph
  walk building ``layout._clusters``,
  ``_cluster_parent`` (mirrors C ``GPARENT``),
  ``_cluster_level`` (mirrors C ``LEVEL``).
- ``build_node_to_cluster(layout)`` — populates
  ``_node_to_cluster`` / ``_node_to_cluster_obj``
  (mirrors C ``ND_clust(n)`` / ``PARENT(n)``).
- ``compute_cluster_bboxes(layout)`` — fills each
  cluster's ``bb`` from member positions plus margin.

Wired into ``FdpLayout.__init__`` /
``_init_from_graph`` / ``layout()``.

**Phase B — ``objectList`` + ``compoundEdges``.**
Added to ``common/edge_routing.py``
(engine-agnostic; duck-types on Phase A's cluster
fields):

- ``_cluster_bbox_polygon(cl, margin)`` — CW Ppoly
  from a cluster bbox.
- ``_gparent(layout, g)`` — C ``GPARENT`` macro.
- ``_add_graph_objs(layout, g, tex, hex_, polys, margin)``
  — C ``addGraphObjs`` (clusteredges.c:104).
- ``object_list(layout, edge, margin)`` — C
  ``objectList`` (clusteredges.c:151).  Walks both
  endpoints up to their cluster LCA, excluding the
  endpoints' enclosing clusters and any common
  ancestors.
- ``route_edges_compound(layout)`` — C
  ``compoundEdges`` (clusteredges.c:207).  Per-edge
  ``Pobsopen`` / ``Pobspath`` / ``Pobsclose`` loop.

``FdpLayout.layout()`` dispatches to
``route_edges_compound`` when ``self._clusters`` is
non-empty; flat graphs continue through
``route_edges`` (regression-safe).

**Phase C — cluster bbox emission.**  Extended
``FdpLayout._to_json`` to emit a ``"clusters"`` array
matching dot's format (so the shared SVG renderer
draws cluster outlines).  Added an
``FdpLayout._write_back`` override that walks the
subgraph tree and writes
``sub.attr_record["bb"] = "x1,y1,x2,y2"`` on each
``cluster*`` subgraph, putting cluster geometry into
``-Tdot`` round-trips.

**Phase D (partial) — visual cluster cohesion +
separation.**  Quick fixes that give most of the
visual benefit of C's ``deriveGraph`` two-level
pipeline at much lower cost:

1. **Edges inside subgraph blocks now contribute to
   the force model.**  The Py parser stores
   intra-cluster edges in the subgraph's own
   ``.edges`` dict (lowest-common-subgraph rule).
   Added ``FdpLayout._iter_all_edges`` walking
   ``gather_all_subgraphs`` and used it in every fdp
   edge-iteration site.  Same fix to base
   ``_write_back`` and ``_to_json``.  Without this,
   5 of 10 edges on the demo graph were silently
   dropped, leaving cluster members with no internal
   cohesion.
2. ``remove_cluster_overlap`` — iteratively
   translates whole top-level clusters apart along
   the smaller-overlap axis until no top-level pair
   overlaps (≥ ``sep=20`` pt gap).  Members move
   with their cluster.
3. ``push_nonmembers_out_of_clusters`` —
   coordinated-group escape: for each cluster, group
   non-member intruders into connected components
   (via their own edges), then pick the SAME
   cardinal escape direction for the whole group
   that minimizes total post-push edge length.
   Connected pairs end up on the same side of a
   cluster (short edges) instead of split across
   opposite sides.
4. **Intra-group spread.**  After picking the escape
   direction, sort group members along the
   perpendicular axis and bump overlapping pairs
   apart so each consecutive pair sits at least
   ``half_a + half_b + sep`` apart.

Sequence in ``FdpLayout.layout()``:
``tlayout → xlayout → compute_cluster_bboxes →
remove_cluster_overlap →
push_nonmembers_out_of_clusters →
compute_cluster_bboxes (recompute) →
route_edges_compound``.

**Tests: 21 new in ``test_fdp_layout.py``** (5 in
``TestFdpClusterTracking``, 6 in
``TestFdpCompoundRouting``, 7 in
``TestFdpClusterEmit``, 3 inside the cluster-emit
class for cluster overlap / cohesion / coordinated
escape / no-stack).  Full suite: **1201 passed**, 4
skipped, 1 deselected (was 1181 at start of work).
**42 fdp tests** (was 22).

**Test fixture:** ``test_data/fdp_cluster_demo.gv``
— three sibling clusters with cross-cluster edges.

**Open follow-up (deferred):** full C ``deriveGraph``
two-level layout port (collapse clusters → proxy
nodes; lay out derived graph; recursively lay out
each cluster's interior; ``expandCluster`` to
translate members to proxy positions).  The current
quick-fixes give most of the visual benefit; the
proper port lands a node-for-node match with C.
Estimated 1-2 days when needed.

**Trace channels:**
- ``GVPY_TRACE_FDP=1`` for cluster discovery, bbox,
  overlap-removal, push-out steps.
- ``GVPY_TRACE_NEATO=1`` (shared) for routing.

**Note:** neato's ``spline_edges_`` (neatosplines.c:580)
explicitly says "intra-cluster edges are not
constrained to remain in the cluster's bounding box"
— neato is DESIGNED to ignore clusters.  Py's neato
is correctly matching that.  Only fdp differs.

**Side-issues surfaced (separate parser bugs, not
blocking):**

- Edges declared INSIDE subgraph blocks aren't
  registered by the Py parser (e.g. ``subgraph X
  { a -- b; }`` produces zero edges).
- Edges declared AFTER subgraph blocks at the root
  level also aren't registered.

Workaround in fixtures: declare edges BEFORE
subgraph blocks.  Worth filing properly when next
touched.

---

## §4.F — Fdp engine C-alignment (full port) + neato → common refactor — 2026-05-02

Two-pronged work: (1) refactor the engine-agnostic neato modules
into `common/` so fdp (and future engines) can share them, and
(2) port `lib/fdpgen/` to a multi-module Py package that uses the
common infrastructure end-to-end.

**common/ refactor** — three modules promoted from `neato/`:

| Old path | New path | Why |
|---|---|---|
| `neato/adjust.py` | `common/adjust.py` | Overlap-mode dispatcher is duck-typed on `lnodes`/`sep`/`overlap`; no neato specifics. |
| `neato/voronoi.py` | `common/voronoi.py` | Same. |
| `neato/splines.py` | `common/edge_routing.py` | Edge-routing pipeline is duck-typed on `lnodes`/`graph.edges`/`edge_routes`; renamed to avoid name collision with the existing `common/splines.py` (geometry primitives). |

The `TYPE_CHECKING` import of `NeatoLayout` was the only neato
coupling; replaced with `Any` since the API is structural.
Twopi's existing imports were updated; neato itself imports the
common modules from their new home.

**Fdp package structure** (mirrors `lib/fdpgen/`):

| Py module | C source |
|---|---|
| `fdp_layout.py` | `fdpinit.c` + `layout.c` (orchestrator) |
| `tlayout.py` | `tlayout.c` (Phase 1 force-directed) |
| `xlayout.py` | `xlayout.c` (Phase 2 overlap-aware) |
| `grid.py` | `grid.c` (spatial index) |

**Phase 1 — `tlayout`.**  Fruchterman-Reingold spring-electrical
model.  Per iteration: clear displacements, compute repulsive
forces (grid-accelerated when `use_grid` and N > 20), apply
attractive forces along edges, cap displacement by linearly-
cooling temperature.  Mirrors `tlayout.c::layoutSubGraph`.

**Phase 2 — `xlayout`.**  Force-based overlap removal.  Up to 9
attempts; each grows `K` by 50%.  Inner loop uses a modified
F-R: overlapping pairs get `1.5 K²` repulsion, non-overlapping
pairs get `0.1 K²`; edge attraction uses clear-distance after
subtracting the bounding-box "radius".  Mirrors
`xlayout.c::fdp_xLayout`.  Used when `overlap=fdp`.

**Overlap mode dispatch.**  `overlap=fdp` runs the historical
xlayout pass; everything else (`scale`, `scalexy`, `compress`,
`voronoi`, `prism`, `ortho`, etc.) routes through the shared
`common.adjust.remove_overlap` dispatcher — same modes as neato
and twopi expose.

**Edge spline routing.**  Reuses `common.edge_routing.route_edges`
(the same path-planning + Schneider Bezier fit pipeline neato and
twopi use).  `splines=true`/`spline`/`polyline`/`line`/`false`
all work; `_to_json` mirrors NeatoLayout / TwopiLayout in
emitting multi-point routes when `edge_routes` is populated.

**Trace channel:** `GVPY_TRACE_FDP=1` emits `[TRACE fdp_*]` lines
across `tlayout` and `xlayout` phases.

22/22 fdp tests pass (6 new alignment tests for grid build,
neighbour offsets, overlap dispatcher routing, splines bezier /
polyline modes, and xlayout overlap clearance).  Full suite 1138
pass, 4 skip.

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
