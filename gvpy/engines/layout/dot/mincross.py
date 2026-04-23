"""Phase 2: crossing minimization.

See: /lib/dotgen/mincross.c @ 743

Responsibilities
----------------
Given rank-assigned nodes (from Phase 1), compute an ordering within
each rank that minimizes edge crossings between adjacent ranks.
Supports hierarchical cluster constraints via the skeleton-based
expand pattern that mirrors C's ``mincross_clust`` recursion.

Extracted functions
-------------------
The following were moved from ``DotGraphInfo`` in ``dot_layout.py``
as free functions taking ``layout`` as the first argument:

- :func:`phase2_ordering`          — entry point (``_phase2_ordering``)
- :func:`run_mincross`             — non-cluster driver (``_run_mincross``)
- :func:`remincross_full`          — final ReMincross pass on expanded graph
- :func:`skeleton_mincross`        — cluster-aware skeleton + expand driver
- :func:`cluster_medians`          — C ``mincross.c:medians()``
- :func:`cluster_reorder`          — C ``mincross.c:reorder()`` bubble sort
- :func:`cluster_transpose`        — C ``mincross.c:transpose_step()`` + ``left2right``
- :func:`cluster_build_ranks`      — C ``mincross.c:build_ranks()`` + class2 + fastgr
- :func:`order_by_weighted_median` — legacy per-rank median sort
- :func:`transpose_rank`           — legacy per-rank transpose
- :func:`count_crossings_for_pair` — pair-wise crossing check used by transpose
- :func:`count_all_crossings`      — global crossing count (C ``ncross``)
- :func:`count_scoped_crossings`   — cluster-scoped crossing count (C ``ncross``
  with per-subgraph ``ND_out``)
- :func:`save_ordering`            — C ``save_best``
- :func:`restore_ordering`         — C ``restore_best``
- :func:`flat_reorder`             — C ``mincross.c:flat_reorder``
- :func:`mark_low_clusters`        — C ``mincross.c:mark_lowclusters``
- :func:`mval_edge`                — C ``VAL(node, port)`` with port.order

Each ``DotGraphInfo._xxx`` method is now a 3-line delegating wrapper
calling the matching function here.

Session history
---------------
The cluster-ordering investigation work of the 2026-04-10..12 sessions
landed primarily in ``skeleton_mincross``, ``cluster_build_ranks``,
``cluster_medians`` and ``cluster_reorder``.  Key fixes:

- **DFS cluster expand order** (``skeleton_mincross``): replaced a
  depth-iteration BFS loop with depth-first recursion through the
  cluster tree to match C's ``mincross_clust`` call order.  Without
  this, children of the same parent were processed before siblings
  were expanded, producing different median propagation.

- **Scoped crossing count** (``count_scoped_crossings``): C's
  ``ncross()`` uses the per-subgraph fast graph's ``ND_out``, which
  excludes intra-child-cluster edges (``class2.c:199``).  Python
  previously used a global edge iterator that counted extra edges
  and caused the mincross "better or equal" early-termination to
  reject valid reorderings.

- **down_first / up_first boundary** (``skeleton_mincross`` local
  mincross block): C's ``mincross_step`` (``mincross.c:1534-1546``)
  includes the cluster's min rank in the down pass when the cluster
  is a sub-cluster (``GD_minrank(g) > GD_minrank(Root)``), not just
  ``min+1``.  Python now mirrors this boundary adjustment.

- **class2 fast graph** (``cluster_build_ranks``): matches C's
  ``fast_node`` (prepend to nlist), ``fast_edge`` (append to ND_out),
  ``build_skeleton`` (rank-leader virtual chain), ``install_cluster``
  (BFS install-all-ranks-then-enqueue-all-neighbors), and
  ``interclrep``/``leader_of`` for cross-cluster edge redirection.

Related modules
---------------
- :mod:`gvpy.engines.layout.dot.position` — Phase 3 position assignment.
  Shares no state with mincross; runs after mincross has finalized
  the rank orderings.
- :mod:`gvpy.engines.layout.dot.dot_layout` — holds ``DotGraphInfo`` (the
  state container) and still has Phase 1 rank assignment, Phase 4
  spline routing, and cluster geometry helpers.  Mincross functions
  here take ``layout: DotGraphInfo`` as their first argument and
  read/mutate ``layout.lnodes``, ``layout.ranks``, ``layout.ledges``,
  ``layout._clusters`` directly.
"""
from __future__ import annotations

import sys
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from gvpy.engines.layout.dot.trace import trace

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import DotGraphInfo


def phase2_ordering(layout):
    trace("order", f"phase2 begin: ordering={layout.ordering}")
    if not layout.ranks:
        return

    for rank_nodes in layout.ranks.values():
        for i, name in enumerate(rank_nodes):
            layout.lnodes[name].order = i

    # Build innermost-cluster map (used by _left2right)
    layout._mark_low_clusters()

    # ordering=out preserves input order — skip crossing minimization
    if layout.ordering in ("out", "in"):
        trace("order", f"skip mincross: ordering={layout.ordering}")
        return

    # ── Skeleton-based cluster ordering ──────────────
    # Mirrors Graphviz class2 build_skeleton → init_mincross → mincross
    # → mincross_clust expand_cluster → mincross per cluster.
    if layout._clusters:
        layout._skeleton_mincross()
        d5_stage_crossings(layout, "after_skeleton_mincross")
        # Final remincross on full expanded graph (C: mincross(g, 2))
        # C mincross.c:381-398: runs mincross on the fully expanded
        # graph with ReMincross=true.  Uses VAL with port.order from
        # real node record fields.
        if layout.remincross:
            layout._mark_low_clusters()
            layout._remincross_full()
            d5_stage_crossings(layout, "after_remincross_full")
    else:
        layout._run_mincross()

    crossings = layout._count_all_crossings()
    trace("order", f"after mincross: crossings={crossings}")

    # Enforce flat-edge ordering: tails left of heads
    layout._flat_reorder()

    # Log final ordering (matching C format: name(order))
    for r in sorted(layout.ranks.keys()):
        names = layout.ranks[r]
        parts = []
        for n in names:
            if not layout.lnodes[n].virtual:
                parts.append(f"{n}({layout.lnodes[n].order})")
        if parts:
            trace("order", f"rank {r}: {' '.join(parts)}")

    # D5 diagnostic — measure multi-rank-edge sides relative to
    # non-member clusters.  Gated on ``GV_TRACE=d5`` so the cost is
    # zero in normal runs.
    from gvpy.engines.layout.dot.trace import trace_on as _d5_on
    if _d5_on("d5"):
        _trace_d5_sides(layout, stage="final")


def d5_stage_crossings(layout, stage: str) -> int:
    """Count current cluster-straddle crossings (same metric
    as :func:`_trace_d5_sides`) and emit a single summary line.

    Used to pinpoint which pipeline stage introduces the bulk of
    the D5 crossings when debugging the skeleton / expand flow.
    """
    from gvpy.engines.layout.dot.trace import trace, trace_on
    if not trace_on("d5"):
        return 0
    crosses = _count_d5_crosses(layout)
    trace("d5", f"stage={stage} cluster_pair_crosses={crosses}")
    return crosses


def _count_d5_crosses(layout) -> int:
    """Return the number of edge × non-member-cluster pairs whose
    sides string contains both ``L`` and ``R``, or any ``T`` — the
    same classification used by :func:`_trace_d5_sides`."""
    if not layout.ranks:
        return 0
    cluster_orders: dict[str, dict[int, tuple[int, int]]] = {}
    cluster_members: dict[str, set[str]] = {}
    for cl in layout._clusters:
        member_set = set(cl.nodes)
        cluster_members[cl.name] = member_set
        per_rank: dict[int, tuple[int, int]] = {}
        for r, rank_nodes in layout.ranks.items():
            orders = [i for i, n in enumerate(rank_nodes) if n in member_set]
            if orders:
                per_rank[r] = (min(orders), max(orders))
        cluster_orders[cl.name] = per_rank

    chains = getattr(layout, "_vnode_chains", {}) or {}
    seen: set[tuple[str, str]] = set()
    reports: list[tuple[str, str, list[tuple[int, str]]]] = []
    for (tail_name, head_name), chain in chains.items():
        seq: list[tuple[int, str]] = []
        if tail_name in layout.lnodes:
            seq.append((layout.lnodes[tail_name].rank, tail_name))
        seq.extend((layout.lnodes[v].rank, v) for v in chain
                   if v in layout.lnodes)
        if head_name in layout.lnodes:
            seq.append((layout.lnodes[head_name].rank, head_name))
        if len(seq) >= 2:
            reports.append((tail_name, head_name, seq))
            seen.add((tail_name, head_name))
    for le in layout.ledges:
        if le.virtual:
            continue
        pair = (le.tail_name, le.head_name)
        if pair in seen:
            continue
        if le.tail_name not in layout.lnodes or le.head_name not in layout.lnodes:
            continue
        tr = layout.lnodes[le.tail_name].rank
        hr = layout.lnodes[le.head_name].rank
        reports.append((le.tail_name, le.head_name,
                        [(tr, le.tail_name), (hr, le.head_name)]))

    crosses = 0
    for tail_name, head_name, seq in reports:
        for cl in layout._clusters:
            member_set = cluster_members[cl.name]
            if tail_name in member_set or head_name in member_set:
                continue
            per_rank = cluster_orders[cl.name]
            if not per_rank:
                continue
            sides: list[str] = []
            for r, node_name in seq:
                if r not in per_rank:
                    sides.append("-")
                    continue
                cl_min, cl_max = per_rank[r]
                try:
                    n_order = layout.ranks[r].index(node_name)
                except ValueError:
                    continue
                if n_order < cl_min:
                    sides.append("L")
                elif n_order > cl_max:
                    sides.append("R")
                else:
                    sides.append("T")
            meaningful = {s for s in sides if s in ("L", "R", "T")}
            if not meaningful:
                continue
            if ("L" in meaningful and "R" in meaningful) or "T" in meaningful:
                crosses += 1
    return crosses


