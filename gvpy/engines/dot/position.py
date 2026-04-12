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
    from gvpy.engines.dot.dot_layout import DotGraphInfo


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
    # Lazy import to avoid circular dependency: dot_layout defines
    # _NetworkSimplex at module level and imports this module for
    # the phase3_position entry point.
    from gvpy.engines.dot.dot_layout import _NetworkSimplex

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

        # ── 3b. Containment: ln → node, node → rn ───
        # (contain_nodes in C code)
        for cl in layout._clusters:
            margin = int(cl.margin)
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
            margin = int(cl_by_name[par].margin)
            par_bl = cl_border_l.get(par, 0.0)
            par_br = cl_border_r.get(par, 0.0)
            aux_edges.append((cl_ln[par], cl_ln[cl_name],
                              max(1, int(margin + par_bl)), 0))
            aux_edges.append((cl_rn[cl_name], cl_rn[par],
                              max(1, int(margin + par_br)), 0))

        # ── 3e. Sibling separation ────────────────────
        # DISABLED: average-order-based sibling separation conflicts
        # with per-rank separation when two sibling clusters have
        # their average X order differ across ranks.  That creates
        # cycles in the constraint graph (cl_A._crn → cl_B._cln via
        # avg-order sibling sep, while at some rank c_B_mem → c_A_mem
        # via rank separation, producing cl_A → cl_B → cl_A).
        # Per-rank separation edges already ensure sibling clusters
        # don't overlap in ranks they share.  For ranks they don't
        # share, keepout edges (3f) handle adjacent external nodes.
        _sibling_separation_enabled = False
        def _avg_order(cl_name: str) -> float:
            orders = [layout.lnodes[n].order
                      for n in node_sets[cl_name]
                      if n in layout.lnodes]
            return sum(orders) / len(orders) if orders else 0

        if _sibling_separation_enabled:
            for par in list(tree_children.keys()):
                siblings = tree_children[par]
                if len(siblings) < 2:
                    continue
                # Sort siblings by average order
                siblings_sorted = sorted(siblings, key=_avg_order)
                for i in range(len(siblings_sorted) - 1):
                    left_cl = siblings_sorted[i]
                    right_cl = siblings_sorted[i + 1]
                    # Only add if they overlap in rank range
                    left_ranks = {layout.lnodes[n].rank
                                  for n in node_sets[left_cl]
                                  if n in layout.lnodes}
                    right_ranks = {layout.lnodes[n].rank
                                   for n in node_sets[right_cl]
                                   if n in layout.lnodes}
                    if left_ranks & right_ranks:
                        m = int(cl_by_name.get(par, cl_by_name.get(
                            left_cl, layout._clusters[0])).margin
                            if par else 8)
                        aux_edges.append((cl_rn[left_cl],
                                          cl_ln[right_cl],
                                          max(1, m), 0))

        # ── 3f. Keepout: external nodes outside clusters ─
        # For each rank, if a non-cluster node is adjacent to a
        # cluster boundary, add separation edge.
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
                    if ext not in node_sets[cl.name]:
                        rw = int(layout.lnodes[ext].width / 2.0)
                        aux_edges.append((ext, cl_ln[cl.name],
                                          max(1, rw + margin), 0))

                # Node to the RIGHT of the cluster
                if right_order < len(rank_nodes) - 1:
                    ext = rank_nodes[right_order + 1]
                    if ext not in node_sets[cl.name]:
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
        if layout._clusters:
            layout._cl_ln_x = {}
            layout._cl_rn_x = {}
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
