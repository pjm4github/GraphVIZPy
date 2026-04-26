"""Phase 1: rank assignment.

See: /lib/dotgen/rank.c @ 545

Given a directed graph, assign each node an integer rank such that
every edge goes from a lower-rank node to a higher-rank one, and the
total weighted edge length (sum of ``minlen * weight`` over edges)
is minimized.

Pipeline
--------
The entry point :func:`phase1_rank` runs this sequence (matching
C ``dot_rank``/``dot2_rank`` in ``rank.c``):

1. :func:`break_cycles`         — DFS-based cycle removal
   (C ``rank.c:break_cycles``).  Reverses back edges so the
   constraint graph becomes a DAG.

2. :func:`classify_edges`       — tag edges as tree/cross/back/forward
   based on the DFS ordering.  Mirrors C's edge classification used
   by the NS ranker.

3. :func:`inject_same_rank_edges` — converts ``rank=same`` subgraph
   constraints into zero-length high-weight edges that the network
   simplex solver enforces natively (C ``collapse_sets``).

4. **Network simplex ranking**:
   - :func:`cluster_aware_rank` when the graph has clusters — builds
     a per-cluster + root NS problem that respects cluster
     containment constraints.
   - :func:`network_simplex_rank` for the flat (no-cluster) path.

5. :func:`apply_rank_constraints` — enforces ``rank=min/max/source/
   sink`` hard constraints post-NS.

6. :func:`compact_ranks` — shifts ranks down so the minimum rank is
   zero (C ``compact_rankset``).

7. :func:`add_virtual_nodes`    — for any edge spanning multiple
   ranks, insert virtual nodes at intermediate ranks (C virtual node
   chains) so Phase 2 mincross operates on rank-adjacent edges only.

8. :func:`build_ranks`          — initial rank-to-nodelist assembly.

9. :func:`classify_flat_edges` — identify same-rank edges and mark
   them for the flat-edge routing path in Phase 4.

Extracted functions
-------------------
All 11 Phase 1 methods moved from ``DotGraphInfo`` in ``dot_layout.py``
as free functions taking ``layout`` as the first argument.  See the
session's ``TODO_core_refactor.md`` for the full migration plan.

Related modules
---------------
- :mod:`gvpy.engines.layout.dot.mincross` — Phase 2, consumes ``layout.ranks``
  and reorders nodes within each rank.
- :mod:`gvpy.engines.layout.dot.position` — Phase 3 coordinate assignment.
- :mod:`gvpy.engines.layout.dot.dotsplines`  — Phase 4 edge routing.
- :mod:`gvpy.engines.layout.dot.dot_layout` — holds ``DotGraphInfo`` (state
  container), Phase 1 init helpers (``_collect_edges``,
  ``_collect_clusters``, ``_dedup_cluster_nodes``), cluster geometry,
  compound-edge handling, and the data types (``LayoutNode``,
  ``LayoutEdge``, ``LayoutCluster``, ``_NetworkSimplex``).
"""
from __future__ import annotations

import sys
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from gvpy.engines.layout.dot.trace import trace

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import DotGraphInfo


def phase1_rank(layout):
    trace("rank", f"phase1 begin: newrank={layout.newrank} clusterrank={layout.clusterrank}")
    layout._break_cycles()
    reversed_count = sum(1 for le in layout.ledges if le.reversed)
    trace("rank", f"break_cycles: reversed={reversed_count}")
    layout._classify_edges()
    # Inject rank=same constraints as zero-length high-weight edges
    # BEFORE running NS so the solver respects them natively
    # (matching Graphviz collapse_sets).
    layout._inject_same_rank_edges()
    if layout.newrank or layout.clusterrank == "none":
        layout._network_simplex_rank()
    else:
        layout._cluster_aware_rank()
    # Log rank assignments for all real (non-virtual) nodes
    for name in sorted(layout.lnodes.keys()):
        ln = layout.lnodes[name]
        if not ln.virtual:
            trace("rank", f"node_rank: {name} rank={ln.rank}")
    layout._apply_rank_constraints()
    layout._compact_ranks()
    max_rank = max((ln.rank for ln in layout.lnodes.values()), default=0)
    trace("rank", f"after compact: max_rank={max_rank}")
    layout._add_virtual_nodes()
    vcount = sum(1 for ln in layout.lnodes.values() if ln.virtual)
    trace("rank", f"virtual_nodes: {vcount}")
    layout._build_ranks()
    layout._classify_flat_edges()
    trace("rank", f"phase1 done: ranks={sorted(layout.ranks.keys())} nodes_per_rank={[(r, len(layout.ranks[r])) for r in sorted(layout.ranks.keys())]}")


def break_cycles(layout):
    """Reverse back-edges so the constraint graph becomes a DAG.

    See: /lib/dotgen/rank.c @ 944

    Standard DFS with three-state colouring (UNVISITED/IN_PROGRESS/
    DONE).  Any edge that points to an IN_PROGRESS node is a back
    edge — flip its tail/head and mark ``le.reversed = True``.
    """
    UNVISITED, IN_PROGRESS, DONE = 0, 1, 2
    state = {n: UNVISITED for n in layout.lnodes}

    def dfs(u):
        state[u] = IN_PROGRESS
        for le in layout.ledges:
            if le.tail_name != u:
                continue
            v = le.head_name
            if state[v] == IN_PROGRESS:
                le.reversed = True
                le.tail_name, le.head_name = le.head_name, le.tail_name
            elif state[v] == UNVISITED:
                dfs(v)
        state[u] = DONE

    for n in layout.lnodes:
        if state[n] == UNVISITED:
            dfs(n)


def classify_edges(layout):
    """Classify edges by type for downstream processing.

    Sets ``le.edge_type`` on each LayoutEdge to one of:
    - ``'normal'`` — standard cross-rank edge
    - ``'flat'`` — same-rank edge (detected after ranking)
    - ``'reversed'`` — edge reversed by cycle breaking
    - ``'layout'`` — layout-loop

    This runs before ranking so types are preliminary; flat edges
    can only be fully detected after ranks are assigned.  A second
    pass runs after ranking to finalize flat-edge classification.

    Mirrors Graphviz ``class1.c:class1()`` (pre-rank) and
    ``class2.c:class2()`` (post-rank) classification.
    """
    for le in layout.ledges:
        if le.virtual:
            le.edge_type = "virtual"
        elif le.tail_name == le.head_name:
            le.edge_type = "self"
        elif le.reversed:
            le.edge_type = "reversed"
        else:
            le.edge_type = "normal"


def classify_flat_edges(layout):
    """Post-ranking pass: mark same-rank edges as flat.

    See: /lib/dotgen/class2.c @ 155

    After rank assignment, edges where both endpoints sit at the same
    rank are flagged so Phase 2 mincross treats them via the flat-edge
    sub-pipeline rather than the cross-rank median heuristic.
    """
    for le in layout.ledges:
        if le.virtual:
            continue
        t = layout.lnodes.get(le.tail_name)
        h = layout.lnodes.get(le.head_name)
        if t and h and t.rank == h.rank:
            le.edge_type = "flat"