def _trace_d5_sides(layout, stage: str = "final") -> None:
    """Emit per-edge, per-non-member-cluster "side" classifications
    at mincross-exit.

    For every real edge (tail, head — spanning ≥ 1 rank), we walk the
    full rank sequence [tail_rank .. head_rank] and at each rank
    classify the edge's touching node (tail / virtual / head) relative
    to every non-member cluster's order range in that rank::

        L  — node_order < min(cluster member orders)
        R  — node_order > max(cluster member orders)
        T  — node_order lies within the range (threading through)
        -  — cluster has no members at this rank

    A "clean" edge (``LLL`` or ``RRR``) hugs one side of the cluster
    throughout.  A flipping edge (``LLR`` or ``RLL``) geometrically
    crosses the cluster — the same cluster-corner-grazing that D4
    fights post-hoc at the splines layer.  This pass only **measures**
    — it does not modify ordering.  Divergence from C at this level
    points to the mincross stage as the root cause.

    Emitted line format (greppable)::

        [TRACE d5] edge=<tail>-><head> ranks=r0-rN span=<N>
                   cluster=<name> sides=<string> crosses=<True|False>
                   members_preview=<csv>
    """
    if not layout.ranks:
        trace("d5", "no ranks to classify")
        return

    # Precompute order ranges for every cluster at every rank it
    # touches.  Uses the cluster's ``nodes`` list (post-expansion,
    # includes virtual members from the rank insertion pass).
    cluster_orders: dict[str, dict[int, tuple[int, int]]] = {}
    cluster_members: dict[str, set[str]] = {}
    for cl in layout._clusters:
        member_set = set(cl.nodes)
        cluster_members[cl.name] = member_set
        per_rank: dict[int, tuple[int, int]] = {}
        for r, rank_nodes in layout.ranks.items():
            orders = [i for i, n in enumerate(rank_nodes) if n in member_set]
            if orders:
                per_rank[r] = (min(orders), max(orders))
        cluster_orders[cl.name] = per_rank

    chains = getattr(layout, "_vnode_chains", {}) or {}

    # Walk every ORIGINAL edge — both multi-rank (via chain) and
    # short (direct tail→head).  For multi-rank edges we thread
    # through the intermediate virtuals; for short edges we sample
    # just the two endpoints.
    visited_pairs: set[tuple[str, str]] = set()
    edge_reports: list[tuple[str, str, list[tuple[int, str]]]] = []

    for (tail_name, head_name), chain in chains.items():
        seq: list[tuple[int, str]] = []
        if tail_name in layout.lnodes:
            seq.append((layout.lnodes[tail_name].rank, tail_name))
        seq.extend((layout.lnodes[v].rank, v) for v in chain
                   if v in layout.lnodes)
        if head_name in layout.lnodes:
            seq.append((layout.lnodes[head_name].rank, head_name))
        if len(seq) >= 2:
            edge_reports.append((tail_name, head_name, seq))
            visited_pairs.add((tail_name, head_name))

    # Now add short (adjacent / flat) real edges not already covered
    # by a chain entry.  ledges includes virtual edges, so filter.
    for le in layout.ledges:
        if le.virtual:
            continue
        pair = (le.tail_name, le.head_name)
        if pair in visited_pairs:
            continue
        if le.tail_name not in layout.lnodes or le.head_name not in layout.lnodes:
            continue
        tr = layout.lnodes[le.tail_name].rank
        hr = layout.lnodes[le.head_name].rank
        seq = [(tr, le.tail_name), (hr, le.head_name)]
        edge_reports.append((le.tail_name, le.head_name, seq))

    # Summary counters
    total_edges = len(edge_reports)
    crosses = 0
    edges_with_relevant_cluster = 0

    for tail_name, head_name, seq in edge_reports:
        r0 = seq[0][0]
        rN = seq[-1][0]
        span = abs(rN - r0) + 1
        any_relevant = False
        for cl in layout._clusters:
            member_set = cluster_members[cl.name]
            if tail_name in member_set or head_name in member_set:
                continue
            per_rank = cluster_orders[cl.name]
            if not per_rank:
                continue
            any_overlap = any(r in per_rank for r, _ in seq)
            if not any_overlap:
                continue
            any_relevant = True
            sides: list[str] = []
            for r, node_name in seq:
                if r not in per_rank:
                    sides.append("-")
                    continue
                cl_min, cl_max = per_rank[r]
                rank_nodes = layout.ranks.get(r, [])
                try:
                    n_order = rank_nodes.index(node_name)
                except ValueError:
                    sides.append("?")
                    continue
                if n_order < cl_min:
                    sides.append("L")
                elif n_order > cl_max:
                    sides.append("R")
                else:
                    sides.append("T")
            meaningful = {s for s in sides if s in ("L", "R", "T")}
            crosses_this = ("L" in meaningful and "R" in meaningful) \
                or ("T" in meaningful)
            if crosses_this:
                crosses += 1
            members_in = ",".join(sorted(member_set))[:60]
            trace(
                "d5",
                f"edge={tail_name}->{head_name} "
                f"ranks={r0}-{rN} span={span} "
                f"cluster={cl.name} "
                f"sides={''.join(sides)} "
                f"crosses={crosses_this} "
                f"members_preview={members_in}"
            )
        if any_relevant:
            edges_with_relevant_cluster += 1

    trace(
        "d5",
        f"summary total_edges={total_edges} "
        f"edges_vs_nonmember_cluster={edges_with_relevant_cluster} "
        f"edge_cluster_pair_crosses={crosses}"
    )


def run_mincross(layout):
    """Run crossing minimization sweeps on the current rank arrays.

    See: /lib/dotgen/mincross.c @ 743

    Alternates down passes (median + reorder + transpose at each rank
    from min to max) and up passes (max to min), tracking the best
    ordering seen so far via save_best / restore_best.  Iteration
    count is bounded by MAX_MINCROSS_ITER × mclimit (C ``MaxIter``).

    The ``use_cluster_impl`` flag switches between two backends:

    - ``cluster_medians`` + ``cluster_reorder`` + ``cluster_transpose``
      (matches C's ``medians()``/``reorder()``/``transpose()`` in
      ``lib/dotgen/mincross.c``, including ``VAL`` + port.order
      scaling, sawclust, and bubble-sort reorder semantics).  Required
      for correctness in skeleton / remincross passes.
    - ``order_by_weighted_median`` + ``transpose_rank`` (legacy
      Python-idiomatic group-sort implementation).  Kept as a
      fallback for non-clustered graphs where it's cheaper and
      produces equivalent orderings.  Enabled when
      ``GVPY_LEGACY_MINCROSS=1``.
    """
    from gvpy.engines.layout.dot.trace import trace, trace_on
    import os as _os_mc
    _trace_order = trace_on("order")
    if _trace_order:
        _n_nodes = sum(len(v) for v in layout.ranks.values())
        _n_ranks = len(layout.ranks)
        trace("order", f"mincross_entry n_ranks={_n_ranks} "
                       f"n_nodes={_n_nodes}")

    _legacy = _os_mc.environ.get("GVPY_LEGACY_MINCROSS", "") == "1"

    # Set up fast graph + node-to-cluster map for the cluster-aware
    # backend.  Mirrors the prep already done by ``remincross_full``
    # (mincross.py lines 405-435) and C's ``init_mincross`` setup.
    all_nodes = set(layout.lnodes.keys())
    node_cl: dict[str, str] = {}
    if layout._clusters:
        for cl in sorted(layout._clusters,
                         key=lambda c: len(c.nodes), reverse=True):
            for n in cl.nodes:
                if n in layout.lnodes:
                    node_cl[n] = cl.name  # innermost wins
    fg_out: dict[str, list[str]] = defaultdict(list)
    fg_in: dict[str, list[str]] = defaultdict(list)
    _seen: set[tuple[str, str]] = set()
    for le in layout.ledges:
        t, h = le.tail_name, le.head_name
        if t == h:
            continue
        if t not in layout.lnodes or h not in layout.lnodes:
            continue
        pair = (t, h)
        if pair in _seen:
            continue
        _seen.add(pair)
        fg_out[t].append(h)
        fg_in[h].append(t)

    max_rank = max(layout.ranks.keys()) if layout.ranks else 0
    best_crossings = layout._count_all_crossings()
    best_order = layout._save_ordering()

    iterations = max(1, int(layout.MAX_MINCROSS_ITER * layout.mclimit))
    _done_iter = 0
    _step_calls = 0

    def _step(down: bool, reverse: bool) -> None:
        if _legacy:
            rng = (range(1, max_rank + 1) if down
                   else range(max_rank - 1, -1, -1))
            for r in rng:
                if r in layout.ranks:
                    layout._order_by_weighted_median(
                        r, r - 1 if down else r + 1)
                    layout._transpose_rank(r)
            return
        rng = (range(1, max_rank + 1) if down
               else range(max_rank - 1, -1, -1))
        for r in rng:
            if r not in layout.ranks:
                continue
            layout._cluster_medians(
                r, r - 1 if down else r + 1,
                all_nodes, fg_out, fg_in)
            layout._cluster_reorder(r, all_nodes, node_cl, reverse)
        # One transpose pass per full down+up cycle — matches C's
        # mincross_step (single transpose at the end).
        if not down:
            for r in range(max_rank + 1):
                if r in layout.ranks:
                    layout._cluster_transpose(r, all_nodes, node_cl)

    for pass_i in range(iterations):
        _done_iter += 1
        reverse = (pass_i % 4) < 2
        _step(down=True, reverse=reverse)
        _step(down=False, reverse=reverse)
        _step_calls += 1
        c = layout._count_all_crossings()
        if c < best_crossings:
            best_crossings = c
            best_order = layout._save_ordering()

    if layout.remincross and best_crossings > 0:
        for pass_i in range(iterations):
            _done_iter += 1
            reverse = (pass_i % 4) < 2
            _step(down=True, reverse=reverse)
            _step(down=False, reverse=reverse)
            _step_calls += 1
            c = layout._count_all_crossings()
            if c < best_crossings:
                best_crossings = c
                best_order = layout._save_ordering()

    layout._restore_ordering(best_order)
    if _trace_order:
        trace("order", f"mincross_exit total_iterations={_done_iter} "
                       f"total_step_calls={_step_calls} "
                       f"final_crossings={best_crossings}")


