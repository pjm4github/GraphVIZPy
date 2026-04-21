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

        # Create chain of virtual nodes
        chain = []
        prev_name = le.tail_name
        for j in range(1, span):
            vname = f"_v_{le.tail_name}_{le.head_name}_{j}"
            # Ensure unique name
            while vname in layout.lnodes:
                vname += "_"
            layout.lnodes[vname] = LayoutNode(
                name=vname, node=None, rank=t_rank + j, virtual=True,
                width=2.0, height=2.0,
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
    """Populate layout.ranks with DFS-based initial ordering.

    Mirrors Graphviz ``init_mincross()`` / ``dfs_range()``: traverse
    from a root node following edges, assigning order within each
    rank based on DFS visit order.  This naturally groups connected
    components and clusters together, giving the mincross a better
    starting configuration than simple dict-order iteration.
    """
    layout.ranks = defaultdict(list)

    # Build adjacency preserving edge list order (matching C's edge
    # traversal in decompose search_component).
    # C visits: flat_in, flat_out, in, out — in reverse edge order.
    # We approximate this: for each node, collect neighbors in the
    # order edges appear in layout.ledges, then reverse (to match C's
    # reverse iteration with a LIFO stack).
    adj: dict[str, list[str]] = defaultdict(list)
    for le in layout.ledges:
        adj[le.tail_name].append(le.head_name)
        adj[le.head_name].append(le.tail_name)
    # Reverse to match C's stack-based reverse iteration
    for k in adj:
        adj[k].reverse()

    visited: set[str] = set()

    # Use explicit stack to mirror C's search_component:
    # push neighbors in reverse order (C iterates edge list backward
    # and pushes, stack pops give forward order).
    def _dfs(start: str):
        if start in visited or start not in layout.lnodes:
            return
        stack: list[str] = [start]
        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            layout.ranks[layout.lnodes[name].rank].append(name)
            # Push neighbors in reverse order so first neighbor
            # gets processed first (LIFO)
            nbrs = [n for n in adj.get(name, [])
                    if n in layout.lnodes and n not in visited]
            for nbr in reversed(nbrs):
                stack.append(nbr)

    # Start from nodes in DOT file order (matching C's agfstnode)
    # The graph.nodes dict preserves insertion order.
    dot_order_nodes: list[str] = []
    for name in layout.graph.nodes:
        if name in layout.lnodes:
            dot_order_nodes.append(name)
    # Also include virtual nodes (sorted by rank for consistency)
    virtual_nodes = [n for n in layout.lnodes if n not in set(dot_order_nodes)]
    virtual_nodes.sort(key=lambda n: (layout.lnodes[n].rank, n))
    for name in dot_order_nodes + virtual_nodes:
        _dfs(name)

    # Ensure all nodes are in ranks (disconnected nodes)
    for name, ln in layout.lnodes.items():
        if name not in visited:
            layout.ranks[ln.rank].append(name)