def inject_same_rank_edges(layout):
    """Add zero-length high-weight edges between rank=same nodes.

    This ensures the network simplex solver assigns them the same rank
    rather than relying on a post-hoc fixup that can violate other
    edge constraints.  Mirrors Graphviz ``rank.c:collapse_sets()``.
    """
    # Lazy import — LayoutEdge class lives in dot_layout.py; rank.py
    # cannot import it at module level (circular: dot_layout imports
    # this module via the delegating wrappers).
    from gvpy.engines.layout.dot.dot_layout import LayoutEdge
    for kind, node_names in layout._rank_constraints:
        if kind != "same" or len(node_names) < 2:
            continue
        # Chain consecutive pairs with bidirectional zero-length edges
        for i in range(len(node_names) - 1):
            a, b = node_names[i], node_names[i + 1]
            if a not in layout.lnodes or b not in layout.lnodes:
                continue
            # Forward: a → b, minlen=0, weight=1000
            layout.ledges.append(LayoutEdge(
                edge=None, tail_name=a, head_name=b,
                minlen=0, weight=1000, virtual=True,
                constraint=True,
            ))
            # Backward: b → a, minlen=0, weight=1000
            layout.ledges.append(LayoutEdge(
                edge=None, tail_name=b, head_name=a,
                minlen=0, weight=1000, virtual=True,
                constraint=True,
            ))


def network_simplex_rank(layout):
    """Assign ranks via network simplex on the constraint graph.

    See: /lib/dotgen/rank.c @ 449

    The flat (no-cluster) path: build edge weights with the
    ``group`` attribute boost (×100, capped at 1000), call NS,
    write the ranks back to ``ND_rank``.
    """
    # _NetworkSimplex now lives in ns_solver.py — direct import is
    # cheaper than the dot_layout.py re-export and avoids any
    # remaining import-cycle risk.
    from gvpy.engines.layout.dot.ns_solver import _NetworkSimplex
    if not layout.lnodes:
        return
    # Build node group map for weight boosting
    node_groups: dict[str, str] = {}
    for name, ln in layout.lnodes.items():
        if ln.node:
            grp = ln.node.attributes.get("group", "")
            if grp:
                node_groups[name] = grp

    # Only edges with constraint=True affect ranking
    # Boost weight ×100 for edges connecting nodes in the same group
    ns_edges = []
    for le in layout.ledges:
        if not le.constraint:
            continue
        w = le.weight
        t_grp = node_groups.get(le.tail_name, "")
        h_grp = node_groups.get(le.head_name, "")
        if t_grp and t_grp == h_grp:
            w = min(w * 100, 1000)
        ns_edges.append((le.tail_name, le.head_name, le.minlen, w))
    ns = _NetworkSimplex(list(layout.lnodes.keys()), ns_edges)
    ns.SEARCH_LIMIT = layout.searchsize
    ranks = ns.solve(max_iter=layout.nslimit1)
    for name, r in ranks.items():
        if name in layout.lnodes:
            layout.lnodes[name].rank = r


def cluster_aware_rank(layout):
    """Rank nodes using recursive bottom-up cluster ranking.

    Mirrors Graphviz ``rank.c:dot1_rank()`` which recursively ranks
    each cluster bottom-up via ``collapse_sets()`` → ``collapse_cluster()``
    → ``dot1_rank(child)``.  Each cluster is ranked independently
    starting from the deepest leaves of the cluster tree, then the
    parent graph is ranked with cluster-internal edges replaced by
    min-length constraints between cluster boundary nodes.
    """
    # _NetworkSimplex from its own ns_solver module; LayoutCluster
    # still lives in dot_layout.py (circular import for that one).
    from gvpy.engines.layout.dot.ns_solver import _NetworkSimplex
    from gvpy.engines.layout.dot.dot_layout import LayoutCluster
    if not layout._clusters:
        layout._network_simplex_rank()
        return

    # Build cluster hierarchy from the Graph's subgraph tree
    # so we can walk it bottom-up like the C code does.
    cl_by_name: dict[str, "LayoutCluster"] = {
        cl.name: cl for cl in layout._clusters
    }
    cl_node_sets: dict[str, set[str]] = {
        cl.name: set(cl.nodes) for cl in layout._clusters
    }

    # Determine parent-child relationships among clusters:
    # A cluster P is parent of C if C.nodes ⊂ P.nodes and P is the
    # smallest such containing cluster.
    children_of: dict[str | None, list[str]] = {None: []}
    for cl in layout._clusters:
        children_of[cl.name] = []
    parent_of: dict[str, str | None] = {}
    for cl in layout._clusters:
        best_parent: str | None = None
        best_size = float("inf")
        for other in layout._clusters:
            if other.name == cl.name:
                continue
            if cl_node_sets[cl.name] < cl_node_sets[other.name]:
                if len(cl_node_sets[other.name]) < best_size:
                    best_parent = other.name
                    best_size = len(cl_node_sets[other.name])
        parent_of[cl.name] = best_parent
        children_of.setdefault(best_parent, []).append(cl.name)

    # Track which nodes have been ranked by a cluster pass
    ranked_nodes: set[str] = set()

    # ── Recursive bottom-up ranking (mirrors dot1_rank) ─────────
    def _dot1_rank_cluster(cl_name: str):
        """Rank a single cluster bottom-up: children first, then layout.

        This mirrors the C code path:
          dot1_rank(g) → collapse_sets(g) → for each child cluster:
            collapse_cluster(g, child) → dot1_rank(child)
          then: class1 → decompose → acyclic → rank1 → expand_ranksets
        """
        # 1. Recursively rank all child clusters first (bottom-up)
        for child_name in children_of.get(cl_name, []):
            _dot1_rank_cluster(child_name)

        cl = cl_by_name[cl_name]
        cl_members = cl_node_sets[cl_name]

        # 2. Collect edges internal to this cluster that involve
        #    nodes NOT already locked by a child cluster ranking.
        #    For nodes ranked by children, we keep their relative
        #    ranks fixed and add constraint edges to anchor them.
        child_ranked = ranked_nodes & cl_members
        unranked = cl_members - ranked_nodes

        # All internal edges (both endpoints in this cluster)
        cl_edges: list[tuple[str, str, int, int]] = []
        for le in layout.ledges:
            if not le.constraint:
                continue
            if le.tail_name in cl_members and le.head_name in cl_members:
                cl_edges.append((
                    le.tail_name, le.head_name, le.minlen, le.weight,
                ))

        # If child clusters have already been ranked, anchor their
        # nodes with high-weight edges so NS preserves their relative
        # ranks while positioning them within the parent cluster.
        anchor_edges: list[tuple[str, str, int, int]] = []
        for child_name in children_of.get(cl_name, []):
            child_nodes_sorted = sorted(
                (n for n in cl_by_name[child_name].nodes
                 if n in layout.lnodes and n in ranked_nodes),
                key=lambda n: layout.lnodes[n].rank,
            )
            for i in range(len(child_nodes_sorted) - 1):
                a, b = child_nodes_sorted[i], child_nodes_sorted[i + 1]
                span = layout.lnodes[b].rank - layout.lnodes[a].rank
                if span >= 1:
                    anchor_edges.append((a, b, span, 1000))

        all_edges = cl_edges + anchor_edges
        all_nodes = sorted(cl_members)

        if not all_nodes:
            return

        # 3. Run network simplex on this cluster
        ns = _NetworkSimplex(all_nodes, all_edges)
        ns.SEARCH_LIMIT = layout.searchsize
        ranks = ns.solve(max_iter=layout.nslimit1)

        # 4. Apply ranks to nodes
        for n, r in ranks.items():
            if n in layout.lnodes:
                layout.lnodes[n].rank = r

        # 5. Mark all nodes in this cluster as ranked
        ranked_nodes.update(cl_members)

    # ── Walk the cluster tree: rank leaf clusters first ─────────
    # Process top-level clusters (those with no parent cluster).
    # Each one recursively processes its children first.
    top_level = children_of.get(None, [])
    for cl_name in top_level:
        _dot1_rank_cluster(cl_name)

    # ── UF_union collapse → global NS → expand ──────────
    # Mirrors C rank.c: cluster_leader() collapses each top-level
    # cluster to a single leader via UF_union.  class1/interclust1
    # converts inter-cluster edges using the "slack node + 2 edges"
    # pattern with offset-adjusted minlens.  rank1() runs global NS.
    # expand_ranksets() maps: rank(n) += rank(UF_find(n)).

    # 1. Build UF_find map: every node in a top-level cluster
    #    maps to that cluster's leader (min-rank node).
    top_clusters = children_of.get(None, [])
    uf_find: dict[str, str] = {}         # node → leader
    local_offset: dict[str, int] = {}    # node → rank offset from leader

    for cl_name in top_clusters:
        cl = cl_by_name[cl_name]
        members = [n for n in cl.nodes
                   if n in layout.lnodes and n in ranked_nodes]
        if not members:
            continue
        members.sort(key=lambda n: layout.lnodes[n].rank)
        leader = members[0]
        min_rank = layout.lnodes[leader].rank
        for n in members:
            uf_find[n] = leader
            local_offset[n] = layout.lnodes[n].rank - min_rank

    # 2. Build global NS graph.
    #    - Non-cluster nodes and leaders appear as themselves.
    #    - Intra-cluster edges (both endpoints → same leader) are skipped.
    #    - Inter-cluster/cross edges use interclust1 pattern:
    #      slack_node → UF_find(tail), slack_node → UF_find(head)
    #      with offset-adjusted minlens.
    _CL_BACK = 10  # C CL_BACK weight multiplier for tail side

    global_nodes: set[str] = set()
    for name in layout.lnodes:
        global_nodes.add(uf_find.get(name, name))

    global_edges: list[tuple[str, str, int, int]] = []
    _vn_ctr = [0]

    for le in layout.ledges:
        if not le.constraint:
            continue
        t, h = le.tail_name, le.head_name
        if t not in layout.lnodes or h not in layout.lnodes:
            continue

        t0 = uf_find.get(t, t)
        h0 = uf_find.get(h, h)

        if t0 == h0:
            continue  # intra-cluster

        t_in_cluster = t in uf_find
        h_in_cluster = h in uf_find

        if not t_in_cluster and not h_in_cluster:
            # Neither endpoint in a cluster — regular edge
            global_edges.append((t0, h0, le.minlen, le.weight))
        else:
            # At least one endpoint in a cluster — use interclust1
            # pattern: create slack node V with offset-adjusted edges
            t_rank = local_offset.get(t, 0)
            h_rank = local_offset.get(h, 0)
            offset = le.minlen + t_rank - h_rank
            if offset > 0:
                t_len = 0
                h_len = offset
            else:
                t_len = -offset
                h_len = 0

            _vn_ctr[0] += 1
            vn = f"_uf_v{_vn_ctr[0]}"
            global_nodes.add(vn)
            global_edges.append((vn, t0, t_len,
                                 _CL_BACK * le.weight))
            global_edges.append((vn, h0, h_len, le.weight))

    # 3. Run global NS (sorted for deterministic results —
    #    set iteration order varies with PYTHONHASHSEED)
    ns = _NetworkSimplex(sorted(global_nodes), global_edges)
    ns.SEARCH_LIMIT = layout.searchsize
    ranks = ns.solve(max_iter=layout.nslimit1)

    # 4. Re-normalize: C expand_ranksets iterates real nodes only
    #    (agfstnode), so slack nodes from interclust1 don't affect
    #    the rank floor.  Shift so min real/leader rank == 0.
    real_min = min(
        (ranks[uf_find.get(n, n)]
         for n in layout.lnodes if uf_find.get(n, n) in ranks),
        default=0)
    if real_min != 0:
        ranks = {k: v - real_min for k, v in ranks.items()}

    # 5. Expand: rank(n) = rank(UF_find(n)) + local_offset(n)
    for name in layout.lnodes:
        leader = uf_find.get(name, name)
        if leader in ranks:
            layout.lnodes[name].rank = ranks[leader] + local_offset.get(name, 0)