def remincross_full(layout):
    """Final remincross on the fully expanded graph.

    Matches C mincross.c:381-398: mincross(g, 2) with ReMincross=true
    after all cluster expansion.  Uses _cluster_medians with VAL
    + port.order from Node.record_fields, and _cluster_reorder with
    the full reorder bubble sort.  Scoped fast graph covers all nodes.
    """
    all_nodes = set(layout.lnodes.keys())
    max_rank = max(layout.ranks.keys()) if layout.ranks else 0
    min_rank = min(layout.ranks.keys()) if layout.ranks else 0

    # Build scoped fast graph for the full graph
    # (matching C class2 at root level, class2.c:155-282)
    fg_out: dict[str, list[str]] = defaultdict(list)
    fg_in: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    # mark_clusters for ReMincross: left2right blocks ALL
    # cross-cluster swaps (mincross.c:612-613)
    node_cl: dict[str, str] = {}
    if layout._clusters:
        for cl in sorted(layout._clusters,
                         key=lambda c: len(c.nodes), reverse=True):
            for n in cl.nodes:
                if n in layout.lnodes:
                    node_cl[n] = cl.name  # innermost cluster

    for le in layout.ledges:
        t, h = le.tail_name, le.head_name
        if t not in layout.lnodes or h not in layout.lnodes:
            continue
        if t == h:
            continue
        pair = (t, h)
        if pair not in seen:
            seen.add(pair)
            fg_out[t].append(h)
            fg_in[h].append(t)

    # C mincross.c:774-797 iteration loop
    max_iter = max(4, int(24 * layout.mclimit))
    cur_cross = best_cross = layout._count_all_crossings()
    best_order = layout._save_ordering()
    _MIN_QUIT = 8
    _CONVERGENCE = 0.995
    trying = 0

    for _pass in range(max_iter):
        if cur_cross == 0:
            break
        if trying >= _MIN_QUIT:
            break
        trying += 1

        reverse = (_pass % 4) < 2
        if _pass % 2 == 0:
            for r in range(min_rank + 1, max_rank + 1):
                if r in layout.ranks:
                    layout._cluster_medians(
                        r, r - 1, all_nodes, fg_out, fg_in)
                    layout._cluster_reorder(
                        r, all_nodes, node_cl, reverse,
                        remincross_phase=True)
        else:
            for r in range(max_rank - 1, min_rank - 1, -1):
                if r in layout.ranks:
                    layout._cluster_medians(
                        r, r + 1, all_nodes, fg_out, fg_in)
                    layout._cluster_reorder(
                        r, all_nodes, node_cl, reverse,
                        remincross_phase=True)
        # Single transpose (mincross.c:1553)
        for r in range(min_rank, max_rank + 1):
            if r in layout.ranks:
                layout._cluster_transpose(
                    r, all_nodes, node_cl, remincross_phase=True)

        cur_cross = layout._count_all_crossings()
        if cur_cross <= best_cross:
            if cur_cross < _CONVERGENCE * best_cross:
                trying = 0
            best_cross = cur_cross
            best_order = layout._save_ordering()

    layout._restore_ordering(best_order)


