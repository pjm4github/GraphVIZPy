"""C-aligned ``deriveGraph`` two-level layout for fdp.

Mirrors ``lib/fdpgen/layout.c`` (entry: ``layout()`` at line 800,
helpers ``deriveGraph`` at 380, ``expandCluster`` at 662).

Algorithm (matches C verbatim except where noted):

1. **deriveGraph(scope)** — at any scope (root graph or a cluster
   subgraph), produce a *derived graph*:

   - Each direct child **cluster** becomes a single **proxy node**
     in the derived graph.  Its size = the cluster's bbox size
     (computed by recursing into the cluster's interior first, so
     by the time we lay out this scope the proxy size is known).
   - Each direct member **node** becomes a pass-through node in
     the derived graph.
   - Each edge is "lifted" to the derived graph: the edge's
     endpoints are mapped to the immediate child of *scope* that
     contains them (the cluster proxy if the endpoint lives in a
     descendant cluster, or the node itself if it's a direct
     member).  Self-loops (both endpoints map to the same child)
     are dropped.

2. **recursive_layout(scope)** — bottom-up:

   - Recurse into every direct child cluster first; each call
     fills the cluster's ``bb``.
   - Build the derived graph for this scope.
   - Run ``tlayout`` on the derived graph.  Cluster proxies
     participate as flat F-R nodes with the size set in step 1.
   - Run ``xlayout`` for proxy overlap removal at this scope.
   - Translate each cluster's interior (already laid out) so its
     centroid sits at the proxy's final position.
   - Set the scope's bbox to the union of derived-node bboxes.

3. **expand_cluster** is folded into the recursion: when we
   recurse into a cluster, we already know its content; we don't
   need C's port-injection step for an initial layout (ports are
   only needed for downstream renderer alignment, which fdp
   doesn't require for splines).

What's deliberately left out (vs C):

- **Port nodes** (C ``IS_PORT`` / ``getEdgeList`` / ``genPorts``)
  — used only when an edge crosses cluster boundaries and the
  proxy needs an attachment angle.  Routing already handles this
  via ``compoundEdges`` in Py.
- **Pinned-cluster placement** (C ``chkPos``) — minor, fdp pins
  are barely used.
- **finalCC normalize/translate-to-origin** — the existing
  ``apply_normalize`` / ``apply_center`` post-pass handles this.

This module replaces the simple post-pass quick fixes
(``remove_cluster_overlap``, ``push_nonmembers_out_of_clusters``)
with a structurally correct hierarchical layout.  The quick
fixes remain in ``cluster.py`` so callers can still opt in via
the legacy path (off by default once deriveGraph ships).

Trace channel: ``GVPY_TRACE_FDP=1`` extends with
``[TRACE fdp_derive] ...`` lines.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gvpy.engines.layout.fdp.fdp_layout import FdpLayout
    from gvpy.engines.layout.fdp.cluster import FdpCluster


# ─────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────


@dataclass
class DerivedNode:
    """A node in a derived graph.

    Either represents a real layout node (``cluster is None``,
    ``real_name`` is set) or a cluster proxy (``cluster`` is the
    :class:`FdpCluster`, ``real_name`` is None).

    The proxy carries the cluster's pre-computed bbox size so
    ``tlayout`` can repel it like a fat node.

    The ``proxy_lnode_name`` is the synthetic name we add to
    ``layout.lnodes`` for the duration of this scope's tlayout
    pass — required because tlayout reads/writes positions
    through ``layout.lnodes[name]`` and proxies aren't in the
    caller's layout state.
    """

    real_name: Optional[str]
    cluster: Optional["FdpCluster"]
    proxy_lnode_name: Optional[str] = None
    width: float = 54.0
    height: float = 36.0

    @property
    def key(self) -> str:
        """Stable name used to address this derived node in
        adjacency / position dicts."""
        if self.real_name is not None:
            return self.real_name
        assert self.proxy_lnode_name is not None
        return self.proxy_lnode_name


@dataclass
class DerivedGraph:
    """Result of ``derive_graph(layout, scope)``.

    - ``nodes``: list of :class:`DerivedNode`, indexed by ``key``.
    - ``edges``: list of ``(tail_key, head_key, length, weight)``
      tuples — the lifted edges with the same length/weight as
      the underlying real edge.

    ``scope_cluster`` is the cluster being laid out, or None for
    the root scope.
    """

    scope_cluster: Optional["FdpCluster"]
    nodes: list[DerivedNode] = field(default_factory=list)
    edges: list[tuple[str, str, float, float]] = field(default_factory=list)


def _trace(msg: str) -> None:
    if os.environ.get("GVPY_TRACE_FDP", "") == "1":
        print(f"[TRACE fdp_derive] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────
# derive_graph
# ─────────────────────────────────────────────────────────────────


def _direct_child_clusters(layout: "FdpLayout",
                           scope: Optional["FdpCluster"]
                           ) -> list["FdpCluster"]:
    """Clusters whose immediate parent is ``scope`` (root if
    ``scope is None``).
    """
    parent_name = scope.name if scope is not None else None
    return [
        c for c in layout._clusters
        if layout._cluster_parent[c.name] == parent_name
    ]


def _direct_member_nodes(layout: "FdpLayout",
                         scope: Optional["FdpCluster"]) -> list[str]:
    """Names of nodes that sit directly in ``scope`` (i.e. their
    PARENT is exactly this scope).

    For root: all nodes with no enclosing cluster.
    For cluster X: its ``direct_nodes`` list.
    """
    if scope is None:
        return [
            n for n in layout.lnodes
            if layout._node_to_cluster.get(n) is None
        ]
    return [n for n in scope.direct_nodes if n in layout.lnodes]


def _lift_node_to_scope(
    layout: "FdpLayout",
    node_name: str,
    scope: Optional["FdpCluster"],
    direct_node_set: set[str],
    cluster_keys: dict[str, str],
) -> Optional[str]:
    """Map a real node name to the key of the scope's direct child
    that contains it.

    - If the node is itself a direct member of scope: return its
      own name.
    - Otherwise climb the cluster ancestry until we hit a cluster
      whose parent is ``scope``; return that cluster's proxy key.
    - Returns None if the node is in a different scope branch
      (shouldn't happen for valid edges within scope).
    """
    if node_name in direct_node_set:
        return node_name
    cl_name = layout._node_to_cluster.get(node_name)
    if cl_name is None:
        # Free node but not a direct member of this scope —
        # belongs to a different scope's subtree.
        return None
    # Walk up until we find a cluster whose parent is scope.
    target_parent = scope.name if scope is not None else None
    cur = cl_name
    seen: set[str] = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        if layout._cluster_parent[cur] == target_parent:
            return cluster_keys.get(cur)
        cur = layout._cluster_parent[cur]
    return None


def derive_graph(
    layout: "FdpLayout",
    scope: Optional["FdpCluster"],
) -> DerivedGraph:
    """Build the derived graph for ``scope``.

    See module docstring for the algorithm.  Cluster proxies are
    sized from each cluster's pre-computed ``bb`` (callers should
    have recursed into clusters first; for clusters with empty bb
    we fall back to a heuristic from member count × K).
    """
    children = _direct_child_clusters(layout, scope)
    direct_nodes = _direct_member_nodes(layout, scope)
    direct_set = set(direct_nodes)

    # Key map for cluster proxies — synthetic lnode names so
    # tlayout can index them.
    cluster_keys: dict[str, str] = {
        c.name: f"_proxy_{c.name}" for c in children
    }

    dg = DerivedGraph(scope_cluster=scope)

    # 1. Pass-through nodes for direct members.
    for n_name in direct_nodes:
        ln = layout.lnodes[n_name]
        dg.nodes.append(DerivedNode(
            real_name=n_name,
            cluster=None,
            proxy_lnode_name=None,
            width=ln.width,
            height=ln.height,
        ))

    # 2. Proxy nodes for direct child clusters.
    for cl in children:
        bx1, by1, bx2, by2 = cl.bb
        w = bx2 - bx1 if bx2 > bx1 else 54.0
        h = by2 - by1 if by2 > by1 else 36.0
        dg.nodes.append(DerivedNode(
            real_name=None,
            cluster=cl,
            proxy_lnode_name=cluster_keys[cl.name],
            width=w,
            height=h,
        ))

    # 3. Lifted edges — walk every edge in the graph, map each
    # endpoint to its scope-direct child, drop self-loops.
    seen_pairs: set[tuple[str, str]] = set()
    if hasattr(layout, "_iter_all_edges"):
        edge_iter = layout._iter_all_edges()
    else:
        edge_iter = layout.graph.edges.items()

    for _key, edge in edge_iter:
        t = edge.tail.name
        h = edge.head.name
        if t == h:
            continue
        t_key = _lift_node_to_scope(layout, t, scope,
                                    direct_set, cluster_keys)
        h_key = _lift_node_to_scope(layout, h, scope,
                                    direct_set, cluster_keys)
        if t_key is None or h_key is None:
            continue  # edge crosses out of this scope
        if t_key == h_key:
            continue  # both endpoints in same child → internal to child

        pair = (t_key, h_key) if t_key < h_key else (h_key, t_key)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        try:
            length = float(edge.attributes.get("len", "")) * 72.0
        except (ValueError, TypeError):
            length = layout.K
        try:
            weight = float(edge.attributes.get("weight", "1.0"))
        except (ValueError, TypeError):
            weight = 1.0
        dg.edges.append((t_key, h_key, length, weight))

    _trace(
        f"derive_graph(scope={scope.name if scope else 'ROOT'}): "
        f"{len(dg.nodes)} derived nodes "
        f"({sum(1 for d in dg.nodes if d.cluster is None)} real, "
        f"{sum(1 for d in dg.nodes if d.cluster is not None)} cluster "
        f"proxies), {len(dg.edges)} edges"
    )
    return dg


# ─────────────────────────────────────────────────────────────────
# recursive_layout
# ─────────────────────────────────────────────────────────────────


def _install_proxy_lnodes(layout,
                          dg: DerivedGraph) -> list[str]:
    """Add cluster proxies to ``layout.lnodes`` for the duration
    of this scope's tlayout pass.  Returns the list of synthetic
    names that the caller must remove afterwards.

    Engine-agnostic: locates the engine's ``LayoutNode`` class
    from the layout's existing nodes (every engine's lnodes
    contain instances of its own LayoutNode class) so we don't
    have to import a hard-coded class.
    """
    # Pluck the LayoutNode class from any existing entry; falls
    # back to fdp's class if lnodes is empty (extremely unlikely
    # by the time this is called but kept for safety).
    if layout.lnodes:
        LayoutNode = type(next(iter(layout.lnodes.values())))
    else:
        from gvpy.engines.layout.fdp.fdp_layout import LayoutNode

    installed: list[str] = []
    for dn in dg.nodes:
        if dn.cluster is None:
            continue
        name = dn.proxy_lnode_name
        assert name is not None
        if name in layout.lnodes:
            continue  # already installed (shouldn't happen)
        # Initial position: cluster's current bbox centre.  After
        # tlayout this will be overwritten.
        bx1, by1, bx2, by2 = dn.cluster.bb
        cx = (bx1 + bx2) / 2.0
        cy = (by1 + by2) / 2.0
        layout.lnodes[name] = LayoutNode(
            name=name, node=None,
            x=cx, y=cy,
            width=dn.width, height=dn.height,
            pinned=False, pos_set=False,
        )
        installed.append(name)
    return installed


def _remove_proxy_lnodes(layout: "FdpLayout",
                         names: list[str]) -> None:
    """Remove proxies installed by :func:`_install_proxy_lnodes`."""
    for name in names:
        layout.lnodes.pop(name, None)


def _default_force_solver(layout, node_list: list[str],
                          edges: list[tuple[str, str, float, float]],
                          K: float, maxiter: int) -> None:
    """Default force solver — fdp's tlayout.

    Engines can pass their own ``force_solver`` to
    :func:`recursive_layout` (e.g. sfdp's multilevel
    spring-electrical with Barnes-Hut quadtree).  The signature is
    ``(layout, node_list, edges, K, maxiter)``; positions are
    read/written via ``layout.lnodes[name]``.
    """
    from gvpy.engines.layout.fdp.tlayout import tlayout, init_positions
    if len(node_list) < 2:
        return
    T0 = layout.T0 if getattr(layout, "T0", -1.0) > 0 else (
        K * math.sqrt(len(node_list)) / 5.0
    )
    init_positions(layout, node_list, K)
    tlayout(layout, node_list, edges, K, T0,
            maxiter, use_grid=getattr(layout, "use_grid", True))


def _default_overlap_solver(layout, K: float, sep: float,
                            maxiter: int,
                            node_subset: list[str]) -> None:
    """Default overlap solver — fdp's xlayout restricted to a
    subset.  Engines that don't have a bbox-aware overlap pass
    can supply a no-op or their own simple displacement loop.
    """
    if len(node_subset) < 2:
        return
    from gvpy.engines.layout.fdp.xlayout import xlayout
    xlayout(layout, K, sep, maxiter, tries=3,
            node_subset=node_subset)


def _translate_cluster_to_proxy(
    layout: "FdpLayout",
    cl: "FdpCluster",
    proxy_x: float,
    proxy_y: float,
) -> None:
    """Translate every transitive member of ``cl`` so the
    cluster's centroid lands at ``(proxy_x, proxy_y)``.
    """
    if not cl.nodes:
        return
    # Centroid of current member positions
    sum_x = 0.0
    sum_y = 0.0
    n = 0
    for name in cl.nodes:
        ln = layout.lnodes.get(name)
        if ln is None:
            continue
        sum_x += ln.x
        sum_y += ln.y
        n += 1
    if n == 0:
        return
    cx = sum_x / n
    cy = sum_y / n
    dx = proxy_x - cx
    dy = proxy_y - cy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return
    for name in cl.nodes:
        ln = layout.lnodes.get(name)
        if ln is None:
            continue
        ln.x += dx
        ln.y += dy


def recursive_layout(
    layout,
    scope: Optional["FdpCluster"],
    *,
    depth: int = 0,
    force_solver=None,
    overlap_solver=None,
) -> None:
    """Recursive two-level layout.  Lays out ``scope``'s interior
    in scope-local coordinates.

    Mirrors C ``layout(g, infop, counter)`` in
    ``lib/fdpgen/layout.c:800``.  Engine-pluggable via
    ``force_solver`` / ``overlap_solver`` callbacks so sfdp can
    reuse the cluster orchestration with its own
    spring-electrical + Barnes-Hut solver.

    Steps:

    1. Recurse into every direct child cluster first.  Each
       recursion fills the cluster's ``bb``.
    2. Build the derived graph for this scope (proxies for
       child clusters, pass-through for direct members).
    3. Run ``force_solver`` on the derived graph.  Cluster
       proxies participate as flat F-R nodes sized to their
       ``bb``.
    4. Run ``overlap_solver`` for overlap removal at this level.
    5. For each cluster proxy, translate the cluster's interior
       so its centroid lands at the proxy's final position.
    6. Recompute this scope's cluster bbox.

    No-op for empty scopes.

    Default ``force_solver`` is fdp's ``tlayout``; default
    ``overlap_solver`` is fdp's ``xlayout``.  Pass alternate
    callables for other engines.
    """
    if force_solver is None:
        force_solver = _default_force_solver
    if overlap_solver is None:
        overlap_solver = _default_overlap_solver

    indent = "  " * depth
    scope_name = scope.name if scope is not None else "ROOT"
    _trace(f"{indent}recursive_layout: {scope_name} (depth={depth})")

    # Step 1: bottom-up recursion into child clusters first.
    children = _direct_child_clusters(layout, scope)
    for cl in children:
        recursive_layout(layout, cl, depth=depth + 1,
                         force_solver=force_solver,
                         overlap_solver=overlap_solver)

    # Step 2: build the derived graph for this scope.
    dg = derive_graph(layout, scope)

    # If there's nothing to lay out at this level (e.g. an empty
    # cluster), still need to fill its bbox so the parent can size
    # its proxy.
    if not dg.nodes:
        if scope is not None:
            scope.bb = (0.0, 0.0, 0.0, 0.0)
        return

    # Step 3: install proxies in lnodes, run force_solver on
    # (real direct nodes ∪ cluster proxies).
    installed = _install_proxy_lnodes(layout, dg)
    try:
        node_list = [dn.key for dn in dg.nodes]
        force_solver(layout, node_list, dg.edges,
                     layout.K, layout.maxiter)

        # Step 4: overlap removal at THIS scope, restricted to
        # derived-graph nodes (proxies + direct members).  F-R
        # repulsion at K=21.6 can't separate cluster proxies
        # whose bboxes are 100-200 pt wide; bbox-aware overlap
        # removal enforces non-overlap.  Engine-specific solver.
        if len(dg.nodes) >= 2:
            overlap_solver(layout, layout.K,
                           getattr(layout, "sep", 0.0),
                           layout.maxiter, node_list)

        # Step 5: translate each cluster's interior to its
        # proxy's final position.
        for dn in dg.nodes:
            if dn.cluster is None:
                continue
            assert dn.proxy_lnode_name is not None
            proxy_ln = layout.lnodes[dn.proxy_lnode_name]
            _translate_cluster_to_proxy(
                layout, dn.cluster, proxy_ln.x, proxy_ln.y,
            )
    finally:
        _remove_proxy_lnodes(layout, installed)

    # Step 6: recompute this scope's bbox.
    from gvpy.engines.layout.fdp.cluster import compute_cluster_bboxes
    if scope is not None:
        # Recompute just this scope's bbox; the helper updates all
        # clusters but only THIS one's value matters here.
        compute_cluster_bboxes(layout)


def derive_graph_layout(layout, *, force_solver=None,
                        overlap_solver=None) -> None:
    """Top-level entry point.  Lays out the entire graph using
    the deriveGraph two-level algorithm.

    Replaces the flat ``tlayout`` + simple post-pass quick fixes
    when ``GVPY_FDP_DERIVE_GRAPH=1`` is set (will become default
    once validated on the corpus).
    """
    if not layout._clusters:
        # No clusters → flat tlayout is correct; caller falls
        # back through the existing path.
        return
    _trace("derive_graph_layout: starting recursive layout")
    recursive_layout(layout, scope=None, depth=0,
                     force_solver=force_solver,
                     overlap_solver=overlap_solver)
    _trace("derive_graph_layout: done")