def apply_rank_constraints(layout):
    """Enforce rank=min/max/source/sink hard constraints post-NS.

    See: /lib/dotgen/rank.c @ 607

    We re-process the rank=same constraint here too even though it's
    also injected as
    weight=1000 edges before NS — covers the corner case where two
    same-rank nodes ended up at different ranks despite the
    constraint (rare but possible if the edges form a contradictory
    cycle).
    """
    if not layout._rank_constraints:
        return
    max_rank = max(ln.rank for ln in layout.lnodes.values()) if layout.lnodes else 0
    for kind, node_names in layout._rank_constraints:
        existing = [layout.lnodes[n] for n in node_names if n in layout.lnodes]
        if not existing:
            continue
        if kind == "same":
            target = min(ln.rank for ln in existing)
            for ln in existing:
                ln.rank = target
        elif kind in ("min", "source"):
            for ln in existing:
                ln.rank = 0
        elif kind in ("max", "sink"):
            for ln in existing:
                ln.rank = max_rank


def compact_ranks(layout):
    """Shift all ranks down so the minimum rank is zero.

    No direct C analogue — C performs this compaction inline while
    tracking ``GD_minrank`` (see ``lib/dotgen/rank.c`` @ 473).  Python
    hoists it into a dedicated helper.  After NS, the smallest rank
    may be negative or > 0; renumber so rank 0 is the topmost.
    """
    if not layout.lnodes:
        return
    min_rank = min(ln.rank for ln in layout.lnodes.values())
    if min_rank != 0:
        for ln in layout.lnodes.values():
            ln.rank -= min_rank


