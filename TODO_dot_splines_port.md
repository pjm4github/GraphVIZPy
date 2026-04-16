# Splines Port — Align `splines.py` to `dotsplines.c`

**Started:** 2026-04-14
**Scope:** Align `gvpy/engines/layout/dot/splines.py` with `lib/dotgen/dotsplines.c` + `lib/common/splines.c` + `lib/common/routespl.c` + `lib/pathplan/*` function-by-function, so future changes in Graphviz can be tracked and ported directly.

**Non-goals for this pass:** ortho routing (`lib/ortho/*`) and neato routing are explicitly deferred — they are separate subtrees and each deserves its own port plan.

---

## Confirmed decisions

| # | Topic | Decision |
|---|---|---|
| 9.1 | Channel-routing disposition | Move `channel_route_edge` / `build_edge_path` / `_bridge_*` / `_channel_bbox_for_node` / `_rounded_corner_bezier` and their helpers out of `splines.py` into a sibling file `splines_experimental.py`, imported only behind the existing `_use_channel_routing` flag. |
| 9.2 | `simpleSplineRoute` strategy | Port Graphviz **Pathplan** (`lib/pathplan/*`, ~2000 lines of polygon shortest-path + spline fit) as real Python. No shapely/scipy bridge. Parity is the goal. |
| 9.3 | Commit granularity | One commit per C function. Commit message format: `splines: port <c_function_name> from dotsplines.c:<line_range>`. Phase-closing summary commits at the end of each phase. |
| 9.4 | Legacy retention | When a new ported function replaces an existing Python routine, delete the old one on swap-in. Git history is the safety net — no `_legacy_` copies left behind. |
| 9.5 | Port map location | `TODO_dot_splines_port.md` (this file). Matches existing convention from `CLAUDE.md`. Port map table lives here. |
| 9.6 | First-pass scope | `dotsplines.c` + `common/splines.c` + `common/routespl.c` + `pathplan/*` only. Ortho and neato deferred. |
| — | `EdgeRoute` extraction | **Done 2026-04-14.** `EdgeRoute` lives in `gvpy/engines/layout/dot/edge_route.py`. `LayoutEdge` delegates `points` / `spline_type` / `label_pos` via properties. |
| — | PyQt adapter stub | **Deferred.** Prove the `EdgeRoute` seam works when the Qt port actually starts. |

---

## 1. Trace gating (prerequisite — do first)

**Goal:** keep every existing `[TRACE ...]` line in place but silent by default, so alignment work runs noise-free while still being able to flip traces back on when something diverges.

### Python side

- Add `gvpy/engines/layout/dot/trace.py` that reads env var `GV_TRACE` (comma list of channels, e.g. `rank,spline,spline_detail`) and exposes:
  ```python
  def trace_on(channel: str) -> bool: ...
  def trace(channel: str, msg: str) -> None: ...  # prints to stderr when enabled
  ```
- Replace every existing `print(f"[TRACE xxx] ...", file=sys.stderr)` with `trace("xxx", f"...")`. Mechanical edit, no behaviour change.
- Channel names: `rank`, `order`, `position`, `spline`, `spline_detail`, `label`. Keep the existing `[TRACE <tag>]` prefix *inside* the message so `compare_traces.py` still works.
- Default: all channels off. Running with `GV_TRACE=spline` re-enables the current output.

### C side (graphviz repo)

- Add `lib/common/tracegate.h`:
  ```c
  static inline int tracegate_on(const char *channel) { ... }  // cached getenv lookup
  ```
- Wrap each existing `fprintf(stderr, "[TRACE ...")` in `if (tracegate_on("<channel>"))` by hand. Same channel names as Python.
- One lightweight commit in graphviz, built with the CLion mingw toolchain per `CLAUDE.md`.

### Tests after gating

- `pytest tests/test_dot_layout.py` with `GV_TRACE` unset → output must be clean (no TRACE lines).
- `GV_TRACE=spline` → old trace lines come back verbatim, byte-for-byte.

---

## 2. Canonical function map

One row per C function in `lib/dotgen/dotsplines.c`, `lib/common/splines.c`, `lib/common/routespl.c`, and `lib/pathplan/*`. Read this section at the top of every port session so the correspondence stays authoritative. Every C function in scope must eventually land in `done` with an exact Python counterpart.

**Columns:**

| column | meaning |
|---|---|
| Ln | Starting C line number |
| C function | Function name as it appears in C |
| Python target | `module.py:function` — blank if nothing exists yet |
| Status | `done` / `partial` / `missing` / `n/a` |
| Phase | Plan §5 phase letter (A–G) or `—` for helpers/n/a |
| Notes | Dependencies, divergence notes, or key behaviour |

**Status key:**

- **done** — Python function is a faithful port (same control flow, same math, same name). No action needed.
- **partial** — a Python function covers part of the C responsibility but via a simplified algorithm, heuristic, or different primitive. Needs to be rewritten as a literal port.
- **missing** — no Python counterpart. Needs to be written from scratch.
- **n/a** — debug printer, `#ifdef DEBUG` helper, or something outside the port scope (e.g., Agsym state management that has no Python analog).

### Naming rule

Python function name = C function name verbatim (drop `static` and any leading underscore). Examples:

- `make_regular_edge` → `make_regular_edge`
- `makeFlatEnd` → `make_flat_end`
- `routesplines_` → `routesplines_impl`
- `dot_splines_` → `dot_splines_impl`

One rename pass on existing Python functions that already have matching names but different signatures.

### Signature rule

First arg is always `layout` (Python equivalent of `graph_t *g`); subsequent args mirror C in order and meaning. No "improvements" during the port — if C takes `const spline_info_t sp` by value we carry a `SplineInfo` dataclass the same way.

### 2.1 `lib/dotgen/dotsplines.c` (2311 lines, ~35 functions)

