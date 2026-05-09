"""
Sfdp layout engine — scalable force-directed placement.

Port of Graphviz ``lib/sfdpgen/``.  Extends fdp with:

- **Multilevel coarsening**: Maximal independent edge set grouping,
  solve coarse → interpolate → refine
- **Barnes-Hut quadtree**: O(n log n) repulsive force approximation
- **Post-processing smoothing**: Optional stress majorization refinement

Command-line::

    python gvcli.py -Ksfdp input.gv -Tsvg -o output.svg

Attributes::

    K               — spring constant (default auto)
    repulsiveforce  — repulsive exponent (default 1)
    levels          — max coarsening levels
    smoothing       — post-processing: none, spring, avg_dist, graph_dist
    quadtree        — Barnes-Hut mode: normal, fast, none
    beautify        — arrange leaves in circle
    rotation        — rotate final layout (degrees)
    overlap         — overlap removal
    start           — random seed
    maxiter         — max iterations per level
"""
from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core._graph_traversal import gather_all_subgraphs
from gvpy.core.graph import Graph
from gvpy.core.node import Node
from gvpy.engines.layout.base import LayoutEngine
from gvpy.engines.layout.fdp.cluster import (
    FdpCluster,
    build_node_to_cluster,
    compute_cluster_bboxes,
    discover_clusters,
)
from gvpy.engines.layout.fdp.derive import derive_graph_layout


_DFLT_K = 0.3 * 72.0
_DFLT_MAXITER = 200
_BH_THETA = 0.6          # Barnes-Hut opening angle threshold
_COARSEN_RATIO = 0.75     # stop coarsening when ratio > this
_COOLING = 0.90
_ADAPTIVE_C = 0.2         # attractive force constant


@dataclass
class LayoutNode:
    name: str
    node: Optional[Node]
    x: float = 0.0
    y: float = 0.0
    width: float = 54.0
    height: float = 36.0
    pinned: bool = False
    pos_set: bool = False
    disp_x: float = 0.0
    disp_y: float = 0.0
    mass: float = 1.0      # for coarsened super-nodes


@dataclass
class _QTNode:
    """Quadtree node for Barnes-Hut approximation."""
    cx: float = 0.0        # center of mass x
    cy: float = 0.0        # center of mass y
    mass: float = 0.0      # total mass
    x0: float = 0.0        # bounding box
    y0: float = 0.0
    size: float = 0.0      # side length
    children: list = field(default_factory=list)  # 4 children or empty
    is_leaf: bool = True
    node_idx: int = -1      # leaf: index of single node