def add_virtual_nodes(layout):
    """Insert virtual nodes for edges spanning multiple ranks.

    See: /lib/dotgen/class2.c @ 70

    For every edge
    where ``rank(head) - rank(tail) > 1``, insert a chain of virtual
    nodes at each intermediate rank and replace the original edge
    with a sequence of rank-adjacent edges.  The chain is recorded
    in ``layout._vnode_chains`` for Phase 4 spline routing.

    Cluster inheritance (see: /lib/dotgen/cluster.c @ 332): when both
    endpoints of a split edge share a common cluster, the virtual
    nodes inherit that
    common cluster's membership so mincross orders them alongside
    the cluster's real members instead of dumping them at the end
    of each rank.  Without this, virtual nodes for intra-cluster
    long edges get ``cluster=None`` and end up at the bottom of
    their rank's cross-rank ordering, producing the catastrophic
    "edge detours to the opposite side of the canvas" pattern seen
    on ``aa1332.dot`` (c4163->c4251, c6428->c6753, etc.).
    """
    # Lazy imports — both classes live in dot_layout.py (circular).
    from gvpy.engines.layout.dot.dot_layout import LayoutNode, LayoutEdge
    layout._vnode_chains = {}
    new_edges = []
    to_remove = []

    # Build a quick lookup of clusters per node so we can find the
    # deepest common cluster of each split edge in O(clusters).  Only
    # needed when the graph has clusters.
    _node_clusters: dict[str, list[str]] = {}
    _by_name: dict[str, "object"] = {}
    if layout._clusters:
        # Map node name -> list of cluster names sorted innermost first
        # (smallest ``.nodes`` membership first).  ``cl.nodes`` is
        # transitively populated by :func:`cluster.scan_clusters` so
        # the smallest cluster containing a node IS the innermost.
        by_size = sorted(layout._clusters, key=lambda c: len(c.nodes))
        for cl in by_size:
            _by_name[cl.name] = cl
            for n in cl.nodes:
                _node_clusters.setdefault(n, []).append(cl.name)

    def _lca_ancestor_chain(tail_name: str,
                             head_name: str) -> list["object"]:
        """Return [LCA, ..., root_ancestor] clusters containing both nodes.

        The innermost common cluster comes first, followed by its
        parent clusters (which also contain both endpoints) in
        increasing size.  A virtual node for an edge between these
        endpoints must be added to **every** cluster in this chain
        so that each layer of the cluster-aware mincross
        (``skeleton_mincross``) sees the virtual inside its
        ``cl_node_set`` and can assign its ``mval`` properly —
        adding only to the LCA leaves the outer layers with a
        broken mval and the virtual still gets dropped at the end
        of the rank.
        """
        tcls = _node_clusters.get(tail_name, [])
        if not tcls:
            return []
        head_cls = set(_node_clusters.get(head_name, ()))
        result: list[object] = []
        seen_common = False
        for cname in tcls:  # innermost first
            if cname in head_cls:
                seen_common = True
            if seen_common:
                result.append(_by_name[cname])
        return result

    for i, le in enumerate(layout.ledges):
        t_rank = layout.lnodes[le.tail_name].rank
        h_rank = layout.lnodes[le.head_name].rank
        span = h_rank - t_rank
        # [TRACE rank] — matches C's trace in lib/dotgen/class2.c
        # ``make_chain``.  Gated on ``GV_TRACE=rank``.  Fires for all
        # edges (including span<=1) so missing entries indicate edges
        # absent from ``layout.ledges`` entirely, not just edges
        # C-would-chain that Python puts on adjacent ranks.
        from gvpy.engines.layout.dot.trace import trace as _trace_rank
        t_rk = layout.lnodes[le.tail_name].rank
        h_rk = layout.lnodes[le.head_name].rank
        _trace_rank("rank", f"edge={le.tail_name}->{le.head_name} "
                            f"tail_rank={t_rk} head_rank={h_rk} span={span}")
        if span <= 1:
            continue  # No virtual nodes needed
        # Historical note: commit 4bdecdb introduced an arbitrary
        # ``span > 100`` cap as a dev-time safety guard.  The cap
        # silently dropped cross-rank edges — they became 3-box
        # corridors whose polygons self-intersected, so
        # ``Pshortestpath`` failed and the edge never appeared in
        # output.  Confirmed on 2343.dot (rankdir=LR, 500+ ranks)
        # where 66 edges were silently missing.  C's ``make_chain``
        # has no cap.  Raised to 200 here as a tuned stop-gap:
        # eliminates ~80% of skip-induced failures on realistic graphs
        # while keeping virtual-node count tractable (removing the cap
        # entirely on 2343 added 12 k virtuals and ballooned mincross
        # time past the audit budget).  Proper fix is a performance
        # pass on mincross+position to handle dense virtual chains.
        if span > 200:
            continue

        # Determine the cluster chain the virtual chain should live
        # in (LCA upward through every ancestor cluster that also
        # contains both endpoints).
        cluster_chain = _lca_ancestor_chain(le.tail_name, le.head_name)

        # Size the label-bearing vnode (middle of the chain) so the
        # final spacing between the two real endpoints accommodates
        # the label with ~15 % margin on each side (total ~1.3 ×
        # label width).  The rank-axis gap at route time is
        # ``2 × ranksep + vnode_width`` (one ranksep on each side of
        # the vnode's rank box), so:
        #
        #     target_gap   = 1.3 × label_width
        #     vnode_width  = target_gap - 2 × ranksep
        #                  = 1.3 × label_width - 2 × ranksep
        #
        # For small labels the formula can go negative; clamp to a
        # small positive floor so the vnode never disappears.
        # Without this sizing a labeled edge's vnode was 2 pt × 2 pt
        # and wide labels collided with the surrounding real nodes.
        label_vnode_idx = -1  # index in the chain that carries the label
        label_w = label_h = 0.0
        edge_obj = getattr(le, "edge", None)
        edge_label = ""
        if edge_obj is not None:
            edge_label = edge_obj.attributes.get("label", "")
        if edge_label and span >= 2:
            try:
                _fs = float(edge_obj.attributes.get("fontsize", "14"))
            except (ValueError, TypeError):
                _fs = 14.0
            from gvpy.grammar.html_label import (
                is_html_label, parse_html_label, html_label_size,
            )
            if is_html_label(edge_label):
                _ast = parse_html_label(edge_label, default_font_size=_fs)
                label_w, label_h = html_label_size(_ast)
            else:
                from gvpy.engines.layout.common.text import (
                    text_width_times_roman,
                )
                _lines = edge_label.replace("\\n", "\n").split("\n")
                label_w = max(text_width_times_roman(ln, _fs) for ln in _lines)
                label_h = len(_lines) * _fs * 1.2
            # Reduce the vnode from its raw label dims to account for
            # the two ranksep gaps that already sit around it.  The
            # resulting total real-to-real gap targets ~1.3 × label_w
            # (= 15 % margin each side).
            _rs = float(getattr(layout, "ranksep", 36.0))
            label_w = max(4.0, 1.3 * label_w - 2.0 * _rs)
            label_h = max(4.0, 1.3 * label_h - 2.0 * _rs)
            # Pre-swap for LR/RL so the TB-internal pipeline sees the
            # label width on the cross-rank axis.
            if layout.rankdir in ("LR", "RL"):
                label_w, label_h = label_h, label_w
            label_vnode_idx = (span - 1) // 2  # middle vnode (0-indexed)

        # Create chain of virtual nodes
        chain = []
        prev_name = le.tail_name
        for j in range(1, span):
            vname = f"_v_{le.tail_name}_{le.head_name}_{j}"
            # Ensure unique name
            while vname in layout.lnodes:
                vname += "_"
            # Label-bearing vnodes absorb the edge label's dimensions;
            # plain bend vnodes stay at 2pt × 2pt.
            if (j - 1) == label_vnode_idx and label_w > 0:
                vn_w, vn_h = label_w, label_h
            else:
                vn_w, vn_h = 2.0, 2.0
            layout.lnodes[vname] = LayoutNode(
                name=vname, node=None, rank=t_rank + j, virtual=True,
                width=vn_w, height=vn_h,
            )
            chain.append(vname)
            # Inherit cluster membership from the edge's LCA and
            # every ancestor.  Mincross needs to see the virtual
            # inside the cl_node_set at every level of its
            # skeleton / expand traversal — adding only to the LCA
            # leaves outer-level mincross passes with mval=-1 for
            # the virtual, which lets it drift to the end of the
            # rank instead of aligning with its endpoints.
            for cl in cluster_chain:
                cl.nodes.append(vname)
            new_edges.append(LayoutEdge(
                edge=None, tail_name=prev_name, head_name=vname,
                minlen=1, weight=le.weight, virtual=True,
                orig_tail=le.tail_name, orig_head=le.head_name,
            ))
            prev_name = vname

        # Final edge to head
        new_edges.append(LayoutEdge(
            edge=None, tail_name=prev_name, head_name=le.head_name,
            minlen=1, weight=le.weight, virtual=True,
            orig_tail=le.tail_name, orig_head=le.head_name,
        ))

        layout._vnode_chains[(le.tail_name, le.head_name)] = chain
        to_remove.append(i)

    # Move original long edges to _chain_edges, add virtual edges to ledges
    for idx in sorted(to_remove, reverse=True):
        layout._chain_edges.append(layout.ledges.pop(idx))
    layout.ledges.extend(new_edges)


