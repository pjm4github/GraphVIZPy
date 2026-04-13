"""Phase 3: position assignment.

C analogue: ``lib/dotgen/position.c`` — ``set_ycoords()``,
``set_xcoords()``, ``make_LR_constraints()``, ``make_edge_pairs()``,
``contain_nodes()``, ``pos_clusters()``, ``contain_subclust()``, etc.

Current status of the extraction
--------------------------------
This module is the long-term home for all Phase 3 code (per the C
factoring).  For now it contains:

- ``phase3_position(layout)``   — orchestrator, C ``dot_position``
- ``ns_x_position(layout)``     — X-coordinate NS solver, C
  ``position.c:create_aux_edges`` + ``rank()`` + ``set_xcoords``

Other Phase 3 helpers (``_set_ycoords``, ``_expand_leaves``,
``_insert_flat_label_nodes``, ``_bottomup_ns_x_position``,
``_compute_cluster_boxes``, ``_simple_x_position``,
``_median_x_improvement``, ``_center_ranks``, ``_apply_rankdir``,
``_resolve_cluster_overlaps``, ``_post_rankdir_keepout``) still live in
``dot_layout.py`` as methods on ``DotGraphInfo``.  They are called from
here via ``layout._xxx()``.  Subsequent passes will migrate them here.

See ``TODO_core_refactor.md`` step 4 for the full migration plan.

Historical note
---------------
The cluster-overlap bug fix of 2026-04-12 landed in this module's
``ns_x_position``.  See the comments at sections "1. Separation edges"
and "3e. Sibling separation" for the two root causes and their fixes.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.engines.layout.dot.dot_layout import DotGraphInfo


def phase3_position(layout: "DotGraphInfo") -> None:
    """Top-level Phase 3 driver.

    C analogue: ``dot_position()`` in ``lib/dotgen/position.c`` calls
    ``set_ycoords()`` then ``set_xcoords()`` then does post-processing
    for cluster-overlap resolution and rankdir flipping.
    """
    print(
        f"[TRACE position] phase3 begin: rankdir={layout.rankdir} "
        f"ranksep={layout.ranksep} nodesep={layout.nodesep}",
        file=sys.stderr,
    )
    if not layout.lnodes:
        return

    # Y coordinates following Graphviz position.c set_ycoords().
    layout._set_ycoords()
    # Log Y coords for real nodes
    for name in sorted(layout.lnodes.keys()):
        ln = layout.lnodes[name]
        if not ln.virtual:
            print(
                f"[TRACE position] set_ycoords: {name} y={ln.y:.1f}",
                file=sys.stderr,
            )

    # Expand leaves: ensure degree-1 nodes have proper spacing
    # (Graphviz position.c expand_leaves).
    layout._expand_leaves()

    # Insert virtual label nodes for labeled flat edges (Graphviz
    # position.c flat_edges).  If any were inserted, re-run Y coords.
    if layout._insert_flat_label_nodes():
        layout._set_ycoords()

    # X coordinates: single-pass global NS for clustered graphs,
    # matching Graphviz position.c create_aux_edges + rank().
    if layout._clusters:
        if not ns_x_position(layout):
            # Fallback to bottom-up if NS fails
            layout._bottomup_ns_x_position()
        layout._compute_cluster_boxes()
    else:
        layout._simple_x_position()
        layout._median_x_improvement()
        layout._center_ranks()

    # Log final X,Y coords for real nodes
    for name in sorted(layout.lnodes.keys()):
        ln = layout.lnodes[name]
        if not ln.virtual:
            print(
                f"[TRACE position] final_pos: {name} x={ln.x:.1f} "
                f"y={ln.y:.1f} w={ln.width:.1f} h={ln.height:.1f}",
                file=sys.stderr,
            )

    layout._apply_rankdir()

    # Post-rankdir: resolve all cluster overlaps and push non-member
    # nodes out of sibling cluster bboxes.
    if layout._clusters:
        layout._resolve_cluster_overlaps()
        layout._post_rankdir_keepout()

    # Log post-rankdir positions
    for name in sorted(layout.lnodes.keys()):
        ln = layout.lnodes[name]
        if not ln.virtual:
            print(
                f"[TRACE position] post_rankdir: {name} "
                f"x={ln.x:.1f} y={ln.y:.1f}",
                file=sys.stderr,
            )


def ns_x_position(layout: "DotGraphInfo") -> bool:
    """Assign X coordinates using network simplex on an auxiliary graph.

    Mirrors Graphviz ``position.c``: ``create_aux_edges()`` builds a
    constraint graph, ``rank()`` solves it with NS, ``set_xcoords()``
    extracts positions.

    Bug history
    -----------
    The auxiliary graph must be **acyclic** — every edge flows from a
    lower-order (left) node to a higher-order (right) node, and cluster
    boundary nodes (ln/rn) must be positioned consistently with the
    mincross ordering at every shared rank.

    On 2026-04-12 two cycle sources were removed:

    1. A per-rank "stable sort by innermost cluster name" inside this
       function used to reorder ``layout.ranks[r]`` by cluster alphabet
       and rewrite ``lnode.order``.  That destroyed the mincross
       result and introduced cycles via the keepout edges (3f).
       Removed — separation edges now come directly from mincross order.

    2. The "sibling separation" block (3e) added
       ``cl_rn[left] → cl_ln[right]`` edges using a GLOBAL average-order
       sort of sibling clusters.  When sibling clusters interleaved
       across ranks (e.g. A left of B at rank 5 but B left of A at
       rank 7), this created contradictory constraints and cycles.
       Disabled behind ``_sibling_separation_enabled``.  Per-rank
       separation and keepout edges already handle sibling ordering
       in ranks the clusters share.
    """
    # _NetworkSimplex now lives in its own ns_solver module;
    # importing directly avoids the dot_layout.py re-export hop.
    from gvpy.engines.layout.dot.ns_solver import _NetworkSimplex

    real_nodes = [n for n in layout.lnodes if not layout.lnodes[n].virtual]
    if len(real_nodes) < 2:
        return False

    aux_nodes: list[str] = list(layout.lnodes.keys())
    aux_edges: list[tuple[str, str, int, int]] = []
    _vn_counter = [0]

    def _vnode(prefix: str = "_xv") -> str:
        _vn_counter[0] += 1
        return f"{prefix}_{_vn_counter[0]}"

    # ── Pre-compute cluster maps ──────────────────────
    _cl_by_name: dict[str, object] = {}
    _node_to_cl: dict[str, str] = {}
    if layout._clusters:
        _cl_by_name = {cl.name: cl for cl in layout._clusters}
        for cl in sorted(layout._clusters,
                         key=lambda c: len(c.nodes), reverse=True):
            for n in cl.nodes:
                if n in layout.lnodes:
                    _node_to_cl[n] = cl.name

    # ── 1. Separation edges (make_LR_constraints) ─────
    # Adjacent nodes in the same rank: left → right with
    # minlen = separation needed, weight = 0.
    #
    # NOTE: We used to re-sort each rank by innermost cluster name
    # here.  That sort was consistent (alphabetical → same order at
    # every rank) but destroyed the mincross result.  Removed.
    # See the module docstring for the full history.
    for rank_val, rank_nodes in layout.ranks.items():
        for i in range(len(rank_nodes) - 1):
            left = rank_nodes[i]
            right = rank_nodes[i + 1]
            ln_l = layout.lnodes[left]
            ln_r = layout.lnodes[right]
            min_dist = int(ln_l.width / 2.0 + ln_r.width / 2.0
                           + layout.nodesep)
            left_cl = _node_to_cl.get(left, "")
            right_cl = _node_to_cl.get(right, "")
            if left_cl != right_cl:
                if left_cl and left_cl in _cl_by_name:
                    min_dist += int(_cl_by_name[left_cl].margin)
                if right_cl and right_cl in _cl_by_name:
                    min_dist += int(_cl_by_name[right_cl].margin)
            # Enforce the settable routing-channel floor: the
            # cross-rank gap between adjacent node bboxes must be at
            # least ``_routing_channel`` so a routing channel fits
            # between them.  ``nodesep`` is already typically larger
            # (18pt default vs 8pt), so this only kicks in when the
            # user shrinks nodesep or raises _routing_channel.
            _rc = float(getattr(layout, "_routing_channel",
                                getattr(layout, "_CL_OFFSET", 8.0)))
            min_gap = int(ln_l.width / 2.0 + ln_r.width / 2.0 + _rc)
            if min_gap > min_dist:
                min_dist = min_gap
            aux_edges.append((left, right, max(1, min_dist), 0))

    # ── 2. Alignment edges (make_edge_pairs) ──────────
    # For each real edge, a slack node pulls endpoints together.
    node_groups: dict[str, str] = {}
    for name, ln in layout.lnodes.items():
        if ln.node:
            grp = ln.node.attributes.get("group", "")
            if grp:
                node_groups[name] = grp

    for le in layout.ledges:
        t_ln = layout.lnodes.get(le.tail_name)
        h_ln = layout.lnodes.get(le.head_name)
        if not t_ln or not h_ln:
            continue
        w = le.weight
        t_grp = node_groups.get(le.tail_name, "")
        h_grp = node_groups.get(le.head_name, "")
        if t_grp and t_grp == h_grp:
            w = max(w * 100, 100)
        # Port offset: difference in cross-rank port positions
        # (mirrors C make_edge_pairs: m0 = head_port.x - tail_port.x)
        m0 = int(getattr(le, 'head_port_cross', 0)
                 - getattr(le, 'tail_port_cross', 0))
        if m0 > 0:
            m1 = 0
        else:
            m1 = -m0
            m0 = 0
        sn = _vnode("_sn")
        aux_nodes.append(sn)
        aux_edges.append((sn, le.tail_name, m0 + 1, w))
        aux_edges.append((sn, le.head_name, m1 + 1, w))

    # ── 3. Cluster boundary edges (pos_clusters) ──────
    cl_ln: dict[str, str] = {}
    cl_rn: dict[str, str] = {}
    if layout._clusters:
        node_sets = {cl.name: set(cl.nodes) for cl in layout._clusters}

        # Build TRUE parent map from subgraph tree
        cl_names_set = set(node_sets.keys())
        tree_parent: dict[str, str | None] = {}
        def _walk(g, parent_cl):
            for sub_name, sub in g.subgraphs.items():
                if sub_name in cl_names_set:
                    tree_parent[sub_name] = parent_cl
                    _walk(sub, sub_name)
                else:
                    _walk(sub, parent_cl)
        _walk(layout.graph, None)

        tree_children: dict[str | None, list[str]] = {}
        for cn, par in tree_parent.items():
            tree_children.setdefault(par, []).append(cn)

        cl_by_name = {cl.name: cl for cl in layout._clusters}

        # ── 3a. Create ln/rn boundary nodes ──────────
        # Compute cluster border widths for labels (C: input.c)
        # For rankdir=LR/RL, label height becomes cross-rank border.
        cl_border_l: dict[str, float] = {}
        cl_border_r: dict[str, float] = {}
        is_flipped = layout.rankdir in ("LR", "RL")
        for cl in layout._clusters:
            bl = br = 0.0
            if cl.label:
                try:
                    fontsize = float(cl.attrs.get("fontsize", 14))
                except (ValueError, TypeError):
                    fontsize = 14.0
                # Label dimen: width = text_width, height = fontsize
                # PAD adds 4pt each side
                label_h = fontsize + 8.0
                label_w = len(cl.label) * fontsize * 0.6 + 8.0
                labelloc = cl.attrs.get("labelloc", "t").lower()
                if is_flipped:
                    # Rotated: TOP→RIGHT, BOTTOM→LEFT
                    # border.x = dimen.y (label height → cross-rank)
                    if labelloc != "b":
                        br = label_h  # label at top → right border
                    else:
                        bl = label_h
                # TB/BT: borders are in rank direction, not cross-rank
            cl_border_l[cl.name] = bl
            cl_border_r[cl.name] = br

        for cl in layout._clusters:
            ln_name = _vnode("_cln")
            rn_name = _vnode("_crn")
            aux_nodes.extend([ln_name, rn_name])
            cl_ln[cl.name] = ln_name
            cl_rn[cl.name] = rn_name
            # Label width edge for ln→rn (C: make_lrvn)
            if cl.label and not is_flipped:
                lbl_w = max(cl_border_l.get(cl.name, 0),
                            cl_border_r.get(cl.name, 0))
                if lbl_w > 0:
                    aux_edges.append((ln_name, rn_name,
                                      max(1, int(lbl_w)), 0))

        # Settable routing-channel width floor applied to every
        # cluster-boundary gap below.  The user can bump this via
        # ``layout._routing_channel`` to widen every cluster margin
        # and sibling-cluster separation in one knob.
        _rc_floor = float(getattr(layout, "_routing_channel",
                                   getattr(layout, "_CL_OFFSET", 8.0)))

        # ── 3b. Containment: ln → node, node → rn ───
        # (contain_nodes in C code)
        for cl in layout._clusters:
            margin = max(int(cl.margin), int(_rc_floor))
            ln_name = cl_ln[cl.name]
            rn_name = cl_rn[cl.name]
            border_l = cl_border_l.get(cl.name, 0.0)
            border_r = cl_border_r.get(cl.name, 0.0)

            # For each rank, constrain the leftmost and rightmost
            # cluster nodes (matches C contain_nodes).
            cl_ranks: dict[int, list[str]] = {}
            for n in cl.nodes:
                if n in layout.lnodes:
                    r = layout.lnodes[n].rank
                    cl_ranks.setdefault(r, []).append(n)

            for r, nodes in cl_ranks.items():
                nodes.sort(key=lambda n: layout.lnodes[n].order)
                leftmost = nodes[0]
                rightmost = nodes[-1]
                lw = layout.lnodes[leftmost].width / 2.0
                rw = layout.lnodes[rightmost].width / 2.0
                aux_edges.append((ln_name, leftmost,
                                  max(1, int(lw + margin + border_l)), 0))
                aux_edges.append((rightmost, rn_name,
                                  max(1, int(rw + margin + border_r)), 0))

            # ── 3c. Compaction: ln → rn (weight=128) ─
            aux_edges.append((ln_name, rn_name, 1, 128))

        # ── 3d. Hierarchy: parent.ln → child.ln, child.rn → parent.rn
        # (contain_subclust in C code — includes parent border)
        for cl_name, par in tree_parent.items():
            if par is None:
                continue
            margin = max(int(cl_by_name[par].margin), int(_rc_floor))
            par_bl = cl_border_l.get(par, 0.0)
            par_br = cl_border_r.get(par, 0.0)
            aux_edges.append((cl_ln[par], cl_ln[cl_name],
                              max(1, int(margin + par_bl)), 0))
            aux_edges.append((cl_rn[cl_name], cl_rn[par],
                              max(1, int(margin + par_br)), 0))

        # ── 3e. Sibling separation (separate_subclust) ──
        # C analogue: lib/dotgen/position.c:separate_subclust().  For
        # every pair of sibling clusters under a common parent, if
        # their rank ranges overlap, pick which one sits left/right
        # by comparing ND_order at a *single* rank — specifically
        # the minimum rank where both clusters are present.  Add a
        # weight-0 edge ``left._crn → right._cln`` with minlen equal
        # to the parent's margin.
        #
        # The earlier Python attempt used an AVERAGE-order comparator
        # which could flip the left/right pick across ranks and create
        # cycles (cl_A._crn → cl_B._cln via avg-order sep, and at some
        # rank c_B_mem → c_A_mem via per-rank separation, giving
        # cl_A → cl_B → cl_A).  C sidesteps this by construction
        # because its comparator uses a single rank, so the relative
        # order is consistent everywhere the edge lives.
        def _ranks_of(cl_name: str) -> set[int]:
            return {layout.lnodes[n].rank
                    for n in node_sets[cl_name]
                    if n in layout.lnodes}

        def _min_order_at_rank(cl_name: str, r: int) -> int | None:
            orders = [layout.lnodes[n].order
                      for n in node_sets[cl_name]
                      if n in layout.lnodes
                      and layout.lnodes[n].rank == r]
            return min(orders) if orders else None

        for par in list(tree_children.keys()):
            siblings = tree_children[par]
            if len(siblings) < 2:
                continue
            # margin comes from the common parent; fall back to a
            # child margin when the parent is the virtual root.
            if par is not None and par in cl_by_name:
                m = int(cl_by_name[par].margin)
            else:
                m = int(max(
                    cl_by_name[s].margin for s in siblings))
            m = max(m, int(_rc_floor))
            for i in range(len(siblings)):
                for j in range(i + 1, len(siblings)):
                    a_name = siblings[i]
                    b_name = siblings[j]
                    a_ranks = _ranks_of(a_name)
                    b_ranks = _ranks_of(b_name)
                    overlap = a_ranks & b_ranks
                    if not overlap:
                        continue
                    # Mirror C's SWAP(low, high) so ``low`` always
                    # starts on the earlier rank.
                    if min(a_ranks) > min(b_ranks):
                        low_name, high_name = b_name, a_name
                    else:
                        low_name, high_name = a_name, b_name
                    # Compare orders at high.minrank — the first
                    # rank where both clusters are present.  C uses
                    # v[0] (the smallest-order member at that rank),
                    # which is what _min_order_at_rank returns.
                    decision_rank = min(high_ranks := _ranks_of(high_name))
                    # (``decision_rank`` is always in ``overlap``
                    # because it's the smaller end of ``high``'s
                    # range and ``overlap`` is non-empty.)
                    lo_ord = _min_order_at_rank(low_name, decision_rank)
                    hi_ord = _min_order_at_rank(high_name, decision_rank)
                    if lo_ord is None or hi_ord is None:
                        # ``low`` might not reach decision_rank; fall
                        # back to any common rank.
                        decision_rank = min(overlap)
                        lo_ord = _min_order_at_rank(low_name, decision_rank)
                        hi_ord = _min_order_at_rank(high_name, decision_rank)
                        if lo_ord is None or hi_ord is None:
                            continue
                    if lo_ord < hi_ord:
                        left_cl, right_cl = low_name, high_name
                    else:
                        left_cl, right_cl = high_name, low_name
                    aux_edges.append((cl_rn[left_cl],
                                      cl_ln[right_cl],
                                      max(1, m), 0))

        # ── 3f. Keepout: external nodes outside clusters ─
        # For each rank, if a non-cluster node is adjacent to a
        # cluster boundary, add a separation edge so the external
        # node can't penetrate the cluster's bbox.
        #
        # Only fires when ``ext`` is truly external — i.e., not in
        # any cluster at all.  When ``ext`` is itself inside another
        # cluster (a sibling or cousin of ``cl``) the separation is
        # already handled by the cluster-hierarchy constraints
        # (section 3d: parent.ln → child.ln and child.rn → parent.rn,
        # plus the per-rank ordering edges built in section 1).
        # Firing this keepout for an in-cluster ``ext`` was the root
        # cause of the ``cluster_6413`` compaction bug on aa1332:
        # at rank 18 the edge ``_crn_cluster_6409 → c6411`` (where
        # c6411 is the rank-adjacent neighbour in a sibling cluster)
        # forced c6411 to sit ~240pt below its paired c6412 because
        # cluster_6409 has multiple rank-spanning members whose
        # rightmost boundary is far from c6412's rank neighbours.
        any_cluster_members: set[str] = set()
        for _cs in node_sets.values():
            any_cluster_members.update(_cs)

        for rank_val, rank_nodes in layout.ranks.items():
            for cl in layout._clusters:
                cl_ranks_nodes: dict[int, list[str]] = {}
                for n in cl.nodes:
                    if n in layout.lnodes:
                        r = layout.lnodes[n].rank
                        cl_ranks_nodes.setdefault(r, []).append(n)
                if rank_val not in cl_ranks_nodes:
                    continue
                cl_at_rank = cl_ranks_nodes[rank_val]
                cl_at_rank.sort(key=lambda n: layout.lnodes[n].order)
                left_node = cl_at_rank[0]
                right_node = cl_at_rank[-1]
                left_order = layout.lnodes[left_node].order
                right_order = layout.lnodes[right_node].order
                margin = int(cl.margin)

                # Node to the LEFT of the cluster
                if left_order > 0:
                    ext = rank_nodes[left_order - 1]
                    if (ext not in node_sets[cl.name]
                            and ext not in any_cluster_members):
                        rw = int(layout.lnodes[ext].width / 2.0)
                        aux_edges.append((ext, cl_ln[cl.name],
                                          max(1, rw + margin), 0))

                # Node to the RIGHT of the cluster
                if right_order < len(rank_nodes) - 1:
                    ext = rank_nodes[right_order + 1]
                    if (ext not in node_sets[cl.name]
                            and ext not in any_cluster_members):
                        lw = int(layout.lnodes[ext].width / 2.0)
                        aux_edges.append((cl_rn[cl.name], ext,
                                          max(1, lw + margin), 0))

    if not aux_edges:
        return False

    # ── Seed: use C-style cumulative initialization ───
    # Match Graphviz make_LR_constraints: for each rank,
    # set positions cumulatively from left to right.
    seed: dict[str, int] = {}
    for rank_val in sorted(layout.ranks.keys()):
        rank_nodes = layout.ranks[rank_val]
        last = 0
        for j, name in enumerate(rank_nodes):
            seed[name] = last
            if j < len(rank_nodes) - 1:
                ln_l = layout.lnodes[name]
                ln_r = layout.lnodes[rank_nodes[j + 1]]
                width = int(ln_l.width / 2.0 + ln_r.width / 2.0
                            + layout.nodesep)
                last += width
    # Cluster boundary nodes: initialize from member positions
    if layout._clusters:
        for cl_obj in layout._clusters:
            cn = cl_obj.name
            member_seeds = [seed.get(n, 0)
                            for n in cl_obj.nodes
                            if n in layout.lnodes]
            if member_seeds:
                m = int(cl_obj.margin)
                if cn in cl_ln:
                    seed[cl_ln[cn]] = min(member_seeds) - m
                if cn in cl_rn:
                    seed[cl_rn[cn]] = max(member_seeds) + m

    # ── Solve ─────────────────────────────────────────
    print(
        f"[TRACE position] aux_graph: total_aux_edges={len(aux_edges)} "
        f"total_aux_nodes={len(aux_nodes)}",
        file=sys.stderr,
    )
    # Log containment edges
    if layout._clusters:
        for cl in layout._clusters:
            cn = cl.name
            if cn in cl_ln and cn in cl_rn:
                print(
                    f"[TRACE position] contain_nodes: {cn} "
                    f"margin={int(cl.margin)}",
                    file=sys.stderr,
                )
    # Log pre-NS positions for real nodes
    for name in sorted(layout.lnodes.keys()):
        ln = layout.lnodes[name]
        if not ln.virtual:
            print(
                f"[TRACE position] pre_ns: {name} "
                f"rank_val={seed.get(name, 0)} "
                f"lw={ln.width/2:.1f} rw={ln.width/2:.1f}",
                file=sys.stderr,
            )
    try:
        ns = _NetworkSimplex(aux_nodes, aux_edges)
        ns.SEARCH_LIMIT = layout.searchsize
        x_ranks = ns.solve(max_iter=layout.nslimit)
        for name, xr in x_ranks.items():
            if name in layout.lnodes:
                layout.lnodes[name].x = float(xr)

        # Log NS-solved positions
        for name in sorted(layout.lnodes.keys()):
            ln = layout.lnodes[name]
            if not ln.virtual:
                print(
                    f"[TRACE position] ns_solved: {name} x_pos={int(ln.x)}",
                    file=sys.stderr,
                )

        # Store ln/rn X positions for cluster bbox computation.
        # The C code uses these directly as cluster X boundaries
        # (dot_compute_bb: LL.x = ND_rank(GD_ln(g))).
        # ``_cl_ln_x`` / ``_cl_rn_x`` are declared on DotGraphInfo;
        # clear here to drop any stale mapping from a prior run.
        if layout._clusters:
            layout._cl_ln_x.clear()
            layout._cl_rn_x.clear()
            for cl_name, ln_name in cl_ln.items():
                if ln_name in x_ranks:
                    layout._cl_ln_x[cl_name] = float(x_ranks[ln_name])
            for cl_name, rn_name in cl_rn.items():
                if rn_name in x_ranks:
                    layout._cl_rn_x[cl_name] = float(x_ranks[rn_name])

        return True
    except Exception as e:
        print(
            f"[TRACE position] ns_x_position FAILED: {e}",
            file=sys.stderr,
        )
        return False


def compute_cluster_boxes(layout):
    """Compute bounding boxes for clusters from positioned nodes.

    C analogue: ``lib/dotgen/position.c:dot_compute_bb()`` and
    ``lib/dotgen/cluster.c`` post-NS bbox finalization.  After the
    NS X solve has placed nodes and cluster ln/rn boundaries, walk
    each cluster's members and compute the (LL, UR) box, expanding
    for cluster labels and margins.

    The bbox is always computed from member node positions + margin.
    When a cluster has a label, the box is expanded so the label
    text doesn't overlap internal nodes.
    """
    for cl in layout._clusters:
        members = [layout.lnodes[n] for n in cl.nodes if n in layout.lnodes]
        if not members:
            continue

        min_x = min(ln.x - ln.width / 2 for ln in members) - cl.margin
        min_y = min(ln.y - ln.height / 2 for ln in members) - cl.margin
        max_x = max(ln.x + ln.width / 2 for ln in members) + cl.margin
        max_y = max(ln.y + ln.height / 2 for ln in members) + cl.margin

        # Expand for cluster label
        if cl.label:
            try:
                fontsize = float(cl.attrs.get("fontsize", 14))
            except (ValueError, TypeError):
                fontsize = 14.0
            label_h = fontsize + 4.0
            labelloc = cl.attrs.get("labelloc", "t")
            if labelloc == "b":
                max_y += label_h
            else:
                min_y -= label_h

        cl.bb = (min_x, min_y, max_x, max_y)
        print(f"[TRACE label] cluster_bb: {cl.name} bb=({min_x:.1f},{min_y:.1f},{max_x:.1f},{max_y:.1f})", file=sys.stderr)


def expand_leaves(layout):
    """Ensure degree-1 (leaf) nodes have proper separation.

    In Graphviz, leaf nodes may have been collapsed during ranking
    and are re-inserted here with proper width.  In our implementation
    leaf nodes are never collapsed, but we ensure they have at least
    ``nodesep`` separation from their sole neighbor by adjusting their
    width if needed.  This prevents leaf nodes from being packed too
    tightly against their parent.

    Mirrors Graphviz ``position.c:expand_leaves()``.
    """
    # Build degree map
    degree: dict[str, int] = {}
    for le in layout.ledges:
        if le.virtual:
            continue
        degree[le.tail_name] = degree.get(le.tail_name, 0) + 1
        degree[le.head_name] = degree.get(le.head_name, 0) + 1

    for name, ln in layout.lnodes.items():
        if ln.virtual:
            continue
        if degree.get(name, 0) == 1:
            # Leaf node: ensure minimum width for spacing
            ln.width = max(ln.width, layout.nodesep * 2)


def insert_flat_label_nodes(layout) -> bool:
    """Insert virtual label nodes for labeled same-rank edges.

    For each labeled flat edge whose endpoints are not adjacent in
    the rank ordering, a virtual node is inserted into the rank
    above, sized to hold the label.  This reserves vertical space
    and allows ``_ns_x_position`` to add separation constraints.

    Returns True if any label nodes were inserted (caller should
    re-run ``_set_ycoords``).

    Mirrors Graphviz ``flat.c:flat_edges()`` + ``flat_node()``.
    """
    inserted = False

    for le in layout.ledges:
        if le.virtual or not le.label:
            continue
        t = layout.lnodes.get(le.tail_name)
        h = layout.lnodes.get(le.head_name)
        if not t or not h or t.rank != h.rank:
            continue

        # Check if endpoints are adjacent
        if abs(t.order - h.order) == 1:
            # Adjacent: store label width as ED_dist on the edge for
            # the separation constraint in _ns_x_position
            le._flat_label_dist = layout._estimate_label_size(
                le.label, 14.0)[0]
            continue

        # Non-adjacent: insert a virtual label node in rank above
        target_rank = t.rank - 1
        if target_rank < 0:
            # Need to create rank -1 (shift all ranks up)
            # For simplicity, place it at rank 0 and shift existing
            # ranks up — this is rare, skip for now
            continue

        if target_rank not in layout.ranks:
            layout.ranks[target_rank] = []

        # Compute label dimensions
        try:
            fs = float(le.edge.attributes.get("fontsize", "14"))
        except (ValueError, AttributeError):
            fs = 14.0
        lw, lh = layout._estimate_label_size(le.label, fs)

        # Create virtual label node
        vn_name = f"_flatlabel_{le.tail_name}_{le.head_name}_{id(le)}"
        from gvpy.engines.layout.dot.dot_layout import LayoutNode
        vn = LayoutNode(name=vn_name)
        vn.virtual = True
        vn.width = lw
        vn.height = lh
        vn.rank = target_rank

        # Insert into rank at midpoint between tail and head order
        mid_order = (t.order + h.order) // 2
        rank_nodes = layout.ranks[target_rank]
        insert_pos = min(mid_order, len(rank_nodes))
        rank_nodes.insert(insert_pos, vn_name)

        # Reassign orders
        for i, name in enumerate(rank_nodes):
            layout.lnodes[name].order = i

        layout.lnodes[vn_name] = vn
        vn.order = insert_pos

        # Store reference: edge → label node for NS constraints
        le._flat_label_vnode = vn_name

        # Create virtual edges from label node to endpoints
        # (these help the crossing minimization and NS positioning)
        from gvpy.engines.layout.dot.dot_layout import LayoutEdge
        ve1 = LayoutEdge(edge=None, tail_name=vn_name,
                         head_name=le.tail_name, minlen=0, weight=1)
        ve1.virtual = True
        ve2 = LayoutEdge(edge=None, tail_name=vn_name,
                         head_name=le.head_name, minlen=0, weight=1)
        ve2.virtual = True
        layout.ledges.extend([ve1, ve2])

        inserted = True

    return inserted


def set_ycoords(layout):
    """Assign Y coordinates to each rank following Graphviz set_ycoords.

    Computes two sets of per-rank half-heights:
    - ``pht1/pht2``: primary (node-only) half-heights
    - ``ht1/ht2``: half-heights expanded by cluster margins and labels

    The inter-rank gap is ``max(pht-gap + ranksep, ht-gap + CL_OFFSET)``.
    """
    max_rank = max((ln.rank for ln in layout.lnodes.values()), default=0)
    min_rank = min((ln.rank for ln in layout.lnodes.values()), default=0)

    # Step 1: primary half-heights from nodes
    pht1: dict[int, float] = {}  # bottom half (toward higher rank index)
    pht2: dict[int, float] = {}  # top half (toward lower rank index)
    for r in range(min_rank, max_rank + 1):
        pht1[r] = 0.0
        pht2[r] = 0.0

    for ln in layout.lnodes.values():
        r = ln.rank
        hh = ln.height / 2.0
        pht1[r] = max(pht1.get(r, 0), hh)
        pht2[r] = max(pht2.get(r, 0), hh)

    # Start with cluster-aware heights = primary heights
    ht1 = dict(pht1)
    ht2 = dict(pht2)

    # Step 2: expand ht1/ht2 for cluster boundaries
    if layout._clusters:
        node_sets = {cl.name: set(cl.nodes) for cl in layout._clusters}

        # Find each node's innermost cluster
        sorted_cls = sorted(layout._clusters,
                            key=lambda c: len(c.nodes), reverse=True)
        node_cluster: dict[str, "LayoutCluster"] = {}
        cl_by_name = {cl.name: cl for cl in layout._clusters}
        for cl in sorted_cls:
            for n in cl.nodes:
                if n in layout.lnodes:
                    node_cluster[n] = cl

        # Per-cluster ht1/ht2 (boundary half-heights)
        cl_ht1: dict[str, float] = {}
        cl_ht2: dict[str, float] = {}

        for name, ln in layout.lnodes.items():
            if ln.virtual:
                continue
            cl = node_cluster.get(name)
            if cl is None:
                continue
            margin = cl.margin if cl.margin > 0 else layout._CL_OFFSET
            hh = ln.height / 2.0 + margin

            # Cluster's min rank → ht2 (top boundary)
            cl_ranks = [layout.lnodes[n].rank for n in cl.nodes
                        if n in layout.lnodes]
            if not cl_ranks:
                continue
            cl_min_r = min(cl_ranks)
            cl_max_r = max(cl_ranks)

            if ln.rank == cl_min_r:
                cl_ht2[cl.name] = max(cl_ht2.get(cl.name, 0), hh)
            if ln.rank == cl_max_r:
                cl_ht1[cl.name] = max(cl_ht1.get(cl.name, 0), hh)

        # Step 3: propagate cluster heights through nesting (clust_ht)
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

        def _clust_ht(cl_name: str):
            cl = cl_by_name[cl_name]
            cl_ranks = [layout.lnodes[n].rank for n in cl.nodes
                        if n in layout.lnodes]
            if not cl_ranks:
                return
            cl_min_r = min(cl_ranks)
            cl_max_r = max(cl_ranks)
            margin = cl.margin if cl.margin > 0 else layout._CL_OFFSET

            h1 = cl_ht1.get(cl_name, 0)
            h2 = cl_ht2.get(cl_name, 0)

            for child_name in children_of.get(cl_name, []):
                _clust_ht(child_name)
                child = cl_by_name[child_name]
                child_ranks = [layout.lnodes[n].rank for n in child.nodes
                               if n in layout.lnodes]
                if not child_ranks:
                    continue
                child_min_r = min(child_ranks)
                child_max_r = max(child_ranks)
                if child_max_r == cl_max_r:
                    h1 = max(h1, cl_ht1.get(child_name, 0) + margin)
                if child_min_r == cl_min_r:
                    h2 = max(h2, cl_ht2.get(child_name, 0) + margin)

            # Add cluster label height
            if cl.label:
                label_h = 14.0  # approximate label height
                h2 += label_h

            cl_ht1[cl_name] = h1
            cl_ht2[cl_name] = h2

            # Propagate to global rank table
            ht1[cl_max_r] = max(ht1.get(cl_max_r, 0), h1)
            ht2[cl_min_r] = max(ht2.get(cl_min_r, 0), h2)

        for top_cl in children_of.get(None, []):
            _clust_ht(top_cl)

    # Step 4: assign Y coordinates
    rank_y: dict[int, float] = {}
    rank_y[min_rank] = ht1.get(min_rank, 0)

    for r in range(min_rank + 1, max_rank + 1):
        # Node-driven gap
        d0 = pht2.get(r, 0) + pht1.get(r - 1, 0) + layout.ranksep
        # Cluster-driven gap
        d1 = ht2.get(r, 0) + ht1.get(r - 1, 0) + layout._CL_OFFSET
        rank_y[r] = rank_y[r - 1] + max(d0, d1)

    for ln in layout.lnodes.values():
        ln.y = rank_y.get(ln.rank, ln.rank * layout.ranksep)


def simple_x_position(layout):
    """Heuristic X positioning for non-clustered graphs.

    No direct C analogue — this is a Python-specific simple
    placement used as a starting point for ``median_x_improvement``
    when there are no clusters.  C uses ``lib/dotgen/position.c``
    NS-based positioning unconditionally; this Python path is a
    legacy fallback that pre-dates the NS X solver in
    :func:`ns_x_position`.
    """
    # Count edges incident to each node to estimate routing channel space
    edge_count: dict[str, int] = {}
    for le in layout.ledges:
        edge_count[le.tail_name] = edge_count.get(le.tail_name, 0) + 1
        edge_count[le.head_name] = edge_count.get(le.head_name, 0) + 1

    # Build innermost cluster map for inter-cluster spacing
    node_cluster: dict[str, str] = {}
    if layout._clusters:
        for cl in sorted(layout._clusters, key=lambda c: len(c.nodes), reverse=True):
            for n in cl.nodes:
                if n in layout.lnodes:
                    node_cluster[n] = cl.name
    cluster_gap = layout.nodesep * 2  # extra gap between different clusters

    for rank_val, rank_nodes in layout.ranks.items():
        x = 0.0
        prev_cluster = None
        for name in rank_nodes:
            ln = layout.lnodes[name]
            cur_cluster = node_cluster.get(name, "")

            # Add inter-cluster gap when crossing cluster boundaries
            if prev_cluster is not None and cur_cluster != prev_cluster:
                x += cluster_gap

            ln.x = x + ln.width / 2.0
            # Add routing channel space proportional to edge count
            ec = edge_count.get(name, 0)
            channel_space = min(ec * 8.0, 80.0)  # up to 80pt extra
            x += ln.width + layout.nodesep + channel_space
            prev_cluster = cur_cluster


def median_x_improvement(layout):
    """Iteratively adjust X positions toward median of connected neighbors.

    Similar to the Graphviz median heuristic: for each node, compute
    the median X of its connected neighbors in adjacent ranks and shift
    toward it, subject to separation constraints.
    """
    # Build adjacency: for each node, connected nodes in adjacent ranks
    adj: dict[str, list[str]] = {}
    for le in layout.ledges:
        adj.setdefault(le.tail_name, []).append(le.head_name)
        adj.setdefault(le.head_name, []).append(le.tail_name)

    for _iteration in range(8):
        moved = False
        for rank_val in sorted(layout.ranks.keys()):
            rank_nodes = layout.ranks[rank_val]
            for idx, name in enumerate(rank_nodes):
                ln = layout.lnodes[name]
                neighbors = adj.get(name, [])
                if not neighbors:
                    continue
                # Median X of neighbors
                neighbor_xs = sorted(layout.lnodes[n].x for n in neighbors
                                     if n in layout.lnodes)
                if not neighbor_xs:
                    continue
                mid = len(neighbor_xs) // 2
                median_x = neighbor_xs[mid]

                # Compute allowed range from separation constraints
                min_x = -1e9
                max_x = 1e9
                if idx > 0:
                    left = layout.lnodes[rank_nodes[idx - 1]]
                    min_x = left.x + left.width / 2.0 + layout.nodesep + ln.width / 2.0
                if idx < len(rank_nodes) - 1:
                    right = layout.lnodes[rank_nodes[idx + 1]]
                    max_x = right.x - right.width / 2.0 - layout.nodesep - ln.width / 2.0

                target = max(min_x, min(max_x, median_x))
                if abs(target - ln.x) > 0.5:
                    ln.x = target
                    moved = True
        if not moved:
            break

# ── Hierarchical (bottom-up) X positioning ──────────────


def bottomup_ns_x_position(layout):
    """Assign X coordinates bottom-up through the cluster hierarchy.

    No direct C analogue.  C's :func:`ns_x_position` (which mirrors
    ``lib/dotgen/position.c:create_aux_edges`` + ``rank()`` +
    ``set_xcoords()``) handles clusters in one global NS solve.
    This Python function is a fallback for the case where the
    global NS fails to converge — it solves each cluster level
    independently bottom-up, treating already-positioned child
    clusters as rigid blocks.

    After the cluster-cycle bug fixes of 2026-04-12, the global NS
    in :func:`ns_x_position` converges reliably and this fallback
    is rarely if ever exercised on real graphs.
    """
    # _NetworkSimplex from its own ns_solver module.
    from gvpy.engines.layout.dot.ns_solver import _NetworkSimplex

    node_sets = {cl.name: set(cl.nodes) for cl in layout._clusters}
    cl_by_name = {cl.name: cl for cl in layout._clusters}

    # Build tree from subgraph structure
    cl_names_set = set(node_sets.keys())
    tree_parent: dict[str, str | None] = {}
    def _walk(g, parent_cl):
        for sub_name, sub in g.subgraphs.items():
            if sub_name in cl_names_set:
                tree_parent[sub_name] = parent_cl
                _walk(sub, sub_name)
            else:
                _walk(sub, parent_cl)
    _walk(layout.graph, None)

    tree_children: dict[str | None, list[str]] = {}
    for cn, par in tree_parent.items():
        tree_children.setdefault(par, []).append(cn)

    # Depth of each cluster
    depth_of: dict[str, int] = {}
    for cn in tree_parent:
        d, cur = 0, cn
        while tree_parent.get(cur) is not None:
            d += 1
            cur = tree_parent[cur]
        depth_of[cn] = d
    max_depth = max(depth_of.values()) if depth_of else 0

    # Direct nodes per cluster
    direct_of: dict[str, set[str]] = {}
    for cl in layout._clusters:
        child_nodes: set[str] = set()
        for kid in tree_children.get(cl.name, []):
            child_nodes.update(node_sets.get(kid, set()))
        direct_of[cl.name] = node_sets[cl.name] - child_nodes

    # Track each cluster's computed X extent (min_x, max_x)
    cl_extent: dict[str, tuple[float, float]] = {}

    # Edge adjacency
    adj: dict[str, list[tuple[str, int]]] = {}  # node → [(neighbor, weight)]
    for le in layout.ledges:
        adj.setdefault(le.tail_name, []).append((le.head_name, le.weight))
        adj.setdefault(le.head_name, []).append((le.tail_name, le.weight))

    _vn_counter = [0]
    def _vnode(prefix: str = "_bns") -> str:
        _vn_counter[0] += 1
        return f"{prefix}_{_vn_counter[0]}"

    def _solve_level(cl_name: str | None):
        """Run NS for one cluster (or root level if None).

        Each child cluster has one block vnode per rank it spans,
        chained with bidirectional weight-1000 edges to stay aligned.
        Separation edges between items at each rank + all-pairs
        sibling separation prevent overlaps.
        """
        if cl_name is not None:
            direct = direct_of[cl_name]
            children = tree_children.get(cl_name, [])
            margin = cl_by_name[cl_name].margin
        else:
            all_cl_nodes: set[str] = set()
            for cl in layout._clusters:
                all_cl_nodes.update(cl.nodes)
            direct = {n for n in layout.lnodes
                      if not layout.lnodes[n].virtual
                      and n not in all_cl_nodes}
            children = tree_children.get(None, [])
            margin = 0.0

        all_ranks: set[int] = set()
        for n in direct:
            if n in layout.lnodes:
                all_ranks.add(layout.lnodes[n].rank)
        for kid in children:
            for n in node_sets.get(kid, set()):
                if n in layout.lnodes:
                    all_ranks.add(layout.lnodes[n].rank)
        if not all_ranks:
            return

        aux_nodes: list[str] = []
        aux_edges: list[tuple[str, str, int, int]] = []

        # ── Block vnodes per child cluster ───────────────
        block_nodes: dict[str, dict[int, str]] = {}
        block_width: dict[str, float] = {}

        for kid in children:
            if kid not in cl_extent:
                continue
            kx1, kx2 = cl_extent[kid]
            bw = kx2 - kx1
            block_width[kid] = bw
            block_nodes[kid] = {}
            kid_ranks = sorted(set(
                layout.lnodes[n].rank for n in node_sets[kid]
                if n in layout.lnodes
            ))
            prev_bn = None
            for r in kid_ranks:
                bn = _vnode("_blk")
                block_nodes[kid][r] = bn
                aux_nodes.append(bn)
                if prev_bn is not None:
                    aux_edges.append((prev_bn, bn, 0, 1000))
                    aux_edges.append((bn, prev_bn, 0, 1000))
                prev_bn = bn

        for n in direct:
            if n in layout.lnodes:
                aux_nodes.append(n)

        if len(aux_nodes) < 2:
            for n in aux_nodes:
                if n in layout.lnodes:
                    layout.lnodes[n].x = 0
            return

        # ── Per-rank separation ──────────────────────────
        for rank_val in sorted(all_ranks):
            rank_list = layout.ranks.get(rank_val, [])
            items: list[str] = []
            seen_kids: set[str] = set()
            for n in rank_list:
                if n in direct and n in layout.lnodes:
                    items.append(n)
                else:
                    for kid in children:
                        if kid in block_nodes and rank_val in block_nodes[kid]:
                            if n in node_sets.get(kid, set()) and kid not in seen_kids:
                                items.append(block_nodes[kid][rank_val])
                                seen_kids.add(kid)
                                break
            for i in range(len(items) - 1):
                left, right = items[i], items[i + 1]
                lw = (layout.lnodes[left].width / 2 if left in layout.lnodes
                      else block_width.get(next((k for k, rs in block_nodes.items()
                                                 if left in rs.values()), ""), 20) / 2)
                rw = (layout.lnodes[right].width / 2 if right in layout.lnodes
                      else block_width.get(next((k for k, rs in block_nodes.items()
                                                 if right in rs.values()), ""), 20) / 2)
                aux_edges.append((left, right, max(1, int(lw + rw + layout.nodesep)), 0))

        # ── Adjacent sibling separation ────────────────────
        def _avg_order(kid):
            orders = [layout.lnodes[n].order for n in node_sets.get(kid, set())
                      if n in layout.lnodes]
            return sum(orders) / len(orders) if orders else 0

        kids_sorted = sorted([k for k in children if k in block_nodes], key=_avg_order)
        for i in range(len(kids_sorted) - 1):
            lk, rk = kids_sorted[i], kids_sorted[i + 1]
            sep = int(block_width.get(lk, 20) / 2 + block_width.get(rk, 20) / 2
                      + layout.nodesep + margin)
            lr = set(block_nodes[lk].keys())
            rr = set(block_nodes[rk].keys())
            shared = lr & rr
            for r in shared:
                aux_edges.append((block_nodes[lk][r], block_nodes[rk][r], max(1, sep), 0))
            if not shared:
                # Single edge between first-rank block nodes
                aux_edges.append((block_nodes[lk][min(lr)], block_nodes[rk][min(rr)],
                                  max(1, sep), 0))

        # ── Alignment edges ──────────────────────────────
        node_to_block: dict[str, str] = {}
        for kid in children:
            if kid in block_nodes:
                for n in node_sets.get(kid, set()):
                    if n in layout.lnodes:
                        r = layout.lnodes[n].rank
                        if r in block_nodes[kid]:
                            node_to_block[n] = block_nodes[kid][r]

        level_set = set(aux_nodes)
        seen_align: set[tuple[str, str]] = set()

        # Direct node <-> direct node / block alignment
        for n in direct:
            for neighbor, w in adj.get(n, []):
                target = neighbor if neighbor in level_set else node_to_block.get(neighbor)
                if target and target in level_set and target != n:
                    key = (min(n, target), max(n, target))
                    if key not in seen_align:
                        seen_align.add(key)
                        sn = _vnode("_sn")
                        aux_nodes.append(sn)
                        aux_edges.append((sn, n, 0, w))
                        aux_edges.append((sn, target, 0, w))

        # Block <-> block alignment for edges between child clusters.
        # This is critical when a parent cluster has NO direct nodes
        # (all nodes are in child wrapper clusters forming a pipeline).
        for kid in children:
            for n in node_sets.get(kid, set()):
                for neighbor, w in adj.get(n, []):
                    n_bn = node_to_block.get(n)
                    t_bn = node_to_block.get(neighbor)
                    if n_bn and t_bn and n_bn != t_bn:
                        if n_bn in level_set and t_bn in level_set:
                            key = (min(n_bn, t_bn), max(n_bn, t_bn))
                            if key not in seen_align:
                                seen_align.add(key)
                                sn = _vnode("_sn")
                                aux_nodes.append(sn)
                                aux_edges.append((sn, n_bn, 0, w))
                                aux_edges.append((sn, t_bn, 0, w))

        if not aux_edges:
            return

        # ── Seed + Solve ─────────────────────────────────
        seed: dict[str, int] = {}
        for n in aux_nodes:
            if n in layout.lnodes:
                seed[n] = int(layout.lnodes[n].x)
        for kid in children:
            if kid in cl_extent and kid in block_nodes:
                center = int(sum(cl_extent[kid]) / 2)
                for bn in block_nodes[kid].values():
                    seed[bn] = center

        n_aux = len(aux_nodes)
        try:
            ns = _NetworkSimplex(aux_nodes, aux_edges)
            ns.SEARCH_LIMIT = layout.searchsize
            x_ranks = ns.solve(max_iter=max(n_aux * 4, 400),
                               initial_ranks=seed)
        except Exception:
            return

        for n in direct:
            if n in x_ranks and n in layout.lnodes:
                layout.lnodes[n].x = float(x_ranks[n])

        for kid in children:
            if kid not in block_nodes or kid not in cl_extent:
                continue
            first_r = min(block_nodes[kid].keys())
            bn = block_nodes[kid][first_r]
            if bn not in x_ranks:
                continue
            new_center = float(x_ranks[bn])
            old_x1, old_x2 = cl_extent[kid]
            old_center = (old_x1 + old_x2) / 2
            shift = new_center - old_center
            if abs(shift) > 0.5:
                for n in node_sets[kid]:
                    if n in layout.lnodes:
                        layout.lnodes[n].x += shift
                cl_extent[kid] = (old_x1 + shift, old_x2 + shift)

        if cl_name is not None:
            xs_min = [layout.lnodes[n].x - layout.lnodes[n].width / 2
                      for n in node_sets[cl_name] if n in layout.lnodes]
            xs_max = [layout.lnodes[n].x + layout.lnodes[n].width / 2
                      for n in node_sets[cl_name] if n in layout.lnodes]
            if xs_min:
                cl_extent[cl_name] = (min(xs_min) - margin, max(xs_max) + margin)

    # ── Process bottom-up ────────────────────────────
    for d in range(max_depth, -1, -1):
        for cl_name in sorted(depth_of, key=lambda c: depth_of[c]):
            if depth_of[cl_name] == d:
                _solve_level(cl_name)

    # Root level
    _solve_level(None)


def resolve_cluster_overlaps(layout):
    """Push overlapping sibling clusters apart in the cross-rank direction.

    No direct C analogue.  C avoids the need for this entirely
    because its NS X solver (``lib/dotgen/position.c``
    ``create_aux_edges`` / ``pos_clusters``) enforces sibling
    cluster separation as part of the constraint graph.  This
    Python helper is a post-pass safety net for cases where the
    global NS could not enforce all constraints (typically when the
    cycle-detection in :func:`ns_x_position` had to relax some
    edges).

    Walks the cluster tree top-down.  For each set of siblings,
    detects 2D bbox overlaps and shifts the overlapping cluster
    (and all its internal nodes) in the cross-rank direction until
    the overlap is eliminated.  Iterates until no overlaps remain.
    """
    if not layout._clusters:
        return

    node_sets = {cl.name: set(cl.nodes) for cl in layout._clusters}
    cl_by_name = {cl.name: cl for cl in layout._clusters}

    # Build tree from subgraph structure
    cl_names_set = set(node_sets.keys())
    tree_parent: dict[str, str | None] = {}
    def _walk(g, parent_cl):
        for sub_name, sub in g.subgraphs.items():
            if sub_name in cl_names_set:
                tree_parent[sub_name] = parent_cl
                _walk(sub, sub_name)
            else:
                _walk(sub, parent_cl)
    _walk(layout.graph, None)

    tree_children: dict[str | None, list[str]] = {}
    for cn, par in tree_parent.items():
        tree_children.setdefault(par, []).append(cn)

    is_lr = layout.rankdir in ("LR", "RL")
    gap = layout.nodesep

    def _shift_cluster(cl_name: str, dx: float, dy: float):
        """Shift all nodes in a cluster by (dx, dy)."""
        for n in node_sets[cl_name]:
            if n in layout.lnodes:
                layout.lnodes[n].x += dx
                layout.lnodes[n].y += dy

    for _pass in range(8):
        layout._compute_cluster_boxes()
        moved = False

        # Process each set of siblings
        for parent in list(tree_children.keys()):
            siblings = tree_children[parent]
            if len(siblings) < 2:
                continue

            # Sort siblings by their bbox center in the cross-rank axis
            def _center(cn):
                cl = cl_by_name.get(cn)
                if not cl or not cl.bb:
                    return 0
                if is_lr:
                    return (cl.bb[1] + cl.bb[3]) / 2  # Y center
                else:
                    return (cl.bb[0] + cl.bb[2]) / 2  # X center

            sibs = sorted(siblings, key=_center)

            # Check all pairs and push apart
            for i in range(len(sibs)):
                a = cl_by_name.get(sibs[i])
                if not a or not a.bb:
                    continue
                for j in range(i + 1, len(sibs)):
                    b = cl_by_name.get(sibs[j])
                    if not b or not b.bb:
                        continue

                    ax1, ay1, ax2, ay2 = a.bb
                    bx1, by1, bx2, by2 = b.bb

                    # Check 2D overlap
                    if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
                        # Compute overlap in cross-rank direction
                        if is_lr:
                            # Push in Y
                            overlap = min(ay2, by2) - max(ay1, by1) + gap
                            # Push b downward (positive Y)
                            _shift_cluster(sibs[j], 0, overlap)
                        else:
                            # Push in X
                            overlap = min(ax2, bx2) - max(ax1, bx1) + gap
                            _shift_cluster(sibs[j], overlap, 0)
                        moved = True
                        # Recompute b's bbox for subsequent pair checks
                        layout._compute_cluster_boxes()

        if not moved:
            break


def post_rankdir_keepout(layout):
    """Push non-member nodes out of sibling cluster bboxes.

    No direct C analogue.  C handles non-cluster-member separation
    within ``lib/dotgen/position.c`` via the keepout edges added by
    ``create_aux_edges`` (section 3f in our :func:`ns_x_position`).
    This Python helper is a post-rankdir safety net for cases where
    the NS solver couldn't enforce all keepout edges (typically
    because they would have created cycles in the constraint
    graph).

    Runs after ``apply_rankdir`` so coordinates are in the final
    space.  Only pushes in the **cross-rank** direction (X for LR/RL,
    Y for TB/BT), never in the rank direction, because rank positions
    are fixed by phase 1.  Recomputes cluster boxes after each pass.
    """
    if not layout._clusters:
        return

    cl_node_sets = {cl.name: set(cl.nodes) for cl in layout._clusters}

    # Build tree parent for sibling detection
    cl_names_set = set(cl_node_sets.keys())
    tree_parent: dict[str, str | None] = {}
    def _walk(g, parent_cl):
        for sub_name, sub in g.subgraphs.items():
            if sub_name in cl_names_set:
                tree_parent[sub_name] = parent_cl
                _walk(sub, sub_name)
            else:
                _walk(sub, parent_cl)
    _walk(layout.graph, None)

    tree_children: dict[str | None, list[str]] = {}
    for cn, par in tree_parent.items():
        tree_children.setdefault(par, []).append(cn)

    # Node → innermost cluster
    node_home: dict[str, str | None] = {}
    for cl in sorted(layout._clusters, key=lambda c: len(c.nodes), reverse=True):
        for n in cl.nodes:
            node_home[n] = cl.name

    # Determine which axis is the cross-rank axis (the one NS controls)
    # For LR/RL: cross-rank is Y (vertical).  For TB/BT: cross-rank is X.
    push_y = layout.rankdir in ("LR", "RL")

    for _pass in range(4):
        layout._compute_cluster_boxes()
        moved = False

        for name, ln in layout.lnodes.items():
            if ln.virtual:
                continue
            hw = ln.width / 2.0
            hh = ln.height / 2.0
            home = node_home.get(name)
            home_parent = tree_parent.get(home) if home else None

            for sib_name in tree_children.get(home_parent, []):
                if sib_name == home:
                    continue
                cl = next((c for c in layout._clusters if c.name == sib_name), None)
                if not cl or not cl.bb:
                    continue
                if name in cl_node_sets[cl.name]:
                    continue

                bx1, by1, bx2, by2 = cl.bb
                x_overlap = (ln.x - hw < bx2) and (ln.x + hw > bx1)
                y_overlap = (ln.y - hh < by2) and (ln.y + hh > by1)

                if x_overlap and y_overlap:
                    gap = layout.nodesep
                    if push_y:
                        # LR/RL: push in Y only
                        y_pen_top = by2 - (ln.y - hh)
                        y_pen_bottom = (ln.y + hh) - by1
                        if y_pen_top < y_pen_bottom:
                            ln.y = by1 - hh - gap
                        else:
                            ln.y = by2 + hh + gap
                    else:
                        # TB/BT: push in X only
                        x_pen_left = bx2 - (ln.x - hw)
                        x_pen_right = (ln.x + hw) - bx1
                        if x_pen_left < x_pen_right:
                            ln.x = bx1 - hw - gap
                        else:
                            ln.x = bx2 + hw + gap
                    moved = True

        if not moved:
            break


def center_ranks(layout):
    """Horizontally center each rank within the widest rank.

    No direct C analogue.  C's NS X positioning produces ranks that
    are already balanced left-to-right via the cluster ln/rn
    constraints in ``lib/dotgen/position.c``.  This Python helper
    is part of the legacy non-cluster path
    (:func:`simple_x_position` + :func:`median_x_improvement`) and
    is only invoked when there are no clusters.
    """
    rank_widths = {}
    for rank_val, rank_nodes in layout.ranks.items():
        if rank_nodes:
            first = layout.lnodes[rank_nodes[0]]
            last = layout.lnodes[rank_nodes[-1]]
            rank_widths[rank_val] = (last.x + last.width / 2.0) - (first.x - first.width / 2.0)
        else:
            rank_widths[rank_val] = 0

    max_width = max(rank_widths.values()) if rank_widths else 0

    for rank_val, rank_nodes in layout.ranks.items():
        offset = (max_width - rank_widths[rank_val]) / 2.0
        for name in rank_nodes:
            layout.lnodes[name].x += offset


def apply_rankdir(layout):
    """Rotate / flip coordinates for the requested rankdir.

    C analogue: ``lib/dotgen/position.c`` rankdir handling and
    ``lib/common/postproc.c:translate()``.  C's layout pipeline
    runs internally in TB mode and rotates the final coordinates
    based on ``GD_rankdir`` at the end.  This Python function does
    the same:
      - TB: identity
      - BT: flip Y (``y -> max_y - y``)
      - LR: swap (x, y) and swap (width, height)
      - RL: swap then flip Y
    """
    if layout.rankdir == "TB":
        return
    elif layout.rankdir == "BT":
        max_y = max(ln.y for ln in layout.lnodes.values()) if layout.lnodes else 0
        for ln in layout.lnodes.values():
            ln.y = max_y - ln.y
    elif layout.rankdir == "LR":
        for ln in layout.lnodes.values():
            ln.x, ln.y = ln.y, ln.x
            ln.width, ln.height = ln.height, ln.width
    elif layout.rankdir == "RL":
        max_y = max(ln.y for ln in layout.lnodes.values()) if layout.lnodes else 0
        for ln in layout.lnodes.values():
            old_x, old_y = ln.x, ln.y
            ln.x = max_y - old_y
            ln.y = old_x
            ln.width, ln.height = ln.height, ln.width