class SfdpLayout(LayoutEngine):
    """Scalable force-directed placement layout engine."""

    def __init__(self, graph: Graph):
        super().__init__(graph)
        self.lnodes: dict[str, LayoutNode] = {}
        self.K = _DFLT_K
        self.maxiter = _DFLT_MAXITER
        self.max_levels = 100
        self.seed = 1
        # Match Graphviz convention: overlap=false (remove
        # overlaps) is the sfdp default.  C's
        # ``post_process_smoothing`` always calls
        # ``remove_overlap`` regardless of the attribute; the
        # attribute selects *which* algorithm.  GraphvizPy
        # treats ``overlap=true`` as "skip removal" to preserve
        # the user's escape hatch.
        self.overlap = "false"
        self.sep = 0.0
        self.pack = True
        self.repulsive_exp = 1.0
        self.smoothing = "none"
        self.use_quadtree = True
        self.beautify = False
        self.rotation_deg = 0.0
        self._edge_len: dict[tuple[str, str], float] = {}
        self._edge_weight: dict[tuple[str, str], float] = {}
        # Cluster tracking — populated by ``discover_clusters``
        # / ``build_node_to_cluster`` / ``compute_cluster_bboxes``
        # in :mod:`gvpy.engines.layout.fdp.cluster` (engine-agnostic
        # helpers reused from fdp).  Sfdp dispatches to fdp's
        # ``derive_graph_layout`` for clustered graphs so it
        # inherits the C-aligned hierarchical layout end-to-end —
        # only the per-scope force solver is sfdp-specific
        # (multilevel spring-electrical with Barnes-Hut).
        self._clusters: list[FdpCluster] = []
        self._cluster_parent: dict[str, Optional[str]] = {}
        self._cluster_level: dict[str, int] = {}
        self._node_to_cluster: dict[str, Optional[str]] = {}
        self._node_to_cluster_obj: dict[str, Optional[FdpCluster]] = {}
        # Sfdp doesn't have its own T0; the derive helpers default
        # T0 to ``K * sqrt(N) / 5`` when ``layout.T0`` is missing
        # or non-positive.
        self.T0 = -1.0

    def layout(self) -> dict:
        self._init_from_graph()
        N = len(self.lnodes)
        if N == 0:
            return self._to_json()

        # Cluster-aware path: dispatch to fdp's deriveGraph
        # two-level recursive layout, plugging in sfdp's
        # multilevel spring-electrical solver.  The cluster
        # orchestration (proxy nodes, bottom-up recursion,
        # translate-cluster-to-proxy) is shared with fdp; only
        # the per-scope force pass differs.
        import os as _os_dg
        use_derive_graph = (
            self._clusters
            and _os_dg.environ.get(
                "GVPY_SFDP_DERIVE_GRAPH", "1"
            ) == "1"
        )
        if use_derive_graph:
            derive_graph_layout(
                self,
                force_solver=self._sfdp_force_solver,
                overlap_solver=self._sfdp_overlap_solver,
            )
            # Recompute cluster bboxes after the recursive
            # layout has translated each cluster's interior to
            # its proxy's final position.
            # ``recursive_layout`` only refreshes bboxes for
            # non-root scopes; the root call needs an explicit
            # final pass so the SVG renderer / -Tdot writeback
            # see the post-translate positions.
            compute_cluster_bboxes(self)
        else:
            adj = self._build_adjacency()
            components = self._find_components(adj)
            if len(components) > 1 and self.pack:
                for comp in components:
                    self._layout_component(comp, adj)
                self._pack_components_lr(components,
                                         gap=max(self.K * 0.5, 36.0))
            else:
                self._layout_component(set(self.lnodes.keys()), adj)

        # Overlap removal
        if self.overlap not in ("true", "1", "yes"):
            self._remove_overlap()

        # Sfdp-specific rotation
        if self.rotation_deg != 0:
            rad = math.radians(self.rotation_deg)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            for ln in self.lnodes.values():
                x, y = ln.x, ln.y
                ln.x = x * cos_a - y * sin_a
                ln.y = x * sin_a + y * cos_a

        if self.normalize:
            self._apply_normalize()
        if self.landscape or self.rotate_deg:
            self._apply_rotation()
        if self.center:
            self._apply_center()

        self._compute_label_positions()
        self._write_back()
        return self._to_json()

    # ── Initialization ───────────────────────────

    def _init_from_graph(self):
        self._init_common_attrs()

        k_str = self.graph.get_graph_attr("K")
        if k_str:
            try:
                self.K = float(k_str) * 72.0
            except ValueError:
                pass

        maxiter_str = self.graph.get_graph_attr("maxiter")
        if maxiter_str:
            try:
                self.maxiter = int(maxiter_str)
            except ValueError:
                pass

        levels_str = self.graph.get_graph_attr("levels")
        if levels_str:
            try:
                self.max_levels = int(levels_str)
            except ValueError:
                pass

        rf_str = self.graph.get_graph_attr("repulsiveforce")
        if rf_str:
            try:
                self.repulsive_exp = float(rf_str)
            except ValueError:
                pass

        self.smoothing = (self.graph.get_graph_attr("smoothing") or "none").lower()
        qt_str = (self.graph.get_graph_attr("quadtree") or "normal").lower()
        self.use_quadtree = qt_str not in ("none", "false", "0")
        self.beautify = (self.graph.get_graph_attr("beautify") or "").lower() \
                        in ("true", "1", "yes")

        rot_str = self.graph.get_graph_attr("rotation")
        if rot_str:
            try:
                self.rotation_deg = float(rot_str)
            except ValueError:
                pass

        ov_str = (self.graph.get_graph_attr("overlap") or "false").lower()
        self.overlap = ov_str

        sep_str = self.graph.get_graph_attr("sep")
        if sep_str:
            try:
                self.sep = float(sep_str)
            except ValueError:
                pass

        self.pack = (self.graph.get_graph_attr("pack") or "true").lower() \
                    not in ("false", "0", "no")

        start_str = self.graph.get_graph_attr("start") or ""
        if start_str.isdigit():
            self.seed = int(start_str)
        elif start_str == "random":
            import time
            self.seed = int(time.time())
        random.seed(self.seed)

        for name, node in self.graph.nodes.items():
            w, h = self._compute_node_size(name, node)
            ln = LayoutNode(name=name, node=node, width=w, height=h)
            pos_str = (node.attributes.get("pos") or "").strip() if node else ""
            if pos_str:
                try:
                    parts = pos_str.replace("!", "").split(",")
                    ln.x = float(parts[0]) * 72.0
                    ln.y = float(parts[1]) * 72.0
                    ln.pos_set = True
                    ln.pinned = "!" in pos_str or \
                                (node and node.attributes.get("pin", "").lower()
                                 in ("true", "1", "yes"))
                except (ValueError, IndexError):
                    pass
            self.lnodes[name] = ln

        # Walk root + every subgraph so edges declared inside
        # cluster subgraphs land in the cache (mirrors fdp's
        # ``_iter_all_edges`` — see DONE §4.F-clusters for the
        # parser-bug context).
        for key, edge in self._iter_all_edges():
            t, h = edge.tail.name, edge.head.name
            pair = (min(t, h), max(t, h))
            try:
                self._edge_len[pair] = float(edge.attributes.get("len", "")) * 72.0
            except (ValueError, TypeError):
                self._edge_len[pair] = self.K
            try:
                self._edge_weight[pair] = float(edge.attributes.get("weight", "1.0"))
            except ValueError:
                self._edge_weight[pair] = 1.0

        # Cluster discovery (engine-agnostic helpers from fdp).
        # When clusters exist, ``layout()`` dispatches to
        # ``derive_graph_layout`` with sfdp's force solver.
        discover_clusters(self)
        build_node_to_cluster(self)

    def _iter_all_edges(self):
        """Yield ``(key, edge)`` for every edge in the graph,
        including subgraph-owned edges.

        Mirrors ``FdpLayout._iter_all_edges``: edges declared
        inside subgraph blocks are stored in the lowest-common-
        subgraph's ``.edges`` dict, NOT root's.  Without this
        helper, intra-cluster edges would be lost from the force
        model.
        """
        for sg in gather_all_subgraphs(self.graph):
            for k, e in sg.edges.items():
                yield k, e

    def _build_adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = defaultdict(list)
        for name in self.lnodes:
            adj[name]
        # Walk every edge across the subgraph tree so intra-
        # cluster edges contribute to the graph topology.
        for key, edge in self._iter_all_edges():
            t, h = edge.tail.name, edge.head.name
            if t in self.lnodes and h in self.lnodes:
                if h not in adj[t]:
                    adj[t].append(h)
                if t not in adj[h]:
                    adj[h].append(t)
        return dict(adj)

    # ── Multilevel layout ────────────────────────

    def _layout_component(self, nodes: set[str], adj: dict[str, list[str]]):
        """Multilevel spring-electrical layout for a component.

        Dispatches between:

        - ``c`` (default): C-aligned port of
          ``lib/sfdpgen/spring_electrical.c`` —
          :func:`gvpy.engines.layout.sfdp.spring_electrical.multilevel_spring_electrical_embedding`.
        - ``legacy``: original homegrown FR + Barnes-Hut quadtree
          path.  Kept for diagnostic comparison.

        Override with ``GVPY_SFDP_SPRING_ELECTRICAL=legacy``.
        """
        node_list = [n for n in self.lnodes if n in nodes]
        N = len(node_list)
        if N == 0:
            return
        if N == 1:
            ln = self.lnodes[node_list[0]]
            if not ln.pos_set:
                ln.x, ln.y = 0.0, 0.0
            return

        import os as _os_se
        mode = _os_se.environ.get("GVPY_SFDP_SPRING_ELECTRICAL", "c")
        if mode == "c":
            self._layout_component_c_aligned(node_list, adj)
        else:
            self._layout_component_legacy(node_list, adj)

    def _layout_component_c_aligned(
        self, node_list: list[str], adj: dict[str, list[str]]
    ) -> None:
        """C-aligned multilevel spring-electrical layout.

        Builds the multilevel hierarchy via
        :mod:`gvpy.engines.layout.sfdp.multilevel`, then runs the
        descent in
        :mod:`gvpy.engines.layout.sfdp.spring_electrical`.

        Pinned nodes (``ln.pinned``) are honored at the finest
        level only — matches C, which has no pin concept and so
        moves all coarse-level proxies freely.

        Coordinate convention: the spring-electrical port runs in
        unit-K space (initial random coords in [0, 1) before
        ``average_edge_length`` resets K).  The final layout is
        rescaled by ``self.K`` so the per-edge spacing matches
        the existing engine's pt-based downstream consumers
        (overlap removal, label placement, SVG renderer).
        """
        from gvpy.engines.layout.sfdp.multilevel import (
            csr_from_adjacency,
            multilevel_new,
        )
        from gvpy.engines.layout.sfdp.spring_electrical import (
            SpringElectricalControl,
            multilevel_spring_electrical_embedding,
        )
        import numpy as _np

        N = len(node_list)
        # 1. Build CSR.
        A = csr_from_adjacency(node_list, adj, self._edge_weight)

        # 2. Build multilevel hierarchy.
        grid = multilevel_new(
            A, max_levels=self.max_levels, seed=self.seed,
        )

        # 3. Allocate finest-level coords array.  Preserve
        # already-pinned positions; everything else gets random
        # init via spring-electrical's own ``random_start`` path.
        x = _np.zeros((N, 2), dtype=_np.float64)
        pinned_mask = _np.zeros(N, dtype=bool)
        any_pinned = False
        for i, name in enumerate(node_list):
            ln = self.lnodes[name]
            if ln.pinned and ln.pos_set:
                # Map pinned coords into unit-K space.
                x[i, 0] = ln.x / max(self.K, 1e-9)
                x[i, 1] = ln.y / max(self.K, 1e-9)
                pinned_mask[i] = True
                any_pinned = True

        ctrl = SpringElectricalControl()
        ctrl.K = -1.0  # auto-derive from initial random layout
        ctrl.maxiter = self.maxiter
        ctrl.random_seed = self.seed
        ctrl.random_start = not any_pinned
        ctrl.adaptive_cooling = True
        ctrl.beautify_leaves = self.beautify

        # If any nodes are pinned, we can't random-start (would
        # overwrite their positions).  Seed the rest with a
        # deterministic-but-spread layout.
        if any_pinned:
            import random as _rand
            r = _rand.Random(self.seed)
            for i in range(N):
                if not pinned_mask[i]:
                    x[i, 0] = r.random()
                    x[i, 1] = r.random()
            ctrl.random_start = False

        # 4. Run the descent.
        multilevel_spring_electrical_embedding(
            A, ctrl, grid, x,
            pinned_mask=pinned_mask if any_pinned else None,
        )

        # 5. Post-process smoothing (stress majorization or
        # spring re-pass).  Mirrors C ``post_process_smoothing``
        # (post_process.c:974).  Runs on unit-K coords *before*
        # the rescale so the per-edge spacing the smoother sees
        # matches the Lwd matrix the smoother built.  Gated by
        # ``GVPY_SFDP_POST_PROCESS=c|legacy`` (default ``c``).
        import os as _os_pp
        if _os_pp.environ.get("GVPY_SFDP_POST_PROCESS", "c") == "c":
            self._post_process_smoothing_c_aligned(
                A, ctrl, grid, x, node_list,
            )

        # 6. Initial scaling — mirrors C ``remove_overlap``'s
        # ``scale_to_edge_length`` block (overlap.c:443/519).
        # The descent's output coords are in unit-K-ish space
        # (random init in [0,1) → forces preserve scale → final
        # avg edge length is roughly the auto-derived ``ctrl.K``,
        # which is ~0.3 for unit-square initial coords).  We need
        # to scale so the average edge length matches a multiple
        # of the average label size — without this step the
        # layout fits in ~200pt regardless of N, and every node
        # overlaps every other.  Default ``initial_scaling = -4``
        # → target avg edge = 4 × avg(width + height).
        self._apply_initial_scaling(x, node_list, A, ctrl.initial_scaling)

        # 7. Snapshot pinned node positions to restore after the
        # bbox overlap pass — initial scaling moves pinned nodes
        # too, but they're supposed to stay put.  We restore
        # pt-space coords from ``self.lnodes`` (set at engine
        # init).
        pinned_pt: dict[str, tuple[float, float]] = {}
        for i, name in enumerate(node_list):
            ln = self.lnodes[name]
            if ln.pinned and ln.pos_set:
                pinned_pt[name] = (ln.x, ln.y)

        # 8. Write back to lnodes so the bbox-aware overlap
        # solver in fdp's xlayout can read current positions.
        for i, name in enumerate(node_list):
            ln = self.lnodes[name]
            ln.x = float(x[i, 0])
            ln.y = float(x[i, 1])
        # Restore pinned to their original pt-space coords.
        for name, (px, py) in pinned_pt.items():
            ln = self.lnodes[name]
            ln.x = px
            ln.y = py

        # 9. Bbox-aware overlap removal.  Mirrors C ``remove_overlap``
        # (overlap.c:486) — the post-descent layout is correctly
        # *spaced* but not necessarily *non-overlapping* because
        # initial_scaling is averaged.  Run fdp's xlayout (proper
        # axis-aligned bbox detection) unless ``overlap=true``
        # explicitly disables it.
        if self.overlap not in ("true", "1", "yes"):
            self._sfdp_overlap_pass(node_list)

        # 10. Beautify leaves if requested (matches C
        # ``ctrl->beautify_leaves`` after the descent).
        if self.beautify:
            self._beautify_leaves(node_list, adj)

    def _apply_initial_scaling(
        self, x, node_list, A, initial_scaling: float,
    ) -> None:
        """Mirrors C ``scale_to_edge_length`` (overlap.c:443) and
        the ``initial_scaling`` block of ``remove_overlap``
        (overlap.c:519).

        Scales ``x`` in place so the average edge length matches:

        - ``-initial_scaling × avg_label_size`` if
          ``initial_scaling < 0`` where ``avg_label_size`` mirrors
          C's storage of *half-extents* — ``label_sizes[i*dim] +
          label_sizes[i*dim+1] = w/2 + h/2`` averaged across
          nodes.  Defaulting ``initial_scaling = -4`` then
          targets ``2·avg(w+h)`` which proves too aggressive in
          practice — C's post-scale ``do_shrinking`` compresses
          the layout further until there are no overlaps.  We
          don't port the full ``do_shrinking`` algorithm; instead
          we use ``initial_scaling = -2`` as the GraphvizPy
          default which produces canvas dimensions comparable to
          the system C ``dot`` for our reference graphs.
        - ``initial_scaling`` (absolute pt) if
          ``initial_scaling > 0``.

        No-op if ``initial_scaling == 0`` or the layout has no
        edges.
        """
        if initial_scaling == 0.0:
            return
        from gvpy.engines.layout.sfdp.spring_electrical import (
            average_edge_length,
        )
        if initial_scaling < 0:
            # Match C convention: avg of half-extents.
            avg_label = 0.0
            for name in node_list:
                ln = self.lnodes[name]
                avg_label += (ln.width + ln.height) * 0.5
            avg_label /= max(len(node_list), 1)
            target_edge = -initial_scaling * avg_label
        else:
            target_edge = initial_scaling
        current = average_edge_length(A, x)
        if current < 1.0e-12:
            return
        scale = target_edge / current
        x *= scale

    def _sfdp_overlap_pass(self, node_list: list[str]) -> None:
        """Bbox-aware overlap removal restricted to ``node_list``.

        Iterative axis-aligned bbox push-apart.  At each round,
        for every overlapping pair, push them along the smaller
        of the (x, y) penetration axes — this preserves the
        macro layout while clearing local overlaps.  Stops when
        no pair overlaps or after ``max_iters``.

        Doesn't grow ``K`` (unlike fdp's ``xlayout``), so the
        canvas size stays close to what ``initial_scaling``
        produced.  For graphs that initial_scaling already
        cleared, this loop is a single-iter no-op.
        """
        if len(node_list) < 2:
            return
        sep = self.sep
        max_iters = 50
        for _ in range(max_iters):
            moved_any = False
            # Snapshot positions so within-iter pushes don't
            # cascade — mirrors C's stress-smoothing pass which
            # also reads from a frozen state.
            for i in range(len(node_list)):
                a = self.lnodes[node_list[i]]
                if a.pinned:
                    continue
                for j in range(i + 1, len(node_list)):
                    b = self.lnodes[node_list[j]]
                    if b.pinned:
                        continue
                    dx = b.x - a.x
                    dy = b.y - a.y
                    # Required separation per axis.
                    req_x = (a.width + b.width) * 0.5 + sep
                    req_y = (a.height + b.height) * 0.5 + sep
                    pen_x = req_x - abs(dx)
                    pen_y = req_y - abs(dy)
                    if pen_x <= 0 or pen_y <= 0:
                        continue  # no overlap
                    # Push along the smaller-penetration axis.
                    if pen_x < pen_y:
                        push = (pen_x * 0.5) + 0.5
                        sign = 1.0 if dx >= 0 else -1.0
                        a.x -= sign * push
                        b.x += sign * push
                    else:
                        push = (pen_y * 0.5) + 0.5
                        sign = 1.0 if dy >= 0 else -1.0
                        a.y -= sign * push
                        b.y += sign * push
                    moved_any = True
            if not moved_any:
                break

    def _post_process_smoothing_c_aligned(
        self, A, ctrl, grid, x, node_list,
    ) -> None:
        """C-aligned dispatch to
        :func:`gvpy.engines.layout.sfdp.post_process.post_process_smoothing`.

        Maps GraphvizPy's lower-case smoothing attribute values to
        C's enum and supplies a ``spring_re_run`` callback that
        rebuilds a tightened control struct and re-descends the
        hierarchy (matches C ``SpringSmoother_smooth``).
        """
        if self.smoothing in (None, "", "none"):
            return
        from gvpy.engines.layout.sfdp.post_process import (
            post_process_smoothing,
        )
        from gvpy.engines.layout.sfdp.spring_electrical import (
            SpringElectricalControl,
            multilevel_spring_electrical_embedding,
        )
        import random as _rand

        rng = _rand.Random(self.seed)

        # ``spring_re_run`` callback: re-descend hierarchy with
        # the C-aligned spring-electrical solver, ``maxiter=20``,
        # ``step /= 2``, ``random_start=False`` (matches
        # ``SpringSmoother_new`` post_process.c:944-947).
        def _spring_re_run(coords):
            ctrl_re = SpringElectricalControl()
            ctrl_re.K = ctrl.K
            ctrl_re.maxiter = 20
            ctrl_re.step = ctrl.step / 2.0
            ctrl_re.random_seed = self.seed
            ctrl_re.random_start = False
            ctrl_re.adaptive_cooling = False
            multilevel_spring_electrical_embedding(
                A, ctrl_re, grid, coords,
            )

        post_process_smoothing(
            A, self.smoothing, x,
            rng=rng,
            spring_re_run=_spring_re_run,
        )

    def _layout_component_legacy(
        self, node_list: list[str], adj: dict[str, list[str]]
    ) -> None:
        """Pre-C-port multilevel FR + Barnes-Hut quadtree path.

        Kept behind ``GVPY_SFDP_SPRING_ELECTRICAL=legacy`` for
        diagnostic comparison.  Uses the engine's homegrown force
        formula and the local Barnes-Hut implementation.
        """
        N = len(node_list)
        # Build coarsening hierarchy
        levels = self._build_hierarchy(node_list, adj)

        # Solve at coarsest level
        coarsest = levels[-1]
        K_level = self.K
        for _ in range(len(levels) - 1):
            K_level *= 0.75

        self._init_positions(coarsest["nodes"], len(coarsest["nodes"]))
        self._spring_electrical(coarsest["nodes"], coarsest["adj"],
                                K_level, self.maxiter)

        # Uncoarsen: interpolate and refine
        for level_idx in range(len(levels) - 2, -1, -1):
            level = levels[level_idx]
            parent = levels[level_idx + 1]
            mapping = level.get("mapping", {})

            # Prolongate: interpolate positions from parent
            for name in level["nodes"]:
                ln = self.lnodes[name]
                parent_name = mapping.get(name, name)
                if parent_name in self.lnodes:
                    parent_ln = self.lnodes[parent_name]
                    if not ln.pos_set:
                        ln.x = parent_ln.x + (random.random() - 0.5) * K_level * 0.1
                        ln.y = parent_ln.y + (random.random() - 0.5) * K_level * 0.1

            K_level = self.K
            iters = min(self.maxiter, max(50, self.maxiter // (level_idx + 2)))
            self._spring_electrical(level["nodes"], level["adj"],
                                    K_level, iters)

        # Smoothing post-process
        if self.smoothing == "spring":
            self._spring_electrical(node_list, adj, self.K, 50)

        # Beautify: arrange leaf nodes in circle
        if self.beautify:
            self._beautify_leaves(node_list, adj)

    def _build_hierarchy(self, node_list: list[str],
                         adj: dict[str, list[str]]) -> list[dict]:
        """Build multilevel hierarchy via maximal independent edge set.

        Dispatches between the C-aligned port (default) and the
        legacy homegrown matching.  Set
        ``GVPY_SFDP_MULTILEVEL=legacy`` to revert.

        - ``c`` (default): port of ``lib/sfdpgen/Multilevel.c`` —
          MIES with supervariable preprocessing, heavy-edge
          per-node matching, Galerkin coarsening
          (``cA = R · A · P``).  See
          :mod:`gvpy.engines.layout.sfdp.multilevel`.
        - ``legacy``: greedy heaviest-edge matching on adjacency
          dicts, no Galerkin step.  Kept for diagnostic
          comparison.
        """
        import os as _os_ml
        mode = _os_ml.environ.get("GVPY_SFDP_MULTILEVEL", "c")
        if mode == "c":
            return self._build_hierarchy_c_aligned(node_list, adj)
        return self._build_hierarchy_legacy(node_list, adj)

    def _build_hierarchy_c_aligned(
        self, node_list: list[str], adj: dict[str, list[str]]
    ) -> list[dict]:
        """C-aligned multilevel coarsening via Multilevel.c port.

        Builds the hierarchy as :class:`Multilevel` (sparse-
        matrix-based), then converts to the legacy
        ``[{nodes, adj, mapping}]`` shape that
        :meth:`_spring_electrical` consumes.
        """
        from gvpy.engines.layout.sfdp.multilevel import (
            csr_from_adjacency,
            multilevel_new,
            multilevel_to_legacy_levels,
        )
        A = csr_from_adjacency(node_list, adj, self._edge_weight)
        grid = multilevel_new(
            A, max_levels=self.max_levels, seed=self.seed,
        )
        return multilevel_to_legacy_levels(grid, node_list)

    def _build_hierarchy_legacy(self, node_list: list[str],
                                adj: dict[str, list[str]]
                                ) -> list[dict]:
        """Legacy homegrown matching (pre-2026-05-08).

        Kept behind ``GVPY_SFDP_MULTILEVEL=legacy`` for
        comparison.  Uses greedy heaviest-edge matching on
        adjacency dicts; no Galerkin step.
        """
        levels = [{"nodes": node_list, "adj": adj}]

        current_nodes = set(node_list)
        current_adj = adj

        for level in range(self.max_levels):
            N = len(current_nodes)
            if N <= 4:
                break

            # Find maximal independent edge set (greedy matching)
            matched: set[str] = set()
            groups: dict[str, str] = {}  # node → representative
            representatives: set[str] = set()

            # Sort edges by weight (heaviest first)
            edges = []
            for u in current_nodes:
                for v in current_adj.get(u, []):
                    if v in current_nodes and u < v:
                        pair = (min(u, v), max(u, v))
                        w = self._edge_weight.get(pair, 1.0)
                        edges.append((w, u, v))
            edges.sort(reverse=True)

            for w, u, v in edges:
                if u not in matched and v not in matched:
                    matched.add(u)
                    matched.add(v)
                    groups[u] = u
                    groups[v] = u  # v maps to u
                    representatives.add(u)
                    # Average positions
                    lu, lv = self.lnodes.get(u), self.lnodes.get(v)
                    if lu and lv:
                        lu.mass += lv.mass

            # Unmatched nodes become their own representative
            for n in current_nodes:
                if n not in groups:
                    groups[n] = n
                    representatives.add(n)

            # Check coarsening ratio
            if len(representatives) / N > _COARSEN_RATIO:
                break

            # Build coarsened adjacency
            coarse_adj: dict[str, list[str]] = defaultdict(list)
            for rep in representatives:
                coarse_adj[rep]
            for u in current_nodes:
                for v in current_adj.get(u, []):
                    if v in current_nodes:
                        ru, rv = groups[u], groups[v]
                        if ru != rv and rv not in coarse_adj[ru]:
                            coarse_adj[ru].append(rv)
                            coarse_adj[rv].append(ru)

            level_data = {
                "nodes": list(representatives),
                "adj": dict(coarse_adj),
                "mapping": groups,
            }
            levels.append(level_data)

            current_nodes = representatives
            current_adj = dict(coarse_adj)

        return levels

    def _init_positions(self, node_list, N):
        span = self.K * (math.sqrt(N) + 1.0)
        for name in node_list:
            ln = self.lnodes.get(name)
            if ln and not ln.pos_set:
                ln.x = (random.random() - 0.5) * span
                ln.y = (random.random() - 0.5) * span

    # ── Spring-electrical solver ─────────────────

    def _spring_electrical(self, node_list: list[str],
                           adj: dict[str, list[str]],
                           K: float, maxiter: int):
        """Spring-electrical force computation with optional quadtree."""
        N = len(node_list)
        if N < 2:
            return

        step = K
        K2 = K * K
        p = self.repulsive_exp

        for iteration in range(maxiter):
            # Clear displacements
            for name in node_list:
                ln = self.lnodes[name]
                ln.disp_x = 0.0
                ln.disp_y = 0.0

            # Repulsive forces
            if self.use_quadtree and N > 45:
                self._quadtree_repulsion(node_list, K, p)
            else:
                self._allpairs_repulsion(node_list, K, p)

            # Attractive forces
            seen = set()
            for u in node_list:
                for v in adj.get(u, []):
                    if v in set(node_list):
                        pair_key = (min(u, v), max(u, v))
                        if pair_key in seen:
                            continue
                        seen.add(pair_key)
                        pu, pv = self.lnodes[u], self.lnodes[v]
                        dx = pv.x - pu.x
                        dy = pv.y - pu.y
                        dist = math.sqrt(dx * dx + dy * dy)
                        if dist < 0.01:
                            continue
                        edge_len = self._edge_len.get(pair_key, K)
                        w = self._edge_weight.get(pair_key, 1.0)
                        # F_attr = C * d^2 / (K * d_ij)
                        force = _ADAPTIVE_C * w * dist / (K * max(edge_len / 72.0, 0.01))
                        fx, fy = dx / dist * force, dy / dist * force
                        pu.disp_x += fx
                        pu.disp_y += fy
                        pv.disp_x -= fx
                        pv.disp_y -= fy

            # Update positions with adaptive step
            max_disp = 0.0
            for name in node_list:
                ln = self.lnodes[name]
                if ln.pinned:
                    continue
                d = math.sqrt(ln.disp_x ** 2 + ln.disp_y ** 2)
                if d > 0:
                    scale = min(step, d) / d
                    ln.x += ln.disp_x * scale
                    ln.y += ln.disp_y * scale
                    max_disp = max(max_disp, d)

            # Adaptive cooling
            step *= _COOLING
            if max_disp < K * 0.001:
                break

    def _allpairs_repulsion(self, node_list, K, p):
        """O(n^2) repulsive forces."""
        Kp = K ** (1 + p)
        for i in range(len(node_list)):
            pi = self.lnodes[node_list[i]]
            for j in range(i + 1, len(node_list)):
                pj = self.lnodes[node_list[j]]
                dx = pj.x - pi.x
                dy = pj.y - pi.y
                dist2 = dx * dx + dy * dy
                if dist2 < 0.01:
                    dx += random.random() * 0.1
                    dy += random.random() * 0.1
                    dist2 = dx * dx + dy * dy
                dist = math.sqrt(dist2)
                # F_rep = K^(1+p) / dist^(1+p)
                force = Kp / (dist ** (1 + p))
                fx, fy = dx / dist * force, dy / dist * force
                pj.disp_x += fx
                pj.disp_y += fy
                pi.disp_x -= fx
                pi.disp_y -= fy

    # ── Barnes-Hut quadtree ──────────────────────

    def _quadtree_repulsion(self, node_list, K, p):
        """O(n log n) Barnes-Hut repulsive forces."""
        nodes_data = [(self.lnodes[n].x, self.lnodes[n].y,
                        self.lnodes[n].mass) for n in node_list]
        N = len(nodes_data)

        # Compute bounding box
        min_x = min(d[0] for d in nodes_data)
        max_x = max(d[0] for d in nodes_data)
        min_y = min(d[1] for d in nodes_data)
        max_y = max(d[1] for d in nodes_data)
        size = max(max_x - min_x, max_y - min_y, 1.0)

        # Build quadtree
        root = _QTNode(x0=min_x, y0=min_y, size=size)
        for i in range(N):
            self._qt_insert(root, i, nodes_data[i][0], nodes_data[i][1],
                            nodes_data[i][2])

        # Compute forces
        Kp = K ** (1 + p)
        for i in range(N):
            fx, fy = self._qt_force(root, i, nodes_data[i][0],
                                     nodes_data[i][1], Kp, p)
            ln = self.lnodes[node_list[i]]
            ln.disp_x += fx
            ln.disp_y += fy

    def _qt_insert(self, node: _QTNode, idx: int, x: float, y: float,
                   mass: float):
        """Insert a point into the quadtree."""
        if node.mass == 0 and node.is_leaf:
            node.cx, node.cy = x, y
            node.mass = mass
            node.node_idx = idx
            return

        if node.is_leaf and node.mass > 0:
            # Split: move existing point to child
            node.is_leaf = False
            half = node.size / 2
            node.children = [
                _QTNode(x0=node.x0, y0=node.y0, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0, size=half),
                _QTNode(x0=node.x0, y0=node.y0 + half, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0 + half, size=half),
            ]
            # Re-insert old point
            oi = self._qt_quadrant(node, node.cx, node.cy)
            self._qt_insert(node.children[oi], node.node_idx,
                            node.cx, node.cy, node.mass)
            node.node_idx = -1

        # Insert new point
        qi = self._qt_quadrant(node, x, y)
        if not node.children:
            half = node.size / 2
            node.children = [
                _QTNode(x0=node.x0, y0=node.y0, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0, size=half),
                _QTNode(x0=node.x0, y0=node.y0 + half, size=half),
                _QTNode(x0=node.x0 + half, y0=node.y0 + half, size=half),
            ]
        self._qt_insert(node.children[qi], idx, x, y, mass)

        # Update center of mass
        total = node.mass + mass
        node.cx = (node.cx * node.mass + x * mass) / total
        node.cy = (node.cy * node.mass + y * mass) / total
        node.mass = total

    @staticmethod
    def _qt_quadrant(node: _QTNode, x: float, y: float) -> int:
        half = node.size / 2
        mx = node.x0 + half
        my = node.y0 + half
        if x < mx:
            return 2 if y >= my else 0
        else:
            return 3 if y >= my else 1

    def _qt_force(self, node: _QTNode, idx: int, x: float, y: float,
                  Kp: float, p: float) -> tuple[float, float]:
        """Compute repulsive force on point idx from quadtree node."""
        if node.mass == 0:
            return 0.0, 0.0

        dx = node.cx - x
        dy = node.cy - y
        dist2 = dx * dx + dy * dy

        if node.is_leaf:
            if node.node_idx == idx:
                return 0.0, 0.0
            if dist2 < 0.01:
                dx += random.random() * 0.1
                dy += random.random() * 0.1
                dist2 = dx * dx + dy * dy
            dist = math.sqrt(dist2)
            force = Kp * node.mass / (dist ** (1 + p))
            return -dx / dist * force, -dy / dist * force

        # Check Barnes-Hut criterion: size/distance < theta
        dist = math.sqrt(max(dist2, 0.01))
        if node.size / dist < _BH_THETA:
            # Treat as single mass
            force = Kp * node.mass / (dist ** (1 + p))
            return -dx / dist * force, -dy / dist * force

        # Recurse into children
        fx, fy = 0.0, 0.0
        for child in node.children:
            cfx, cfy = self._qt_force(child, idx, x, y, Kp, p)
            fx += cfx
            fy += cfy
        return fx, fy

    # ── Beautify ─────────────────────────────────

    def _beautify_leaves(self, node_list, adj):
        """Arrange leaf nodes (degree 1) in a circle around their neighbor."""
        for name in node_list:
            nbrs = [n for n in adj.get(name, []) if n in set(node_list)]
            if len(nbrs) != 1:
                continue
            parent = self.lnodes[nbrs[0]]
            leaf = self.lnodes[name]
            # Count siblings
            siblings = [n for n in adj.get(nbrs[0], [])
                        if n in set(node_list) and
                        len(adj.get(n, [])) == 1]
            if len(siblings) <= 1:
                continue
            idx = siblings.index(name)
            angle = 2 * math.pi * idx / len(siblings)
            radius = self.K * 0.8
            leaf.x = parent.x + radius * math.cos(angle)
            leaf.y = parent.y + radius * math.sin(angle)

    # ── Overlap removal ──────────────────────────

    def _remove_overlap(self):
        """Bbox-aware iterative overlap removal.

        Operates on every node in ``self.lnodes`` (the
        whole-layout pass invoked from ``layout()`` after the
        per-component layouts settle).  Same axis-aligned bbox
        push logic as :meth:`_sfdp_overlap_pass` — earlier
        versions used a Euclidean ``(w+h)/4`` metric that
        actively *introduced* bbox overlaps along the diagonal
        when nodes were tangent in x but well-separated in y
        (or vice versa), so the fix is to detect overlap on the
        bbox axes themselves and push along the smaller-
        penetration axis only.
        """
        names = list(self.lnodes.keys())
        if len(names) < 2:
            return
        self._sfdp_overlap_pass(names)

    # ── Cluster-aware output (mirrors FdpLayout) ────────────────

    def _to_json(self) -> dict:
        result = super()._to_json()
        # Emit cluster bboxes for the SVG renderer / JSON
        # consumers.  Format matches dot's ``_to_json`` so the
        # shared ``_render_cluster`` consumes it directly.
        if self._clusters:
            clusters_json = []
            for cl in self._clusters:
                if cl.bb == (0.0, 0.0, 0.0, 0.0):
                    continue
                cl_entry: dict = {
                    "name": cl.name,
                    "label": cl.label,
                    "bb": [round(v, 2) for v in cl.bb],
                    "nodes": cl.nodes,
                }
                cl_entry.update(cl.attrs)
                clusters_json.append(cl_entry)
            if clusters_json:
                result["clusters"] = clusters_json
                # Expand graph bb to include cluster bboxes so
                # the SVG viewBox doesn't clip cluster outlines.
                if "graph" in result and "bb" in result["graph"]:
                    gx1, gy1, gx2, gy2 = result["graph"]["bb"]
                    for cl in self._clusters:
                        if cl.bb == (0.0, 0.0, 0.0, 0.0):
                            continue
                        cx1, cy1, cx2, cy2 = cl.bb
                        gx1 = min(gx1, cx1)
                        gy1 = min(gy1, cy1)
                        gx2 = max(gx2, cx2)
                        gy2 = max(gy2, cy2)
                    result["graph"]["bb"] = [
                        round(gx1, 2), round(gy1, 2),
                        round(gx2, 2), round(gy2, 2),
                    ]
        return result

    def _write_back(self):
        """Extends the base ``_write_back`` (nodes + edges +
        root bb) by setting ``bb=`` on every cluster subgraph
        for ``-Tdot`` round-trip.  See FdpLayout._write_back
        for the same pattern."""
        super()._write_back()
        if not self._clusters:
            return
        cluster_subgraphs: dict[str, object] = {}

        def _index(g):
            for sub_name, sub in g.subgraphs.items():
                if sub_name.startswith("cluster"):
                    cluster_subgraphs[sub_name] = sub
                _index(sub)

        _index(self.graph)
        for cl in self._clusters:
            if cl.bb == (0.0, 0.0, 0.0, 0.0):
                continue
            sub = cluster_subgraphs.get(cl.name)
            if sub is None:
                continue
            x1, y1, x2, y2 = cl.bb
            sub.attr_record["bb"] = (
                f"{round(x1, 2)},{round(y1, 2)},"
                f"{round(x2, 2)},{round(y2, 2)}"
            )

    # ── deriveGraph solver bridges ───────────────────────────────
    #
    # The fdp ``derive_graph_layout`` orchestrates cluster-aware
    # layout but defers the per-scope force pass to a callback.
    # These two methods adapt sfdp's existing
    # ``_spring_electrical`` + simple overlap loop to the
    # ``(layout, node_list, edges, K, maxiter)`` callback shape.

    def _sfdp_force_solver(self, _layout, node_list, edges,
                           K: float, maxiter: int) -> None:
        """Run sfdp's force pass on a subset of ``self.lnodes``.

        ``edges`` is the deriveGraph's lifted edge list
        ``[(tail, head, length, weight)]`` — convert to the
        adjacency form ``_spring_electrical`` expects.
        """
        if len(node_list) < 2:
            return
        # Initialise positions for any fresh proxy / member.
        self._init_positions(node_list, len(node_list))
        # Build adjacency for this subset.
        adj: dict[str, list[str]] = {n: [] for n in node_list}
        for t, h, _len, _wt in edges:
            if t in adj and h in adj:
                if h not in adj[t]:
                    adj[t].append(h)
                if t not in adj[h]:
                    adj[h].append(t)
        # Run the existing multilevel-aware solver.  For the
        # derived graph (proxies + free nodes at one scope) the
        # node count is typically small and quadtree drops out;
        # the solver still produces a valid F-R layout.
        self._spring_electrical(node_list, adj, K, maxiter)

    def _sfdp_overlap_solver(self, _layout, K: float, sep: float,
                             maxiter: int,
                             node_subset: list[str]) -> None:
        """Bbox-aware overlap removal restricted to
        ``node_subset``.

        Bridges to fdp's ``xlayout`` (with the ``node_subset``
        parameter added in DONE §4.F-derivegraph) — properly
        detects axis-aligned bbox overlap.  Sfdp's homegrown
        ``_remove_overlap`` uses an incorrect distance metric
        (``(width+height)/4`` instead of axis-projected
        overlap), so it can't separate cluster proxies whose
        bboxes are 100-200 pt wide.
        """
        if len(node_subset) < 2:
            return
        from gvpy.engines.layout.fdp.xlayout import xlayout as _fdp_xlayout
        _fdp_xlayout(self, K, sep, maxiter, tries=3,
                     node_subset=node_subset)

    # Shared from LayoutEngine: _compute_node_size, _init_common_attrs,
    # _apply_normalize, _apply_rotation, _apply_center,
    # _compute_label_positions, _clip_to_boundary, _find_components,
    # _pack_components_lr, _write_back, _to_json