def build_ranks(layout):
    """Populate ``layout.ranks`` with an initial in-rank ordering.

    Mirrors Graphviz ``lib/dotgen/mincross.c: build_ranks()``: BFS
    from every source node (no in-edges), walking only OUT-edges, so
    each rank's order is determined by a breadth-first wavefront
    rather than a depth-first plunge.  Gated on
    ``GVPY_LEGACY_BUILD_RANKS=1`` — set that to restore the previous
    DFS-over-undirected-adjacency behaviour for diagnostics.

    Why this matters: the legacy DFS interleaves invis-chain virtuals
    with cluster members on the same rank (because it walks from
    root all the way to a leaf before backtracking).  C's BFS pulls
    all sources' rank-1 children into the rank first, then their
    rank-2 children, keeping cluster members contiguous at their
    rank and matching the starting configuration C's mincross expects.
    On ``d5_regression.dot`` the switch changes rank-2 initial order
    from ``[_v_*_2, _v_*_2, B_in, A_r1, A_l1, ...]`` to
    ``[A_l1, A_l2, A_r1, A_r2, B_in, ...]`` — cluster blocks tight
    before mincross even begins.
    """
    import os as _os_br

    layout.ranks = defaultdict(list)

    from gvpy.engines.layout.dot.trace import trace as _bfs_trace, trace_on as _bfs_on
    _bfs_traceon = _bfs_on("bfs")

    # BFS-from-sources is the **default** (C-aligned) path as of
    # §1.5.31 (2026-04-26).  §1.5.21–§1.5.30 added install_cluster
    # recursion, rank-then-DOT source ordering, and rank-internal
    # source repositioning, then ported C's 3-pass mincross loop with
    # cross-rank transpose / reverse tie-break / flat_mval+hasfixed
    # / CL_CROSS-guarded reverse tie-break.  d5_regression baseline
    # closes (1 crossing, matches C) under the new default;
    # 1879.dot's parent-child placement spread drops 17× vs the
    # legacy DFS path.  Set ``GVPY_LEGACY_BUILD_RANKS=1`` to fall
    # back to the DFS-over-undirected path for diagnostics.
    if _os_br.environ.get("GVPY_LEGACY_BUILD_RANKS", "") == "1":
        _build_ranks_legacy_dfs(layout, _bfs_trace, _bfs_traceon)
        # Apply the same cluster-contiguity normalization to the
        # DFS output so both backends present a consistent final
        # layout to mincross.
        _normalize_cluster_contiguity(layout)
        return

    # Build directed out-adjacency + in-degree.  C's ``build_ranks``
    # starts from every node whose ``otheredges`` list (``ND_in`` for
    # pass=0) is empty — i.e. graph sources.  We mimic that.
    out_adj: dict[str, list[str]] = defaultdict(list)
    in_count: dict[str, int] = defaultdict(int)
    seen_pairs: set[tuple[str, str]] = set()
    for le in layout.ledges:
        t, h = le.tail_name, le.head_name
        if t not in layout.lnodes or h not in layout.lnodes:
            continue
        if (t, h) in seen_pairs:
            continue
        seen_pairs.add((t, h))
        out_adj[t].append(h)
        in_count[h] += 1

    visited: set[str] = set()
    installed: set[str] = set()  # added to ``layout.ranks``
    cluster_installed: set[str] = set()  # whole cluster placed
    from collections import deque

    # Innermost cluster per node (mirrors C's ``ND_clust(n)``).
    node_cl: dict[str, str] = {}
    clusters_by_name: dict = {}
    if getattr(layout, "_clusters", None):
        size_by_cl = {cl.name: len(cl.nodes) for cl in layout._clusters}
        for cl in layout._clusters:
            clusters_by_name[cl.name] = cl
            for n in cl.nodes:
                if n not in layout.lnodes:
                    continue
                prev = node_cl.get(n)
                if prev is None or size_by_cl[cl.name] < size_by_cl[prev]:
                    node_cl[n] = cl.name

    def _install_cluster(cl_name: str, q: "deque[str]") -> None:
        """Mirror of ``lib/dotgen/cluster.c:install_cluster()``.

        Install every member of cluster ``cl_name`` into its rank in
        cluster-declaration order, then enqueue all their out-neighbors.
        Sets ``cluster_installed`` so a later BFS pop on a sibling
        member is a no-op.
        """
        if cl_name in cluster_installed:
            return
        cl = clusters_by_name.get(cl_name)
        if cl is None:
            return
        for n in cl.nodes:
            if n not in layout.lnodes or n in installed:
                continue
            layout.ranks[layout.lnodes[n].rank].append(n)
            installed.add(n)
            visited.add(n)
            if _bfs_traceon:
                _bfs_trace("bfs",
                           f"install_cluster {cl_name} member {n} "
                           f"rank={layout.lnodes[n].rank}")
        cluster_installed.add(cl_name)
        # C does this in a separate loop after every rankleader is in.
        for n in cl.nodes:
            if n not in layout.lnodes:
                continue
            for nbr in out_adj.get(n, []):
                if nbr not in visited and nbr in layout.lnodes:
                    visited.add(nbr)
                    q.append(nbr)

    def _bfs(start: str) -> None:
        if start in visited or start not in layout.lnodes:
            return
        if _bfs_traceon:
            _bfs_trace("bfs",
                       f"source: {start} rank={layout.lnodes[start].rank}")
        queue: "deque[str]" = deque([start])
        visited.add(start)
        while queue:
            name = queue.popleft()
            if name in installed:
                continue  # already placed via _install_cluster
            cl_name = node_cl.get(name)
            if cl_name is not None and cl_name not in cluster_installed:
                # Cluster-block install — every member at its rank, in
                # declaration order, with all out-neighbors enqueued at
                # the end (matches C's ``install_cluster`` two-loop
                # structure).
                _install_cluster(cl_name, queue)
                continue
            # Plain node install.
            layout.ranks[layout.lnodes[name].rank].append(name)
            installed.add(name)
            if _bfs_traceon:
                _bfs_trace("bfs",
                           f"install {name} rank={layout.lnodes[name].rank}")
            for nbr in out_adj.get(name, []):
                if nbr not in visited and nbr in layout.lnodes:
                    visited.add(nbr)
                    queue.append(nbr)

    # Walk sources in **rank-then-DOT** order — C's ``GD_nlist`` is
    # populated in rank order during graph build, so its
    # ``agfstnode``/``ND_next`` scan visits rank-0 sources before any
    # rank-1+ source.  Pure-DOT-order iteration (the §1.5.22 default)
    # interleaves ranks, so a rank-1 source declared early in the file
    # gets BFS'd before a rank-0 source declared later, producing a
    # rank-0 ordering that doesn't match C's.  The sort key keeps
    # DOT-declaration order *within* a rank, only promoting earlier
    # ranks ahead of later ones — preserves §1.5.22 behaviour for
    # graphs with no rank-skew between sources.
    dot_order_nodes: list[str] = [
        name for name in layout.graph.nodes if name in layout.lnodes
    ]
    virtual_nodes: list[str] = sorted(
        (n for n in layout.lnodes if n not in set(dot_order_nodes)),
        key=lambda n: (layout.lnodes[n].rank, n),
    )
    # Stable sort: (rank, original DOT position) — Python's sort is
    # stable so equal-rank entries retain their dot_order_nodes order.
    dot_idx = {n: i for i, n in enumerate(dot_order_nodes)}
    iter_order = sorted(
        dot_order_nodes + virtual_nodes,
        key=lambda n: (layout.lnodes[n].rank, dot_idx.get(n, len(dot_order_nodes))),
    )

    # Phase 1: sources with in_count == 0, in rank-then-DOT order.
    for name in iter_order:
        if name in visited or name not in layout.lnodes:
            continue
        if in_count.get(name, 0) == 0:
            _bfs(name)

    # Phase 2: any residual (e.g. cycle-only components) — start from
    # the first unvisited node in rank-then-DOT order.
    for name in iter_order:
        if name not in visited and name in layout.lnodes:
            _bfs(name)

    # Ensure disconnected nodes get placed (use ``installed`` since
    # ``visited`` includes nodes reserved for cluster-block install
    # that may not yet be in ``layout.ranks``).
    for name, ln in layout.lnodes.items():
        if name not in installed:
            layout.ranks[ln.rank].append(name)
            installed.add(name)

    # Post-BFS cluster-contiguity normalization is now redundant when
    # the in-BFS ``_install_cluster`` runs (mirrors C's behaviour
    # exactly).  Kept as a no-op safety net for single-rank clusters
    # the BFS reaches via cluster-internal edges only — the pass
    # leaves rank arrays untouched if every cluster is already
    # contiguous.
    _normalize_cluster_contiguity(layout)

    # §1.5.24 — Reposition rank-internal sources by children-median.
    # A rank-internal source is a node with no incoming edges that's
    # at rank > 0 (typically pulled to its rank by cluster
    # constraints).  BFS installs these at the END of their rank
    # (whenever the source-iteration phase reaches them), but their
    # children may already live near the FRONT of the next rank,
    # creating long parent→child edges.  Mincross can't pull them
    # leftward because it has no upward median for them.
    #
    # Fix: for each rank-internal source, slot it (and its cluster)
    # in front of the rank position whose children-median equals
    # this source's children-median.  Surgical — only moves nodes
    # mincross can't move on its own; leaves every node with at
    # least one incoming edge in its BFS-determined position.
    #
    # Iterate up to ``_MAX_ITERS`` passes — moving one source can
    # shift another's children-median, so a single pass undershoots
    # cases like ``couple_5378x5379`` where children sit deep on the
    # left.  Stops on first pass that produces no further changes
    # (typical: 2-3 iterations).
    _MAX_ITERS = 5
    prev_state: list[tuple[int, tuple[str, ...]]] = []
    for _it in range(_MAX_ITERS):
        snapshot = sorted((r, tuple(rl)) for r, rl in layout.ranks.items())
        if snapshot == prev_state:
            break
        prev_state = snapshot
        _reposition_rank_internal_sources(layout, in_count, out_adj)