def skeleton_mincross(layout):
    """Skeleton-based cluster ordering matching Graphviz mincross.

    1. Build skeleton: replace each top-level cluster with one virtual
       rank-leader node per rank it spans.
    2. Run mincross on the reduced graph.
    3. Expand: splice real cluster nodes at the skeleton position,
       run mincross within each cluster, recurse into children.
    4. Clean up skeleton nodes.
    """
    node_sets = {cl.name: set(cl.nodes) for cl in layout._clusters}

    # Build parent map
    parent_of: dict[str, str | None] = {}
    for cl in layout._clusters:
        best, best_sz = None, float("inf")
        for other in layout._clusters:
            if other.name == cl.name:
                continue
            if node_sets[cl.name] < node_sets[other.name]:
                if len(node_sets[other.name]) < best_sz:
                    best, best_sz = other.name, len(node_sets[other.name])
        parent_of[cl.name] = best

    children_of: dict[str | None, list[str]] = {}
    for cn, par in parent_of.items():
        children_of.setdefault(par, []).append(cn)

    top_clusters = children_of.get(None, [])
    if not top_clusters:
        layout._run_mincross()
        return

    cl_by_name = {cl.name: cl for cl in layout._clusters}

    # Lazy import — class-level references lost scope when moved out
    # of dot_layout.py.  Both classes are used by the nested
    # _build_skeleton closure below.
    from gvpy.engines.layout.dot.dot_layout import LayoutNode, LayoutEdge

    # ── Build skeletons for ALL clusters (all levels) ──
    skeleton_nodes: dict[str, dict[int, str]] = {}
    skeleton_edges: list[LayoutEdge] = []

    def _build_skeleton(cl_name: str):
        """Create rank-leader virtual nodes for a cluster."""
        cl_node_set = node_sets[cl_name]
        # Only use DIRECT nodes (not in child clusters)
        child_nodes: set[str] = set()
        for child in children_of.get(cl_name, []):
            child_nodes.update(node_sets[child])
        direct = cl_node_set - child_nodes

        cl_ranks = sorted(set(
            layout.lnodes[n].rank for n in cl_node_set if n in layout.lnodes
        ))
        if not cl_ranks:
            return

        rank_leaders: dict[int, str] = {}
        prev_leader = None
        for r in cl_ranks:
            vn_name = f"_skel_{cl_name}_{r}"
            vn = LayoutNode(name=vn_name, node=None, rank=r, virtual=True,
                            width=4.0, height=4.0)
            layout.lnodes[vn_name] = vn
            rank_leaders[r] = vn_name
            if prev_leader is not None:
                se = LayoutEdge(
                    edge=None, tail_name=prev_leader, head_name=vn_name,
                    minlen=1, weight=layout._CL_CROSS, virtual=True,
                )
                skeleton_edges.append(se)
                layout.ledges.append(se)
            prev_leader = vn_name
        skeleton_nodes[cl_name] = rank_leaders

        # Build child skeletons first (depth-first)
        for child in children_of.get(cl_name, []):
            _build_skeleton(child)

    for cl_name in top_clusters:
        _build_skeleton(cl_name)

    # ── Inter-cluster skeleton edges ──────────────────────
    # For each real edge crossing between child clusters of the same
    # parent, create a skeleton edge between the rank-leader nodes.
    # This gives the local mincross (during expand) something to work
    # with when ordering sibling cluster skeletons.
    #
    # Build a map: real node → innermost skeleton-owning cluster
    _node_skel_cluster: dict[str, str] = {}
    for cl_name in skeleton_nodes:
        for n in node_sets[cl_name]:
            if n in layout.lnodes:
                _node_skel_cluster[n] = cl_name  # last write = innermost

    _seen_skel_edges: set[tuple[str, str]] = set()
    for le in layout.ledges:
        if le.virtual:
            continue
        t_cl = _node_skel_cluster.get(le.tail_name)
        h_cl = _node_skel_cluster.get(le.head_name)
        if not t_cl or not h_cl or t_cl == h_cl:
            continue
        # Find the sibling level: walk up until both share the same parent
        t_path: list[str] = [t_cl]
        cur = t_cl
        while parent_of.get(cur) is not None:
            cur = parent_of[cur]
            t_path.append(cur)
        h_path: list[str] = [h_cl]
        cur = h_cl
        while parent_of.get(cur) is not None:
            cur = parent_of[cur]
            h_path.append(cur)
        h_set = set(h_path)
        # Find sibling pair: for each parent, check if both are children
        for par_cl in t_path:
            if par_cl in h_set:
                # par_cl is the common ancestor
                # t_child = the child of par_cl on the tail side
                t_child = t_path[max(0, t_path.index(par_cl) - 1)]
                h_child = h_path[max(0, h_path.index(par_cl) - 1)]
                if t_child == par_cl or h_child == par_cl:
                    break  # one is a direct node of par_cl, not a child cluster
                if t_child == h_child:
                    break  # same child cluster
                # Create inter-cluster edge chain between rank-leaders.
                # Mirrors C class2.c:99-124 interclrep() → make_chain():
                # instead of a direct edge from t_skel to h_skel,
                # create a chain of virtual nodes at intermediate ranks
                # so the BFS visits all ranks between the endpoints.
                t_rank = layout.lnodes[le.tail_name].rank
                h_rank = layout.lnodes[le.head_name].rank
                t_skel = skeleton_nodes.get(t_child, {}).get(t_rank)
                h_skel = skeleton_nodes.get(h_child, {}).get(h_rank)
                if t_skel and h_skel and t_rank != h_rank:
                    # Ensure t_rank < h_rank (C interclrep:106-108)
                    if t_rank > h_rank:
                        t_skel, h_skel = h_skel, t_skel
                        t_rank, h_rank = h_rank, t_rank
                    key = (t_skel, h_skel)
                    if key not in _seen_skel_edges:
                        _seen_skel_edges.add(key)
                        # C class2.c:70-96 make_chain(): create chain
                        # from→v1→v2→...→to with virtual nodes at
                        # each intermediate rank.
                        prev_name = t_skel
                        for cr in range(t_rank + 1, h_rank + 1):
                            if cr < h_rank:
                                # Intermediate virtual node
                                # (C class2.c:87 plain_vnode)
                                cvn = f"_icv_{t_skel}_{h_skel}_{cr}"
                                layout.lnodes[cvn] = LayoutNode(
                                    name=cvn, node=None, rank=cr, virtual=True,
                                    width=2.0, height=2.0)
                                next_name = cvn
                            else:
                                next_name = h_skel
                            ce = LayoutEdge(
                                edge=None, tail_name=prev_name,
                                head_name=next_name,
                                minlen=1, weight=le.weight,
                                virtual=True)
                            skeleton_edges.append(ce)
                            layout.ledges.append(ce)
                            prev_name = next_name
                elif t_skel and h_skel and t_rank == h_rank:
                    # Same rank: C interclrep:114-115 skips same-rank
                    # inter-cluster edges.  No edge created.
                    pass
                break

    # ── Collapse: replace clusters with skeletons, top-down ──
    # For each cluster (deepest first), hide its direct nodes and
    # child skeleton nodes, replace with this cluster's skeleton.
    # Process deepest children first so their skeletons are in place
    # before the parent collapses.

    # Compute depth for ordering
    depth_of: dict[str, int] = {}
    for cl_name in skeleton_nodes:
        d, cur = 0, cl_name
        while parent_of.get(cur) is not None:
            d += 1
            cur = parent_of[cur]
        depth_of[cl_name] = d
    max_depth = max(depth_of.values()) if depth_of else 0

    # Track which nodes are currently visible (not hidden)
    hidden_by: dict[str, str] = {}  # node_name → cl_name that hid it

    # Collapse from deepest to shallowest
    for d in range(max_depth, -1, -1):
        for cl_name, rank_leaders in skeleton_nodes.items():
            if depth_of.get(cl_name, 0) != d:
                continue

            # Nodes to hide: direct nodes + child cluster skeletons
            cl_node_set = node_sets[cl_name]
            child_skel_nodes: set[str] = set()
            for child in children_of.get(cl_name, []):
                if child in skeleton_nodes:
                    child_skel_nodes.update(skeleton_nodes[child].values())

            to_hide = set()
            for n in cl_node_set:
                if n in layout.lnodes and n not in hidden_by:
                    to_hide.add(n)
            to_hide.update(n for n in child_skel_nodes if n not in hidden_by)

            for r in sorted(rank_leaders.keys()):
                rank_list = layout.ranks.get(r, [])
                new_rank = []
                skel_inserted = False
                for name in rank_list:
                    if name in to_hide:
                        hidden_by[name] = cl_name
                        if not skel_inserted:
                            new_rank.append(rank_leaders[r])
                            skel_inserted = True
                    else:
                        new_rank.append(name)
                if not skel_inserted and r in rank_leaders:
                    new_rank.append(rank_leaders[r])
                layout.ranks[r] = new_rank
                for i, name in enumerate(layout.ranks[r]):
                    layout.lnodes[name].order = i

    # ── Run mincross on fully collapsed graph ──
    layout._run_mincross()
    d5_stage_crossings(layout, "post_collapsed_mincross")

    # Trace skeleton ordering (just skeleton node positions)
    for r in sorted(layout.ranks.keys()):
        skel_parts = []
        for n in layout.ranks[r]:
            if n.startswith("_skel_"):
                skel_parts.append(n)
        if skel_parts:
            trace("order", f"skeleton rank {r}: {skel_parts}")

    # ── Expand: DFS through cluster tree ──
    # C mincross.c:574-598 mincross_clust recurses depth-first
    # through the cluster tree in GD_clust (definition) order:
    #   mincross_clust(g):
    #     expand_cluster(g); mincross(g, 2);
    #     for c in GD_clust(g): mincross_clust(c)
    # This is different from BFS by depth — for each cluster, we
    # fully recurse into all its children before moving to the
    # next sibling.  Mixing up this order changes what's visible
    # as a skeleton vs a real node at mincross time, and changes
    # the median/reorder results.
    cluster_dfs_order: list[str] = []
    def _dfs_cluster_order(parent: str | None):
        for child in children_of.get(parent, []):
            if child in skeleton_nodes:
                cluster_dfs_order.append(child)
                _dfs_cluster_order(child)
    _dfs_cluster_order(None)

    for cl_name in cluster_dfs_order:
        if True:  # preserve existing indentation
            rank_leaders = skeleton_nodes[cl_name]

            # Collect nodes hidden by this cluster
            cl_hidden = {n for n, hider in hidden_by.items()
                         if hider == cl_name and n in layout.lnodes}

            # Collect virtual nodes that participate in this cluster's
            # BFS.  In C, the cluster subgraph contains virtual nodes
            # from edge splitting AND inter-cluster chain nodes from
            # interclrep/make_chain (class2.c:70-96).
            cl_member_set = node_sets[cl_name]
            cl_virtual: set[str] = set()
            cl_min_r = min(rank_leaders.keys())
            cl_max_r = max(rank_leaders.keys())
            for vname, vln in layout.lnodes.items():
                if not vln.virtual:
                    continue
                if vln.rank < cl_min_r or vln.rank > cl_max_r:
                    continue
                # Include inter-cluster chain nodes (_icv_*) created
                # by interclrep make_chain (C class2.c:70-96)
                if vname.startswith("_icv_"):
                    cl_virtual.add(vname)
                    continue
                # Include virtual nodes from edge splitting whose
                # chain connects two cluster members
                for le in layout.ledges:
                    if le.tail_name == vname or le.head_name == vname:
                        ot = getattr(le, 'orig_tail', None)
                        oh = getattr(le, 'orig_head', None)
                        if ot and oh and ot in cl_member_set and oh in cl_member_set:
                            cl_virtual.add(vname)
                            break

            # Child skeleton nodes
            child_skel_set: set[str] = set()
            child_skel_ranks: dict[str, dict[int, str]] = {}
            for child in children_of.get(cl_name, []):
                if child in skeleton_nodes:
                    child_skel_ranks[child] = skeleton_nodes[child]
                    for sn in skeleton_nodes[child].values():
                        child_skel_set.add(sn)

            # BFS over hidden + virtual + child skeleton nodes
            bfs_nodes = cl_hidden | cl_virtual | child_skel_set
            bfs_order, cl_fg_out, cl_fg_in = layout._cluster_build_ranks(
                bfs_nodes, child_skel_set, child_skel_ranks,
                node_sets)

            # Splice BFS-ordered nodes at skeleton positions.
            # Virtual nodes that were already in layout.ranks at
            # their positions need to be removed first then
            # re-inserted in BFS order.
            for r, skel_name in rank_leaders.items():
                rank_list = layout.ranks.get(r, [])
                try:
                    skel_pos = rank_list.index(skel_name)
                except ValueError:
                    continue

                # Remove virtual nodes that will be re-placed by BFS.
                # Sort for deterministic removal order (cl_virtual is a set).
                virt_at_r = sorted(n for n in cl_virtual
                                   if n in layout.lnodes
                                   and layout.lnodes[n].rank == r)
                for vn in virt_at_r:
                    if vn in rank_list:
                        idx = rank_list.index(vn)
                        rank_list.pop(idx)
                        if idx < skel_pos:
                            skel_pos -= 1

                # Get BFS-ordered nodes for this rank, filters to
                # correct rank
                restore = [n for n in bfs_order.get(r, [])
                           if n in layout.lnodes
                           and layout.lnodes[n].rank == r]
                if restore:
                    rank_list[skel_pos:skel_pos + 1] = restore
                else:
                    rank_list.pop(skel_pos)
                layout.ranks[r] = rank_list
                for i, name in enumerate(rank_list):
                    layout.lnodes[name].order = i

            # Un-hide these nodes
            for n in list(hidden_by):
                if hidden_by[n] == cl_name:
                    del hidden_by[n]

            # Trace expand ordering (matching C format)
            trace("order", f"expand_cluster {cl_name}: after build_ranks")
            for r2 in sorted(rank_leaders.keys()):
                parts = []
                for n in layout.ranks.get(r2, []):
                    if n in child_skel_set:
                        # Find which child cluster this skeleton represents
                        for ch, rls in child_skel_ranks.items():
                            if n in rls.values():
                                parts.append(f"[CL:{ch}]")
                                break
                    elif n in layout.lnodes and not layout.lnodes[n].virtual:
                        if n in node_sets.get(cl_name, set()):
                            parts.append(n)
                if parts:
                    trace("order", f"  rank {r2}: {' '.join(parts)}")

            # Local mincross within this cluster.
            # Include child skeleton nodes that haven't been expanded
            # yet — they stand in for the child clusters and carry
            # inter-cluster edges needed by the median heuristic.
            cl_node_set = set(node_sets[cl_name])
            for child in children_of.get(cl_name, []):
                if child in skeleton_nodes:
                    for sn in skeleton_nodes[child].values():
                        if sn in layout.lnodes:
                            cl_node_set.add(sn)
            cl_ranks = sorted(set(
                layout.lnodes[n].rank for n in cl_node_set
                if n in layout.lnodes
            ))
            if len(cl_ranks) >= 2:
                min_r, max_r = min(cl_ranks), max(cl_ranks)

                # Build child-cluster map matching C's mark_clusters:
                # each node maps to its top-level child cluster within
                # cl_name.  Skeleton nodes are NOT mapped (they can be
                # swapped freely — matching C left2right exception for
                # CLUSTER+VIRTUAL nodes).
                child_cl_map: dict[str, str] = {}
                for child in children_of.get(cl_name, []):
                    for n in node_sets.get(child, set()):
                        if n in cl_node_set:
                            child_cl_map[n] = child

                max_iter = max(4, int(24 * layout.mclimit))

                # Build post-expansion scoped fast graph for real
                # nodes, matching C class2 inside expand_cluster
                # (cluster.c:282,298 → class2.c:155-282).
                # Includes edges where both endpoints are in
                # cl_node_set.  Excludes intra-child-cluster edges.
                mc_fg_out: dict[str, list[str]] = defaultdict(list)
                mc_fg_in: dict[str, list[str]] = defaultdict(list)
                mc_seen: set[tuple[str, str]] = set()

                def _skel_sub(name: str) -> str:
                    """Map a real node that's currently hidden by a
                    child cluster's skeleton to that skeleton node at
                    the node's rank.

                    During ``cl_name``'s local mincross, every child
                    sub-cluster is collapsed to a row of ``_skel_*``
                    nodes and its real members are recorded in
                    ``hidden_by``.  When we hand ``mc_fg_in`` /
                    ``mc_fg_out`` to ``cluster_medians`` it walks
                    ``layout.ranks[adj_rank]`` looking for neighbours;
                    a hidden real node will not be there, so its mval
                    contribution gets silently dropped.  Substitute
                    the live skeleton representation so the median
                    computation sees something at the right order.
                    """
                    hider = hidden_by.get(name)
                    if hider is None:
                        return name
                    r = layout.lnodes[name].rank
                    skel = skeleton_nodes.get(hider, {}).get(r)
                    return skel if skel is not None else name

                for le in layout.ledges:
                    t, h = le.tail_name, le.head_name
                    if t not in cl_node_set and h not in cl_node_set:
                        continue
                    if t not in layout.lnodes or h not in layout.lnodes:
                        continue
                    t_in = t in cl_node_set
                    h_in = h in cl_node_set
                    if not t_in and not h_in:
                        continue
                    # Include virtual nodes within rank range
                    if not t_in or not h_in:
                        t_r = layout.lnodes[t].rank
                        h_r = layout.lnodes[h].rank
                        if t_r < min_r or t_r > max_r:
                            continue
                        if h_r < min_r or h_r > max_r:
                            continue
                    if t == h:
                        continue  # class2.c:226
                    # Exclude intra-child-cluster (class2.c:199)
                    t_ch = child_cl_map.get(t)
                    h_ch = child_cl_map.get(h)
                    if t_ch and h_ch and t_ch == h_ch:
                        continue
                    # Substitute hidden real nodes with their
                    # currently-active skeleton representation so
                    # cluster_medians can find them in layout.ranks
                    # at the right rank+order.  Without this, virtual
                    # nodes whose upstream/downstream neighbour lives
                    # in a sibling child cluster get mval=-1 and drift
                    # to the end of their rank.
                    t_sub = _skel_sub(t)
                    h_sub = _skel_sub(h)
                    pair = (t_sub, h_sub)
                    if pair not in mc_seen:
                        mc_seen.add(pair)
                        mc_fg_out[t_sub].append(h_sub)
                        mc_fg_in[h_sub].append(t_sub)

                # C ncross() (mincross.c:1617) uses ND_out which is
                # the cluster's scoped fast graph — intra-child-cluster
                # edges are excluded (class2.c:199).  We emulate this
                # by counting only edges in mc_fg_out.
                def _scoped_cross():
                    return layout._count_scoped_crossings(
                        mc_fg_out, min_r, max_r)
                cur_cross = best_cross = _scoped_cross()
                best_order = layout._save_ordering()

                # C mincross.c:774-797: iteration loop.
                _MIN_QUIT = 8       # mincross.c:1820
                _CONVERGENCE = 0.995  # mincross.c:159
                trying = 0

                # C mincross_step (mincross.c:1534-1546):
                # down pass: first = GD_minrank(g) + 1, but for
                # sub-clusters (GD_minrank(g) > GD_minrank(Root)),
                # first-- (so it includes the cluster's first rank).
                # up pass: symmetric with GD_maxrank(g).
                # Root's min rank for this graph.
                root_min = min(layout.ranks.keys()) if layout.ranks else 0
                root_max = max(layout.ranks.keys()) if layout.ranks else 0
                down_first = min_r + 1
                if min_r > root_min:
                    down_first = min_r
                up_first = max_r - 1
                if max_r < root_max:
                    up_first = max_r

                for _pass in range(max_iter):
                    if cur_cross == 0:
                        break
                    if trying >= _MIN_QUIT:
                        break
                    trying += 1

                    # mincross_step (mincross.c:1528-1554)
                    reverse = (_pass % 4) < 2
                    if _pass % 2 == 0:
                        for r in range(down_first, max_r + 1):
                            if r in layout.ranks:
                                layout._cluster_medians(
                                    r, r - 1, cl_node_set,
                                    mc_fg_out, mc_fg_in)
                                layout._cluster_reorder(
                                    r, cl_node_set, child_cl_map,
                                    reverse)
                    else:
                        for r in range(up_first, min_r - 1, -1):
                            if r in layout.ranks:
                                layout._cluster_medians(
                                    r, r + 1, cl_node_set,
                                    mc_fg_out, mc_fg_in)
                                layout._cluster_reorder(
                                    r, cl_node_set, child_cl_map,
                                    reverse)
                    for r in range(min_r, max_r + 1):
                        if r in layout.ranks:
                            layout._cluster_transpose(
                                r, cl_node_set, child_cl_map)

                    # mincross.c:786-791: check improvement using scoped count
                    cur_cross = _scoped_cross()
                    if cur_cross <= best_cross:
                        if cur_cross < _CONVERGENCE * best_cross:
                            trying = 0
                        best_cross = cur_cross
                        best_order = layout._save_ordering()

                layout._restore_ordering(best_order)
                d5_stage_crossings(layout, f"post_expand_{cl_name}")

    # ── Clean up skeleton nodes, chain nodes, and edges ──
    for cl_name, rank_leaders in skeleton_nodes.items():
        for r, skel_name in rank_leaders.items():
            if r in layout.ranks and skel_name in layout.ranks[r]:
                layout.ranks[r].remove(skel_name)
            layout.lnodes.pop(skel_name, None)

    # Remove inter-cluster chain virtual nodes (_icv_* from
    # interclrep make_chain, C class2.c:70-96)
    icv_names = [n for n in layout.lnodes if n.startswith("_icv_")]
    for n in icv_names:
        for r in layout.ranks.values():
            if n in r:
                r.remove(n)
        del layout.lnodes[n]

    skel_edge_set = set(id(se) for se in skeleton_edges)
    layout.ledges = [le for le in layout.ledges if id(le) not in skel_edge_set]

    for r, rank_nodes in layout.ranks.items():
        for i, name in enumerate(rank_nodes):
            if name in layout.lnodes:
                layout.lnodes[name].order = i


