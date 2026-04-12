"""Cluster discovery, deduplication, and post-layout cluster geometry.

C analogue: ``lib/dotgen/cluster.c`` (cluster scaffolding) plus the
post-position cluster bbox / sibling separation routines that in C
are spread across ``cluster.c``, ``position.c``, and the cluster
finalization in ``dotsplines.c``.

Responsibilities
----------------
- **Cluster discovery** (``collect_clusters``, ``scan_clusters``,
  ``collect_nodes_into``): walk the parsed Graph subgraph tree and
  build the ``layout._clusters`` list of LayoutCluster objects.
  Each cluster records its name, attributes, label, margin, and
  the set of node names it directly contains.

- **Cluster node deduplication** (``dedup_cluster_nodes``): a node
  may belong to multiple clusters via subgraph nesting; deduplicate
  so each node is recorded under its **innermost** cluster only.
  This matches C's ``mark_clusters()`` semantics where ND_clust(n)
  points to the innermost containing cluster.

- **Sibling cluster separation** (``separate_sibling_clusters``):
  post-position safety net that pushes overlapping sibling clusters
  apart in the cross-rank direction.  See the function docstring
  for the C analogue and why this Python helper exists.

- **Cluster node shifting** (``shift_cluster_nodes_y``,
  ``shift_cluster_nodes_x``): low-level helpers used by
  ``separate_sibling_clusters`` to move all members of a cluster
  (including transitively-contained nodes) by a delta.

Extracted functions
-------------------
All 7 cluster-related methods moved from ``DotGraphInfo`` in
``dot_layout.py`` as free functions taking ``layout`` as the first
argument.  See ``TODO_core_refactor.md`` for the migration plan.

Related modules
---------------
- :mod:`gvpy.engines.dot.dotinit` — top-level layout init.  Calls
  :func:`collect_clusters` during ``init_from_graph``.
- :mod:`gvpy.engines.dot.position` — Phase 3.  Calls
  :func:`separate_sibling_clusters` (via ``layout._...``) during
  the post-position cleanup.
- :mod:`gvpy.engines.dot.mincross` — Phase 2.  Reads
  ``layout._clusters`` to build cluster skeletons for the
  cluster-aware mincross expand pipeline.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.engines.dot.dot_layout import DotGraphInfo, LayoutCluster


def collect_clusters(layout):
    """Scan subgraphs for cluster_* names and record membership.

    After scanning, a deduplication pass removes nodes that were
    spuriously added to a cluster because an edge referencing them
    appeared in that cluster's subgraph body.  In Graphviz C,
    a node belongs to a cluster only if it was *defined* there (or
    in a descendant cluster), not merely *referenced* in an edge.
    """
    layout._clusters = []
    if layout.clusterrank != "none":
        layout._scan_clusters(layout.graph)
        layout._dedup_cluster_nodes()


def collect_nodes_into(layout, sub, seen: set[str]):
    """Recursively gather node names from a subgraph and its children.

    C analogue: ``lib/dotgen/cluster.c`` cluster-membership walk
    used by ``mark_clusters()``.  Recurses into nested subgraphs and
    accumulates the union of node names that the cluster owns
    (directly or transitively through child subgraphs).
    """
    for n in sub.nodes:
        if n in layout.lnodes:
            seen.add(n)
    for child in sub.subgraphs.values():
        layout._collect_nodes_into(child, seen)


def scan_clusters(layout, g: Graph):
    """Recursively walk subgraphs and create LayoutCluster entries.

    C analogue: ``lib/dotgen/cluster.c`` cluster discovery and
    ``mark_clusters()`` (which is the C path that walks
    ``GD_clust(g)`` and marks each node's cluster ownership).
    """
    # Lazy import — LayoutCluster lives in dot_layout.py.
    from gvpy.engines.dot.dot_layout import LayoutCluster
    for sub_name, sub in g.subgraphs.items():
        if sub_name.startswith("cluster"):
            node_names = layout._all_nodes_recursive(sub)
            direct_names = [n for n in sub.nodes if n in layout.lnodes]
            label = sub.get_graph_attr("label") or ""
            margin_str = sub.get_graph_attr("margin")
            # margin is in points (not inches)
            margin = float(margin_str) if margin_str else 8.0
            # Collect visual attributes for rendering
            cl_attrs = {}
            for attr in ("color", "fillcolor", "bgcolor", "pencolor",
                         "fontcolor", "fontname", "fontsize", "style",
                         "penwidth", "peripheries", "labelloc", "labeljust",
                         "tooltip", "URL", "href", "target", "id", "class",
                         "colorscheme", "gradientangle"):
                val = sub.get_graph_attr(attr)
                if val:
                    cl_attrs[attr] = val
            layout._clusters.append(LayoutCluster(
                name=sub_name, label=label, nodes=node_names,
                direct_nodes=direct_names, margin=margin, attrs=cl_attrs,
            ))
        layout._scan_clusters(sub)


def dedup_cluster_nodes(layout):
    """Remove spurious node membership caused by edge references.

    In DOT, when an edge ``A -> B`` appears inside a subgraph, the
    parser adds both A and B to that subgraph's node dict even if
    A was *defined* in a different subgraph.  Graphviz C only adds a
    node to a cluster if it was created there.

    Strategy: use the **subgraph tree** (not node-set containment)
    to determine the true cluster hierarchy.  Then for each node,
    find the deepest cluster that is its true home by checking which
    cluster's child subgraphs do NOT contain the node.
    """
    if not layout._clusters:
        return

    cl_names = {cl.name for cl in layout._clusters}

    # Build the TRUE parent map from the subgraph tree structure,
    # not from node-set containment (which is corrupted by the bug).
    tree_parent: dict[str, str | None] = {}

    def _walk_tree(g, parent_cl: str | None):
        for sub_name, sub in g.subgraphs.items():
            if sub_name in cl_names:
                tree_parent[sub_name] = parent_cl
                _walk_tree(sub, sub_name)
            else:
                # Non-cluster subgraph: pass through parent
                _walk_tree(sub, parent_cl)

    _walk_tree(layout.graph, None)

    tree_children: dict[str | None, list[str]] = {}
    for cn, par in tree_parent.items():
        tree_children.setdefault(par, []).append(cn)

    # For each cluster, collect nodes from all descendant clusters
    _desc_nodes_cache: dict[str, set[str]] = {}
    def _desc_nodes(cl_name: str) -> set[str]:
        if cl_name in _desc_nodes_cache:
            return _desc_nodes_cache[cl_name]
        result: set[str] = set()
        for kid in tree_children.get(cl_name, []):
            cl_obj = next((c for c in layout._clusters if c.name == kid), None)
            if cl_obj:
                result.update(cl_obj.nodes)
            result.update(_desc_nodes(kid))
        _desc_nodes_cache[cl_name] = result
        return result

    # A node's true home: the deepest cluster (by tree structure)
    # where it appears but is NOT in any tree-child cluster.
    home_of: dict[str, str] = {}
    for cl in layout._clusters:
        desc = _desc_nodes(cl.name)
        for n in cl.nodes:
            if n not in desc:
                # n is in this cluster but not in any child → home
                # Smallest cluster wins (overwrite from larger to smaller)
                if n not in home_of:
                    home_of[n] = cl.name
                else:
                    # Keep the deeper one (further from root in tree)
                    cur_depth = 0
                    p = cl.name
                    while tree_parent.get(p) is not None:
                        cur_depth += 1
                        p = tree_parent[p]
                    old_depth = 0
                    p = home_of[n]
                    while tree_parent.get(p) is not None:
                        old_depth += 1
                        p = tree_parent[p]
                    if cur_depth > old_depth:
                        home_of[n] = cl.name

    def _tree_ancestors(cl_name: str) -> set[str]:
        anc: set[str] = set()
        cur = cl_name
        while tree_parent.get(cur) is not None:
            cur = tree_parent[cur]
            anc.add(cur)
        return anc

    # Remove nodes whose home is not this cluster or a descendant.
    for cl in layout._clusters:
        cleaned = []
        for n in cl.nodes:
            home = home_of.get(n)
            if home is None:
                cleaned.append(n)
                continue
            # Keep if: home == this cluster, or this cluster is a
            # tree-ancestor of home.
            if home == cl.name or cl.name in _tree_ancestors(home):
                cleaned.append(n)
        cl.nodes = cleaned
        cl.direct_nodes = [n for n in cl.direct_nodes
                           if n in set(cleaned)]


def separate_sibling_clusters(layout):
    """Push apart sibling clusters whose bounding boxes overlap.

    No direct C analogue.  C avoids the problem entirely because its
    NS X solver (``lib/dotgen/position.c``) enforces sibling
    separation as part of the constraint graph (see ``pos_clusters``
    and the cluster ln/rn boundary edges).  This Python helper is a
    post-pass safety net invoked after the position phase, kept for
    cases where the global NS could not enforce all sibling
    separation constraints (typically when they would create cycles
    in the constraint graph — see :func:`gvpy.engines.dot.position
    .ns_x_position`).

    Builds a cluster hierarchy, identifies sibling groups, and shifts
    nodes so that sibling clusters occupy non-overlapping regions.
    After shifting, ``_compute_cluster_boxes`` should be called again.
    """
    if not layout._clusters:
        return

    # Build parent map: for each cluster, find the smallest containing cluster
    cl_by_name: dict[str, "LayoutCluster"] = {cl.name: cl for cl in layout._clusters}
    node_sets = {cl.name: set(cl.nodes) for cl in layout._clusters}
    parent_of: dict[str, str | None] = {}

    for cl in layout._clusters:
        best_parent = None
        best_size = float("inf")
        for other in layout._clusters:
            if other.name == cl.name:
                continue
            if node_sets[cl.name] < node_sets[other.name]:
                if len(node_sets[other.name]) < best_size:
                    best_parent = other.name
                    best_size = len(node_sets[other.name])
        parent_of[cl.name] = best_parent

    # Group siblings (same parent)
    children_of: dict[str | None, list[str]] = {}
    for cl_name, par in parent_of.items():
        children_of.setdefault(par, []).append(cl_name)

    # Only separate leaf-level sibling clusters (those with no children).
    # This avoids cascading shifts from parent-level separations.
    gap = 8.0

    # Only separate leaf-level sibling clusters (those with no children)
    # to avoid cascading shifts from parent-level separation.
    has_children = set()
    for par in parent_of.values():
        if par is not None:
            has_children.add(par)

    # Always separate on X-axis because this runs BEFORE
    # _apply_rankdir (coordinates are still in TB space).
    for _parent, siblings in children_of.items():
        leaf_sibs = [s for s in siblings if s not in has_children]
        if len(leaf_sibs) < 2:
            continue
        sib_cls = [cl_by_name[s] for s in leaf_sibs if cl_by_name[s].bb]
        if len(sib_cls) < 2:
            continue

        sib_cls.sort(key=lambda c: c.bb[0])
        for i in range(len(sib_cls) - 1):
            c1 = sib_cls[i]
            c2 = sib_cls[i + 1]
            overlap_val = c1.bb[2] + gap - c2.bb[0]
            if overlap_val > 0:
                # Shift all nodes in subsequent siblings rightward
                shift_nodes: set[str] = set()
                for sib in sib_cls[i + 1:]:
                    shift_nodes.update(node_sets.get(sib.name, set()))
                for name in shift_nodes:
                    if name in layout.lnodes:
                        layout.lnodes[name].x += overlap_val
                # Recompute bboxes for shifted clusters
                for sib in sib_cls[i + 1:]:
                    members = [layout.lnodes[n] for n in sib.nodes
                               if n in layout.lnodes]
                    if members:
                        sib.bb = (
                            min(ln.x - ln.width/2 for ln in members) - sib.margin,
                            min(ln.y - ln.height/2 for ln in members) - sib.margin,
                            max(ln.x + ln.width/2 for ln in members) + sib.margin,
                            max(ln.y + ln.height/2 for ln in members) + sib.margin,
                        )


def shift_cluster_nodes_y(layout, cl, dy: float, node_sets: dict,
                            subsequent: list, prior: list):
    """Shift nodes exclusively in subsequent siblings by dy.

    No direct C analogue.  Helper for
    :func:`separate_sibling_clusters` (which itself has no C
    counterpart — see that function's docstring for context).
    Nodes shared with prior (already positioned) siblings are not
    moved so we don't undo earlier separation work.
    """
    prior_nodes: set[str] = set()
    for p in prior:
        prior_nodes.update(node_sets.get(p.name, set()))

    nodes_to_shift: set[str] = set()
    for sib in subsequent:
        nodes_to_shift.update(node_sets.get(sib.name, set()))
    nodes_to_shift -= prior_nodes

    for name in nodes_to_shift:
        if name in layout.lnodes:
            layout.lnodes[name].y += dy


def shift_cluster_nodes_x(layout, cl, dx: float, node_sets: dict,
                            subsequent: list, prior: list):
    """Shift nodes exclusively in subsequent siblings by dx.

    No direct C analogue.  X-axis counterpart of
    :func:`shift_cluster_nodes_y`; see that function's docstring.
    """
    prior_nodes: set[str] = set()
    for p in prior:
        prior_nodes.update(node_sets.get(p.name, set()))

    nodes_to_shift: set[str] = set()
    for sib in subsequent:
        nodes_to_shift.update(node_sets.get(sib.name, set()))
    nodes_to_shift -= prior_nodes

    for name in nodes_to_shift:
        if name in layout.lnodes:
            layout.lnodes[name].x += dx