def build_ranks_on_skeleton(layout, active_nodes: set[str]) -> None:
    """Re-run BFS-based rank ordering restricted to a skeleton view.

    Mirrors C's ``mincross.c:build_ranks(g, 0)`` when ``g`` is the
    SKELETON graph produced by ``class2`` (cluster proxies +
    non-cluster real nodes + chain virtuals).  Currently
    :func:`build_ranks` runs in phase 1 on the *original* graph and
    its output is the input to ``skeleton_mincross``.  C's flow is
    different: phase 1 only assigns rank numbers, then ``class2``
    builds the skeleton graph, then ``mincross()`` calls
    ``build_ranks`` on the SKELETON.  Source iteration happens over
    the skeleton's ``GD_nlist`` (cluster proxies count!), so the
    first BFS source can be a rank-1 cluster proxy whose cluster has
    no inter-cluster in-edges — not a rank-0 real-node source as
    Py's pre-§1.5.34 build_ranks always picks.

    ``active_nodes`` is the set of skeleton-visible names: cluster
    rank-leader proxies plus any real nodes that aren't currently
    hidden inside a cluster.  Edges with one endpoint outside this
    set are skipped — they're either intra-cluster (already
    represented by the cluster's chain edges) or cross to a hidden
    node (which has been re-routed to the cluster's proxy via the
    skeleton chain).

    Repopulates ``layout.ranks`` with the new ordering.  Other
    layout state (lnodes / ledges) is unchanged.
    """
    import os as _os_skel
    from collections import deque, defaultdict as _dd
    from gvpy.engines.layout.dot.trace import (
        trace as _bfs_trace, trace_on as _bfs_on,
    )
    _bfs_traceon = _bfs_on("bfs")

    # Reset the rank arrays — caller is asking for a fresh ordering.
    layout.ranks = _dd(list)

    # Build directed out-adjacency restricted to ``active_nodes``.
    out_adj: dict[str, list[str]] = _dd(list)
    in_count: dict[str, int] = _dd(int)
    seen_pairs: set[tuple[str, str]] = set()
    for le in layout.ledges:
        t, h = le.tail_name, le.head_name
        if t not in active_nodes or h not in active_nodes:
            continue
        if (t, h) in seen_pairs:
            continue
        seen_pairs.add((t, h))
        out_adj[t].append(h)
        in_count[h] += 1

    visited: set[str] = set()
    installed: set[str] = set()

    def _bfs(start: str) -> None:
        if start in visited or start not in layout.lnodes:
            return
        if _bfs_traceon:
            _bfs_trace(
                "bfs",
                f"source: {start} rank={layout.lnodes[start].rank}")
        queue: "deque[str]" = deque([start])
        visited.add(start)
        while queue:
            name = queue.popleft()
            if name in installed:
                continue
            layout.ranks[layout.lnodes[name].rank].append(name)
            installed.add(name)
            if _bfs_traceon:
                _bfs_trace(
                    "bfs",
                    f"install {name} rank={layout.lnodes[name].rank}")
            for nbr in out_adj.get(name, []):
                if nbr in active_nodes and nbr not in visited:
                    visited.add(nbr)
                    queue.append(nbr)

    # Source-iteration order.  §1.5.35 trace of C's ``GD_nlist`` on
    # 1879.dot showed:
    #   * idx 0-27 are nodes with ``has_in=1`` — reached via DFS from
    #     ``agfstnode``-order starting points (DOT-declared first).
    #   * Sources (``has_in=0``) appear from idx 28 onwards in the
    #     order C's DFS stack pops them — basically a DFS pre-order
    #     through the cluster graph following ``ND_out``.
    # The first source in C's iteration is therefore the FIRST source
    # encountered during DFS pre-order from the first DOT-declared
    # node, which on 1879.dot is ``cluster_7545x7546`` (rank 1) —
    # whatever the DFS happens to reach last among the rank-1 cluster
    # proxies.  ``GVPY_SKELETON_ITER_ORDER=dfs`` selects this; legacy
    # ``dot`` and ``rank_then_dot`` remain available for diagnostics.
    _order_mode = _os_skel.environ.get("GVPY_SKELETON_ITER_ORDER", "dfs")

    # Build a list of active nodes in our chosen iteration order.
    if _order_mode == "dfs":
        # DFS pre-order starting from the first DOT-declared active
        # node, walking out-edges.  Mirrors C's ``GD_nlist`` order
        # observed on 1879.dot via the [TRACE skeleton_nlist] dump
        # — clusters and non-cluster nodes come out of this in the
        # exact sequence C uses, so the eventual source-iteration
        # picks the same first source as C.
        clusters_by_name = {cl.name: cl for cl in (
            getattr(layout, "_clusters", None) or [])}
        node_dot_idx = {n: i for i, n in enumerate(layout.graph.nodes)}

        def _proxy_dot_idx(p: str) -> int:
            """For a ``_skel_<cluster>_<rank>`` proxy, the DOT
            position of its cluster's first member — gives a stable
            seed point for DFS within the active set."""
            rest = p[len("_skel_"):]
            u = rest.rfind("_")
            if u < 0:
                return len(node_dot_idx)
            cl_name = rest[:u]
            cl = clusters_by_name.get(cl_name)
            if cl is None:
                return len(node_dot_idx)
            for member in cl.nodes:
                if member in node_dot_idx:
                    return node_dot_idx[member]
            return len(node_dot_idx)

        def _start_key(n: str) -> int:
            if n.startswith("_skel_"):
                return _proxy_dot_idx(n)
            return node_dot_idx.get(n, len(node_dot_idx))

        # Order in which to TRY DFS starting points.  Within a DFS
        # tree, child order also matters — use the same key on
        # neighbours.
        start_order = sorted(active_nodes, key=_start_key)

        dfs_visited: set[str] = set()
        iter_order: list[str] = []

        def _dfs(n: str) -> None:
            stack = [n]
            while stack:
                node = stack.pop()
                if node in dfs_visited:
                    continue
                dfs_visited.add(node)
                iter_order.append(node)
                # §1.5.36: visit neighbours in their ``out_adj``
                # insertion order, matching C's ND_out linked-list
                # head-to-tail walk.  Stack is LIFO, so push in
                # REVERSE of desired visit order — the first
                # neighbour in ``out_adj`` ends up on top of the
                # stack and gets popped (visited) first.  Trace
                # ``[TRACE nd_out_emit]`` on 1879.dot confirmed
                # cluster_325x326's ND_out order matches our
                # ``layout.ledges``-derived ``out_adj`` order
                # exactly when no sort is applied.
                nbrs = [nbr for nbr in out_adj.get(node, [])
                        if nbr in active_nodes and nbr not in dfs_visited]
                for nbr in reversed(nbrs):
                    stack.append(nbr)

        for s in start_order:
            if s not in dfs_visited:
                _dfs(s)

    elif _order_mode == "rank_then_dot":
        # Same key as legacy ``build_ranks``: rank ascending, then
        # DOT-declaration order within rank.
        dot_nodes = [n for n in layout.graph.nodes if n in active_nodes]
        dot_idx = {n: i for i, n in enumerate(dot_nodes)}
        rest = [n for n in active_nodes if n not in dot_idx]
        rest.sort(key=lambda n: (layout.lnodes[n].rank, n))
        iter_order = sorted(
            dot_nodes + rest,
            key=lambda n: (layout.lnodes[n].rank,
                           dot_idx.get(n, len(dot_nodes))),
        )
    else:
        # Default: DOT-declaration order with cluster proxies
        # interleaved at the position of their first member.  Real
        # non-cluster nodes appear in their DOT order; cluster
        # proxies appear before/after based on their cluster's first
        # member's position.
        dot_nodes = [n for n in layout.graph.nodes if n in active_nodes]
        skel_nodes = [n for n in active_nodes
                      if n not in set(dot_nodes) and n.startswith("_skel_")]
        # Map each cluster proxy to its cluster's first DOT-order
        # member's index, then sort proxies among real names.
        clusters_by_name = {cl.name: cl for cl in (
            getattr(layout, "_clusters", None) or [])}
        node_dot_idx = {n: i for i, n in enumerate(layout.graph.nodes)}

        def _proxy_idx(p: str) -> int:
            # ``_skel_<cluster>_<rank>`` — find <cluster>
            rest = p[len("_skel_"):]
            u = rest.rfind("_")
            if u < 0:
                return len(node_dot_idx)
            cl_name = rest[:u]
            cl = clusters_by_name.get(cl_name)
            if cl is None:
                return len(node_dot_idx)
            for member in cl.nodes:
                if member in node_dot_idx:
                    return node_dot_idx[member]
            return len(node_dot_idx)

        # Other virtuals (icv, anonymous) come last in name order.
        other_virt = [n for n in active_nodes
                      if n not in set(dot_nodes)
                      and not n.startswith("_skel_")]
        other_virt.sort()
        proxy_order = sorted(skel_nodes, key=_proxy_idx)
        # Interleave real nodes and proxies by their DOT position.
        keyed: list[tuple[int, int, str]] = []
        for n in dot_nodes:
            keyed.append((node_dot_idx[n], 0, n))
        for p in proxy_order:
            keyed.append((_proxy_idx(p), 1, p))
        keyed.sort()
        iter_order = [n for _, _, n in keyed] + other_virt

    if _bfs_traceon:
        _bfs_trace(
            "bfs",
            f"build_ranks_on_skeleton active={len(active_nodes)} "
            f"order_mode={_order_mode}")

    # Phase 1: sources with in_count == 0 in our iteration order.
    for name in iter_order:
        if in_count.get(name, 0) == 0:
            _bfs(name)

    # Phase 2: any residual (cycle-only components).
    for name in iter_order:
        if name not in visited and name in layout.lnodes:
            _bfs(name)

    # Disconnected fall-through.
    for name in active_nodes:
        if name not in installed and name in layout.lnodes:
            layout.ranks[layout.lnodes[name].rank].append(name)
            installed.add(name)

    # Update per-node order indices.
    for r, rank_list in layout.ranks.items():
        for i, name in enumerate(rank_list):
            if name in layout.lnodes:
                layout.lnodes[name].order = i