def cluster_medians(layout, rank: int, adj_rank: int,
                      cl_nodes: set[str],
                      fg_out: dict | None = None,
                      fg_in: dict | None = None):
    """Compute median values for nodes at rank.

    Mirrors C mincross.c:1687-1743 medians().
    Uses VAL(node, port) = MC_SCALE * order + port.order
    (mincross.c:1685, sameport.c:151-152) for neighbor positions.
    Stores results in layout._node_mval[name].
    """
    rank_nodes = layout.ranks.get(rank, [])
    adj_set = set(layout.ranks.get(adj_rank, []))

    # Build port lookup for edges: (tail, head) → (headport, tailport)
    # Used to compute VAL with port.order (C mincross.c:1702,1706).
    # Pre-declared on DotGraphInfo.__init__; populate lazily on first
    # call (empty dict means not yet populated for this layout run).
    if not layout._edge_port_lookup:
        for le in layout.ledges:
            hp = getattr(le, 'headport', '') or ''
            tp = getattr(le, 'tailport', '') or ''
            # Strip compass suffix (e.g., "Out0:n" → "Out0")
            if ':' in hp:
                hp = hp.split(':')[0]
            if ':' in tp:
                tp = tp.split(':')[0]
            layout._edge_port_lookup[(le.tail_name, le.head_name)] = (hp, tp)

    for name in rank_nodes:
        if name not in cl_nodes:
            layout._node_mval[name] = -1.0
            continue

        positions = []
        if fg_out is not None and fg_in is not None:
            # Fast graph edges (C ND_out/ND_in)
            # Use VAL(node, port) (mincross.c:1702,1706)
            if adj_rank > rank:
                # Down: VAL(aghead(e), ED_head_port(e))
                for nbr in fg_out.get(name, []):
                    if nbr in adj_set:
                        hp, _ = layout._edge_port_lookup.get(
                            (name, nbr), ('', ''))
                        positions.append(layout._mval_edge(nbr, hp))
            else:
                # Up: VAL(agtail(e), ED_tail_port(e))
                for nbr in fg_in.get(name, []):
                    if nbr in adj_set:
                        _, tp = layout._edge_port_lookup.get(
                            (nbr, name), ('', ''))
                        positions.append(layout._mval_edge(nbr, tp))
        else:
            for le in layout.ledges:
                if le.tail_name == name and le.head_name in adj_set:
                    hp = getattr(le, 'headport', '') or ''
                    if ':' in hp:
                        hp = hp.split(':')[0]
                    positions.append(layout._mval_edge(le.head_name, hp))
                elif le.head_name == name and le.tail_name in adj_set:
                    tp = getattr(le, 'tailport', '') or ''
                    if ':' in tp:
                        tp = tp.split(':')[0]
                    positions.append(layout._mval_edge(le.tail_name, tp))

        # C mincross.c:1708-1735
        if not positions:
            layout._node_mval[name] = -1.0
        elif len(positions) == 1:
            layout._node_mval[name] = float(positions[0])
        elif len(positions) == 2:
            layout._node_mval[name] = (positions[0] + positions[1]) / 2.0
        else:
            positions.sort()
            m = len(positions) // 2
            if len(positions) % 2:
                layout._node_mval[name] = float(positions[m])
            else:
                lm = m - 1
                rspan = positions[-1] - positions[m]
                lspan = positions[lm] - positions[0]
                if lspan == rspan:
                    layout._node_mval[name] = (positions[lm] + positions[m]) / 2.0
                elif lspan + rspan > 0:
                    layout._node_mval[name] = (
                        positions[lm] * rspan + positions[m] * lspan
                    ) / (lspan + rspan)
                else:
                    layout._node_mval[name] = (positions[lm] + positions[m]) / 2.0

    # Trace median values + VAL details for specific ranks
    # Capture both skeleton level (>10 nodes) and child level (<10)
    _trace_names = {'c4118', 'c4145', 'c4147', 'c4051', 'c4139', 'c4138',
                    'c4143', 'c4146', 'c4236', 'c4243'}
    _has_trace_nodes = any(n in _trace_names for n in layout.ranks.get(rank, []))
    if _has_trace_nodes and rank in (1, 2, 3, 4, 5, 6):
        parts = []
        for name in layout.ranks.get(rank, []):
            if name in cl_nodes:
                v = "v" if (name in layout.lnodes and layout.lnodes[name].virtual) else ""
                parts.append(f"{name}{v}={layout._node_mval.get(name, -9):.1f}")
        trace("median", f"rank {rank} (adj {adj_rank}): {' '.join(parts)}")
        # Trace per-node neighbor VAL details
        adj_s = set(layout.ranks.get(adj_rank, []))
        for name in layout.ranks.get(rank, []):
            if name not in cl_nodes:
                continue
            nbr_parts = []
            if fg_out is not None and fg_in is not None:
                edge_list = fg_out.get(name, []) if adj_rank > rank else (fg_in or {}).get(name, [])
                for nbr in edge_list:
                    if nbr in adj_s:
                        if adj_rank > rank:
                            hp, _ = layout._edge_port_lookup.get((name, nbr), ('', ''))
                            val = layout._mval_edge(nbr, hp)
                            po = layout._port_order_cache.get((nbr, hp), 128)
                        else:
                            _, tp = layout._edge_port_lookup.get((nbr, name), ('', ''))
                            val = layout._mval_edge(nbr, tp)
                            po = layout._port_order_cache.get((nbr, tp), 128)
                        nbr_parts.append(f"{nbr}(ord={layout.lnodes[nbr].order},port={po},val={val})")
            else:
                for le in layout.ledges:
                    nbr = None
                    if le.tail_name == name and le.head_name in adj_s:
                        nbr = le.head_name
                        hp = (getattr(le, 'headport', '') or '').split(':')[0]
                        val = layout._mval_edge(nbr, hp)
                        po = layout._port_order_cache.get((nbr, hp), 128)
                    elif le.head_name == name and le.tail_name in adj_s:
                        nbr = le.tail_name
                        tp = (getattr(le, 'tailport', '') or '').split(':')[0]
                        val = layout._mval_edge(nbr, tp)
                        po = layout._port_order_cache.get((nbr, tp), 128)
                    if nbr:
                        nbr_parts.append(f"{nbr}(ord={layout.lnodes[nbr].order},port={po},val={val})")
            if nbr_parts:
                trace("median", f"  {name} adj_nbrs: {' '.join(nbr_parts)}")