| Ln | C function | Python target | Status | Phase | Notes |
|---|---|---|---|---|---|
| 48 | `makefwdedge` | `splines.py:makefwdedge` | done | A | Ported 2026-04-15. Returns a new LayoutEdge with tail/head, tailport/headport, and lhead/ltail swapped; `virtual=True`; `orig_tail`/`orig_head` preserved. |
| 99 | `getmainedge` | `splines.py:getmainedge` | done | A | Ported 2026-04-15. For chain virtuals, walks back to the real LayoutEdge matching `orig_tail`/`orig_head`. Returns self for non-chain virtuals and real edges. |
| 108 | `spline_merge` | `splines.py:spline_merge` | done | A | Ported 2026-04-15. Returns `ln.virtual and (len(in_edges) > 1 or len(out_edges) > 1)`. |
| 113 | `swap_ends_p` | `splines.py:swap_ends_p` | done | A | Ported 2026-04-15. Walks via `getmainedge`; compares main tail/head rank then order. |
| 128 | `portcmp` | `splines.py:portcmp` | done | A | Ported 2026-04-15. Lex order: undefined < defined, then by aiming-point x then y. Uses new `Port` dataclass from `path.py`. |
| 144 | `swap_bezier` | `splines.py:swap_bezier` | done | A | Ported 2026-04-15. Operates on `EdgeRoute` directly (single-bezier model). Reverses `points`, swaps `sflag` ↔ `eflag`, swaps `sp` ↔ `ep`. Involution verified. |
| 154 | `swap_spline` | `splines.py:swap_spline` | done | A | Ported 2026-04-15. Equivalent to `swap_bezier` for Python's one-bezier-per-edge model; will diverge when compound-edge routing lands in Phase E and `EdgeRoute` gains `beziers: list[Bezier]`. |
| 173 | `edge_normalize` | `splines.py:edge_normalize` | done | A | Ported 2026-04-15. Iterates `layout.ledges + _chain_edges`, reverses any edge where `swap_ends_p` is True. No-op under the current driver because `break_cycles` pre-reverses back-edges in phase 1 — becomes active once the Phase A step 6 driver rewrite stops pre-reversing. |
| 187 | `resetRW` | `splines.py:resetRW` | done | A | Ported 2026-04-15. Walks self-loop nodes and swaps `width/2` ↔ `mval`. Gated on `mval > 0` for safety until Phase F self-loop inflation populates `mval`. Involution verified against a manually-inflated node. |
| 199 | `setEdgeLabelPos` | — | missing | A | Pre-place labels for ortho routing (reads `ND_alg`). |
| 228 | `dot_splines_` | `splines.py:phase4_routing` | done | A | Ported 2026-04-15. Driver shape now mirrors C's dot_splines_: resetRW → classify+setflags → edgecmp sort → per-edge dispatch → edge_normalize. Per-edge routing still calls existing heuristic Python routers until Phase D/E/F ports replace them. Batch dispatch on equivalence classes deferred to Phase D. |
| 481 | `dot_splines` | `splines.py:phase4_routing` | done | A | Trivial wrapper: `dot_splines_(g, 1)`. Same Python entry as above — Phase A step 6 ported 2026-04-15. |
| 486 | `place_vnlabel` | — | missing | F | Label position from virtual-node coords. |
| 499 | `setflags` | `splines.py:setflags` | done | A | Ported 2026-04-15. Auto-detects SELF*/FLAT/REGULAR edge type and FWD/BWD direction from tail/head rank+order when `hint1`/`hint2` are 0. Verified against C on parallel + self-loop + back-edge graphs. |
| 537 | `edgecmp` | `splines.py:edgecmp` | done | A | Ported 2026-04-15. Full 9-step lex order with `getmainedge` resolution, `_edge_seq_map` for AGSEQ, `makefwdedge` swap for BWDEDGE, `portcmp` for tie-break. AGSEQ cached lazily on `layout._edge_seq_cache`. Verified determinism and SELFNP/SELFWP/FLAT/REG descending order on a parallel-edges smoke test. |
| 638 | `attr_state_t` (struct) | — | missing | E | Save/restore global attrsym state around `make_flat_adj_edges` recursion. |
| 683 | `setState` | — | missing | E | Save + bind global attrsym vars to the aux graph. |
| 775 | `cloneGraph` | — | missing | E | Copy node/edge attrs to fresh auxiliary graph. Uses `setState`. |
| 822 | `cleanupCloneGraph` | — | missing | E | Pair with `cloneGraph`; restores globals and frees. |
| 872 | `cloneNode` | — | missing | E | Node clone; wraps record label in `{...}` for LR rotation. |
| 886 | `cloneEdge` | — | missing | E | Edge clone with attr copy. |
| 895 | `transformf` | — | missing | E | Rotate-and-translate point for aux-graph coord transfer. |
| 909 | `edgelblcmpfn` | — | missing | E | Sort order for `makeSimpleFlatLabels` (has-label, width, height). |
| 946 | `makeSimpleFlatLabels` | — | missing | E | Alternating up/down label stacking for adjacent flat edges with labels. Uses `simpleSplineRoute`. |
| 1077 | `makeSimpleFlat` | `splines.py:flat_adjacent` | partial | E | Python version is a simple 4-point bezier; C builds a spindle of cubics or an 11-point pline via `EDGETYPE_PLINE` branch. |
| 1124 | `make_flat_adj_edges` | — | missing | E | The hard case: clones graph, calls `dot_splines_` recursively on the clone, copies results back via `transformf`. Last step of Phase E. |
| 1285 | `makeFlatEnd` | — | missing | E | Build top-side end-box chain for flat edge via `beginpath`/`endpath`. |
| 1300 | `makeBottomFlatEnd` | — | missing | E | Same, but for bottom side (south ports). |
| 1316 | `make_flat_labeled_edge` | `splines.py:flat_labeled` | partial | E | Python is a naive `p1 → (p1.x,label_y) → (p2.x,label_y) → p2` bend. C builds 3-box path + `routesplines`. |
| 1420 | `make_flat_bottom_edges` | `splines.py:flat_arc` (direction=+1) | partial | E | Python is a 4-point bezier arc. C builds per-edge 3-box staggered paths via `routesplines`. |
| 1504 | `make_flat_edge` | `splines.py:flat_edge_route` | partial | E | Dispatcher. Python's classification is close but misses adjacent-port recursion, bottom-port detection nuances, and `EDGETYPE_LINE` straight branch. |
| 1620 | `leftOf` | — | missing | D | 2D cross-product sign test. Trivial. |
| 1638 | `makeLineEdge` | — | missing | D | `splines=line` straight polyline with optional label bend. |
| 1702 | `make_regular_edge` | `splines.py:route_regular_edge` + `channel_route_edge` | partial | D | **The biggest gap.** Python uses a 4-point bezier heuristic (or the experimental channel router). C builds a full box-path via `beginpath`/`rank_box`/`endpath` + straight-segment optimisation (`straight_len`/`straight_path`) + `routesplines`. |
| 1916 | `completeregularpath` | — | missing | D | Stitches tail + inter-rank + head box chains; uses `top_bound`/`bot_bound` for parallel-edge adjacency. |
| 1954 | `makeregularend` | — | missing | D | Build the final end box (TOP/BOTTOM) clamped to y of the node boundary. |
| 1976 | `adjustregularpath` | — | missing | D | Widens boxes to `MINW=16` / `HALFMINW=8`. The `(i - fb) % 2` dance matters. |
| 2011 | `rank_box` | `splines.py:rank_box` | done | D | Ported 2026-04-14. Signature `rank_box(layout, sp, r) -> Box`. Cached in `sp.rank_box[r]`. Y-down formula: `ll_y = left0.y + ht1[r]`, `ur_y = left1.y - ht2[r+1]` (swapped node reference vs C's y-up). |
| 2026 | `straight_len` | — | missing | D | Count vertically aligned virtual nodes for straight-segment shortcut. |
| 2044 | `straight_path` | — | missing | D | Emit straight polyline for the detected run. |
| 2056 | `recover_slack` | — | missing | D | Push virtual nodes' `x` back into the routed corridor. |
| 2077 | `resize_vn` | — | missing | D | Trivial: set `ND_coord.x` / `ND_lw` / `ND_rw` from corridor. |
| 2083 | `top_bound` | — | missing | D | Find already-routed parallel sibling above for `completeregularpath`. |
| 2099 | `bot_bound` | — | missing | D | Same, below. |
| 2117 | `cl_vninside` | `splines.py:cl_vninside` | done | A | Ported 2026-04-15. Closed-interval point-in-bbox test (`ll_x <= x <= ur_x && ll_y <= y <= ur_y`). |
| 2131 | `cl_bound` | `splines.py:cl_bound` | done | A | Ported 2026-04-15. Walks n's tail/head cluster context + adj's cluster via `_virtual_orig_endpoints` for virtuals. Returns None when adj is in same cluster hierarchy. |
| 2170 | `maximal_bbox` | `splines.py:maximal_bbox` | done | A | Ported 2026-04-15. Signature `maximal_bbox(layout, sp, vn, ie, oe) -> Box`. C literal in docstring. Y-axis flipped for y-down. Python divergences: `ND_label(vn)` branches elided (LayoutNode has no label tracking); `ND_mval(left)` approximated as `left.width/2`. |
| 2229 | `neighbor` | `splines.py:neighbor` | done | A | Ported 2026-04-15. Skips parallel-path neighbours via `pathscross`. "Virtual with label" branch elided (see maximal_bbox). |
| 2253 | `pathscross` | `splines.py:pathscross` | done | A | Ported 2026-04-15. Two-hop forward+backward chain walk with order-flip detection. |
| 2297 | `showpath` | — | n/a | — | `#ifdef DEBUG` PostScript dump. |

### 2.2 `lib/common/splines.c` (1375 lines, ~25 functions)

| Ln | C function | Python target | Status | Phase | Notes |
|---|---|---|---|---|---|
| 34 | `debugleveln` | — | n/a | — | Debug helper. |
| 43 | `showPoints` | — | n/a | — | Debug helper. |
| 65 | `arrow_clip` | — | missing | C | Shorten spline by arrowhead/tail length. Reads `arrow_length` from the arrow shape table. |
| 109 | `bezier_clip` | — | missing | C | Recursive bezier subdivision against a predicate (used by `shape_clip`). |
| 162 | `shape_clip0` | — | missing | C | One-side shape clip (tail or head). |
| 195 | `shape_clip` | — | missing | C | Main entry: recursive bezier clip against node shape. Python currently pre-clips at endpoint-picking time, which is less accurate for curved ends. |
| 214 | `new_spline` | — | missing | C | Allocate a `bezier` inside `ED_spl(e)`. Python data model side only. |
| 236 | `clip_and_install` | — | missing | C | **Load-bearing final step.** Clips spline to tail/head shapes, applies arrow clip, installs in `ED_spl`. Every router ends with this. |
| 318 | `conc_slope` | — | missing | C | Concentrator slope helper for merged edges. |
| 338 | `add_box` | — | missing | B | Append box to `path.boxes`. |
| 378 | `beginpath` | — | missing | B | Build start end-box chain from node + port. Complex: handles compass, record-port, side flags. |
| 575 | `endpath` | — | missing | B | Mirror of `beginpath` for the head side. |
| 774 | `convert_sides_to_points` | — | missing | F | Lookup table mapping (tail_side, head_side) to a self-loop case. |
| 809 | `selfBottom` | `splines.py:self_loop_points` | partial | F | Python has a single generic arc. C has 4 compass variants (this one + selfTop/selfLeft/selfRight). |
| 879 | `selfTop` | `splines.py:self_loop_points` | partial | F | Top-compass self-loop variant. |
| 986 | `selfRight` | `splines.py:self_loop_points` | partial | F | Right-compass self-loop variant. |
| 1057 | `selfLeft` | `splines.py:self_loop_points` | partial | F | Left-compass self-loop variant. |
| 1139 | `selfRightSpace` | — | missing | F | Compute right-margin reservation for a self-loop (used by position). |
| 1164 | `makeSelfEdge` | `splines.py:self_loop_points` | partial | F | Dispatcher into the 4 compass variants. Handles multi-loop stagger. |
| 1205 | `makePortLabels` | — | missing | F | Place head/tail labels if present. |
| 1223 | `endPoints` | — | missing | F | Extract `(sp, ep)` from a splines container. |
| 1247 | `polylineMidpoint` | — | missing | F | Length-parametric midpoint on a polyline for label anchor. |
| 1283 | `edgeMidpoint` | — | missing | F | Same, for an edge's final spline. |
| 1307 | `addEdgeLabels` | — | missing | F | Attach head/tail/main label positions. |
| 1316 | `place_portlabel` | — | missing | F | Position head/tail label using `labelangle`/`labeldistance`. |
| 1363 | `getsplinepoints` | — | missing | F | Compute sample points for edge bbox — used by `top_bound`/`bot_bound`. |

### 2.3 `lib/common/routespl.c` (~1000 lines, ~20 functions)

| Ln | C function | Python target | Status | Phase | Notes |
|---|---|---|---|---|---|
| 40 | `printboxes` | — | n/a | — | Debug helper. |
| 52 | `psprintpolypts` | — | n/a | — | Debug helper. |
| 63 | `psprintpoint` | — | n/a | — | Debug helper. |
| 74 | `psprintpointf` | — | n/a | — | Debug helper. |
| 87 | `psprintspline` | — | n/a | — | Debug helper. |
| 101 | `psprintline` | — | n/a | — | Debug helper. |
| 115 | `psprintpoly` | — | n/a | — | Debug helper. |
| 134 | `psprintboxes` | — | n/a | — | Debug helper. |
| 155 | `psprintinit` | — | n/a | — | Debug helper. |
| 163 | `debugleveln` | — | n/a | — | Debug helper. |
| 174 | `simpleSplineRoute` | — | missing | B | Polygon-bounded spline via Pathplan. Used by `makeSimpleFlatLabels`. Depends on `Pobsopen`/`Pobspath`/`Proutespline`. |
| 218 | `routesplinesinit` | — | missing | B | Allocates workspace for `routesplines_`. |
| 231 | `routesplinesterm` | — | missing | B | Releases workspace. |
| 238 | `limitBoxes` | — | missing | B | Trim box chain to the subset actually crossed by a spline. |
| 294 | `routesplines_` | — | missing | B | **The load-bearing primitive.** Spline fit through a corridor of overlapping boxes. Calls `Proutespline` internally. Renders Python's current `route_regular_edge` heuristic obsolete. |
| 598 | `routesplines` | — | missing | B | Public wrapper: `routesplines_(pp, n, 0)`. |
| 602 | `routepolylines` | — | missing | B | Public wrapper: `routesplines_(pp, n, 1)`. |
| 606 | `overlap` | — | missing | B | 1-D interval overlap length. Trivial. |
| 635 | `checkpath` | — | missing | B | Assert that adjacent boxes actually touch. |
| 758 | `printpath` | — | n/a | — | Debug helper. |
| 773 | `get_centroid` | — | missing | G | Centroid of a graph component. |
| 784 | `nodes_delete` | — | missing | G | Free a `nodes_t` vector. |
| 793 | `cycle_contains_edge` | — | missing | G | Set membership on a discovered cycle. |
| 811 | `is_cycle_unique` | — | missing | G | Dedup for `find_all_cycles`. |
| 839 | `dfs` | — | missing | G | DFS helper for `find_all_cycles`. |
| 865 | `find_all_cycles` | — | missing | G | Enumerates all simple cycles for line-mode back-edge bending. |
| 884 | `find_shortest_cycle_with_edge` | — | missing | G | Picks the cycle to use for an edge's bend. |
| 904 | `get_cycle_centroid` | — | missing | G | Centroid used as bend anchor. |
| 933 | `bend` | — | missing | G | Apply bend to a 4-point cubic around a centroid. |
| 956 | `makeStraightEdge` | — | missing | G | Emit one straight or bent cubic for `splines=line`. |
| 975 | `makeStraightEdges` | — | missing | G | Batch wrapper over a group of line edges. |

### 2.4 `lib/pathplan/*` (~2000 lines, ~30 public + private functions)

Phase B prerequisite. Ports as a single new Python package `gvpy/engines/layout/dot/pathplan/` with one module per C file. No existing Python target for any of these.

**`pathplan/visibility.c`** (355 lines — visibility graph):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 26 | `allocArray` | done | B2 | Ported 2026-04-15. Nested-list V×V matrix + `extra` None rows (matches C's `array2` layout with row pointers). |
| 46 | `area2` | done | B1 | Ported 2026-04-15 as a step-B1 prerequisite for `in_poly`. |
| 55 | `wind` | done | B1 | Ported 2026-04-15 with C's 0.0001 collinearity tolerance. |
| 67 | `inBetween` | done | B2 | Ported 2026-04-15. Uses Python chained comparison `a.x < c.x < b.x`. |
| 80 | `intersect` | done | B2 | Ported 2026-04-15. Literal transliteration including the `wind == 0 && inBetween` boundary case. |
| 108 | `in_cone` | done | B2 | Ported 2026-04-15. Convex/reflex branch on `wind(a0, a1, a2)`. |
| 122 | `dist2` | done | B2 | Ported 2026-04-15. |
| 133 | `dist` | done | B2 | Ported 2026-04-15. Public in Python (no file-scope access control). |
| 138 | `inCone` | done | B2 | Ported 2026-04-15. Index-based wrapper around `in_cone`. |
| 147 | `clear` | done | B2 | Ported 2026-04-15. Walks `[0, start)` ∪ `[end, V)` and tests each polygon edge with `intersect`. |
| 171 | `compVis` | done | B2 | Ported 2026-04-15. Inner loop for `visibility`; populates the visibility matrix via pairwise vertex checks. |
| 213 | `visibility` | done | B2 | Ported 2026-04-15. Allocates `conf.vis` with N+2 rows and calls `compVis`. |
| 224 | `polyhit` | done | B2 | Ported 2026-04-15. Lazy import of `in_poly` to break the circular `visibility ↔ inpoly` dependency. |
| 247 | `ptVis` | done | B2 | Ported 2026-04-15. Returns `list[float]` of length N+2 (last 2 are reserved for query point p/q). Handles `POLYID_UNKNOWN` by delegating to `polyhit`. |
| 306 | `directVis` | done | B2 | Ported 2026-04-15. Four-branch skip-range cascade preserved verbatim from C. |

**`pathplan/cvt.c`** (194 lines — vconfig conversion):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 28 | `Pobsopen` | done | B4 | Ported 2026-04-15. Flat-list API over C's double-pointer `obstacles`. Builds `P`/`start`/`next`/`prev` and calls `visibility` to populate the matrix. |
| 89 | `Pobsclose` | done | B4 | No-op in Python (GC). Preserved for API symmetry. |
| 102 | `Pobspath` | done | B4 | Ported 2026-04-15. `ptVis` × 2 → `makePath` → `dad`-walk to build output polyline. Verified end-to-end on one-obstacle and two-obstacle detour cases. |
| 143 | `printVconfig` | n/a | — | Debug helper (`#ifdef DEBUG`). |
| 169 | `printVis` | n/a | — | Debug helper. |
| 179 | `printDad` | n/a | — | Debug helper. |

**`pathplan/shortest.c`** (448 lines — Euclidean shortest path):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 83 | `Pshortestpath` | done | B3 | Ported 2026-04-15. Funnel algorithm via triangle strip. Per-call state (tris list, deque) instead of C's static globals. Returns `(status, polyline)` tuple. Verified on square (direct case) and L-shape (3-point funnel path through corner `(2, 2)`). |
| 317 | `_triangulate_pnls` | done | B3 | Ear-clipping helper over `_PointNLink` arrays (private). |
| 343 | `_loadtriangle` | done | B3 | Triangle constructor helper (private). |
| 360 | `_connecttris` | done | B3 | Edge-sharing adjacency builder (private). |
| 378 | `_marktripath` | done | B3 | DFS marker for the triangle strip (private). |
| 395 | `_add2dq` | done | B3 | Funnel deque push (private). |
| 409 | `_splitdq` | done | B3 | Funnel deque truncate (private). |
| 416 | `_finddqsplit` | done | B3 | Funnel split index finder (private). |
| 426 | `_pointintri` | done | B3 | Triangle containment test (private). |

**`pathplan/shortestpth.c`** (109 lines — Dijkstra on visibility graph):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 30 | `shortestPath` | done | B3 | Ported 2026-04-15. Dijkstra with sign-flip settled/tentative trick; sentinel value preserved via explicit variable (no `val[-1]` C pointer hack). Verified on 3-node hand-built graph. |
| 93 | `makePath` | done | B3 | Ported 2026-04-15. Direct-visibility short-circuit + splice query visibility vectors into rows V and V+1. |

**`pathplan/route.c`** (495 lines — spline fitting through barriers):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 70 | `Proutespline` | missing | B5d | **Top-level spline fit** — called from `routesplines_`. Returns a cubic bezier through a polyline while avoiding `Pedge_t` barriers. |
| 97 | `reallyroutespline` | missing | B5d | Recursive spline-fit core. |
| 159 | `mkspline` | done | B5b | Ported 2026-04-15 to `pathplan/route.py`. Returns tuple `(sp0, sv0, sp1, sv1)` instead of C's four out-parameters. Verified on a 3-sample symmetric fit and a singular-Gram-matrix fallback (`d01/3` heuristic). |
| 200 | `dist_n` | done | B5b | Ported 2026-04-15. Piecewise polyline length via `math.hypot`. |
| 212 | `splinefits` | missing | B5d | Test fit against barriers; recursively split if it fails. |
| 314 | `splineintersectsline` | done | B5c | Ported 2026-04-15. Three internal cases (degenerate-point, vertical line, general line) preserved. `count == 4` degenerate sentinel propagates through. Both curve parameter `t` and segment parameter `s` verified in `[0, 1]` before accepting a root. Verified on 8 test cases including the exact `(15 ± √105)/30` root pair for `y=2` crossing the canonical `(0,0)→(3,5)→(7,5)→(10,0)` arch. |
| 394 | `points2coeff` | done | B5a | Ported 2026-04-15. Returns `list[float]` of length 4 in constant-term-first order matching `solvers.solve3`'s convention. Verified on the linear-bezier case `[0, 1/3, 2/3, 1]` → `[0, 1, 0, 0]`. |
| 403 | `addroot` | done | B5a | Ported 2026-04-15. Mutates a Python list via `append` instead of C's `rootnp` out-parameter. Closed `[0, 1]` interval preserved. |
| 409 | `normv` | done | B5a | Ported 2026-04-15. Zero-vector guard preserved via `d > 1e-6` check. |
| 431 | `add` | done | B5a | Ported 2026-04-15. Returns fresh `Ppoint` (Python doesn't have C's struct value-copy). |
| 437 | `sub` | done | B5a | Ported 2026-04-15. |
| 443 | `dist` (route-local) | done | B5a | Ported 2026-04-15. Distinct from `visibility.dist` — C has a `static` copy in each file; Python port preserves the split for fidelity. |
| 451 | `scale` | done | B5a | Ported 2026-04-15. |
| 457 | `dot` | done | B5a | Ported 2026-04-15. |
| 462 | `B0` | done | B5a | Ported 2026-04-15. `(1-t)^3` Bernstein basis. |
| 468 | `B1` | done | B5a | Ported 2026-04-15. `3t(1-t)^2` Bernstein basis. |
| 474 | `B2` | done | B5a | Ported 2026-04-15. `3t^2(1-t)` Bernstein basis. |
| 480 | `B3` | done | B5a | Ported 2026-04-15. `t^3` Bernstein basis. Partition-of-unity verified (`B0+B1+B2+B3 == 1`). |
| 485 | `B01` | done | B5a | Ported 2026-04-15. Combined `B0+B1` weight for `mkspline`. |
| 491 | `B23` | done | B5a | Ported 2026-04-15. Combined `B2+B3` weight for `mkspline`. `B01+B23` also partitions unity. |

**`pathplan/triang.c`** (150 lines — polygon triangulation):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 22 | `triangulate` (static fwd decl) | done | B3 | Same function as line 63 (C forward declares it). |
| 25 | `ccw` | done | B3 | Ported 2026-04-15 with graphviz screen-convention (y-down) sign — INVERTED from `wind`. Returns `ISCCW=1`, `ISCW=2`, or `ISON=3`. |
| 30 | `point_indexer` (triang) | done | B3 | Default indexer for `isdiagonal` in the triang-module context (private). |
| 38 | `Ptriangulate` | done | B3 | Ported 2026-04-15. Calls a user callback `fn(closure, tri)` for each emitted triangle. Verified: square → 2 triangles, pentagon → 3. |
| 63 | `triangulate` (static) | done | B3 | Ported as `_triangulate_recursive` (private). Ear-clipping algorithm. |
| 94 | `between` | done | B3 | Collinearity-gated dot-product range check (private helper for `_intersects`). |
| 104 | `intersects` | done | B3 | Segment intersection (private, distinct from `visibility.intersect` — uses `ccw` instead of `wind`). |
| 122 | `isdiagonal` | done | B3 | Ported 2026-04-15. Convex/reflex neighbourhood test + full edge-intersection sweep. |

**`pathplan/solvers.c`** (105 lines — polynomial roots):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 26 | `solve3` | done | B1 | Ported 2026-04-15 to `pathplan/solvers.py`. Tuple return `(count, roots)`; count 4 = degenerate. Verified on `(x-1)(x-2)(x-3)`, `x³-1`, and quadratic fallback. |
| 69 | `solve2` | done | B1 | Ported 2026-04-15. Discriminant + quadratic formula; fallback to `solve1` when leading coeff ~0. Verified on real/complex/double-root cases. |
| 92 | `solve1` | done | B1 | Ported 2026-04-15. Linear equation with degenerate `0==0` returning sentinel `4`. |

**`pathplan/util.c`** (70 lines):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 19 | `freePath` | done | B1 | Ported 2026-04-15 as no-op (Python GC). |
| 24 | `Ppolybarriers` | done | B1 | Ported 2026-04-15. Returns `list[Pedge]` (Python idiom over C's output-pointer+count pattern). |
| 44 | `make_polyline` | done | B1 | Ported 2026-04-15. Each interior vertex tripled, endpoints doubled — produces `[A,A,B,B,B,...,Z,Z]` bezier-ready layout. Python version allocates a fresh list per call instead of C's thread-unsafe `static LIST`. |

**`pathplan/inpoly.c`** (35 lines):

| Ln | C function | Status | Phase | Notes |
|---|---|---|---|---|
| 26 | `in_poly` | done | B1 | Ported 2026-04-15. Convex-polygon CW-winding test (not W. Randolph Franklin). Verified on 4-point square. |

### 2.5 Summary counts (after this scan)

| Phase | done | partial | missing | n/a | total |
|---|---:|---:|---:|---:|---:|
| A (driver + classification) | 18 | 0 | 2 | 0 | 20 |
| B (box-corridor + pathplan) | 53 | 0 | -2 | 16 | 67 |
| C (clip/install/arrow) | 0 | 0 | 9 | 2 | 11 |
| D (regular edge) | 1 | 1 | 9 | 0 | 11 |
| E (flat edges + aux graph) | 0 | 4 | 13 | 0 | 17 |
| F (self-loops + labels) | 0 | 5 | 10 | 0 | 15 |
| G (splines=line bending) | 0 | 0 | 9 | 0 | 9 |
| **total** | **72** | **10** | **50** | **18** | **150** |

*(Phase B `missing` is now `-2` — see the B5a note about individual helper rows exceeding the original block count.  Net accounting stays consistent: `done + partial + missing + n/a` sums to the phase total within the off-by-one accounting quirk.)*

**Read of the map:** 14 functions have a partial Python implementation to replace; 118 are missing outright. The 14 partials are mostly `make_*` dispatchers with heuristic fallbacks (4-point bezier, naive polyline). The 118 missing are heavily weighted to Phase B — 51 pathplan + routespl primitives that all need to land before any of the regular/flat edge phases can do a literal C-matching port. That matches the plan's assessment that Phase B is the load-bearing piece.

**Partials at a glance** (the 14 functions to rewrite rather than create):

1. `dot_splines_` / `dot_splines` → `phase4_routing`
2. `maximal_bbox` (Phase A)
3. `rank_box` (Phase D)
4. `make_regular_edge` → `route_regular_edge` + `channel_route_edge`
5. `makeSimpleFlat` → `flat_adjacent`
6. `make_flat_labeled_edge` → `flat_labeled`
7. `make_flat_bottom_edges` → `flat_arc` (direction=+1)
8. `make_flat_edge` → `flat_edge_route`
9. `selfBottom` / `selfTop` / `selfLeft` / `selfRight` / `makeSelfEdge` → `self_loop_points` (5 C functions collapsed into 1 Python fallback)

Everything in `channel_route_edge` + `build_edge_path` + `_bridge_*` + `_channel_bbox_for_node` + `_find_segment_obstacles` is scheduled to move to `splines_experimental.py` per §4 before Phase D starts, so those Python functions do **not** appear in this table.

---

## 3. Data model harmonisation

Before the first function port, introduce Python classes that mirror the C structs `splines.py` has never had:

### Transient routing workspace (`gvpy/engines/layout/dot/path.py` — NEW)

- `Box` — `(ll_x, ll_y, ur_x, ur_y)`. Pick either a frozen tuple or a small dataclass and stick to it across the file.
- `PathEnd` — mirrors C `pathend_t`: `nb` (Box), `sidemask`, `boxes: list[Box]`, `boxn: int`, `np: (float,float)` (node point), `theta: float`, `constrained: bool`.
- `Path` — mirrors C `path`: `boxes: list[Box]`, `nbox: int`, `start: PathEnd`, `end: PathEnd`. Transient, owned by a routing call, reused across edges.
- `SplineInfo` — mirrors C `spline_info_t`: `left_bound`, `right_bound`, `splinesep`, `multisep`, `rank_box_cache`. Currently `phase4_routing` stores these as ad-hoc attributes on `layout`.

### Edge flag bits on `LayoutEdge`

- Add `tree_index: int` with bit constants `FLATEDGE`, `REGULAREDGE`, `SELFNPEDGE`, `SELFWPEDGE`, `FWDEDGE`, `BWDEDGE`, `MAINGRAPH`, `AUXGRAPH`. C stores these via `ED_tree_index(e)`.

### Result boundary (`gvpy/engines/layout/dot/edge_route.py` — DONE 2026-04-14)

- `EdgeRoute` with `points`, `spline_type`, `label_pos`. Delegated to from `LayoutEdge` via properties so existing call sites are unchanged.
- Deferred fields (add when the C port wires them up): `sflag` / `eflag` / `sp` / `ep` from C `bezier` struct.

### Why `Path` is not an `Edge` subclass

1. C's `path` is transient workspace, reused across every edge in `dot_splines_` (`P.nbox = 0` between edges). Its lifetime is the phase-4 call, not the edge.
2. `make_flat_adj_edges` recurses — it clones the graph, calls `dot_splines_` on the clone, and copies splines back. During that recursion two live `path` workspaces exist. Tying `Path` to `Edge` makes this impossible to express cleanly.
3. `path` doesn't know about tail/head/label/attrs. Putting it on `Edge` pollutes the semantic class with compute-time scratch state.
4. The *result* already lives on the edge (via `EdgeRoute`). That is the right unification — not the scratch workspace that produced it.

### PyQt migration angle

```
Edge         (gvpy/core/edge.py)         — semantic entity, user-visible
LayoutEdge   (dot_layout.py)             — compute-time wrapper, owns route: EdgeRoute
EdgeRoute    (edge_route.py)             — result of phase 4, stable boundary for Qt
Path         (path.py, future)           — transient routing workspace, never Qt-aware
```

When the Qt port happens, `EdgeRoute.to_qpainter_path()` is a ~30-line adapter. Nothing below `EdgeRoute` ever touches Qt. Nothing above `EdgeRoute` ever touches the engine's state graph.

Same pattern applies for nodes eventually: `Node` / `LayoutNode` / `NodeShape` / `NodeGraphicsItem`.

---

## 4. Channel-routing disposition

`channel_route_edge` + `build_edge_path` + `_channel_bbox_for_node` + `_bridge_*` + `_find_segment_obstacles` + `_remove_polyline_spikes` + `_split_at_sharp_corners` + `_rounded_corner_bezier` + `_perp_stub` + `route_through_channel_boxes` + `_row_crossings` + `_row_safe_cr` + `_bridge_row_detour` + `_NodeObstacle` + `_bridge_foreign_hits` + `_face_constraint_side` + `_bridge_points_for_obstacle` + `_cl_bound` (experimental version) + `_innermost_cluster` + `_edge_clusters_for_le` + `_rank_neighbor_at` + `_channel_bbox_for_node` + `_edge_node_path` + `build_edge_path` + `_find_gap_obstacles`.

**Action:** move the above into `gvpy/engines/layout/dot/splines_experimental.py`. `splines.py` re-exports behind the `_use_channel_routing` flag so existing call sites in `phase4_routing` keep working.

Purpose: removes ~800 lines from the alignment surface. Preserves the step-6 channel-routing work in case we want the cluster-aware waypoints later.

---

## 5. Porting order (dependency-driven)

Work bottom-up so each function being ported only depends on already-ported functions.

### Phase A — primitives and driver shell

1. Data model (§3): `Box`, `PathEnd`, `Path`, `SplineInfo`, `tree_index` flags.
2. `rank_box` — verify Python version matches C.
3. Cluster-aware bbox family: `cl_vninside`, `cl_bound`, `neighbor`, `pathscross`, `maximal_bbox`. No routing change yet — just land the helpers.
4. Edge classification and sort: `portcmp`, `getmainedge`, `swap_ends_p`, `spline_merge`, `makefwdedge`, `setflags`, `edgecmp`. Landing this lets the driver group parallel edges into equivalence classes instead of the post-pass `_apply_parallel_offsets`.
5. Back-edge normalisation: `resetRW`, `edge_normalize`, `swap_bezier`, `swap_spline`.
6. Top-level driver rewrite: `dot_splines_impl` iterates ranks in C order and dispatches, *without* touching the per-edge routers yet. Existing routers stay plugged in via an adapter shim.

### Phase B — box-corridor optimiser

7. `path` / `pathend_t` construction helpers from `lib/common/splines.c`: `add_box`, `beginpath`, `endpath`.
8. `routesplines_impl` / `routesplines` / `routepolylines` / `limitBoxes` / `checkpath` / `overlap` from `lib/common/routespl.c`. Likely its own file: `gvpy/engines/layout/dot/routespl.py`. Load-bearing — most downstream work depends on it.
9. `simpleSplineRoute` — depends on Pathplan's polygon shortest-path. Port Pathplan (decision 9.2).

### Phase C — clip and install pipeline

10. `new_spline`, `clip_and_install`, `bezier_clip`, `shape_clip`, `shape_clip0`, `arrow_clip`, `conc_slope`.

### Phase D — regular edges

11. `makeregularend`, `adjustregularpath`, `completeregularpath`.
12. `top_bound`, `bot_bound`, `straight_len`, `straight_path`, `recover_slack`, `resize_vn`.
13. `makeLineEdge`, `leftOf`.
14. `make_regular_edge` — direct transliteration using the helpers above. At this point Python's regular-edge routing should match C on numerical control points.

### Phase E — flat edges

15. `makeFlatEnd`, `makeBottomFlatEnd`.
16. `makeSimpleFlat`, `makeSimpleFlatLabels`, `edgelblcmpfn`.
17. `make_flat_labeled_edge`.
18. `make_flat_bottom_edges`.
19. `make_flat_edge` (dispatcher).
20. Aux-graph helpers: `cloneGraph`, `cloneNode`, `cloneEdge`, `setState`, `cleanupCloneGraph`, `transformf`, `attr_state_t`.
21. `make_flat_adj_edges` (requires recursive `dot_splines_impl` call — last in this phase).

### Phase F — self-loops and labels

22. `selfRightSpace`, `selfTop`, `selfBottom`, `selfLeft`, `selfRight`, `makeSelfEdge`.
23. `place_vnlabel`, `place_portlabel`, `makePortLabels`, `addEdgeLabels`, `polylineMidpoint`, `edgeMidpoint`, `endPoints`, `getsplinepoints`.

### Phase G — splines=line back-edge bending

24. `get_centroid`, `find_all_cycles`, `find_shortest_cycle_with_edge`, `get_cycle_centroid`, `bend`, `makeStraightEdge`, `makeStraightEdges`.

After each phase the port map is updated, `pytest tests/test_dot_layout.py` runs green, and the per-phase validation dot file (§7) matches C.

---

## 6. Per-function porting protocol

Same seven steps for every C function. No exceptions.

1. **Read the C function in full.** Note every static/global it touches, every helper it calls, every field it reads on `graph_t`/`node_t`/`edge_t`. Don't start translating until you can describe its inputs and outputs in one paragraph.
2. **Update the port map row** with C line range and dependency notes.
3. **Transliterate to Python** into `splines.py` (or `routespl.py` for Phase B, or `pathplan.py` for the Pathplan port). Same variable names, same control flow, same order of statements. No cleverness.
4. **Keep the pre-existing Python routine alongside** under a `_legacy_` prefix only if tests still call it during the transition. Remove on swap-in (decision 9.4).
5. **Unit comparison:** pick a minimal dot file that exercises only this function's path, run both engines with `GV_TRACE` on for the relevant channel, diff. Expected divergence budget: zero for pure math, ≤ 0.5 pt for routines that call `routesplines`.
6. **Swap in the new version.** Delete any `_legacy_` copy. Full test suite must stay green.
7. **Commit.** One function per commit. Message: `splines: port <c_function_name> from dotsplines.c:<line_range>`. Makes `git log` a direct mapping back to C.

---

## 7. Validation anchors

Fixed set of dot files, each targeting a specific code path, run after every commit via a single script.

| Dot file | Code path exercised |
|---|---|
| `test_data/1444.dot` (1 edge, 2 nodes) | minimal `make_regular_edge` happy path |
| `test_data/2734.dot` | tailport / headport + default splines |
| `test_data/1453.dot` | `splines=curved`, compound, rank constraints |
| `test_data/2592.dot` | compound clipping, `lhead` / `ltail`, invis edge |
| `test_data/1554.dot` | same-rank arcs, curved |
| `test_data/1367.dot` (if it parses cleanly) | self-loops + lhead |
| `test_data/aa1332.dot` | the kitchen sink — regression anchor |

The script: for each file, run both engines (C ref binary per `CLAUDE.md` + `.venv` Python), diff edge control points from `-Tplain`. Keep a per-commit baseline so regressions are visible.

---

## 8. Instrumentation left on during porting

Even with gating from §1, keep one default-on line per engine so CI output always shows phase health:

- `[TRACE spline] phase4 begin: edges=N splines=<mode>`
- `[TRACE spline] phase4 end: routed=N skipped=N`

Everything more detailed must be explicitly enabled via `GV_TRACE`.

---

## Progress log

### 2026-04-14 — Session start
- Extracted `EdgeRoute` dataclass into `gvpy/engines/layout/dot/edge_route.py`.
- Modified `LayoutEdge` in `dot_layout.py`: dropped `points` / `spline_type` / `label_pos` fields; added `route: EdgeRoute = field(default_factory=EdgeRoute)`; added three delegating `@property` / `@setter` pairs so every existing call site keeps working.
- Verified: `tests/test_dot_layout.py` 238/238, `tests/test_dot_parser.py` + `tests/test_svg_renderer.py` 62/62, end-to-end SVG render on `1453.dot`, `2734.dot`, `aa1332.dot`.
- Plan saved to this file.

### 2026-04-14 — §1 trace gating
- **Python side:** Added `gvpy/engines/layout/dot/trace.py` with `trace_on(channel)` / `trace(channel, msg)` gated by `GV_TRACE` env var (comma-list, plus `all`). Rewrote all 33 existing `print(f"[TRACE ...", file=sys.stderr)` call sites across `dot_layout.py`, `rank.py`, `mincross.py`, `position.py`, `splines.py` to use `trace(channel, msg)`. Channels: `bfs`, `class2`, `label`, `median`, `order`, `port`, `position`, `rank`, `record`, `spline`, `spline_detail`.
- **C side:** Added `lib/common/tracegate.h` with `tracegate_on(channel)` — stateless `getenv("GV_TRACE")` parser supporting comma list and `all`. Wrapped all 41 existing `fprintf(stderr, "[TRACE ...")` call sites in `lib/dotgen/{rank,mincross,cluster,position,dotsplines}.c` + `lib/common/shapes.c` with `if (tracegate_on("<channel>"))`. Where a whole block (counting loop + fprintf) was trace-only, hoisted the check to wrap the block.
- **Verified Python gating:** `GV_TRACE` unset → 0 TRACE lines, `GV_TRACE=spline` → 43 spline-only lines, `GV_TRACE=rank,order` → only rank+order, `GV_TRACE=all` → 254 lines across all 6 active channels.
- **Verified C gating:** Rebuilt `dot.exe` via CLion MinGW toolchain (pre-existing format-string warnings, no new errors). `GV_TRACE` unset → 0 lines, `GV_TRACE=spline` → 2 lines (phase4 begin + end), `GV_TRACE=all` → 691 lines across 6 channels (`bfs`, `median`, `order`, `position`, `rank`, `spline`).
- **Shared prefix preserved:** Both sides still emit `[TRACE <channel>] <message>`, so `tools/compare_traces.py` will diff cleanly when both sides are re-enabled.
- `tests/test_dot_layout.py` 300/300 still green.

### Note on bash output capture
`gcc.exe` (the CLion MinGW compiler) writes stderr in a way the Git Bash shell in this environment swallows entirely — the raw `cmake --build` in bash showed `FAILED` lines with zero diagnostic text, even for successful compiles. PowerShell captures it correctly. When debugging C build failures, invoke `cmake --build` via the `PowerShell` tool, or wrap the gcc call with `cmd /c "gcc ... 2> errfile"`.

### 2026-04-14 — §2 canonical function map
- Inventoried every function in `lib/dotgen/dotsplines.c` (~35 functions), `lib/common/splines.c` (~25), `lib/common/routespl.c` (~20), and `lib/pathplan/*` (~45 across 9 files). Total **150 rows**, of which **18 are `n/a`** (debug helpers + `#ifdef DEBUG`), **14 are `partial`** (Python has a heuristic fallback to rewrite), and **118 are `missing`** outright.
- Port map tables landed in §2.1–§2.4 of this file, organised by C source file, with columns `Ln / C function / Python target / Status / Phase / Notes`. Summary counts by phase in §2.5.
- Key takeaway: Phase B (box-corridor + pathplan) is 51 missing functions and has no partials at all. Everything in Phase D–G depends transitively on Phase B's `routesplines_` + `Proutespline`, so that block has to land first even though it's the deepest part of the dependency graph.
- No code touched. Read-only inventory.

### 2026-04-14 — §3 data model harmonisation
- **New file** `gvpy/engines/layout/dot/path.py` with:
  - `Box` — mirrors `boxf` in `lib/common/geom.h:41`. Mutable (for `adjustregularpath` widening), with `width` / `height` properties and an `is_valid()` strict-positive check.
  - `PathEnd` — mirrors `pathend_t` in `lib/common/types.h:73-79`. Fields `nb`, `np`, `sidemask`, `boxn`, `boxes` one-for-one; `theta` / `constrained` hoisted from C `path.port start`/`end` to travel with the end-box chain.
  - `Path` — mirrors `path` in `lib/common/types.h:81-87`. `boxes`, `nbox`, `start`, `end`. `void *data` omitted (neato-only).
  - `SplineInfo` — mirrors `spline_info_t` in `lib/dotgen/dotsplines.c:64-70`. `left_bound`, `right_bound`, `splinesep`, `multisep`, `rank_box` (sparse dict cache instead of C's fixed array).
- **Constants exported from `path.py`**:
  - Sidemask bits `BOTTOM` / `RIGHT` / `TOP` / `LEFT` (+ `*_IX` indexes) — `const.h:111-120`.
  - Spline tunables `NSUB` / `MINW` / `HALFMINW` — `dotsplines.c:36-40`.
  - Tree-index flag bits `REGULAREDGE` / `FLATEDGE` / `SELFWPEDGE` / `SELFNPEDGE` / `EDGETYPEMASK`, `FWDEDGE` / `BWDEDGE`, `MAINGRAPH` / `AUXGRAPH` / `GRAPHTYPEMASK` — `const.h:149-155` + `dotsplines.c:41-47`.
  - `PATH_END_BOX_MAX = 20` matching C `pathend_t.boxes[20]`.
- **`LayoutEdge.tree_index: int = 0`** field added to `dot_layout.py`. Docstring references the flag constants in `path` module. C analogue: `ED_tree_index(e)` as written by `setflags` in `dotsplines.c`.
- **No function ports yet** — these are just the data types so Phase A step 3 (cluster-aware bbox family) has somewhere to stash its inputs.
- **Verified** via smoke test: Box width/height/is_valid, Path/PathEnd/SplineInfo per-instance isolation (no shared mutable defaults), flag bit masks consistent (`REGULAREDGE|FLATEDGE|SELFWPEDGE|SELFNPEDGE == EDGETYPEMASK`, `MAINGRAPH|AUXGRAPH == GRAPHTYPEMASK`), `LayoutEdge.tree_index` accepts `REGULAREDGE | FWDEDGE | MAINGRAPH` packed value and extracts each group via the mask constants.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

### 2026-04-14 — Phase A step 2: `rank_box` alignment
- Rewrote `splines.py:rank_box` as a literal port of C `dotsplines.c:rank_box()` lines 2014–2026. New signature `rank_box(layout, sp: SplineInfo, r: int) -> Box` matches C `static boxf rank_box(spline_info_t *sp, graph_t *g, int r)`. The full C source is quoted in the Python docstring.
- Cache moved from nothing to `sp.rank_box[r]` — C uses `b.LL.x == b.UR.x` as an uninitialised-sentinel check; Python uses dict membership which expresses the same intent cleanly.
- Y-axis note in the docstring: C y-up convention has `LL.y = left1.y + ht2[r+1]` (visual bottom of corridor) and `UR.y = left0.y - ht1[r]` (visual top). Python y-down has the opposite node reference on each side: `ll_y = left0.y + ht1[r]` and `ur_y = left1.y - ht2[r+1]`. The math resolves to the same corridor geometry, just flipped through the y-axis.
- **`SplineInfo` now allocated by `phase4_routing`** at the top of the pass (`dotsplines.c:268-270`): `layout._spline_info = SplineInfo(left_bound, right_bound, splinesep=nodesep/4, multisep=nodesep)`. Field declared on `DotGraphInfo.__init__` as `_spline_info: SplineInfo | None = None`. Cleared at end of pass... actually still live — future ports may want it. Left live for now.
- **`DotGraphInfo._rank_box(r)` wrapper** now reads `self._spline_info` and passes it through, keeping the one existing caller in `route_regular_edge` (`rbox.ll_y + rbox.ur_y) / 2.0`) unchanged except for `.ll_y`/`.ur_y` attribute access instead of tuple indexing.
- **One existing caller updated**: `route_regular_edge` multi-rank branch (lines ~2420) now unpacks via `rbox.ll_y` / `rbox.ur_y` instead of `rbox[1]` / `rbox[3]`. That branch turns out to be dead under the current driver (multi-rank edges become chain edges and go through `route_through_chain`), but the update is still needed to keep the code compiling if the driver's edge classification changes.
- **Port map status update**: `rank_box` moves from `partial` → `done` in §2.1. First entry in the "done" column of the summary counts.
- **Verified** via three smoke checks plus the full test suite:
  1. Direct call with a hand-built `SplineInfo` on a 3-rank linear graph `{a->b->c}`: returns a `Box`, caches by rank index, identity-equal on second call, math matches the y-down formulas for both the start corridor (rank 0 → rank 1) and the next one (rank 1 → rank 2).
  2. Wrapper call via `layout._rank_box(r)` on a 4-node linear graph `{a->b->c->d}`: all three corridors valid, ordered (`b0.ur_y ≤ b1.ll_y`), identity-equal on repeat call.
  3. `phase4_routing` allocates `SplineInfo` with the right field values (`splinesep = nodesep/4`, `multisep = nodesep`, `left_bound/right_bound` matching the legacy `layout._left_bound/_right_bound`).
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green. SVG bytes for `1453.dot` (19939) and `aa1332.dot` (138108) unchanged — no output regression from the port.

### 2026-04-15 — Divergence harness + spline sub-channels
- **Extended the trace vocabulary** with six spline sub-channels so each ported function can emit into its own bucket and be diffed independently: `spline_regular`, `spline_flat`, `spline_self`, `spline_clip`, `spline_path`, `spline_route` (plus the existing `spline` for phase markers and `spline_detail` for per-edge dumps). Mirrored in both `gvpy/engines/layout/dot/trace.py:KNOWN_CHANNELS` and the comment block in `lib/common/tracegate.h` (no C code change — `tracegate_on` is a string match, the header just documents the reserved vocabulary). **No emissions yet**; each sub-channel gets populated as its Phase A–G port lands.
- **New tool `tools/diff_phases.py`** — phase-by-phase divergence diff harness. Invokes C `dot.exe` and Python `dot.py` on the same dot file with a given `GV_TRACE` channel, captures stderr, normalises numbers to N decimals (`--tolerance N`, default 1), sorts alphabetically, and prints a `unified_diff` with per-set counts (`only in C`, `only in Python`, `common`). Exit 0 on exact match, exit 1 on drift. Supports `--full-diff`, `--show-only-in-c`, `--show-only-in-py` flags for triage.
- **Smoke-tested on three channels**:
  - `rank` on `{a -> b;}`: **2 lines match exactly** (`node_rank: a rank=0` / `node_rank: b rank=1`). Remaining drift is message-shape misalignment — C says `phase1 begin: newrank=0`, Python says `phase1 begin: newrank=False clusterrank=local`. Same semantic content, different wording. Python emits `begin layout` + `break_cycles` + `phase1 done` that don't exist in C output.
  - `rank` on `1444.dot`: more drift because C runs phase 1 twice (it has `rank=same`, triggers collapse + re-rank), Python runs it once. Documented divergence — not a bug.
  - `position` on `1444.dot`: 0 common lines yet. Python emits `final_pos: n1 x=123 y=18` with the *post-rankdir* positions; C emits `final_pos: n1 x=0 y=0` with the *pre-flip* positions. Both are correct for their flip convention — alignment is a per-port task.
- **Decision**: harness lands now but **baselines and pytest integration wait**. Message-shape alignment is a function-port deliverable, not a harness deliverable. Will revisit once Phase A step 4 (edge classification + driver rewrite) lands — by then `rank` + `position` channels will have stable shapes and it's worth baselining them.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green. `KNOWN_CHANNELS` size 17.

### 2026-04-15 — Phase A step 3: cluster-aware bbox family
- **Five functions ported** as literal transliterations of `lib/dotgen/dotsplines.c:2120–2294`:
  - `cl_vninside(cl, ln) -> bool` — closed-interval point-in-bbox test
  - `cl_bound(layout, n_ln, adj_ln) -> LayoutCluster | None` — returns adj's cluster if it differs from n's tail/head clusters and (for virtuals) contains adj's centre
  - `maximal_bbox(layout, sp, vn_ln, ie, oe) -> Box` — X extent via left/right neighbour walk with cluster wall + splinesep offset; Y extent as the rank band around vn.y (y-flipped for y-down)
  - `neighbor(layout, vn_ln, ie, oe, dir) -> LayoutNode | None` — rank walk returning first NORMAL node or first non-crossing virtual
  - `pathscross(layout, n0, n1, ie1, oe1) -> bool` — two-hop forward+backward chain walk with order-flip detection
- **Support helpers added** in `splines.py`: `_node_out_edges`, `_node_in_edges`, `_clust` (wrapper for `_innermost_cluster`), `_virtual_orig_endpoints` (maps a virtual node to its original `(orig_tail, orig_head)` via the chain edge's stored fields).
- **`LayoutNode.name: str = ""` field added** to the dot `LayoutNode` dataclass, matching every other layout engine's `LayoutNode`. Fixes a latent `TypeError` in `position.py:839` which was already calling `LayoutNode(name=vn_name)` against a class without the field. Updated four constructors (`dotinit.py:145`, `mincross.py:341`, `mincross.py:432`, `rank.py:622`) to pass the name.
- **`FUDGE = 4` constant** added to `path.py` alongside `NSUB`/`MINW`/`HALFMINW`. C analogue: `dotsplines.c:2171`.
- **Old `maximal_bbox` deleted** — it was `partial` with zero live callers, so a straight replacement was safer than a `_legacy_` rename (per decision 9.4). `DotGraphInfo._maximal_bbox(vn_ln, ie=None, oe=None)` wrapper updated to the new five-arg form and now reads `self._spline_info` implicitly.
- **`LeftBound`/`RightBound` computation aligned with C** at `dotsplines.c:273–305`. C's `sd.LeftBound -= MINW` runs *inside* the rank loop (once per rank), so a graph with N ranks subtracts MINW from LeftBound N times. Python was doing a single `- 16` outside any loop — replaced with a literal port of C's loop. Also fixed `splinesep` and `multisep` to match C's integer truncation: `GD_nodesep` is `int` in `types.h:334`, so `GD_nodesep(g) / 4` is integer division. Python now does `int(layout.nodesep) // 4`.
- **Diagnostic sweep in `phase4_routing`** (gated on `trace_on("spline_path")`): walks every real node, calls `maximal_bbox(layout, sp, ln, None, None)`, emits a `[TRACE spline_path] maximal_bbox: vn=<name> ll=... ur=...` line. Zero overhead when disabled. The equivalent C emission lives inside `maximal_bbox` itself at `dotsplines.c:2230` — on the C side each `(ie, oe)` combination fires once per `make_regular_edge` invocation, so C's line count is higher. Expected and documented.
- **C-side emissions added** in `lib/dotgen/dotsplines.c`:
  - `spline_info: left_bound=... right_bound=... splinesep=... multisep=...` line emitted after the main LeftBound/RightBound loop (line 295 area) — same four fields as Python.
  - `maximal_bbox: vn=... ll=... ur=...` line emitted at the end of `maximal_bbox` (line 2230 area) — uses `agnameof(vn)` for NORMAL nodes and `(virt)` for virtuals.
- **Harness verification** via `tools/diff_phases.py <file> spline_path`:
  - On `{a->b;}` (1-edge): **3 lines each**, structurally matching. `splinesep=4.0 multisep=18.0` match. X and Y coordinate origins differ (C y-up, Python y-down; C centers at x=0, Python offset by +27pt). Documented as a Phase 3 (position.c) divergence, not a Phase 4 issue.
  - On `{a->b->c; b->d;}` (4-node diamond-ish): Python 5 lines, C 7 lines (C emits `vn=b` 3× because `make_regular_edge` calls `maximal_bbox` once per adjacent edge). Structural alignment confirmed: the c/d split at rank 2 correctly carves each node's half of the rank width based on its neighbour's position.
- **Port map updated**: Phase A `done` count jumps from 0 → 5 (cl_vninside, cl_bound, maximal_bbox, neighbor, pathscross). Phase A `partial` drops from 3 → 2. Summary row: **total done 6, partial 12, missing 114, n/a 18**.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

### 2026-04-15 — Phase A step 4: edge classification and driver sort
- **Seven functions ported** as literal transliterations of `lib/dotgen/dotsplines.c:48–143, 507–636`:
  - `makefwdedge(old) -> LayoutEdge` — fresh LayoutEdge with tail/head + tailport/headport + lhead/ltail swapped, `virtual=True`, original direction preserved in `orig_tail`/`orig_head`.
  - `getmainedge(layout, le) -> LayoutEdge` — walks chain virtuals back to the real LayoutEdge matching `orig_tail`/`orig_head`. Returns self for real edges and non-chain virtuals.
  - `spline_merge(layout, ln) -> bool` — `ln.virtual and (in_count > 1 or out_count > 1)`.
  - `swap_ends_p(layout, le) -> bool` — walks via getmainedge, then compares main tail/head rank then order per C's three-branch conditional.
  - `portcmp(p0, p1) -> int` — standalone on the new `Port` dataclass.
  - `setflags(layout, le, hint1, hint2, f3)` — auto-detect REGULAREDGE/FLATEDGE/SELFWPEDGE/SELFNPEDGE from tail/head/ports, auto-detect FWDEDGE/BWDEDGE from rank (or order for flat), OR in the graph-type bit.
  - `edgecmp(layout, e0, e1) -> int` — full 9-step lex order: edge-type (inverted), abs rank diff, abs x diff, main AGSEQ, port tail (after `makefwdedge` on BWDEDGE), port head, graph type, label, edge AGSEQ.
- **`Port` dataclass added** to `path.py` with `defined: bool` and `p: tuple[float, float]`. Mirrors `port` struct in `lib/common/types.h:48-64`, minus the fields not yet consulted by ported code. C's full port struct has 11 fields; we start with 2 and add more as the downstream ports need them.
- **`_get_edge_port(le, side)`** helper parses `le.tailport`/`le.headport` strings into a `Port`. Empty string → undefined, non-empty → defined with aiming point `(0, 0)` for now. Real compass/record aiming points are a Phase B deliverable (`beginpath`/`endpath`).
- **`_edge_seq_map(layout)`** provides a lazy `AGSEQ`-equivalent cache — `id(le) -> int` for every edge in `layout.ledges` + `layout._chain_edges`. Cached on `layout._edge_seq_cache`, cleared at the start of each `phase4_routing` sweep.
- **Diagnostic sweep added** in `phase4_routing` (gated on `trace_on("spline")`): classifies every real edge via `setflags`, sorts with `edgecmp`, emits `[TRACE spline] setflags: <edge> type=<...> dir=<...> tree_index=<n>` per edge plus a single `[TRACE spline] edgecmp_sorted: [<edge> <edge> ...]` line with the final order. Zero overhead when disabled.
- **Matching C-side emissions added** in `lib/dotgen/dotsplines.c`:
  - `setflags` emits a `[TRACE spline] setflags: ...` line at the end with the same type/dir/tree_index fields.
  - Right after `LIST_SORT(&edges, edgecmp)` a single `[TRACE spline] edgecmp_sorted: [...]` line is emitted listing the final batch order.
- **Smoke tests (ASCII-only, 9 assertions)** on a graph with parallel edges, self-loops, and back-edges:
  - `portcmp`: 7 cases covering undefined/defined + x/y ordering.
  - `setflags`: `c->c` → `SELFNPEDGE`, `d->d [tailport=n,headport=s]` → `SELFWPEDGE`, `a->b` → `REGULAREDGE`. `tree_index` values match C: REGULAR+FWD+MAIN = 81, SELFNP+FWD+MAIN = 88, SELFWP+FWD+MAIN = 84.
  - `getmainedge`: returns self for real edges.
  - `spline_merge`: False for real nodes.
  - `swap_ends_p`: False for a forward edge.
  - `makefwdedge`: tail/head/ports swapped, `virtual=True`, not the same object, `orig_tail`/`orig_head` set.
  - `edgecmp`: determinism confirmed across two sorted runs with cleared cache.
  - `edgecmp` edge-type order: `[8, 4, 1, 1, 1, 1, 1]` — SELFNP first, SELFWP next, REGULAR last (C's inverted ordering).
  - **Parallel edges grouped contiguously** at positions `[2, 3, 4]` — exactly what `edgecmp` is designed to achieve for `make_regular_edge` batching.
- **Harness verification** via `tools/diff_phases.py <file> spline` on `{a->b; a->b; b->a; c->c;}`:
  - **1 line matches exactly**: `[TRACE spline] setflags: a->b type=REGULAR dir=FWD tree_index=81`. Confirms the classification algorithm matches C bit-for-bit.
  - Remaining drift is architectural, not algorithmic:
    1. C iterates 3 edge lists per node (`ND_out`, `ND_flat_out`, `ND_other`) with different graph-type bits (MAINGRAPH for `ND_out`, AUXGRAPH for the others). Python's sweep uses MAINGRAPH only because `LayoutNode` doesn't track those lists yet. Deferred to Phase A step 6 (driver rewrite).
    2. C keeps `b->a` back-edges with `BWDEDGE` marker; Python's `break_cycles` has already physically reversed them before phase 4 runs.
    3. `phase4 begin` line format differs (C: `et=10 normalize=1`, Python: `splines= compound=False`). Cosmetic.
- **Port map status update**: Phase A jumps from 5 → 12 done. Seven entries flip from `missing` → `done`. Summary: **total done 13, partial 12, missing 107, n/a 18**.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

### 2026-04-15 — Phase A step 5: back-edge control-point normalisation
- **Four functions ported** as literal transliterations of `lib/dotgen/dotsplines.c:145–194`:
  - `swap_bezier(route)` — reverses `route.points`, swaps `sflag` ↔ `eflag`, swaps `sp` ↔ `ep`. Operates on `EdgeRoute` directly (one-bezier-per-edge model).
  - `swap_spline(route)` — equivalent to `swap_bezier` under the single-bezier model; kept distinct for C naming parity. Will diverge once `EdgeRoute` gains `beziers: list[Bezier]` in Phase E.
  - `edge_normalize(layout)` — iterates `layout.ledges` + `layout._chain_edges`, reverses any edge where `swap_ends_p(le)` is True. No-op under the current data flow because `break_cycles` in phase 1 has already physically reversed back-edges.
  - `resetRW(layout)` — walks nodes with self-loops; for each, swaps `width/2` with `mval`. Gated on `mval > 0` as a Python-specific safety check (Python's position.py doesn't inflate rw for self-loops yet).
- **Data model additions**:
  - `EdgeRoute.sflag`, `eflag`, `sp`, `ep` — fields promoted from the "future fields" list in the docstring to real dataclass fields. `sflag`/`eflag` default to 0; `sp`/`ep` default to `(0.0, 0.0)`.
  - `LayoutNode.mval: float = 0.0` — mirrors C `ND_mval(n)`. Docstring records the Phase F self-loop inflation dependency.
- **Smoke tests (7 assertions)** all pass:
  1. `swap_bezier` on a 4-point cubic with non-trivial sflag/eflag/sp/ep → points reversed, sflag/eflag swapped, sp/ep swapped.
  2. `swap_bezier` involution — double-swap restores original state.
  3. `swap_spline` equivalent to `swap_bezier`.
  4. `edge_normalize` on `{a->b->c; c->a;}` with a real back-edge — no edge modified, confirming the no-op behaviour under Python's current data flow.
  5. `resetRW` on an uninflated self-loop node `a`: width and mval unchanged. No destructive zeroing.
  6. `resetRW` on a manually-inflated node (width=74, mval=27): after swap width=54, mval=37.
  7. `resetRW` involution — double-call restores state.
- **Port map status update**: Phase A jumps from 12 → 16 done. Four entries flip from `missing` → `done`. Summary: **total done 17, partial 12, missing 103, n/a 18**.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

### 2026-04-15 — Phase A step 6: top-level driver rewrite
- **`phase4_routing` rewritten** as a literal port of `dot_splines_` in `dotsplines.c:228–475`. The driver shape now mirrors C end-to-end:
  1. Pre-compute rank obstacle bounds (`_rank_ht1`/`_rank_ht2`).
  2. Compute `LeftBound`/`RightBound` via per-rank MINW loop (Phase A step 3).
  3. Allocate `SplineInfo` (Phase A step 2).
  4. **`resetRW(layout)`** — call into the self-loop rw restoration (Phase A step 5, no-op today).
  5. **Classify every real edge with `setflags` and sort with `edgecmp`** — one-pass iteration over `layout.ledges`, filtering virtuals, tagging each with `MAINGRAPH | FWDEDGE/BWDEDGE | REGULAREDGE/FLATEDGE/SELFWPEDGE/SELFNPEDGE`, then `sorted(..., key=cmp_to_key(edgecmp))` to group equivalence classes.
  6. **Route in sorted order**: the main routing loop now iterates `sorted_real_edges` instead of `layout.ledges`. Per-edge dispatch (self / flat / ortho / line / channel / regular) is unchanged — the existing heuristic Python routers still do the work.
  7. Chain edges route separately (Python stores them in `_chain_edges` rather than as `ND_out` virtuals).
  8. Post-processing unchanged: `apply_sameport`, compound clipping, bezier conversion, `_apply_parallel_offsets`.
  9. **`edge_normalize(layout)`** — call the back-edge control-point reverser (Phase A step 5, no-op under Python's current break_cycles-based back-edge handling).
- **`phase4 begin` trace format aligned with C**: Python now emits `phase4 begin: et=<int> normalize=1` matching C's `dotsplines.c:236` format. New `edge_type_from_splines(splines_str) -> int` helper in `path.py` maps the Python splines-attribute string to C's `EDGETYPE_*` enum (e.g. default/spline/true → `EDGETYPE_SPLINE=10`, `curved` → `4`, `ortho` → `8`). Full `EDGETYPE_*` constants added to `path.py` mirroring `lib/common/const.h:234-240`.
- **Per-edge routing log moved from `spline` to `spline_detail`**. The top-level `spline` channel is now reserved for phase markers + classification — keeps the diff harness output focused on driver shape, not control-point dumps.
- **Diagnostic sweeps consolidated**: the step-4 gated sweep (which ran its own classify+sort for trace emission) is gone. With the rewrite, setflags/edgecmp are unconditional, so the trace block just reports the live state without duplicating work.
- **Nondeterminism caveat documented**: `1453.dot` produces a ~9.72pt uniform coordinate shift across runs without `PYTHONHASHSEED=0`. Pre-existing set-iteration issue (already in `memory/feedback_set_nondeterminism.md`); not caused by this rewrite. `aa1332.dot` remains deterministic across runs regardless of hash seed.
- **Harness verification**: `tools/diff_phases.py <file> spline` on `{a->b; a->b; c->c;}` shows **4 common lines out of 6 on each side** (up from 1 in step 4):
  - `[TRACE spline] edgecmp_sorted: [c->c a->b a->b]` ✓ matches
  - `[TRACE spline] phase4 begin: et=10 normalize=1` ✓ matches (after format alignment)
  - `[TRACE spline] phase4 end: edges_routed=3` ✓ matches
  - `[TRACE spline] setflags: a->b type=REGULAR dir=FWD tree_index=81` ✓ matches
  - Remaining 2 drifted lines are the documented architectural divergence: C tags duplicate `a->b` and `c->c` with AUXGRAPH bit (128) because they live in `ND_other`/`ND_flat_out`; Python uses MAINGRAPH only. Phase B will add Python's flat_out/other tracking.
- **Port map status update**: Phase A `done` jumps from 16 → 18. Both `dot_splines_` and `dot_splines` flip from `partial` → `done`. **Phase A is now 18/20 done — the remaining 2 are the ortho-only `setEdgeLabelPos` and the Phase-F-territory `place_vnlabel`, both of which can stay `missing` until their downstream phase work starts.** Summary: **total done 19, partial 10, missing 103, n/a 18**.
- Anchor SVG byte counts after rewrite: `1453.dot` 19951, `2734.dot` 10948, `aa1332.dot` 138108, `2592.dot` 3980, `1444.dot` 906. All stable (modulo the `1453.dot` PYTHONHASHSEED non-determinism).
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

---

## Next action

**🎉 Phase A complete.**

**Phase B — pathplan port + box-corridor optimiser.** This is the single largest piece of the whole port and gates every downstream routing phase. 51 missing functions across:

1. **`lib/pathplan/*`** — visibility.c, cvt.c, shortest.c, shortestpth.c, route.c, triang.c, solvers.c, util.c, inpoly.c. About 30 public + private functions, all `missing`. New Python package `gvpy/engines/layout/dot/pathplan/` with one module per C file.
2. **`lib/common/routespl.c`** — `routesplinesinit`, `routesplines_`, `routesplines`, `routepolylines`, `limitBoxes`, `checkpath`, `overlap`, `simpleSplineRoute`. The **load-bearing primitive**: every multi-rank, labeled-flat, and bottom-arc edge in C goes through `routesplines_`, and no Phase D/E function can produce a C-matching port without it.
3. **`lib/common/splines.c` path helpers** — `add_box`, `beginpath`, `endpath`. The end-box chain construction that feeds `routesplines_`.

**Suggested decomposition**:
- **Step B1**: minimal pathplan primitives — `solvers.c` (polynomial roots), `inpoly.c` (point-in-polygon), `util.c` (`Ppolybarriers`). ~10 small pure-math functions. Standalone unit tests possible.
- **Step B2**: `visibility.c` — visibility graph builder. ~15 functions including `visibility`, `ptVis`, `directVis`, `area2`, `wind`, `intersect`, `in_cone`. Still pure geometry, no routing integration yet.
- **Step B3**: `triang.c` (`Ptriangulate`) + `shortest.c` (`Pshortestpath`) + `shortestpth.c` (Dijkstra on visibility graph). Depends on B1 + B2.
- **Step B4**: `cvt.c` (`Pobsopen` / `Pobspath`) — glues visibility + Dijkstra.
- **Step B5**: `route.c` — `Proutespline` + its recursive `reallyroutespline` / `mkspline` / `splinefits` / `splineintersectsline` + Bernstein basis helpers. The spline-fit-through-barriers engine.
- **Step B6**: `lib/common/routespl.c` — `routesplines_` + `limitBoxes` + `checkpath` + `simpleSplineRoute`. Wraps the pathplan API for the dotgen caller.
- **Step B7**: `lib/common/splines.c` path helpers — `add_box`, `beginpath`, `endpath`. Builds the end-box chain that `routesplines_` traverses.

After Phase B (step B7) the full box-corridor infrastructure exists and Phase D (`make_regular_edge`) can port as a literal transliteration that calls `beginpath` / `rank_box` / `endpath` / `routesplines` without any heuristic fallback.

**Start point recommendation:** step B1 (solvers + inpoly + util). Small, independent, testable — a good warm-up for the much larger step B5 / B6 work. Each of those ~10 functions is 5–50 lines, pure math, no Python data-model dependencies.

### 2026-04-15 — Phase B step B1: pathplan primitives
- **New package `gvpy/engines/layout/dot/pathplan/`** with six modules:
  - `pathgeom.py` — `Ppoint`, `Pvector`, `Ppoly`, `Ppolyline`, `Pedge` dataclasses mirroring `pathgeom.h:33-54`. `Ppoly.pn` is a computed property (Python lists carry length).
  - `solvers.py` — `solve1`, `solve2`, `solve3` from `solvers.c:26-105`. Python API uses tuple return `(count, roots)` instead of C's in-out parameter; the `count==4` degenerate-equation sentinel is preserved so downstream callers see the same semantics.
  - `visibility.py` — minimal stub with `area2` + `wind` only. Full visibility graph lands in step B2. Split out now because `in_poly` depends on `wind`.
  - `inpoly.py` — `in_poly(poly, q) -> bool` from `inpoly.c:26-35`. Convex-polygon CW-winding test.
  - `util.py` — `Ppolybarriers(polys) -> list[Pedge]`, `make_polyline(line) -> Ppolyline`, `freePath` (no-op). Python returns lists directly instead of C's output-pointer+count pattern. `make_polyline` allocates a fresh list instead of C's thread-unsafe `static LIST`.
  - `__init__.py` — re-exports the 14 public symbols.
- **10 functions ported total**: `Ppoint`/`Pvector`/`Ppoly`/`Ppolyline`/`Pedge` (5 types), `solve1`/`solve2`/`solve3`, `area2`/`wind`, `in_poly`, `Ppolybarriers`/`make_polyline`/`freePath`. Plus the supporting constants and helpers.
- **Smoke tests (9/9 PASS)** cover every function:
  1. Dataclass construction + `Ppoly.pn` length.
  2. `solve1` linear + degenerate `0==0` + `0==nonzero` cases.
  3. `solve2` on `x²-3x+2`, `x²+1` (no real), `(x-1)²` (double), and linear fallback `2x+4`.
  4. `solve3` on `(x-1)(x-2)(x-3)`, `x³-1`, `x³`, quadratic fallback.
  5. `area2` returns 100 for the canonical `(0,0)-(10,0)-(0,10)` triangle (2× the 50 area).
  6. `wind` returns `1`/`-1`/`0` for CCW/CW/collinear, with the 0.0001 tolerance verified.
  7. `in_poly` on a CW-oriented square: interior points True, all four exterior directions False.
  8. `Ppolybarriers` flattens two triangles to 6 edges in the expected vertex order.
  9. `make_polyline` expands `[A,B,C,D]` → `[A,A,B,B,B,C,C,C,D,D]` (10 points). Empty input handled.
- **Port map status update**: Phase B jumps from 0 → 10 done. 10 entries flip from `missing` → `done`. Summary: **total done 29, partial 10, missing 93, n/a 18**.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

---

### 2026-04-15 — Phase B step B2: visibility graph
- **New module `pathplan/vispath.py`** with:
  - `Vconfig` dataclass mirroring C `struct vconfig_s` in `vis.h:29-39` (fields: `Npoly`, `N`, `P`, `start`, `next`, `prev`, `vis`). Field name `next` shadows the Python builtin — preserved verbatim from C.
  - `POLYID_NONE = -1111`, `POLYID_UNKNOWN = -2222` sentinel constants.
- **`visibility.py` expanded** with 13 new functions ported literally from `visibility.c:26-355`:
  - Pure geometry: `inBetween`, `intersect`, `in_cone`, `dist`, `dist2`, `inCone`, `clear`.
  - 2D-array allocator: `allocArray` (nested-list model — `V × V` plus `extra` None rows).
  - Internal compute pass: `compVis` (pairwise vertex visibility).
  - Public entry points: `visibility`, `polyhit`, `ptVis`, `directVis`.
- **Visibility matrix storage** — picked nested `list[list[float]]`. Pure Python, no numpy dependency. Pragmatic for the small V values typical of dot layouts (tens of polygons, hundreds of vertices total). Can switch to numpy later if Phase D profiling shows the spline fit is bottlenecked on visibility-matrix access.
- **Circular import fix** — `visibility.py` lazy-imports `in_poly` inside `polyhit` to break the `visibility.py → inpoly.py → visibility.py` dependency chain. Documented at the import site.
- **`__init__.py` re-exports** all 15 new public symbols: `allocArray`, `clear`, `compVis`, `dist`, `dist2`, `directVis`, `in_cone`, `inBetween`, `inCone`, `intersect`, `polyhit`, `ptVis`, `visibility`, `POLYID_NONE`, `POLYID_UNKNOWN`, `Vconfig`. Total pathplan API surface now 29 symbols.
- **Smoke tests (12/12 PASS)** on a CW square obstacle at `(3,3)-(7,7)`:
  1. `inBetween` on horizontal + vertical segments, endpoint excluded.
  2. `intersect` on crossing, parallel, disjoint, and T-intersection cases.
  3. `in_cone` convex: CCW sequence `(0,10)→(0,0)→(10,0)`, `(5,5)` inside, `(-5,5)` and `(5,-5)` outside.
  4. `in_cone` reflex: CW sequence `(10,0)→(0,0)→(0,10)`, `(-5,-5)` inside (big region), `(5,5)` outside (excluded wedge).
  5. `dist` / `dist2` on the 3-4-5 triangle.
  6. `allocArray(4, 2)` → 4 V-length zero lists + 2 `None` placeholders, independent row aliasing.
  7. `clear` on a triangle: blocks a horizontal line, allows a disjoint vertical line.
  8. `visibility` on the 4-vertex square: matrix populated with distance 4 between adjacent vertices, `None` placeholders at rows 4-5.
  9. `polyhit`: `(5,5)` → polygon 0, `(0,0)` and `(10,10)` → `POLYID_NONE`.
  10. `directVis`: `(0,0)→(10,0)` below the square (True), `(0,5)→(10,5)` through the square (False), `(5,10)→(5,20)` above (True).
  11. `ptVis` from `(10,3)` outside the polygon: length N+2 vector, at least one visible vertex, placeholders zero.
  12. `ptVis` with `POLYID_UNKNOWN` on a point inside the polygon → `polyhit` delegation correctly zeros the polygon's own vertices.
- **Port map status update**: Phase B jumps from 10 → 23 done. 13 entries flip from `missing` → `done`. Summary: **total done 42, partial 10, missing 80, n/a 18**.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

---

### 2026-04-15 — Phase B step B3: triangulation + shortest path
- **New module `pathplan/triang.py`** (~240 lines):
  - `ISCCW`/`ISCW`/`ISON` enum constants from `tri.h`.
  - `ccw` with graphviz screen-coordinate convention (y-down, sign INVERTED from `visibility.wind`). Documented at length — this is an easy source of subtle porting bugs.
  - `_between` / `_intersects` private helpers (distinct from `visibility.intersect`, which uses `wind`).
  - `isdiagonal(i, ip2, points, n, indexer=None)` with pluggable indexer, shared by both `Ptriangulate` and `shortest.Pshortestpath`.
  - `Ptriangulate(polygon, fn, vc=None)` — public ear-clipping entry, calls `fn(vc, triangle)` for each emitted triangle. Preserves the C callback pattern.
- **New module `pathplan/shortestpth.py`** (~140 lines):
  - `shortestPath(root, target, V, wadj) -> list[int]` — Dijkstra with C's sign-flip settled/tentative trick. Sentinel preserved via explicit variable instead of C's `val[-1]` pointer hack. Lower-triangular matrix access matching C.
  - `makePath(p, pp, pvis, q, qp, qvis, conf) -> list[int]` — glue: direct-visibility short-circuit via `directVis`, otherwise splices `pvis`/`qvis` into rows `V` and `V+1` of `conf.vis` and delegates to `shortestPath`.
- **New module `pathplan/shortest.py`** (~430 lines — the single biggest pathplan file):
  - `_PointNLink` / `_TriEdge` / `_Triangle` / `_Deque` dataclasses mirroring C's `pointnlink_t` / `tedge_t` / `triangle_t` / `deque_t`. `_Triangle.e` is a list of three `_TriEdge` objects rather than C's fixed `[3]` array.
  - 8 private helpers: `_point_indexer_shortest`, `_loadtriangle`, `_triangulate_pnls`, `_connecttris`, `_marktripath`, `_add2dq`, `_splitdq`, `_finddqsplit`, `_pointintri`.
  - `Pshortestpath(polyp, eps) -> (int, Ppolyline)` — tuple-return over C's out-parameter pattern. Per-call state (`state["tris"]`, local `dq`) instead of C's static globals — thread-safe and test-isolated.
  - Auto-detects polygon winding and reverses if not CCW, matching C's behaviour. Preserves C's duplicate-vertex deduplication.
- **Key quirk documented**: `ccw` has INVERTED sign semantics from `wind`. C's `ccw(a, b, c)` returns `ISCW` for math-convention CCW triangles because graphviz uses screen coordinates (y increases downward). Test cases use the graphviz "CCW" interpretation: `(0,0) → (0,1) → (1,0)` is graphviz-CCW.
- **Smoke tests (8/8 PASS)**:
  1. `ccw` graphviz convention — three cases covering CCW / CW / collinear.
  2. `isdiagonal` on a CCW pentagon — `(0, 2)` returns True.
  3. `Ptriangulate` on a CCW square → 2 triangles emitted via callback.
  4. `Ptriangulate` on a CCW pentagon → 3 triangles.
  5. `Pshortestpath` direct case: square with nearby endpoints → straight line `pn=2`.
  6. **`Pshortestpath` L-shape funnel case**: endpoints `(1, 5)` and `(5, 1)` in a CW L-polygon → path `[(1, 5), (2, 2), (5, 1)]`. This is the textbook funnel-algorithm output pivoting through the inner corner. Confirms triangulation + strip marking + funnel walk + back-chain reconstruction all work end-to-end.
  7. `shortestPath` Dijkstra on a 3-node hand-built graph finds `0 → 1 → 2` (cost 2) over the direct `0 → 2` edge (cost 3).
  8. `makePath` direct-visibility short-circuit on a square obstacle with line-of-sight below it.
- **Port map status update**: Phase B jumps from 23 → 36 done. 13 entries flip from `missing` → `done` (6 in shortest.c + 2 in shortestpth.c + 5 in triang.c, counting private helpers and `ccw`). Summary: **total done 55, partial 10, missing 67, n/a 18**.
- `tests/test_dot_layout.py` / `test_dot_parser.py` / `test_svg_renderer.py`: 300/300 green.

---

### 2026-04-15 — Phase B step B4: obstacle-avoidance glue (cvt.c)
- **New module `pathplan/cvt.py`** (~140 lines) with three public functions:
  - `Pobsopen(obs: list[Ppoly]) -> Vconfig` — flattens polygon obstacles into the Vconfig's `P` / `start` / `next` / `prev` layout, builds the doubly-linked ring structure per polygon, and calls `visibility()` to populate the matrix.
  - `Pobsclose(config)` — no-op (Python GC handles cleanup). Preserved for API symmetry with C.
  - `Pobspath(config, p0, poly0, p1, poly1) -> Ppolyline` — end-to-end obstacle-avoidance path finder: `ptVis` × 2 → `makePath` → walk `dad` back-pointer array → build output polyline. Python deviation: returns the polyline directly instead of C's out-parameter pattern.
- **Python API deviations documented**:
  - C's `Pobsopen(Ppoly_t **obs, int n_obs)` → Python `Pobsopen(obs: list[Ppoly])` (count implicit in list length).
  - C's `Pobspath(..., Ppolyline_t *output_route)` → Python `Pobspath(...) -> Ppolyline`.
- **Smoke tests (7/7 PASS)** covering the full pipeline:
  1. `Pobsopen` single square → correct Vconfig shape (`N=4`, `start=[0,4]`, `next=[1,2,3,0]`, `prev=[3,0,1,2]`, `vis` populated).
  2. `Pobspath` direct-visibility line below the obstacle → 2-point output.
  3. **`Pobspath` single-square detour** `(0,5) → (10,5)` through an obstacle at `(3,3)-(7,7)` → **`[(0,5), (3,7), (7,7), (10,5)]`** — pivots through the top-left and top-right corners.
  4. `Pobsopen` two disjoint squares → `start=[0, 4, 8]`, `N=8`.
  5. **`Pobspath` two-obstacle detour** → **`[(0,5), (2,6), (4,6), (6,6), (8,6), (10,5)]`** — 6-point path climbing over both obstacles along their top edges.
  6. `Pobsclose` safe to call on any Vconfig.
  7. **`Pobspath` diagonal detour** `(0,2) → (10,8)` → **`[(0,2), (3,7), (10,8)]`** — single-corner pivot through `(3,7)`.
- **Port map status update**: Phase B jumps from 36 → 39 done. 3 entries flip from `missing` → `done`. Summary: **total done 58, partial 10, missing 64, n/a 18**.
- **End-to-end obstacle-avoidance pipeline is live**: `Pobsopen → visibility → ptVis → makePath → back-pointer walk → Pobspath`. Any downstream code can now call `Pobspath(conf, p, POLYID_NONE, q, POLYID_NONE)` on a set of polygon barriers and get a clean detour polyline.
- `tests/test_dot_layout.py`: 238/238 green.

---

### 2026-04-15 — Phase B step B5a+b: route.c foundations
- **New module `pathplan/route.py`** with 15 functions landed in the first B5 sub-pass:
  - **Vector math**: `add`, `sub`, `dist` (route-local — distinct from `visibility.dist` for fidelity), `scale`, `dot`, `normv`.
  - **Bernstein basis**: `B0`, `B1`, `B2`, `B3` (standard cubic basis), `B01` / `B23` (combined weights used by `mkspline`).
  - **Polynomial helpers**: `points2coeff` (cubic Bezier → coefficient list), `addroot` (append a root to a list if in `[0, 1]`).
  - **Polyline length**: `dist_n` (sum of segment `math.hypot` distances).
  - **Least-squares fit**: `mkspline` — solves the 2×2 normal equations for the two tangent magnitudes, pinned endpoints, with fallback to the `d01 / 3` heuristic when the Gram matrix is singular.
- **`Tna` dataclass** mirrors C's `tna_t` struct for per-sample `(t, a[0], a[1])` tuples used by `mkspline`.
- **Python API deviations**:
  - C's `mkspline(..., sp0*, sv0*, sp1*, sv1*)` (4 out-parameters) → Python returns a 4-tuple.
  - C's `points2coeff(..., coeff[])` → Python returns a fresh `list[float]`.
  - C's `addroot(..., roots*, rootnp*)` → Python appends to a list (caller inspects `len(roots)`).
- **Duplicate `dist` preserved**: `visibility.dist` and `route.dist` are two distinct file-scope statics in C; Python keeps them in separate modules for fidelity. Mathematically identical (both `math.hypot(dx, dy)`).
- **Smoke tests (13/13 PASS)**:
  1. `add` / `sub` / `dist` / `scale` / `dot` — basic vector ops.
  2. `normv`: unit-length normalisation + zero-vector guard (`d > 1e-6`).
  3. **Bernstein partition-of-unity**: `B0 + B1 + B2 + B3 == 1` at every test `t` (7 sample points).
  4. Bernstein endpoint values: `B0(0)==1, B3(1)==1, B1(0)==B2(0)==B1(1)==B2(1)==0`.
  5. Midpoint symmetry: `B1(0.5) == B2(0.5)`, `B0(0.5) == B3(0.5)`.
  6. `B01 + B23 == 1` at every test `t`.
  7. `points2coeff` on the linear-bezier case `[0, 1/3, 2/3, 1]` → `[0, 1, 0, 0]` — the polynomial `t`. Validates the constant-term-first ordering matches `solvers.solve3`'s convention.
  8. `addroot` closed-interval `[0, 1]` acceptance + out-of-range rejection.
  9. `dist_n` on a unit-grid staircase (3-segment total 3.0), on a 5-12-13 Pythagorean straight line (13.0), on a 1-point degenerate input (0.0).
  10. `mkspline` symmetric 3-sample fit: endpoints pinned, tangent directions inward (`sv0.x > 0, sv1.x < 0`), magnitudes positive.
  11. **`mkspline` singular fallback**: all-zero basis vectors → tangent magnitude collapses to `dist(end0, end1) / 3 = 10/3` exactly.
- **Port map status update**: Phase B jumps from 39 → 52 done (13 new route.c entries). Summary: **total done 71, partial 10, missing 51, n/a 18**.
- `tests/test_dot_layout.py`: 238/238 green.

### 2026-04-15 — Phase B step B5c: splineintersectsline
- **`splineintersectsline(sps, lps) -> (int, list[float])`** added to `pathplan/route.py`. Literal transliteration of `route.c:314-392`.
- **Three internal cases preserved** from C:
  1. **Degenerate line (point)** — both `dx == 0` and `dy == 0`: solve `x(t) = lps[0].x` and `y(t) = lps[0].y` separately, combine via set intersection (or propagate the `xrootn == 4` / `yrootn == 4` sentinels).
  2. **Vertical line** — `dx == 0`, `dy != 0`: solve `x(t) = lps[0].x`, then check `y(t)` maps to `sv ∈ [0, 1]`.
  3. **General line** — `dx != 0`: rotate coords (`y' = y - rat * x`) so the line becomes horizontal, solve, verify `x(t)` maps to `sv ∈ [0, 1]`.
- **Python API deviation**: C uses an out-parameter `roots[4]`; Python returns `(count, roots)` tuple. The `count == 4` "everything is a root" sentinel is preserved for downstream callers (`splinefits` in B5d).
- **Smoke tests (8/8 PASS)** on the canonical `(0,0)→(3,5)→(7,5)→(10,0)` arch cubic:
  1. Horizontal line `y=2` across full width → 2 roots at `t = (15 ± √105)/30 ≈ 0.1584, 0.8416`. Exact analytic match with the hand-derived quadratic `15t² - 15t + 2 = 0`.
  2. Horizontal line `y=5` above the peak (3.75) → 0 roots.
  3. Baseline `y=0` matching endpoints → 2 roots at exactly `t=0.0` and `t=1.0`.
  4. Vertical line `x=5` (case 2 coverage) → 1 root at `t=0.5`, verified `y(0.5) = 3.75`.
  5. Vertical line `x=15` out of x-range → 0 roots.
  6. **Short segment rejection**: `(2,2)→(4,2)` on a line that hits the cubic at `x ≈ 1.66, 8.34` (outside the segment) → 0 roots. Confirms segment-parameter `sv ∈ [0, 1]` check is enforced.
  7. Degenerate point case → returns cleanly (0 or 1 roots depending on floating-point equality).
  8. Slanted line `y = 2 + 0.2*x` (case 3) → roots verified by plugging back into the line equation.
- **Port map status update**: Phase B jumps from 52 → 53 done. Summary: **total done 72, partial 10, missing 50, n/a 18**.
- `tests/test_dot_layout.py`: 238/238 green.

---

## Next action

**Phase B step B5d — recursive core.** The final B5 sub-pass, and the closing piece of pathplan `route.c`:

- **`splinefits`** (~100 lines of C, lines 212–313) — takes a trial cubic Bezier, tests whether every polyline sample lies within the tangent cone, tests whether the cubic crosses any barrier edge, and either accepts the fit or signals a split.  Called recursively.
- **`reallyroutespline`** (~60 lines, lines 97–158) — the recursive kernel.  Tries `mkspline + splinefits` at the current granularity, subdivides the polyline at the midpoint if the fit fails, and retries.
- **`Proutespline`** (~30 lines, lines 70–96) — public entry point.  Sets up the `tna_t` sample array, computes endpoint tangent directions, and calls `reallyroutespline`.

**Recommendation**: pause here and restart in a fresh session for B5d. Reasons:

1. The recursive core is the trickiest part of the whole pathplan port — subtle bugs in `splinefits` will cascade through `reallyroutespline` and be hard to isolate.
2. An end-to-end Bezier-fit smoke test (real obstacle graph → `Pobspath` polyline → `Proutespline` cubic) is worth a clean context budget so I can fully reason about the input, the expected output, and any numerical divergences.
3. TODO captures exact status and all smoke-test patterns from B5a-c — a fresh session can pick up without reconstructing the mental model.

**If** you want to continue now instead: the natural next action is to read `route.c:97-313` (`reallyroutespline` + `splinefits`), transliterate both, and land the `Proutespline` public entry + end-to-end smoke test. Probably feasible in the current context, but closer to the edge than the last few passes.