def _reposition_rank_internal_sources(layout, in_count, out_adj):
    """Move rank-internal sources (no in-edges, rank > 0) to a position
    in their rank that reflects their children's centroid.

    Mincross's median heuristic computes ``upward median`` (parent
    positions) to position a node — but a node with no parents has
    no upward median, so mincross leaves it where build_ranks put
    it.  This function fills that gap by positioning such nodes
    using their children's median index in the next rank.
    """
    if not layout.ranks:
        return
    sorted_ranks = sorted(layout.ranks.keys())
    if len(sorted_ranks) < 2:
        return

    # Innermost cluster per node so we move clusters as units.
    node_cl: dict[str, str] = {}
    if getattr(layout, "_clusters", None):
        size_by_cl = {cl.name: len(cl.nodes) for cl in layout._clusters}
        for cl in layout._clusters:
            for n in cl.nodes:
                if n not in layout.lnodes:
                    continue
                prev = node_cl.get(n)
                if prev is None or size_by_cl[cl.name] < size_by_cl[prev]:
                    node_cl[n] = cl.name

    # Walk ranks 1..N-1.  §1.5.26 included rank 0 too, but on 1879
    # that cascaded through the median chain and tripled rank-3
    # overlaps (14 → 41) — the per-rank coupling is too tight to
    # blindly resort rank 0 at build_ranks time.  Skipping rank 0
    # here defers its ordering to mincross (which has the full
    # crossing-count signal to balance against), and limits this
    # pass to deeper-rank sources mincross definitionally can't
    # move (no upward median).
    for ri, r in enumerate(sorted_ranks):
        if ri == 0:
            continue
        next_r = sorted_ranks[ri + 1] if ri + 1 < len(sorted_ranks) else None
        if next_r is None:
            continue  # bottom rank — no children to median over
        child_pos = {n: idx for idx, n in enumerate(layout.ranks[next_r])}
        rank_list = layout.ranks[r]

        # Identify rank-internal sources at this rank.
        sources: list[tuple[float, str]] = []
        for n in rank_list:
            if in_count.get(n, 0) != 0:
                continue
            children = out_adj.get(n, [])
            indices = sorted(child_pos[c] for c in children if c in child_pos)
            if not indices:
                continue
            cnt = len(indices)
            med = (float(indices[cnt // 2]) if cnt % 2
                   else (indices[cnt // 2 - 1] + indices[cnt // 2]) / 2.0)
            sources.append((med, n))
        if not sources:
            continue

        # Group source-cluster blocks (a source's whole cluster moves
        # with it).  Pull them out of the rank, then re-insert at the
        # position whose existing-node children-median is closest.
        cluster_blocks: dict[str, tuple[float, list[str]]] = {}
        loose_sources: list[tuple[float, str]] = []
        for med, n in sources:
            cl = node_cl.get(n)
            if cl is None:
                loose_sources.append((med, n))
                continue
            # First time we see this cluster, harvest all its members.
            if cl not in cluster_blocks:
                members = [m for m in rank_list if node_cl.get(m) == cl]
                cluster_blocks[cl] = (med, members)
            else:
                # Multiple sources in same cluster — keep min-median.
                old_med, members = cluster_blocks[cl]
                cluster_blocks[cl] = (min(old_med, med), members)

        # Build the moved-out set and the residual rank.
        moved: set[str] = set()
        for cl, (_, members) in cluster_blocks.items():
            moved.update(members)
        for _, n in loose_sources:
            moved.add(n)
        residual = [n for n in rank_list if n not in moved]

        # Compute children-medians for the residual nodes too, so we
        # can find the right insertion point per moved block.
        residual_med: list[float] = []
        for n in residual:
            children = out_adj.get(n, [])
            indices = sorted(child_pos[c] for c in children if c in child_pos)
            if not indices:
                residual_med.append(float("inf"))  # no signal — push right
            else:
                cnt = len(indices)
                m = (float(indices[cnt // 2]) if cnt % 2
                     else (indices[cnt // 2 - 1] + indices[cnt // 2]) / 2.0)
                residual_med.append(m)

        # Splice each moved block in by its median: insert before the
        # first residual entry whose median is >= the block's median.
        new_rank: list[str] = list(residual)
        new_rank_med: list[float] = list(residual_med)

        # Process blocks in ascending median order so insertion
        # positions remain stable as we add to ``new_rank``.
        all_blocks: list[tuple[float, list[str]]] = []
        for cl, (med, members) in cluster_blocks.items():
            all_blocks.append((med, members))
        for med, n in loose_sources:
            all_blocks.append((med, [n]))
        all_blocks.sort(key=lambda x: x[0])

        for med, members in all_blocks:
            insert_at = len(new_rank)
            for j, m in enumerate(new_rank_med):
                if m >= med:
                    insert_at = j
                    break
            new_rank[insert_at:insert_at] = members
            new_rank_med[insert_at:insert_at] = [med] * len(members)

        layout.ranks[r] = new_rank

    # Cluster contiguity may have been disturbed if a moved cluster
    # landed between two members of another cluster.  Re-group.
    _normalize_cluster_contiguity(layout)


def _normalize_cluster_contiguity(layout):
    """Reorder each rank so cluster members are contiguous at the
    rank position where the cluster was first touched.

    This runs on both BFS and DFS build_ranks outputs (post-BFS
    cleanup for BFS; for DFS it's typically a no-op because DFS
    already groups connected components including cluster members).
    The goal is to leave every non-cluster node in its BFS-assigned
    position while moving any cluster peer that BFS visited later
    (via a different sub-tree) into the cluster's group.
    """
    if not getattr(layout, "_clusters", None):
        return
    # Innermost cluster per node.
    node_cl: dict[str, str] = {}
    size_by_cl = {cl.name: len(cl.nodes) for cl in layout._clusters}
    for cl in layout._clusters:
        for n in cl.nodes:
            if n not in layout.lnodes:
                continue
            prev = node_cl.get(n)
            if prev is None or size_by_cl[cl.name] < size_by_cl[prev]:
                node_cl[n] = cl.name
    for rank_num, rank_list in list(layout.ranks.items()):
        if not rank_list:
            continue
        first_pos: dict[str, int] = {}
        cluster_members: dict[str, list[str]] = {}
        for i, n in enumerate(rank_list):
            cl = node_cl.get(n)
            if cl is None:
                continue
            if cl not in first_pos:
                first_pos[cl] = i
                cluster_members[cl] = []
            cluster_members[cl].append(n)
        if not cluster_members:
            continue
        placed: set[str] = set()
        new_rank: list[str] = []
        for i, n in enumerate(rank_list):
            cl = node_cl.get(n)
            if cl is None:
                new_rank.append(n)
                continue
            if cl in placed:
                continue
            if first_pos[cl] == i:
                # Emit all members of this cluster together.
                placed.add(cl)
                new_rank.extend(cluster_members[cl])
        layout.ranks[rank_num] = new_rank


def _build_ranks_legacy_dfs(layout, _bfs_trace, _bfs_traceon):
    """Previous DFS-over-undirected-adjacency implementation.

    Kept behind ``GVPY_LEGACY_BUILD_RANKS=1`` so anyone investigating
    a regression can A/B the two algorithms.  Walking an undirected
    adjacency with a LIFO stack visits long chains before siblings —
    different order than C's BFS-from-sources-following-out-edges.
    """
    from collections import defaultdict as _dd
    adj: dict[str, list[str]] = _dd(list)
    for le in layout.ledges:
        adj[le.tail_name].append(le.head_name)
        adj[le.head_name].append(le.tail_name)
    for k in adj:
        adj[k].reverse()

    visited: set[str] = set()

    def _dfs(start: str):
        if start in visited or start not in layout.lnodes:
            return
        if _bfs_traceon:
            _bfs_trace("bfs",
                       f"source: {start} rank={layout.lnodes[start].rank}")
        stack: list[str] = [start]
        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            layout.ranks[layout.lnodes[name].rank].append(name)
            if _bfs_traceon:
                _bfs_trace("bfs",
                           f"install {name} rank={layout.lnodes[name].rank}")
            nbrs = [n for n in adj.get(name, [])
                    if n in layout.lnodes and n not in visited]
            for nbr in reversed(nbrs):
                stack.append(nbr)

    dot_order_nodes: list[str] = []
    for name in layout.graph.nodes:
        if name in layout.lnodes:
            dot_order_nodes.append(name)
    virtual_nodes = [n for n in layout.lnodes if n not in set(dot_order_nodes)]
    virtual_nodes.sort(key=lambda n: (layout.lnodes[n].rank, n))
    for name in dot_order_nodes + virtual_nodes:
        _dfs(name)

    for name, ln in layout.lnodes.items():
        if name not in visited:
            layout.ranks[ln.rank].append(name)