def cluster_reorder(layout, rank: int, cl_nodes: set[str],
                      child_cl_map: dict[str, str] | None = None,
                      reverse: bool = False,
                      remincross_phase: bool = False):
    """Bubble-sort reorder matching C mincross.c:1476-1526 reorder().

    Compares nodes by mval (from _cluster_medians).  Skips nodes
    with mval < 0 (no neighbors).  Respects left2right (blocks
    swaps between different child clusters).  The sawclust logic
    allows jumping over a single cluster group.

    ``remincross_phase`` mirrors C's ``ReMincross`` flag.  When
    set, :func:`_left2right_blocks` uses the stricter rule —
    a swap is blocked whenever the two nodes belong to different
    clusters, including the non-member-vs-cluster-member case.
    That prevents non-cluster nodes from drifting *past* cluster
    members during the final expansion pass — which was the root
    cause of the D5 ``RL``-flip storm on 2796 (TODO §1 D5,
    Docs/D5_measurement_findings.md).
    """
    nodes = layout.ranks.get(rank, [])
    n = len(nodes)
    if n < 2:
        return

    mval = layout._node_mval
    ep = n  # shrinking endpoint (C: ep = vlist + n)

    # [TRACE d5_step] — emit the rank's state at reorder entry.  Uses
    # one-line format: `[TRACE d5_step] reorder_enter rank=R reverse=<bool>
    # rmx=<bool> nodes=<name:ord:mval ...>`.  Matching C emission at
    # mincross.c: start of reorder() for line-for-line diff.
    from gvpy.engines.layout.dot.trace import trace as _trace, trace_on as _on
    if _on("d5_step"):
        _ns = " ".join(
            f"{nm}:{i}:{mval.get(nm, -1):.2f}" for i, nm in enumerate(nodes))
        _trace("d5_step",
               f"reorder_enter rank={rank} reverse={1 if reverse else 0} "
               f"rmx={1 if remincross_phase else 0} nodes=[{_ns}]")

    for nelt in range(n - 1, -1, -1):  # C: nelt = n-1 downto 0
        li = 0
        while li < ep:
            # Find leftmost with mval >= 0 (C: mincross.c:1486)
            while li < ep and mval.get(nodes[li], -1) < 0:
                li += 1
            if li >= ep:
                break

            # Find right comparison partner (C: mincross.c:1493)
            sawclust = False
            muststay = False
            ri = li + 1
            while ri < ep:
                rn = nodes[ri]
                # sawclust: skip consecutive cluster nodes
                # (C mincross.c:1494-1495)
                r_cl = (child_cl_map or {}).get(rn)
                if sawclust and r_cl:
                    ri += 1
                    continue
                # left2right check (C mincross.c:1496-1498).  In the
                # remincross phase, the block fires whenever clusters
                # differ — including None vs a cluster — and has no
                # skeleton/virtual escape hatch (C: only the
                # non-ReMincross branch includes the virtual bypass).
                l_cl = (child_cl_map or {}).get(nodes[li])
                if remincross_phase:
                    if l_cl != r_cl:
                        muststay = True
                        break
                elif l_cl and r_cl and l_cl != r_cl:
                    # Check if either is virtual/skeleton (can swap)
                    lv = nodes[li] in layout.lnodes and layout.lnodes[nodes[li]].virtual
                    rv = rn in layout.lnodes and layout.lnodes[rn].virtual
                    if not lv and not rv:
                        muststay = True
                        break
                # Found node with mval >= 0 (C mincross.c:1500)
                if mval.get(rn, -1) >= 0:
                    break
                # Mark cluster encounter (C mincross.c:1502-1503)
                if r_cl:
                    sawclust = True
                ri += 1

            if ri >= ep:
                break

            _l_name = nodes[li]
            _r_name = nodes[ri]
            if not muststay:
                p1 = mval.get(nodes[li], -1)
                p2 = mval.get(nodes[ri], -1)
                # C mincross.c:1510: swap if p1>p2 or tie+reverse
                _swapped = p1 > p2 or (p1 >= p2 and reverse)
                if _on("d5_step"):
                    _trace("d5_step",
                           f"reorder_cmp rank={rank} l={_l_name}@{li} "
                           f"r={_r_name}@{ri} p1={p1:.2f} p2={p2:.2f} "
                           f"swapped={1 if _swapped else 0}")
                if _swapped:
                    # exchange (swap positions)
                    nodes[li], nodes[ri] = nodes[ri], nodes[li]
                    layout.lnodes[nodes[li]].order = li
                    layout.lnodes[nodes[ri]].order = ri
            elif _on("d5_step"):
                _trace("d5_step",
                       f"reorder_block rank={rank} l={_l_name}@{li} "
                       f"r={_r_name}@{ri}")

            li = ri

        # C mincross.c:1517-1518: shrink unless hasfixed or reverse
        if not reverse:
            ep -= 1


def cluster_transpose(layout, rank: int, cl_nodes: set[str],
                       child_cl_map: dict[str, str] | None = None,
                       remincross_phase: bool = False):
    """Adjacent-swap transpose restricted to cluster nodes.

    See: /lib/dotgen/mincross.c @ 685

    Iterates adjacent pairs in the rank, swapping when the swap
    reduces local crossings.  ``left2right()`` blocks swaps between
    nodes in different child clusters UNLESS at least one is a
    cluster-skeleton virtual node, preserving cluster grouping
    while letting the skeleton nodes float freely.

    ``remincross_phase`` mirrors C's ``ReMincross`` flag — when set,
    the block fires whenever clusters differ (including a
    non-cluster node drifting past a cluster member) and virtuals
    are NOT exempt.  Fixes the D5 ``RL``-flip pattern identified on
    2796 (see ``Docs/D5_measurement_findings.md``).
    """
    nodes = layout.ranks.get(rank, [])
    if len(nodes) < 2:
        return
    improved = True
    while improved:
        improved = False
        for i in range(len(nodes) - 1):
            v, w = nodes[i], nodes[i + 1]
            if v not in cl_nodes or w not in cl_nodes:
                continue
            # left2right check
            if child_cl_map is not None:
                v_cl = child_cl_map.get(v)
                w_cl = child_cl_map.get(w)
                if remincross_phase:
                    # C ReMincross branch: any cluster mismatch blocks,
                    # no virtual escape hatch.
                    if v_cl != w_cl:
                        continue
                elif v_cl and w_cl and v_cl != w_cl:
                    # Both in different non-null clusters — check if
                    # either is a virtual/skeleton node (can swap).
                    v_virt = v in layout.lnodes and layout.lnodes[v].virtual
                    w_virt = w in layout.lnodes and layout.lnodes[w].virtual
                    if not v_virt and not w_virt:
                        continue  # block swap
            c_before = layout._count_crossings_for_pair(v, w)
            c_after = layout._count_crossings_for_pair(w, v)
            if c_after < c_before:
                nodes[i], nodes[i + 1] = w, v
                layout.lnodes[w].order = i
                layout.lnodes[v].order = i + 1
                improved = True


def cluster_build_ranks(
    layout,
    bfs_nodes: set[str],
    child_skel_set: set[str],
    child_skel_ranks: dict[str, dict[int, str]],
    node_sets: dict[str, set[str]] | None = None,
) -> dict[int, list[str]]:
    """Initial ordering for cluster expand via class2 + decompose + build_ranks.

    Ports C expand_cluster (cluster.c:280-296):
      class2(subg)            → build fast graph with scoped edge lists
      build_ranks(subg, 0)    → decompose DFS for nlist, then BFS
    """
    _ns = node_sets or {}

    # ── Maps ──
    skel_to_child: dict[str, str] = {}
    for child_name, rleaders in child_skel_ranks.items():
        for sn in rleaders.values():
            skel_to_child[sn] = child_name

    # mark_clusters (class2.c:163): node → top-level child cluster
    node_child: dict[str, str] = {}
    for child_name in child_skel_ranks:
        for n in _ns.get(child_name, set()):
            if n in bfs_nodes:
                node_child[n] = child_name

    # ── Step 1: class2 — build fast graph (class2.c:155-282) ──
    # Per-node out/in edge lists + nlist, matching C fastgr.c.
    fg_nlist: list[str] = []          # GD_nlist — prepend order
    fg_nlist_set: set[str] = set()
    fg_out: dict[str, list[str]] = defaultdict(list)  # ND_out
    fg_in: dict[str, list[str]] = defaultdict(list)   # ND_in
    fg_edges: set[tuple[str, str]] = set()  # dedup

    def _fg_fast_node(n: str):
        """C fastgr.c:175-187 — prepend n to nlist."""
        if n not in fg_nlist_set:
            fg_nlist.insert(0, n)
            fg_nlist_set.add(n)

    def _fg_fast_edge(t: str, h: str):
        """C fastgr.c:71-93 — append to tail out / head in."""
        pair = (t, h)
        if pair not in fg_edges:
            fg_edges.add(pair)
            fg_out[t].append(h)
            fg_in[h].append(t)

    # 1a. build_skeleton for each child cluster
    # C class2.c:164-165, cluster.c:356-374.
    # virtual_node calls fast_node (prepend), virtual_edge calls
    # fast_edge (append to ND_out).  C iterates GD_clust array
    # which is in subgraph registration order (make_new_cluster
    # during initial ranking).  We approximate with the DOT file
    # subgraph definition order by walking layout.graph.subgraphs
    # recursively.
    def _subgraph_order(g) -> list[str]:
        """Collect cluster subgraph names in DOT definition order."""
        result = []
        for name, sub in g.subgraphs.items():
            if name in child_skel_ranks:
                result.append(name)
            result.extend(_subgraph_order(sub))
        return result
    child_order = _subgraph_order(layout.graph)
    # Add any child clusters not found in subgraph walk
    for cn in sorted(child_skel_ranks.keys()):
        if cn not in child_order:
            child_order.append(cn)
    for child_name in child_order:
        rleaders = child_skel_ranks[child_name]
        prev_sn = None
        for r in sorted(rleaders.keys()):
            sn = rleaders[r]
            _fg_fast_node(sn)            # virtual_node → fast_node
            if prev_sn is not None:
                _fg_fast_edge(prev_sn, sn)  # virtual_edge chain
            prev_sn = sn

    # 1b. Process each node's outgoing edges (class2.c:174-282).
    # C iterates agfstnode(g)/agnxtnode(g,n) for node order, then
    # agfstout(g,n)/agnxtout(g,e) for per-node edge order.
    # agfstout returns edges in the subgraph's edge dictionary
    # order — matching layout.graph.edges insertion order for
    # original edges.
    #
    # Build per-node outgoing edge index matching agfstout order.
    # Walk the graph's edge dictionary recursively (subgraphs
    # first, matching how edges appear in the DOT file).
    node_out_edges: dict[str, list] = defaultdict(list)

    def _collect_out_edges(g):
        """Collect per-node outgoing edges in DOT definition order
        (matching agfstout/agnxtout for the subgraph)."""
        for key, edge in g.edges.items():
            tail_name = key[0]
            if tail_name in bfs_nodes:
                node_out_edges[tail_name].append(edge)
        for sub in g.subgraphs.values():
            _collect_out_edges(sub)
    _collect_out_edges(layout.graph)

    # Also index virtual/skeleton edges per tail node
    # (these come from edge splitting and skeleton construction,
    # appended to layout.ledges after original edges)
    node_virt_edges: dict[str, list] = defaultdict(list)
    for le in layout.ledges:
        if le.virtual and le.tail_name in bfs_nodes:
            node_virt_edges[le.tail_name].append(le)

    dot_order = {name: i for i, name in enumerate(layout.graph.nodes)}
    ordered_nodes = sorted(
        bfs_nodes,
        key=lambda n: (dot_order.get(n, len(dot_order)), n))

    for n in ordered_nodes:
        # class2.c:175-176: non-cluster leader nodes → fast_node
        n_child = node_child.get(n) or skel_to_child.get(n)
        is_virtual = n in layout.lnodes and layout.lnodes[n].virtual
        if not n_child and not is_virtual:
            _fg_fast_node(n)

        # class2.c:179: iterate outgoing edges in agfstout order.
        # Process original edges first (from graph.edges), then
        # virtual edges (from layout.ledges, appended later).
        seen_heads: set[str] = set()

        # Helper: leader_of (class2.c:55-66) — for a node in a
        # child cluster, return the skeleton rank leader at the
        # node's rank.  For non-cluster nodes, return the node.
        def _leader_of(name):
            ch = node_child.get(name) or skel_to_child.get(name)
            if ch and ch in child_skel_ranks:
                r = layout.lnodes[name].rank if name in layout.lnodes else None
                if r is not None and r in child_skel_ranks[ch]:
                    return child_skel_ranks[ch][r]
            return name

        for edge in node_out_edges.get(n, []):
            h = edge.head.name if edge.head else None
            if not h or h not in bfs_nodes or h == n:
                continue

            t_ch = node_child.get(n) or skel_to_child.get(n)
            h_ch = node_child.get(h) or skel_to_child.get(h)

            if t_ch or h_ch:
                if t_ch and h_ch and t_ch == h_ch:
                    continue  # intra-cluster (class2.c:199)
                # interclrep (class2.c:99-124): convert to edge
                # between rank leaders via leader_of
                lt = _leader_of(n)
                lh = _leader_of(h)
                if lt != lh:
                    pair_key = (lt, lh)
                    if pair_key not in seen_heads:
                        seen_heads.add(pair_key)
                        _fg_fast_edge(lt, lh)
                continue

            # class2.c:251: regular edge → make_chain/fast_edge
            if h not in seen_heads:
                seen_heads.add(h)
                _fg_fast_edge(n, h)

        # Virtual/skeleton edges from this node (interclrep chains,
        # edge-split virtual edges)
        for le in node_virt_edges.get(n, []):
            h = le.head_name
            if h not in bfs_nodes or h == n:
                continue

            t_ch = node_child.get(n) or skel_to_child.get(n)
            h_ch = node_child.get(h) or skel_to_child.get(h)

            if t_ch or h_ch:
                if t_ch and h_ch and t_ch == h_ch:
                    continue  # intra-cluster
                lt = _leader_of(n)
                lh = _leader_of(h)
                if lt != lh:
                    pair_key = (lt, lh)
                    if pair_key not in seen_heads:
                        seen_heads.add(pair_key)
                        _fg_fast_edge(lt, lh)
                continue

            if h not in seen_heads:
                seen_heads.add(h)
                _fg_fast_edge(n, h)

    # ── Step 2: build_ranks uses GD_nlist directly ──────
    # expand_cluster (cluster.c:280-296) calls class2 then
    # build_ranks.  build_ranks (mincross.c:1270,1292-1298)
    # iterates GD_nlist(g) — the fast graph nlist built by
    # class2's fast_node (prepend) calls.  It does NOT call
    # decompose.  The nlist IS the traversal order.
    #
    # fast_node prepends, so fg_nlist[0] = last node added.
    # walkbackwards (mincross.c:1288): walk from END of nlist
    # toward front = reversed(fg_nlist).

    # ── Step 3: build_ranks BFS (mincross.c:1265-1339) ──
    # Walk GD_nlist backward (mincross.c:1288-1298 walkbackwards).
    # Source = node with ND_in(n).list[0] == NULL (pass=0).
    sources = []
    for n in reversed(fg_nlist):
        if fg_in.get(n):
            continue  # has incoming — not a source
        if (n in layout.lnodes and layout.lnodes[n].virtual
                and not n.startswith("_skel_")):
            continue  # _v_* virtual node — skip
        sources.append(n)

    # BFS from sources (mincross.c:1302-1320)
    result: dict[int, list[str]] = defaultdict(list)
    visited: set[str] = set()
    installed_children: set[str] = set()
    _bfs_trace = len(bfs_nodes) > 20

    if _bfs_trace:
        skel_nlist = [n for n in fg_nlist if n.startswith("_skel_")]
        trace("bfs", f"fg_nlist (skeletons): {skel_nlist}")
    _bfs_trace = len(bfs_nodes) > 20

    if _bfs_trace:
        trace("bfs", f"sources: {sources}")

    queue: deque[str] = deque()
    for s in sources:
        if s in visited:
            continue
        visited.add(s)
        queue.append(s)
        while queue:
            n0 = queue.popleft()
            if n0 in child_skel_set:
                # CLUSTER node → install_cluster (cluster.c:393-407)
                child_name = skel_to_child.get(n0, "")
                if child_name and child_name not in installed_children:
                    installed_children.add(child_name)
                    if _bfs_trace:
                        trace("bfs", f"install_cluster {child_name}")
                    rleaders = child_skel_ranks[child_name]
                    # install all rank leaders (cluster.c:399-404)
                    for r in sorted(rleaders.keys()):
                        result[r].append(rleaders[r])
                    # enqueue neighbors (cluster.c:405-406)
                    for sn in rleaders.values():
                        for nbr in fg_out.get(sn, []):
                            if nbr not in visited:
                                visited.add(nbr)
                                queue.append(nbr)
                                if _bfs_trace:
                                    nbr_cl = skel_to_child.get(nbr, "")
                                    trace("bfs", f"  enqueue {nbr} (cl={nbr_cl}) from {sn} of {child_name}")
            else:
                # Regular node → install_in_rank (mincross.c:1308)
                result[layout.lnodes[n0].rank].append(n0)
                if _bfs_trace:
                    trace("bfs", f"install {n0} rank={layout.lnodes[n0].rank}")
                # enqueue_neighbors (mincross.c:1341-1351)
                for nbr in fg_out.get(n0, []):
                    if nbr not in visited:
                        visited.add(nbr)
                        queue.append(nbr)

    # Handle unreached nodes (disconnected components).
    for n in sorted(bfs_nodes):
        if n in visited:
            continue
        if n in child_skel_set:
            child_name = skel_to_child.get(n, "")
            if child_name and child_name not in installed_children:
                installed_children.add(child_name)
                for r in sorted(child_skel_ranks[child_name].keys()):
                    result[r].append(child_skel_ranks[child_name][r])
        elif n in layout.lnodes:
            result[layout.lnodes[n].rank].append(n)

    # Note: C build_ranks (mincross.c:1326-1332) reverses each rank
    # when GD_flip is set.  However, the C expand_cluster trace
    # shows the POST-build_ranks order which includes this reversal.
    # Our comparison target IS the post-reversal order, so we apply
    # the reversal here to match.
    # TODO: verify whether GD_flip applies to cluster subgraphs
    # if layout.rankdir in ("LR", "RL"):
    #     for r in result:
    #         result[r].reverse()

    return result, fg_out, fg_in


