"""Cluster discovery, parent tree, and post-layout bbox computation.

See: ``lib/fdpgen/clusteredges.c`` (entry: ``compoundEdges``,
``objectList``).

Phase A of the cluster-aware fdp routing port (TODO §4.x).  This
module gives ``FdpLayout`` the same cluster awareness that the
dot engine has, scaled down for fdp's flat (no-rank) layout
model.

Responsibilities
----------------
- **Discovery** (:func:`discover_clusters`): walk
  ``layout.graph.subgraphs`` recursively; record every
  ``cluster*``-named subgraph as a :class:`FdpCluster` with its
  direct + transitive node membership, label, margin, and
  visual attributes.

- **Parent tree** (built during discovery): each cluster's
  immediate parent cluster (or ``None`` if it sits directly
  under the root graph).  Mirrors C's ``GPARENT`` macro.

- **Level map**: depth from the root graph (root = 0,
  top-level clusters = 1, nested = 2, ...).  Mirrors C's
  ``LEVEL(graph)`` macro used by ``raiseLevel`` /
  ``objectList``.

- **Node → cluster map** (:func:`build_node_to_cluster`):
  PARENT(node) — points to the **innermost** cluster
  containing the node, mirroring C's ``ND_clust(n)`` /
  ``PARENT(n)``.  Nodes outside any cluster map to ``None``.

- **Post-layout bbox** (:func:`compute_cluster_bboxes`):
  after the force-directed pass settles, fill
  ``cluster.bb`` from member node positions plus margin.
  Required by ``compoundEdges`` to construct cluster-shaped
  obstacles.

The dot engine has equivalent helpers in
``gvpy.engines.layout.dot.cluster`` but they are tied to
dot's rank-and-order pipeline (cluster-overlap separation,
sibling-shifting, dedup-by-edge-reference) — fdp doesn't
need any of that.  This module is the minimal subset.

API surface
-----------
- :class:`FdpCluster`
- :func:`discover_clusters` — call from
  ``FdpLayout._init_from_graph``.
- :func:`build_node_to_cluster` — call after discovery.
- :func:`compute_cluster_bboxes` — call after overlap removal,
  before ``route_edges`` / ``compoundEdges``.

Trace channel: ``GVPY_TRACE_FDP=1`` emits
``[TRACE fdp_cluster] ...`` lines on stderr.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.engines.layout.fdp.fdp_layout import FdpLayout


# ─────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────


@dataclass
class FdpCluster:
    """Per-cluster layout state for fdp.

    Mirrors the relevant subset of C ``graph_t`` fields
    accessed via ``GD_*`` macros for cluster subgraphs.

    - ``name``: subgraph name (``cluster*`` prefix).
    - ``direct_nodes``: nodes literally written inside this
      subgraph in the .dot source (excluding nested cluster
      members).  Used by :func:`build_node_to_cluster` to
      decide PARENT(n).
    - ``nodes``: transitive membership including descendants.
      Used for bbox computation.
    - ``margin``: cluster bbox margin in points (mirrors C's
      ``late_int(g, G_margin, CL_OFFSET, 0)`` for fdp the
      default is 8 pt = ``CL_OFFSET``).
    - ``label``: cluster label text (raw, unparsed).
    - ``attrs``: visual attributes pass-through for renderer.
    - ``bb``: post-layout bounding box in points
      ``(x_min, y_min, x_max, y_max)`` — set by
      :func:`compute_cluster_bboxes`.  Default
      ``(0, 0, 0, 0)`` means "not yet computed".
    """

    name: str
    direct_nodes: list[str] = field(default_factory=list)
    nodes: list[str] = field(default_factory=list)
    margin: float = 8.0
    label: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    bb: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


def _trace(msg: str) -> None:
    if os.environ.get("GVPY_TRACE_FDP", "") == "1":
        print(f"[TRACE fdp_cluster] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────────────────────────


_VISUAL_ATTRS = (
    "color", "fillcolor", "bgcolor", "pencolor",
    "fontcolor", "fontname", "fontsize", "style",
    "penwidth", "peripheries", "labelloc", "labeljust",
    "tooltip", "URL", "href", "target", "id", "class",
    "colorscheme", "gradientangle",
)


def _all_nodes_recursive(layout: "FdpLayout", sub: "Graph",
                         seen: Optional[set[str]] = None) -> list[str]:
    """Return the union of node names directly in ``sub`` plus all
    descendants, restricted to nodes ``layout`` already knows about.
    """
    if seen is None:
        seen = set()
    for n in sub.nodes:
        if n in layout.lnodes:
            seen.add(n)
    for child in sub.subgraphs.values():
        _all_nodes_recursive(layout, child, seen)
    return list(seen)


def _scan_subgraph(layout: "FdpLayout", sub: "Graph",
                   parent_cluster: Optional[FdpCluster],
                   level: int) -> None:
    """Recursive helper: scan one subgraph; if it's a cluster, add
    it; descend into all children carrying the right parent.
    """
    for sub_name, child in sub.subgraphs.items():
        is_cluster = sub_name.startswith("cluster")
        if is_cluster:
            label = child.get_graph_attr("label") or ""
            margin_str = child.get_graph_attr("margin")
            try:
                margin = float(margin_str) if margin_str else 8.0
            except ValueError:
                margin = 8.0

            attrs: dict[str, str] = {}
            for a in _VISUAL_ATTRS:
                v = child.get_graph_attr(a)
                if v:
                    attrs[a] = v

            # Direct membership = nodes literally inside this
            # subgraph's own .nodes list, intersected with
            # known layout nodes.
            direct = [n for n in child.nodes if n in layout.lnodes]
            # Transitive = direct + everything in nested clusters.
            transitive = _all_nodes_recursive(layout, child)

            cl = FdpCluster(
                name=sub_name,
                direct_nodes=direct,
                nodes=transitive,
                margin=margin,
                label=label,
                attrs=attrs,
            )
            layout._clusters.append(cl)
            layout._cluster_parent[sub_name] = (
                parent_cluster.name if parent_cluster else None
            )
            layout._cluster_level[sub_name] = level

            # Descend with this cluster as the new parent and
            # depth + 1.
            _scan_subgraph(layout, child, cl, level + 1)
        else:
            # Non-cluster subgraph: descend without changing
            # parent or level.  Mirrors C's behaviour where
            # only ``cluster*`` subgraphs participate in the
            # cluster tree.
            _scan_subgraph(layout, child, parent_cluster, level)


def discover_clusters(layout: "FdpLayout") -> None:
    """Populate ``layout._clusters`` + parent / level maps.

    Idempotent — clears any prior state before scanning.  Call
    once from ``FdpLayout._init_from_graph`` after ``lnodes`` is
    built (the discovery filters node names against
    ``layout.lnodes``).

    See: ``lib/fdpgen/clusteredges.c`` and ``lib/dotgen/cluster.c``.
    """
    layout._clusters = []
    layout._cluster_parent = {}     # name -> parent name or None
    layout._cluster_level = {}       # name -> int (1 = top-level)

    _scan_subgraph(layout, layout.graph, parent_cluster=None, level=1)

    if layout._clusters:
        _trace(
            f"discovered {len(layout._clusters)} cluster(s); "
            f"top-level={sum(1 for n in layout._cluster_parent if layout._cluster_parent[n] is None)} "
            f"max_level={max(layout._cluster_level.values(), default=0)}"
        )
        for cl in layout._clusters:
            _trace(
                f"  {cl.name}: direct={len(cl.direct_nodes)} "
                f"transitive={len(cl.nodes)} "
                f"parent={layout._cluster_parent[cl.name]} "
                f"level={layout._cluster_level[cl.name]}"
            )


# ─────────────────────────────────────────────────────────────────
# Node → cluster (PARENT semantics)
# ─────────────────────────────────────────────────────────────────


def build_node_to_cluster(layout: "FdpLayout") -> None:
    """Build ``layout._node_to_cluster`` mapping name → innermost
    cluster name (or ``None`` for nodes outside any cluster).

    Mirrors C's ``ND_clust(n)`` / ``PARENT(n)``: a node belongs to
    its **innermost** containing cluster.  We pick the cluster
    with the maximum ``level`` among those whose ``direct_nodes``
    list contains the node.  When no cluster owns the node, it
    maps to ``None``.

    Must be called AFTER :func:`discover_clusters`.
    """
    layout._node_to_cluster = {}

    if not layout._clusters:
        return

    # Index clusters by name → (level, cluster).
    by_name = {cl.name: cl for cl in layout._clusters}

    # For each node, find the deepest cluster whose direct_nodes
    # list contains it.  Iterate clusters in decreasing level so
    # the first hit wins.
    sorted_cls = sorted(
        layout._clusters,
        key=lambda c: layout._cluster_level[c.name],
        reverse=True,
    )

    for node_name in layout.lnodes:
        for cl in sorted_cls:
            if node_name in cl.direct_nodes:
                layout._node_to_cluster[node_name] = cl.name
                break
        else:
            # Node not in any direct membership — could be a
            # transitive descendant only.  Look in transitive
            # ``nodes`` too as a fallback (innermost wins).
            for cl in sorted_cls:
                if node_name in cl.nodes:
                    layout._node_to_cluster[node_name] = cl.name
                    break
            else:
                layout._node_to_cluster[node_name] = None

    # Resolve to FdpCluster object (or None) for downstream
    # consumers that prefer object access.  Keep both maps for
    # convenience.
    layout._node_to_cluster_obj = {
        n: (by_name[cn] if cn else None)
        for n, cn in layout._node_to_cluster.items()
    }

    if layout._clusters:
        n_in = sum(
            1 for v in layout._node_to_cluster.values() if v is not None
        )
        _trace(
            f"node→cluster map: {n_in}/{len(layout._node_to_cluster)} "
            f"nodes in some cluster"
        )


# ─────────────────────────────────────────────────────────────────
# Post-layout bbox
# ─────────────────────────────────────────────────────────────────


def remove_cluster_overlap(
    layout: "FdpLayout",
    sep: float = 20.0,
    max_iter: int = 50,
) -> int:
    """Iteratively translate overlapping top-level clusters apart.

    Without this pass, fdp's flat force model lays out cluster
    members based on inter-cluster edges only, with no awareness
    of cluster grouping.  Cluster bboxes computed from member
    positions can still overlap visually even though node-level
    overlap removal cleared per-node collisions.

    This is a poor-man's substitute for C ``fdpgen/layout.c``'s
    ``deriveGraph`` two-level pipeline (collapse clusters to
    proxy nodes, lay out the derived graph, then lay out each
    cluster's interior).  Implementing the full pipeline is 1-2
    days of work; this simple post-pass gives most of the visual
    benefit at much lower cost.

    Algorithm: for each pair of top-level clusters whose bboxes
    overlap, push them apart along the smaller-overlap axis by
    half the overlap each (with ``sep`` extra margin).  Translate
    every member node by the same delta.  Recompute bboxes after
    each move.  Repeat until no overlaps remain or ``max_iter``
    hits.  Returns the number of iterations executed.

    Top-level only: nested clusters move with their parent (since
    nested cluster nodes are also in the parent's ``nodes`` list).
    """
    top_level = [
        c for c in layout._clusters
        if layout._cluster_parent[c.name] is None
    ]
    if len(top_level) < 2:
        return 0

    moved_any = False
    for iteration in range(max_iter):
        any_overlap = False
        for i in range(len(top_level)):
            for j in range(i + 1, len(top_level)):
                a = top_level[i]
                b = top_level[j]
                ax1, ay1, ax2, ay2 = a.bb
                bx1, by1, bx2, by2 = b.bb
                # Overlap extent along each axis (positive when
                # bboxes intersect, zero/negative otherwise).
                ox = min(ax2, bx2) - max(ax1, bx1) + sep
                oy = min(ay2, by2) - max(ay1, by1) + sep
                if ox <= 0 or oy <= 0:
                    continue
                any_overlap = True
                acx = (ax1 + ax2) / 2.0
                acy = (ay1 + ay2) / 2.0
                bcx = (bx1 + bx2) / 2.0
                bcy = (by1 + by2) / 2.0
                # Push along smaller-overlap axis (cheaper move).
                if ox < oy:
                    push = ox / 2.0
                    a_dx = -push if acx < bcx else push
                    b_dx = -a_dx
                    a_dy = b_dy = 0.0
                else:
                    push = oy / 2.0
                    a_dy = -push if acy < bcy else push
                    b_dy = -a_dy
                    a_dx = b_dx = 0.0
                for n in a.nodes:
                    ln = layout.lnodes.get(n)
                    if ln is not None:
                        ln.x += a_dx
                        ln.y += a_dy
                for n in b.nodes:
                    ln = layout.lnodes.get(n)
                    if ln is not None:
                        ln.x += b_dx
                        ln.y += b_dy
                moved_any = True
                # Recompute bboxes for affected clusters before
                # the next pair check this iteration.
                compute_cluster_bboxes(layout)
                ax1, ay1, ax2, ay2 = a.bb
                bx1, by1, bx2, by2 = b.bb
        if not any_overlap:
            break

    if moved_any:
        _trace(
            f"remove_cluster_overlap: {iteration + 1} iter(s); "
            f"final cluster bboxes:"
        )
        for cl in top_level:
            _trace(
                f"  {cl.name} bb=({cl.bb[0]:.1f},{cl.bb[1]:.1f},"
                f"{cl.bb[2]:.1f},{cl.bb[3]:.1f})"
            )
    return iteration + 1 if moved_any else 0


def push_nonmembers_out_of_clusters(
    layout: "FdpLayout",
    sep: float = 8.0,
    max_iter: int = 50,
) -> int:
    """Push every node out of clusters it doesn't belong to.

    fdp's flat force model can land a non-member node inside a
    cluster's bbox if the node has edges into that cluster (it
    gets pulled toward the cluster's members).  Visually the
    node appears "inside" the cluster box even though it's not a
    member.

    Algorithm — **coordinated group escape**:
    For each cluster with non-member intruders, group the
    intruders into connected components (via the intruders' own
    edges).  All members of one connected component escape in
    the SAME cardinal direction, chosen to minimize the total
    edge length post-push.  This keeps connected free nodes
    close to each other (rather than splitting them onto
    opposite sides of the cluster, which a per-node greedy
    escape would do).

    Mirrors the spirit of C ``lib/dotgen/position.c
    keepout_othernodes`` (which is dot-engine-specific) — fdp
    needs an equivalent guarantee for cluster-rendering
    correctness.

    Cluster bboxes are NOT modified (only the non-member node
    moves).  Returns the number of iterations executed.
    """
    if not layout._clusters:
        return 0
    import math

    # Index: cluster.name -> set of member names (transitive).
    members_by_cl: dict[str, set[str]] = {
        cl.name: set(cl.nodes) for cl in layout._clusters
    }

    # Build undirected adjacency from all edges (root + every
    # subgraph) so connected-component grouping sees the
    # intra-cluster edges too.
    adj: dict[str, list[str]] = {n: [] for n in layout.lnodes}
    seen_pair: set[tuple[str, str]] = set()
    if hasattr(layout, "_iter_all_edges"):
        edge_iter = layout._iter_all_edges()
    else:
        edge_iter = layout.graph.edges.items()
    for _key, edge in edge_iter:
        t = edge.tail.name
        h = edge.head.name
        if t not in adj or h not in adj or t == h:
            continue
        pair = (min(t, h), max(t, h))
        if pair in seen_pair:
            continue
        seen_pair.add(pair)
        adj[t].append(h)
        adj[h].append(t)

    def _intruders_of(cl) -> list[str]:
        """Names of non-member nodes whose inflated bbox sits
        inside cluster ``cl``'s bbox."""
        cx1, cy1, cx2, cy2 = cl.bb
        out: list[str] = []
        members = members_by_cl[cl.name]
        for name, ln in layout.lnodes.items():
            if name in members:
                continue
            hw = ln.width / 2.0 + sep
            hh = ln.height / 2.0 + sep
            if (cx1 - hw < ln.x < cx2 + hw
                    and cy1 - hh < ln.y < cy2 + hh):
                out.append(name)
        return out

    def _component_groups(intruders: list[str]) -> list[list[str]]:
        """Group ``intruders`` into connected components via
        edges between intruders (cross-cluster edges to outside
        nodes don't bind the group together)."""
        intruder_set = set(intruders)
        seen: set[str] = set()
        groups: list[list[str]] = []
        for n in intruders:
            if n in seen:
                continue
            comp: list[str] = []
            stack = [n]
            seen.add(n)
            while stack:
                x = stack.pop()
                comp.append(x)
                for y in adj[x]:
                    if y in intruder_set and y not in seen:
                        seen.add(y)
                        stack.append(y)
            groups.append(comp)
        return groups

    def _push_group(group: list[str], cl) -> bool:
        """Try all 4 cardinal escape directions for the whole
        group; apply the one with the lowest sum of edge
        lengths post-push.  Returns True if any node moved."""
        cx1, cy1, cx2, cy2 = cl.bb
        # Pre-cache half-extents for each group member.
        half: dict[str, tuple[float, float]] = {}
        for n in group:
            ln = layout.lnodes[n]
            half[n] = (ln.width / 2.0 + sep, ln.height / 2.0 + sep)

        # Candidate positions per direction.
        directions: dict[str, dict[str, tuple[float, float]]] = {}
        for d in ("up", "down", "left", "right"):
            cand: dict[str, tuple[float, float]] = {}
            for n in group:
                ln = layout.lnodes[n]
                hw, hh = half[n]
                if d == "left":
                    cand[n] = (cx1 - hw, ln.y)
                elif d == "right":
                    cand[n] = (cx2 + hw, ln.y)
                elif d == "up":
                    cand[n] = (ln.x, cy1 - hh)
                else:
                    cand[n] = (ln.x, cy2 + hh)
            directions[d] = cand

        # Cost: sum of edge lengths for every edge incident to
        # any group member.  Endpoints outside the group stay
        # at their current positions.
        best_dir = None
        best_cost = float("inf")
        for d, cand in directions.items():
            cost = 0.0
            for n in group:
                nx, ny = cand[n]
                for nb in adj[n]:
                    if nb in cand:
                        bx, by = cand[nb]
                    else:
                        nb_ln = layout.lnodes.get(nb)
                        if nb_ln is None:
                            continue
                        bx, by = nb_ln.x, nb_ln.y
                    cost += math.hypot(nx - bx, ny - by)
            if cost < best_cost:
                best_cost = cost
                best_dir = d

        cand = dict(directions[best_dir])

        # Spread members along the axis perpendicular to the
        # escape direction so they don't overlap each other.
        # For up/down escape, all members share a y; spread x.
        # For left/right escape, all members share an x; spread y.
        if best_dir in ("up", "down"):
            ordered = sorted(group, key=lambda n: cand[n][0])
            for i in range(1, len(ordered)):
                prev = ordered[i - 1]
                curr = ordered[i]
                prev_hw = layout.lnodes[prev].width / 2.0 + sep
                curr_hw = layout.lnodes[curr].width / 2.0 + sep
                min_x = cand[prev][0] + prev_hw + curr_hw
                if cand[curr][0] < min_x:
                    cand[curr] = (min_x, cand[curr][1])
        else:  # left / right escape
            ordered = sorted(group, key=lambda n: cand[n][1])
            for i in range(1, len(ordered)):
                prev = ordered[i - 1]
                curr = ordered[i]
                prev_hh = layout.lnodes[prev].height / 2.0 + sep
                curr_hh = layout.lnodes[curr].height / 2.0 + sep
                min_y = cand[prev][1] + prev_hh + curr_hh
                if cand[curr][1] < min_y:
                    cand[curr] = (cand[curr][0], min_y)

        moved = False
        for n, (nx, ny) in cand.items():
            ln = layout.lnodes[n]
            if ln.x != nx or ln.y != ny:
                ln.x = nx
                ln.y = ny
                moved = True
        return moved

    moved_any = False
    iteration = 0
    for iteration in range(max_iter):
        any_change = False
        for cl in layout._clusters:
            if cl.bb == (0.0, 0.0, 0.0, 0.0):
                continue
            intruders = _intruders_of(cl)
            if not intruders:
                continue
            for group in _component_groups(intruders):
                if _push_group(group, cl):
                    any_change = True
                    moved_any = True
        if not any_change:
            break

    if moved_any:
        _trace(
            f"push_nonmembers_out_of_clusters: "
            f"{iteration + 1} iter(s); coordinated group escape"
        )
    return iteration + 1 if moved_any else 0


def compute_cluster_bboxes(layout: "FdpLayout") -> None:
    """Fill each ``cluster.bb`` from member node positions + margin.

    Walks every cluster's transitive ``nodes`` list, accumulates
    the union of their inflated bboxes (centre ± half-extent),
    then expands by the cluster's ``margin``.  Empty clusters
    keep ``bb=(0, 0, 0, 0)``.

    Must be called AFTER node positions have settled (post
    overlap removal, pre routing) and AFTER
    :func:`discover_clusters`.

    Mirrors C ``compute_bb`` (lib/dotgen/) for the simple
    member-union case.  fdp doesn't have rank-direction extras
    so this is just an axis-aligned union.
    """
    for cl in layout._clusters:
        if not cl.nodes:
            cl.bb = (0.0, 0.0, 0.0, 0.0)
            continue
        x_min = float("inf")
        y_min = float("inf")
        x_max = float("-inf")
        y_max = float("-inf")
        any_member = False
        for n in cl.nodes:
            ln = layout.lnodes.get(n)
            if ln is None:
                continue
            any_member = True
            hw = ln.width / 2.0
            hh = ln.height / 2.0
            if ln.x - hw < x_min:
                x_min = ln.x - hw
            if ln.y - hh < y_min:
                y_min = ln.y - hh
            if ln.x + hw > x_max:
                x_max = ln.x + hw
            if ln.y + hh > y_max:
                y_max = ln.y + hh
        if not any_member:
            cl.bb = (0.0, 0.0, 0.0, 0.0)
            continue
        m = cl.margin
        cl.bb = (x_min - m, y_min - m, x_max + m, y_max + m)
        _trace(
            f"  {cl.name} bb=({cl.bb[0]:.1f},{cl.bb[1]:.1f},"
            f"{cl.bb[2]:.1f},{cl.bb[3]:.1f}) "
            f"size={cl.bb[2]-cl.bb[0]:.1f}x{cl.bb[3]-cl.bb[1]:.1f}"
        )