def order_by_weighted_median(layout, rank: int, adj_rank: int):
    nodes = layout.ranks.get(rank, [])
    if not nodes:
        return
    adj_set = set(layout.ranks.get(adj_rank, []))
    node_set = set(nodes)
    lnodes = layout.lnodes

    # Pre-compute each node's adj-rank neighbour list with weight, in one
    # pass over ``layout.ledges``.  Replaces the prior O(N·E) per-rank
    # scan — same precompute pattern shipped for ``transpose_rank`` in
    # commit 7dd6c1b; this sibling was missed.  On 2343.dot this was
    # 100 s / 13680 calls of own time; the rest of the function is
    # cheap per-node median arithmetic that the precompute serves.
    neighbours: dict[str, list[tuple[str, int]]] = {n: [] for n in nodes}
    for le in layout.ledges:
        tname, hname, w = le.tail_name, le.head_name, le.weight
        if tname in node_set and hname in adj_set:
            neighbours[tname].append((hname, w))
        if hname in node_set and tname in adj_set:
            neighbours[hname].append((tname, w))

    medians: dict[str, float] = {}
    for name in nodes:
        positions: list[int] = []
        for neighbour, w in neighbours[name]:
            pos = lnodes[neighbour].order
            if w <= 1:
                positions.append(pos)
            else:
                positions.extend([pos] * w)
        if positions:
            positions.sort()
            m = len(positions)
            if m % 2 == 1:
                medians[name] = positions[m // 2]
            else:
                medians[name] = (positions[m // 2 - 1] + positions[m // 2]) / 2.0
        else:
            medians[name] = lnodes[name].order

    # [TRACE d5_step] — emit pre-reorder rank snapshot matching C's
    # reorder_enter format so Py-vs-C diff works at the
    # skeleton mincross layer too.  This is the path taken by
    # run_mincross (which drives skeleton_mincross) — distinct from
    # cluster_reorder which is invoked by remincross_full + per-
    # cluster expand.
    from gvpy.engines.layout.dot.trace import trace as _trace, trace_on as _on
    _trace_enabled = _on("d5_step")
    if _trace_enabled:
        _ns = " ".join(
            f"{nm}:{i}:{medians.get(nm, -1):.2f}" for i, nm in enumerate(nodes))
        _trace("d5_step",
               f"reorder_enter rank={rank} reverse=0 rmx=0 nodes=[{_ns}]")

    if layout._node_to_cluster:
        # Group-aware sort: sort within contiguous cluster runs
        # but never interleave nodes from different clusters.
        # Mirrors Graphviz reorder() which respects left2right.
        groups: list[tuple[str | None, list[str]]] = []
        for name in nodes:
            cl = layout._node_to_cluster.get(name)
            if groups and groups[-1][0] == cl:
                groups[-1][1].append(name)
            else:
                groups.append((cl, [name]))
        result: list[str] = []
        for _, group_nodes in groups:
            group_nodes.sort(key=lambda n: medians[n])
            result.extend(group_nodes)
        nodes[:] = result
    else:
        nodes.sort(key=lambda n: medians[n])
    for i, name in enumerate(nodes):
        lnodes[name].order = i
    layout.ranks[rank] = nodes

    if _trace_enabled:
        _ns = " ".join(
            f"{nm}:{i}:{medians.get(nm, -1):.2f}" for i, nm in enumerate(nodes))
        _trace("d5_step",
               f"reorder_exit rank={rank} nodes=[{_ns}]")


def transpose_rank(layout, rank: int):
    nodes = layout.ranks.get(rank, [])
    if len(nodes) < 2:
        return
    has_clusters = bool(layout._clusters)

    # Pre-compute adjacent-rank neighbor orders for every node in this
    # rank.  Used to be one O(E) scan of ``layout.ledges`` per
    # :func:`count_crossings_for_pair` call — with N nodes and W
    # while-loop iterations that's O(N·W·E), which is what made 2343.dot
    # phase-2 sit at 55 s on the 172-node subset.  The swap loop only
    # reorders nodes WITHIN this rank, so neighbor orders on adjacent
    # ranks are invariant — precompute once per ``transpose_rank`` call.
    node_set = set(nodes)
    r_above = rank - 1
    r_below = rank + 1
    lnodes = layout.lnodes
    above: dict[str, list[int]] = {n: [] for n in nodes}
    below: dict[str, list[int]] = {n: [] for n in nodes}
    for le in layout.ledges:
        tname, hname = le.tail_name, le.head_name
        if tname in node_set:
            h_ln = lnodes.get(hname)
            if h_ln is not None:
                if h_ln.rank == r_above:
                    above[tname].append(h_ln.order)
                elif h_ln.rank == r_below:
                    below[tname].append(h_ln.order)
        if hname in node_set:
            t_ln = lnodes.get(tname)
            if t_ln is not None:
                if t_ln.rank == r_above:
                    above[hname].append(t_ln.order)
                elif t_ln.rank == r_below:
                    below[hname].append(t_ln.order)

    def _count(u: str, v: str) -> int:
        c = 0
        # Rank above.
        u_n, v_n = above[u], above[v]
        for un in u_n:
            for vn in v_n:
                if un > vn:
                    c += 1
        # Rank below.
        u_n, v_n = below[u], below[v]
        for un in u_n:
            for vn in v_n:
                if un > vn:
                    c += 1
        return c

    improved = True
    while improved:
        improved = False
        for i in range(len(nodes) - 1):
            # Block swaps between nodes of different clusters
            # (Graphviz mincross.c left2right).
            if has_clusters and layout._left2right(nodes[i], nodes[i + 1]):
                continue
            c_before = _count(nodes[i], nodes[i + 1])
            c_after = _count(nodes[i + 1], nodes[i])
            if c_after < c_before:
                nodes[i], nodes[i + 1] = nodes[i + 1], nodes[i]
                lnodes[nodes[i]].order = i
                lnodes[nodes[i + 1]].order = i + 1
                improved = True


def count_crossings_for_pair(layout, u: str, v: str) -> int:
    """Count crossings on edges incident to u and v.

    See: /lib/dotgen/mincross.c @ 634

    Counts edges that go to the rank above and below ``u``/``v`` and
    tallies pairwise crossings between them.  :func:`transpose_rank`
    now precomputes a rank-local adjacency cache and calls a closure
    over it instead of this function — this public variant is kept for
    any external caller that holds a single-pair question and doesn't
    amortise a per-rank cache.  O(E) per call.
    """
    u_rank = layout.lnodes[u].rank
    crossings = 0
    for adj_rank in (u_rank - 1, u_rank + 1):
        if adj_rank not in layout.ranks:
            continue
        u_neighbors = []
        v_neighbors = []
        for le in layout.ledges:
            h_ln = layout.lnodes.get(le.head_name)
            t_ln = layout.lnodes.get(le.tail_name)
            if le.tail_name == u and h_ln and h_ln.rank == adj_rank:
                u_neighbors.append(h_ln.order)
            elif le.head_name == u and t_ln and t_ln.rank == adj_rank:
                u_neighbors.append(t_ln.order)
            if le.tail_name == v and h_ln and h_ln.rank == adj_rank:
                v_neighbors.append(h_ln.order)
            elif le.head_name == v and t_ln and t_ln.rank == adj_rank:
                v_neighbors.append(t_ln.order)
        for un in u_neighbors:
            for vn in v_neighbors:
                if un > vn:
                    crossings += 1
    return crossings


def count_all_crossings(layout) -> int:
    """Total edge crossings across all rank-to-rank pairs.

    See: /lib/dotgen/mincross.c @ 1629

    Uses every edge in ``self.ledges`` rather than the cluster-scoped
    fast graph.  See :func:`count_scoped_crossings` for the
    C-equivalent that emulates ``ND_out``-based counting used inside
    the cluster mincross loop.
    """
    total = 0
    max_rank = max(layout.ranks.keys()) if layout.ranks else 0
    for r in range(max_rank):
        if r not in layout.ranks or r + 1 not in layout.ranks:
            continue
        upper_set = set(layout.ranks[r])
        lower_set = set(layout.ranks[r + 1])
        edges_between = []
        for le in layout.ledges:
            if le.tail_name in upper_set and le.head_name in lower_set:
                edges_between.append((layout.lnodes[le.tail_name].order,
                                      layout.lnodes[le.head_name].order))
            elif le.head_name in upper_set and le.tail_name in lower_set:
                edges_between.append((layout.lnodes[le.head_name].order,
                                      layout.lnodes[le.tail_name].order))
        for i in range(len(edges_between)):
            for j in range(i + 1, len(edges_between)):
                o1_t, o1_h = edges_between[i]
                o2_t, o2_h = edges_between[j]
                if (o1_t - o2_t) * (o1_h - o2_h) < 0:
                    total += 1
    return total


def count_scoped_crossings(layout, fg_out: dict[str, list[str]],
                             min_r: int, max_r: int) -> int:
    """Count crossings using only edges in the given fast graph.

    Mirrors C mincross.c:1617-1632 ncross() which iterates
    ND_out(n) — the subgraph's scoped edge list.  At cluster
    mincross time, this excludes intra-child-cluster edges
    (class2.c:199) so reorderings at the parent cluster level
    are judged only by inter-child crossings.
    """
    total = 0
    for r in range(min_r, max_r):
        if r not in layout.ranks or r + 1 not in layout.ranks:
            continue
        upper_set = set(layout.ranks[r])
        lower_set = set(layout.ranks[r + 1])
        edges_between = []
        for t in layout.ranks[r]:
            for h in fg_out.get(t, []):
                if h in lower_set:
                    edges_between.append((layout.lnodes[t].order,
                                          layout.lnodes[h].order))
        for t in layout.ranks[r + 1]:
            for h in fg_out.get(t, []):
                if h in upper_set:
                    edges_between.append((layout.lnodes[h].order,
                                          layout.lnodes[t].order))
        for i in range(len(edges_between)):
            for j in range(i + 1, len(edges_between)):
                o1_t, o1_h = edges_between[i]
                o2_t, o2_h = edges_between[j]
                if (o1_t - o2_t) * (o1_h - o2_h) < 0:
                    total += 1
    return total


def save_ordering(layout) -> dict[str, int]:
    """Snapshot the current ``ND_order`` of every node.

    See: /lib/dotgen/mincross.c @ 836

    Captures the best ordering seen so far in the iteration loop so
    we can revert if a later pass makes things worse.
    """
    return {name: ln.order for name, ln in layout.lnodes.items()}


def restore_ordering(layout, ordering: dict[str, int]):
    """Restore a previously-saved snapshot of ``ND_order``.

    See: /lib/dotgen/mincross.c @ 818

    Sets the order field on every node from the snapshot, then
    re-sorts each rank list to match the new order and re-assigns
    sequential indices to keep ``ND_order`` consistent with the rank
    list position.
    """
    for name, order in ordering.items():
        layout.lnodes[name].order = order
    for rank_val in layout.ranks:
        layout.ranks[rank_val].sort(key=lambda n: layout.lnodes[n].order)
        for i, name in enumerate(layout.ranks[rank_val]):
            layout.lnodes[name].order = i


def flat_reorder(layout):
    """Enforce left-to-right ordering for flat (same-rank) edges.

    For each rank, flat edges with weight > 0 establish an ordering
    constraint: tail must be left of head.  This is implemented as
    a topological sort on the flat-edge graph within each rank.
    Mirrors Graphviz ``mincross.c:flat_reorder()``.
    """
    # Collect flat edges per rank
    flat_by_rank: dict[int, list[tuple[str, str]]] = {}
    for le in layout.ledges:
        if le.virtual:
            continue
        t = layout.lnodes.get(le.tail_name)
        h = layout.lnodes.get(le.head_name)
        if t and h and t.rank == h.rank and le.weight > 0:
            flat_by_rank.setdefault(t.rank, []).append(
                (le.tail_name, le.head_name))

    for rank_val, flat_edges in flat_by_rank.items():
        rank_nodes = layout.ranks.get(rank_val)
        if not rank_nodes or len(rank_nodes) < 2:
            continue

        # Build adjacency for topological sort
        in_degree: dict[str, int] = {}
        adj: dict[str, list[str]] = {}
        rank_set = set(rank_nodes)
        for t, h in flat_edges:
            if t not in rank_set or h not in rank_set:
                continue
            adj.setdefault(t, []).append(h)
            in_degree[h] = in_degree.get(h, 0) + 1
            in_degree.setdefault(t, in_degree.get(t, 0))

        # Nodes with flat-edge constraints
        constrained = set(in_degree.keys())
        if not constrained:
            continue

        # Topological sort (Kahn's algorithm) on constrained nodes
        queue = [n for n in rank_nodes if n in constrained
                 and in_degree.get(n, 0) == 0]
        topo_order: list[str] = []
        while queue:
            u = queue.pop(0)
            topo_order.append(u)
            for v in adj.get(u, []):
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(topo_order) != len(constrained):
            # Cycle in flat edges — skip (cycle should have been
            # broken by _break_cycles, but flat edges may create new
            # cycles if they were added after cycle breaking)
            continue

        # Merge: constrained nodes in topo order, unconstrained keep
        # their relative positions
        unconstrained = [n for n in rank_nodes if n not in constrained]
        # Interleave: place constrained nodes at their original
        # positions, preserving unconstrained order
        new_order: list[str] = []
        ci = 0  # index into topo_order
        for n in rank_nodes:
            if n in constrained:
                new_order.append(topo_order[ci])
                ci += 1
            else:
                new_order.append(n)

        for i, name in enumerate(new_order):
            layout.lnodes[name].order = i
        layout.ranks[rank_val] = new_order


def mark_low_clusters(layout):
    """Label every node with its innermost cluster.

    See: /lib/dotgen/cluster.c @ 433

    Largest clusters are processed first so that smaller (more
    deeply nested) clusters overwrite, leaving each node mapped to
    its innermost containing cluster.  Used by ReMincross to enforce
    cluster boundaries during the final remincross pass.
    """
    # ``_node_to_cluster`` is declared on DotGraphInfo.__init__;
    # clear here to drop any stale mapping from a prior layout run.
    layout._node_to_cluster.clear()
    if not layout._clusters:
        return
    for cl in sorted(layout._clusters,
                     key=lambda c: len(c.nodes), reverse=True):
        for n in cl.nodes:
            if n in layout.lnodes:
                layout._node_to_cluster[n] = cl.name


def mval_edge(layout, node_name: str, port_name: str) -> int:
    """VAL(node, port) with port.order from Node.record_fields.

    Matches C mincross.c:1685 VAL() + sameport.c:151-152:
      port.order = MC_SCALE * (lw + port.x) / (lw + rw)

    The port fraction comes from Node.record_fields (parsed at
    DOT load time, sized by RecordField.compute_size/positions).
    Node is the single source of truth for port geometry.
    """
    if node_name not in layout.lnodes:
        return 0
    ln = layout.lnodes[node_name]
    order = ln.order

    if not port_name:
        # C: edges without explicit ports have ED_port.order = 0
        # (the port struct is zero-initialized).  Only edges that
        # go through resolvePort/sameport get nonzero port.order.
        # C shapes.c:2865 sets pp->order = MC_SCALE/2 for
        # NORMAL shapes, but virtual/skeleton edges keep 0.
        return layout._MC_SCALE * order

    cache_key = (node_name, port_name)
    if cache_key in layout._port_order_cache:
        return layout._MC_SCALE * order + layout._port_order_cache[cache_key]

    # Look up port fraction from Node.record_fields (parsed at DOT
    # load, sized at layout start).  For HTML-label nodes fall back
    # to the parsed HtmlTable's cell-centre → fraction computation.
    port_order = layout._MC_SCALE // 2  # default center
    if ln.node and ln.node.record_fields is not None:
        frac = ln.node.record_fields.port_fraction(
            port_name, rankdir=layout._rankdir_int())
        if frac is not None:
            port_order = int(frac * layout._MC_SCALE)
    elif ln.node and getattr(ln.node, "html_table", None) is not None:
        from gvpy.grammar.html_label import html_port_fraction
        frac = html_port_fraction(
            ln.node.html_table, port_name,
            rankdir=layout._rankdir_int(),
        )
        if frac is not None:
            port_order = int(frac * layout._MC_SCALE)

    layout._port_order_cache[cache_key] = port_order
    return layout._MC_SCALE * order + port_order

